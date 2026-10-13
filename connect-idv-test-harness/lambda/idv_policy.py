"""
idv_policy.py
=============
The policy decision point (PDP) for the ARIA ID&V test harness.

This module is the ONLY code allowed to change a caller's level of assurance.
It is deliberately pure Python with no I/O: same inputs, same answer, every
time. In production the same rules would live in Cedar policies inside Amazon
Verified Permissions; the function names below map one-to-one onto that design.

Level of assurance (LoA) ladder
-------------------------------
    0  Anonymous         general information only
    1  Identified        CLI match or claimed identity, low risk; protective actions
    2  Verified          one strong factor; balances and existing-payee payments
    3  Strongly verified device-bound push, app handoff, or SMS OTP + KBA on own phone
    4  Payment           level 3 plus a payment step-up. NOT granted here: ARIA does
                         it in the main conversational flow, only when a payment is asked for

The harness aims for level 3 on every contact. Two rules are enforced here,
not in the dialogue:
    * Risk removes weak factors; it never makes a level easier to reach.
    * Assurance only changes when a signed receipt is accepted.
"""

import time

import idv_verifiers as verifiers

LOA_ANONYMOUS, LOA_IDENTIFIED, LOA_VERIFIED, LOA_STRONG = 0, 1, 2, 3

# Level 4 exists but is never granted here. It is reached only inside the main
# conversational flow, when ARIA runs a payment step-up on top of level 3.
LOA_PAYMENT = 4

# The level the harness tries to reach on every contact, whatever the customer
# wants. The customer is not asked what they want first: that is ARIA's job.
TARGET_LOA = LOA_STRONG

# What each level is for. Calibrate with Fraud and Risk before any real use.
REQUIRED_LOA: dict[str, int] = {
    "servicing": LOA_STRONG,   # everything ARIA does except moving money
    "payment":   LOA_PAYMENT,  # making a payment: level 3 plus ARIA's step-up
}

MAX_ATTEMPTS_PER_FACTOR = 2   # wrong OTP / KBA entries before the factor is dead

# What each kind of receipt is worth on its own.
_METHOD_LOA: dict[str, int] = {
    "push": LOA_STRONG,
    "app_handoff": LOA_STRONG,
    "sca": LOA_STRONG,          # in-app biometric bound to the request
    "otp_sms": LOA_VERIFIED,
    "otp_email": LOA_VERIFIED,
    "kba": LOA_VERIFIED,
    "dial_code": LOA_VERIFIED,  # upgraded to LoA3 when the CLI is the registered mobile
    "chat_session": LOA_VERIFIED,
}

# On a high-risk line only these receipts are accepted at all.
_HIGH_RISK_ACCEPTED = {"push", "app_handoff", "sca"}


def baseline_loa(candidate_count: int, risk: str) -> tuple[int, list[str]]:
    """
    LoA from CLI evidence alone, before the caller has proved anything.
    Exactly one candidate on a low-risk line is LoA1. Everything else is LoA0.
    """
    if risk == "HIGH":
        return LOA_ANONYMOUS, ["CLI_HIGH_RISK"]
    if candidate_count == 1:
        return LOA_IDENTIFIED, ["CLI_MATCH"]
    if candidate_count > 1:
        return LOA_ANONYMOUS, ["CLI_MULTIPLE_MATCHES"]
    return LOA_ANONYMOUS, ["CLI_NO_MATCH"]


def evaluate(loa: int, risk: str, target: int = TARGET_LOA) -> dict:
    """
    PERMIT when the target level has been reached, otherwise STEP_UP.

    Returns decision, required, reasons and obligations. Obligations are the
    conditions attached to a PERMIT. On a high-risk line, reaching level 3 is
    still allowed (only a pre-swap device can get there) but sensitive changes
    must be held for a cooling-off period.
    """
    if loa < target:
        return {"decision": "STEP_UP", "required": target, "reasons": ["STEP_UP_REQUIRED"], "obligations": []}
    reasons, obligations = ["PERMIT"], []
    if risk == "HIGH":
        obligations.append("HOLD_72H")
        reasons.insert(0, "COOLING_OFF_72H")
    return {"decision": "PERMIT", "required": target, "reasons": reasons, "obligations": obligations}


def allowed_methods(ctx: dict) -> list[str]:
    """
    Which verification methods may be OFFERED right now, strongest first.

    A push is offered once per contact; when it fails the caller falls back to
    OTP + KBA once (each capped at MAX_ATTEMPTS_PER_FACTOR tries), then referral.

    Risk removes weak factors rather than adding questions:
        * high risk          -> no SMS/email OTP, no KBA; push only to a device
                                bound before the SIM swap
        * borrowed phone     -> push only if the app is on another device;
                                OTP goes to email, never to the phone on the line
        * phone reported stolen -> that phone is removed from push targets
        * chat               -> never KBA
    """
    profile = ctx.get("profile") or {}
    high_risk = ctx.get("risk") == "HIGH"
    relationship = ctx.get("cli_relationship", "NONE")
    channel = ctx.get("channel", "voice")
    methods: list[str] = []

    app_ok = bool(profile.get("app_enrolled")) and not ctx.get("app_unreachable")
    if app_ok and ctx.get("device_stolen"):
        app_ok = bool(profile.get("app_on_second_device"))
    if app_ok and relationship != "MATCH":
        app_ok = bool(profile.get("app_on_second_device"))
    if app_ok and high_risk:
        swap = profile.get("sim_swap_days_ago")
        swap = ctx.get("forced_swap_days") if swap is None else swap
        if swap is not None:
            app_ok = profile.get("device_bound_days_ago", 0) > swap
    if app_ok:
        methods.append("push")

    if not high_risk:
        own_phone_in_hand = relationship == "MATCH" and not ctx.get("device_stolen")
        methods.append("otp_sms" if own_phone_in_hand else "otp_email")
        if channel == "voice":
            methods.append("kba")

    # Drop anything already proven, and any factor whose attempts are used up.
    evidence = set(ctx.get("evidence") or [])
    attempts = ctx.get("attempts") or {}
    limits = {"push": 1, "otp": MAX_ATTEMPTS_PER_FACTOR, "kba": MAX_ATTEMPTS_PER_FACTOR}
    return [m for m in methods
            if m not in evidence and attempts.get(m.split("_")[0], 0) < limits[m.split("_")[0]]]


def loa_from_evidence(methods: set[str], ctx: dict) -> int:
    """
    The level a SET of accepted receipts adds up to.

    An SMS OTP to the registered mobile the caller is holding, plus KBA, is
    possession + knowledge and reaches LoA3 on a low-risk line. An EMAIL OTP
    plus KBA (the borrowed-phone route) stays at LoA2: the email inbox is a
    weaker possession factor than a device on the call.
    """
    if not methods:
        return LOA_ANONYMOUS
    level = max(_METHOD_LOA.get(m, LOA_ANONYMOUS) for m in methods)
    if {"otp_sms", "kba"} <= methods and ctx.get("risk") != "HIGH":
        level = LOA_STRONG
    if "dial_code" in methods and ctx.get("cli_is_registered_mobile"):
        level = LOA_STRONG
    return level


def accept_receipt(receipt: str, ctx: dict, secret: str, now: float | None = None) -> dict:
    """
    request_auth_level: the single doorway through which assurance can rise.

    A receipt is accepted only if it is genuinely signed by a verifier, has not
    expired, has not been used before, and is bound to THIS contact and THIS
    customer. Anything else leaves the level unchanged and says why.

    ctx needs: contact_id, customer_id, risk, profile, evidence (list of
    methods already accepted), used_nonces (list), loa (current level).
    """
    now = time.time() if now is None else now
    current = int(ctx.get("loa", 0))
    denied = {"accepted": False, "loa": current}

    payload = verifiers.verify_token(receipt, secret)
    if payload is None:
        return {**denied, "reason": "RECEIPT_INVALID_SIGNATURE"}
    if payload.get("typ") != "receipt":
        return {**denied, "reason": "RECEIPT_WRONG_TYPE"}
    if payload.get("exp", 0) < now:
        return {**denied, "reason": "RECEIPT_EXPIRED"}
    if payload.get("contact") != ctx.get("contact_id"):
        return {**denied, "reason": "RECEIPT_WRONG_CONTACT"}
    if payload.get("cust") != ctx.get("customer_id"):
        return {**denied, "reason": "RECEIPT_WRONG_CUSTOMER"}
    if payload.get("nonce") in (ctx.get("used_nonces") or []):
        return {**denied, "reason": "RECEIPT_REPLAYED"}

    method = payload.get("method", "")
    if method not in _METHOD_LOA:
        return {**denied, "reason": "RECEIPT_UNKNOWN_METHOD"}
    if ctx.get("risk") == "HIGH" and method not in _HIGH_RISK_ACCEPTED:
        return {**denied, "reason": "METHOD_NOT_ALLOWED_AT_HIGH_RISK"}

    evidence = set(ctx.get("evidence") or []) | {method}
    granted = max(current, loa_from_evidence(evidence, ctx))
    # A pre-authenticated session can carry a level in the token itself (for
    # example an app session that was only LoA2). It can cap, never exceed.
    claimed = payload.get("loa")
    if method in ("chat_session", "app_handoff") and claimed is not None:
        granted = max(current, min(int(claimed), _METHOD_LOA[method] if method == "chat_session" else LOA_STRONG))
    return {"accepted": True, "loa": granted, "method": method,
            "nonce": payload.get("nonce"), "evidence": sorted(evidence),
            "reason": f"RECEIPT_ACCEPTED_{method.upper()}"}
