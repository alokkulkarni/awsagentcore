"""
flowview.py
===========
"How it works", for demos: where a chat or call from the app has got to, as facts the page turns into words
anyone can follow (web/flowview/flowview.js). Read from Connect's own record of the contact, never the browser:

    ARIA has joined     DescribeContact: the contact has its Amazon Q in Connect session (WisdomInfo)
    a specialist        the contact attributes the flow writes as it hands over (connect-bot-flow-modular):
                          entry card_dispute or aria, or handbackRoute card_dispute    the card dispute assistant
                          entry web_widget, or handbackRoute mortgage_livesync         the mortgage assistant
                            or mortgage_form
                          the Money Hub bridge's mark on the contact (specialist#…)   the Money Hub agent (*)
    back to ARIA        entry returned (returnedFrom card_dispute or mortgage): the specialist handed the customer
                        back (dispute rule R15, mortgage FR-39)
    a colleague         handbackRoute human (waiting); AgentInfo.ConnectedToAgentTimestamp (joined)
    the dispute         the dispute service: a dispute this conversation started, sent or submitted
    ended               DisconnectTimestamp

(*) Nothing in Connect records the Money Hub hand-over (ARIA calls the Money Hub agent over A2A, and the Q in
Connect messages don't say which agent spoke), so the Money Hub bridge marks the contact when a stint starts and
when it hands back to ARIA (connect-money-hub bridge/a2a_bridge.py SPECIALIST_KEY), in the table both share.

Whether the view shows at all is one setting, read at run time so it can be turned off without a redeploy: the
SSM parameter /aria-banking-app/flow-view (FLOW_VIEW_PARAMETER), "on" or "off". Missing or unreadable is "off",
so a missing permission can never put it in front of a customer. FLOW_VIEW=on|off overrides it (local preview).
"""

from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger()

PARAMETER = os.environ.get("FLOW_VIEW_PARAMETER", "/aria-banking-app/flow-view")
CACHE_SECONDS = 30
SPECIALIST_KEY = "specialist#{contact_id}"        # written by the Money Hub bridge (the same format, kept in step by a test)             # how long a read of the setting stands: turning it off shows within this
DISPUTE_STATUSES = {"draft": "started", "submitted": "submitted", "with_adviser": "with_adviser"}   # dispute_model's

_ssm = None
_cached = {"at": -CACHE_SECONDS, "on": False}


def ssm_client():
    """AWS Systems Manager, created on first use (replaced in tests)."""
    global _ssm
    if _ssm is None:
        import boto3
        _ssm = boto3.client("ssm")
    return _ssm


def enabled(clock=time.time) -> bool:
    """Whether the demo view shows: FLOW_VIEW if set, else the SSM setting (cached), else off."""
    override = os.environ.get("FLOW_VIEW", "").strip().lower()
    if override in ("on", "off"):
        return override == "on"
    now = clock()
    if now - _cached["at"] < CACHE_SECONDS:
        return _cached["on"]
    try:
        value = ssm_client().get_parameter(Name=PARAMETER)["Parameter"]["Value"]
        on = value.strip().lower() == "on"
    except Exception as error:                     # missing, no permission, no network: off
        logger.info("flow view off: %s", type(error).__name__)
        on = False
    _cached.update(at=now, on=on)
    return on


def money_hub_stint(mark: dict | None) -> str:
    """The Money Hub agent on this contact, from the bridge's mark: "active", "done" (handed back) or ""."""
    mark = mark or {}
    if not mark.get("moneyHubStartedAt"):
        return ""
    return "done" if float(mark.get("moneyHubFinishedAt") or 0) >= float(mark["moneyHubStartedAt"]) else "active"


def specialist(attributes: dict, money_hub: str = "") -> tuple[str, str]:
    """(who, basis): the assistant helping the customer now, and how we know ("connect": Connect's record or the
    Money Hub bridge's mark)."""
    entry, route = attributes.get("entry", ""), attributes.get("handbackRoute", "")
    # The flow's own transfers come first: while one of those assistants has the contact, ARIA (and so the Money Hub
    # agent she calls) is out of the conversation.
    if route == "card_dispute" or entry in ("card_dispute", "aria"):     # "aria": the flow's mark of a dispute
        return "card_dispute", "connect"
    if route in ("mortgage_livesync", "mortgage_form") or entry == "web_widget":
        return "mortgage", "connect"
    if money_hub == "active":
        return "money_hub", "connect"
    return "", ""


def state(described: dict, attributes: dict, dispute: dict | None = None, money_hub_mark: dict | None = None) -> dict:
    """Where the contact has got to, from DescribeContact's Contact, its attributes, (optionally) the dispute this
    conversation is about ({status, formSent}) and the Money Hub bridge's mark. Facts only: the page words them.
    back: the specialist that last handed back to ARIA, while she is helping again."""
    attributes = attributes or {}
    stint = money_hub_stint(money_hub_mark)
    who, basis = specialist(attributes, stint)
    returned_from = attributes.get("returnedFrom", "") if attributes.get("entry") == "returned" else ""
    agent = described.get("AgentInfo") or {}
    colleague = "joined" if agent.get("ConnectedToAgentTimestamp") else "waiting" if attributes.get("handbackRoute") == "human" else ""
    found = {
        "aria": bool((described.get("WisdomInfo") or {}).get("SessionArn")),
        "specialist": who, "basis": basis, "colleague": colleague,
        "ended": bool(described.get("DisconnectTimestamp")),
        "trouble": attributes.get("handbackOutcome") == "error",       # ARIA's block failed; the flow carried on
        "returned": attributes.get("entry") == "returned",              # back to ARIA from a specialist
        "returnedFrom": returned_from,
        "moneyHub": stint,
        # Only ARIA escalates (dispute rule R16, mortgage FR-40): a specialist sent the customer back for a colleague.
        "colleagueAsked": attributes.get("entry") == "returned" and attributes.get("returnIntent") == "escalate",
        "back": "" if who else ("money_hub" if stint == "done" else returned_from),
    }
    if dispute and dispute.get("status") in DISPUTE_STATUSES:
        found["dispute"] = {"status": DISPUTE_STATUSES[dispute["status"]], "formSent": bool(dispute.get("formSent"))}
    return found
