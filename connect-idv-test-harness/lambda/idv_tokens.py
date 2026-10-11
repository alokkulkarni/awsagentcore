"""
idv_tokens.py
=============
Signing helpers for the ARIA ID&V test harness: receipts, pre-authentication
tokens, app dial codes and the harness's own conversation state.

This module has no dependencies beyond the Python standard library, so the
local helper script (scripts/mint_test_token.py) can use it without boto3.

Signing uses HMAC-SHA256 with a shared test secret. Production would sign with
an asymmetric KMS key that the AI agent has no permission to use, so that a
receipt can be checked by the policy engine but never forged by the agent.
"""

import base64
import hashlib
import hmac
import json
import time


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_token(payload: dict, secret: str) -> str:
    """Return '<base64url payload>.<base64url HMAC>'."""
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(sig)}"


def verify_token(token: str, secret: str) -> dict | None:
    """Return the payload if the signature is valid, otherwise None. Never raises."""
    try:
        body, sig = (token or "").split(".", 1)
        expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(sig)):
            return None
        payload = json.loads(_unb64(body))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _digits_from(secret: str, material: str, length: int) -> str:
    """Deterministic decimal digits derived from the secret (used for codes)."""
    digest = hmac.new(secret.encode(), material.encode(), hashlib.sha256).hexdigest()
    return str(int(digest, 16))[-length:].zfill(length)


DIAL_CODE_WINDOW_SECONDS = 300


def dial_code_for(customer_id: str, secret: str, now: float | None = None, window_offset: int = 0) -> str:
    """The six-digit code the app would append when it dials the bank number."""
    now = time.time() if now is None else now
    window = int(now // DIAL_CODE_WINDOW_SECONDS) + window_offset
    return _digits_from(secret, f"dial|{customer_id}|{window}", 6)


def mint_token(typ: str, customer_id: str, secret: str, loa: int = 3, intent: str = "",
               ttl: int = 300, now: float | None = None) -> str:
    """
    Mint a pre-authentication token, as the bank's mobile or chat backend would.
        typ 'call'    one-time call token for an in-app (WebRTC) call
        typ 'session' signed chat session token
        typ 'sca'     in-app biometric approval bound to one intent
    """
    now = time.time() if now is None else now
    return sign_token({"typ": typ, "cust": customer_id, "loa": loa, "intent": intent,
                       "iat": int(now), "exp": int(now) + ttl,
                       "jti": _digits_from(secret, f"jti|{typ}|{customer_id}|{now}", 12)}, secret)
