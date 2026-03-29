"""AgentCore Memory wrapper for ARIA conversation history.

Provides save/retrieve helpers backed by Amazon Bedrock AgentCore Memory.
When ``AGENTCORE_MEMORY_ID`` is not set, all operations are no-ops so the
agent works identically in local mode without any code-path changes.

Memory is used to persist conversation turns across multiple /invocations
calls within the same logical session, enabling multi-turn banking dialogues
where the customer can ask follow-up questions without re-stating context.

Note: PII vault data is intentionally NOT stored in AgentCore Memory.
The in-memory _VAULT dict is correct for session-scoped PII because:
  - AgentCore Runtime provides microVM isolation per session
  - PII vault has a max TTL of 900 s and should expire with the session
  - AgentCore Memory is for conversation history, not ephemeral secure tokens
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("aria.memory")

# Memory resource ID provisioned during agentcore deploy.
# When absent, all operations silently become no-ops.
_MEMORY_ID: Optional[str] = os.getenv("AGENTCORE_MEMORY_ID")
_REGION: str = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))

_client = None  # Lazy-initialised MemoryClient


def _get_client():
    """Return a cached MemoryClient, or None if memory is not configured."""
    global _client
    if not _MEMORY_ID:
        return None
    if _client is None:
        try:
            from bedrock_agentcore.memory import MemoryClient
            _client = MemoryClient(region_name=_REGION)
            logger.info("AgentCore MemoryClient initialised (region=%s, memory_id=%s)", _REGION, _MEMORY_ID)
        except Exception as exc:  # pragma: no cover
            logger.warning("Could not initialise AgentCore MemoryClient: %s", exc)
            return None
    return _client


def save_turn(
    actor_id: str,
    session_id: str,
    user_text: str,
    aria_text: str,
) -> None:
    """Persist a single conversation turn to AgentCore Memory.

    Args:
        actor_id:   Customer ID (e.g. ``CUST-001``) or ``anonymous``.
        session_id: AgentCore session ID.
        user_text:  Raw customer utterance (PII already redacted by tool pipeline).
        aria_text:  ARIA's response text.
    """
    client = _get_client()
    if not client:
        return
    try:
        client.save_conversation(
            memory_id=_MEMORY_ID,
            actor_id=actor_id,
            session_id=session_id,
            messages=[("user", user_text), ("assistant", aria_text)],
            event_timestamp=datetime.now(timezone.utc),
        )
        logger.debug("Saved conversation turn to memory (session=%s)", session_id)
    except Exception as exc:
        logger.warning("Failed to save conversation turn to memory: %s", exc)


def get_recent_turns(
    actor_id: str,
    session_id: str,
    k: int = 5,
) -> list[dict]:
    """Retrieve the last k conversation turns for this session.

    Returns a flat list of ``{"role": "user"|"assistant", "content": str}`` dicts
    in chronological order, ready to be prepended to the agent context.
    Returns an empty list if memory is not configured or on any error.

    Args:
        actor_id:   Customer ID.
        session_id: AgentCore session ID.
        k:          Number of most-recent turns to retrieve (default 5).
    """
    client = _get_client()
    if not client:
        return []
    try:
        turns = client.get_last_k_turns(
            memory_id=_MEMORY_ID,
            actor_id=actor_id,
            session_id=session_id,
            k=k,
        )
        messages = []
        for turn in turns:
            for msg in turn:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if isinstance(content, list):
                    content = " ".join(
                        c.get("text", "") for c in content if isinstance(c, dict)
                    )
                messages.append({"role": role, "content": content})
        logger.debug(
            "Retrieved %d messages from memory (session=%s)", len(messages), session_id
        )
        return messages
    except Exception as exc:
        logger.warning("Failed to retrieve conversation turns from memory: %s", exc)
        return []
