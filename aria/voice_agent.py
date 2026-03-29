"""ARIA Voice Agent — Nova Sonic 2 speech-to-speech via Bedrock bidirectional stream.

Used when ``--channel voice`` is passed to main.py.  Shares the same tools and
system prompt as the text-based agent so all ARIA behaviour is identical — only
the I/O transport changes (microphone in / speaker out vs stdin / stdout).

Regional availability of Nova Sonic 2 (amazon.nova-2-sonic-v1:0):
    us-east-1 | eu-north-1 | ap-northeast-1  (NOT eu-west-2 / eu-west-1)

Audio protocol (fixed by Nova Sonic):
    Input  — 16 kHz, 16-bit PCM mono
    Output — 16 kHz, 16-bit PCM mono  (Nova Sonic v2 default)

Dependencies (beyond core requirements.txt):
    strands-agents[bidi]   →  installs aws_sdk_bedrock_runtime (experimental SDK)
    pyaudio                →  mic capture and speaker playback
    portaudio (system)     →  brew install portaudio  /  apt-get install portaudio19-dev
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any

logger = logging.getLogger("aria.voice")

# ---------------------------------------------------------------------------
# Nova Sonic 2 constants
# ---------------------------------------------------------------------------
_NOVA_SONIC_REGIONS = frozenset({"us-east-1", "eu-north-1", "ap-northeast-1"})
_NOVA_SONIC_MODEL_ID = "amazon.nova-2-sonic-v1:0"

# "tiffany" — US-English female, warm conversational tone.
# Other built-in options: "matthew" (male), "amy" (British female).
_NOVA_VOICE = os.getenv("NOVA_SONIC_VOICE", "tiffany")

# How aggressively Nova Sonic detects end-of-turn.
# HIGH suits banking (short factual exchanges); LOW suits long explanations.
_ENDPOINTING = os.getenv("NOVA_SONIC_ENDPOINTING", "HIGH")
if _ENDPOINTING not in {"HIGH", "MEDIUM", "LOW"}:
    _ENDPOINTING = "HIGH"


# ---------------------------------------------------------------------------
# Region resolution
# ---------------------------------------------------------------------------

def _resolve_nova_region() -> str:
    """Return a Nova Sonic–compatible AWS region.

    Priority:
    1. NOVA_SONIC_REGION env var
    2. AWS_REGION env var (if it's in the supported set)
    3. Fallback: eu-north-1  (closest EU data-centre that supports the model)
    """
    for var in ("NOVA_SONIC_REGION", "AWS_REGION"):
        region = os.getenv(var, "").strip()
        if region in _NOVA_SONIC_REGIONS:
            logger.info("Nova Sonic region resolved from %s: %s", var, region)
            return region
        if region:
            logger.warning(
                "Region '%s' (from %s) does not support Nova Sonic 2; "
                "available regions: %s",
                region, var, ", ".join(sorted(_NOVA_SONIC_REGIONS)),
            )
    logger.info("Nova Sonic region falling back to eu-north-1")
    return "eu-north-1"


# ---------------------------------------------------------------------------
# Credential / session builder (mirrors agent.py logic)
# ---------------------------------------------------------------------------

def _build_boto_session(region: str):
    """Build a boto3 Session using the standard AWS credential chain.

    BidiNovaSonicModel hangs silently on bad credentials — we validate eagerly
    so the user gets a meaningful error instead of waiting indefinitely.
    """
    import boto3
    from botocore.exceptions import NoCredentialsError, ClientError

    profile = os.getenv("AWS_PROFILE") or os.getenv("AWS_DEFAULT_PROFILE")
    role_arn = os.getenv("AWS_ROLE_ARN", "").strip()
    role_session = os.getenv("AWS_ROLE_SESSION_NAME", "aria-nova-sonic")

    if profile:
        logger.info("Nova Sonic: using AWS named profile: %s", profile)
        session = boto3.Session(profile_name=profile, region_name=region)
    else:
        logger.info("Nova Sonic: using default AWS credential chain")
        session = boto3.Session(region_name=region)

    try:
        identity = session.client("sts").get_caller_identity()
        logger.info(
            "Nova Sonic credentials OK | account=%s arn=%s",
            identity.get("Account"), identity.get("Arn"),
        )
    except NoCredentialsError:
        logger.error(
            "No AWS credentials found. Configure via AWS_ACCESS_KEY_ID env vars, "
            "~/.aws/credentials, or an IAM instance role."
        )
        raise
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        logger.error("AWS credential check failed for Nova Sonic [%s]: %s", code, exc)
        raise

    if role_arn:
        logger.info("Nova Sonic: assuming IAM role %s", role_arn)
        sts = session.client("sts")
        assumed = sts.assume_role(RoleArn=role_arn, RoleSessionName=role_session)
        creds = assumed["Credentials"]
        session = boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=region,
        )
        logger.info("Nova Sonic: role assumed successfully: %s", role_arn)

    return session


# ---------------------------------------------------------------------------
# Voice-specific system prompt
# ---------------------------------------------------------------------------

_VOICE_PREAMBLE_UNAUTH = """\
=== VOICE SESSION — CRITICAL OPERATING RULES ===

You are ARIA, Meridian Bank's voice banking assistant, on a LIVE phone call.

SESSION CONTEXT:
- Channel: voice (bidirectional audio stream)
- Auth state: unauthenticated
- The caller is waiting on the line right now.

MANDATORY RULES FOR THIS SESSION:
1. Greet the caller warmly as ARIA from Meridian Bank and begin identity verification.
2. This session STAYS OPEN. Do NOT call stop_conversation or pii_vault_purge
   unless the caller explicitly says goodbye or asks to end the call.
3. After your greeting, listen — the caller will speak next.
4. Never end the session based on a connection event or your own judgement.
   Only end when the caller clearly says goodbye or ends the call.
5. You are on VOICE — never read out URLs, account numbers in full, or long
   reference numbers digit by digit mid-sentence. Speak naturally.

=== END VOICE RULES — BANKING INSTRUCTIONS FOLLOW ===

"""

_VOICE_PREAMBLE_AUTH = """\
=== VOICE SESSION — CRITICAL OPERATING RULES ===

You are ARIA, Meridian Bank's voice banking assistant, on a LIVE phone call.

SESSION CONTEXT:
- Channel: voice (bidirectional audio stream)
- Auth state: authenticated
- Customer ID: {customer_id}
- The caller has already been verified. Do NOT ask them to re-authenticate.
- Call get_customer_details("{customer_id}") immediately to fetch their profile,
  then greet them by preferred_name.

MANDATORY RULES FOR THIS SESSION:
1. Fetch the customer profile first, then greet the caller by name.
2. This session STAYS OPEN. Do NOT call stop_conversation or pii_vault_purge
   unless the caller explicitly says goodbye or asks to end the call.
3. After your greeting, listen — the caller will speak next.
4. Never end the session based on a connection event or your own judgement.
   Only end when the caller clearly says goodbye or ends the call.
5. You are on VOICE — never read out URLs, account numbers in full, or long
   reference numbers digit by digit mid-sentence. Speak naturally.

=== END VOICE RULES — BANKING INSTRUCTIONS FOLLOW ===

"""


def _build_voice_system_prompt(authenticated: bool, customer_id: str | None) -> str:
    """Return ARIA_SYSTEM_PROMPT with a voice-mode preamble prepended.

    Injecting session context into the system prompt (rather than the
    messages list) prevents Nova Sonic from treating the greeting as a
    completed exchange and calling stop_conversation prematurely.
    """
    from aria.system_prompt import ARIA_SYSTEM_PROMPT

    if authenticated and customer_id:
        preamble = _VOICE_PREAMBLE_AUTH.format(customer_id=customer_id)
    else:
        preamble = _VOICE_PREAMBLE_UNAUTH

    return preamble + ARIA_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Terminal output handler (BidiOutput-compatible)
# ---------------------------------------------------------------------------

class _TerminalOutput:
    """Prints live transcripts and tool activity to the terminal.

    Implements the BidiOutput protocol so it can be passed directly to
    ``BidiAgent.run(outputs=[..., terminal_output])``.

    Transcript strategy:
    - BidiTranscriptStreamEvent arrives as streaming chunks; we accumulate
      them per-turn and print the complete turn only when is_final=True.
    - This avoids garbled output from \r overwriting partial chunks of
      different lengths.
    """

    def __init__(self) -> None:
        self._aria_buf: str = ""
        self._customer_buf: str = ""

    async def start(self, agent: Any) -> None:
        print("\n[Voice session connected — speak now. Say 'stop conversation' or press Ctrl-C to end]\n")

    async def stop(self) -> None:
        print("\n[Voice session ended]\n")

    async def __call__(self, event: Any) -> None:
        from strands.experimental.bidi import (
            BidiTranscriptStreamEvent,
            BidiResponseCompleteEvent,
            BidiConnectionCloseEvent,
            BidiErrorEvent,
            BidiUsageEvent,
            ToolUseStreamEvent,
            ToolResultEvent,
        )

        if isinstance(event, BidiTranscriptStreamEvent):
            role = event.role  # "user" or "assistant"
            if event.is_final:
                # current_transcript holds the full accumulated text for this turn
                full_text = event.current_transcript or event.text
                if full_text:
                    if role == "assistant":
                        print(f"\nARIA: {full_text}\n")
                    else:
                        print(f"\nCustomer: {full_text}\n")

        elif isinstance(event, BidiResponseCompleteEvent):
            logger.debug("Nova Sonic response complete | stop_reason=%s", getattr(event, "stop_reason", ""))

        elif isinstance(event, BidiConnectionCloseEvent):
            reason = getattr(event, "reason", "")
            logger.info("Nova Sonic connection closed: %s", reason)

        elif isinstance(event, BidiErrorEvent):
            err = getattr(event, "error", str(event))
            logger.error("Nova Sonic stream error: %s", err)

        elif isinstance(event, BidiUsageEvent):
            usage = getattr(event, "usage", {})
            logger.debug("Nova Sonic token usage: %s", usage)

        elif isinstance(event, ToolUseStreamEvent):
            tool = getattr(getattr(event, "tool_use", None), "name", "unknown")
            logger.debug("Nova Sonic tool invoked: %s", tool)


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

def create_aria_voice_agent(authenticated: bool = False, customer_id: str | None = None):
    """Create a BidiAgent backed by Nova Sonic 2 with all ARIA tools.

    Imports of bidi dependencies are deferred so that the text-mode path
    (``from aria.voice_agent import ...``) does not fail when optional
    packages are absent — the ImportError only surfaces at call-time.

    Args:
        authenticated: True if the customer has already been authenticated.
        customer_id:   Customer ID for authenticated sessions.

    Returns:
        BidiAgent instance ready for ``await agent.run(inputs, outputs)``.

    Raises:
        ImportError: If strands-agents[bidi] or pyaudio are not installed.
        ValueError / RuntimeError: If AWS credentials cannot be resolved.
    """
    try:
        from strands.experimental.bidi import BidiAgent, stop_conversation
        from strands.experimental.bidi.models.nova_sonic import BidiNovaSonicModel
    except ImportError as exc:
        raise ImportError(
            "Voice mode requires additional dependencies.  Install with:\n"
            "  pip install 'strands-agents[bidi]' pyaudio\n"
            f"Original error: {exc}"
        ) from exc

    from aria.tools import ALL_TOOLS

    region = _resolve_nova_region()
    session = _build_boto_session(region)
    model_id = os.getenv("NOVA_SONIC_MODEL_ID", _NOVA_SONIC_MODEL_ID)
    voice_system_prompt = _build_voice_system_prompt(authenticated, customer_id)

    logger.info(
        "Initialising BidiNovaSonicModel | model=%s region=%s voice=%s endpointing=%s",
        model_id, region, _NOVA_VOICE, _ENDPOINTING,
    )

    model = BidiNovaSonicModel(
        model_id=model_id,
        provider_config={
            "audio": {
                "voice": _NOVA_VOICE,
            },
            "inference": {
                "max_tokens": int(os.getenv("NOVA_SONIC_MAX_TOKENS", "2048")),
                "top_p": float(os.getenv("NOVA_SONIC_TOP_P", "0.9")),
                "temperature": float(os.getenv("NOVA_SONIC_TEMPERATURE", "0.7")),
            },
            "turn_detection": {
                "endpointingSensitivity": _ENDPOINTING,
            },
        },
        client_config={"boto_session": session},
    )

    agent = BidiAgent(
        model=model,
        system_prompt=voice_system_prompt,
        tools=[*ALL_TOOLS, stop_conversation],
    )
    logger.info(
        "BidiAgent (Nova Sonic) ready | tools=%d session=%s",
        len(ALL_TOOLS) + 1,
        "authenticated" if authenticated else "unauthenticated",
    )
    return agent


# ---------------------------------------------------------------------------
# Session runner — public entry point called from main.py
# ---------------------------------------------------------------------------

async def run_voice_session(authenticated: bool, customer_id: str | None) -> None:
    """Run a full Nova Sonic 2 S2S voice session.

    Lifecycle:
    1. Validates pyaudio is importable (fail-fast with a clear message).
    2. Creates the BidiAgent with the session-start context pre-loaded.
    3. Opens BidiAudioIO (mic at 16 kHz → Bedrock; Bedrock → speaker at 16 kHz).
    4. Registers a terminal output handler for live transcripts.
    5. Blocks until the caller says "stop" or Ctrl-C is pressed.
    6. Gracefully shuts down the Bedrock stream and PyAudio devices.

    Args:
        authenticated: Whether the caller has already been authenticated.
        customer_id:   Customer ID for authenticated sessions.
    """
    # Fail fast if audio deps are missing rather than hanging silently
    try:
        from strands.experimental.bidi.io.audio import BidiAudioIO
    except (ImportError, ModuleNotFoundError) as exc:
        logger.error("Voice audio dependency missing: %s", exc)
        print(
            "\nVoice mode requires additional packages.  Install them with:\n"
            "  pip install 'strands-agents[bidi]' pyaudio\n"
            "  brew install portaudio  (macOS) or  apt-get install portaudio19-dev  (Linux)\n"
        )
        sys.exit(1)

    try:
        agent = create_aria_voice_agent(authenticated, customer_id)
    except ImportError as exc:
        print(f"\n{exc}\n")
        sys.exit(1)
    except Exception as exc:
        logger.critical("Failed to initialise Nova Sonic voice agent: %s", exc, exc_info=True)
        print(
            "\nARIA Voice could not start.  Check aria.log for details.\n"
            f"Nova Sonic 2 requires one of these regions: {', '.join(sorted(_NOVA_SONIC_REGIONS))}\n"
            "Set NOVA_SONIC_REGION in your environment or .env file.\n"
        )
        sys.exit(1)

    audio_io = BidiAudioIO()
    terminal = _TerminalOutput()

    logger.info(
        "Starting Nova Sonic voice session | authenticated=%s customer_id=%s",
        authenticated, customer_id or "unknown",
    )

    try:
        await agent.run(
            inputs=[audio_io.input()],
            outputs=[audio_io.output(), terminal],
        )
    except KeyboardInterrupt:
        logger.info("Voice session interrupted by user (Ctrl-C)")
        print("\n\nARIA: Thank you for calling Meridian Bank. Goodbye.\n")
    except asyncio.CancelledError:
        logger.info("Voice session task cancelled")
    except Exception as exc:
        logger.error("Voice session error: %s", exc, exc_info=True)
        print(
            "\nARIA: I'm sorry, I'm experiencing a technical issue. "
            "Please hold while I transfer you to an advisor.\n"
        )
    finally:
        logger.info("Voice session ended")
