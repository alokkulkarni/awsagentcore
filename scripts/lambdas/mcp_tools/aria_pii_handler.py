"""
Lambda handler: ARIA PII Tools (AgentCore MCP Gateway target)

Tools exposed via MCP:
  - pii_detect_and_redact  — detect and redact PII from text
  - pii_vault_store        — store PII tokens in the session vault
  - pii_vault_retrieve     — retrieve original values from vault tokens
  - pii_vault_purge        — purge all PII for a session
"""

from __future__ import annotations

import json
import logging
import re
import uuid

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DOMAIN = "pii"

_DISPATCH = {}

# In-memory PII vault — replace with AWS Secrets Manager or DynamoDB in production.
_VAULT: dict[str, dict] = {}


def _register(name):
    def decorator(fn):
        _DISPATCH[name] = fn
        return fn
    return decorator



# Per official AWS docs (gateway-add-target-lambda.html):
#   tool name  → context.client_context.custom['bedrockAgentCoreToolName']
#   parameters → event (flat key/value map)
# We also support the JSON-RPC 2.0 format that Connect AI Agent sends through
# the gateway, so both invocation paths work without code changes.
def _parse_tool_call(event: dict, context) -> tuple:
    # ── 1. Tool name ──────────────────────────────────────────────────────────
    raw = ""
    try:
        raw = (context.client_context.custom or {}).get("bedrockAgentCoreToolName", "")
    except Exception:
        logger.debug("context.client_context not available", exc_info=True)
    if not raw:                                      # JSON-RPC fallback
        _p = event.get("params", {})
        if isinstance(_p, str):
            try:
                import json as _j; _p = _j.loads(_p)
            except Exception:
                _p = {}
        raw = (
            _p.get("name")
            or event.get("toolName")
            or event.get("tool_name")
            or ""
        )
    tool_name = raw.split("___", 1)[1] if "___" in raw else raw

    # ── 2. Parameters ─────────────────────────────────────────────────────────
    _p = event.get("params", {})
    if isinstance(_p, str):
        try:
            import json as _j; _p = _j.loads(_p)
        except Exception:
            _p = {}
    params: dict = (
        _p.get("arguments")           # JSON-RPC (Connect AI Agent)
        or event.get("parameters")    # legacy direct invocation
        or event.get("tool_input")    # Bedrock inline-agent format
        or {}
    )
    # Official gateway format: event IS the params (no wrapper keys)
    if not params and not any(k in event for k in
            ("jsonrpc", "method", "params", "toolName", "tool_name", "id")):
        params = {k: v for k, v in event.items()
                  if k not in ("bedrockAgentCoreMessageVersion",)}

    return tool_name, params


# Security: redact PII/sensitive fields before logging
_REDACT_KEYS = frozenset({
    "date_of_birth", "dob", "mobile", "mobile_last_four", "phone", "phone_number",
    "password", "pin", "otp", "cvv", "cvc", "card_number", "full_card_number",
    "account_number", "sort_code", "iban", "secret", "token", "auth_token",
    "access_token", "refresh_token", "credit_card", "debit_card",
})

def _redact_event(event: dict) -> dict:
    """Return a shallow copy of event with sensitive values replaced by ***REDACTED***."""
    return {
        k: "***REDACTED***" if k.lower() in _REDACT_KEYS else v
        for k, v in event.items()
    }

def lambda_handler(event: dict, context) -> dict:
    logger.info("pii event: %s", json.dumps(_redact_event(event)))

    tool_name, params = _parse_tool_call(event, context)

    # Parse stringified inputs if needed
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except json.JSONDecodeError:
            params = {}

    handler_fn = _DISPATCH.get(tool_name)
    if not handler_fn:
        logger.warning("Unknown tool: %s (domain=%s)", tool_name, DOMAIN)
        return {
            "result": {
                "error": f"Tool '{tool_name}' not found in domain '{DOMAIN}'",
                "available_tools": list(_DISPATCH.keys()),
            }
        }

    try:
        return {"result": handler_fn(params)}
    except Exception as exc:
        logger.exception("Tool %s raised an exception", tool_name)
        return {"result": {"error": str(exc), "tool": tool_name}}


@_register("pii_detect_and_redact")
def _pii_detect_and_redact(params: dict) -> dict:
    text    = str(params.get("message", ""))
    session = str(params.get("session_id", "default"))
    pii_map: dict[str, str] = {}
    redacted = text

    patterns = {
        "account_number": r"\b\d{8}\b",
        "sort_code":      r"\b\d{2}[-\u2013]\d{2}[-\u2013]\d{2}\b",
        "card_number":    r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b",
        "mobile":         r"\b0[0-9]{10}\b",
        "dob":            r"\b\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b",
    }

    for pii_type, pattern in patterns.items():
        for match in re.findall(pattern, text):
            token   = f"{pii_type.upper()}_{uuid.uuid4().hex[:6]}"
            pii_map[token] = match
            redacted = redacted.replace(match, f"[{pii_type}]")

    return {
        "redacted_text": redacted,
        "pii_detected":  bool(pii_map),
        "pii_map":       pii_map,
        "pii_types_found": list({k.rsplit("_", 1)[0] for k in pii_map}),
    }


@_register("pii_vault_store")
def _pii_vault_store(params: dict) -> dict:
    session = str(params.get("session_id", "default"))
    raw_map = params.get("pii_map", {})
    if isinstance(raw_map, str):
        try:
            raw_map = json.loads(raw_map)
        except Exception:
            raw_map = {}

    if session not in _VAULT:
        _VAULT[session] = {}

    vault_refs: dict[str, str] = {}
    for token, value in raw_map.items():
        _VAULT[session][token] = value
        vault_refs[token] = f"vault://{session}/{token}"

    return {"vault_status": "stored", "vault_refs": vault_refs}


@_register("pii_vault_retrieve")
def _pii_vault_retrieve(params: dict) -> dict:
    session = str(params.get("session_id", "default"))
    raw_refs = params.get("vault_refs", "[]")
    if isinstance(raw_refs, str):
        try:
            vault_refs: list = json.loads(raw_refs)
        except Exception:
            vault_refs = []
    else:
        vault_refs = list(raw_refs)

    session_data = _VAULT.get(session, {})
    retrieved = {ref: session_data.get(ref.split("/")[-1], "[NOT_FOUND]") for ref in vault_refs}
    return {"retrieved": retrieved, "purpose": str(params.get("purpose", ""))}


@_register("pii_vault_purge")
def _pii_vault_purge(params: dict) -> dict:
    session = str(params.get("session_id", "default"))
    _VAULT.pop(session, None)
    return {
        "purge_status": "purged",
        "session_id":   session,
        "reason":       str(params.get("purge_reason", "")),
    }
