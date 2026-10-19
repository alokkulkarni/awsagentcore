"""
disputes.py
===========
The customer's card disputes in the banking app, using the dispute service's own code (dispute_service,
dispute_store, dispute_model, packaged unchanged from connect-card-dispute/lambda) on its own table, so the
app sees exactly what the dispute assistant and the adviser see.

    list_disputes   the customer's disputes, newest first, for the Help and Cards pages
    submit          the customer submits their own complete draft (the service's rule R11)
    live            during a conversation: the customer's open dispute, and whether the dispute assistant has
                    sent its form since this conversation began (on a call it texts it; in a chat it posts it)
    open_live       opens that dispute's form in the app, joined to the app's own call or chat: the service's
                    own mint_form_link and open_form_link, as if the customer had opened the texted link. The
                    form then fills in through Live Sync exactly as on the dispute page.

Nothing here changes a dispute's details: opening the form only marks that the customer is watching, as the
dispute page does.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

TABLE = os.environ.get("DISPUTE_TABLE_NAME", "")
PAGES_URL = os.environ.get("DISPUTE_PAGES_URL", "").rstrip("/")
SHOWN = 10                     # disputes listed

try:                           # the dispute service's code, packaged alongside (unchanged)
    import dispute_model as model
    from dispute_service import DisputeError, DisputeService
    from dispute_store import DynamoStore, MemoryStore
except ImportError:            # pragma: no cover - running without the dispute code
    model = DisputeService = DisputeError = DynamoStore = MemoryStore = None

_service = None


class NotAvailable(Exception):
    """The dispute service isn't set up for this app."""


def service():
    """The dispute service on its own table (replaced in tests)."""
    global _service
    if _service is None:
        if DisputeService is None or not TABLE:
            raise NotAvailable()
        _service = DisputeService(DynamoStore(TABLE, time.time), time.time, page_url=PAGES_URL)
    return _service


def _summary(dispute: dict) -> dict:
    shown = model.view(dispute)
    return {**{k: shown[k] for k in ("disputeId", "status", "statusWords", "merchant", "amount", "transactionDate",
                                     "cardType", "cardLastFour", "missing")},
            "open": dispute["status"] in model.OPEN_STATUSES, "updatedAt": dispute.get("updatedAt", ""),
            "formSentAt": dispute.get("linkSentAt", ""), "formSentVia": dispute.get("linkSentVia", ""),
            "watching": bool(dispute.get("screenAttached")), "transactionId": dispute.get("transactionId", ""),
            "canSubmit": service().can_customer_submit(dispute),
            "alreadyDisputedAs": (service().standing_elsewhere(dispute) or {}).get("disputeId", "")
                                 if dispute["status"] == model.DRAFT else ""}


def list_disputes(customer_id: str) -> list[dict]:
    """The customer's disputes, newest first."""
    svc = service()
    index = svc.store.get(f"cust#{customer_id}") or {}
    found = []
    for dispute_id in reversed(index.get("disputeIds") or []):
        dispute = svc.store.get(f"dispute#{dispute_id}")
        if dispute and dispute.get("customerId") == customer_id:
            found.append(_summary(dispute))
        if len(found) >= SHOWN:
            break
    return found


def _as_time(text: str) -> float:
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return 0.0


def live(customer_id: str, began_at: float) -> dict:
    """The customer's open dispute, and whether its form was sent since the conversation began (began_at, epoch)."""
    open_ones = [d for d in list_disputes(customer_id) if d["open"]]
    if not open_ones:
        return {"dispute": None, "formSent": False}
    dispute = open_ones[0]
    # The service stamps whole seconds: allow for the second the conversation began in.
    sent = bool(dispute["formSentAt"]) and _as_time(dispute["formSentAt"]) >= began_at - 1
    return {"dispute": dispute, "formSent": sent and dispute["status"] == model.DRAFT}


def submit(customer_id: str, dispute_id: str) -> dict:
    """The customer submits their own dispute from the list: only theirs, only a complete draft (service rule R11)."""
    return _summary(service().customer_submit(customer_id, dispute_id, "app"))


def open_live(customer_id: str, contact_id: str, dispute_id: str) -> dict:
    """The dispute's form, joined to this conversation: {sessionId} for the form page's own calls."""
    svc = service()
    link = svc.mint_form_link(customer_id, contact_id, dispute_id)      # refuses another customer's dispute
    return svc.open_form_link(link.rsplit("#k=", 1)[-1])
