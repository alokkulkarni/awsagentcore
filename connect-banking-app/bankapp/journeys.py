"""
journeys.py
===========
Which assistant helps, from the page the customer is on when they chat or call.

    Money Hub          entry=money_hub and the tab: exactly what the Money Hub page sends today, so the
                       session injector tells ARIA and ARIA hands over to the Money Hub agent.
    Mortgage form      entry=banking_app, appPage=mortgage, with the application and its stage: ARIA greets
                       the customer and hands over at once (the session injector tells her the form is open);
                       the bot flow then passes the contact to the mortgage assistant joined to this form
                       (entry=web_widget, as the mortgage page's own Point B), which fills it through Live Sync.
    Card dispute       entry=banking_app, appPage=card_dispute, with the payment the customer chose as
                       handoverSummary and their name as preferredName: ARIA greets them and hands over to
                       the card dispute assistant at once, naming that payment. An unverified link has ARIA
                       check who they are first. (Both pages went straight to the assistant until 20 Oct 2026;
                       now every page starts with ARIA, and the dispute assistant hands back to her.)
    Anything else      entry=banking_app and the page's name. ARIA helps on its own. In a chat, Accounts, Cards
                       and Help open with a line saying where the customer is (as the Money Hub does); on a
                       call the session injector gives ARIA the same as a known contact reason. Home sends
                       nothing, so ARIA opens with what she already knows about the customer.

Who the customer is comes from the page link's record on the server, never from the browser. Only a link
minted at Level 2 or above adds the verified fields (the Money Hub rule), and only then does a mortgage
contact carry the customerId.
"""

from __future__ import annotations

import re

from moneyhub import contact as money_hub

PAGES = {"home": "Home", "accounts": "Accounts", "cards": "Cards", "money_hub": "Money Hub",
         "mortgages": "Mortgages", "mortgage": "Mortgage application", "card_dispute": "Card dispute",
         "help": "Help"}
MORTGAGE_STAGES = {"about_you": "About you", "property_loan": "Property and loan",
                   "dip_result": "Decision in Principle", "product_selection": "Choose a product",
                   "documents": "Documents", "review_submit": "Review and submit"}
APPLICATION_ID = re.compile(r"^MA-[A-HJ-NP-Z2-9]{8}$")       # the mortgage page's own format


def verified_fields(customer_id: str, loa: str) -> dict:
    """What a Level 2+ link adds, as the Money Hub page does."""
    if not money_hub.verified_level(loa):
        return {}
    return {"customerId": customer_id, "authStatus": "authenticated", "idvStatus": "verified",
            "LoA": str(int(loa)), "idvMethod": "money_hub_link"}


def dispute_summary(payment: dict | None) -> str:
    """What the dispute assistant is told the customer wants (its handoverSummary), from the server's own record of
    the payment they chose. No card numbers beyond the last four, as ARIA's hand-over does."""
    if not payment:
        return "Wants to dispute a card payment."
    return (f"Wants to dispute a card payment: {payment['merchant']}, £{payment['amount']:.2f} on {payment['date']}, "
            f"{payment['card']} card ending {payment['ending']}. Chose it in internet banking.")


def attributes(page: str, customer_id: str, loa: str, view: str = "", stage: str = "",
               application_id: str = "", payment: dict | None = None, first_name: str = "") -> dict:
    """The contact attributes for a chat or call started on this page."""
    if page == "money_hub":
        # appPage marks a contact from this app (as on every other page): on a call, the dispute service then opens
        # its form here instead of texting it (a call from the browser has no number to text).
        return {**money_hub.attributes(customer_id, loa, view), "appPage": "money_hub"}
    if page == "mortgage":
        if stage not in MORTGAGE_STAGES:
            raise ValueError("unknown mortgage stage")
        if not APPLICATION_ID.match(application_id or ""):
            raise ValueError("unknown application")
        # ARIA first; the mortgage flow reads applicationId and stage when she hands over (and customerId if verified)
        return {"entry": "banking_app", "appPage": "mortgage", "applicationId": application_id, "stage": stage,
                **verified_fields(customer_id, loa)}
    verified = verified_fields(customer_id, loa)
    if page == "card_dispute":
        # ARIA first, told which payment (the session injector), then the dispute assistant starting from it
        return {"entry": "banking_app", "appPage": "card_dispute", "handoverSummary": dispute_summary(payment),
                **({"preferredName": first_name} if first_name else {}), **verified}
    return {"entry": "banking_app", "appPage": page if page in PAGES else "home", **verified}


def opener(page: str, view: str = "", stage: str = "", payment: dict | None = None) -> str:
    """The customer's first chat message, naming where they are, or "" for none. payment: the card payment they
    chose to dispute, from the server's own list (never words from the browser)."""
    if page == "money_hub":
        tab = money_hub.VIEWS.get(view, "Money out")
        return f"I'm on my Money Hub page, on the {tab} tab, and I'd like some help understanding my money."
    if page == "mortgage":
        return f"I'm filling in my mortgage application, on the {MORTGAGE_STAGES.get(stage, 'About you')} step."
    if page == "card_dispute":
        if payment:
            return (f"I'd like to dispute a card payment: {payment['merchant']}, £{payment['amount']:.2f} on "
                    f"{payment['date']}, on my {payment['card']} card ending {payment['ending']}.")
        return "I'd like to dispute a card payment."
    return PAGE_OPENERS.get(page, "")


# The other pages' first chat message, in the same spirit as the Money Hub's: where the customer is, so ARIA can
# start there. Home sends nothing: ARIA opens with what she knows about the customer.
PAGE_OPENERS = {
    "accounts": "I'm looking at my accounts in internet banking and I'd like some help with them.",
    "cards": "I'm looking at my cards and card payments in internet banking and I'd like some help with them.",
    "help": "I'm on the Help page in internet banking and I have a question.",
}


def start_request(kind: str, page: str, customer_id: str, loa: str, instance_id: str, flow_id: str,
                  client_token: str, view: str = "", stage: str = "", application_id: str = "",
                  payment: dict | None = None, first_name: str = "") -> dict:
    """Keyword arguments for connect.start_web_rtc_contact (kind "call") or start_chat_contact (kind "chat")."""
    request = money_hub.start_request(kind, customer_id, loa, view, instance_id, flow_id, client_token)
    request["Attributes"] = attributes(page, customer_id, loa, view, stage, application_id, payment, first_name)
    request["ParticipantDetails"] = {"DisplayName": "Customer"}
    return request
