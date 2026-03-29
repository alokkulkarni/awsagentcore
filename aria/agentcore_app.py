"""ARIA Banking Agent — Amazon Bedrock AgentCore Runtime Entrypoint.

This module exposes both channels through a single ``BedrockAgentCoreApp``:

  POST /invocations  →  chat channel (Strands Agent + Claude Sonnet 4.6)
  GET  /ping         →  health check (handled automatically by the framework)
  WS   /ws           →  voice channel (Nova Sonic 2 S2S via WebSocket)

**Chat payload (client → server)**::

    {
      "message":       "What is my account balance?",   # required
      "authenticated": true,                              # optional; first call only
      "customer_id":   "CUST-001"                        # optional; first call only
    }

**WebSocket protocol**: see ``aria/agentcore_voice.py`` for the full spec.

The app is started by Dockerfile via::

    uvicorn aria.agentcore_app:app --host 0.0.0.0 --port 8080 --workers 1

For local development::

    uvicorn aria.agentcore_app:app --port 8080 --reload
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from typing import Optional

from bedrock_agentcore import BedrockAgentCoreApp
from bedrock_agentcore.runtime.context import RequestContext
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from aria.agentcore_voice import ARIAWebSocketVoiceSession
from aria.audit_manager import emit_chat_tool_audits as _emit_audit

logger = logging.getLogger("aria.agentcore")

# ---------------------------------------------------------------------------
# Application instance
# ---------------------------------------------------------------------------

# Allow all origins in development (CORS required for React dev server → localhost)
# In production (AgentCore), the runtime proxy handles auth — CORS is irrelevant.
_cors_middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
]

app = BedrockAgentCoreApp(middleware=_cors_middleware)

# ---------------------------------------------------------------------------
# Session state (per-microVM in-memory cache)
#
# AgentCore Runtime guarantees that all requests within the same session_id
# are routed to the same microVM process, so a plain dict is safe here.
# ---------------------------------------------------------------------------

_CHAT_AGENTS: dict[str, object] = {}    # session_id → Strands Agent

# Each value: {"authenticated": bool, "customer_id": str | None}
_SESSION_META: dict[str, dict] = {}

# Transcript managers keyed by session_id
_TRANSCRIPTS: dict[str, object] = {}

# Session IDs that have already received the SESSION_START injection
_SESSION_STARTED: set[str] = set()


# ---------------------------------------------------------------------------
# Helper: build SESSION_START trigger (mirrors main.py logic)
# ---------------------------------------------------------------------------

def _build_session_start(
    authenticated: bool, customer_id: Optional[str], channel: str
) -> str:
    channel_line = f"X-Channel: {channel}. "
    if authenticated and customer_id:
        return (
            "SESSION_START: An authenticated customer has connected. "
            "X-Channel-Auth: authenticated. "
            f"X-Customer-ID: {customer_id}. "
            + channel_line
            + "Call get_customer_details with this customer ID to fetch their profile, "
            "then greet them by their preferred_name and ask how you can help today. "
            "Do not ask them to re-verify their identity."
        )
    return (
        "SESSION_START: A new customer has connected on an unauthenticated channel. "
        "X-Channel-Auth: unauthenticated. "
        + channel_line
        + "Greet them as ARIA from Meridian Bank and begin the identity verification flow."
    )


def _clean_response(text: str) -> str:
    """Strip markdown from ARIA's response for API consumers."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"_(.+?)_", r"\1", text)
    text = re.sub(r"#{1,6}\s*", "", text)
    text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.MULTILINE)
    return text.strip()


_FAREWELL_WORDS = frozenset({
    "goodbye", "good bye", "bye", "farewell", "that's all",
    "thank you goodbye", "thanks goodbye", "no more", "all done",
})


def _maybe_save_transcript(transcript, aria_text: str) -> None:
    """Save the transcript to S3 after every turn (durable in case of crash)
    and perform a final save when a farewell is detected in ARIA's response."""
    lower = aria_text.lower()
    if any(w in lower for w in ("goodbye", "take care", "farewell", "pleasure helping")):
        transcript.save()
    else:
        # Incremental save: overwrite S3 object with latest content each turn.
        # This ensures no transcript is lost if the microVM is recycled.
        transcript._saved = False   # allow re-save
        transcript.save()
        transcript._saved = False   # keep open for future turns


# ---------------------------------------------------------------------------
# Chat handler — POST /invocations
# ---------------------------------------------------------------------------

@app.entrypoint
def chat_handler(payload: dict, context: RequestContext) -> str:
    """Process a single chat turn and return ARIA's response.

    On the first call within a session the handler transparently injects a
    ``SESSION_START`` trigger so ARIA fetches the customer profile and greets
    by name before answering the customer's first message.

    Returns:
        ARIA's plain-text response (markdown stripped).
    """
    session_id = context.session_id or str(uuid.uuid4())

    # ------------------------------------------------------------------
    # Extract message and one-time auth metadata from payload
    # ------------------------------------------------------------------
    user_message: str = (payload.get("message") or "").strip()
    if not user_message:
        return "I'm sorry, I didn't receive a message. Could you please try again?"

    # Auth metadata only needed on first call; ignored silently thereafter
    authenticated: bool = bool(payload.get("authenticated", False))
    customer_id: Optional[str] = payload.get("customer_id") or None

    # ------------------------------------------------------------------
    # Get or create the Strands Agent for this session
    # ------------------------------------------------------------------
    if session_id not in _CHAT_AGENTS:
        from aria.agent import create_aria_agent
        from aria.transcript_manager import TranscriptManager
        _CHAT_AGENTS[session_id] = create_aria_agent()
        _SESSION_META[session_id] = {
            "authenticated": authenticated,
            "customer_id":   customer_id,
        }
        _TRANSCRIPTS[session_id] = TranscriptManager(
            session_id=session_id,
            customer_id=customer_id,
            channel="agentcore-chat",
            authenticated=authenticated,
        )
        logger.info(
            "Created new chat agent session: %s authenticated=%s customer_id=%s",
            session_id, authenticated, customer_id,
        )

    agent = _CHAT_AGENTS[session_id]
    meta  = _SESSION_META[session_id]
    transcript = _TRANSCRIPTS[session_id]

    # ------------------------------------------------------------------
    # Retrieve conversation history from AgentCore Memory (if configured)
    # ------------------------------------------------------------------
    actor_id = meta.get("customer_id") or "anonymous"
    try:
        from aria import memory_client
        history = memory_client.get_recent_turns(actor_id, session_id, k=5)
        if history:
            logger.debug("Loaded %d memory messages for session %s", len(history), session_id)
    except Exception as exc:
        logger.warning("Memory retrieval skipped: %s", exc)
        history = []

    # ------------------------------------------------------------------
    # Build prompt — inject SESSION_START on first turn only
    # ------------------------------------------------------------------
    if session_id not in _SESSION_STARTED:
        _SESSION_STARTED.add(session_id)
        session_start = _build_session_start(
            meta["authenticated"], meta["customer_id"], channel="agentcore-chat"
        )
        # Combine SESSION_START with the customer's first message in a single
        # LLM call to avoid an extra round-trip.
        prompt = (
            f"{session_start}\n\n"
            f"Customer's first message: {user_message}"
        )
        logger.info("Injecting SESSION_START for session %s", session_id)
    else:
        prompt = user_message

    # ------------------------------------------------------------------
    # Call the Strands Agent
    # ------------------------------------------------------------------
    _msg_idx = len(agent.messages)
    try:
        result = agent(prompt)
        aria_text = _clean_response(str(result))
    except Exception as exc:
        logger.error("Agent error in session %s: %s", session_id, exc, exc_info=True)
        aria_text = (
            "I'm sorry, I'm experiencing a technical issue. "
            "Please try again or call our main line on 0161 900 9900."
        )

    # Emit audit events for every tool call made during this turn
    _emit_audit(
        agent.messages, _msg_idx,
        customer_id=meta.get("customer_id"),
        session_id=session_id,
        channel="agentcore-chat",
        authenticated=meta.get("authenticated", False),
    )

    # ------------------------------------------------------------------
    # Save turn to AgentCore Memory (async-friendly: best-effort fire)
    # ------------------------------------------------------------------
    try:
        from aria import memory_client
        memory_client.save_turn(actor_id, session_id, user_message, aria_text)
    except Exception as exc:
        logger.warning("Memory save skipped: %s", exc)

    # Save to transcript (appends turn; S3 upload on farewell/session end)
    transcript.add_turn("Customer", user_message)
    transcript.add_turn("ARIA", aria_text)
    _maybe_save_transcript(transcript, aria_text)

    return aria_text


# ---------------------------------------------------------------------------
# Voice handler — WebSocket /ws
# ---------------------------------------------------------------------------

@app.websocket
async def voice_handler(websocket, context: RequestContext) -> None:
    """Bridge a WebSocket audio connection to Nova Sonic 2 S2S.

    The WebSocket client supplies microphone audio as binary messages and
    receives ARIA's voice output as binary messages.  All text events
    (transcripts, session lifecycle) are sent as JSON text messages.

    See ``aria/agentcore_voice.py`` for the full message protocol.
    """
    session_id = context.session_id or str(uuid.uuid4())
    logger.info("Voice WebSocket connected: session_id=%s", session_id)

    session = ARIAWebSocketVoiceSession(
        session_id=session_id,
        websocket=websocket,
    )
    await session.run()

    logger.info("Voice WebSocket session ended: session_id=%s", session_id)


# ---------------------------------------------------------------------------
# Local dev / Docker entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    log_level = os.getenv("LOG_LEVEL", "info").lower()
    port      = int(os.getenv("PORT", "8080"))

    logger.info("Starting ARIA AgentCore app on 0.0.0.0:%d", port)
    uvicorn.run(
        "aria.agentcore_app:app",
        host="0.0.0.0",
        port=port,
        log_level=log_level,
        workers=1,   # single worker: session cache is in-process memory
    )
