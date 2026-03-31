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
import logging.handlers
import os
import re
import uuid
from pathlib import Path
from typing import Optional

from bedrock_agentcore import BedrockAgentCoreApp
from bedrock_agentcore.runtime.context import RequestContext
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from aria.agentcore_voice import ARIAWebSocketVoiceSession
from aria.audit_manager import emit_chat_tool_audits as _emit_audit

# ---------------------------------------------------------------------------
# Logging — configure once at import time so all aria.* loggers get handlers.
# When running via `uvicorn aria.agentcore_app:app`, uvicorn configures its own
# logging for the uvicorn.* namespace only — our application loggers have no
# handlers unless we add them explicitly here.
# ---------------------------------------------------------------------------
def _configure_logging() -> None:
    _log_dir  = Path(os.getenv("LOG_DIR", "."))
    _log_file = _log_dir / "aria_agentcore.log"
    _level    = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)

    root = logging.getLogger()
    if root.handlers:
        # Already configured (e.g., called twice via uvicorn reload) — skip
        return

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # File handler — rotating, 10 MB × 5 backups
    fh = logging.handlers.RotatingFileHandler(
        _log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(fmt)

    # Console handler — so logs also appear in uvicorn's terminal output
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)

    root.setLevel(_level)
    root.addHandler(fh)
    root.addHandler(sh)

    # Keep noisy third-party libs quiet
    for _noisy in ("strands", "botocore", "boto3", "urllib3", "opentelemetry", "httpcore"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)

    logging.getLogger("aria").info(
        "ARIA logging configured → console + %s (level=%s)",
        _log_file, logging.getLevelName(_level),
    )


_configure_logging()

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

# Sessions that have been closed via a farewell — will be purged on next contact
_ENDED_SESSIONS: set[str] = set()

_FAREWELL_RESPONSE_WORDS = frozenset({
    "goodbye", "take care", "farewell", "pleasure helping", "all the best",
    "have a great", "thank you for calling", "thanks for calling",
})


def _extract_vulnerability_from_messages(messages: list, from_index: int) -> Optional[dict]:
    """Scan new agent messages for a get_customer_details result that contains
    a non-null vulnerability field, and return it as a plain dict for audit tagging."""
    import json as _json
    for msg in messages[from_index:]:
        for block in (msg.get("content") or []):
            if "toolResult" not in block:
                continue
            tr = block["toolResult"]
            for content_item in (tr.get("content") or []):
                raw = content_item.get("text", "") if isinstance(content_item, dict) else ""
                if not raw:
                    continue
                try:
                    data = _json.loads(raw)
                except Exception:
                    continue
                vuln = data.get("vulnerability")
                if vuln and isinstance(vuln, dict) and vuln.get("flag_type"):
                    return vuln
    return None


def _extract_escalation_from_messages(messages: list, from_index: int) -> Optional[dict]:
    """Scan new agent messages for a successful escalate_to_human_agent tool result.

    Returns the handoff metadata dict if the tool returned handoff_status
    'accepted' or 'queued', otherwise None.
    """
    import json as _json
    for msg in messages[from_index:]:
        for block in (msg.get("content") or []):
            if "toolResult" not in block:
                continue
            tr = block["toolResult"]
            for content_item in (tr.get("content") or []):
                raw = content_item.get("text", "") if isinstance(content_item, dict) else ""
                if not raw:
                    continue
                try:
                    data = _json.loads(raw)
                except Exception:
                    continue
                if data.get("handoff_status") in ("accepted", "queued"):
                    return {
                        "handoff_status": data.get("handoff_status"),
                        "handoff_ref": data.get("handoff_ref"),
                        "estimated_wait_seconds": data.get("estimated_wait_seconds"),
                        "agent_id": data.get("agent_id"),
                    }
    return None

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


def _is_farewell_response(text: str) -> bool:
    # Only inspect the final 150 characters — farewell phrases are always at the
    # end of a response. Scanning the full text causes false-positives on phrases
    # like "I can take care of that for you" or "pleasure helping" mid-sentence.
    tail = text[-150:].lower() if len(text) > 150 else text.lower()
    return any(w in tail for w in _FAREWELL_RESPONSE_WORDS)


def _purge_session(session_id: str) -> None:
    """Remove all server-side state for a session after it ends gracefully."""
    _CHAT_AGENTS.pop(session_id, None)
    _SESSION_META.pop(session_id, None)
    _TRANSCRIPTS.pop(session_id, None)
    _SESSION_STARTED.discard(session_id)
    _ENDED_SESSIONS.discard(session_id)


def _maybe_save_transcript(transcript, aria_text: str) -> None:
    """Save the transcript to S3 after every turn."""
    transcript._saved = False
    transcript.save()
    transcript._saved = False


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
    # If the session ended cleanly (farewell), start a fresh one
    # ------------------------------------------------------------------
    if session_id in _ENDED_SESSIONS:
        _purge_session(session_id)
        logger.info("Restarting ended session %s", session_id)

    # ------------------------------------------------------------------
    # Get or create the Strands Agent for this session
    # ------------------------------------------------------------------
    if session_id not in _CHAT_AGENTS:
        from aria.agent import create_aria_agent
        from aria.transcript_manager import TranscriptManager

        # Load cross-session memory BEFORE creating the agent so it can be injected
        # into the system prompt — matching what agentcore_voice.py does.
        # This must happen at agent creation, not per-turn: the Strands agent accumulates
        # its own conversation in agent.messages across turns; the history block is only
        # meaningful for restoring context from a prior session.
        history_block = ""
        _history_actor_id = customer_id or "anonymous"
        try:
            from aria import memory_client as _mc_init
            prior_turns = _mc_init.get_recent_turns(_history_actor_id, session_id, k=5)
            if prior_turns:
                lines = [
                    f"{'Customer' if m['role'] == 'user' else 'ARIA'}: {m['content']}"
                    for m in prior_turns
                ]
                history_block = (
                    "\n=== RECENT CONVERSATION HISTORY (for context) ===\n"
                    + "\n".join(lines)
                    + "\n=== END HISTORY ===\n\n"
                )
                logger.info(
                    "Injecting %d memory turns into chat agent (session=%s)",
                    len(prior_turns), session_id,
                )
        except Exception as _mem_init_exc:
            logger.warning("Memory load for new chat session skipped: %s", _mem_init_exc)

        _CHAT_AGENTS[session_id] = create_aria_agent(prior_history_block=history_block)
        _SESSION_META[session_id] = {
            "authenticated": authenticated,
            "customer_id":   customer_id,
            "vulnerability": None,  # populated on first get_customer_details result
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
    actor_id = meta.get("customer_id") or "anonymous"

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

        # When the LLM only calls tools (PII detect/store, initiate_auth, etc.)
        # without generating a text response in the same turn, str(result) is
        # empty. Scan the new agent messages for the last assistant text block.
        if not aria_text:
            for msg in reversed(agent.messages[_msg_idx:]):
                if msg.get("role") == "assistant":
                    content = msg.get("content", [])
                    # content may be a plain string (Strands inline format)
                    if isinstance(content, str):
                        candidate = _clean_response(content)
                        if candidate:
                            aria_text = candidate
                    else:
                        for block in content:
                            if isinstance(block, str):
                                candidate = _clean_response(block)
                            elif isinstance(block, dict):
                                candidate = _clean_response(
                                    block.get("text", "") or block.get("content", "")
                                )
                            else:
                                candidate = ""
                            if candidate:
                                aria_text = candidate
                                break
                if aria_text:
                    break

        # If still empty, ask the agent to continue explicitly
        if not aria_text:
            logger.info("Empty agent response for session %s — prompting continuation", session_id)
            result2 = agent("Please continue and respond to the customer.")
            aria_text = _clean_response(str(result2))

        if not aria_text:
            aria_text = "I'm sorry, I didn't catch that. Could you please try again?"

    except Exception as exc:
        logger.error("Agent error in session %s: %s", session_id, exc, exc_info=True)
        aria_text = (
            "I'm sorry, I'm experiencing a technical issue. "
            "Please try again or call our main line on 0161 900 9900."
        )

    # Extract vulnerability flag from get_customer_details result (first time only)
    if meta.get("vulnerability") is None:
        detected = _extract_vulnerability_from_messages(agent.messages, _msg_idx)
        if detected:
            meta["vulnerability"] = detected
            logger.info(
                "Vulnerability flag detected for session %s: %s",
                session_id, detected.get("flag_type"),
            )

    # Emit audit events for every tool call made during this turn,
    # tagging all events if this is a vulnerable-customer session
    _emit_audit(
        agent.messages, _msg_idx,
        customer_id=meta.get("customer_id"),
        session_id=session_id,
        channel="agentcore-chat",
        authenticated=meta.get("authenticated", False),
        vulnerability=meta.get("vulnerability"),
    )

    # Detect successful escalation — end the session and prepare transfer signal
    escalation = _extract_escalation_from_messages(agent.messages, _msg_idx)
    if escalation:
        logger.info(
            "Escalation completed for session %s — handoff_ref=%s status=%s",
            session_id, escalation.get("handoff_ref"), escalation.get("handoff_status"),
        )
        _ENDED_SESSIONS.add(session_id)

    # ------------------------------------------------------------------
    # Save turn to AgentCore Memory (async-friendly: best-effort fire)
    # ------------------------------------------------------------------
    try:
        from aria import memory_client
        memory_client.save_turn(actor_id, session_id, user_message, aria_text)
    except Exception as exc:
        logger.warning("Memory save skipped: %s", exc)

    # Save to transcript and handle farewell / session teardown
    transcript.add_turn("Customer", user_message)
    transcript.add_turn("ARIA", aria_text)
    _maybe_save_transcript(transcript, aria_text)

    # Mark session as ended if ARIA said a farewell — next message from this
    # session_id will get a clean slate rather than a stale "session ended" reply.
    if not escalation and _is_farewell_response(aria_text):
        logger.info("Farewell detected — marking session %s as ended", session_id)
        _ENDED_SESSIONS.add(session_id)

    # Return structured JSON when a transfer occurred so the frontend can
    # show the handoff UI and disable the chat input. Plain text otherwise.
    if escalation:
        import json as _json
        return _json.dumps({
            "response": aria_text,
            "transfer": True,
            "handoff_ref": escalation.get("handoff_ref"),
            "estimated_wait_seconds": escalation.get("estimated_wait_seconds"),
            "session_ended": True,
        })

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
    try:
        await session.run()
    except Exception as exc:
        logger.error("Unhandled exception in voice_handler (session_id=%s): %s", session_id, exc, exc_info=True)

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
