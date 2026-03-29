"""ARIA Audit Manager — records immutable audit events for banking compliance.

Every tool invocation that reads or modifies customer data is recorded as a
structured JSON event.  Events are written to a local JSONL file and/or
published to an Amazon EventBridge custom bus for fan-out to CloudTrail Lake,
DynamoDB, and S3 WORM storage.

**Local mode** (default — when running via ``main.py``):
  Appends a JSONL line to ``AUDIT_DIR/{customer_id}/{YYYY-MM-DD}/audit.jsonl``.
  One JSON object per line; files are append-only and never overwritten.

**EventBridge mode** (AgentCore / cloud deployment):
  Publishes a ``BankingAuditEvent`` to the custom bus named in
  ``AUDIT_EVENTBRIDGE_BUS``.  Downstream EventBridge rules route events to
  CloudTrail Lake (immutable), DynamoDB (hot queries), and S3 WORM (archive).

**Both** (set ``AUDIT_STORE=both``):
  Writes locally AND publishes to EventBridge.

Tool tiers
----------
Tier 1 — Critical   : irreversible / high-value actions (card block, auth, escalation)
Tier 2 — Significant: data access (PII, account, card, mortgage, PII vault)
Tier 3 — Informational: public/non-sensitive reads (catalogue, KB, transcript summary)

Environment variables
---------------------
AUDIT_DIR               Local JSONL directory.  Default: ``./audit``
AUDIT_EVENTBRIDGE_BUS   EventBridge bus name or full ARN.  Required for cloud mode.
AUDIT_REGION            AWS region for EventBridge client.  Default: ``AWS_REGION``.
AUDIT_STORE             ``local`` | ``eventbridge`` | ``both``.
                        Auto-detected: ``eventbridge`` when AUDIT_EVENTBRIDGE_BUS
                        is set, ``local`` otherwise.  Override with this variable.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("aria.audit")

# ---------------------------------------------------------------------------
# Configuration (read once at import time)
# ---------------------------------------------------------------------------

_AUDIT_DIR  = os.getenv("AUDIT_DIR", "./audit")
_EB_BUS     = os.getenv("AUDIT_EVENTBRIDGE_BUS", "").strip()
_EB_REGION  = os.getenv("AUDIT_REGION", os.getenv("AWS_REGION", "eu-west-2"))


def _resolve_store() -> str:
    explicit = os.getenv("AUDIT_STORE", "").strip().lower()
    if explicit in ("local", "eventbridge", "both"):
        return explicit
    return "eventbridge" if _EB_BUS else "local"


_STORE = _resolve_store()

# ---------------------------------------------------------------------------
# Tool audit metadata
# (event_type, category, tier, severity)
# ---------------------------------------------------------------------------

_TOOL_META: dict[str, tuple[str, str, int, str]] = {
    # --- Tier 1: Critical ---
    "block_debit_card":                ("CARD_BLOCK",              "CARD_MANAGEMENT",   1, "CRITICAL"),
    "escalate_to_human_agent":         ("AGENT_ESCALATION",        "ESCALATION",        1, "HIGH"),
    "validate_customer_auth":          ("AUTH_VALIDATION",         "AUTHENTICATION",    1, "HIGH"),
    "verify_customer_identity":        ("IDENTITY_VERIFICATION",   "AUTHENTICATION",    1, "HIGH"),
    "cross_validate_session_identity": ("SESSION_CROSS_VALIDATE",  "AUTHENTICATION",    1, "HIGH"),
    "initiate_customer_auth":          ("AUTH_INITIATION",         "AUTHENTICATION",    1, "HIGH"),
    # --- Tier 2: Significant ---
    "get_customer_details":            ("CUSTOMER_DATA_ACCESS",    "DATA_ACCESS",       2, "MEDIUM"),
    "get_account_details":             ("ACCOUNT_DATA_ACCESS",     "DATA_ACCESS",       2, "MEDIUM"),
    "get_debit_card_details":          ("DEBIT_CARD_DATA_ACCESS",  "DATA_ACCESS",       2, "MEDIUM"),
    "get_credit_card_details":         ("CREDIT_CARD_DATA_ACCESS", "DATA_ACCESS",       2, "MEDIUM"),
    "get_mortgage_details":            ("MORTGAGE_DATA_ACCESS",    "DATA_ACCESS",       2, "MEDIUM"),
    "analyse_spending":                ("SPENDING_ANALYSIS",       "DATA_ACCESS",       2, "MEDIUM"),
    "pii_vault_store":                 ("PII_VAULT_STORE",         "PII",               2, "MEDIUM"),
    "pii_vault_retrieve":              ("PII_VAULT_RETRIEVE",      "PII",               2, "MEDIUM"),
    "pii_vault_purge":                 ("PII_VAULT_PURGE",         "PII",               2, "MEDIUM"),
    # --- Tier 3: Informational ---
    "get_product_catalogue":           ("PRODUCT_CATALOGUE_VIEW",  "INFORMATIONAL",     3, "LOW"),
    "search_knowledge_base":           ("KB_SEARCH",               "INFORMATIONAL",     3, "LOW"),
    "get_feature_parity":              ("FEATURE_PARITY_VIEW",     "INFORMATIONAL",     3, "LOW"),
    "generate_transcript_summary":     ("TRANSCRIPT_SUMMARY",      "INFORMATIONAL",     3, "LOW"),
    "pii_detect_and_redact":           ("PII_DETECT_REDACT",       "PII",               3, "LOW"),
}

# Keys whose values should always be masked in audit records (PCI-DSS / GDPR)
_SENSITIVE_KEYS = frozenset({
    "pin", "cvv", "cvv2", "password", "passcode", "secret",
    "access_key", "secret_key", "token",
})

# ---------------------------------------------------------------------------
# Parameter sanitiser
# ---------------------------------------------------------------------------

def _sanitise_params(params: dict) -> dict:
    """Return a copy of *params* with sensitive values masked.

    Rules:
    - Any key whose name matches a known sensitive pattern → ``"***"``
    - Any string value that is purely digits and ≥ 13 characters (PAN-like) → ``"***REDACTED***"``
    - All other values are passed through unchanged.
    """
    out: dict = {}
    for k, v in params.items():
        key_lower = k.lower()
        if any(s in key_lower for s in _SENSITIVE_KEYS):
            out[k] = "***"
        elif isinstance(v, str) and re.fullmatch(r"\d{13,19}", v.replace(" ", "")):
            out[k] = "***REDACTED***"
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# AuditManager
# ---------------------------------------------------------------------------

class AuditManager:
    """Emits structured banking audit events for every tool invocation.

    This class is intentionally stateless — all session context is passed to
    :meth:`record` on each call so the same instance can serve multiple
    concurrent sessions safely.

    Instantiate once at module level and call :meth:`record` from any tool
    execution path (voice or chat).
    """

    def record(
        self,
        *,
        tool_name:     str,
        customer_id:   Optional[str],
        session_id:    str,
        channel:       str,
        authenticated: bool,
        parameters:    dict,
        outcome:       str,          # "SUCCESS" | "FAILURE"
        error_message: Optional[str] = None,
    ) -> None:
        """Build and emit an audit event.

        Args:
            tool_name:     Name of the Strands tool that was invoked.
            customer_id:   Authenticated customer identifier (or None).
            session_id:    ARIA session UUID.
            channel:       ``"chat"`` | ``"voice"`` | ``"agentcore-chat"`` | ``"agentcore-voice"``
            authenticated: Whether the session has passed identity verification.
            parameters:    Tool input arguments (sensitive values auto-masked).
            outcome:       ``"SUCCESS"`` or ``"FAILURE"``.
            error_message: Human-readable error detail on failure.
        """
        meta = _TOOL_META.get(
            tool_name,
            ("TOOL_INVOCATION", "UNKNOWN", 3, "LOW"),
        )
        event_type, category, tier, severity = meta

        event: dict[str, Any] = {
            "event_id":       str(uuid.uuid4()),
            "event_type":     event_type,
            "category":       category,
            "tier":           tier,
            "severity":       severity,
            "timestamp":      datetime.now(timezone.utc).isoformat(),
            "session_id":     session_id,
            "customer_id":    customer_id or "anonymous",
            "channel":        channel,
            "actor":          "ARIA",
            "actor_type":     "AI_AGENT",
            "tool_name":      tool_name,
            "parameters":     _sanitise_params(parameters),
            "outcome":        outcome,
            "error_message":  error_message,
            "authenticated":  authenticated,
        }

        self._dispatch(event, tier, severity, tool_name, outcome, session_id, customer_id)

    async def async_record(
        self,
        *,
        tool_name:     str,
        customer_id:   Optional[str],
        session_id:    str,
        channel:       str,
        authenticated: bool,
        parameters:    dict,
        outcome:       str,
        error_message: Optional[str] = None,
    ) -> None:
        """Fire-and-forget version for use inside ``async`` voice agent loops.

        All I/O (local JSONL write, EventBridge PutEvents) is offloaded to a
        thread-pool worker via :func:`asyncio.to_thread` so the asyncio event
        loop is **never blocked**, preserving audio streaming latency.
        """
        import asyncio
        # Build event on the calling coroutine (cheap, no I/O) then dispatch
        # the I/O portion in a thread.
        meta = _TOOL_META.get(tool_name, ("TOOL_INVOCATION", "UNKNOWN", 3, "LOW"))
        event_type, category, tier, severity = meta
        event: dict[str, Any] = {
            "event_id":       str(uuid.uuid4()),
            "event_type":     event_type,
            "category":       category,
            "tier":           tier,
            "severity":       severity,
            "timestamp":      datetime.now(timezone.utc).isoformat(),
            "session_id":     session_id,
            "customer_id":    customer_id or "anonymous",
            "channel":        channel,
            "actor":          "ARIA",
            "actor_type":     "AI_AGENT",
            "tool_name":      tool_name,
            "parameters":     _sanitise_params(parameters),
            "outcome":        outcome,
            "error_message":  error_message,
            "authenticated":  authenticated,
        }
        # Dispatch I/O in a background thread — never awaited, never blocks loop
        asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._dispatch(event, tier, severity, tool_name, outcome, session_id, customer_id),
        )

    def _dispatch(
        self,
        event: dict,
        tier: int, severity: str, tool_name: str, outcome: str,
        session_id: str, customer_id: Optional[str],
    ) -> None:
        store = _STORE
        if store in ("local", "both"):
            self._write_local(event)
        if store in ("eventbridge", "both") and _EB_BUS:
            self._publish_eventbridge(event)

        logger.debug(
            "Audit[tier=%d %s] tool=%s outcome=%s session=%s customer=%s",
            tier, severity, tool_name, outcome, session_id[:8], customer_id,
        )

    # ------------------------------------------------------------------
    # Local JSONL backend
    # ------------------------------------------------------------------

    def _write_local(self, event: dict) -> None:
        cid      = re.sub(r"[^\w\-]", "_", event["customer_id"])
        date_str = event["timestamp"][:10]           # YYYY-MM-DD
        path     = Path(_AUDIT_DIR) / cid / date_str / "audit.jsonl"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, default=str) + "\n")
        except Exception as exc:
            logger.error("Failed to write local audit event: %s", exc)

    # ------------------------------------------------------------------
    # EventBridge backend
    # ------------------------------------------------------------------

    def _publish_eventbridge(self, event: dict) -> None:
        try:
            import boto3
            client = boto3.client("events", region_name=_EB_REGION)
            response = client.put_events(
                Entries=[{
                    "Source":      "com.meridianbank.aria",
                    "DetailType":  "BankingAuditEvent",
                    "Detail":      json.dumps(event, default=str),
                    "EventBusName": _EB_BUS,
                }]
            )
            if response.get("FailedEntryCount", 0):
                logger.error(
                    "EventBridge PutEvents partial failure: %s",
                    response.get("Entries"),
                )
        except Exception as exc:
            # Never raise — audit failure must not break the banking session.
            logger.error("Failed to publish audit event to EventBridge: %s", exc)


# ---------------------------------------------------------------------------
# Module-level singleton — import and use directly
# ---------------------------------------------------------------------------

audit = AuditManager()


# ---------------------------------------------------------------------------
# Helper: extract and emit audit events from Strands messages (chat channel)
# ---------------------------------------------------------------------------

def emit_chat_tool_audits(
    messages:      list,
    from_index:    int,
    customer_id:   Optional[str],
    session_id:    str,
    channel:       str,
    authenticated: bool,
) -> None:
    """Inspect Strands agent messages added since *from_index* and emit one
    audit event per tool call/result pair found.

    Strands stores tool interactions in the Bedrock Converse message format::

        # Assistant message — tool use request
        {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": "id1", "name": "get_account_details",
                         "input": {"customer_id": "CUST-001"}}}
        ]}

        # User message — tool result
        {"role": "user", "content": [
            {"toolResult": {"toolUseId": "id1",
                            "content": [{"text": "..."}],
                            "status": "success"}}
        ]}

    Args:
        messages:      The agent's full message list (``agent.messages``).
        from_index:    Index of the first new message to inspect (snapshot
                       ``len(agent.messages)`` before invoking the agent).
        customer_id:   Authenticated customer identifier.
        session_id:    ARIA session UUID.
        channel:       ``"chat"`` or ``"agentcore-chat"``.
        authenticated: Whether the session is authenticated.
    """
    tool_uses:    dict[str, dict] = {}   # toolUseId → {name, input}
    tool_results: dict[str, dict] = {}   # toolUseId → {status, content}

    for msg in messages[from_index:]:
        for block in (msg.get("content") or []):
            if "toolUse" in block:
                tu = block["toolUse"]
                tool_uses[tu["toolUseId"]] = {
                    "name":  tu.get("name", ""),
                    "input": tu.get("input", {}),
                }
            if "toolResult" in block:
                tr = block["toolResult"]
                tool_results[tr["toolUseId"]] = {
                    "status":  tr.get("status", "success"),
                    "content": tr.get("content", []),
                }

    for use_id, use_data in tool_uses.items():
        result   = tool_results.get(use_id, {})
        status   = result.get("status", "success")
        err_msg  = None
        if status == "error":
            content_list = result.get("content") or []
            if content_list and isinstance(content_list[0], dict):
                err_msg = content_list[0].get("text", "")

        audit.record(
            tool_name=use_data["name"],
            customer_id=customer_id,
            session_id=session_id,
            channel=channel,
            authenticated=authenticated,
            parameters=use_data.get("input") or {},
            outcome="SUCCESS" if status == "success" else "FAILURE",
            error_message=err_msg,
        )
