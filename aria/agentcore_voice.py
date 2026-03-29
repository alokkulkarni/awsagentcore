"""ARIA WebSocket Voice Agent — Nova Sonic 2 S2S for Amazon Bedrock AgentCore Runtime.

This module provides ``ARIAWebSocketVoiceSession``, a Nova Sonic 2 bidirectional
stream session that uses a WebSocket connection for audio I/O instead of local
PyAudio devices.  It is designed for the AgentCore Runtime ``/ws`` endpoint where:

  Client (mobile / web)  ←──WebSocket──→  AgentCore Runtime /ws
                                                    │
                                   InvokeModelWithBidirectionalStream
                                                    │
                                          Nova Sonic 2 (Bedrock)

**WebSocket message protocol**

Client → Server (text):
    {"type": "session.config", "authenticated": true, "customer_id": "CUST-001"}
    {"type": "session.end"}

Client → Server (binary):
    Raw 16 kHz 16-bit mono PCM audio (1 024 frames = 2 048 bytes per chunk)

Server → Client (text):
    {"type": "session.started"}
    {"type": "transcript.user",  "text": "..."}
    {"type": "transcript.aria",  "text": "..."}
    {"type": "session.ended"}
    {"type": "error", "message": "..."}

Server → Client (binary):
    Raw 24 kHz 16-bit mono PCM audio (ARIA voice output)

This module intentionally does NOT import ``pyaudio``.
For local device-based voice, see ``aria/voice_agent.py``.
"""

from __future__ import annotations

import asyncio
import base64
import collections
import hashlib
import inspect
import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Optional

from aria.audit_manager import audit as _audit

logger = logging.getLogger("aria.voice.ws")

# ---------------------------------------------------------------------------
# Nova Sonic 2 constants  (identical to voice_agent.py)
# ---------------------------------------------------------------------------
_NOVA_SONIC_REGIONS = frozenset({"us-east-1", "eu-north-1", "ap-northeast-1"})
_NOVA_SONIC_MODEL_ID = "amazon.nova-2-sonic-v1:0"

_INPUT_SAMPLE_RATE  = 16_000   # client mic → Nova Sonic
_OUTPUT_SAMPLE_RATE = 24_000   # Nova Sonic → client speaker

_FAREWELL_PHRASES = frozenset({
    "goodbye", "good bye", "bye", "bye bye", "farewell",
    "that's all", "that is all", "that's everything", "nothing else",
    "thank you goodbye", "thanks goodbye", "thank you bye",
    "good night", "goodnight", "have a good day",
    "see you", "see ya", "take care", "no more help",
    "done for today", "all done", "all good bye",
    "stop conversation", "end the session",
})

_NOVA_VOICE  = os.getenv("NOVA_SONIC_VOICE", "tiffany")
_ENDPOINTING = os.getenv("NOVA_SONIC_ENDPOINTING", "HIGH")
if _ENDPOINTING not in {"HIGH", "MEDIUM", "LOW"}:
    _ENDPOINTING = "HIGH"


# ---------------------------------------------------------------------------
# Region / credential helpers  (identical to voice_agent.py)
# ---------------------------------------------------------------------------

def _resolve_nova_region() -> str:
    for var in ("NOVA_SONIC_REGION", "AWS_REGION"):
        region = os.getenv(var, "").strip()
        if region in _NOVA_SONIC_REGIONS:
            return region
        if region:
            logger.warning("Region '%s' not supported by Nova Sonic 2; falling back.", region)
    return "eu-north-1"


def _build_boto_session(region: str):
    import boto3
    from botocore.exceptions import NoCredentialsError, ClientError

    profile  = os.getenv("AWS_PROFILE") or os.getenv("AWS_DEFAULT_PROFILE")
    role_arn = os.getenv("AWS_ROLE_ARN", "").strip()

    session = (
        boto3.Session(profile_name=profile, region_name=region)
        if profile
        else boto3.Session(region_name=region)
    )

    try:
        identity = session.client("sts").get_caller_identity()
        logger.info("Nova Sonic credentials OK | arn=%s", identity.get("Arn"))
    except (NoCredentialsError, ClientError) as exc:
        logger.error("AWS credential check failed for Nova Sonic: %s", exc)
        raise

    if role_arn:
        sts     = session.client("sts")
        assumed = sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName=os.getenv("AWS_ROLE_SESSION_NAME", "aria-nova-sonic"),
        )
        creds   = assumed["Credentials"]
        session = boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=region,
        )

    return session


# ---------------------------------------------------------------------------
# Voice system prompt  (identical to voice_agent.py _build_voice_system_prompt)
# ---------------------------------------------------------------------------

def _build_voice_system_prompt(
    authenticated: bool, customer_id: Optional[str], session_id: str
) -> str:
    from aria.system_prompt import ARIA_SYSTEM_PROMPT

    _EMPATHY_BLOCK = (
        "EMPATHY & VULNERABILITY — VOICE MODE (MANDATORY):\n"
        "Voice is the most personal channel. Customers can hear warmth and care — use that.\n\n"
        "EMPATHY TRIGGERS — acknowledge the customer's feelings FIRST, then act:\n"
        "  Lost or stolen card:\n"
        "    → 'I'm really sorry to hear that — let me get that sorted for you right away.'\n"
        "       Then proceed immediately to identify the card and initiate the block.\n"
        "  Suspected fraud or unexpected transaction:\n"
        "    → 'That must be really worrying. Let me look into that straightaway.'\n"
        "  High balance, missed payment, or financial concern:\n"
        "    → Acknowledge calmly without judgement: 'I understand — let me pull up the details\n"
        "       so we can go through this together.'\n"
        "  Bereavement or account of a deceased person:\n"
        "    → Speak very gently. Pause. Offer the bereavement specialist team before doing\n"
        "       anything else: 'I'm so sorry for your loss. I'd like to make sure you get the\n"
        "       right support — would it be alright if I connected you with our specialist team?'\n"
        "  Financial hardship or difficulty paying:\n"
        "    → 'I hear you, and we want to make sure you get the right support. Let me see\n"
        "       what options are available for you.'\n"
        "  Customer sounds distressed, upset, or overwhelmed:\n"
        "    → Pause before responding. Speak more slowly. Acknowledge: 'Take your time —\n"
        "       there's no rush at all.' Do NOT rush to the task.\n\n"
        "VULNERABILITY DETECTION — listen for spoken cues, not just the profile flag:\n"
        "  Distress or panic:\n"
        "    → Slow your speaking pace. Use very short sentences. Acknowledge and reassure.\n"
        "  Confusion or repetition:\n"
        "    → Use simplest possible language. Confirm understanding after each step.\n"
        "  Third-party pressure:\n"
        "    → Do NOT proceed with irreversible actions. Escalate to specialist.\n"
        "  Mid-call disclosure of vulnerability:\n"
        "    → Adapt immediately. Offer specialist support before continuing.\n\n"
        "WARM ACKNOWLEDGMENT RULE:\n"
        "  On any distressing call — say something warm and human BEFORE any task or tool call.\n\n"
    )

    if authenticated and customer_id:
        preamble = (
            "=== VOICE SESSION — CRITICAL OPERATING RULES ===\n\n"
            "You are ARIA, Meridian Bank's voice banking assistant, on a LIVE call.\n\n"
            "SESSION CONTEXT:\n"
            f"- Channel: voice (WebSocket audio stream via AgentCore Runtime)\n"
            f"- Auth state: authenticated\n"
            f"- Customer ID: {customer_id}\n"
            f"- Session ID (use for all tool calls requiring session_id): {session_id}\n"
            "- The caller is already verified. Do NOT ask them to re-authenticate.\n"
            f"- Call get_customer_details(\"{customer_id}\") immediately, then greet by preferred_name.\n\n"
            + _EMPATHY_BLOCK
            + "CARD QUERIES — VOICE OVERRIDE (MANDATORY):\n"
            "After get_customer_details, you know every card_last_four from the profile.\n"
            "  1. NEVER ask the customer to provide or confirm digits you already have.\n"
            "  2. NEVER call pii_vault_retrieve for card_last_four — use profile values directly.\n"
            "  3. ONE card of requested type → use its card_last_four directly. Tell the customer.\n"
            "  4. MULTIPLE cards of same type → list scheme + last_four, ask which one.\n"
            "  5. 'Confirm the card' = TELL the customer which card you are using.\n\n"
            "MANDATORY SESSION RULES:\n"
            "1. Fetch customer profile first, then greet by name.\n"
            "2. Session stays open until the caller says goodbye.\n"
            "3. You are on VOICE — speak naturally. Never read full URLs or full card numbers.\n\n"
            "=== END VOICE RULES — BANKING INSTRUCTIONS FOLLOW ===\n\n"
        )
    else:
        preamble = (
            "=== VOICE SESSION — CRITICAL OPERATING RULES ===\n\n"
            "You are ARIA, Meridian Bank's voice banking assistant, on a LIVE call.\n\n"
            "SESSION CONTEXT:\n"
            "- Channel: voice (WebSocket audio stream via AgentCore Runtime)\n"
            "- Auth state: unauthenticated\n"
            f"- Session ID (use for all tool calls requiring session_id): {session_id}\n"
            "- Greet the caller warmly as ARIA from Meridian Bank and begin identity verification.\n\n"
            + _EMPATHY_BLOCK
            + "MANDATORY RULES:\n"
            "1. Session stays open until the caller says goodbye.\n"
            "2. You are on VOICE — speak naturally. No full URLs or card numbers.\n\n"
            "=== END VOICE RULES — BANKING INSTRUCTIONS FOLLOW ===\n\n"
        )
    return preamble + ARIA_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# WebSocket Voice Session
# ---------------------------------------------------------------------------

class ARIAWebSocketVoiceSession:
    """Nova Sonic 2 S2S session bridged over a WebSocket connection.

    The WebSocket client (mobile app / browser) supplies microphone audio as
    binary messages and receives speaker audio as binary messages.  All tool
    calls are executed server-side using the same Strands tool functions as
    the chat agent.

    Usage (inside an AgentCore @app.websocket handler)::

        @app.websocket
        async def voice_handler(websocket, context):
            session = ARIAWebSocketVoiceSession(
                session_id=context.session_id or str(uuid.uuid4()),
                websocket=websocket,
            )
            await session.run()
    """

    _SESSION_START_TMPL = json.dumps({
        "event": {
            "sessionStart": {
                "inferenceConfiguration": {
                    "maxTokens": int(os.getenv("NOVA_SONIC_MAX_TOKENS", "2048")),
                    "topP":      float(os.getenv("NOVA_SONIC_TOP_P", "0.9")),
                    "temperature": float(os.getenv("NOVA_SONIC_TEMPERATURE", "0.7")),
                },
                "turnDetectionConfiguration": {
                    "endpointingSensitivity": _ENDPOINTING,
                },
            }
        }
    })

    def __init__(self, session_id: str, websocket: Any) -> None:
        self.session_id = session_id
        self.websocket  = websocket

        # Nova Sonic connection
        region            = _resolve_nova_region()
        boto_session      = _build_boto_session(region)
        self._region      = region
        self._boto_session = boto_session
        self._model_id    = _NOVA_SONIC_MODEL_ID
        self._client      = None
        self._stream      = None

        # Session config (populated from first WebSocket text message)
        self._authenticated: bool         = False
        self._customer_id:   Optional[str] = None

        # Unique IDs for this Nova Sonic session
        self._prompt_name      = str(uuid.uuid4())
        self._sys_content_name = str(uuid.uuid4())
        self._audio_content    = str(uuid.uuid4())

        # Response state
        self._display_assistant_text = False
        self._role: str = ""
        self._aria_buf: list[str] = []

        # Lifecycle flags
        self.is_active           = False
        self._farewell_detected  = False
        self._session_ended      = False
        self._audio_input_closed = False

        # Pending tool call
        self._tool_name    = ""
        self._tool_use_id  = ""
        self._tool_content = ""

        # Tool map
        from aria.tools import ALL_TOOLS
        self._tools    = ALL_TOOLS
        self._tool_map = {t.tool_name: t for t in ALL_TOOLS}

        # Audio output queue (Nova Sonic → client)
        self._audio_output_queue: asyncio.Queue[bytes] = asyncio.Queue()

        # Hashes of recently-sent audio chunks — used to ignore AgentCore proxy echoes
        self._sent_audio_hashes: collections.deque = collections.deque(maxlen=20)

        # Memory: last user utterance buffered until ARIA's response is flushed
        self._last_user_text: Optional[str] = None

        # Transcript — populated during session, saved on close
        from aria.transcript_manager import TranscriptManager
        self._transcript: Optional[TranscriptManager] = None  # set after config received

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Accept the WebSocket, read config, run the voice session."""
        await self.websocket.accept()

        # Read the first text message — must be session.config
        try:
            raw = await asyncio.wait_for(self.websocket.receive_text(), timeout=10.0)
            config = json.loads(raw)
        except asyncio.TimeoutError:
            await self._ws_send_text({"type": "error", "message": "No session.config received within 10s."})
            return
        except Exception as exc:
            await self._ws_send_text({"type": "error", "message": f"Invalid config: {exc}"})
            return

        if config.get("type") != "session.config":
            await self._ws_send_text({"type": "error", "message": "First message must be type=session.config"})
            return

        self._authenticated = bool(config.get("authenticated", False))
        self._customer_id   = config.get("customer_id") or None

        # Initialise transcript now that we know the customer
        from aria.transcript_manager import TranscriptManager
        self._transcript = TranscriptManager(
            session_id=self.session_id,
            customer_id=self._customer_id,
            channel="agentcore-voice",
            authenticated=self._authenticated,
        )

        logger.info(
            "WS voice session starting: session_id=%s authenticated=%s customer_id=%s",
            self.session_id, self._authenticated, self._customer_id,
        )

        system_prompt = _build_voice_system_prompt(
            self._authenticated, self._customer_id, self.session_id
        )

        # Inject prior conversation history from AgentCore Memory (no-op if not configured)
        try:
            from aria import memory_client as _mc
            actor_id = self._customer_id or "anonymous"
            history = _mc.get_recent_turns(actor_id, self.session_id, k=5)
            if history:
                lines = []
                for msg in history:
                    role_label = "Customer" if msg["role"] == "user" else "ARIA"
                    lines.append(f"{role_label}: {msg['content']}")
                history_block = (
                    "\n=== RECENT CONVERSATION HISTORY (for context) ===\n"
                    + "\n".join(lines)
                    + "\n=== END HISTORY ===\n"
                )
                system_prompt = history_block + system_prompt
                logger.debug("Injected %d memory messages into voice system prompt", len(history))
        except Exception as _mem_exc:
            logger.warning("Could not load voice session memory: %s", _mem_exc)

        try:
            await self._run_session(system_prompt)
        except Exception as exc:
            logger.error("Voice session error: %s", exc, exc_info=True)
            await self._ws_send_text({"type": "error", "message": "Voice session error — session ended."})
        finally:
            if self._transcript:
                self._transcript.save()
            await self._ws_send_text({"type": "session.ended"})

    # ------------------------------------------------------------------
    # Nova Sonic session lifecycle
    # ------------------------------------------------------------------

    async def _run_session(self, system_prompt: str) -> None:
        from aws_sdk_bedrock_runtime.client import BedrockRuntimeClient
        from aws_sdk_bedrock_runtime.config import Config as SdkConfig, HTTPConfig, Endpoint
        from aws_sdk_bedrock_runtime.models import (
            InvokeModelWithBidirectionalStreamOperationInput,
        )
        from smithy_aws_core.credentials_resolvers.environment import (
            EnvironmentCredentialsResolver,
        )
        from smithy_core.aio.interfaces.retries import RetryErrorType
        import smithy_aws_core.aio.auth.sigv4 as _sigv4

        import boto3

        # Build static credentials resolver from boto3 session
        frozen = self._boto_session.get_credentials().get_frozen_credentials()

        class _StaticResolver:
            async def get_identity(self, *, properties=None):
                class _Id:
                    access_key_id     = frozen.access_key
                    secret_access_key = frozen.secret_key
                    session_token     = frozen.token
                return _Id()

        cfg = SdkConfig(
            endpoint=Endpoint(url=f"https://bedrock-runtime.{self._region}.amazonaws.com"),
            http_config=HTTPConfig(connection_timeout=30, read_timeout=600),
            region=self._region,
            credentials_resolver=_StaticResolver(),
            auth_schemes=[_sigv4.SigV4AuthScheme()],
        )

        self._client = BedrockRuntimeClient(config=cfg)

        self._stream = await self._client.invoke_model_with_bidirectional_stream(
            InvokeModelWithBidirectionalStreamOperationInput(model_id=self._model_id)
        )

        self.is_active = True

        # Send sessionStart
        await self._send_raw(self._SESSION_START_TMPL)

        # Prompt + system prompt
        await self._send_event({"event": {"promptStart": {"promptName": self._prompt_name}}})
        await self._send_event({
            "event": {
                "contentStart": {
                    "promptName":   self._prompt_name,
                    "contentName":  self._sys_content_name,
                    "type":         "TEXT",
                    "interactive":  False,
                    "role":         "SYSTEM",
                    "textInputConfiguration": {"mediaType": "text/plain"},
                }
            }
        })
        await self._send_event({
            "event": {
                "textInput": {
                    "promptName":  self._prompt_name,
                    "contentName": self._sys_content_name,
                    "content":     system_prompt,
                }
            }
        })
        await self._send_event({
            "event": {
                "contentEnd": {
                    "promptName":  self._prompt_name,
                    "contentName": self._sys_content_name,
                }
            }
        })

        # Audio input block
        await self._send_event({
            "event": {
                "contentStart": {
                    "promptName":  self._prompt_name,
                    "contentName": self._audio_content,
                    "type":        "AUDIO",
                    "interactive": True,
                    "role":        "USER",
                    "audioInputConfiguration": {
                        "mediaType":    "audio/lpcm",
                        "sampleRateHertz":    _INPUT_SAMPLE_RATE,
                        "sampleSizeBits":     16,
                        "channelCount":       1,
                        "audioType":          "SPEECH",
                        "encoding":           "base64",
                    },
                }
            }
        })

        await self._ws_send_text({"type": "session.started"})
        logger.info("Nova Sonic session started (session_id=%s)", self.session_id)

        # Run all tasks concurrently
        tasks = await asyncio.gather(
            self._receive_client_audio(),
            self._process_nova_sonic_events(),
            self._send_audio_to_client(),
            return_exceptions=True,
        )
        for t in tasks:
            if isinstance(t, Exception) and not isinstance(t, asyncio.CancelledError):
                logger.warning("Voice session task ended with: %s", t)

        await self._end_session()

    # ------------------------------------------------------------------
    # Audio bridge: client → Nova Sonic
    # ------------------------------------------------------------------

    async def _receive_client_audio(self) -> None:
        """Receive binary PCM audio from WebSocket client, forward to Nova Sonic."""
        try:
            while self.is_active:
                try:
                    msg = await asyncio.wait_for(
                        self.websocket.receive(), timeout=0.1
                    )
                except asyncio.TimeoutError:
                    continue

                # Client requested session end
                if msg.get("type") == "websocket.disconnect":
                    logger.info("WebSocket disconnected by client")
                    self.is_active = False
                    break

                if msg.get("type") == "websocket.receive":
                    if "text" in msg:
                        try:
                            ctrl = json.loads(msg["text"])
                            if ctrl.get("type") == "session.end":
                                logger.info("Client requested session.end")
                                self.is_active = False
                                break
                        except json.JSONDecodeError:
                            pass
                    elif "bytes" in msg and msg["bytes"] and not self._farewell_detected:
                        # Ignore frames echoed back by the AgentCore WebSocket proxy
                        frame = msg["bytes"]
                        if hashlib.sha256(frame).digest() in self._sent_audio_hashes:
                            logger.debug("Ignoring echoed audio frame (%d bytes)", len(frame))
                            continue
                        # Forward raw PCM as base64 audio chunk to Nova Sonic
                        blob = base64.b64encode(frame).decode("utf-8")
                        await self._send_event({
                            "event": {
                                "audioInput": {
                                    "promptName":  self._prompt_name,
                                    "contentName": self._audio_content,
                                    "content":     blob,
                                }
                            }
                        })
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("receive_client_audio error: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # Audio bridge: Nova Sonic → client
    # ------------------------------------------------------------------

    async def _send_audio_to_client(self) -> None:
        """Drain audio output queue and send PCM binary to WebSocket client."""
        try:
            while self.is_active or not self._audio_output_queue.empty():
                try:
                    chunk = await asyncio.wait_for(
                        self._audio_output_queue.get(), timeout=0.2
                    )
                    await self.websocket.send_bytes(chunk)
                    # Record hash so echoed-back frames can be ignored in _receive_client_audio
                    self._sent_audio_hashes.append(hashlib.sha256(chunk).digest())
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("send_audio_to_client error: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # Nova Sonic event processor
    # ------------------------------------------------------------------

    async def _process_nova_sonic_events(self) -> None:
        try:
            async for output in self._stream.await_output():
                try:
                    result = await output[1].receive()
                    if result and result.value and result.value.bytes_:
                        event = json.loads(result.value.bytes_.decode("utf-8"))
                        await self._handle_event(event)
                except Exception as exc:
                    logger.debug("Nova Sonic event receive error: %s", exc)
                if not self.is_active:
                    break
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Nova Sonic event processing error: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # Event handler (mirrors ARIANovaSonicSession._handle_event)
    # ------------------------------------------------------------------

    async def _handle_event(self, event: dict) -> None:  # noqa: C901
        # --- textOutput ---
        if "textOutput" in event:
            to = event["textOutput"]
            role    = to.get("role", "")
            content = to.get("content", "")

            if role == "USER":
                # User transcript (SPECULATIVE stage only)
                text = content.strip()
                if text:
                    logger.info("Customer said: %s", text)
                    await self._ws_send_text({"type": "transcript.user", "text": text})
                    if self._transcript:
                        self._transcript.add_turn("Customer", text)
                    # Buffer for memory save when ARIA's response is complete
                    self._last_user_text = text
                    low = text.lower()
                    if any(ph in low for ph in _FAREWELL_PHRASES):
                        self._farewell_detected = True
                        logger.info("Farewell detected: '%s'", text)
                return

            if role == "ASSISTANT":
                # Barge-in?
                try:
                    parsed = json.loads(content)
                    if parsed.get("interrupted"):
                        await self._handle_interrupt()
                        return
                except (json.JSONDecodeError, AttributeError):
                    pass

                # Show text from SPECULATIVE stage only
                gen_stage = (
                    event.get("textOutput", {})
                    .get("additionalModelFields", {})
                    .get("generationStage", "")
                    if isinstance(event.get("textOutput"), dict) else ""
                )
                if not gen_stage:
                    # Try nested additionalModelFields
                    gen_stage = to.get("additionalModelFields", {}).get("generationStage", "")

                if gen_stage == "SPECULATIVE" or not gen_stage:
                    self._aria_buf.append(content)
                return

        # --- contentStart: track generation stage ---
        if "contentStart" in event:
            cs = event["contentStart"]
            amf = cs.get("additionalModelFields", {})
            if isinstance(amf, str):
                try:
                    amf = json.loads(amf)
                except json.JSONDecodeError:
                    amf = {}
            gen_stage = amf.get("generationStage", "")
            self._display_assistant_text = (gen_stage == "SPECULATIVE")
            self._role = cs.get("role", "")
            return

        # --- audioOutput: queue for client ---
        if "audioOutput" in event:
            audio_b64 = event["audioOutput"].get("content", "")
            if audio_b64:
                audio_bytes = base64.b64decode(audio_b64)
                await self._audio_output_queue.put(audio_bytes)
            return

        # --- toolUse: accumulate ---
        if "toolUse" in event:
            tu = event["toolUse"]
            self._tool_name    = tu.get("toolName", "")
            self._tool_use_id  = tu.get("toolUseId", "")
            self._tool_content = tu.get("content", "{}")
            logger.info("Tool requested: %s (id=%s)", self._tool_name, self._tool_use_id)
            return

        # --- contentEnd: flush text or execute tool ---
        if "contentEnd" in event:
            ce = event["contentEnd"]
            if ce.get("type") == "TOOL":
                await self._dispatch_tool()
            else:
                await self._flush_aria()
            return

        # --- completionEnd: flush remaining, end on farewell ---
        if "completionEnd" in event:
            await self._flush_aria()
            if self._farewell_detected:
                logger.info("Farewell response complete — ending session.")
                self.is_active = False
                await self._close_audio_input()
            return

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _flush_aria(self) -> None:
        if self._aria_buf:
            text = " ".join(self._aria_buf).strip()
            self._aria_buf.clear()
            if text:
                logger.info("ARIA: %s", text)
                await self._ws_send_text({"type": "transcript.aria", "text": text})
                if self._transcript:
                    self._transcript.add_turn("ARIA", text)
                # Persist turn to AgentCore Memory (no-op if AGENTCORE_MEMORY_ID not set)
                if self._last_user_text:
                    try:
                        from aria import memory_client as _mc
                        actor_id = self._customer_id or "anonymous"
                        _mc.save_turn(actor_id, self.session_id, self._last_user_text, text)
                        logger.debug("Saved voice turn to memory (session=%s)", self.session_id)
                    except Exception as _mem_exc:
                        logger.warning("Could not save voice turn to memory: %s", _mem_exc)
                    finally:
                        self._last_user_text = None

    async def _handle_interrupt(self) -> None:
        """Handle barge-in: drain audio queue, clear ARIA buffer."""
        cleared = 0
        while True:
            try:
                self._audio_output_queue.get_nowait()
                cleared += 1
            except asyncio.QueueEmpty:
                break
        self._aria_buf.clear()
        logger.info("Barge-in: cleared %d queued audio chunks", cleared)
        await self._ws_send_text({"type": "interrupt"})

    # ------------------------------------------------------------------
    # Tool execution (identical to ARIANovaSonicSession)
    # ------------------------------------------------------------------

    async def _dispatch_tool(self) -> None:
        result_str = await self._execute_tool(
            self._tool_name, self._tool_use_id, self._tool_content
        )
        tool_content_name = str(uuid.uuid4())

        await self._send_event({
            "event": {
                "contentStart": {
                    "promptName":  self._prompt_name,
                    "contentName": tool_content_name,
                    "interactive": False,
                    "type":        "TOOL",
                    "role":        "TOOL",
                    "toolResultInputConfiguration": {
                        "toolUseId": self._tool_use_id,
                        "type":      "TEXT",
                        "textInputConfiguration": {"mediaType": "text/plain"},
                    },
                }
            }
        })
        await self._send_event({
            "event": {
                "toolResult": {
                    "promptName":  self._prompt_name,
                    "contentName": tool_content_name,
                    "content":     result_str,
                    "role":        "TOOL",
                }
            }
        })
        await self._send_event({
            "event": {
                "contentEnd": {
                    "promptName":  self._prompt_name,
                    "contentName": tool_content_name,
                }
            }
        })

    async def _execute_tool(self, name: str, use_id: str, content_str: str) -> str:
        try:
            args: dict = json.loads(content_str) if content_str else {}
        except json.JSONDecodeError:
            args = {}

        tool = self._tool_map.get(name)
        if tool is None:
            logger.warning("Unknown tool requested: %s", name)
            await _audit.async_record(
                tool_name=name, customer_id=self._customer_id,
                session_id=self.session_id, channel="agentcore-voice",
                authenticated=self._authenticated, parameters=args,
                outcome="FAILURE", error_message="Tool not found",
            )
            return json.dumps({"error": f"Tool '{name}' not found."})

        sig = inspect.signature(tool._tool_func)
        if "session_id" in sig.parameters and "session_id" not in args:
            args["session_id"] = self.session_id

        logger.info("Executing tool %s", name)
        try:
            result = await asyncio.to_thread(tool._tool_func, **args)
            await _audit.async_record(
                tool_name=name, customer_id=self._customer_id,
                session_id=self.session_id, channel="agentcore-voice",
                authenticated=self._authenticated,
                parameters={k: v for k, v in args.items() if k != "session_id"},
                outcome="SUCCESS",
            )
            return json.dumps(result, default=str)
        except Exception as exc:
            await _audit.async_record(
                tool_name=name, customer_id=self._customer_id,
                session_id=self.session_id, channel="agentcore-voice",
                authenticated=self._authenticated,
                parameters={k: v for k, v in args.items() if k != "session_id"},
                outcome="FAILURE", error_message=str(exc),
            )
            logger.error("Tool %s failed: %s", name, exc, exc_info=True)
            return json.dumps({"error": str(exc)})

    # ------------------------------------------------------------------
    # Nova Sonic stream helpers
    # ------------------------------------------------------------------

    async def _send_event(self, event: dict) -> None:
        await self._send_raw(json.dumps(event))

    async def _send_raw(self, raw: str) -> None:
        if self._stream is None:
            return
        from aws_sdk_bedrock_runtime.models import (
            InvokeModelWithBidirectionalStreamInputChunk,
            BidirectionalInputPayloadPart,
        )
        chunk = InvokeModelWithBidirectionalStreamInputChunk(
            value=BidirectionalInputPayloadPart(bytes_=raw.encode("utf-8"))
        )
        await self._stream.input_stream.send(chunk)

    async def _close_audio_input(self) -> None:
        if self._audio_input_closed:
            return
        self._audio_input_closed = True
        try:
            await self._send_event({
                "event": {
                    "contentEnd": {
                        "promptName":  self._prompt_name,
                        "contentName": self._audio_content,
                    }
                }
            })
        except Exception:
            pass

    async def _end_session(self) -> None:
        if self._session_ended:
            return
        self._session_ended = True
        try:
            await self._close_audio_input()
            await self._send_event({
                "event": {"promptEnd": {"promptName": self._prompt_name}}
            })
            await self._send_event({"event": {"sessionEnd": {}}})
            if self._stream:
                await self._stream.input_stream.close()
        except Exception as exc:
            logger.debug("Session end cleanup: %s", exc)

    # ------------------------------------------------------------------
    # WebSocket helpers
    # ------------------------------------------------------------------

    async def _ws_send_text(self, payload: dict) -> None:
        try:
            await self.websocket.send_text(json.dumps(payload))
        except Exception as exc:
            logger.debug("WS send_text failed: %s", exc)
