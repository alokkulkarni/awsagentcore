"""
Unit tests for card transaction disputes.

Run from the repository root:
    python3 -m unittest discover -s connect-card-dispute/tests

They never call AWS: the store is the in-memory one, with a clock the tests move.
Each class covers one part of SPEC.md; rule numbers (R1..R6) are the spec's.
"""

import json
import re
import sys
import unittest
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FOLDER / "lambda"))

import aria_card_dispute as entry  # noqa: E402
import dispute_model as model  # noqa: E402
import dispute_web  # noqa: E402
from dispute_service import DisputeError, DisputeService  # noqa: E402
from dispute_store import ABSENT, DynamoStore, MemoryStore  # noqa: E402

JAMES, SARAH = "CUST-001", "CUST-002"
AMAZON = "TXN-4821-20261011-8999"          # James's debit card, AMAZON.CO.UK, £89.99


class Base(unittest.TestCase):
    def setUp(self):
        self.now = 1_800_000_000.0
        self.service = DisputeService(MemoryStore(lambda: self.now), lambda: self.now,
                                      page_url="https://pages.example")

    def draft(self, kind="unauthorised", customer=JAMES, transaction=AMAZON):
        return self.service.start_card_dispute(customer, transaction, kind)["dispute_id"]

    def complete(self, dispute_id):
        return self.service.update_card_dispute(JAMES, dispute_id, {
            "reason": "not_recognised", "cardInPossession": "yes", "narrative": "I did not buy this."})

    def adviser_token(self, dispute_id):
        return self.service.mint_adviser_link(dispute_id).split("#", 1)[1]

    def refused(self, code, call, *args):
        with self.assertRaises(DisputeError) as caught:
            call(*args)
        self.assertEqual(caught.exception.code, code)


class AriaDraftsADispute(Base):

    def test_transactions_have_stable_ids_and_can_be_filtered_by_card(self):
        everything = self.service.list_card_transactions(JAMES)["transactions"]
        self.assertEqual({t["card_type"] for t in everything}, {"debit", "credit"})
        self.assertIn(AMAZON, [t["transaction_id"] for t in everything])
        credit = self.service.list_card_transactions(JAMES, "credit")["transactions"]
        self.assertEqual({t["card_last_four"] for t in credit}, {"2291"})
        self.assertEqual(everything, self.service.list_card_transactions(JAMES)["transactions"])

    def test_starting_copies_the_transaction_from_the_banks_record(self):       # R5
        reply = self.service.start_card_dispute(JAMES, AMAZON, "unauthorised")
        dispute = reply["dispute"]
        self.assertRegex(reply["dispute_id"], r"^DSP-[A-Z2-9]{8}$")
        self.assertEqual((dispute["merchant"], dispute["amount"], dispute["cardLastFour"], dispute["status"]),
                         ("AMAZON.CO.UK", "89.99", "4821", "draft"))
        self.assertEqual(reply["missing"], ["Reason", "In the customer's words", "Customer still has the card"])

    def test_a_transaction_on_someone_elses_card_cannot_be_disputed(self):      # R5
        self.refused("transaction_not_found", self.service.start_card_dispute, SARAH, AMAZON, "unauthorised")

    def test_starting_twice_for_one_transaction_returns_the_same_draft(self):
        self.assertEqual(self.draft(), self.draft())

    def test_updates_fill_the_form_and_say_what_is_left(self):
        dispute_id = self.draft()
        reply = self.service.update_card_dispute(JAMES, dispute_id, {"reason": "card_details_used_without_card"})
        self.assertEqual(reply["dispute"]["reasonWords"], "Card details used without the card")
        self.assertEqual(self.complete(dispute_id)["missing"], [])
        self.assertEqual(reply["dispute"]["filledBy"]["reason"], "aria")

    def test_values_outside_the_fixed_lists_are_rejected_not_coerced(self):
        dispute_id = self.draft()
        for fields in ({"reason": "because"}, {"cardInPossession": "maybe"}, {"status": "submitted"},
                       {"customerConfirmation": "yes"}, {"narrative": 7}):
            with self.assertRaises(ValueError):
                self.service.update_card_dispute(JAMES, dispute_id, fields)

    def test_a_reason_that_does_not_fit_the_type_keeps_the_form_incomplete(self):
        dispute_id = self.draft("merchant")
        reply = self.service.update_card_dispute(JAMES, dispute_id, {
            "reason": "not_recognised", "contactedMerchant": "yes", "narrative": "x"})
        self.assertEqual(len(reply["missing"]), 1)
        self.assertIn("does not fit", reply["missing"][0])

    def test_another_customer_cannot_read_or_change_the_dispute(self):          # R4
        dispute_id = self.draft()
        self.refused("dispute_not_found", self.service.get_card_dispute, SARAH, dispute_id)
        self.refused("dispute_not_found", self.service.update_card_dispute, SARAH, dispute_id, {"narrative": "x"})
        self.refused("dispute_not_found", self.service.attach_dispute_screen, SARAH, dispute_id, "123456")

    def test_handover_route_depends_on_the_kind_of_dispute(self):
        fraud = self.service.start_card_dispute(JAMES, AMAZON, "unauthorised")
        self.assertEqual(fraud["handover"]["topicCategory"], "fraud_security")
        self.assertEqual(fraud["handover"]["summaryStartsWith"], f"Card dispute {fraud['dispute_id']} drafted.")
        credit = self.service.start_card_dispute(JAMES, "TXN-2291-20261004-61200", "merchant")
        self.assertEqual(credit["handover"]["topicCategory"], "credit_card")
        self.service.merchant_topic = "fraud_security"
        self.assertEqual(self.service.get_card_dispute(JAMES, credit["dispute_id"])["handover"]["topicCategory"],
                         "fraud_security")

    def test_latest_open_dispute_is_found_without_a_reference(self):
        dispute_id = self.draft()
        self.assertEqual(self.service.get_card_dispute(JAMES)["dispute_id"], dispute_id)
        self.refused("dispute_not_found", self.service.get_card_dispute, SARAH)


class AdviserReviewsAndSubmits(Base):

    def test_opening_moves_the_dispute_to_the_adviser_and_locks_aria_out(self):  # R1
        dispute_id = self.draft()
        token = self.adviser_token(dispute_id)
        self.assertEqual(self.service.adviser_open(token)["dispute"]["status"], "with_adviser")
        self.refused("with_adviser", self.service.update_card_dispute, JAMES, dispute_id, {"narrative": "changed"})

    def test_adviser_can_change_every_field(self):
        token = self.adviser_token(self.draft())
        reply = self.service.adviser_update(token, {"disputeType": "merchant", "reason": "charged_twice",
                                                    "contactedMerchant": "no", "narrative": "Charged twice."})
        self.assertEqual((reply["dispute"]["missing"], reply["dispute"]["filledBy"]["reason"]), ([], "adviser"))

    def test_submit_needs_a_complete_form_and_the_customers_confirmation(self):   # R3
        dispute_id = self.draft()
        token = self.adviser_token(dispute_id)
        self.service.adviser_open(token)
        self.refused("incomplete", self.service.adviser_submit, token)
        self.refused("not_ready", self.service.adviser_record_confirmation, token, True)
        self.service.adviser_update(token, {"reason": "not_recognised", "cardInPossession": "yes", "narrative": "No."})
        self.refused("not_confirmed", self.service.adviser_submit, token)
        self.service.adviser_record_confirmation(token, True)
        done = self.service.adviser_submit(token)["dispute"]
        self.assertEqual((done["status"], done["confirmationSource"]), ("submitted", "adviser_recorded"))
        self.refused("closed", self.service.adviser_update, token, {"narrative": "later"})

    def test_changing_what_was_confirmed_clears_the_confirmation(self):           # R6
        dispute_id = self.draft()
        self.complete(dispute_id)
        token = self.adviser_token(dispute_id)
        self.service.adviser_open(token)
        self.service.adviser_record_confirmation(token, True)
        self.assertTrue(self.service.adviser_update(token, {"narrative": "Reworded."})["dispute"]["customerConfirmed"])
        changed = self.service.adviser_update(token, {"reason": "card_lost_or_stolen"})["dispute"]
        self.assertFalse(changed["customerConfirmed"])
        self.refused("not_confirmed", self.service.adviser_submit, token)

    def test_adviser_can_untick_their_own_record_but_not_the_customers_click(self):
        dispute_id = self.draft()
        self.complete(dispute_id)
        token = self.adviser_token(dispute_id)
        self.service.adviser_open(token)
        self.service.adviser_record_confirmation(token, True)
        self.assertFalse(self.service.adviser_record_confirmation(token, False)["dispute"]["customerConfirmed"])
        session = self.service.create_screen()
        self.service.attach_dispute_screen(JAMES, dispute_id, session["code"])
        self.service.customer_confirm(session["sessionId"])
        self.assertTrue(self.service.adviser_record_confirmation(token, False)["dispute"]["customerConfirmed"])

    def test_adviser_link_expires_and_a_made_up_token_opens_nothing(self):
        token = self.adviser_token(self.draft())
        self.refused("link_expired", self.service.adviser_open, "not-a-token")
        self.refused("link_expired", self.service.adviser_open, "")
        self.now += 61 * 60
        self.refused("link_expired", self.service.adviser_open, token)

    def test_history_records_who_and_what_but_never_values(self):
        dispute_id = self.draft()
        self.service.update_card_dispute(JAMES, dispute_id, {"narrative": "SECRET-WORDS"})
        stored = self.service.store.get(f"dispute#{dispute_id}")
        self.assertEqual([h["action"] for h in stored["history"]], ["started", "updated"])
        self.assertNotIn("SECRET-WORDS", json.dumps(stored["history"]))


class CustomerWatchesTheForm(Base):

    def test_page_shows_nothing_until_a_contact_attaches_a_dispute(self):
        session = self.service.create_screen()
        self.assertRegex(session["code"], r"^\d{6}$")
        waiting = self.service.screen_status(session["sessionId"])
        self.assertEqual((waiting["state"], waiting["code"]), ("waiting", session["code"]))
        self.assertNotIn("dispute", waiting)
        self.assertEqual(self.service.screen_status("guessed-session")["state"], "expired")

    def test_attached_page_follows_aria_and_then_the_adviser(self):
        dispute_id = self.draft()
        session = self.service.create_screen()
        self.assertTrue(self.service.attach_dispute_screen(JAMES, dispute_id, session["code"])["attached"])
        self.service.update_card_dispute(JAMES, dispute_id, {"narrative": "Never ordered it."})
        self.assertEqual(self.service.screen_status(session["sessionId"])["dispute"]["narrative"], "Never ordered it.")
        token = self.adviser_token(dispute_id)
        self.service.adviser_update(token, {"narrative": "Customer never ordered it."})
        seen = self.service.screen_status(session["sessionId"])
        self.assertEqual((seen["dispute"]["narrative"], seen["dispute"]["filledBy"]["narrative"]),
                         ("Customer never ordered it.", "adviser"))
        self.assertTrue(self.service.adviser_open(token)["customerIsWatching"])

    def test_customer_can_confirm_only_a_complete_form_that_is_with_the_adviser(self):
        dispute_id = self.draft()
        session = self.service.create_screen()
        self.service.attach_dispute_screen(JAMES, dispute_id, session["code"])
        self.complete(dispute_id)
        self.assertFalse(self.service.screen_status(session["sessionId"])["canConfirm"])       # still a draft
        self.refused("not_ready", self.service.customer_confirm, session["sessionId"])
        token = self.adviser_token(dispute_id)
        self.service.adviser_open(token)
        self.assertTrue(self.service.screen_status(session["sessionId"])["canConfirm"])
        confirmed = self.service.customer_confirm(session["sessionId"])
        self.assertEqual((confirmed["dispute"]["confirmationSource"], confirmed["canConfirm"]), ("customer_click", False))
        self.assertEqual(self.service.adviser_submit(token)["dispute"]["status"], "submitted")
        self.assertEqual(self.service.screen_status(session["sessionId"])["dispute"]["status"], "submitted")

    def test_a_code_works_once_and_for_ten_minutes(self):
        dispute_id = self.draft()
        first, late = self.service.create_screen(), self.service.create_screen()
        self.service.attach_dispute_screen(JAMES, dispute_id, first["code"])
        self.refused("code_not_recognised", self.service.attach_dispute_screen, JAMES, dispute_id, first["code"])
        self.now += 11 * 60
        self.refused("code_not_recognised", self.service.attach_dispute_screen, JAMES, dispute_id, late["code"])
        self.assertEqual(self.service.screen_status(late["sessionId"])["state"], "expired")
        self.assertEqual(self.service.screen_status(first["sessionId"])["state"], "attached")   # attached pages last longer

    def test_five_wrong_codes_lock_attaching_for_that_dispute_only(self):
        locked, other = self.draft(), self.draft(transaction="TXN-4821-20261010-4250")
        for _ in range(5):
            self.refused("code_not_recognised", self.service.attach_dispute_screen, JAMES, locked, "000000")
        session = self.service.create_screen()
        self.refused("code_locked", self.service.attach_dispute_screen, JAMES, locked, session["code"])
        self.assertTrue(self.service.attach_dispute_screen(JAMES, other, session["code"])["attached"])

    def test_a_page_cannot_be_taken_over_by_a_second_dispute(self):
        first, second = self.draft(), self.draft(transaction="TXN-4821-20261010-4250")
        session = self.service.create_screen()
        self.service.attach_dispute_screen(JAMES, first, session["code"])
        self.refused("code_not_recognised", self.service.attach_dispute_screen, JAMES, second, session["code"])
        self.assertEqual(self.service.screen_status(session["sessionId"])["dispute"]["disputeId"], first)


class ScreenPop(Base):

    def test_no_open_dispute_says_so(self):
        self.assertEqual(self.service.screen_pop(JAMES), {"hasDispute": "false"})
        self.assertEqual(self.service.screen_pop(""), {"hasDispute": "false"})

    def test_open_dispute_gives_lines_and_a_working_link(self):
        dispute_id = self.draft()
        pop = self.service.screen_pop(JAMES)
        self.assertEqual((pop["hasDispute"], pop["disputeId"]), ("true", dispute_id))
        self.assertIn("**AMAZON.CO.UK**, **£89.99** on 11 Oct 2026, debit card ending 4821", pop["dispute2"])
        self.assertTrue(pop["dispute3"].startswith("**Still needed:** Reason"))
        self.assertTrue(pop["disputeUrl"].startswith("https://pages.example/adviser#"))
        self.assertTrue(all(isinstance(v, str) and "\n" not in v for v in pop.values()), "one line of text each")
        self.assertEqual(self.service.adviser_open(pop["disputeUrl"].split("#")[1])["dispute"]["disputeId"], dispute_id)

    def test_submitted_dispute_no_longer_appears(self):
        dispute_id = self.draft()
        self.complete(dispute_id)
        token = self.adviser_token(dispute_id)
        self.service.adviser_open(token)
        self.service.adviser_record_confirmation(token, True)
        self.service.adviser_submit(token)
        self.assertEqual(self.service.screen_pop(JAMES)["hasDispute"], "false")


class Context:
    """Stands in for the Lambda context the MCP gateway passes."""
    def __init__(self, tool):
        self.client_context = type("C", (), {"custom": {"bedrockAgentCoreToolName": tool}})()


def http(method, path, body=None):
    return {"requestContext": {"http": {"method": method}}, "rawPath": path,
            "body": json.dumps(body) if body is not None else None}


CONTACT = "0a1b2c3d-1111-2222-3333-444455556666"


class LiveSyncRoute(Base):
    """SPEC Part 3, route 3: a contact attaches to the page, and the page saves the form (rules R7 to R10)."""

    def attached(self, customer=JAMES, contact=CONTACT):
        session = self.service.create_screen()
        reply = self.service.attach_contact_screen(contact, customer, session["code"])
        self.assertEqual(reply, {"attached": True, "locked": False, "reason": ""})
        return session["sessionId"]

    def test_attaching_a_contact_turns_the_page_into_a_form_with_that_customers_payments(self):
        status = self.service.screen_status(self.attached())
        self.assertEqual((status["state"], status["dispute"], status["editable"], status["contactId"]),
                         ("form", None, True, CONTACT))
        self.assertEqual({t["card_last_four"] for t in status["transactions"]}, {"4821", "2291"})
        self.assertIn("unauthorised", status["choices"]["reason"])

    def test_first_save_naming_a_payment_creates_the_dispute_and_later_saves_fill_it(self):
        session = self.attached()
        nothing = self.service.page_save(session, {"narrative": "Not me.", "transactionId": ""})
        self.assertIsNone(nothing["dispute"], "no payment chosen yet: nothing to keep")
        saved = self.service.page_save(session, {"transactionId": AMAZON, "disputeType": "unauthorised",
                                                 "reason": "", "narrative": ""})["dispute"]
        self.assertEqual((saved["merchant"], saved["status"], saved["filledBy"]["disputeType"]),
                         ("AMAZON.CO.UK", "draft", "page"))                                    # R10
        done = self.service.page_save(session, {"transactionId": AMAZON, "disputeType": "unauthorised",
                                                "reason": "not_recognised", "cardInPossession": "yes",
                                                "narrative": "I never ordered this."})
        self.assertEqual((done["dispute"]["missing"], done["dispute"]["disputeId"]), ([], saved["disputeId"]))
        self.assertEqual(self.service.screen_pop(JAMES)["disputeId"], saved["disputeId"], "the adviser will see it")
        self.assertIn("watching the form", self.service.screen_pop(JAMES)["dispute4"])

    def test_a_page_can_only_choose_one_of_that_customers_own_payments(self):         # R5, R7
        session = self.attached(customer=SARAH)
        self.refused("transaction_not_found", self.service.page_save, session, {"transactionId": AMAZON})

    def test_a_page_can_never_confirm_or_submit(self):                                # R9
        session = self.attached()
        self.service.page_save(session, {"transactionId": AMAZON, "disputeType": "unauthorised"})
        for fields in ({"customerConfirmation": "yes"}, {"status": "submitted"}, {"cardBlocked": "definitely"}):
            with self.assertRaises(ValueError):
                self.service.page_save(session, fields)
        self.assertEqual(self.service.screen_status(session)["dispute"]["status"], "draft")

    def test_once_an_adviser_has_it_the_page_is_read_only_and_can_confirm(self):       # R8
        session = self.attached()
        self.service.page_save(session, {"transactionId": AMAZON, "disputeType": "unauthorised",
                                         "reason": "not_recognised", "cardInPossession": "yes", "narrative": "No."})
        token = self.service.screen_pop(JAMES)["disputeUrl"].split("#")[1]
        self.service.adviser_open(token)
        self.refused("with_adviser", self.service.page_save, session, {"narrative": "changed my mind"})
        status = self.service.screen_status(session)
        self.assertEqual((status["editable"], status["canConfirm"]), (False, True))
        self.service.customer_confirm(session)
        self.assertEqual(self.service.adviser_submit(token)["dispute"]["status"], "submitted")

    def test_a_page_that_no_contact_attached_cannot_save(self):                        # R8
        waiting = self.service.create_screen()["sessionId"]
        self.refused("not_attached", self.service.page_save, waiting, {"transactionId": AMAZON})
        self.refused("not_attached", self.service.page_save, "made-up", {"transactionId": AMAZON})
        # A page showing ARIA's dispute (Part 1) is a view, not a form.
        dispute_id = self.draft()
        viewer = self.service.create_screen()
        self.service.attach_dispute_screen(JAMES, dispute_id, viewer["code"])
        self.refused("not_attached", self.service.page_save, viewer["sessionId"], {"narrative": "x"})

    def test_wrong_codes_lock_that_contact_and_the_same_call_asking_again_is_fine(self):
        session = self.service.create_screen()
        for _ in range(4):
            self.assertEqual(self.service.attach_contact_screen(CONTACT, JAMES, "000000")["reason"], "code_not_recognised")
        self.assertTrue(self.service.attach_contact_screen(CONTACT, JAMES, "000000")["locked"])
        self.assertEqual(self.service.attach_contact_screen(CONTACT, JAMES, session["code"]),
                         {"attached": False, "locked": True, "reason": "too_many_wrong_codes"})
        other = "9a1b2c3d-1111-2222-3333-444455556666"
        self.assertTrue(self.service.attach_contact_screen(other, JAMES, session["code"])["attached"])
        self.assertTrue(self.service.attach_contact_screen(other, JAMES, session["code"])["attached"], "asked twice")
        third = "7a1b2c3d-1111-2222-3333-444455556666"
        self.assertFalse(self.service.attach_contact_screen(third, SARAH, session["code"])["attached"], "already taken")

    def test_no_customer_on_the_contact_attaches_nothing(self):                        # R7
        session = self.service.create_screen()
        self.assertEqual(self.service.attach_contact_screen(CONTACT, "", session["code"])["reason"],
                         "customer_not_identified")
        self.assertEqual(self.service.screen_status(session["sessionId"])["state"], "waiting")

    def test_a_page_attached_to_a_call_cannot_be_taken_over_by_a_tool(self):
        session = self.service.create_screen()
        self.service.attach_contact_screen(CONTACT, JAMES, session["code"])
        self.refused("code_not_recognised", self.service.attach_dispute_screen, JAMES, self.draft(), session["code"])


class ThreeWaysIn(Base):

    def setUp(self):
        super().setUp()
        entry.service = self.service
        self.asked_connect = []
        entry.doors = dispute_web.Doors(
            acxd_key=lambda: "the-key", touchpoint_keys=lambda: {"deploymentKey": "dk", "apiKey": "ak"},
            customer_of_contact=lambda contact: self.asked_connect.append(contact) or JAMES, region="eu-west-2",
            instance_id="inst-1")

    def acxd(self, body, key="the-key"):
        return entry.lambda_handler({**http("POST", "/acxd/ops", body), "headers": {"x-api-key": key}}, None)

    def test_cx_designer_door_needs_the_key_and_offers_one_operation(self):
        session = json.loads(entry.lambda_handler(http("POST", "/api/screen"), None)["body"])
        ask = {"operation": "attachToScreen", "contactId": CONTACT, "code": session["code"]}
        self.assertEqual(self.acxd(ask, key="wrong")["statusCode"], 401)
        self.assertEqual(self.acxd(ask, key="")["statusCode"], 401)
        for operation in ("screen_pop", "adviser_submit", "start_card_dispute", "getDispute"):
            self.assertEqual(self.acxd({**ask, "operation": operation})["statusCode"], 403, operation)
        self.assertEqual(self.service.screen_status(session["sessionId"])["state"], "waiting", "nothing attached yet")
        reply = self.acxd(ask)
        self.assertEqual((reply["statusCode"], json.loads(reply["body"])), (200, {"attached": True, "locked": False, "reason": ""}))
        entry.doors.acxd_key = lambda: ""
        self.assertEqual(self.acxd(ask)["statusCode"], 503)

    def test_cx_designer_door_takes_the_customer_from_connect_never_from_the_request(self):      # R7
        session = json.loads(entry.lambda_handler(http("POST", "/api/screen"), None)["body"])
        self.acxd({"operation": "attachToScreen", "contactId": CONTACT.upper(), "code": session["code"],
                   "customerId": SARAH, "customer_id": SARAH})
        self.assertEqual(self.asked_connect, [CONTACT])
        status = self.service.screen_status(session["sessionId"])
        self.assertEqual({t["card_last_four"] for t in status["transactions"]}, {"4821", "2291"}, "James's, not Sarah's")

    def test_cx_designer_door_always_answers_with_every_field(self):
        for body in ({"operation": "attachToScreen", "contactId": "not-a-contact", "code": "123456"},
                     {"operation": "attachToScreen", "contactId": CONTACT, "code": "000000"},
                     {"operation": "attachToScreen", "contactId": CONTACT}):
            reply = self.acxd(body)
            self.assertEqual((reply["statusCode"], set(json.loads(reply["body"]))), (200, {"attached", "locked", "reason"}))

    def test_page_can_save_over_http_and_gets_live_sync_settings(self):
        session = json.loads(entry.lambda_handler(http("POST", "/api/screen"), None)["body"])
        self.acxd({"operation": "attachToScreen", "contactId": CONTACT, "code": session["code"]})
        saved = entry.lambda_handler(http("POST", "/api/screen/save", {
            "sessionId": session["sessionId"], "fields": {"transactionId": AMAZON, "disputeType": "merchant"}}), None)
        self.assertEqual(json.loads(saved["body"])["dispute"]["disputeTypeWords"], "Problem with a payment the customer made")
        refused = entry.lambda_handler(http("POST", "/api/screen/save", {"sessionId": "nope", "fields": {}}), None)
        self.assertEqual(refused["statusCode"], 403)
        config = json.loads(entry.lambda_handler(http("GET", "/api/config"), None)["body"])
        self.assertEqual(config, {"configured": True, "region": "eu-west-2", "instanceId": "inst-1",
                                  "deploymentKey": "dk", "apiKey": "ak"})
        entry.doors.touchpoint_keys = lambda: {}
        self.assertEqual(json.loads(entry.lambda_handler(http("GET", "/api/config"), None)["body"]),
                         {"configured": False, "region": "eu-west-2", "instanceId": "inst-1"})

    def test_only_the_customer_page_may_run_the_live_sync_library(self):
        customer = entry.lambda_handler(http("GET", "/"), None)["headers"]["content-security-policy"]
        adviser = entry.lambda_handler(http("GET", "/adviser"), None)["headers"]["content-security-policy"]
        for address in ("https://nlu.acxd.connect.eu-west-2.amazonaws.com", "wss://ws.nlu.acxd.connect.eu-west-2.amazonaws.com",
                        "https://participant.connect.eu-west-2.amazonaws.com", "https://participant.connect.eu-west-2.api.aws",
                        "wss://*.transport.connect.eu-west-2.amazonaws.com", "https://*.chime.aws", "wss://*.chime.aws"):
            self.assertIn(address, customer, "same list as the mortgage Live Sync page")
        self.assertNotIn("acxd", adviser)
        self.assertNotIn("unsafe-inline", adviser)
        for policy in (customer, adviser):
            self.assertIn("frame-ancestors 'none'", policy)
            self.assertNotIn("'unsafe-eval'", policy.replace("'wasm-unsafe-eval'", ""))
        for path in ("/vendor/../aria_card_dispute.js", "/vendor/touchpoint-1.0.1/../../customer.js",
                     "/vendor/missing.js", "/vendor/a/b/c.js", "/vendor/x.html"):
            self.assertEqual(entry.lambda_handler(http("GET", path), None)["statusCode"], 404, path)

    def tool(self, name, **args):
        return entry.lambda_handler(args, Context(f"aria-banking-dispute___{name}"))

    def test_tool_calls_reach_the_service_in_both_gateway_forms(self):
        started = self.tool("start_card_dispute", customer_id=JAMES, transaction_id=AMAZON, dispute_type="unauthorised")
        self.assertEqual(started["status"], "draft")
        rpc = entry.lambda_handler({"jsonrpc": "2.0", "params": {"name": "aria-banking-dispute___update_card_dispute",
                                   "arguments": {"customer_id": JAMES, "dispute_id": started["dispute_id"],
                                                 "card_in_possession": "no", "card_blocked": "yes"}}}, None)
        self.assertEqual((rpc["dispute"]["cardInPossession"], rpc["dispute"]["cardBlocked"]), ("no", "yes"))

    def test_tool_errors_come_back_as_data_never_as_an_exception(self):
        self.assertEqual(self.tool("start_card_dispute", customer_id=JAMES, transaction_id="x",
                                   dispute_type="unauthorised")["error"], "transaction_not_found")
        self.assertEqual(self.tool("update_card_dispute", customer_id=JAMES, dispute_id="DSP-NOPE")["error"],
                         "dispute_not_found")
        self.assertEqual(self.tool("delete_everything")["error"], "unknown_tool")

    def test_no_tool_can_submit_or_confirm(self):                                # R2
        dispute_id = self.draft()
        self.complete(dispute_id)
        for name in ("submit_card_dispute", "confirm_card_dispute", "adviser_submit"):
            self.assertEqual(self.tool(name, customer_id=JAMES, dispute_id=dispute_id)["error"], "unknown_tool")
        reply = self.tool("update_card_dispute", customer_id=JAMES, dispute_id=dispute_id, status="submitted",
                          customer_confirmation="yes", narrative="still a draft")
        self.assertEqual((reply["status"], reply["dispute"]["customerConfirmed"]), ("draft", False))

    def test_a_web_request_is_never_treated_as_a_tool_or_internal_call(self):
        dispute_id = self.draft()
        for disguise in ({"operation": "screen_pop", "customerId": JAMES},
                         {"params": {"name": "get_card_dispute", "arguments": {"customer_id": JAMES}}},
                         {"customer_id": JAMES, "dispute_id": dispute_id, "toolName": "get_card_dispute"}):
            reply = entry.lambda_handler({**http("POST", "/api/screen/status", {"sessionId": "x"}), **disguise}, None)
            self.assertEqual(json.loads(reply["body"]), {"state": "expired"})

    def test_a_tool_call_can_never_reach_the_internal_operation(self):           # R2
        # The internal operation hands out an adviser link, which can confirm and submit.
        # ARIA must not be able to get one by passing "operation" as a tool argument.
        self.draft()
        ask = {"operation": "screen_pop", "customerId": JAMES, "customer_id": JAMES}
        for reply in (
            entry.lambda_handler(dict(ask), Context("aria-banking-dispute___get_card_dispute")),
            entry.lambda_handler(dict(ask), Context("aria-banking-dispute___screen_pop")),
            entry.lambda_handler({"jsonrpc": "2.0", "operation": "screen_pop", "customerId": JAMES,
                                  "params": {"name": "x___screen_pop", "arguments": ask}}, None),
            entry.lambda_handler({**ask, "toolName": "screen_pop"}, None),
        ):
            self.assertNotIn("disputeUrl", reply)
            self.assertNotIn("hasDispute", reply)
            self.assertNotIn("adviser#", json.dumps(reply))

    def test_internal_screen_pop_call(self):
        self.draft()
        self.assertEqual(entry.lambda_handler({"operation": "screen_pop", "customerId": JAMES}, None)["hasDispute"], "true")
        self.assertEqual(entry.lambda_handler({"operation": "screen_pop"}, None), {"hasDispute": "false"})

    def test_pages_and_their_calls_over_http(self):
        page = entry.lambda_handler(http("GET", "/"), None)
        self.assertEqual(page["statusCode"], 200)
        self.assertIn("frame-ancestors 'none'", page["headers"]["content-security-policy"])
        self.assertEqual(entry.lambda_handler(http("GET", "/adviser"), None)["statusCode"], 200)
        self.assertEqual(entry.lambda_handler(http("GET", "/assets/customer.js"), None)["statusCode"], 200)
        for missing in ("/assets/../aria_card_dispute.py", "/assets/secret.txt", "/api/screen"):
            self.assertEqual(entry.lambda_handler(http("GET", missing), None)["statusCode"], 404)

        session = json.loads(entry.lambda_handler(http("POST", "/api/screen"), None)["body"])
        dispute_id = self.draft()
        self.service.attach_dispute_screen(JAMES, dispute_id, session["code"])
        status = json.loads(entry.lambda_handler(http("POST", "/api/screen/status", session), None)["body"])
        self.assertEqual(status["dispute"]["disputeId"], dispute_id)

        token = self.adviser_token(dispute_id)
        refused = entry.lambda_handler(http("POST", "/api/adviser/submit", {"token": token}), None)
        self.assertEqual((refused["statusCode"], json.loads(refused["body"])["error"]), (409, "incomplete"))
        bad = entry.lambda_handler(http("POST", "/api/adviser/update", {"token": token, "fields": {"reason": "x"}}), None)
        self.assertEqual((bad["statusCode"], json.loads(bad["body"])["error"]), (400, "invalid_field"))
        self.assertEqual(entry.lambda_handler(http("POST", "/api/adviser/open", {"token": "nope"}), None)["statusCode"], 403)
        huge = {**http("POST", "/api/screen/status"), "body": "x" * 5000}
        self.assertEqual(entry.lambda_handler(huge, None)["statusCode"], 413)

    def test_pages_have_no_inline_script_and_write_text_not_html(self):
        for name in ("customer.html", "adviser.html"):
            html = (FOLDER / "web" / name).read_text()
            self.assertEqual(re.findall(r"<script(?![^>]*\bsrc=)", html), [], name)
            self.assertNotRegex(html, r"\son[a-z]+=", name)
            self.assertNotIn("style=", html, name)
        for name in ("common.js", "customer.js", "adviser.js"):
            script = (FOLDER / "web" / name).read_text()
            for unsafe in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
                self.assertNotIn(unsafe, script, name)

    def test_logs_carry_no_customer_content_codes_or_tokens(self):
        with self.assertLogs(level="INFO") as logs:
            started = self.tool("start_card_dispute", customer_id=JAMES, transaction_id=AMAZON, dispute_type="unauthorised")
            self.tool("update_card_dispute", customer_id=JAMES, dispute_id=started["dispute_id"],
                      narrative="PRIVATE-NARRATIVE")
            session = json.loads(entry.lambda_handler(http("POST", "/api/screen"), None)["body"])
            self.tool("attach_dispute_screen", customer_id=JAMES, dispute_id=started["dispute_id"], code=session["code"])
            pop = entry.lambda_handler({"operation": "screen_pop", "customerId": JAMES}, None)
            entry.lambda_handler(http("POST", "/api/adviser/open", {"token": pop["disputeUrl"].split("#")[1]}), None)
            self.tool("get_card_dispute", customer_id=JAMES, dispute_id="\nINJECTED line")
            self.acxd({"operation": "attachToScreen", "contactId": CONTACT, "code": "135790"}, key="GUESSED-KEY")
            self.acxd({"operation": "attachToScreen", "contactId": CONTACT, "code": "135790"})
        written = "\n".join(logs.output)
        for private in ("PRIVATE-NARRATIVE", "AMAZON", "89.99", session["code"], session["sessionId"],
                        pop["disputeUrl"].split("#")[1], "INJECTED", "GUESSED-KEY", "the-key", "135790"):
            self.assertNotIn(private, written)
        self.assertIn(started["dispute_id"], written)


def _has_float(value):
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_has_float(v) for v in value.values())
    return isinstance(value, list) and any(_has_float(v) for v in value)


class AriaPromptAndTools(unittest.TestCase):

    def setUp(self):
        sys.path.insert(0, str(FOLDER / "scripts"))
        import build_aria_prompt
        self.builder = build_aria_prompt
        self.block = self.builder.BLOCK_FILES["direct"].read_text()
        self.live = ("system: |\n  You are ARIA.\n\n  <assurance_levels>\n  Levels.\n  </assurance_levels>\n\n"
                     "  ## Query Handling\n  {{$.Custom.customerId}}\n\nmessages:\n  - \"{{$.conversationHistory}}\"\n")

    def test_block_goes_after_assurance_levels_indented_like_the_rest(self):
        built = self.builder.add_disputes(self.live, self.block)
        self.assertEqual(self.builder.check(built), [])
        lines = built.split("\n")
        self.assertEqual(lines[lines.index("  </assurance_levels>") + 2], "  <card_disputes>")
        self.assertLess(lines.index("  </card_disputes>"), lines.index("  ## Query Handling"))
        system = lines[1:lines.index("messages:")]
        self.assertEqual([line for line in system if line and not line.startswith("  ")], [])

    def test_building_twice_does_not_duplicate_the_section(self):
        once = self.builder.add_disputes(self.live, self.block)
        self.assertEqual(self.builder.add_disputes(once, self.block), once)

    def test_a_prompt_connect_would_reject_is_reported(self):
        with self.assertRaises(ValueError):
            self.builder.add_disputes("system: |\n  no anchor\nmessages:\n", self.block)
        too_long = self.live.replace("You are ARIA.", "x" * 100_000)
        self.assertIn("limit", " ".join(self.builder.check(self.builder.add_disputes(too_long, self.block))))
        many = self.live.replace("{{$.Custom.customerId}}", " ".join("{{$.Custom.v%s}}" % chr(97 + n) for n in range(20)))
        self.assertIn("custom variables", " ".join(self.builder.check(many)))

    def test_block_adds_no_custom_variables_and_names_only_real_tools_and_values(self):
        self.assertNotIn("{{", self.block)
        tools = {tool["name"]: tool for tool in json.loads((FOLDER / "scripts" / "tool_schemas.json").read_text())}
        self.assertEqual(tuple(tools), entry._TOOLS)
        for name in tools:
            if name != "get_card_dispute":
                self.assertIn(name, self.block)
        for reason in model.EDITABLE["reason"]:
            self.assertIn(reason, tools["update_card_dispute"]["inputSchema"]["properties"]["reason"]["description"])
        for value in ("card_lost_or_stolen", "card_details_used_without_card", "not_recognised", "fraud_security",
                      "summaryStartsWith", "customer_page"):
            self.assertIn(value, self.block)
        self.assertEqual(set(entry._UPDATE_ARGUMENTS) - set(tools["update_card_dispute"]["inputSchema"]["properties"]), set())


class DisputesCollaborator(unittest.TestCase):
    """SPEC Part 3, route 1: the change the attach script makes to ARIA's AI agent."""

    DISPUTES = "11111111-2222-3333-4444-555555555555"

    def setUp(self):
        sys.path.insert(0, str(FOLDER / "scripts"))
        import collaborator_config
        self.config = collaborator_config
        self.aria = {"orchestrationAIAgentConfiguration": {
            "orchestrationAIPromptId": "prompt:18", "locale": "en_GB", "connectInstanceArn": "arn:instance",
            "orchestrationAIGuardrailId": "guard:1",
            "toolConfigurations": [{"toolName": "Escalate"}, {"toolName": "Complete"}, {"toolName": "Retrieve"}]}}

    def collaborators(self, configuration):
        return configuration["orchestrationAIAgentConfiguration"].get("multiAgentConfigurations", [])

    def test_adds_one_handoff_collaborator_and_changes_nothing_else(self):
        after, changed = self.config.apply(self.aria, self.DISPUTES)
        self.assertTrue(changed)
        (entry,) = self.collaborators(after)
        handoff = entry["handoffAgentConfiguration"]
        self.assertEqual((handoff["agentTarget"], handoff["immediateHandoff"]), ({"aiAgentId": self.DISPUTES}, False))
        rest = dict(after["orchestrationAIAgentConfiguration"])
        del rest["multiAgentConfigurations"]
        self.assertEqual(rest, self.aria["orchestrationAIAgentConfiguration"], "prompt, tools, guardrail, locale untouched")
        self.assertNotIn("multiAgentConfigurations", self.aria["orchestrationAIAgentConfiguration"], "input not mutated")

    def test_running_twice_changes_nothing_the_second_time(self):
        once, _ = self.config.apply(self.aria, self.DISPUTES)
        twice, changed = self.config.apply(once, self.DISPUTES)
        self.assertEqual((twice, changed), (once, False))

    def test_other_collaborators_are_kept_and_ours_is_replaced_or_removed(self):
        other = {"delegateAgentConfiguration": {"agentTarget": {"aiAgentId": "other"},
                                                "instruction": {"instruction": "Score a transaction."}}}
        self.aria["orchestrationAIAgentConfiguration"]["multiAgentConfigurations"] = [other]
        added, _ = self.config.apply(self.aria, self.DISPUTES)
        moved, changed = self.config.apply(added, "99999999-2222-3333-4444-555555555555")   # the agent was recreated
        self.assertTrue(changed)
        self.assertEqual(self.config.describe(self.collaborators(moved)),
                         ["delegate -> other", "handoff -> 99999999-2222-3333-4444-555555555555"])
        removed, changed = self.config.apply(moved, remove=True)
        self.assertEqual((self.collaborators(removed), changed), ([other], True))

    def test_refuses_what_connect_would_refuse(self):
        with self.assertRaises(ValueError):
            self.config.apply({"selfServiceAIAgentConfiguration": {}}, self.DISPUTES)
        self.aria["orchestrationAIAgentConfiguration"]["multiAgentConfigurations"] = [
            {"delegateAgentConfiguration": {"agentTarget": {"aiAgentId": f"a{n}"}, "instruction": {"instruction": "x"}}}
            for n in range(5)]
        with self.assertRaises(ValueError):
            self.config.apply(self.aria, self.DISPUTES)

    def test_a_collaborator_that_talks_to_the_customer_must_be_able_to_hand_back(self):
        ready = {"name": "d", "type": "ORCHESTRATION", "configuration": {"orchestrationAIAgentConfiguration": {
            "toolConfigurations": [{"toolName": "Complete"}, {"toolName": "Escalate"}]}}}
        self.assertEqual(self.config.check_collaborator(ready), [])
        ready["configuration"]["orchestrationAIAgentConfiguration"]["toolConfigurations"].pop()
        self.assertIn("no Escalate tool", self.config.check_collaborator(ready)[0])
        self.assertIn("not an Orchestration", self.config.check_collaborator({"name": "x", "type": "SELF_SERVICE"})[0])

    def test_instruction_carries_the_contract_both_prompts_rely_on(self):
        instruction = self.config.INSTRUCTION
        for needed in ("Level 2", "customer ID", "Do not announce", "'Card dispute'", "six-digit code"):
            self.assertIn(needed, instruction)

    def test_disputes_agent_prompt_keeps_the_join_invisible_and_hands_back_in_the_agreed_form(self):
        prompt = (FOLDER / "prompts" / "disputes-agent-prompt-v1.yaml").read_text()
        self.assertTrue(prompt.startswith("system: |\n"))
        lines = prompt.split("\n")
        self.assertEqual([l for l in lines[1:lines.index("messages:")] if l and not l.startswith("  ")], [])
        self.assertLessEqual(len(set(re.findall(r"\{\{\$\.Custom\.([A-Za-z]+)\}\}", prompt))), 19)
        for field in ("topicCategory:", "escalationReason: complex_request", "customerIntent: Dispute a card transaction",
                      "conversationSummary"):
            self.assertIn(field, prompt, "Escalate fails if a required field is left out")
        self.assertIn("do NOT offer or ask again", prompt)
        for needed in ("You are ARIA", "Never greet", "Card dispute <dispute_id> drafted. topicCategory=<handover.topicCategory>.",
                       "Card dispute not drafted.", "Level 2 or above", "{{$.toolConfigurationList}}"):
            self.assertIn(needed, prompt)
        for tool in entry._TOOLS:
            if tool != "get_card_dispute":
                self.assertIn(tool, prompt)
        aria = (FOLDER / "prompts" / "card-disputes-agents-block.txt").read_text()
        for needed in ('summary that begins "Card dispute"', 'after "topicCategory="', "Do NOT greet", "StartCardDispute", "screenCode"):
            self.assertIn(needed, aria)
        self.assertNotIn("{{", aria)


class LiveSyncConfiguration(unittest.TestCase):
    """SPEC Part 3, route 3: what is pasted into the CX designer and imported into Connect agrees with the code."""

    def setUp(self):
        self.node = (FOLDER / "acxd" / "live-sync-node.md").read_text()
        self.flow = json.loads((FOLDER / "flows" / "card-dispute-livesync-handover-flow.json").read_text())
        self.blocks = {a["Identifier"]: a for a in self.flow["Actions"]}

    def declared(self, set_by_connect):
        rows = re.findall(r"^\| `(\w+)` \| String \| (On|Off) \|", self.node, re.M)
        return {name for name, frontend in rows if (frontend == "On") == set_by_connect}

    def test_flow_passes_only_declared_context_variables_and_at_most_ten(self):
        passed = self.blocks["CardDisputeAssistant"]["Parameters"]["AgentConfiguration"]["ContextVariables"]
        self.assertEqual(set(passed), self.declared(set_by_connect=True))
        self.assertLessEqual(len(passed), 10)
        self.assertEqual(passed["contactId"], "$.ContactId")
        self.assertNotIn("customerId", passed, "the service finds the customer from the contact itself (R7)")

    def test_flow_reads_back_only_what_the_assistant_sets(self):
        read = set(re.findall(r"\$\.AgenticCX\.ContextVariables\.(\w+)", json.dumps(self.flow)))
        self.assertEqual(read, self.declared(set_by_connect=False))
        for name in read:
            self.assertRegex(self.node, rf"\| `{name}` \| `", f"{name} is set on the Escalate node")

    def test_every_way_out_of_the_assistant_reaches_a_person_with_a_topic(self):
        start = self.blocks["CardDisputeAssistant"]["Transitions"]
        self.assertEqual(start["Conditions"][0]["NextAction"], "CheckTopic")
        for name in ("Escalated", "EscalatedTopicUnknown", "AssistantUnavailable"):
            block = self.blocks[name]
            self.assertTrue(block["Parameters"]["Attributes"]["topicCategory"])
            self.assertEqual(block["Transitions"]["NextAction"], "ToHumanHandover")
        self.assertEqual(self.blocks["EscalatedTopicUnknown"]["Parameters"]["Attributes"]["topicCategory"], "fraud_security")
        topics = [c["Condition"]["Operands"][0] for c in self.blocks["CheckTopic"]["Transitions"]["Conditions"]]
        self.assertEqual(topics, ["fraud_security", "debit_card", "credit_card"])
        self.assertIn("fraud_security, debit_card, credit_card", self.node)

    def test_the_one_data_request_matches_the_door_it_calls(self):
        sample = json.loads(re.search(r"Request sample \| `(\{.*?\})`", self.node).group(1))
        self.assertEqual(set(sample), {"operation", "contactId", "code"})
        self.assertRegex(sample["contactId"], dispute_web.CONTACT_ID)
        response = json.loads(re.search(r"Response sample \| `(\{.*?\})`", self.node).group(1))
        self.assertEqual(set(response), set(dispute_web.ACXD_REPLY))
        self.assertEqual(re.findall(r"\| Data request \| `(\w+)`", self.node), ["attachToScreen"])

    def test_nothing_the_assistant_has_can_confirm_or_submit(self):
        self.assertEqual(json.loads((FOLDER / "acxd" / "live-sync-actions.json").read_text()), {"actions": []})
        self.assertIn("Never submit, confirm or accept a dispute", self.node)
        self.assertNotIn("Task complete |", self.node.split("### 3d.")[1].split("Also connect")[0])

    def test_prompt_variables_are_all_declared(self):
        prompt = self.node.split("### 3a. Agent prompt")[1].split("```")[1]
        used = set(re.findall(r"\{(\w+)\}", prompt))
        self.assertLessEqual(used, self.declared(True) | self.declared(False))

    def test_arias_hand_over_tool_and_prompt_agree(self):
        schema = json.loads((FOLDER / "acxd" / "connect-ai-agent" / "StartCardDispute.schema.json").read_text())
        self.assertEqual(schema["required"], ["handoverSummary", "screenCode"])
        self.assertEqual(schema["properties"]["screenCode"]["pattern"], "^\\d{6}$")
        aria = (FOLDER / "prompts" / "card-disputes-agents-block.txt").read_text()
        for name in schema["properties"]:
            self.assertIn(name, aria)


class FakeTable:
    """The slice of a DynamoDB table DynamoStore uses, with conditional writes."""
    def __init__(self):
        self.items = {}

    def get_item(self, Key, ConsistentRead):
        item = self.items.get(Key["pk"])
        return {"Item": dict(item)} if item else {}

    def put_item(self, Item, ConditionExpression=None, ExpressionAttributeNames=None, ExpressionAttributeValues=None):
        for alias in re.findall(r"#\w+", ConditionExpression or ""):
            assert alias in ExpressionAttributeNames, f"{alias} has no name"
        assert not _has_float(Item), "DynamoDB refuses floats"
        current = self.items.get(Item["pk"])
        values = ExpressionAttributeValues or {}
        if ConditionExpression and "attribute_not_exists" in ConditionExpression:
            if current is not None and not current.get("expiresAt", float("inf")) <= values[":now"]:
                raise type("ConditionalCheckFailedException", (Exception,), {})()
        elif ConditionExpression and (current is None or current.get("version") != values[":seen"]):
            raise type("ConditionalCheckFailedException", (Exception,), {})()
        self.items[Item["pk"]] = dict(Item)


class BothStoresBehaveTheSame(unittest.TestCase):

    def stores(self):
        clock = {"now": 1000.0}
        tick = lambda: clock["now"]                                              # noqa: E731
        return clock, (MemoryStore(tick), DynamoStore("t", tick, table=FakeTable()))

    def test_conditional_writes_and_expiry(self):
        clock, stores = self.stores()
        for store in stores:
            clock["now"] = 1000.0
            name = type(store).__name__
            self.assertTrue(store.put("k", {"version": 1, "expiresAt": 1100}, expect=ABSENT), name)
            self.assertFalse(store.put("k", {"version": 1}, expect=ABSENT), name)
            self.assertFalse(store.put("k", {"version": 3}, expect=2), name)
            self.assertTrue(store.put("k", {"version": 2, "expiresAt": 1100}, expect=1), name)
            self.assertEqual(store.get("k"), {"version": 2, "expiresAt": 1100}, name)
            clock["now"] = 1101.0
            self.assertIsNone(store.get("k"), name)
            self.assertTrue(store.put("k", {"version": 1}, expect=ABSENT), f"{name}: an expired item counts as absent")

    def test_the_service_works_on_the_dynamodb_store(self):
        now = [1_800_000_000.25]          # a real clock is never a whole number
        service = DisputeService(DynamoStore("t", lambda: now[0], table=FakeTable()), lambda: now[0], page_url="https://p")
        dispute_id = service.start_card_dispute(JAMES, AMAZON, "unauthorised")["dispute_id"]
        session = service.create_screen()
        service.attach_dispute_screen(JAMES, dispute_id, session["code"])
        service.update_card_dispute(JAMES, dispute_id, {"reason": "not_recognised", "cardInPossession": "yes",
                                                        "narrative": "Not me."})
        token = service.screen_pop(JAMES)["disputeUrl"].split("#")[1]
        service.adviser_open(token)
        service.customer_confirm(session["sessionId"])
        self.assertEqual(service.adviser_submit(token)["dispute"]["status"], "submitted")


if __name__ == "__main__":
    unittest.main()
