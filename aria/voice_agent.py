"""ARIA Voice Agent — Nova Sonic 2 speech-to-speech via direct Bedrock bidirectional stream API.

Uses ``aws_sdk_bedrock_runtime`` directly (not the strands bidi SDK) following
the official AWS Nova Sonic 2 example at:
  https://docs.aws.amazon.com/nova/latest/nova2-userguide/sonic-getting-started.html

This approach gives us full control over the event protocol, display logic,
and half-duplex echo suppression.

Regional availability of Nova Sonic 2 (amazon.nova-2-sonic-v1:0):
    us-east-1 | eu-north-1 | ap-northeast-1

Audio protocol (fixed by Nova Sonic):
    Input  — 16 kHz, 16-bit PCM mono
    Output — 24 kHz, 16-bit PCM mono
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
import logging
import math
import os
import struct
import sys
import threading
import time
import uuid
from typing import Any

import pyaudio

logger = logging.getLogger("aria.voice")

# ---------------------------------------------------------------------------
# Nova Sonic 2 constants
# ---------------------------------------------------------------------------
_NOVA_SONIC_REGIONS = frozenset({"us-east-1", "eu-north-1", "ap-northeast-1"})
_NOVA_SONIC_MODEL_ID = "amazon.nova-2-sonic-v1:0"

_INPUT_SAMPLE_RATE  = 16_000   # mic  → Nova Sonic
_OUTPUT_SAMPLE_RATE = 24_000   # Nova Sonic → speaker
_CHANNELS  = 1
_FORMAT    = pyaudio.paInt16
_CHUNK_SIZE = 1024             # frames per mic read

# Seconds to keep mic muted *after* the last audio chunk finishes playing.
_ECHO_TAIL_SECS = float(os.getenv("ECHO_GATE_TAIL_SECS", "0.8"))

# RMS energy threshold for the smart echo gate.
# Audio above this level passes through even during ARIA playback (barge-in).
# 800 ≈ 2.4 % of 16-bit full scale (32768). Decrease for more sensitive barge-in.
# Set NOVA_BARGE_IN_THRESHOLD=0 to always send real mic audio (headphone users).
_BARGE_IN_THRESHOLD = int(os.getenv("NOVA_BARGE_IN_THRESHOLD", "800"))

# Phrases that indicate the customer is ending the conversation.
_FAREWELL_PHRASES = frozenset({
    "goodbye", "good bye", "bye", "bye bye", "farewell",
    "that's all", "that is all", "that's everything", "nothing else",
    "thank you goodbye", "thanks goodbye", "thank you bye",
    "good night", "goodnight", "have a good day",
    "see you", "see ya", "take care", "no more help",
    "done for today", "all done", "all good bye",
})

_NOVA_VOICE       = os.getenv("NOVA_SONIC_VOICE", "tiffany")
_ENDPOINTING      = os.getenv("NOVA_SONIC_ENDPOINTING", "HIGH")
if _ENDPOINTING not in {"HIGH", "MEDIUM", "LOW"}:
    _ENDPOINTING = "HIGH"


def _compute_rms(data: bytes) -> float:
    """Return the RMS energy of a 16-bit little-endian PCM audio chunk."""
    n = len(data) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack_from(f"<{n}h", data)
    return math.sqrt(sum(s * s for s in samples) / n)


# ---------------------------------------------------------------------------
# Region / credential helpers  (reused from original voice_agent)
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
    except NoCredentialsError:
        logger.error("No AWS credentials found for Nova Sonic.")
        raise
    except ClientError as exc:
        logger.error("AWS credential check failed: %s", exc)
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
# Voice-specific system prompt preamble
# ---------------------------------------------------------------------------

def _build_voice_system_prompt(authenticated: bool, customer_id: str | None, session_id: str) -> str:
    from aria.system_prompt import ARIA_SYSTEM_PROMPT

    # Shared empathy/vulnerability block — applies to all voice sessions
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
        "  Distress or panic (crying voice, fast breathing, expressions of fear):\n"
        "    → Slow your speaking pace. Use very short sentences. Acknowledge and reassure\n"
        "       before proceeding: 'I'm here and I'll help you through this step by step.'\n"
        "  Confusion or repetition (customer repeating themselves or not following):\n"
        "    → Use the simplest possible language. Confirm understanding after each step:\n"
        "       'Does that make sense so far?' Take one step at a time.\n"
        "  Third-party pressure (someone coaching in the background, customer sounds scripted\n"
        "  or pressured, mentions someone told them to call about something unusual):\n"
        "    → Do NOT proceed with any irreversible action (card block, transfer, or change).\n"
        "       Say: 'I want to make sure everything is done safely for you. I'd like to\n"
        "       connect you with a specialist colleague who can help further.' Then escalate.\n"
        "  Mid-call disclosure of vulnerability (illness, mental health, bereavement, debt):\n"
        "    → Adapt immediately as if refer_to_specialist is true. Offer the specialist\n"
        "       support team before continuing with the original query.\n\n"
        "WARM ACKNOWLEDGMENT RULE:\n"
        "  On any call involving card loss, suspected fraud, financial hardship, or emotional\n"
        "  distress — say something warm and human in ONE sentence BEFORE proceeding with any\n"
        "  task, security question, or tool call. Never jump straight to 'I'll need to verify'\n"
        "  when the customer has just told you something upsetting.\n\n"
    )

    if authenticated and customer_id:
        preamble = (
            "=== VOICE SESSION — CRITICAL OPERATING RULES ===\n\n"
            "You are ARIA, Meridian Bank's voice banking assistant, on a LIVE phone call.\n\n"
            "SESSION CONTEXT:\n"
            f"- Channel: voice (bidirectional audio stream)\n"
            f"- Auth state: authenticated\n"
            f"- Customer ID: {customer_id}\n"
            f"- Session ID (use for all tool calls that require session_id): {session_id}\n"
            "- The caller has already been verified. Do NOT ask them to re-authenticate.\n"
            f"- Call get_customer_details(\"{customer_id}\") immediately to fetch their profile,\n"
            "  then greet them by preferred_name.\n\n"
            + _EMPATHY_BLOCK +
            "CARD QUERIES — VOICE OVERRIDE (MANDATORY):\n"
            "After get_customer_details runs, you already know every card_last_four value from\n"
            "the customer profile. Apply these rules EXACTLY:\n"
            "  1. NEVER ask the customer to provide or confirm card digits you already have.\n"
            "  2. NEVER call pii_vault_retrieve for card_last_four — use values from the profile.\n"
            "  3. ONE card of the requested type → use its card_last_four directly. Tell the\n"
            "     customer which card you are accessing, e.g. 'I'll check your Visa Debit ending\n"
            "     in 4821' — then call the tool immediately without waiting for confirmation.\n"
            "  4. MULTIPLE cards of the same type → read each card's scheme + last_four to the\n"
            "     customer and ask which one they mean, then use the selected card_last_four.\n"
            "  5. 'Confirm the card' in any instruction means TELL the customer which card you\n"
            "     are using — NOT ask them to supply digits.\n\n"
            "MANDATORY SESSION RULES:\n"
            "1. Fetch the customer profile first, then greet the caller by name.\n"
            "2. This session STAYS OPEN. Never end it until the caller explicitly says goodbye.\n"
            "3. You are on VOICE — speak naturally. Never read full URLs or full card numbers.\n\n"
            "=== END VOICE RULES — BANKING INSTRUCTIONS FOLLOW ===\n\n"
        )
    else:
        preamble = (
            "=== VOICE SESSION — CRITICAL OPERATING RULES ===\n\n"
            "You are ARIA, Meridian Bank's voice banking assistant, on a LIVE phone call.\n\n"
            "SESSION CONTEXT:\n"
            "- Channel: voice (bidirectional audio stream)\n"
            "- Auth state: unauthenticated\n"
            f"- Session ID (use for all tool calls that require session_id): {session_id}\n"
            "- Greet the caller warmly as ARIA from Meridian Bank and begin identity verification.\n\n"
            + _EMPATHY_BLOCK +
            "MANDATORY RULES:\n"
            "1. This session STAYS OPEN. Never end it until the caller says goodbye.\n"
            "2. You are on VOICE — speak naturally. Do not read out full URLs or card numbers.\n\n"
            "=== END VOICE RULES — BANKING INSTRUCTIONS FOLLOW ===\n\n"
        )
    return preamble + ARIA_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Main session class
# ---------------------------------------------------------------------------

class ARIANovaSonicSession:
    """Manages a full Nova Sonic 2 bidirectional stream session for ARIA.

    Follows the official AWS Nova 2 Sonic example pattern with additions:
    - All ARIA Strands tools wired as Nova Sonic tool specs
    - Half-duplex echo gate: mic sends silence while ARIA's audio is playing
    - SPECULATIVE-stage display logic (only show real AI text, not audio echoes)
    """

    # ----- Nova Sonic event templates -----
    _SESSION_START = json.dumps({
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

    def __init__(
        self,
        model_id: str,
        region: str,
        boto_session: Any,
        system_prompt: str,
        session_id: str,
        authenticated: bool = False,
        customer_id: str | None = None,
    ) -> None:
        self.model_id      = model_id
        self.region        = region
        self.system_prompt = system_prompt
        self.session_id    = session_id
        self._authenticated = authenticated
        self._customer_id   = customer_id

        self._boto_session = boto_session
        self._client       = None
        self._stream       = None
        self.is_active     = False

        # Unique IDs for this session's prompt / content blocks
        self._prompt_name      = str(uuid.uuid4())
        self._sys_content_name = str(uuid.uuid4())
        self._audio_content    = str(uuid.uuid4())

        # Response state
        self._display_assistant_text = False
        self._role: str = ""
        self._aria_buf: list[str] = []

        # Session lifecycle flags
        self._farewell_detected  = False  # set when user says goodbye
        self._session_ended      = False  # set once end_session() has run
        self._audio_input_closed = False  # set once audio contentEnd is sent

        # Pending tool call
        self._tool_name    = ""
        self._tool_use_id  = ""
        self._tool_content = ""

        # Audio queues / echo gate
        self._audio_output_queue: asyncio.Queue = asyncio.Queue()
        self._gate_lock  = threading.Lock()
        self._silence_until: float = 0.0   # monotonic time until mic is muted

        # Tool map: name → DecoratedFunctionTool
        from aria.tools import ALL_TOOLS
        self._tools    = ALL_TOOLS
        self._tool_map = {t.tool_name: t for t in ALL_TOOLS}

        # Transcript manager — saves conversation to .md file on session end
        from aria.transcript_manager import TranscriptManager
        self._transcript = TranscriptManager(
            session_id=session_id,
            customer_id=customer_id,
            channel="voice",
            authenticated=authenticated,
        )

    # ------------------------------------------------------------------
    # Client initialisation  (converts boto3 credentials → SDK Config)
    # ------------------------------------------------------------------

    def _initialize_client(self) -> None:
        from aws_sdk_bedrock_runtime.client import BedrockRuntimeClient
        from aws_sdk_bedrock_runtime.config import Config
        from smithy_aws_core.identity import AWSCredentialsIdentity

        creds = self._boto_session.get_credentials()
        if creds is None:
            raise RuntimeError("No AWS credentials available.")
        frozen = creds.get_frozen_credentials()

        # Build a resolver that wraps the boto3 frozen credentials.
        # We do NOT override auth_scheme_resolver / auth_schemes — the SDK
        # defaults already use ShapeID("aws.auth#sigv4") → SigV4AuthScheme
        # which is what Nova Sonic requires.  Overriding with a plain-string
        # key causes a silent auth failure (connection hangs indefinitely).
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

        config = Config(
            endpoint_uri=f"https://bedrock-runtime.{self.region}.amazonaws.com",
            region=self.region,
            aws_credentials_identity_resolver=_StaticResolver(identity),
        )
        self._client = BedrockRuntimeClient(config=config)

    # ------------------------------------------------------------------
    # Tool spec builder
    # ------------------------------------------------------------------

    def _build_tool_specs(self) -> list[dict]:
        """Convert Strands tool specs to Nova Sonic toolSpec format.

        session_id is removed from required / properties because the voice
        agent injects it automatically at execution time.
        """
        specs = []
        for t in self._tools:
            ts = t.tool_spec
            schema: dict = json.loads(json.dumps(ts["inputSchema"]["json"]))  # deep copy

            # Strip session_id — injected at execution time
            schema.get("properties", {}).pop("session_id", None)
            if "required" in schema:
                schema["required"] = [r for r in schema["required"] if r != "session_id"]

            specs.append({
                "toolSpec": {
                    "name": ts["name"],
                    "description": ts["description"],
                    "inputSchema": {
                        "json": json.dumps(schema)
                    },
                }
            })
        return specs

    # ------------------------------------------------------------------
    # Event sender
    # ------------------------------------------------------------------

    async def _send_event(self, event: dict | str) -> None:
        from aws_sdk_bedrock_runtime.models import (
            InvokeModelWithBidirectionalStreamInputChunk,
            BidirectionalInputPayloadPart,
        )
        payload = event if isinstance(event, str) else json.dumps(event)
        chunk = InvokeModelWithBidirectionalStreamInputChunk(
            value=BidirectionalInputPayloadPart(bytes_=payload.encode("utf-8"))
        )
        await self._stream.input_stream.send(chunk)

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def start_session(self) -> None:
        """Open the bidirectional stream and send all initialisation events."""
        from aws_sdk_bedrock_runtime.client import (
            InvokeModelWithBidirectionalStreamOperationInput,
        )

        if not self._client:
            self._initialize_client()

        self._stream = await self._client.invoke_model_with_bidirectional_stream(
            InvokeModelWithBidirectionalStreamOperationInput(model_id=self.model_id)
        )
        self.is_active = True

        # 1. Session start
        await self._send_event(self._SESSION_START)
        await asyncio.sleep(0.05)

        # 2. Prompt start (with tool configuration)
        await self._send_event({
            "event": {
                "promptStart": {
                    "promptName": self._prompt_name,
                    "textOutputConfiguration": {"mediaType": "text/plain"},
                    "audioOutputConfiguration": {
                        "mediaType": "audio/lpcm",
                        "sampleRateHertz": _OUTPUT_SAMPLE_RATE,
                        "sampleSizeBits": 16,
                        "channelCount": _CHANNELS,
                        "voiceId": _NOVA_VOICE,
                        "encoding": "base64",
                        "audioType": "SPEECH",
                    },
                    "toolUseOutputConfiguration": {"mediaType": "application/json"},
                    "toolConfiguration": {"tools": self._build_tool_specs()},
                }
            }
        })
        await asyncio.sleep(0.05)

        # 3. System prompt
        await self._send_event({
            "event": {
                "contentStart": {
                    "promptName": self._prompt_name,
                    "contentName": self._sys_content_name,
                    "type": "TEXT",
                    "interactive": True,
                    "role": "SYSTEM",
                    "textInputConfiguration": {"mediaType": "text/plain"},
                }
            }
        })
        await self._send_event({
            "event": {
                "textInput": {
                    "promptName": self._prompt_name,
                    "contentName": self._sys_content_name,
                    "content": self.system_prompt,
                }
            }
        })
        await self._send_event({
            "event": {
                "contentEnd": {
                    "promptName": self._prompt_name,
                    "contentName": self._sys_content_name,
                }
            }
        })
        await asyncio.sleep(0.05)

        # 5. Audio content start — opens the continuous mic stream
        await self._send_event({
            "event": {
                "contentStart": {
                    "promptName": self._prompt_name,
                    "contentName": self._audio_content,
                    "type": "AUDIO",
                    "interactive": True,
                    "role": "USER",
                    "audioInputConfiguration": {
                        "mediaType": "audio/lpcm",
                        "sampleRateHertz": _INPUT_SAMPLE_RATE,
                        "sampleSizeBits": 16,
                        "channelCount": _CHANNELS,
                        "audioType": "SPEECH",
                        "encoding": "base64",
                    },
                }
            }
        })

    async def _close_audio_input(self) -> None:
        """Send contentEnd for the mic audio content block.

        Called immediately when farewell is detected so Nova Sonic stops
        accepting audio input and cannot start another response turn from
        ARIA's own echo or ambient noise.  Idempotent — safe to call twice.
        """
        if self._audio_input_closed:
            return
        self._audio_input_closed = True
        try:
            await self._send_event({
                "event": {
                    "contentEnd": {
                        "promptName": self._prompt_name,
                        "contentName": self._audio_content,
                    }
                }
            })
            logger.info("Audio input closed (farewell detected).")
        except Exception as exc:
            logger.debug("Error closing audio input: %s", exc)

    async def end_session(self) -> None:
        if self._session_ended:
            return
        self._session_ended = True
        self.is_active = False
        try:
            # Close audio input only if it wasn't already closed on farewell.
            await self._close_audio_input()
            await self._send_event({
                "event": {"promptEnd": {"promptName": self._prompt_name}}
            })
            await self._send_event({"event": {"sessionEnd": {}}})
            await self._stream.input_stream.close()
        except Exception as exc:
            logger.debug("Error during session end (may be normal): %s", exc)
        finally:
            self.is_active = False

    # ------------------------------------------------------------------
    # Response processor
    # ------------------------------------------------------------------

    async def send_kickoff(self) -> None:
        """Send the SESSION_START trigger that causes ARIA to call
        get_customer_details and deliver its opening greeting.

        Must be called AFTER the response-processing task is running so that
        the resulting toolUse events are received and dispatched correctly.
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

        logger.info("Sending session kickoff (auth=%s, customer=%s)", self._authenticated, self._customer_id)
        await self._send_event({
            "event": {
                "contentStart": {
                    "promptName": self._prompt_name,
                    "contentName": kickoff_content,
                    "type": "TEXT",
                    "interactive": False,
                    "role": "USER",
                    "textInputConfiguration": {"mediaType": "text/plain"},
                }
            }
        })
        await self._send_event({
            "event": {
                "textInput": {
                    "promptName": self._prompt_name,
                    "contentName": kickoff_content,
                    "content": kickoff_text,
                }
            }
        })
        await self._send_event({
            "event": {
                "contentEnd": {
                    "promptName": self._prompt_name,
                    "contentName": kickoff_content,
                }
            }
        })

    async def _process_responses(self) -> None:
        """Continuously read events from the Nova Sonic stream."""
        try:
            while self.is_active:
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
            logger.info("Nova Sonic stream ended.")
        except Exception as exc:
            logger.error("Response processing error: %s", exc, exc_info=True)
        finally:
            self.is_active = False

    async def _handle_event(self, event: dict) -> None:  # noqa: C901
        # --- contentStart: sets role & display flag ---
        if "contentStart" in event:
            cs = event["contentStart"]
            self._role = cs.get("role", "")
            self._display_assistant_text = False
            if "additionalModelFields" in cs:
                try:
                    extra = json.loads(cs["additionalModelFields"])
                    if extra.get("generationStage") == "SPECULATIVE":
                        self._display_assistant_text = True
                except (json.JSONDecodeError, KeyError):
                    pass

        # --- textOutput: transcripts ---
        elif "textOutput" in event:
            text = event["textOutput"].get("content", "")
            role = event["textOutput"].get("role", self._role).upper()

            # Detect barge-in interrupt signal: Nova Sonic sends
            # textOutput role=ASSISTANT content='{"interrupted": true}'
            if role == "ASSISTANT" and text.startswith("{"):
                try:
                    evt_data = json.loads(text)
                    if evt_data.get("interrupted") is True:
                        await self._handle_interrupt()
                        return
                except (json.JSONDecodeError, KeyError):
                    pass

            if role == "ASSISTANT" and self._display_assistant_text:
                if text:
                    self._aria_buf.append(text)

            elif role == "USER":
                # Flush any buffered ARIA text first, then show user speech
                self._flush_aria()
                if text.strip():
                    print(f"\nCustomer: {text.strip()}\n")
                    self._transcript.add_turn("Customer", text.strip())
                # Detect farewell to trigger graceful session end
                if not self._farewell_detected:
                    lower = text.lower()
                    if any(phrase in lower for phrase in _FAREWELL_PHRASES):
                        self._farewell_detected = True
                        logger.info("Farewell detected — will end session after ARIA's response")

        # --- audioOutput: queue for playback ---
        elif "audioOutput" in event:
            audio_bytes = base64.b64decode(event["audioOutput"]["content"])
            await self._audio_output_queue.put(audio_bytes)

        # --- toolUse: accumulate tool call ---
        elif "toolUse" in event:
            tu = event["toolUse"]
            self._tool_name    = tu.get("toolName", "")
            self._tool_use_id  = tu.get("toolUseId", "")
            self._tool_content = tu.get("content", "{}")
            logger.info("Tool requested: %s (id=%s)", self._tool_name, self._tool_use_id)

        # --- contentEnd: flush text; execute tool if TOOL type ---
        elif "contentEnd" in event:
            ce = event["contentEnd"]
            if ce.get("type") == "TOOL":
                await self._dispatch_tool()
            else:
                # End of a non-tool content block — flush ARIA buffer
                self._flush_aria()

        # --- completionEnd: flush any remaining ARIA text; end on farewell ---
        elif "completionEnd" in event:
            self._flush_aria()
            if self._farewell_detected:
                logger.info("Farewell response complete — ending session.")
                self.is_active = False
                # Close the audio input stream immediately so Nova Sonic stops
                # accepting mic input.  Without this, ARIA's own farewell audio
                # can echo back through the mic and trigger a second response.
                await self._close_audio_input()

    def _flush_aria(self) -> None:
        if self._aria_buf:
            text = " ".join(self._aria_buf).strip()
            self._aria_buf.clear()
            if text:
                print(f"\nARIA: {text}\n")
                self._transcript.add_turn("ARIA", text)

    async def _handle_interrupt(self) -> None:
        """Handle a barge-in interrupt signal from Nova Sonic.

        Nova Sonic sends ``textOutput`` with role=ASSISTANT and
        content='{"interrupted": true}' when the user speaks over ARIA.
        We mirror the React client's ``audioPlayer.bargeIn()`` call:
        clear all queued audio immediately and reset the echo gate.
        """
        cleared = 0
        while True:
            try:
                self._audio_output_queue.get_nowait()
                cleared += 1
            except asyncio.QueueEmpty:
                break

        # Clear any buffered ARIA display text for the interrupted turn
        self._aria_buf.clear()

        # Unblock the echo gate so the mic reopens immediately
        with self._gate_lock:
            self._silence_until = 0.0

        logger.info("Barge-in: cleared %d queued audio chunks", cleared)
        print("\n[Customer interrupted — listening...]\n")

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def _dispatch_tool(self) -> None:
        """Execute the accumulated tool call and send the result to Nova Sonic."""
        result_str = await self._execute_tool(
            self._tool_name, self._tool_use_id, self._tool_content
        )
        tool_content_name = str(uuid.uuid4())

        # contentStart (TOOL)
        await self._send_event({
            "event": {
                "contentStart": {
                    "promptName": self._prompt_name,
                    "contentName": tool_content_name,
                    "interactive": False,
                    "type": "TOOL",
                    "role": "TOOL",
                    "toolResultInputConfiguration": {
                        "toolUseId": self._tool_use_id,
                        "type": "TEXT",
                        "textInputConfiguration": {"mediaType": "text/plain"},
                    },
                }
            }
        })
        # toolResult
        await self._send_event({
            "event": {
                "toolResult": {
                    "promptName": self._prompt_name,
                    "contentName": tool_content_name,
                    "content": result_str,
                    "role": "TOOL",
                }
            }
        })
        # contentEnd
        await self._send_event({
            "event": {
                "contentEnd": {
                    "promptName": self._prompt_name,
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
            return json.dumps({"error": f"Tool '{name}' not found."})

        # Inject session_id if the tool accepts it and the caller didn't pass it
        sig = inspect.signature(tool._tool_func)
        if "session_id" in sig.parameters and "session_id" not in args:
            args["session_id"] = self.session_id

        logger.info("Executing tool %s with args %s", name, {k: v for k, v in args.items() if k != "session_id"})
        try:
            result = await asyncio.to_thread(tool._tool_func, **args)
            return json.dumps(result, default=str)
        except Exception as exc:
            logger.error("Tool %s failed: %s", name, exc, exc_info=True)
            return json.dumps({"error": str(exc)})

    # ------------------------------------------------------------------
    # Audio capture (mic → Nova Sonic, with echo gate)
    # ------------------------------------------------------------------

    async def capture_audio(self) -> None:
        p      = pyaudio.PyAudio()
        stream = p.open(
            format=_FORMAT,
            channels=_CHANNELS,
            rate=_INPUT_SAMPLE_RATE,
            input=True,
            frames_per_buffer=_CHUNK_SIZE,
        )
        try:
            while self.is_active:
                audio_data = await asyncio.to_thread(
                    stream.read, _CHUNK_SIZE, False  # exception_on_overflow=False
                )

                # After farewell: always send silence so Nova Sonic cannot pick up
                # ARIA's own echo or ambient noise and start a brand-new response.
                if self._farewell_detected:
                    audio_data = b"\x00" * len(audio_data)
                else:
                    # Smart echo gate: during ARIA playback, mute low-energy audio
                    # (speaker echo) but pass through high-energy audio (user speech).
                    # If NOVA_BARGE_IN_THRESHOLD=0, always send real audio (headphones).
                    with self._gate_lock:
                        muted = time.monotonic() < self._silence_until

                    if muted:
                        rms = _compute_rms(audio_data)
                        if _BARGE_IN_THRESHOLD == 0 or rms >= _BARGE_IN_THRESHOLD:
                            # User is speaking over ARIA — pass through for barge-in
                            pass
                        else:
                            # Low energy — likely speaker echo, suppress it
                            audio_data = b"\x00" * len(audio_data)

                if self.is_active:
                    blob = base64.b64encode(audio_data).decode("utf-8")
                    await self._send_event({
                        "event": {
                            "audioInput": {
                                "promptName": self._prompt_name,
                                "contentName": self._audio_content,
                                "content": blob,
                            }
                        }
                    })
                await asyncio.sleep(0)  # yield to event loop
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Audio capture error: %s", exc)
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()

    # ------------------------------------------------------------------
    # Audio playback (Nova Sonic → speaker, updates echo gate)
    # ------------------------------------------------------------------

    async def play_audio(self) -> None:
        p      = pyaudio.PyAudio()
        stream = p.open(
            format=_FORMAT,
            channels=_CHANNELS,
            rate=_OUTPUT_SAMPLE_RATE,
            output=True,
        )
        try:
            while self.is_active or not self._audio_output_queue.empty():
                try:
                    audio_bytes = await asyncio.wait_for(
                        self._audio_output_queue.get(), timeout=0.5
                    )
                except asyncio.TimeoutError:
                    continue

                # Estimate playback duration and extend the echo gate
                duration = len(audio_bytes) / (_OUTPUT_SAMPLE_RATE * 2)
                with self._gate_lock:
                    self._silence_until = max(
                        self._silence_until,
                        time.monotonic() + duration + _ECHO_TAIL_SECS,
                    )

                # Write audio to speaker (blocking — run in thread)
                await asyncio.to_thread(stream.write, audio_bytes)

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Audio playback error: %s", exc)
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run_voice_session(authenticated: bool, customer_id: str | None) -> None:
    """Run a full Nova Sonic 2 S2S voice session.

    Args:
        authenticated: True if the caller has already been verified.
        customer_id:   Customer ID string for authenticated sessions.
    """
    # Verify aws_sdk_bedrock_runtime is available
    try:
        import aws_sdk_bedrock_runtime  # noqa: F401
    except ImportError:
        print(
            "\nVoice mode requires aws_sdk_bedrock_runtime.\n"
            "Install with:  pip install 'strands-agents[bidi]'\n"
        )
        sys.exit(1)

    region       = _resolve_nova_region()
    session_id   = str(uuid.uuid4())
    model_id     = os.getenv("NOVA_SONIC_MODEL_ID", _NOVA_SONIC_MODEL_ID)

    try:
        boto_sess    = _build_boto_session(region)
    except Exception as exc:
        print(f"\nFailed to resolve AWS credentials: {exc}\n")
        sys.exit(1)

    system_prompt = _build_voice_system_prompt(authenticated, customer_id, session_id)

    nova = ARIANovaSonicSession(
        model_id=model_id,
        region=region,
        boto_session=boto_sess,
        system_prompt=system_prompt,
        session_id=session_id,
        authenticated=authenticated,
        customer_id=customer_id,
    )

    logger.info(
        "Starting Nova Sonic session | model=%s region=%s voice=%s auth=%s",
        model_id, region, _NOVA_VOICE, authenticated,
    )

    try:
        await nova.start_session()
    except Exception as exc:
        logger.critical("Failed to start Nova Sonic session: %s", exc, exc_info=True)
        print(
            f"\nCould not connect to Nova Sonic 2.\n"
            f"Supported regions: {', '.join(sorted(_NOVA_SONIC_REGIONS))}\n"
            f"Set NOVA_SONIC_REGION in your environment.\nError: {exc}\n"
        )
        sys.exit(1)

    print(
        "\n[Voice session connected — speak now. "
        "Say 'goodbye' or press Ctrl-C to end]\n"
        f"[Barge-in threshold: {_BARGE_IN_THRESHOLD} "
        f"({'always on' if _BARGE_IN_THRESHOLD == 0 else 'set NOVA_BARGE_IN_THRESHOLD=0 for headphones'})]\n"
    )

    response_task = asyncio.create_task(nova._process_responses())
    playback_task = asyncio.create_task(nova.play_audio())
    capture_task  = asyncio.create_task(nova.capture_audio())

    # Send the SESSION_START kickoff NOW — after tasks are running so that
    # the toolUse event (get_customer_details) is handled by _process_responses.
    await nova.send_kickoff()

    try:
        await response_task
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    except Exception as exc:
        logger.error("Voice session error: %s", exc)
    finally:
        nova.is_active = False  # stop capture and any lingering loops

        # Cancel mic capture immediately — no more input needed.
        if not capture_task.done():
            capture_task.cancel()

        # Let playback drain so farewell audio finishes (up to 8 s).
        try:
            await asyncio.wait_for(playback_task, timeout=8.0)
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
            if not playback_task.done():
                playback_task.cancel()

        # Gather all tasks to suppress any remaining CancelledError noise.
        try:
            await asyncio.gather(
                capture_task, playback_task, response_task,
                return_exceptions=True,
            )
        except Exception:
            pass

        try:
            await nova.end_session()
        except Exception:
            pass

        nova._transcript.save()
        print("\n[Voice session ended]\n")
        logger.info("Voice session ended.")
