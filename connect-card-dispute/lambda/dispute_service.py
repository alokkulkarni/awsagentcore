"""
dispute_service.py
==================
Everything that can be done to a card dispute, and the rules that decide whether
it may be done (SPEC.md section 4, rules R1 to R6).

The three ways into the Lambda (tools, web pages, the screen pop) all end up
here, so a rule enforced here holds whoever is asking.

Nothing in this file logs or returns a code, a page secret or an adviser token
except to the one caller entitled to it.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Callable

import dispute_model as model
from dispute_store import ABSENT

CODE_SECONDS = 10 * 60              # a page's code, before a contact attaches to it
SCREEN_SECONDS = 2 * 60 * 60        # an attached customer page
ADVISER_LINK_SECONDS = 60 * 60
MAX_WRONG_CODES = 5
HISTORY_KEPT = 60
_ID_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"     # no 0/O or 1/I to misread

FORM_LINK_SECONDS = 2 * 60 * 60     # a form link texted to the customer
MAX_LINK_OPENS = 5                  # the customer may open it again, or on another device
MAX_LINKS_PER_DISPUTE = 3
CARD_ACTIONS_KEPT = 20
CARD_ACTION_SHOWN_SECONDS = 4 * 60 * 60     # "on this call", near enough, for the screen pop
REPLACEMENT_WORKING_DAYS = "3 to 5"
NOTE_MAX_CHARS = 300
CARD_ACTIONS = {"blocked": "BLOCK", "replacement_ordered": "REPL"}
ESCALATION_REASONS = ("dispute_ready_for_review", "dispute_incomplete", "customer_request", "vulnerability",
                      "tool_failure", "other")

# What the CX designer agent gets back for a dispute. Every key, always: the CX
# designer rejects a reply that lacks a field its sample had.
ASSISTANT_DISPUTE = {"ok": False, "reason": "", "message": "", "disputeId": "", "status": "", "payment": "",
                     "disputeType": "", "reasonCode": "", "reasonsAllowed": "", "cardInPossession": "",
                     "cardBlocked": "", "contactedMerchant": "", "narrative": "", "missing": "", "complete": False,
                     "customerWatching": False, "linkSent": False}


_LINK_WORDS = {"text": "texted to the customer", "chat": "posted in the chat"}
PAYMENTS_PER_PAGE = 5


def _is_date(text: str) -> bool:
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return len(text) == 10
    except (TypeError, ValueError):
        return False


def _day_words(date: str) -> str:
    """'2026-10-11' -> '11 Oct 2026'."""
    return datetime.strptime(date, "%Y-%m-%d").strftime("%-d %b %Y")


def clean_note(text: str) -> str:
    """
    Text an AI wrote, made safe to show in the screen pop: one line, no markdown
    or HTML control characters (so it cannot add links or formatting), capped.
    """
    if not isinstance(text, str):
        return ""
    kept = "".join(" " if ch in "[]()<>*_`#|\\{}" or not ch.isprintable() else ch for ch in text)
    return " ".join(kept.split())[:NOTE_MAX_CHARS]


class DisputeError(Exception):
    """A request that was understood and refused. `code` is safe to show and to log."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


class DisputeService:
    def __init__(self, store, clock: Callable[[], float], page_url: str = "", merchant_topic: str = ""):
        self.store, self.clock = store, clock
        self.page_url = page_url.rstrip("/")
        self.merchant_topic = merchant_topic

    # ── helpers ────────────────────────────────────────────────────────────────

    def _now_text(self) -> str:
        return datetime.fromtimestamp(self.clock(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _owned(self, customer_id: str, dispute_id: str) -> dict:
        """The dispute, only if it belongs to this customer (rule R4)."""
        dispute = self.store.get(f"dispute#{dispute_id}") if dispute_id else None
        if not dispute or not customer_id or dispute["customerId"] != customer_id:
            raise DisputeError("dispute_not_found", "No dispute with that reference for this customer.", 404)
        return dispute

    def _change(self, dispute_id: str, who: str, action: str, mutate: Callable[[dict], list[str]]) -> dict:
        """Load, change and save a dispute, retrying if someone else changed it in between."""
        for _ in range(4):
            dispute = self.store.get(f"dispute#{dispute_id}")
            if not dispute:
                raise DisputeError("dispute_not_found", "No dispute with that reference.", 404)
            seen = int(dispute["version"])
            changed = mutate(dispute)
            if not changed:
                return dispute
            dispute["version"] = seen + 1
            dispute["updatedAt"] = self._now_text()
            dispute["history"] = (dispute.get("history") or [])[-(HISTORY_KEPT - 1):] + [
                {"at": dispute["updatedAt"], "by": who, "action": action, "fields": changed}]
            if self.store.put(f"dispute#{dispute_id}", dispute, expect=seen):
                return dispute
        raise DisputeError("busy", "The dispute is being changed by someone else. Try again.", 409)

    def _apply(self, dispute: dict, fields: dict, who: str) -> list[str]:
        changed = [name for name, value in fields.items() if dispute.get(name) != value]
        for name in changed:
            dispute[name] = fields[name]
            dispute.setdefault("filledBy", {})[name] = who
        if any(name in model.CONFIRMATION_SENSITIVE for name in changed) and dispute.get("customerConfirmation"):
            dispute["customerConfirmation"] = None            # rule R6
            changed.append("customerConfirmation")
        return changed

    def _handover(self, dispute: dict) -> dict:
        """What ARIA should pass to its Escalate tool for this dispute."""
        if dispute.get("disputeType") == model.MERCHANT:
            topic = self.merchant_topic or f"{dispute['cardType']}_card"
        else:
            topic = "fraud_security"
        return {"topicCategory": topic,
                "customerIntent": "Dispute a card transaction",
                "summaryStartsWith": f"Card dispute {dispute['disputeId']} drafted."}

    def _reply(self, dispute: dict) -> dict:
        shown = model.view(dispute)
        return {"dispute_id": dispute["disputeId"], "status": dispute["status"], "dispute": shown,
                "missing": shown["missing"], "handover": self._handover(dispute),
                "customer_page": self.page_url, "customer_is_watching": bool(dispute.get("screenAttached")),
                "card_actions": [{key: a[key] for key in ("action", "cardType", "cardLastFour", "reference", "at")}
                                 for a in self._recent_card_actions(dispute["customerId"])],
                "assistant_note": dispute.get("assistantNote", "")}

    def _latest_open(self, customer_id: str) -> dict | None:
        index = self.store.get(f"cust#{customer_id}") or {}
        for dispute_id in reversed(index.get("disputeIds") or []):
            dispute = self.store.get(f"dispute#{dispute_id}")
            if dispute and dispute["status"] in model.OPEN_STATUSES:
                return dispute
        return None

    # ── tools (ARIA and the agent-assist agents) ───────────────────────────────

    def list_card_transactions(self, customer_id: str, card_type: str = "") -> dict:
        transactions = model.card_transactions(customer_id, card_type if card_type in ("debit", "credit") else "")
        if not transactions:
            raise DisputeError("no_transactions", "No card transactions found for this customer.", 404)
        return {"transactions": transactions}

    def _transaction_fields(self, customer_id: str, transaction_id: str) -> dict:
        """The transaction's details from the bank's own record, never from a caller (rule R5)."""
        transaction = model.find_transaction(customer_id, transaction_id)
        if not transaction:
            raise DisputeError("transaction_not_found", "That transaction is not on this customer's cards. "
                               "Use a transaction_id from list_card_transactions.", 404)
        return {"cardType": transaction["card_type"], "cardLastFour": transaction["card_last_four"],
                "transactionId": transaction["transaction_id"], "transactionDate": transaction["date"],
                "merchant": transaction["merchant"], "amount": transaction["amount"],
                "currency": transaction["currency"]}

    def _create(self, customer_id: str, transaction_id: str, who: str, fields: dict) -> dict:
        """A new draft for one transaction, or the customer's existing draft for it."""
        details = self._transaction_fields(customer_id, transaction_id)
        index = self.store.get(f"cust#{customer_id}") or {"version": 0, "disputeIds": []}
        for dispute_id in index["disputeIds"]:
            existing = self.store.get(f"dispute#{dispute_id}")
            if existing and existing["status"] == model.DRAFT and existing["transactionId"] == transaction_id:
                return existing
        blocked = {a["cardLastFour"] for a in index.get("cardActions") or [] if a["action"] == "blocked"}
        if details["cardLastFour"] in blocked and "cardBlocked" not in fields:
            fields = {**fields, "cardBlocked": "yes"}            # blocked earlier in the call, before the dispute
        dispute_id = "DSP-" + "".join(secrets.choice(_ID_ALPHABET) for _ in range(8))
        now = self._now_text()
        dispute = {
            "disputeId": dispute_id, "customerId": customer_id, "status": model.DRAFT, "version": 1,
            "createdAt": now, "updatedAt": now, **details, **fields,
            "filledBy": {"transaction": who, **{name: who for name in fields}},
            "history": [{"at": now, "by": who, "action": "started", "fields": ["transaction", *fields]}],
        }
        if not self.store.put(f"dispute#{dispute_id}", dispute, expect=ABSENT):
            raise DisputeError("busy", "Could not create the dispute. Try again.", 409)
        seen = int(index["version"])
        index = {**index, "version": seen + 1, "disputeIds": index["disputeIds"][-19:] + [dispute_id]}   # keeps cardActions
        self.store.put(f"cust#{customer_id}", index, expect=seen if seen else None)
        return dispute

    def start_card_dispute(self, customer_id: str, transaction_id: str, dispute_type: str) -> dict:
        fields = model.check_fields({"disputeType": dispute_type})
        return self._reply(self._create(customer_id, transaction_id, "aria", fields))

    def update_card_dispute(self, customer_id: str, dispute_id: str, fields: dict) -> dict:
        self._owned(customer_id, dispute_id)
        clean = model.check_fields(fields)

        def mutate(dispute: dict) -> list[str]:
            if dispute["status"] != model.DRAFT:                                    # rule R1
                raise DisputeError("with_adviser", "An adviser now has this dispute. It can no longer be "
                                   "changed by the assistant.", 409)
            return self._apply(dispute, clean, "aria")
        return self._reply(self._change(dispute_id, "aria", "updated", mutate))

    def get_card_dispute(self, customer_id: str, dispute_id: str = "") -> dict:
        dispute = self._owned(customer_id, dispute_id) if dispute_id else self._latest_open(customer_id)
        if not dispute:
            raise DisputeError("dispute_not_found", "This customer has no open card dispute.", 404)
        return self._reply(dispute)

    def attach_dispute_screen(self, customer_id: str, dispute_id: str, code: str) -> dict:
        dispute = self._owned(customer_id, dispute_id)
        if int(dispute.get("wrongCodes", 0)) >= MAX_WRONG_CODES:
            raise DisputeError("code_locked", "Too many wrong codes. The page cannot be attached to this dispute.", 429)
        digits = "".join(ch for ch in str(code) if ch.isdigit())
        waiting = self.store.get(f"code#{digits}") if len(digits) == 6 else None
        screen = self.store.get(waiting["screen"]) if waiting else None
        if not screen or screen.get("disputeId") or screen.get("contactId"):
            def count(d: dict) -> list[str]:
                d["wrongCodes"] = int(d.get("wrongCodes", 0)) + 1
                return ["wrongCodes"]
            self._change(dispute_id, "aria", "wrong_code", count)
            raise DisputeError("code_not_recognised", "That code is not showing on a waiting page. Ask the customer "
                               "to read the code on their screen again; it changes after ten minutes.", 404)
        seen = int(screen["version"])
        claimed = {**screen, "version": seen + 1, "disputeId": dispute_id, "expiresAt": self.clock() + SCREEN_SECONDS}
        if not self.store.put(waiting["screen"], claimed, expect=seen):
            raise DisputeError("code_not_recognised", "That code has just been used. Ask for a new one.", 409)
        self.store.put(f"code#{digits}", {"screen": "", "expiresAt": self.clock()})     # single use

        def mark(d: dict) -> list[str]:
            d["screenAttached"] = True
            return ["screenAttached"]
        self._change(dispute_id, "aria", "screen_attached", mark)
        return {"attached": True, "dispute_id": dispute_id}

    # ── the Live Sync route: a contact attaches to a page, and the page saves the form ──

    def attach_contact_screen(self, contact_id: str, customer_id: str, code: str) -> dict:
        """
        Attach a phone contact to the page showing `code` (SPEC section 15, rule R7).
        `customer_id` is what Connect says about that contact, looked up by the
        caller of this method; it never comes from the agent or the customer.
        Always answers with the same fields, because the CX designer rejects a
        reply that lacks one.
        """
        reply = {"attached": False, "locked": False, "reason": ""}
        if not contact_id or not customer_id:
            return {**reply, "reason": "customer_not_identified"}
        wrong_key = f"wrong#{contact_id}"
        wrong = self.store.get(wrong_key) or {"count": 0}
        if int(wrong["count"]) >= MAX_WRONG_CODES:
            return {**reply, "locked": True, "reason": "too_many_wrong_codes"}
        digits = "".join(ch for ch in str(code) if ch.isdigit())
        waiting = self.store.get(f"code#{digits}") if len(digits) == 6 else None
        if waiting and waiting.get("usedBy") == contact_id:
            return {**reply, "attached": True}                    # the same call asking again
        screen = self.store.get(waiting["screen"]) if waiting and waiting.get("screen") else None
        if not screen or screen.get("disputeId") or screen.get("contactId"):
            count = int(wrong["count"]) + 1
            self.store.put(wrong_key, {"count": count, "expiresAt": self.clock() + 24 * 60 * 60})
            return {**reply, "locked": count >= MAX_WRONG_CODES, "reason": "code_not_recognised"}
        seen = int(screen["version"])
        claimed = {**screen, "version": seen + 1, "contactId": contact_id, "customerId": customer_id,
                   "expiresAt": self.clock() + SCREEN_SECONDS}
        if not self.store.put(waiting["screen"], claimed, expect=seen):
            return {**reply, "reason": "code_not_recognised"}
        self.store.put(f"code#{digits}", {"screen": "", "usedBy": contact_id, "expiresAt": waiting["expiresAt"]})
        return {**reply, "attached": True}

    def page_save(self, session_id: str, fields: dict) -> dict:
        """
        Save the form as it stands on the customer's page (rules R8 to R10). The
        first save that names a transaction creates the dispute. Empty values
        are "not answered yet" and are skipped.
        """
        key = f"screen#{_hash(session_id)}" if session_id else ""
        screen = self.store.get(key) if key else None
        if not screen or not screen.get("contactId"):
            raise DisputeError("not_attached", "This page is not attached to a call.", 403)       # R8
        if not isinstance(fields, dict):
            raise DisputeError("bad_request", "The request was not understood.", 400)
        answered = {name: value for name, value in fields.items() if value not in ("", None)}
        transaction_id = answered.pop("transactionId", "")
        if not isinstance(transaction_id, str):
            raise ValueError("transactionId must be text")
        clean = model.check_fields(answered)                                                        # R9
        customer_id = screen["customerId"]

        dispute = self.store.get(f"dispute#{screen['disputeId']}") if screen.get("disputeId") else None
        if not dispute:
            if not transaction_id:
                return self.screen_status(session_id)             # nothing to keep until a payment is chosen
            dispute = self._create(customer_id, transaction_id, "page", clean)
            self.store.put(key, {**screen, "version": int(screen["version"]) + 1, "disputeId": dispute["disputeId"]},
                           expect=int(screen["version"]))
        details = self._transaction_fields(customer_id, transaction_id) if transaction_id else {}

        def mutate(d: dict) -> list[str]:
            if d["status"] != model.DRAFT:                                                          # R8
                raise DisputeError("with_adviser", "An adviser now has this dispute. They will make any changes.", 409)
            changed = self._apply(d, clean, "page")                                                 # R10
            if details and d["transactionId"] != details["transactionId"]:
                d.update(details)
                d.setdefault("filledBy", {})["transaction"] = "page"
                changed.append("transaction")
                if d.get("customerConfirmation"):
                    d["customerConfirmation"] = None
            if not d.get("screenAttached"):
                d["screenAttached"] = True
                changed.append("screenAttached")
            return changed
        self._change(dispute["disputeId"], "page", "saved", mutate)
        return self.screen_status(session_id)

    # ── the CX designer disputes agent (SPEC Part 4) ───────────────────────────
    # Called through the CX designer door. `customer_id` is always what Connect
    # holds for the call (rule R7), worked out by the caller of these methods.

    def _card_actions(self, customer_id: str) -> list[dict]:
        return list((self.store.get(f"cust#{customer_id}") or {}).get("cardActions") or [])

    def _recent_card_actions(self, customer_id: str) -> list[dict]:
        since = self.clock() - CARD_ACTION_SHOWN_SECONDS
        return [a for a in self._card_actions(customer_id) if float(a["epoch"]) >= since]

    def _note_card_action(self, customer_id: str, action: dict) -> None:
        key = f"cust#{customer_id}"
        for _ in range(4):
            index = self.store.get(key) or {"version": 0, "disputeIds": []}
            seen = int(index["version"])
            kept = (index.get("cardActions") or [])[-(CARD_ACTIONS_KEPT - 1):] + [action]
            if self.store.put(key, {**index, "version": seen + 1, "cardActions": kept}, expect=seen if seen else ABSENT):
                return
        raise DisputeError("busy", "Could not record that. Try again.", 409)

    def _assistant_reply(self, dispute: dict) -> dict:
        shown = model.view(dispute)
        return {**ASSISTANT_DISPUTE, "ok": True,
                "disputeId": shown["disputeId"], "status": shown["status"], "payment": model.payment_words(dispute),
                "disputeType": shown["disputeType"], "reasonCode": shown["reason"],
                "reasonsAllowed": ", ".join(model.REASONS.get(shown["disputeType"], {})) or "set disputeType first",
                "cardInPossession": shown["cardInPossession"], "cardBlocked": shown["cardBlocked"],
                "contactedMerchant": shown["contactedMerchant"], "narrative": shown["narrative"],
                "missing": ", ".join(shown["missing"]) or "nothing", "complete": not shown["missing"],
                "customerWatching": bool(dispute.get("screenAttached")), "linkSent": bool(dispute.get("linkSentAt"))}

    def assistant_cards_and_payments(self, customer_id: str, page=1, from_date: str = "", to_date: str = "",
                                     card_type: str = "") -> dict:
        """
        The customer's cards, and one page of their card payments, newest first.
        Customers rarely remember the exact shop or amount, so the assistant shows
        these and lets them choose. Each payment has a number that runs across the
        pages, so "number 7" means the same payment on any page.
        """
        blocked = {a["cardLastFour"] for a in self._card_actions(customer_id) if a["action"] == "blocked"}
        cards = [{"cardType": c["card_type"], "cardLastFour": c["card_last_four"],
                  "status": "blocked" if c["card_last_four"] in blocked else "active"}
                 for c in model.customer_cards(customer_id)]
        if not cards:
            raise DisputeError("no_cards", "This customer has no cards with us.", 404)
        for name, value in (("fromDate", from_date), ("toDate", to_date)):
            if value and not _is_date(value):
                raise ValueError(f"{name} must be a date written YYYY-MM-DD, for example 2026-10-01")
        if card_type and card_type not in ("debit", "credit"):
            raise ValueError("cardType must be debit or credit, or empty for both")
        try:
            page = max(1, int(page or 1))
        except (TypeError, ValueError):
            raise ValueError("page must be a whole number, starting at 1")
        chosen = [t for t in model.card_transactions(customer_id, card_type)
                  if (not from_date or t["date"] >= from_date) and (not to_date or t["date"] <= to_date)]
        pages = max(1, -(-len(chosen) // PAYMENTS_PER_PAGE))
        first = (page - 1) * PAYMENTS_PER_PAGE
        payments = [{"number": first + i + 1, "transactionId": t["transaction_id"], "date": t["date"],
                     "merchant": t["merchant"], "amount": t["amount"], "cardType": t["card_type"],
                     "cardLastFour": t["card_last_four"],
                     "label": f"{_day_words(t['date'])}, {t['merchant']}, £{t['amount']}, "
                              f"{t['card_type']} card ending {t['card_last_four']}"}
                    for i, t in enumerate(chosen[first:first + PAYMENTS_PER_PAGE])]
        message = "" if payments else ("No payments in that period." if chosen == [] else "No more payments.")
        return {"today": datetime.fromtimestamp(self.clock(), timezone.utc).strftime("%Y-%m-%d"),
                "cards": cards, "payments": payments, "page": page, "totalPages": pages,
                "totalPayments": len(chosen), "hasMore": page < pages, "message": message}

    def assistant_start(self, customer_id: str, transaction_id: str, dispute_type: str) -> dict:
        fields = model.check_fields({"disputeType": dispute_type}) if dispute_type else {}
        return self._assistant_reply(self._create(customer_id, transaction_id, "assistant", fields))

    def assistant_update(self, customer_id: str, dispute_id: str, fields: dict) -> dict:
        self._owned(customer_id, dispute_id)
        clean = model.check_fields({name: value for name, value in fields.items() if value not in ("", None)})

        def mutate(dispute: dict) -> list[str]:
            if dispute["status"] != model.DRAFT:                                    # rule R1
                raise DisputeError("with_adviser", "An adviser now has this dispute. They will make any changes.", 409)
            return self._apply(dispute, clean, "assistant")
        return self._assistant_reply(self._change(dispute_id, "assistant", "updated", mutate))

    def assistant_get(self, customer_id: str, dispute_id: str = "") -> dict:
        dispute = self._owned(customer_id, dispute_id) if dispute_id else self._latest_open(customer_id)
        if not dispute:
            raise DisputeError("dispute_not_found", "This customer has no open card dispute.", 404)
        return self._assistant_reply(dispute)

    def card_action(self, customer_id: str, card_type: str, action: str) -> dict:
        """
        Block a card, or order its replacement. Only the customer's own card, from
        the bank's record. Asking twice gives the same reference, so a repeated
        tool call never blocks or orders twice. A replacement needs the card blocked.

        These cards are test data; a real deployment calls the card system here.
        """
        card = next((c for c in model.customer_cards(customer_id) if c["card_type"] == card_type), None)
        if not card:
            raise DisputeError("card_not_found", "The customer has no card of that type. Use cardType debit or credit.", 404)
        last_four = card["card_last_four"]
        done = {a["action"] for a in self._card_actions(customer_id) if a["cardLastFour"] == last_four}
        earlier = next((a for a in reversed(self._card_actions(customer_id))
                        if a["cardLastFour"] == last_four and a["action"] == action), None)
        if earlier:
            return earlier
        if action == "replacement_ordered" and "blocked" not in done:
            raise DisputeError("card_not_blocked", "Block the card first. A replacement is only sent for a blocked card.", 409)
        entry = {"action": action, "cardType": card_type, "cardLastFour": last_four,
                 "reference": f"{CARD_ACTIONS[action]}-{last_four}-" + "".join(secrets.choice(_ID_ALPHABET) for _ in range(6)),
                 "at": self._now_text(), "epoch": int(self.clock())}
        self._note_card_action(customer_id, entry)
        if action == "blocked":
            # An open draft about a payment on this card now says the card is blocked.
            for dispute_id in (self.store.get(f"cust#{customer_id}") or {}).get("disputeIds") or []:
                dispute = self.store.get(f"dispute#{dispute_id}")
                if dispute and dispute["status"] == model.DRAFT and dispute.get("cardLastFour") == last_four:
                    self._change(dispute_id, "assistant", "card_blocked",
                                 lambda d: self._apply(d, {"cardBlocked": "yes"}, "assistant"))
        return entry

    def mint_form_link(self, customer_id: str, contact_id: str, dispute_id: str) -> str:
        """
        A link that opens this dispute's form on the customer's own phone, already
        joined to their call, with no code to read out. The secret goes after "#",
        so it never reaches a server log. Works for two hours, a few opens.
        """
        dispute = self._owned(customer_id, dispute_id)
        if dispute["status"] != model.DRAFT:
            raise DisputeError("with_adviser", "An adviser now has this dispute.", 409)
        if int(dispute.get("linksSent", 0)) >= MAX_LINKS_PER_DISPUTE:
            raise DisputeError("too_many_links", "The form link has already been sent the most times allowed.", 429)

        def count(d: dict) -> list[str]:
            d["linksSent"] = int(d.get("linksSent", 0)) + 1
            return ["linksSent"]
        self._change(dispute_id, "assistant", "link_issued", count)
        token = secrets.token_urlsafe(32)
        self.store.put(f"link#{_hash(token)}", {"version": 1, "opens": 0, "contactId": contact_id,
                                                "customerId": customer_id, "disputeId": dispute_id,
                                                "expiresAt": self.clock() + FORM_LINK_SECONDS})
        return f"{self.page_url}/#k={token}"

    def mark_link_sent(self, dispute_id: str, via: str = "text") -> None:
        """via: "text" (an SMS on a call) or "chat" (posted in the chat)."""
        def mark(d: dict) -> list[str]:
            d["linkSentAt"], d["linkSentVia"] = self._now_text(), via
            return ["linkSentAt", "linkSentVia"]
        self._change(dispute_id, "assistant", "link_sent", mark)

    def open_form_link(self, token: str) -> dict:
        """The customer opened the texted link: a new page session, joined to the call and the dispute."""
        key = f"link#{_hash(token)}" if token else ""
        link = self.store.get(key) if key else None
        if not link:
            raise DisputeError("link_expired", "This link has expired. Ask the person on the phone to send a new one.", 403)
        if int(link["opens"]) >= MAX_LINK_OPENS:
            raise DisputeError("link_used_up", "This link has been opened too many times. Ask for a new one.", 403)
        seen = int(link["version"])
        if not self.store.put(key, {**link, "version": seen + 1, "opens": int(link["opens"]) + 1}, expect=seen):
            raise DisputeError("busy", "Try again.", 409)
        session_id = secrets.token_urlsafe(32)
        self.store.put(f"screen#{_hash(session_id)}", {
            "version": 1, "code": "", "disputeId": link["disputeId"], "contactId": link["contactId"],
            "customerId": link["customerId"], "expiresAt": self.clock() + SCREEN_SECONDS})

        def mark(d: dict) -> list[str]:
            if d.get("screenAttached"):
                return []
            d["screenAttached"] = True
            return ["screenAttached"]
        self._change(link["disputeId"], "customer", "link_opened", mark)
        return {"sessionId": session_id}

    def handover(self, customer_id: str, note: str = "", reason: str = "") -> dict:
        """
        What the Connect flow passes to ARIA's human hand-over when the disputes
        agent finishes. Built from the record, not from what the agent remembers,
        so the routing and the adviser's summary are always right. Flat text only:
        Connect's Lambda block reads a string map.
        """
        note = clean_note(note)
        dispute = self._latest_open(customer_id) if customer_id else None
        actions = self._recent_card_actions(customer_id) if customer_id else []
        done = [f"{a['cardType'].capitalize()} card ending {a['cardLastFour']} "
                f"{'blocked' if a['action'] == 'blocked' else 'replacement ordered'} ({a['reference']})." for a in actions]
        if dispute and note:
            def keep(d: dict) -> list[str]:
                if d.get("assistantNote") == note:
                    return []
                d["assistantNote"] = note
                return ["assistantNote"]
            dispute = self._change(dispute["disputeId"], "assistant", "handed_over", keep)
        if not dispute:
            summary = " ".join(["Card dispute not drafted.", *done, f"Assistant's note: {note}" if note else ""])
            return {"hasDispute": "false", "disputeId": "none", "topicCategory": "fraud_security",
                    "customerIntent": "Dispute a card transaction",
                    "escalationReason": reason if reason in ESCALATION_REASONS else "dispute_incomplete",
                    "conversationSummary": summary.strip()}
        shown = model.view(dispute)
        if dispute.get("screenAttached"):
            screen = "Customer is viewing the form."
        elif dispute.get("linkSentAt"):
            screen = f"Form link {_LINK_WORDS[dispute.get('linkSentVia', 'text')]}; the customer has not opened it."
        else:
            screen = "Customer is not viewing the form."
        kind = f"{shown['disputeTypeWords']}" + (f" ({shown['reasonWords']})" if shown["reasonWords"] else "")
        summary = " ".join(part for part in [
            f"Card dispute {shown['disputeId']} drafted by the phone assistant.",
            f"{model.payment_words(dispute)}; {kind or 'type not given'}.",
            ("Still needed: " + ", ".join(shown["missing"]) + ".") if shown["missing"] else "All details filled in.",
            *done, screen,
            f"Assistant's note: {note}" if note else "",
            "Confirm the details with the customer before you submit."] if part)
        default = "dispute_incomplete" if shown["missing"] else "dispute_ready_for_review"
        return {"hasDispute": "true", "disputeId": shown["disputeId"],
                "topicCategory": self._handover(dispute)["topicCategory"],
                "customerIntent": "Dispute a card transaction",
                "escalationReason": reason if reason in ESCALATION_REASONS else default,
                "conversationSummary": summary}

    # ── the customer page ──────────────────────────────────────────────────────

    def create_screen(self) -> dict:
        session_id = secrets.token_urlsafe(32)
        key = f"screen#{_hash(session_id)}"
        expires = self.clock() + CODE_SECONDS
        for _ in range(20):
            code = f"{secrets.randbelow(1_000_000):06d}"
            if self.store.put(f"code#{code}", {"screen": key, "expiresAt": expires}, expect=ABSENT):
                self.store.put(key, {"version": 1, "code": code, "disputeId": "", "expiresAt": expires})
                return {"sessionId": session_id, "code": code, "expiresInSeconds": CODE_SECONDS}
        raise DisputeError("busy", "Could not issue a code. Try again.", 503)

    def _screen_dispute(self, session_id: str) -> tuple[dict | None, dict | None]:
        screen = self.store.get(f"screen#{_hash(session_id)}") if session_id else None
        dispute = self.store.get(f"dispute#{screen['disputeId']}") if screen and screen.get("disputeId") else None
        return screen, dispute

    def screen_status(self, session_id: str) -> dict:
        screen, dispute = self._screen_dispute(session_id)
        if not screen:
            return {"state": "expired"}
        form = {}
        if screen.get("contactId"):
            # The Live Sync route: the page is a form. It needs the contact to bind
            # Live Sync to, and the customer's own transactions to choose from.
            form = {"contactId": screen["contactId"],
                    "transactions": model.card_transactions(screen["customerId"]),
                    "choices": {"disputeType": model.TYPE_WORDS, "reason": model.REASONS,
                                "narrativeMaxChars": model.NARRATIVE_MAX_CHARS},
                    "editable": not dispute or dispute["status"] == model.DRAFT}
        if not dispute:
            if form:
                return {"state": "form", "dispute": None, "canConfirm": False, **form}
            return {"state": "waiting", "code": screen["code"],
                    "expiresInSeconds": max(0, int(screen["expiresAt"] - self.clock()))}
        shown = model.view(dispute)
        can_confirm = dispute["status"] == model.WITH_ADVISER and not shown["missing"] and not shown["customerConfirmed"]
        return {"state": "form" if form else "attached", "dispute": shown, "canConfirm": can_confirm, **form}

    def customer_confirm(self, session_id: str) -> dict:
        _, dispute = self._screen_dispute(session_id)
        if not dispute:
            raise DisputeError("not_attached", "This page is not showing a dispute.", 403)

        def mutate(d: dict) -> list[str]:
            if d["status"] != model.WITH_ADVISER or model.missing(d):
                raise DisputeError("not_ready", "The adviser has not finished the form yet.", 409)
            d["customerConfirmation"] = {"accepted": True, "source": "customer_click", "at": self._now_text()}
            return ["customerConfirmation"]
        self._change(dispute["disputeId"], "customer", "confirmed", mutate)
        return self.screen_status(session_id)

    # ── the adviser page ───────────────────────────────────────────────────────

    def mint_adviser_link(self, dispute_id: str) -> str:
        token = secrets.token_urlsafe(32)
        self.store.put(f"adv#{_hash(token)}", {"disputeId": dispute_id, "expiresAt": self.clock() + ADVISER_LINK_SECONDS})
        # The token goes after "#", which browsers never send to a server or put in a Referer.
        return f"{self.page_url}/adviser#{token}"

    def _adviser_dispute_id(self, token: str) -> str:
        grant = self.store.get(f"adv#{_hash(token)}") if token else None
        if not grant:
            raise DisputeError("link_expired", "This link has expired. Open the dispute from the contact again.", 403)
        return grant["disputeId"]

    def _adviser_reply(self, dispute: dict) -> dict:
        return {"dispute": model.view(dispute), "customerIsWatching": bool(dispute.get("screenAttached")),
                "choices": {"disputeType": model.TYPE_WORDS, "reason": model.REASONS,
                            "narrativeMaxChars": model.NARRATIVE_MAX_CHARS},
                "history": [{"at": h["at"], "by": h["by"], "action": h["action"]} for h in dispute.get("history", [])][-12:]}

    def adviser_open(self, token: str) -> dict:
        def mutate(d: dict) -> list[str]:
            if d["status"] != model.DRAFT:
                return []
            d["status"] = model.WITH_ADVISER
            return ["status"]
        return self._adviser_reply(self._change(self._adviser_dispute_id(token), "adviser", "opened", mutate))

    def adviser_update(self, token: str, fields: dict) -> dict:
        clean = model.check_fields(fields)

        def mutate(d: dict) -> list[str]:
            if d["status"] not in model.OPEN_STATUSES:
                raise DisputeError("closed", "This dispute has been submitted and can no longer be changed.", 409)
            return self._apply(d, clean, "adviser")
        return self._adviser_reply(self._change(self._adviser_dispute_id(token), "adviser", "updated", mutate))

    def adviser_record_confirmation(self, token: str, accepted: bool) -> dict:
        def mutate(d: dict) -> list[str]:
            if d["status"] not in model.OPEN_STATUSES:
                raise DisputeError("closed", "This dispute has been submitted and can no longer be changed.", 409)
            current = d.get("customerConfirmation") or {}
            if accepted and model.missing(d):
                raise DisputeError("not_ready", "Fill in everything before recording the customer's confirmation.", 409)
            if accepted and not current.get("accepted"):
                d["customerConfirmation"] = {"accepted": True, "source": "adviser_recorded", "at": self._now_text()}
            elif not accepted and current.get("source") == "adviser_recorded":
                d["customerConfirmation"] = None      # the adviser can undo their own tick, never the customer's click
            else:
                return []
            return ["customerConfirmation"]
        return self._adviser_reply(self._change(self._adviser_dispute_id(token), "adviser", "confirmation", mutate))

    def adviser_submit(self, token: str) -> dict:
        def mutate(d: dict) -> list[str]:
            if d["status"] == model.SUBMITTED:
                return []
            gaps = model.missing(d)
            if gaps:
                raise DisputeError("incomplete", "Still needed: " + ", ".join(gaps) + ".", 409)
            if not (d.get("customerConfirmation") or {}).get("accepted"):                  # rule R3
                raise DisputeError("not_confirmed", "The customer has not confirmed these details yet.", 409)
            d["status"], d["submittedAt"] = model.SUBMITTED, self._now_text()
            return ["status"]
        return self._adviser_reply(self._change(self._adviser_dispute_id(token), "adviser", "submitted", mutate))

    # ── the screen pop (called by the agent-assist Lambda) ─────────────────────

    def screen_pop(self, customer_id: str) -> dict:
        """Lines for the adviser's screen pop, and a fresh link to the adviser page. All values are text."""
        dispute = self._latest_open(customer_id) if customer_id else None
        if not dispute:
            return {"hasDispute": "false"}
        shown = model.view(dispute)
        day = datetime.strptime(shown["transactionDate"], "%Y-%m-%d").strftime("%-d %b %Y")
        confirmed = "**Customer has confirmed** the details." if shown["customerConfirmed"] \
            else "Customer has **not yet confirmed** the details."
        if dispute.get("screenAttached"):
            screen = "Customer is **watching the form** on their own screen."
        elif dispute.get("linkSentAt"):
            screen = (f"Form link **{_LINK_WORDS[dispute.get('linkSentVia', 'text')]}**; **not opened yet**. "
                      "You review and submit it.")
        else:
            screen = "Customer is not viewing the form. **You review and submit it** after confirming with them."
        actions = [f"**{a['cardType'].capitalize()} card ending {a['cardLastFour']} "
                   f"{'blocked' if a['action'] == 'blocked' else 'replacement ordered'}** ({a['reference']})"
                   for a in self._recent_card_actions(customer_id)]
        note = dispute.get("assistantNote", "")
        return {
            "hasDispute": "true",
            "disputeId": shown["disputeId"],
            "disputeUrl": self.mint_adviser_link(shown["disputeId"]),
            "dispute1": f"**{shown['disputeId']}** · **{shown['disputeTypeWords']}** · {shown['statusWords']}",
            "dispute2": f"**{shown['merchant']}**, **£{shown['amount']}** on {day}, "
                        f"{shown['cardType']} card ending {shown['cardLastFour']}",
            "dispute3": ("**Still needed:** " + ", ".join(shown["missing"]) + ".") if shown["missing"]
                        else "**Form complete.** " + confirmed,
            "dispute4": screen,
            "dispute5": ("**Cards:** " + " · ".join(actions) + ".") if actions
                        else "**Cards:** none blocked or replaced on this call.",
            "dispute6": f"**Assistant's note:** {note}" if note else "**Assistant's note:** none.",
        }
