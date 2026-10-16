"""
contact.py
==========
Starting a call or chat with ARIA from the Money Hub page.

The page never talks to Amazon Connect's admin API. It asks the page Lambda,
which builds the request here and calls StartWebRTCContact (a call, joined in the
browser with the Amazon Chime SDK) or StartChatContact (a chat, over the Connect
Participant Service). The browser then gets only what it needs to join.

Everything that tells ARIA who this is comes from the page link's record on the
server, never from the browser:
  - a link minted inside a contact verified at Level 2 or above starts a contact
    that arrives verified (customerId, authStatus, idvStatus, LoA), so ARIA can
    let the Money Hub agent take over at once;
  - any other link (a demo link, or one from a contact without a level) starts
    an anonymous contact, and ARIA verifies the customer as it normally would.
The page's current view goes along as moneyHubView, so the agent knows where
the customer was looking. In a chat, the page also opens with a customer
message naming the tab, so ARIA knows at once what the chat is about.
"""

from __future__ import annotations

VIEWS = {"out": "Money out", "in": "Money in", "expected": "Expected", "transactions": "Transactions", "goals": "Goals"}
ENTRY = "money_hub"


def verified_level(loa: str) -> bool:
    level = str(loa or "").strip()
    return level.isdigit() and int(level) >= 2


def attributes(customer_id: str, loa: str, view: str) -> dict:
    """Contact attributes. Connect stores them on the contact; the bot flow and the bridge read them."""
    values = {"entry": ENTRY, "moneyHubView": view if view in VIEWS else "out"}
    if verified_level(loa):
        values.update({"customerId": customer_id, "authStatus": "authenticated", "idvStatus": "verified",
                       "LoA": str(int(loa)), "idvMethod": "money_hub_link"})
    return values


def start_request(kind: str, customer_id: str, loa: str, view: str, instance_id: str, flow_id: str,
                  client_token: str) -> dict:
    """Keyword arguments for connect.start_web_rtc_contact (kind "call") or start_chat_contact (kind "chat")."""
    request = {"InstanceId": instance_id, "ContactFlowId": flow_id, "ClientToken": client_token,
               "ParticipantDetails": {"DisplayName": "Money Hub customer"},
               "Attributes": attributes(customer_id, loa, view)}
    if kind == "call":
        return request                  # no AllowedCapabilities: audio only, no video or screen sharing
    # No InitialMessage: it isn't documented to reach a Lex bot, so the page sends its opening line as an
    # ordinary customer message once ARIA has greeted (web/talk.js).
    request["SupportedMessagingContentTypes"] = ["text/plain", "text/markdown"]
    return request


def browser_reply(kind: str, response: dict) -> dict:
    """Only what the page needs to join. The participant token is a secret for this one contact."""
    reply = {"contactId": response.get("ContactId", ""), "participantToken": response.get("ParticipantToken", "")}
    if kind == "call":
        data = response.get("ConnectionData") or {}
        reply["meeting"] = data.get("Meeting") or {}
        reply["attendee"] = data.get("Attendee") or {}
    return reply
