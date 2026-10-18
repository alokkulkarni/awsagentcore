"""
dispute_model.py
================
What a card dispute is: its fields, the values each may take, what "complete"
means, and the test transactions a dispute can be raised against.

Nothing here talks to AWS. See SPEC.md section 4 for the record and its rules.

The customers' cards and card payments come from the sample bank's one copy of its
data (connect-money-hub/moneyhub/data.py), so the payment a customer disputes is
the one ARIA, the Money Hub and internet banking show. The package carries
moneyhub/__init__.py and moneyhub/data.py (deploy_card_dispute.sh copies them).

ALL TRANSACTIONS ARE FICTIONAL TEST DATA. Never put real customer data here.
"""

from __future__ import annotations

from moneyhub import data as bank

# Three kinds of case, each a dispute on the record:
#   unauthorised  FRAUD    the customer did not make the payment (or the card was lost or stolen)
#   scam          SCAM     the customer made it, but was tricked into it
#   merchant      DISPUTE  the customer made it, and something went wrong with what they paid for
UNAUTHORISED, SCAM, MERCHANT = "unauthorised", "scam", "merchant"
DISPUTE_TYPES = (UNAUTHORISED, SCAM, MERCHANT)
CASE_WORDS = {UNAUTHORISED: "Fraud", SCAM: "Scam", MERCHANT: "Dispute"}
# Fraud and scam cases block the card; a dispute with a retailer does not.
CARD_AT_RISK = (UNAUTHORISED, SCAM)

# The reasons a customer can give, by type, with the words shown on screen.
REASONS: dict[str, dict[str, str]] = {
    UNAUTHORISED: {
        "card_lost_or_stolen": "Card was lost or stolen",
        "card_details_used_without_card": "Card details used without the card",
        "not_recognised": "Customer does not recognise the payment",
    },
    SCAM: {
        "fake_seller_or_website": "Paid a fake seller or website",
        "impersonation": "Tricked by someone pretending to be a company, the police or the bank",
        "investment_or_romance": "Investment or romance scam",
        "other_scam": "Another kind of scam",
    },
    MERCHANT: {
        "goods_not_received": "Goods or services not received",
        "not_as_described": "Not as described or faulty",
        "charged_twice": "Charged twice",
        "wrong_amount": "Charged the wrong amount",
        "cancelled_subscription": "Charged after cancelling",
        "refund_not_received": "Refund not received",
    },
}
TYPE_WORDS = {UNAUTHORISED: "Payment the customer did not make", SCAM: "Customer was tricked into making the payment",
              MERCHANT: "Problem with a payment the customer made"}

# What the assistant tells the customer happens next, by case. It says only this,
# word for word, so it never invents a timescale or promises an outcome.
# PLACEHOLDER WORDING: replace with your bank's approved text before real use.
WHAT_HAPPENS_NEXT = {
    UNAUTHORISED: ("Our fraud team will investigate this payment. Fraud cases are usually looked into within "
                   "15 working days, and we'll keep you updated. A colleague will now check the details with you."),
    SCAM: ("Our fraud team will review what happened. Scam cases are usually reviewed within 15 working days, and "
           "whether any money can be recovered depends on the case. A colleague will now check the details with you."),
    MERCHANT: ("We'll ask the retailer to respond on your behalf. Most card disputes are settled within 8 weeks, and "
               "it can take longer if the retailer challenges it. A colleague will now check the details with you."),
}
YES_NO = ("yes", "no")

DRAFT, WITH_ADVISER, SUBMITTED, WITHDRAWN = "draft", "with_adviser", "submitted", "withdrawn"
OPEN_STATUSES = (DRAFT, WITH_ADVISER)
STATUS_WORDS = {DRAFT: "Being filled in", WITH_ADVISER: "With an adviser", SUBMITTED: "Submitted", WITHDRAWN: "Withdrawn"}

NARRATIVE_MAX_CHARS = 600

# Fields a tool call or the adviser page may set, and the values each accepts.
# None means free text. The transaction is set separately (rule R5).
EDITABLE: dict[str, tuple[str, ...] | None] = {
    "disputeType": DISPUTE_TYPES,
    "reason": tuple(code for reasons in REASONS.values() for code in reasons),
    "cardInPossession": YES_NO,
    "cardBlocked": YES_NO,
    "contactedMerchant": YES_NO,
    "narrative": None,
}
# Changing one of these after the customer confirmed clears the confirmation (rule R6).
CONFIRMATION_SENSITIVE = ("transactionId", "disputeType", "reason")

LABELS = {
    "transaction": "Transaction",
    "disputeType": "What happened",
    "reason": "Reason",
    "cardInPossession": "Customer still has the card",
    "cardBlocked": "Card blocked",
    "contactedMerchant": "Customer has contacted the retailer",
    "narrative": "In the customer's words",
}

def customer_cards(customer_id: str) -> list[dict]:
    """The customer's cards, as the bank holds them. A card can only be blocked or replaced if it is here."""
    held = (bank.profile(customer_id) or {}).get("cards", [])
    return [{"card_type": c["type"], "card_last_four": c["ending"]} for c in held]


def card_transactions(customer_id: str, card_type: str = "") -> list[dict]:
    """The customer's recent card transactions, newest first, optionally for one card type. The ids are stable, so
    ARIA can pass one back to start a dispute."""
    transactions = []
    for held in customer_cards(customer_id):
        kind, last_four = held["card_type"], held["card_last_four"]
        if card_type and kind != card_type:
            continue
        for p in bank.card_payments(customer_id, kind):
            transactions.append({
                "transaction_id": p["transactionId"], "date": p["date"], "merchant": p["merchant"],
                "amount": f"{p['amount']:.2f}", "currency": "GBP", "card_type": kind, "card_last_four": last_four,
            })
    return sorted(transactions, key=lambda t: t["date"], reverse=True)


def find_transaction(customer_id: str, transaction_id: str) -> dict | None:
    """One of the customer's own transactions, or None. A dispute can only be about these (rule R5)."""
    return next((t for t in card_transactions(customer_id) if t["transaction_id"] == transaction_id), None)


def missing(dispute: dict) -> list[str]:
    """Labels of what still has to be filled in before the dispute can be submitted."""
    needed = ["disputeType", "reason", "narrative"]
    if dispute.get("disputeType") in CARD_AT_RISK:
        needed.append("cardInPossession")
    elif dispute.get("disputeType") == MERCHANT:
        needed.append("contactedMerchant")
    gaps = [] if dispute.get("transactionId") else [LABELS["transaction"]]
    gaps += [LABELS[name] for name in needed if not dispute.get(name)]
    reason, kind = dispute.get("reason"), dispute.get("disputeType")
    if reason and kind and reason not in REASONS.get(kind, {}):
        gaps.append(f"{LABELS['reason']} (does not fit '{TYPE_WORDS[kind]}')")
    return gaps


def check_fields(fields: dict) -> dict:
    """
    The acceptable subset of `fields`, cleaned. Raises ValueError naming the
    first field that is not editable or holds a value it does not accept.
    Rejects, never coerces.
    """
    clean = {}
    for name, value in fields.items():
        if name not in EDITABLE:
            raise ValueError(f"{name} cannot be set")
        if not isinstance(value, str):
            raise ValueError(f"{name} must be text")
        value = value.strip()
        allowed = EDITABLE[name]
        if allowed is None:
            value = " ".join(value.split())[:NARRATIVE_MAX_CHARS]
        elif value not in allowed:
            raise ValueError(f"{name} must be one of: {', '.join(allowed)}")
        clean[name] = value
    return clean


def payment_words(dispute: dict) -> str:
    """'AMAZON.CO.UK, £89.99 on 2026-10-11, debit card ending 4821', or '' before a payment is chosen."""
    if not dispute.get("transactionId"):
        return ""
    return (f"{dispute['merchant']}, £{dispute['amount']} on {dispute['transactionDate']}, "
            f"{dispute['cardType']} card ending {dispute['cardLastFour']}")


def view(dispute: dict) -> dict:
    """The dispute as the pages and the tools see it: readable, and without internal fields."""
    kind = dispute.get("disputeType", "")
    confirmation = dispute.get("customerConfirmation") or {}
    return {
        "disputeId": dispute["disputeId"],
        "status": dispute["status"],
        "statusWords": STATUS_WORDS[dispute["status"]],
        "version": int(dispute.get("version", 0)),
        "cardType": dispute.get("cardType", ""),
        "cardLastFour": dispute.get("cardLastFour", ""),
        "transactionId": dispute.get("transactionId", ""),
        "transactionDate": dispute.get("transactionDate", ""),
        "merchant": dispute.get("merchant", ""),
        "amount": dispute.get("amount", ""),
        "currency": dispute.get("currency", ""),
        "disputeType": kind,
        "disputeTypeWords": TYPE_WORDS.get(kind, ""),
        "caseType": CASE_WORDS.get(kind, ""),
        "whatHappensNext": WHAT_HAPPENS_NEXT.get(kind, ""),
        "reason": dispute.get("reason", ""),
        "reasonWords": REASONS.get(kind, {}).get(dispute.get("reason", ""), ""),
        "cardInPossession": dispute.get("cardInPossession", ""),
        "cardBlocked": dispute.get("cardBlocked", ""),
        "contactedMerchant": dispute.get("contactedMerchant", ""),
        "narrative": dispute.get("narrative", ""),
        "filledBy": dict(dispute.get("filledBy") or {}),
        "missing": missing(dispute),
        "customerConfirmed": bool(confirmation.get("accepted")),
        "confirmationSource": confirmation.get("source", ""),
    }
