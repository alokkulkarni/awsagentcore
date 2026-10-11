"""
idv_verifiers.py
================
SIMULATED identification and verification services for the ARIA ID&V test
harness. Each function stands in for a real bank or telco service named in the
"CLI identification and caller verification" design:

    lookup_by_cli               identity graph / CIF        (hashed CLI lookup)
    get_network_signals         CAMARA SIM Swap, Call Forwarding, Tenure
    resolve_claimed_identity    identity graph / CIF
    create_push_challenge       push authentication service (number matching)
    create_otp / check_otp      OTP service
    check_kba                   KBA / partial PIN service
    issue_receipt               KMS signing of receipts (see idv_tokens.py)

Nothing here calls a real service or sends a real message. A successful
verification returns a SIGNED RECEIPT. The dialogue code cannot raise the
caller's level itself: it must hand the receipt to idv_policy.accept_receipt().

Signing uses HMAC-SHA256 with a shared test secret. Production would sign with
an asymmetric KMS key that the AI agent has no permission to use.
"""

import hashlib
import hmac
import time

import idv_test_data as data
from idv_tokens import (  # noqa: F401  (re-exported for callers of this module)
    _digits_from, dial_code_for, mint_token, sign_token, verify_token,
)

RECEIPT_TTL_SECONDS = 300
PUSH_TIMEOUT_SECONDS = 90      # the real push timeout; the harness keypad wait is shorter
HIGH_RISK_THRESHOLD = 50
SIM_SWAP_LOOKBACK_DAYS = 7


def issue_receipt(method: str, customer_id: str, contact_id: str, intent: str,
                  secret: str, now: float | None = None, loa: int | None = None) -> str:
    """A verifier's signed statement that `method` succeeded for this customer on this contact."""
    now = time.time() if now is None else now
    payload = {
        "typ": "receipt", "method": method, "cust": customer_id, "contact": contact_id,
        "intent": intent, "iat": int(now), "exp": int(now) + RECEIPT_TTL_SECONDS,
        "nonce": _digits_from(secret, f"nonce|{method}|{customer_id}|{contact_id}|{now}", 12),
    }
    if loa is not None:
        payload["loa"] = loa
    return sign_token(payload, secret)


# ---------------------------------------------------------------------------
# Identify — who do we think this is?
# ---------------------------------------------------------------------------

def hash_cli(cli: str) -> str:
    """CLIs are looked up by hash so the raw number never has to be stored."""
    return hashlib.sha256(data.normalise_phone(cli).encode()).hexdigest()


def _cli_index() -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for phone, cust in data.PHONE_TO_CUSTOMER.items():
        index.setdefault(hash_cli(phone), [])
        if cust not in index[hash_cli(phone)]:
            index[hash_cli(phone)].append(cust)
    index[hash_cli(data.SHARED_LANDLINE)] = data.shared_line_customers()
    return index


def lookup_by_cli(cli: str) -> list[str]:
    """Candidate customers for a CLI: zero, one or many. A candidate is a guess, not proof."""
    if not cli:
        return []
    return list(_cli_index().get(hash_cli(cli), []))


def resolve_claimed_identity(dob: str, card_last_four: str) -> str:
    """The single customer matching the claimed details, or '' (never says which detail failed)."""
    matches = [c for c in data.customer_ids()
               if data.profile_for(c)["dob"] == dob and card_last_four in data.card_last_fours(c)]
    return matches[0] if len(matches) == 1 else ""


# ---------------------------------------------------------------------------
# Network and risk signals — facts about the LINE, never proof of the person
# ---------------------------------------------------------------------------

def get_network_signals(cli: str, line_kind: str, force_high: bool = False) -> dict:
    """
    Simulated CAMARA signals plus a call-risk score for the line.

    Returns simSwapDays ('' = none), callForwarding, tenureDays, riskScore,
    risk ('LOW' | 'HIGH') and reasons.
    """
    candidates = lookup_by_cli(cli)
    profile = data.profile_for(candidates[0]) if len(candidates) == 1 else {}
    swap = profile.get("sim_swap_days_ago")
    forwarding = bool(profile.get("call_forwarding"))
    tenure = profile.get("tenure_days")
    if force_high:
        swap, forwarding = (2 if swap is None else swap), True

    score, reasons = 10, []
    if swap is not None and swap <= SIM_SWAP_LOOKBACK_DAYS:
        score += 60
        reasons.append("SIM_SWAP_RECENT")
    if forwarding:
        score += 25
        reasons.append("CALL_FORWARDING_ACTIVE")
    if tenure is not None and tenure < 90:
        score += 15
        reasons.append("NUMBER_TENURE_SHORT")
    if line_kind == "international":
        score += 30
        reasons.append("INTERNATIONAL_ORIGIN")
    if line_kind == "withheld":
        reasons.append("CLI_WITHHELD")
    score = min(score, 100)
    return {
        "simSwapDays": "" if swap is None else str(swap),
        "callForwarding": "true" if forwarding else "false",
        "tenureDays": "" if tenure is None else str(tenure),
        "riskScore": score,
        "risk": "HIGH" if score >= HIGH_RISK_THRESHOLD else "LOW",
        "reasons": reasons,
    }


# ---------------------------------------------------------------------------
# Verify — prove it
# ---------------------------------------------------------------------------

def create_push_challenge(customer_id: str, contact_id: str, secret: str, salt: str) -> str:
    """The two-digit number the agent reads out and the customer must pick in the app."""
    code = int(_digits_from(secret, f"push|{customer_id}|{contact_id}|{salt}", 2))
    return str(10 + code % 90)


def check_push(entered: str, match_code: str) -> str:
    """APPROVED, DECLINED (wrong number or 0) or EXPIRED (no response)."""
    if entered in ("", "Timeout"):
        return "EXPIRED"
    return "APPROVED" if entered == match_code else "DECLINED"


def create_otp(customer_id: str, contact_id: str, secret: str, salt: str) -> str:
    return _digits_from(secret, f"otp|{customer_id}|{contact_id}|{salt}", 6)


def check_otp(entered: str, expected: str) -> bool:
    return bool(expected) and hmac.compare_digest(entered or "", expected)


def check_kba(customer_id: str, entered: str) -> bool:
    """Partial PIN: the 2nd and 5th digits of the customer's security number."""
    number = data.profile_for(customer_id)["security_number"]
    return hmac.compare_digest(entered or "", number[1] + number[4])


# ---------------------------------------------------------------------------
# App-to-call handoff codes and pre-authenticated tokens (Options D and E)
# ---------------------------------------------------------------------------

def resolve_dial_code(code: str, secret: str, now: float | None = None) -> str:
    """The customer a dial code was minted for (current or previous window), or ''."""
    for cust in data.customer_ids():
        for offset in (0, -1):
            if hmac.compare_digest(code or "", dial_code_for(cust, secret, now, offset)):
                return cust
    return ""


def check_preauth_token(token: str, expected_typ: str, secret: str, now: float | None = None) -> dict | None:
    """Payload of a valid, unexpired token of the expected type for a known customer, else None."""
    now = time.time() if now is None else now
    payload = verify_token(token, secret)
    if not payload or payload.get("typ") != expected_typ or payload.get("exp", 0) < now:
        return None
    if payload.get("cust") not in data.STUB_CUSTOMERS:
        return None
    return payload
