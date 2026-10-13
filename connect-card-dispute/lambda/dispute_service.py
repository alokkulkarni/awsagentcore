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
                "customer_page": self.page_url, "customer_is_watching": bool(dispute.get("screenAttached"))}

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
        index = {"version": seen + 1, "disputeIds": index["disputeIds"][-19:] + [dispute_id]}
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
        return {
            "hasDispute": "true",
            "disputeId": shown["disputeId"],
            "disputeUrl": self.mint_adviser_link(shown["disputeId"]),
            "dispute1": f"**{shown['disputeId']}** · **{shown['disputeTypeWords']}** · {shown['statusWords']}",
            "dispute2": f"**{shown['merchant']}**, **£{shown['amount']}** on {day}, "
                        f"{shown['cardType']} card ending {shown['cardLastFour']}",
            "dispute3": ("**Still needed:** " + ", ".join(shown["missing"]) + ".") if shown["missing"]
                        else "**Form complete.** " + confirmed,
            "dispute4": "Customer is **watching the form** on their own screen." if dispute.get("screenAttached")
                        else "Customer is not viewing the form. **You review and submit it** after confirming with them.",
        }
