"""
dispute_model.py
================
What a card dispute is: its fields, the values each may take, what "complete"
means, and the test transactions a dispute can be raised against.

Nothing here talks to AWS. See SPEC.md section 4 for the record and its rules.

ALL TRANSACTIONS ARE FICTIONAL TEST DATA. Never put real customer data here.
"""

from __future__ import annotations

UNAUTHORISED, MERCHANT = "unauthorised", "merchant"
DISPUTE_TYPES = (UNAUTHORISED, MERCHANT)

# The reasons a customer can give, by type, with the words shown on screen.
REASONS: dict[str, dict[str, str]] = {
    UNAUTHORISED: {
        "card_lost_or_stolen": "Card was lost or stolen",
        "card_details_used_without_card": "Card details used without the card",
        "not_recognised": "Customer does not recognise the payment",
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
TYPE_WORDS = {UNAUTHORISED: "Payment the customer did not make", MERCHANT: "Problem with a payment the customer made"}
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

# customerId -> that customer's recent card transactions. The ids are stable, so
# ARIA can pass one back to start a dispute.
_CARDS = {
    "CUST-001": (("debit", "4821"), ("credit", "2291")),
    "CUST-002": (("debit", "3317"),),
    "CUST-003": (("debit", "6612"),),
    "CUST-004": (("debit", "7734"),),
    "CUST-005": (("debit", "1155"),),
}
_SPENDING = (
    ("2026-10-11", "AMAZON.CO.UK", "89.99"),
    ("2026-10-10", "TESCO STORES 2041", "42.50"),
    ("2026-10-09", "TRAINLINE.COM", "64.20"),
    ("2026-10-08", "NETFLIX.COM", "10.99"),
    ("2026-10-06", "ELECTROWORLD ONLINE", "349.00"),
    ("2026-10-04", "SUNSHINE VILLAS BOOKING", "612.00"),
)


def card_transactions(customer_id: str, card_type: str = "") -> list[dict]:
    """The customer's recent card transactions, newest first, optionally for one card type."""
    transactions = []
    for kind, last_four in _CARDS.get(customer_id, ()):
        if card_type and kind != card_type:
            continue
        # A credit card shows the second half of the list, so the two cards differ.
        spending = _SPENDING[3:] if kind == "credit" else _SPENDING[:4]
        for date, merchant, amount in spending:
            transactions.append({
                "transaction_id": f"TXN-{last_four}-{date.replace('-', '')}-{amount.replace('.', '')}",
                "date": date, "merchant": merchant, "amount": amount, "currency": "GBP",
                "card_type": kind, "card_last_four": last_four,
            })
    return sorted(transactions, key=lambda t: t["date"], reverse=True)


def find_transaction(customer_id: str, transaction_id: str) -> dict | None:
    """One of the customer's own transactions, or None. A dispute can only be about these (rule R5)."""
    return next((t for t in card_transactions(customer_id) if t["transaction_id"] == transaction_id), None)


def missing(dispute: dict) -> list[str]:
    """Labels of what still has to be filled in before the dispute can be submitted."""
    needed = ["disputeType", "reason", "narrative"]
    if dispute.get("disputeType") == UNAUTHORISED:
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
