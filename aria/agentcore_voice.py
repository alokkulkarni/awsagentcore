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

_CHANNELS    = 1
_NOVA_VOICE  = os.getenv("NOVA_SONIC_VOICE", "tiffany")
_ENDPOINTING = os.getenv("NOVA_SONIC_ENDPOINTING", "HIGH")
if _ENDPOINTING not in {"HIGH", "MEDIUM", "LOW"}:
    _ENDPOINTING = "HIGH"

# Nova Sonic hard limit: 600 s of cumulative input audio per stream invocation.
# The watchdog silently renews the stream at _SESSION_RENEW_S — the user never notices.
_SESSION_MAX_S   = 600
_SESSION_RENEW_S = 560   # 9 min 20 s — trigger silent renewal before the 600 s kill


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
        self._generation_stage: str = ""   # SPECULATIVE | FINAL | "" (from contentStart)

        # Lifecycle flags
        self.is_active           = False
        self._farewell_detected  = False
        self._session_ended      = False
        self._audio_input_closed = False

        # Stream renewal (transparent 600 s session renewal)
        self._stream_renewing:    bool  = False
        self._stream_generation:  int   = 0
        self._session_warned:     bool  = False
        self._session_start_time: float = 0.0
        self._system_prompt:      str   = ""

        # Conversation history — stored across renewals, injected into new streams.
        # Only FINAL assistant text (not SPECULATIVE) is kept.
        # Byte limits match the official AWS session-continuation sample.
        self._conversation_history: list[dict] = []   # [{role, text}, ...]
        _MAX_TURN_BYTES  = 1024    # max bytes per individual turn
        _MAX_HIST_BYTES  = 40_960  # ~40 KB total history budget
        self._max_turn_bytes = _MAX_TURN_BYTES
        self._max_hist_bytes = _MAX_HIST_BYTES

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

        # Set to True when a barge-in is in-flight: blocks new audio from being
        # queued or sent to the client until Nova Sonic confirms the interrupt.
        self._barge_in_pending: bool = False

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
        logger.info("WS run() entered — calling accept()")
        await self.websocket.accept()
        logger.info("WS accepted — waiting for session.config")

        # Read the first text message — must be session.config
        try:
            raw = await asyncio.wait_for(self.websocket.receive_text(), timeout=10.0)
            config = json.loads(raw)
        except asyncio.TimeoutError:
            logger.warning("session.config not received within 10 s (session_id=%s)", self.session_id)
            await self._ws_send_text({"type": "error", "message": "No session.config received within 10s."})
            return
        except Exception as exc:
            logger.error("Error reading session.config (session_id=%s): %s", self.session_id, exc, exc_info=True)
            try:
                await self._ws_send_text({"type": "error", "message": f"Invalid config: {exc}"})
            except Exception:
                pass
            return

        if config.get("type") != "session.config":
            logger.warning("First WS message was not session.config: %s (session_id=%s)", config.get("type"), self.session_id)
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

    def _build_tool_specs(self) -> list[dict]:
        """Convert Strands tool specs to Nova Sonic toolSpec format."""
        specs = []
        for t in self._tools:
            ts = t.tool_spec
            schema: dict = json.loads(json.dumps(ts["inputSchema"]["json"]))
            schema.get("properties", {}).pop("session_id", None)
            if "required" in schema:
                schema["required"] = [r for r in schema["required"] if r != "session_id"]
            specs.append({
                "toolSpec": {
                    "name": ts["name"],
                    "description": ts["description"],
                    "inputSchema": {"json": json.dumps(schema)},
                }
            })
        return specs

    async def _run_session(self, system_prompt: str) -> None:
        self._system_prompt = system_prompt
        self.is_active = True          # ← must be True before any task loop runs
        await self._open_nova_sonic_stream(system_prompt)

        await self._ws_send_text({"type": "session.started"})
        logger.info("Nova Sonic session started (session_id=%s)", self.session_id)

        # Run all tasks concurrently; kickoff is sent once _process_nova_sonic_events
        # is already polling so it receives the resulting toolUse/textOutput events.
        tasks = await asyncio.gather(
            self._receive_client_audio(),
            self._process_nova_sonic_events(),
            self._send_audio_to_client(),
            self._send_kickoff_after_delay(),
            self._session_watchdog(),
            return_exceptions=True,
        )
        for t in tasks:
            if isinstance(t, Exception) and not isinstance(t, asyncio.CancelledError):
                logger.warning("Voice session task ended with: %s", t)

        await self._end_session()

    # ------------------------------------------------------------------
    # Nova Sonic stream open / renew helpers
    # ------------------------------------------------------------------

    async def _open_nova_sonic_stream(self, system_prompt: str, history_events: list[str] | None = None) -> None:
        """Open a Nova Sonic bidirectional stream and send all init events.

        Called both on first open (from _run_session) and on transparent renewal
        (from _renew_nova_sonic_stream).  Generates fresh UUIDs for prompt/content
        names so each renewed stream is an independent Nova Sonic session.
        """
        from aws_sdk_bedrock_runtime.client import (
            BedrockRuntimeClient,
            InvokeModelWithBidirectionalStreamOperationInput,
        )
        from aws_sdk_bedrock_runtime.config import Config as SdkConfig
        from smithy_aws_core.identity import AWSCredentialsIdentity
        from typing import Any

        # Build credentials resolver the same way voice_agent.py does —
        # do NOT override auth_scheme_resolver/auth_schemes; SDK defaults
        # already map ShapeID("aws.auth#sigv4") → SigV4AuthScheme(service="bedrock").
        # Overriding those causes a silent auth failure (stream hangs).
        creds = self._boto_session.get_credentials()
        if creds is None:
            raise RuntimeError("No AWS credentials available.")
        frozen = creds.get_frozen_credentials()

        class _StaticResolver:
            def __init__(self, identity: AWSCredentialsIdentity) -> None:
                self._identity = identity
            async def get_identity(self, *, properties: Any = None) -> AWSCredentialsIdentity:
                return self._identity

        identity = AWSCredentialsIdentity(
            access_key_id=frozen.access_key,
            secret_access_key=frozen.secret_key,
            session_token=frozen.token,
        )
        cfg = SdkConfig(
            endpoint_uri=f"https://bedrock-runtime.{self._region}.amazonaws.com",
            region=self._region,
            aws_credentials_identity_resolver=_StaticResolver(identity),
        )

        # Fresh UUIDs — each Nova Sonic stream is an independent session
        self._prompt_name      = str(uuid.uuid4())
        self._sys_content_name = str(uuid.uuid4())
        self._audio_content    = str(uuid.uuid4())
        self._audio_input_closed = False
        self._session_ended      = False

        self._client = BedrockRuntimeClient(config=cfg)
        self._stream = await self._client.invoke_model_with_bidirectional_stream(
            InvokeModelWithBidirectionalStreamOperationInput(model_id=self._model_id)
        )
        self._session_start_time = time.monotonic()

        # 1. Session start
        await self._send_raw(self._SESSION_START_TMPL)
        await asyncio.sleep(0.05)

        # 2. Prompt start — must include output configs + tool config
        await self._send_event({
            "event": {
                "promptStart": {
                    "promptName": self._prompt_name,
                    "textOutputConfiguration": {"mediaType": "text/plain"},
                    "audioOutputConfiguration": {
                        "mediaType":        "audio/lpcm",
                        "sampleRateHertz":  _OUTPUT_SAMPLE_RATE,
                        "sampleSizeBits":   16,
                        "channelCount":     _CHANNELS,
                        "voiceId":          _NOVA_VOICE,
                        "encoding":         "base64",
                        "audioType":        "SPEECH",
                    },
                    "toolUseOutputConfiguration": {"mediaType": "application/json"},
                    "toolConfiguration": {"tools": self._build_tool_specs()},
                }
            }
        })
        await asyncio.sleep(0.05)

        # 3. System prompt content block — always just the system prompt, no history appended
        await self._send_event({
            "event": {
                "contentStart": {
                    "promptName":  self._prompt_name,
                    "contentName": self._sys_content_name,
                    "type":        "TEXT",
                    "interactive": True,
                    "role":        "SYSTEM",
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
        await asyncio.sleep(0.05)

        # 3b. If this is a renewal, inject conversation history as proper TEXT content blocks.
        # AWS official pattern: role-tagged USER/ASSISTANT blocks with interactive=False, sent
        # AFTER the system prompt and BEFORE the audio contentStart.
        if history_events:
            for raw_event in history_events:
                await self._send_raw(raw_event)
            await asyncio.sleep(0.05)

        # 4. Open audio input content block (continuous mic stream)
        await self._send_event({
            "event": {
                "contentStart": {
                    "promptName":  self._prompt_name,
                    "contentName": self._audio_content,
                    "type":        "AUDIO",
                    "interactive": True,
                    "role":        "USER",
                    "audioInputConfiguration": {
                        "mediaType":       "audio/lpcm",
                        "sampleRateHertz": _INPUT_SAMPLE_RATE,
                        "sampleSizeBits":  16,
                        "channelCount":    _CHANNELS,
                        "audioType":       "SPEECH",
                        "encoding":        "base64",
                    },
                }
            }
        })

    async def _renew_nova_sonic_stream(self) -> None:
        """Transparently replace the Nova Sonic stream — WebSocket to React stays open.

        Called by _session_watchdog at _SESSION_RENEW_S seconds.  The event processor
        loop detects _stream_renewing=True on StopAsyncIteration and waits here to get
        the new stream, then continues processing without the client noticing.
        """
        logger.info("Renewing Nova Sonic stream (conversation turn %d)", self._stream_generation)
        self._stream_renewing = True

        # Build a concise context summary from recent conversation history
        context_preamble = self._build_context_preamble()

        # Gracefully close old stream (sends contentEnd → promptEnd → sessionEnd)
        try:
            await self._close_audio_input()
            await self._send_event({
                "event": {"promptEnd": {"promptName": self._prompt_name}}
            })
            await self._send_event({"event": {"sessionEnd": {}}})
            if self._stream:
                await self._stream.input_stream.close()
        except Exception as exc:
            logger.debug("Renewal — old stream close: %s", exc)

        # Small gap so the old stream's StopAsyncIteration is delivered before
        # _process_nova_sonic_events resumes on the new one
        await asyncio.sleep(0.3)

        # Build history as proper AWS-style role-tagged content blocks
        history_events = self._build_history_events()

        # Open fresh Nova Sonic stream with conversation context injected
        await self._open_nova_sonic_stream(self._system_prompt, history_events)
        self._stream_generation += 1
        self._session_warned   = False
        self._stream_renewing  = False

        logger.info("Nova Sonic stream renewed (generation=%d, history_turns=%d)",
                    self._stream_generation, len(self._conversation_history))

    def _build_history_events(self) -> list[str]:
        """Build AWS-style TEXT content blocks from conversation history.

        Follows the official session-continuation sample pattern:
        - Each turn becomes: contentStart (interactive=False) → textInput → contentEnd
        - role is preserved as USER or ASSISTANT
        - Individual messages capped at _max_turn_bytes; total capped at _max_hist_bytes
        - Only the most recent turns fitting within the byte budget are used
        """
        if not self._conversation_history:
            return []

        # Trim history to fit byte budget (most recent turns have priority)
        budget = self._max_hist_bytes
        turns: list[dict] = []
        for turn in reversed(self._conversation_history):
            encoded = turn["text"].encode("utf-8")
            size = len(encoded) + len(turn["role"])
            if size > budget:
                break
            turns.insert(0, turn)
            budget -= size

        events: list[str] = []
        for turn in turns:
            role = "USER" if turn["role"] == "user" else "ASSISTANT"
            text = turn["text"]
            # Truncate individual turns to byte limit
            text_bytes = text.encode("utf-8")
            if len(text_bytes) > self._max_turn_bytes:
                text = text_bytes[: self._max_turn_bytes].decode("utf-8", errors="ignore") + "…"

            content_name = str(uuid.uuid4())
            events.append(json.dumps({
                "event": {
                    "contentStart": {
                        "promptName":  self._prompt_name,
                        "contentName": content_name,
                        "type":        "TEXT",
                        "role":        role,
                        "interactive": False,
                        "textInputConfiguration": {"mediaType": "text/plain"},
                    }
                }
            }))
            events.append(json.dumps({
                "event": {
                    "textInput": {
                        "promptName":  self._prompt_name,
                        "contentName": content_name,
                        "content":     text,
                    }
                }
            }))
            events.append(json.dumps({
                "event": {
                    "contentEnd": {
                        "promptName":  self._prompt_name,
                        "contentName": content_name,
                    }
                }
            }))
        return events

    # ------------------------------------------------------------------
    # Session watchdog — transparent renewal before Nova Sonic's 600 s limit
    # ------------------------------------------------------------------

    async def _session_watchdog(self) -> None:
        """Silently renew the Nova Sonic stream before the 600 s hard limit.

        The renewal is completely invisible to the user — no messages, no status
        changes, no speech bubbles.  The React WebSocket stays open the whole time.
        """
        try:
            while self.is_active:
                elapsed = time.monotonic() - self._session_start_time
                if elapsed >= _SESSION_RENEW_S and not self._stream_renewing:
                    logger.info("Session watchdog: silent stream renewal at %.0f s", elapsed)
                    await self._renew_nova_sonic_stream()
                    # Loop continues with fresh _session_start_time for the new stream
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # Session kickoff — triggers ARIA's opening greeting
    # ------------------------------------------------------------------

    async def _send_kickoff_after_delay(self) -> None:
        """Wait briefly for the event-processing task to start, then send kickoff."""
        await asyncio.sleep(0.3)
        await self._send_kickoff()

    async def _send_kickoff(self) -> None:
        """Send a text input that instructs ARIA to greet the customer.

        Must run AFTER _process_nova_sonic_events is already polling so that
        the resulting toolUse / textOutput events are captured correctly.
        """
        kickoff_content = str(uuid.uuid4())
        if self._authenticated and self._customer_id:
            kickoff_text = (
                f"SESSION_START: An authenticated customer has connected. "
                f"X-Channel: voice. X-Channel-Auth: authenticated. "
                f"X-Customer-ID: {self._customer_id}. "
                f"X-Session-ID: {self.session_id}. "
                f"Call get_customer_details with customer_id=\"{self._customer_id}\" "
                f"to fetch their profile, then greet them by their preferred_name "
                f"and ask how you can help today. "
                f"Do not ask them to re-verify their identity."
            )
        else:
            kickoff_text = (
                f"SESSION_START: A new customer has connected on voice. "
                f"X-Channel: voice. X-Channel-Auth: unauthenticated. "
                f"X-Session-ID: {self.session_id}. "
                f"Greet the caller warmly as ARIA from Meridian Bank and begin "
                f"the identity verification flow."
            )

        logger.info(
            "Sending session kickoff (auth=%s customer=%s)",
            self._authenticated, self._customer_id,
        )
        await self._send_event({
            "event": {
                "contentStart": {
                    "promptName":  self._prompt_name,
                    "contentName": kickoff_content,
                    "type":        "TEXT",
                    "interactive": False,
                    "role":        "USER",
                    "textInputConfiguration": {"mediaType": "text/plain"},
                }
            }
        })
        await self._send_event({
            "event": {
                "textInput": {
                    "promptName":  self._prompt_name,
                    "contentName": kickoff_content,
                    "content":     kickoff_text,
                }
            }
        })
        await self._send_event({
            "event": {
                "contentEnd": {
                    "promptName":  self._prompt_name,
                    "contentName": kickoff_content,
                }
            }
        })

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
                            # {interrupted:true} was previously sent by client-side VAD
                            # but is no longer used — barge-in is now handled via Nova
                            # Sonic's native contentEnd.stopReason=="INTERRUPTED" signal.
                            # Kept here as a no-op safety net in case an older client
                            # sends it.
                        except json.JSONDecodeError:
                            pass
                    elif "bytes" in msg and msg["bytes"] and not self._farewell_detected:
                        # Drop frames during ~0.5 s stream renewal gap
                        if self._stream_renewing:
                            continue
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
                    # Discard audio while a barge-in is pending — the client already
                    # silenced itself; sending more audio would restart playback.
                    if self._barge_in_pending:
                        continue
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
        """Continuously read events from the Nova Sonic stream, surviving transparent renewals."""
        while self.is_active:
            try:
                # Inner loop: drain the current stream
                while self.is_active and not self._stream_renewing:
                    output = await self._stream.await_output()
                    result = await output[1].receive()

                    if not (result.value and result.value.bytes_):
                        continue

                    try:
                        data = json.loads(result.value.bytes_.decode("utf-8"))
                    except json.JSONDecodeError:
                        continue

                    event = data.get("event", {})
                    await self._handle_event(event)

            except StopAsyncIteration:
                # Stream ended — either the session is truly over or we triggered a renewal.
                if self._stream_renewing:
                    logger.info("Old Nova Sonic stream ended; waiting for renewal…")
                    while self._stream_renewing and self.is_active:
                        await asyncio.sleep(0.05)
                    if self.is_active:
                        logger.info("Nova Sonic stream renewed — resuming event processing")
                        continue   # outer while — process the new stream
                else:
                    logger.info("Nova Sonic stream ended (session complete).")
                    break

            except asyncio.CancelledError:
                break

            except Exception as exc:
                msg = str(exc)
                _transient = (
                    "cumulative audio stream length exceeded" in msg
                    or "Max allowed Length: 600000" in msg
                    or "System instability detected" in msg
                    or "throttling" in msg.lower()
                    or "ServiceUnavailableException" in msg
                )
                if _transient:
                    logger.warning(
                        "Nova Sonic transient error (%s) — attempting silent stream renewal…", msg
                    )
                    try:
                        await self._renew_nova_sonic_stream()
                        logger.info("Stream renewed after transient error — resuming.")
                        continue  # restart outer while on the new stream
                    except Exception as renew_exc:
                        logger.error(
                            "Stream renewal failed after transient error: %s", renew_exc, exc_info=True
                        )
                else:
                    logger.error("Nova Sonic event processing error: %s", exc, exc_info=True)
                break

        self.is_active = False

    # ------------------------------------------------------------------
    # Event handler (mirrors ARIANovaSonicSession._handle_event)
    # ------------------------------------------------------------------

    async def _handle_event(self, event: dict) -> None:  # noqa: C901
        # --- contentStart: sets role & display flag (only SPECULATIVE shows text) ---
        if "contentStart" in event:
            cs = event["contentStart"]
            self._role = cs.get("role", "")
            self._display_assistant_text = False
            self._generation_stage = ""
            if "additionalModelFields" in cs:
                try:
                    extra = json.loads(cs["additionalModelFields"])
                    stage = extra.get("generationStage", "")
                    self._generation_stage = stage
                    if stage == "SPECULATIVE":
                        self._display_assistant_text = True
                except (json.JSONDecodeError, KeyError):
                    pass

        # --- textOutput: transcripts ---
        elif "textOutput" in event:
            text = event["textOutput"].get("content", "")
            role = event["textOutput"].get("role", self._role).upper()

            # Barge-in interrupt signal from Nova Sonic — only fires if Nova Sonic
            # was explicitly asked to interrupt (currently unused; we handle barge-in
            # directly from the client and reset via USER turn detection above).
            if role == "ASSISTANT" and text.startswith("{"):
                try:
                    if json.loads(text).get("interrupted") is True:
                        # Belt-and-suspenders: if Nova Sonic ever does confirm an
                        # interrupt, make sure the client state is consistent.
                        self._barge_in_pending = False
                        return
                except (json.JSONDecodeError, KeyError):
                    pass

            if role == "ASSISTANT" and self._display_assistant_text:
                if text:
                    self._aria_buf.append(text)

            elif role == "USER":
                await self._flush_aria()
                # User is speaking — barge-in (if any) is fully resolved; re-enable audio
                self._barge_in_pending = False
                text = text.strip()
                if text:
                    logger.info("Customer said: %s", text)
                    await self._ws_send_text({"type": "transcript.user", "text": text})
                    if self._transcript:
                        self._transcript.add_turn("Customer", text)
                    self._last_user_text = text
                    # Record in conversation history for session renewal
                    self._add_to_history("user", text)
                    if any(ph in text.lower() for ph in _FAREWELL_PHRASES):
                        self._farewell_detected = True
                        logger.info("Farewell detected: '%s'", text)

        # --- audioOutput: queue for client (skip if barge-in pending) ---
        elif "audioOutput" in event:
            audio_b64 = event["audioOutput"].get("content", "")
            if audio_b64 and not self._barge_in_pending:
                await self._audio_output_queue.put(base64.b64decode(audio_b64))

        # --- toolUse: accumulate tool call ---
        elif "toolUse" in event:
            tu = event["toolUse"]
            self._tool_name    = tu.get("toolName", "")
            self._tool_use_id  = tu.get("toolUseId", "")
            self._tool_content = tu.get("content", "{}")
            logger.info("Tool requested: %s (id=%s)", self._tool_name, self._tool_use_id)

        # --- contentEnd: flush text, execute tool, or handle native barge-in ---
        elif "contentEnd" in event:
            ce = event["contentEnd"]
            if ce.get("stopReason") == "INTERRUPTED":
                # Nova Sonic detected user speech while generating — native barge-in.
                # Drain the audio queue so stale audio isn't sent to the client,
                # then notify the client to stop playback and re-enable the mic.
                self._barge_in_pending = True
                self._aria_buf.clear()
                cleared = 0
                while True:
                    try:
                        self._audio_output_queue.get_nowait()
                        cleared += 1
                    except asyncio.QueueEmpty:
                        break
                logger.info("Nova Sonic native barge-in (INTERRUPTED): cleared %d chunks", cleared)
                await self._ws_send_text({"type": "interrupt"})
            elif ce.get("type") == "TOOL":
                await self._dispatch_tool()
            else:
                await self._flush_aria()

        # --- completionEnd: flush remaining, end on farewell ---
        elif "completionEnd" in event:
            await self._flush_aria()
            if self._farewell_detected:
                logger.info("Farewell response complete — ending session.")
                self.is_active = False
                await self._close_audio_input()

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
                # Only FINAL stage text goes into conversation history (not SPECULATIVE).
                # Matches the official AWS session-continuation sample behaviour.
                if self._generation_stage == "FINAL":
                    self._add_to_history("assistant", text)
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

    def _add_to_history(self, role: str, text: str) -> None:
        """Append a turn to the conversation history, respecting byte limits."""
        self._conversation_history.append({"role": role, "text": text})
        # Trim oldest turns until total byte usage is within budget
        while self._conversation_history:
            total = sum(
                len(t["text"].encode("utf-8")) + len(t["role"])
                for t in self._conversation_history
            )
            if total <= self._max_hist_bytes:
                break
            self._conversation_history.pop(0)

    async def _handle_interrupt(self) -> None:
        """Handle barge-in: drain audio queue, clear ARIA buffer, notify client."""
        cleared = 0
        while True:
            try:
                self._audio_output_queue.get_nowait()
                cleared += 1
            except asyncio.QueueEmpty:
                break
        self._aria_buf.clear()
        # Nova Sonic confirmed the interrupt — re-enable audio for next response
        self._barge_in_pending = False
        logger.info("Barge-in confirmed by Nova Sonic: cleared %d queued audio chunks", cleared)
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
