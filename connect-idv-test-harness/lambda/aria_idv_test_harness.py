"""
aria_idv_test_harness.py
========================
ARIA ID&V Test Harness Lambda — the dialogue engine behind the
"ARIA IDV Test Harness" contact flow.

TEST TOOL ONLY. It lets a tester pick any test customer known to
session_injector_qconnect.py, choose which phone line the call "arrives from",
walk through CLI identification and caller verification as described in
"CLI identification and caller verification on Amazon Connect", and then hand
the contact to the main "conversation bot flow" with the result as contact
attributes. It refuses to run unless IDV_TEST_HARNESS_ENABLED=true.

How the contact flow uses this Lambda
-------------------------------------
The flow is a small loop. Each time round it invokes this Lambda, saves the
answer as contact attributes, and does what the `action` field says:

    action = "input"    play `prompt`, collect keypad digits, invoke again
    action = "handoff"  play `prompt`, transfer to the main conversational flow
    action = "end"      play `prompt`, disconnect

    [Invoke Lambda: operation=start]
            |
            v
    [Set contact attributes from $.External.*] <---------------+
            |                                                   |
            v                                                   |
    [Check $.External.action] --input--> [Store customer input] |
            |        |                          |               |
         handoff    end        [Invoke Lambda: operation=step, input=digits]
            |        |
    [Transfer to flow]  [Disconnect]

The Lambda keeps no memory between invocations. Everything it needs to carry
on the conversation is returned in `idvState` (a signed string), which the flow
stores as a contact attribute and Connect sends back in the next event.

Who decides what (mirrors the design document)
----------------------------------------------
    this file          orchestrates the dialogue and picks the next step
    idv_verifiers.py   simulated verifiers; success returns a signed receipt
    idv_policy.py      the only code that can change the level of assurance

Lambda input (Connect "Invoke AWS Lambda function" block parameters)
--------------------------------------------------------------------
    operation   "start" | "step"
    input       keypad digits from $.StoredCustomerInput (step only)

Optional contact attributes read at start (for chat, in-app calls, automation)
------------------------------------------------------------------------------
    idvTestCustomerId   quick-select this customer, skip the ID&V dialogue
    idvCallToken        Option D: one-time call token from the app (voice)
    idvSessionToken     Option E: signed chat session token
    idvStepUpToken      Option E: in-app biometric approval bound to idvIntent
    idvIntent           what the customer wants (see idv_policy.INTENT_REQUIRED_LOA)

Lambda output (all strings — Connect STRING_MAP)
------------------------------------------------
    action, prompt, idvState                    drive the flow loop
    customerId, authStatus                      read by session_injector_qconnect
    LoA, idvMethod, cliRelationship, riskScore, reasonCodes   the design's attributes
    idvStatus, idvIntent, idvDecision, idvObligations, idvSummary

ENVIRONMENT VARIABLES
---------------------
Required:
    IDV_TEST_HARNESS_ENABLED   must be "true" or the Lambda refuses to run
    IDV_TEST_SIGNING_SECRET    16+ characters; signs receipts, tokens and state
Optional:
    BANK_NAME                  spoken bank name (default "Nationwide Building Society")
    LOG_LEVEL                  default INFO
    ASSISTANT_ID               only needed so the imported injector module loads
                               the same way it does in its own Lambda; unused here

IAM PERMISSIONS REQUIRED
------------------------
    AWSLambdaBasicExecutionRole only. This Lambda calls no AWS APIs.
"""

import json
import logging
import os
from typing import Any

import idv_policy as policy
import idv_test_data as data
import idv_verifiers as verifiers

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

BANK_NAME: str = os.environ.get("BANK_NAME", "Nationwide Building Society")
MAX_INVALID_INPUTS = 2
MAX_CLAIM_ATTEMPTS = 2

# Keypad digit -> intent. Option 7 is not an intent: it simulates a caller
# pressuring the agent to skip security on someone else's behalf.
INTENT_MENU: list[tuple[str, str, str]] = [
    ("1", "general_info", "general information"),
    ("2", "freeze_card", "freeze my card"),
    ("3", "report_lost_stolen", "my phone has been stolen and I need to stop my card"),
    ("4", "balance", "check my balance"),
    ("5", "change_contact_details", "change my address"),
    ("6", "new_payee_payment", "add a new payee and send money"),
]
THIRD_PARTY_KEY = "7"

FAIL_NEUTRAL = ("I wasn't able to confirm it's you, so I can't make that change on this call. "
                "I can freeze your card now, or you can do it in the app or a branch.")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _secret() -> str:
    return os.environ.get("IDV_TEST_SIGNING_SECRET", "")


def _harness(text: str) -> str:
    """Mark a sentence as a tester instruction, not something a real agent would say."""
    return f"Test harness: {text}"


def _spell(digits: str) -> str:
    return " ".join(digits)


def _clean(raw: str) -> str:
    """Normalise keypad input. A timed-out Store customer input block yields 'Timeout'."""
    raw = (raw or "").strip()
    if raw in ("", "Timeout"):
        return "Timeout"
    return raw.replace("#", "").replace(" ", "")


def _add_reason(s: dict, *codes: str) -> None:
    for code in codes:
        if code and code not in s["rc"]:
            s["rc"].append(code)


def _policy_ctx(s: dict, contact_id: str) -> dict:
    cust = s.get("cand", "")
    return {
        "contact_id": contact_id, "customer_id": cust,
        "profile": data.profile_for(cust) if cust else {},
        "risk": s["risk"], "cli_relationship": s["rel"], "channel": s["ch"],
        "loa": s["loa"], "evidence": s["ev"], "used_nonces": s["nonces"], "attempts": s["att"],
        "app_unreachable": s.get("au", False), "device_stolen": s.get("stolen", False),
        "forced_swap_days": 2 if s.get("fh") else None,
        "cli_is_registered_mobile": bool(cust) and s.get("cli", "") == data.registered_mobile(cust),
    }


def _submit_receipt(s: dict, receipt: str, contact_id: str) -> bool:
    """Hand a verifier's receipt to the policy engine. Only this can raise s['loa']."""
    result = policy.accept_receipt(receipt, _policy_ctx(s, contact_id), _secret())
    _add_reason(s, result["reason"])
    if not result["accepted"]:
        return False
    s["loa"], s["ev"], s["method"] = result["loa"], result["evidence"], "+".join(result["evidence"])
    s["nonces"].append(result["nonce"])
    return True


def _new_state(channel: str, real_cli: str) -> dict:
    return {
        "st": "mode", "ch": channel, "real": real_cli, "cli": "", "kind": "", "cands": [],
        "cand": "", "own": None, "rel": "NONE", "risk": "LOW", "score": 0,
        "loa": 0, "ev": [], "nonces": [], "att": {}, "rc": [], "method": "none",
        "intent": "", "dec": "", "obl": [], "bad": 0, "n": 0, "claims": 0,
    }


# ---------------------------------------------------------------------------
# Building the reply that goes back to the contact flow
# ---------------------------------------------------------------------------

def _reply(s: dict, action: str, prompt: str) -> dict:
    verified = s["loa"] >= policy.LOA_VERIFIED
    status = "verified" if verified else ("identified" if s["loa"] == policy.LOA_IDENTIFIED else "anonymous")
    summary = (f"customer={s['cand'] if verified else 'none'} LoA={s['loa']} method={s['method']} "
               f"cli={s['rel']} risk={s['risk']} decision={s['dec'] or 'n/a'}")
    return {
        "action": action,
        "prompt": prompt.strip() or " ",
        "idvState": verifiers.sign_token(s, _secret()),
        # customerId is released ONLY at LoA2+. Below that the main flow, the
        # session injector and the AI agent never learn who the candidate was.
        "customerId": s["cand"] if verified else "",
        "authStatus": "authenticated" if verified else "unauthenticated",
        "LoA": str(s["loa"]),
        "idvMethod": s["method"],
        "cliRelationship": s["rel"],
        "riskScore": str(s["score"]),
        "reasonCodes": ",".join(s["rc"]),
        "idvStatus": status,
        "idvIntent": s["intent"],
        "idvDecision": s["dec"],
        "idvObligations": ",".join(s["obl"]),
        "idvSummary": summary,
    }


def _ask(s: dict, stage: str, prompt: str) -> dict:
    s["st"] = stage
    return _reply(s, "input", prompt)


def _handoff(s: dict, lead: str = "") -> dict:
    s["st"] = "done"
    who = data.preferred_name(s["cand"]) if s["loa"] >= policy.LOA_VERIFIED else "an unverified caller"
    note = _harness(f"handing over to ARIA as {who}, level {s['loa']}, method {s['method'].replace('_', ' ')}.")
    return _reply(s, "handoff", f"{lead} {note}")


def _end(s: dict, prompt: str) -> dict:
    s["st"] = "done"
    return _reply(s, "end", prompt)


# ---------------------------------------------------------------------------
# Menus
# ---------------------------------------------------------------------------

def _mode_menu() -> str:
    return _harness("press 1 to quick-select a test customer and go straight to ARIA. "
                    "Press 2 for the full identification and verification journey. "
                    "Press 3 if you have an app dial code. Then press hash.")


def _customer_menu() -> str:
    options = ". ".join(f"Press {i} for {data.preferred_name(c)}"
                        for i, c in enumerate(data.customer_ids(), start=1))
    return _harness(f"choose the test customer. {options}. Then press hash.")


def _line_menu(s: dict) -> str:
    options = ". ".join(f"Press {line['key']} for {line['label']}" for line in data.simulated_lines(s["real"]))
    return _harness(f"which line is this call arriving from? {options}. Then press hash.")


def _scenario_menu() -> str:
    return _harness("choose the conditions. Press 1 to use the customer's default profile. "
                    "Press 2 for a high-risk line with a recent SIM swap. "
                    "Press 3 if the bank app cannot be reached. "
                    "Press 4 for both. Then press hash.")


def _intent_menu(with_greeting: bool) -> str:
    greeting = (f"Thanks for calling {BANK_NAME}. I'm the virtual assistant. "
                "In a few words, what can I help with today? ") if with_greeting else "What else can I help with? "
    options = ". ".join(f"Press {key} for {label}" for key, _, label in INTENT_MENU)
    return (f"{greeting}{_harness(options)}. Press {THIRD_PARTY_KEY} to say you are calling for "
            "someone else and want to skip security. Then press hash.")


def _after_menu(lead: str) -> str:
    return f"{lead} {_harness('press 1 to make another request, or 2 to connect to ARIA. Then press hash.')}"


# ---------------------------------------------------------------------------
# Identify: the silent CLI work done before the greeting
# ---------------------------------------------------------------------------

def _run_silent_cli_checks(s: dict) -> None:
    """lookup_by_cli + network signals + baseline level. Nothing here is ever spoken."""
    s["cands"] = verifiers.lookup_by_cli(s["cli"])
    signals = verifiers.get_network_signals(s["cli"], s["kind"], force_high=s.get("fh", False))
    s["risk"], s["score"] = signals["risk"], signals["riskScore"]
    _add_reason(s, *signals["reasons"])
    s["loa"], reasons = policy.baseline_loa(len(s["cands"]), s["risk"])
    _add_reason(s, *reasons)


def _relationship(s: dict, customer_id: str) -> str:
    """MATCH if the caller is a customer the CLI points at, MISMATCH if not, NONE if no CLI match."""
    if not s["cands"]:
        return "NONE"
    return "MATCH" if customer_id in s["cands"] else "MISMATCH"


# ---------------------------------------------------------------------------
# The core: decide what happens next for the current intent
# ---------------------------------------------------------------------------

def _progress(s: dict, contact_id: str, lead: str = "") -> dict:
    """
    Ask the policy engine about the current intent and act on the answer:
    serve it, identify the caller, start the next verification, or fail neutrally.
    """
    intent = s["intent"]
    needs_identity = policy.INTENT_REQUIRED_LOA.get(intent, 3) > policy.LOA_ANONYMOUS

    # 1. Identify. One neutral question separates the caller from the phone owner.
    if needs_identity and s["own"] is None:
        if len(s["cands"]) == 1:
            return _ask(s, "own", f"{lead} Is this call about the account linked to the number you're "
                                  f"calling from? {_harness('press 1 for yes or 2 for no, then hash.')}")
        return _ask_claim_dob(s, lead)

    decision = policy.evaluate(intent, s["loa"], s["risk"], identified=bool(s["cand"]) and s["own"] is True)
    s["dec"], s["obl"] = decision["decision"], decision["obligations"]
    _add_reason(s, *decision["reasons"])

    # 2. Serve at the granted level.
    if decision["decision"] == "PERMIT":
        return _ask(s, "after", _after_menu(f"{lead} {_permit_message(s)}"))

    if decision["decision"] == "DENY":
        return _ask(s, "after", _after_menu(f"{lead} {FAIL_NEUTRAL}"))

    # 3. Step up: pick the strongest allowed method that would actually raise the level.
    ctx = _policy_ctx(s, contact_id)
    for method in policy.allowed_methods(ctx):
        if policy.loa_from_evidence(set(s["ev"]) | {method}, ctx) > s["loa"]:
            return _start_challenge(s, method, contact_id, lead)

    # 4. Nothing left to try. Fail without hints; never say which factor failed or why.
    s["dec"] = "DENY"
    _add_reason(s, "STEP_UP_EXHAUSTED")
    if s["risk"] == "HIGH":
        _add_reason(s, "FRAUD_CASE_RAISED")
    return _ask(s, "after", _after_menu(f"{lead} {FAIL_NEUTRAL}"))


def _permit_message(s: dict) -> str:
    name = data.preferred_name(s["cand"]) if s["loa"] >= policy.LOA_VERIFIED else ""
    thanks = f"Thanks, {name}, that's confirmed. " if name else ""
    intent = s["intent"]
    if intent == "general_info":
        return "Of course, I can help with general information."
    if intent in policy.PROTECTIVE_INTENTS:
        return "Thanks. I've frozen your cards so they can't be used."
    if intent == "balance":
        return f"{thanks}I can help with your balance."
    held = " For your security, this change will be reviewed before it takes effect." if "HOLD_72H" in s["obl"] else ""
    if intent == "new_payee_payment":
        return (f"{thanks}Before we add the payee: has anyone asked you to move money "
                f"or told you what to say?{held}")
    return f"{thanks}I can help you change your address.{held}"


def _ask_claim_dob(s: dict, lead: str = "") -> dict:
    return _ask(s, "claim_dob", f"{lead} Can I take your date of birth, please? "
                                f"{_harness('key the date of birth as eight digits, day month year, then hash.')}")


def _start_challenge(s: dict, method: str, contact_id: str, lead: str = "") -> dict:
    s["n"] += 1
    cust, salt = s["cand"], str(s["n"])
    if method == "push":
        code = verifiers.create_push_challenge(cust, contact_id, _secret(), salt)
        security = "For your security, I need to confirm this through your" if s["risk"] == "HIGH" \
            else "To keep your account safe, I've sent a notification to your"
        return _ask(s, "push", f"{lead} {security} {BANK_NAME} app. Open it, choose {code}, then confirm with "
                               f"your face or fingerprint. I'll wait while you open the app. "
                               + _harness(f"to approve in the app, key {_spell(code)} then hash. Key any other "
                                          "number to pick the wrong one, 0 to decline, or wait to let it time out."))
    if method in ("otp_sms", "otp_email"):
        code = verifiers.create_otp(cust, contact_id, _secret(), salt)
        where = "I'll text a six-digit code to the mobile number we hold for you." if method == "otp_sms" \
            else "I've sent a six-digit code to the email address we hold for you."
        s["otp_m"] = method
        return _ask(s, "otp", f"{lead} {where} Can you read it back? "
                              + _harness(f"no message is really sent. The code is {_spell(code)}. Key it, then hash."))
    return _ask(s, "kba", f"{lead} And the 2nd and 5th digits of your security number? "
                          + _harness("key the two digits, then hash."))


# ---------------------------------------------------------------------------
# Stage handlers (voice). Each takes the cleaned keypad input.
# ---------------------------------------------------------------------------

def _stage_mode(s: dict, digits: str, contact_id: str) -> dict | None:
    if digits == "1":
        return _ask(s, "quick", _customer_menu())
    if digits in ("2", "3"):
        s["dial"] = digits == "3"
        return _ask(s, "line", _line_menu(s))
    return None


def _stage_quick(s: dict, digits: str, contact_id: str) -> dict | None:
    customers = data.customer_ids()
    if not digits.isdigit() or not 1 <= int(digits) <= len(customers):
        return None
    return _quick_select(s, customers[int(digits) - 1])


def _quick_select(s: dict, customer_id: str) -> dict:
    """
    The ONE deliberate bypass in the harness: no receipt, no policy decision.
    It reproduces today's behaviour (a known customer arrives authenticated) so
    the main flow can be tested with any customer. It is loudly labelled.
    """
    s.update({"cand": customer_id, "own": True, "loa": policy.LOA_VERIFIED,
              "method": "test_quick_select", "dec": "PERMIT"})
    _add_reason(s, "TEST_QUICK_SELECT_BYPASS")
    return _handoff(s)


def _stage_line(s: dict, digits: str, contact_id: str) -> dict | None:
    line = next((ln for ln in data.simulated_lines(s["real"]) if ln["key"] == digits), None)
    if line is None:
        return None
    s["cli"], s["kind"] = line["cli"], line["kind"]
    if line["kind"] == "real" and not line["cli"]:
        s["kind"] = "withheld"
    return _ask(s, "scenario", _scenario_menu())


def _stage_scenario(s: dict, digits: str, contact_id: str) -> dict | None:
    if digits not in ("1", "2", "3", "4"):
        return None
    s["fh"], s["au"] = digits in ("2", "4"), digits in ("3", "4")
    _run_silent_cli_checks(s)
    if s.get("dial"):
        return _ask(s, "dial", _harness("key the six-digit app dial code, then hash."))
    return _ask(s, "intent", _intent_menu(with_greeting=True))


def _stage_dial(s: dict, digits: str, contact_id: str) -> dict | None:
    """Option D, PSTN handoff: the app dialled the bank number with a short-lived code."""
    customer_id = verifiers.resolve_dial_code(digits, _secret())
    if not customer_id:
        _add_reason(s, "DIAL_CODE_INVALID")
        return _ask(s, "intent", _intent_menu(with_greeting=True))
    s["cand"], s["own"], s["rel"] = customer_id, True, _relationship(s, customer_id)
    receipt = verifiers.issue_receipt("dial_code", customer_id, contact_id, "", _secret())
    if not _submit_receipt(s, receipt, contact_id):
        # For example a high-risk line: the code alone is not accepted, so the
        # caller gets the ordinary greeting and must step up through the app.
        return _ask(s, "intent", _intent_menu(with_greeting=True))
    greeting = (f"Hi {data.preferred_name(customer_id)}, thanks for calling from the app. "
                "You're already verified. ")
    return _ask(s, "intent", greeting + _intent_menu(with_greeting=False))


def _stage_intent(s: dict, digits: str, contact_id: str) -> dict | None:
    if digits == THIRD_PARTY_KEY:
        _add_reason(s, "THIRD_PARTY_CLAIM")
        return _ask(s, "intent", "I can only make changes with the account holder. If you help someone manage "
                                 "their money, I can explain how to set up a third-party authority. "
                                 + _intent_menu(with_greeting=False))
    intent = next((name for key, name, _ in INTENT_MENU if key == digits), None)
    if intent is None:
        return None
    s["intent"] = intent
    lead = ""
    if intent == "report_lost_stolen":
        s["stolen"] = True   # the stolen phone is removed from push targets for this contact
        _add_reason(s, "DEVICE_REPORTED_STOLEN")
        lead = "I'm sorry to hear that."
    return _progress(s, contact_id, lead)


def _stage_own(s: dict, digits: str, contact_id: str) -> dict | None:
    if digits == "1":
        s["cand"], s["own"], s["rel"] = s["cands"][0], True, "MATCH"
        return _progress(s, contact_id)
    if digits == "2":
        # Borrowed phone: drop the CLI candidate completely. Nothing about the
        # phone's owner is used or disclosed again on this contact.
        s["cands"], s["cand"], s["own"], s["rel"] = [], "", None, "MISMATCH"
        s["loa"] = policy.LOA_ANONYMOUS
        s["borrowed"] = True
        _add_reason(s, "CLI_CANDIDATE_DROPPED")
        return _ask_claim_dob(s, "No problem.")
    return None


def _stage_claim_dob(s: dict, digits: str, contact_id: str) -> dict | None:
    if len(digits) != 8 or not digits.isdigit():
        return None
    s["dob"] = digits
    return _ask(s, "claim_card", "And the last four digits of your card? "
                                 + _harness("key the four digits, then hash."))


def _stage_claim_card(s: dict, digits: str, contact_id: str) -> dict | None:
    if len(digits) != 4 or not digits.isdigit():
        return None
    customer_id = verifiers.resolve_claimed_identity(s.pop("dob", ""), digits)
    if not customer_id:
        s["claims"] += 1
        _add_reason(s, "CLAIMED_IDENTITY_NOT_RESOLVED")
        if s["claims"] < MAX_CLAIM_ATTEMPTS:
            return _ask_claim_dob(s, "I couldn't find those details. Let's try once more.")
        s["dec"] = "DENY"
        return _ask(s, "after", _after_menu(FAIL_NEUTRAL))
    s["cand"], s["own"] = customer_id, True
    s["rel"] = "MISMATCH" if s.get("borrowed") else _relationship(s, customer_id)
    level, _ = policy.baseline_loa(1, s["risk"])
    s["loa"] = max(s["loa"], level)
    _add_reason(s, "CLAIMED_IDENTITY_RESOLVED")
    return _progress(s, contact_id)


def _stage_push(s: dict, digits: str, contact_id: str) -> dict | None:
    code = verifiers.create_push_challenge(s["cand"], contact_id, _secret(), str(s["n"]))
    outcome = verifiers.check_push(digits, code)
    s["att"]["push"] = 1
    if outcome == "APPROVED":
        receipt = verifiers.issue_receipt("push", s["cand"], contact_id, s["intent"], _secret())
        _submit_receipt(s, receipt, contact_id)
        return _progress(s, contact_id)
    _add_reason(s, f"PUSH_{outcome}")
    return _progress(s, contact_id, "I haven't seen that come through." if outcome == "EXPIRED" else "")


def _stage_otp(s: dict, digits: str, contact_id: str) -> dict | None:
    code = verifiers.create_otp(s["cand"], contact_id, _secret(), str(s["n"]))
    s["att"]["otp"] = s["att"].get("otp", 0) + 1
    if verifiers.check_otp(digits, code):
        receipt = verifiers.issue_receipt(s.get("otp_m", "otp_sms"), s["cand"], contact_id, s["intent"], _secret())
        _submit_receipt(s, receipt, contact_id)
        return _progress(s, contact_id)
    _add_reason(s, "OTP_FAILED")
    if s["att"]["otp"] < policy.MAX_ATTEMPTS_PER_FACTOR:
        return _ask(s, "otp", "That didn't match. Please try the code once more. " + _harness("key it, then hash."))
    return _progress(s, contact_id)


def _stage_kba(s: dict, digits: str, contact_id: str) -> dict | None:
    s["att"]["kba"] = s["att"].get("kba", 0) + 1
    if verifiers.check_kba(s["cand"], digits):
        receipt = verifiers.issue_receipt("kba", s["cand"], contact_id, s["intent"], _secret())
        _submit_receipt(s, receipt, contact_id)
        return _progress(s, contact_id)
    _add_reason(s, "KBA_FAILED")
    if s["att"]["kba"] < policy.MAX_ATTEMPTS_PER_FACTOR:
        return _ask(s, "kba", "That didn't match. Please try once more. " + _harness("key the two digits, then hash."))
    return _progress(s, contact_id)


def _stage_after(s: dict, digits: str, contact_id: str) -> dict | None:
    if digits == "1":
        return _ask(s, "intent", _intent_menu(with_greeting=False))
    return _handoff(s)


_STAGES = {
    "mode": _stage_mode, "quick": _stage_quick, "line": _stage_line, "scenario": _stage_scenario,
    "dial": _stage_dial, "intent": _stage_intent, "own": _stage_own, "claim_dob": _stage_claim_dob,
    "claim_card": _stage_claim_card, "push": _stage_push, "otp": _stage_otp, "kba": _stage_kba,
    "after": _stage_after,
}

# Stages where silence is a meaningful answer rather than a mistake.
_TIMEOUT_IS_AN_ANSWER = {"push", "otp", "kba", "after"}


# ---------------------------------------------------------------------------
# Start of contact: pre-authenticated paths (Options D and E) and chat
# ---------------------------------------------------------------------------

def _start(s: dict, attrs: dict, contact_id: str) -> dict:
    def attr(key: str) -> str:
        # Amazon Connect's hosted chat widget prefixes custom attributes.
        return attrs.get(key) or attrs.get(f"HostedWidget-{key}", "")

    intent = attr("idvIntent")
    s["cli"], s["kind"] = s["real"], ("real" if s["real"] else "withheld")

    quick = attr("idvTestCustomerId")
    if quick:
        if quick in data.STUB_CUSTOMERS:
            return _quick_select(s, quick)
        _add_reason(s, "TEST_CUSTOMER_UNKNOWN")

    token_attr, token_typ, method = ("idvSessionToken", "session", "chat_session") if s["ch"] == "chat" \
        else ("idvCallToken", "call", "app_handoff")
    token = attr(token_attr)
    if token:
        payload = verifiers.check_preauth_token(token, token_typ, _secret())
        if payload:
            # The contact inherits the app or chat session's level: no questions asked.
            _run_silent_cli_checks(s)
            s["cand"], s["own"], s["rel"] = payload["cust"], True, _relationship(s, payload["cust"])
            receipt = verifiers.issue_receipt(method, payload["cust"], contact_id, "", _secret(),
                                              loa=int(payload.get("loa", 2)))
            _submit_receipt(s, receipt, contact_id)
        else:
            _add_reason(s, "PREAUTH_TOKEN_INVALID")

    if s["ch"] == "chat":
        return _start_chat(s, attr, intent, contact_id)

    if s["loa"] >= policy.LOA_VERIFIED:
        greeting = (f"Hi {data.preferred_name(s['cand'])}, thanks for calling from the app. "
                    "You're already verified. ")
        return _ask(s, "intent", greeting + _intent_menu(with_greeting=False))
    return _ask(s, "mode", _mode_menu())


def _start_chat(s: dict, attr, intent: str, contact_id: str) -> dict:
    """
    Chat has no keypad, so the whole decision is made from contact attributes
    in one invocation. In chat the SESSION is the identifier, never the device
    number, and knowledge questions (KBA) are never asked.
    """
    if s["loa"] < policy.LOA_VERIFIED:
        _add_reason(s, "UNAUTHENTICATED_CHAT", "NO_KBA_OVER_CHAT")
    if intent in policy.INTENT_REQUIRED_LOA:
        s["intent"] = intent
        decision = policy.evaluate(intent, s["loa"], s["risk"], identified=bool(s["cand"]))
        if decision["decision"] == "STEP_UP" and s["cand"]:
            sca = verifiers.check_preauth_token(attr("idvStepUpToken"), "sca", _secret())
            # The in-app biometric must be for THIS customer and THIS request.
            if sca and sca["cust"] == s["cand"] and sca.get("intent") == intent:
                receipt = verifiers.issue_receipt("sca", s["cand"], contact_id, intent, _secret())
                _submit_receipt(s, receipt, contact_id)
                decision = policy.evaluate(intent, s["loa"], s["risk"], identified=True)
            elif attr("idvStepUpToken"):
                _add_reason(s, "STEP_UP_TOKEN_INVALID")
        s["dec"], s["obl"] = decision["decision"], decision["obligations"]
        _add_reason(s, *decision["reasons"])
    return _handoff(s)


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------

def handler(event: dict, context: Any) -> dict:
    """
    Entry point. Called by Amazon Connect via the "Invoke AWS Lambda function"
    block. Never raises: any failure returns action="end" with a spoken message.
    """
    details: dict = event.get("Details", {}) or {}
    contact: dict = details.get("ContactData", {}) or {}
    params: dict = details.get("Parameters", {}) or {}
    attrs: dict = contact.get("Attributes", {}) or {}
    contact_id: str = contact.get("ContactId", "")
    operation: str = params.get("operation", "start")
    channel = "chat" if (contact.get("Channel") or "VOICE").upper() == "CHAT" else "voice"
    real_cli: str = (contact.get("CustomerEndpoint") or {}).get("Address", "") or ""

    blank = _new_state(channel, data.normalise_phone(real_cli) if real_cli else "")

    def refuse(reason: str, spoken: str) -> dict:
        logger.error("ID&V test harness refused to run: %s", reason)
        return {"action": "end", "prompt": spoken, "idvState": "", "customerId": "",
                "authStatus": "unauthenticated", "LoA": "0", "idvMethod": "none", "cliRelationship": "NONE",
                "riskScore": "0", "reasonCodes": reason, "idvStatus": "anonymous", "idvIntent": "",
                "idvDecision": "", "idvObligations": "", "idvSummary": reason}

    if os.environ.get("IDV_TEST_HARNESS_ENABLED", "").lower() != "true":
        return refuse("HARNESS_DISABLED", "The test harness is switched off.")
    if len(_secret()) < 16:
        return refuse("HARNESS_SECRET_MISSING", "The test harness is not configured.")
    if not contact_id:
        return refuse("MISSING_CONTACT_ID", "The test harness could not read this contact.")

    try:
        if operation == "start":
            reply = _start(blank, attrs, contact_id)
        else:
            state = verifiers.verify_token(attrs.get("idvState", ""), _secret())
            if not state or state.get("st") not in _STAGES:
                # Missing or tampered state: start again rather than trust it.
                logger.warning("idvState missing or invalid for contact %s; restarting", contact_id)
                reply = _start(blank, attrs, contact_id)
            else:
                reply = _step(state, _clean(params.get("input", "")), contact_id)
    except Exception:
        logger.exception("ID&V test harness failed for contact %s", contact_id)
        return refuse("HARNESS_ERROR", "The test harness hit a problem. Please try again.")

    logger.info(json.dumps({"contactId": contact_id, "operation": operation, "action": reply["action"],
                            "summary": reply["idvSummary"], "reasonCodes": reply["reasonCodes"]}))
    return reply


def _step(s: dict, digits: str, contact_id: str) -> dict:
    stage = s["st"]
    timed_out = digits == "Timeout"
    reply = None
    if not timed_out or stage in _TIMEOUT_IS_AN_ANSWER:
        reply = _STAGES[stage](s, digits, contact_id)
    if reply is not None:
        s["bad"] = 0
        reply["idvState"] = verifiers.sign_token(s, _secret())
        return reply

    # Input the stage did not understand: repeat the question, then give up.
    s["bad"] += 1
    if s["bad"] > MAX_INVALID_INPUTS:
        return _end(s, _harness("no valid input received. Goodbye."))
    repeat = {
        "mode": _mode_menu, "quick": _customer_menu, "line": lambda: _line_menu(s), "scenario": _scenario_menu,
        "dial": lambda: _harness("key the six-digit app dial code, then hash."),
        "intent": lambda: _intent_menu(with_greeting=False),
        "own": lambda: _harness("press 1 for yes or 2 for no, then hash."),
        "claim_dob": lambda: _harness("key the date of birth as eight digits, day month year, then hash."),
        "claim_card": lambda: _harness("key the last four digits of the card, then hash."),
    }[stage]()
    return _ask(s, stage, f"Sorry, I didn't get that. {repeat}")
