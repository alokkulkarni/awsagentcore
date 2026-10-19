"""
handback_recovery.py — aria-handback-recovery
=============================================
Recovers ARIA's hand-back when Amazon Connect loses it on a chat.

Two Amazon Connect behaviours (seen from 16 October 2026) lose what ARIA decided when she hands a contact back:

  * CHAT, while ARIA has a collaborator (the Money Hub agent): every hand-back (Complete, Escalate, or a
    return-to-control tool) makes the Get customer input block fail with
        java.lang.NullPointerException: Cannot invoke "java.util.Map.size()" because "m" is null
    so the flow takes the block's Error branch.
  * CALL: the hand-back works, but Complete's own fields (nextStep, handoverSummary …) never reach the flow's Lex
    session attributes; only Tool=Complete does. (Escalate's fields do.)

ARIA's decision is always in her trace (Amazon Q in Connect spans): the tool she called, its fields, and a
return_to_agent step. conversation bot flow calls this Lambda (a) on the Get customer input block's Error branch and
(b) when Complete arrives without a nextStep. It reads the session's spans, finds a hand-back that has just happened
and hasn't been handled, sets the contact attributes the next blocks need (the same ones the flow sets from Lex on a
working hand-back), and returns where to go:

    route = card_dispute          Transfer to flow "Card dispute assistant"  (handoverSummary, entry=aria)
            mortgage_application  CALL only: the flow's phone mortgage path  (handoverSummary, buyerType,
                                  (its check on authStatus)                    screenCode, entry=phone)
            escalate              Transfer to the escalation flow            (topicCategory, escalationReason,
                                                                               customerIntent, conversationSummary)
            end                   Disconnect                                 (the customer needs nothing else)
            none                  nothing recovered: the flow carries on as before (its Loop back to ARIA)

A CHAT mortgage application escalates, as the flow already does for a chat (topicCategory mortgage_application).

It never invents a decision: no hand-back span, one older than MAX_AGE_SECONDS, or one already handled
(handledHandback attribute) gives route=none, or route=end when the flow passes whenNothing=end (the Complete
branch: ARIA did hand back, so the conversation is over).
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

MAX_AGE_SECONDS = int(os.environ.get("MAX_AGE_SECONDS", "90"))
WAIT_SECONDS = float(os.environ.get("WAIT_SECONDS", "6"))       # spans can take a moment to be written
POLL_SECONDS = 1.0
HAND_BACK_TOOLS = ("Complete", "Escalate", "StartCardDispute", "StartMortgageApplication")

_clients: dict = {}


def _client(name: str):
    if name not in _clients:
        import boto3
        _clients[name] = boto3.client(name)
    return _clients[name]


def _when(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _session(contact: dict) -> tuple[str, str] | None:
    """(assistantId, sessionId) from the contact's sessionId attribute (the injector sets it), else DescribeContact."""
    arn = (contact.get("Attributes") or {}).get("sessionId", "")
    if not arn.startswith("arn:aws:wisdom:"):
        instance_id = contact.get("InstanceARN", "").split("/")[-1]
        described = _client("connect").describe_contact(InstanceId=instance_id, ContactId=contact["ContactId"])
        arn = (described["Contact"].get("WisdomInfo") or {}).get("SessionArn", "")
    parts = arn.split("/")
    return (parts[-2], parts[-1]) if arn.startswith("arn:aws:wisdom:") and len(parts) >= 3 else None


def _spans(assistant_id: str, session_id: str) -> list[dict]:
    spans, token = [], None
    while True:
        page = _client("qconnect").list_spans(assistantId=assistant_id, sessionId=session_id,
                                              **({"nextToken": token} if token else {}))
        spans += page.get("spans", [])
        token = page.get("nextToken")
        if not token:
            return spans


def find_hand_back(spans: list[dict], handled: str, now: datetime) -> dict | None:
    """The newest orchestrator hand-back not yet handled and recent enough, with the tool call that made it:
    {spanId, tool, arguments}. None if there isn't one."""
    backs = [s for s in spans if s.get("spanName") == "return_to_agent"
             and (s.get("attributes") or {}).get("aiAgentType") == "ORCHESTRATION"]     # ARIA's, never a collaborator's
    if not backs:
        return None
    back = max(backs, key=lambda s: _when(s["startTimestamp"]))
    if back.get("spanId") == handled or (now - _when(back["startTimestamp"])).total_seconds() > MAX_AGE_SECONDS:
        return None
    # The tool call is in the inference step of the same turn (same parent span), the last hand-back tool it used.
    turn = [s for s in spans if s.get("spanName") == "inference" and s.get("parentSpanId") == back.get("parentSpanId")]
    for step in sorted(turn, key=lambda s: _when(s["startTimestamp"]), reverse=True):
        for message in reversed((step.get("attributes") or {}).get("outputMessages") or []):
            for value in message.get("values") or []:
                use = value.get("toolUse") or {}
                if use.get("name") in HAND_BACK_TOOLS:
                    try:
                        arguments = json.loads(use.get("arguments") or "{}")
                    except (TypeError, ValueError):
                        arguments = {}
                    return {"spanId": back.get("spanId", ""), "tool": use["name"],
                            "arguments": arguments if isinstance(arguments, dict) else {}}
    return None


def decide(hand_back: dict, channel: str = "CHAT") -> tuple[str, dict]:
    """(route, contact attributes to set) for a recovered hand-back, as the flow's own blocks would set them."""
    tool, args = hand_back["tool"], hand_back["arguments"]
    step = args.get("nextStep", "")
    summary = str(args.get("handoverSummary", ""))[:300]
    if tool == "StartCardDispute" or (tool == "Complete" and step == "card_dispute"):
        return "card_dispute", {"handoverSummary": summary or "Wants to dispute a card payment.", "entry": "aria"}
    if (tool == "StartMortgageApplication" or (tool == "Complete" and step == "mortgage_application")) \
            and channel == "VOICE":
        code = str(args.get("screenCode", ""))
        return "mortgage_application", {"handoverSummary": summary, "buyerType": str(args.get("buyerType", "unknown")),
                                        "screenCode": code if code.isdigit() and len(code) == 6 else "",
                                        "entry": "phone"}
    if tool == "StartMortgageApplication" or (tool == "Complete" and step == "mortgage_application"):
        return "escalate", {"topicCategory": "mortgage_application", "escalationReason": "mortgage_application_chat",
                            "customerIntent": "start_mortgage_application", "conversationSummary": summary}
    if tool == "Escalate":
        return "escalate", {k: str(args.get(k, ""))[:500] for k in
                            ("topicCategory", "escalationReason", "customerIntent", "conversationSummary")}
    if tool == "Complete":
        return "end", {}
    return "none", {}


def lambda_handler(event: dict, context=None) -> dict:
    contact = (event.get("Details") or {}).get("ContactData") or {}
    contact_id = contact.get("ContactId", "")
    # The Complete branch passes whenNothing=end: ARIA did hand back, so with nothing to recover the call ends.
    nothing = "end" if ((event.get("Details") or {}).get("Parameters") or {}).get("whenNothing") == "end" else "none"
    try:
        session = _session(contact)
        if not session:
            logger.info("contact=%s no Q in Connect session; nothing to recover", contact_id)
            return {"route": nothing}
        handled = (contact.get("Attributes") or {}).get("handledHandback", "")
        deadline = time.monotonic() + WAIT_SECONDS
        while True:
            hand_back = find_hand_back(_spans(*session), handled, datetime.now(timezone.utc))
            if hand_back or time.monotonic() >= deadline:
                break
            time.sleep(POLL_SECONDS)
        if not hand_back:
            logger.info("contact=%s no unhandled hand-back in ARIA's trace", contact_id)
            return {"route": nothing}
        route, attributes = decide(hand_back, contact.get("Channel", "CHAT"))
        if route == "none":
            return {"route": nothing}
        _client("connect").update_contact_attributes(
            InitialContactId=contact.get("InitialContactId") or contact_id,
            InstanceId=contact.get("InstanceARN", "").split("/")[-1],
            Attributes={**attributes, "handledHandback": hand_back["spanId"]})
        # Fields only, never the summary's words (they can hold what the customer said).
        logger.info("contact=%s recovered %s -> %s (span %s)", contact_id, hand_back["tool"], route, hand_back["spanId"])
        return {"route": route, "recoveredTool": hand_back["tool"]}
    except Exception:                                    # never fail the contact: the flow falls back as before
        logger.exception("contact=%s hand-back recovery failed", contact_id)
        return {"route": nothing}
