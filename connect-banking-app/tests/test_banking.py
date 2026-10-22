"""
Tests for the internet banking app: which assistant each page reaches, who the customer is, what reaches the
mortgage and dispute services, and what the browser may load. No AWS.
"""

import io
import json
import os
import sys
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
sys.path[:0] = [str(APP), str(APP / "api"), str(ROOT / "connect-money-hub"), str(ROOT / "connect-money-hub" / "api"),
                str(ROOT / "connect-card-dispute" / "lambda")]

import banking_api as app  # noqa: E402
import money_api  # noqa: E402
from bankapp import flowview, home, journeys, partners  # noqa: E402
from moneyhub.service import MoneyHub  # noqa: E402
from moneyhub.store import MemoryStore  # noqa: E402

JAMES = "CUST-001"
NOW = 1_800_000_000.0
APP_ID = "MA-ABCDEFGH"


class FakeConnect:
    def __init__(self):
        self.calls = []

    def start_web_rtc_contact(self, **request):
        self.calls.append(("call", request))
        return {"ContactId": "11111111-2222-4333-8444-555555555555", "ParticipantToken": "pt-secret",
                "ConnectionData": {"Meeting": {"MeetingId": "m-1"}, "Attendee": {"AttendeeId": "a-1"}}}

    def start_chat_contact(self, **request):
        self.calls.append(("chat", request))
        return {"ContactId": "22222222-2222-4333-8444-555555555555", "ParticipantToken": "pt-chat"}


class FakeSSM:
    """The flow view's setting: a value, or None for a parameter that doesn't exist (or can't be read)."""

    def __init__(self, value):
        self.value, self.reads = value, 0

    def get_parameter(self, Name):
        self.reads += 1
        if self.value is None:
            raise RuntimeError("ParameterNotFound")
        return {"Parameter": {"Name": Name, "Value": self.value}}


class FakePayload:
    def __init__(self, data):
        self.data = data

    def read(self):
        return json.dumps(self.data).encode()


class FakeLambda:
    """Answers invokes of the mortgage and dispute Lambdas, and records them."""

    def __init__(self, reply):
        self.reply, self.invoked = reply, []

    def invoke(self, FunctionName, Payload):
        self.invoked.append((FunctionName, json.loads(Payload)))
        return {"Payload": FakePayload(self.reply)}


def http(method, path, body=None):
    return {"requestContext": {"http": {"method": method}}, "rawPath": path, "body": json.dumps(body) if body else None}


class Base(unittest.TestCase):

    def setUp(self):
        money_api.hub = MoneyHub(MemoryStore(lambda: NOW), lambda: NOW, page_url="https://bank.example")
        money_api.CONNECT_INSTANCE_ID, money_api.CONTACT_FLOW_ID = "inst-1", "flow-cbf"
        self.connect = FakeConnect()
        money_api._connect = self.connect
        self.verified = money_api.hub.mint_link(JAMES, "2").split("#k=")[1]
        self.demo = money_api.hub.mint_link(JAMES).split("#k=")[1]
        self.ssm = flowview._ssm = FakeSSM(None)
        flowview._cached.update(at=-1e12, on=False)
        os.environ.pop("FLOW_VIEW", None)

    def tearDown(self):
        flowview._ssm = None
        money_api.CONNECT_INSTANCE_ID = money_api.CONTACT_FLOW_ID = ""
        money_api._connect = None
        partners._lambda = None

    def post(self, path, **body):
        reply = app.lambda_handler(http("POST", path, body), None)
        return reply["statusCode"], json.loads(reply["body"])


class WhoHelps(Base):
    """The page decides who helps; the link's record decides who the customer is."""

    def attributes(self, kind="chat"):
        return self.connect.calls[-1][1]["Attributes"]

    def test_money_hub_sends_exactly_what_the_money_hub_page_sends(self):
        status, reply = self.post("/api/contact/chat", token=self.verified, page="money_hub", view="goals")
        self.assertEqual(status, 200)
        self.assertEqual(self.attributes(), {**journeys.money_hub.attributes(JAMES, "2", "goals"), "appPage": "money_hub"},
                         "the Money Hub page's own attributes, plus appPage: this app's form opens on a call")
        self.assertEqual(self.attributes()["entry"], "money_hub")
        self.assertIn("Goals tab", reply["opener"])

    def test_the_mortgage_form_starts_with_aria_carrying_its_application_and_stage(self):
        status, reply = self.post("/api/contact/call", token=self.verified, page="mortgage", stage="property_loan",
                                  applicationId=APP_ID)
        self.assertEqual(status, 200)
        sent = self.attributes()
        self.assertEqual((sent["entry"], sent["appPage"], sent["applicationId"], sent["stage"], sent["customerId"]),
                         ("banking_app", "mortgage", APP_ID, "property_loan", JAMES),
                         "ARIA first; the mortgage flow reads the application when she hands over")
        self.assertEqual(sent["authStatus"], "authenticated")
        self.assertEqual(self.connect.calls[-1][1]["ContactFlowId"], "flow-cbf")
        self.assertEqual(reply["journey"], "mortgage")
        self.assertNotIn("pt-secret", json.dumps(self.attributes()))

    def test_the_form_keeps_telling_the_assistant_its_fields_while_aria_hands_over(self):
        apply = (APP / "web" / "pages" / "apply.js").read_text()
        self.assertIn("resendContext({ send: () => sendContext(), delays: AFTER_ARIA_MS })", apply)
        self.assertIn("export const AFTER_ARIA_MS = [...RESEND_AFTER_MS, 45000, 60000, 90000, 120000];", apply,
                      "ARIA greets and hands over first: the mortgage assistant can start well after the contact")

    def test_a_chat_starts_with_no_initial_message(self):
        self.post("/api/contact/chat", token=self.verified, page="cards")
        self.assertNotIn("InitialMessage", self.connect.calls[-1][1], "the opener goes once ARIA listens")

    def test_a_demo_link_never_carries_the_customer_onto_a_mortgage_contact(self):
        self.post("/api/contact/chat", token=self.demo, page="mortgage", stage="about_you", applicationId=APP_ID)
        self.assertNotIn("customerId", self.attributes())

    def test_a_made_up_stage_or_application_starts_nothing(self):
        for stage, application in (("hacking", APP_ID), ("about_you", "MA-0000"), ("about_you", "")):
            status, reply = self.post("/api/contact/chat", token=self.verified, page="mortgage", stage=stage,
                                      applicationId=application)
            self.assertEqual((status, reply["error"]), (400, "bad_request"))
        self.assertEqual(self.connect.calls, [])

    def test_a_card_dispute_starts_with_aria_told_the_customers_own_payment(self):
        payment = home.cards(JAMES)["payments"][0]
        status, reply = self.post("/api/contact/chat", token=self.verified, page="card_dispute", paymentId=payment["id"])
        self.assertEqual(status, 200)
        sent = self.attributes()
        self.assertEqual((sent["entry"], sent["appPage"], sent["customerId"]), ("banking_app", "card_dispute", JAMES))
        self.assertEqual(sent["preferredName"], "James")
        self.assertIn(payment["merchant"], sent["handoverSummary"])
        self.assertIn(f"£{payment['amount']:.2f}", sent["handoverSummary"])
        self.assertIn(payment["merchant"], reply["opener"])
        self.assertIn(f"£{payment['amount']:.2f}", reply["opener"])

    def test_an_unverified_dispute_goes_to_aria_for_her_id_check_and_carries_no_customer(self):
        payment = home.cards(JAMES)["payments"][0]
        self.post("/api/contact/chat", token=self.demo, page="card_dispute", paymentId=payment["id"])
        sent = self.attributes()
        self.assertEqual((sent["entry"], sent["appPage"]), ("banking_app", "card_dispute"))
        self.assertNotIn("customerId", sent)
        self.assertNotIn("authStatus", sent)

    def test_a_payment_that_isnt_the_customers_is_never_named(self):
        _, reply = self.post("/api/contact/chat", token=self.verified, page="card_dispute", paymentId="TXN-9999-x")
        self.assertEqual(reply["opener"], "I'd like to dispute a card payment.")
        self.assertEqual(self.attributes()["handoverSummary"], "Wants to dispute a card payment.")

    def test_any_other_page_is_aria_on_its_own_and_the_browser_cant_name_the_customer(self):
        self.post("/api/contact/chat", token=self.demo, page="accounts", customerId="CUST-002", LoA="3")
        self.assertEqual(self.attributes(), {"entry": "banking_app", "appPage": "accounts"})
        self.post("/api/contact/chat", token=self.demo, page="nonsense")
        self.assertEqual(self.attributes()["appPage"], "home")

    def test_signed_in_every_page_starts_a_verified_contact_with_its_own_context(self):
        pages = {"home": {}, "accounts": {}, "cards": {}, "help": {}, "money_hub": {"view": "in"},
                 "card_dispute": {}, "mortgage": {"stage": "about_you", "applicationId": APP_ID}}
        for page, extra in pages.items():
            for kind in ("chat", "call"):
                status, _ = self.post(f"/api/contact/{kind}", token=self.verified, page=page, **extra)
                self.assertEqual(status, 200, page)
                sent = self.attributes()
                self.assertEqual(sent.get("customerId"), JAMES, f"{page} {kind}: who it is")
                if page != "mortgage":            # the mortgage assistant (Point B) takes customerId, not ARIA's fields
                    self.assertEqual((sent["authStatus"], sent["LoA"]), ("authenticated", "2"), f"{page} {kind}")
                context = {"money_hub": ("moneyHubView", "in"), "mortgage": ("stage", "about_you")}.get(page, ("appPage", page))
                self.assertEqual(sent.get(context[0]), context[1], f"{page} {kind}: the page's context")

    def test_each_page_opens_a_chat_saying_where_the_customer_is_except_home(self):
        expected = {"home": "", "accounts": "my accounts", "cards": "my cards and card payments", "help": "Help page",
                    "money_hub": "Money Hub page"}
        for page, words in expected.items():
            _, reply = self.post("/api/contact/chat", token=self.verified, page=page, view="out")
            if words:
                self.assertIn(words, reply["opener"], page)
            else:
                self.assertEqual(reply["opener"], "", "Home: ARIA opens with what she knows about the customer")

    def test_the_apps_own_demo_link_is_signed_in_unless_asked_otherwise(self):
        deploy = (APP / "scripts" / "deploy_banking_app.sh").read_text()
        self.assertIn("VERIFIED_DEMO=true", deploy)
        self.assertIn("--unverified-demo) VERIFIED_DEMO=false", deploy)

    def test_nothing_starts_without_a_live_link(self):
        self.assertEqual(self.post("/api/contact/call", token="made-up", page="home")[0], 403)
        self.assertEqual(self.connect.calls, [])


class Partners(Base):

    def setUp(self):
        super().setUp()
        partners.MORTGAGE_FUNCTION, partners.DISPUTE_FUNCTION = "mortgage-livesync-api", "aria-card-dispute"

    def tearDown(self):
        partners.MORTGAGE_FUNCTION = partners.DISPUTE_FUNCTION = ""
        super().tearDown()

    def test_mortgage_page_operations_use_the_iam_door_with_only_known_fields(self):
        fake = FakeLambda({"statusCode": 200, "body": json.dumps({"ok": True, "reference": "MR-1"})})
        partners._lambda = fake
        status, reply = self.post("/api/mortgage/submit", token=self.verified, applicationId=APP_ID, productId="FX5-NF",
                                  dipDecision="accept", declared=True, documents=["payslips", "../etc/passwd"], extra="x")
        self.assertEqual((status, reply["reference"]), (200, "MR-1"))
        function, event = fake.invoked[0]
        self.assertEqual((function, event["operation"]), ("mortgage-livesync-api", "submitApplication"))
        self.assertEqual(event["payload"]["documents"], ["payslips"])
        self.assertNotIn("extra", event["payload"])
        self.post("/api/mortgage/help-code", token=self.verified, applicationId=APP_ID, stage="documents")
        self.assertEqual(fake.invoked[-1][1], {"operation": "createHelpCode",
                                               "payload": {"applicationId": APP_ID, "stage": "documents"}})

    def test_only_the_mortgage_page_operations_can_be_reached(self):
        with self.assertRaises(partners.PartnerError):
            partners.mortgage("runDecisionInPrinciple", {})
        self.assertEqual(app.lambda_handler(http("POST", "/api/mortgage/anything", {"token": self.verified}), None)["statusCode"], 404)

    def test_the_dispute_form_calls_go_to_the_dispute_service_as_its_page_makes_them(self):
        fake = FakeLambda({"statusCode": 200, "body": json.dumps({"sessionId": "s-1"})})
        partners._lambda = fake
        status, reply = self.post("/api/dispute/screen/open", token=self.verified, linkToken="lt-1", customerId="CUST-002")
        self.assertEqual((status, reply["sessionId"]), (200, "s-1"))
        function, event = fake.invoked[0]
        self.assertEqual(function, "aria-card-dispute")
        self.assertEqual(event["rawPath"], "/api/screen/open")
        self.assertEqual(json.loads(event["body"]), {"linkToken": "lt-1"}, "nothing else from the browser")
        self.assertEqual(self.post("/api/dispute/screen/create", token=self.verified)[0], 404)

    def test_a_partner_refusal_is_a_plain_message(self):
        partners._lambda = FakeLambda({"statusCode": 410, "body": json.dumps({"error": "link_expired", "message": "That link has expired."})})
        status, reply = self.post("/api/dispute/screen/open", token=self.verified, linkToken="old")
        self.assertEqual((status, reply["error"], reply["message"]), (410, "link_expired", "That link has expired."))

    def test_without_partner_settings_the_pages_still_work(self):
        partners.MORTGAGE_FUNCTION = ""
        status, reply = self.post("/api/mortgage/config", token=self.verified)
        self.assertEqual(status, 200)
        self.assertFalse(reply["configured"])
        self.assertEqual(len(reply["products"]), 5)
        self.assertEqual(self.post("/api/mortgage/help-code", token=self.verified, applicationId=APP_ID, stage="about_you")[0], 503)


class Disputes(Base):
    """The customer's disputes, and the dispute form opening in the app during its own conversation."""

    def setUp(self):
        super().setUp()
        import dispute_model
        from bankapp import disputes
        from dispute_service import DisputeService
        from dispute_store import MemoryStore as DisputeMemory
        self.clock = [NOW]
        self.disputes = disputes
        disputes._service = DisputeService(DisputeMemory(lambda: self.clock[0]), lambda: self.clock[0],
                                           page_url="https://disputes.example")
        self.service = disputes._service
        payment = next(t for t in dispute_model.card_transactions(JAMES) if "ELECTROWORLD" in t["merchant"])
        self.dispute = self.service.start_card_dispute(JAMES, payment["transaction_id"], "merchant")["dispute_id"]
        began = __import__("datetime").datetime.fromtimestamp(NOW - 60, __import__("datetime").timezone.utc)
        self.connect.describe_contact = lambda InstanceId, ContactId: {"Contact": {"Id": ContactId, "InitiationTimestamp": began}}

    def tearDown(self):
        self.disputes._service = None
        super().tearDown()

    def start_call(self, token=None):
        _, started = self.post("/api/contact/call", token=token or self.verified, page="card_dispute")
        return started["contactId"]

    def complete(self):
        self.service.update_card_dispute(JAMES, self.dispute, {"reason": "goods_not_received", "contactedMerchant": "yes",
                                                                 "narrative": "It never arrived."})

    # ── the customer submits their own dispute (the dispute service's rule R11) ──

    def test_a_complete_draft_can_be_submitted_by_the_customer_from_the_list(self):
        _, listed = self.post("/api/disputes", token=self.verified)
        row = next(d for d in listed["disputes"] if d["disputeId"] == self.dispute)
        self.assertFalse(row["canSubmit"], "not until nothing is missing")
        self.assertTrue(row["transactionId"], "so an unfinished one can go back to the assistant with its payment")
        self.assertEqual(self.post("/api/disputes/submit", token=self.verified, disputeId=self.dispute)[1]["error"],
                         "incomplete")
        self.complete()
        _, listed = self.post("/api/disputes", token=self.verified)
        self.assertTrue(next(d for d in listed["disputes"] if d["disputeId"] == self.dispute)["canSubmit"])
        status, done = self.post("/api/disputes/submit", token=self.verified, disputeId=self.dispute)
        self.assertEqual((status, done["dispute"]["status"], done["dispute"]["canSubmit"]), (200, "submitted", False))
        stored = self.service.store.get(f"dispute#{self.dispute}")
        self.assertEqual((stored["submittedBy"], stored["customerConfirmation"]["source"]),
                         ("customer", "customer_submitted_app"))

    def test_only_a_verified_customer_submits_and_only_their_own(self):
        self.complete()
        status, reply = self.post("/api/disputes/submit", token=self.demo, disputeId=self.dispute)
        self.assertEqual((status, reply["error"]), (403, "not_verified"))
        sarah = money_api.hub.mint_link("CUST-002", "2").split("#k=")[1]
        self.assertEqual(self.post("/api/disputes/submit", token=sarah, disputeId=self.dispute)[1]["error"],
                         "dispute_not_found")
        self.assertEqual(self.service.store.get(f"dispute#{self.dispute}")["status"], "draft")

    def test_the_form_can_be_submitted_from_the_app_as_its_page_makes_the_call(self):
        self.assertIn("submit", __import__("bankapp.partners", fromlist=["x"]).DISPUTE_SCREEN_ROUTES)
        form = (APP / "web" / "dispute" / "form.js").read_text()
        self.assertIn("api('/dispute/screen/submit', { sessionId })", form)
        self.assertIn("if (!event.isTrusted) return; // only the customer's own click submits", form)

    def test_a_call_from_the_money_hub_page_is_marked_as_this_apps_so_the_form_opens_here(self):
        self.post("/api/contact/call", token=self.verified, page="money_hub", view="out")
        self.assertEqual(self.connect.calls[-1][1]["Attributes"]["appPage"], "money_hub")

    def test_the_customers_disputes_are_listed_newest_first(self):
        status, reply = self.post("/api/disputes", token=self.verified)
        self.assertEqual(status, 200)
        self.assertEqual([d["disputeId"] for d in reply["disputes"]], [self.dispute])
        self.assertEqual(reply["disputes"][0]["merchant"], "ELECTROWORLD ONLINE")
        self.assertTrue(reply["disputes"][0]["open"])

    def test_the_form_counts_as_sent_only_once_the_assistant_sends_it_during_this_call(self):
        contact = self.start_call()
        _, live = self.post("/api/disputes/live", token=self.verified, contactId=contact)
        self.assertEqual((live["dispute"]["disputeId"], live["formSent"]), (self.dispute, False))
        self.service.mark_link_sent(self.dispute, "text")          # the dispute assistant texts its form
        _, live = self.post("/api/disputes/live", token=self.verified, contactId=contact)
        self.assertTrue(live["formSent"])

    def test_a_form_sent_before_this_call_doesnt_open_by_itself(self):
        self.clock[0] = NOW - 3600
        self.service.mark_link_sent(self.dispute, "text")          # an hour before this call began
        self.clock[0] = NOW
        contact = self.start_call()
        self.assertFalse(self.post("/api/disputes/live", token=self.verified, contactId=contact)[1]["formSent"])

    def test_how_it_works_shows_this_conversations_dispute_by_its_stage_only(self):
        os.environ["FLOW_VIEW"] = "on"
        self.connect.get_contact_attributes = lambda InstanceId, InitialContactId: {"Attributes": {"entry": "aria"}}
        contact = self.start_call()
        _, found = self.post("/api/contact/journey", token=self.verified, contactId=contact)
        self.assertEqual((found["specialist"], found["aria"]), ("card_dispute", False), "straight to the specialist")
        self.assertEqual(found["dispute"], {"status": "started", "formSent": False})
        self.service.mark_link_sent(self.dispute, "text")
        self.assertTrue(self.post("/api/contact/journey", token=self.verified, contactId=contact)[1]["dispute"]["formSent"])
        self.complete()
        self.post("/api/disputes/submit", token=self.verified, disputeId=self.dispute)
        self.assertEqual(self.post("/api/contact/journey", token=self.verified, contactId=contact)[1]["dispute"]["status"],
                         "submitted", "a submitted dispute still shows, though it's no longer open")
        later = __import__("datetime").datetime.fromtimestamp(NOW + 60, __import__("datetime").timezone.utc)
        self.connect.describe_contact = lambda InstanceId, ContactId: {"Contact": {"Id": ContactId, "InitiationTimestamp": later}}
        self.assertNotIn("dispute", self.post("/api/contact/journey", token=self.verified, contactId=contact)[1],
                         "a dispute untouched since before this conversation isn't this conversation's")

    def test_the_form_opens_joined_to_this_call(self):
        contact = self.start_call()
        status, opened = self.post("/api/disputes/open", token=self.verified, contactId=contact, disputeId=self.dispute)
        self.assertEqual(status, 200)
        screen = self.service.screen_status(opened["sessionId"])
        self.assertEqual((screen["state"], screen["contactId"]), ("form", contact), "the form follows this call (Live Sync)")
        self.assertTrue(self.service.store.get(f"dispute#{self.dispute}")["screenAttached"], "the assistant sees it's watched")

    def test_only_this_links_own_conversation_and_own_dispute(self):
        contact = self.start_call()
        other = money_api.hub.mint_link("CUST-002", "2").split("#k=")[1]
        for token, contact_id in ((other, contact), (self.verified, "33333333-2222-4333-8444-555555555555")):
            self.assertEqual(self.post("/api/disputes/open", token=token, contactId=contact_id, disputeId=self.dispute)[0], 404)
            self.assertEqual(self.post("/api/disputes/live", token=token, contactId=contact_id)[0], 404)
        sarah = self.start_call(token=other)
        status, reply = self.post("/api/disputes/open", token=other, contactId=sarah, disputeId=self.dispute)
        self.assertEqual((status, reply["error"]), (404, "dispute_not_found"), "never another customer's dispute")

    def test_without_the_dispute_service_the_pages_still_work(self):
        self.disputes._service = None
        self.disputes.TABLE = ""
        status, reply = self.post("/api/disputes", token=self.verified)
        self.assertEqual((status, reply["error"]), (503, "disputes_unavailable"))


class EachAccountHasItsOwnPage(Base):
    """19 Oct: every account opened the same page, showing the current account's card payments under the saver."""

    def test_the_saver_shows_only_transfers_to_and_from_the_current_account(self):
        status, reply = self.post("/api/app/accounts", token=self.demo, account="savings")
        self.assertEqual((status, reply["selected"]), (200, "savings"))
        current_ending = next(a["ending"] for a in reply["accounts"] if a["id"] == "current")
        self.assertTrue(reply["recent"], "the saver has movements to show")
        for row in reply["recent"]:
            self.assertEqual(row["category"], "Transfer")
            self.assertIn(row["merchant"], ("FROM CURRENT ACCOUNT", "TO CURRENT ACCOUNT"), "never a merchant")
            self.assertTrue(row["merchantName"].endswith(f"current account ending {current_ending}"))
            self.assertEqual(row["in"], row["amount"] > 0)
        dates = [row["date"] for row in reply["recent"]]
        self.assertEqual(dates, sorted(dates, reverse=True), "newest first")

    def test_the_current_account_shows_its_payments_and_is_the_default(self):
        _, chosen = self.post("/api/app/accounts", token=self.demo, account="current")
        _, plain = self.post("/api/app/accounts", token=self.demo)
        _, odd = self.post("/api/app/accounts", token=self.demo, account="../mortgage")
        self.assertEqual((chosen["selected"], plain["selected"], odd["selected"]), ("current", "current", "current"))
        self.assertEqual(chosen["recent"], plain["recent"])
        self.assertTrue(any(row["category"] != "Transfer" for row in chosen["recent"]), "card payments, bills, salary")
        _, saver = self.post("/api/app/accounts", token=self.demo, account="savings")
        self.assertNotEqual(chosen["recent"], saver["recent"], "two accounts, two different lists")

    def test_each_account_page_has_its_own_address(self):
        for path in ("/accounts", "/accounts/current", "/accounts/savings"):
            self.assertEqual(app.lambda_handler(http("GET", path), None)["statusCode"], 200, path)
        home_js = (APP / "web" / "pages" / "home.js").read_text()
        self.assertIn("`/accounts/${a.id}`", home_js, "an account's card opens that account")


class Pages(Base):

    def test_home_accounts_and_cards_agree_with_the_money_hub_and_the_dispute_service(self):
        status, me = self.post("/api/app/home", token=self.verified)
        self.assertEqual(status, 200)
        current = next(a for a in me["accounts"] if a["kind"] == "current")
        self.assertEqual(current["balance"], money_api.hub.overview(JAMES)["balance"])
        self.assertEqual(me["firstName"], "James")
        self.assertTrue(me["talk"])
        _, cards = self.post("/api/app/cards", token=self.verified)
        self.assertEqual([c["ending"] for c in cards["cards"]], ["4821", "2291"])
        self.assertEqual(cards["payments"][0]["merchant"], "AMAZON.CO.UK")

    def test_money_hub_calls_are_the_money_hubs_own(self):
        status, reply = self.post("/api/hub", token=self.verified)
        self.assertEqual(status, 200)
        self.assertIn("monthlySpending", reply)

    def test_every_app_address_serves_the_app_and_files_only_from_its_folder(self):
        for path in sorted(app.APP_PATHS):
            self.assertEqual(app.lambda_handler(http("GET", path), None)["statusCode"], 200, path)
        for path in ("/assets/app.js", "/assets/mortgage/screenHelp.js", "/assets/widget/talk.js", "/assets/styles.css"):
            self.assertEqual(app.lambda_handler(http("GET", path), None)["statusCode"], 200, path)
        for path in ("/assets/../api/banking_api.py", "/assets/vendor-src/package.json", "/assets/x.py", "/admin",
                     "/vendor/touchpoint/../../app.js"):
            self.assertEqual(app.lambda_handler(http("GET", path), None)["statusCode"], 404, path)

    def test_the_policy_allows_calls_the_face_and_live_sync_and_nothing_inline(self):
        policy = app.lambda_handler(http("GET", "/"), None)["headers"]["content-security-policy"]
        for needed in ("wss://ws.nlu.acxd.connect.", "https://nlu.acxd.connect.", "https://*.chime.aws", "wss://*.daily.co",
                       "script-src 'self' 'wasm-unsafe-eval' https://*.daily.co", "style-src 'self';"):
            self.assertIn(needed, policy)
        self.assertNotIn("unsafe-inline", policy)
        self.assertNotIn("'unsafe-eval'", policy)

    def test_the_page_writes_text_and_never_lets_the_assistant_submit(self):
        sources = {p.name: p.read_text() for p in (APP / "web").rglob("*.js")
                   if p.is_file() and not {"vendor", "vendor-src"} & set(p.parts)}
        for name, source in sources.items():
            self.assertNotIn("innerHTML", source, name)
            self.assertNotIn("insertAdjacentHTML", source, name)
        actions = sources["actions.js"]
        for banned in ("submit_application", "tick_declaration", "consent"):
            self.assertNotIn(banned, actions)
        apply = sources["apply.js"]
        self.assertIn("declaredByClick = e.isTrusted", apply, "only the customer's own click ticks the declaration")
        self.assertIn("input: 'external'", apply, "Touchpoint binds headless to the widget's own contact")

    def test_every_script_the_app_loads_later_is_one_it_serves(self):
        """import(), worklets and the Touchpoint path: each must be an address this Lambda answers (a wrong one only
        shows when a call or chat starts)."""
        import re
        found = []
        for source in (APP / "web").rglob("*.js"):
            if not source.is_file() or {"vendor", "vendor-src"} & set(source.parts):
                continue
            text = source.read_text()
            found += re.findall(r"import\('(/[^']+)'\)|addModule\('(/[^']+)'\)|TOUCHPOINT = '(/[^']+)'", text)
        paths = sorted({p for groups in found for p in groups if p})
        self.assertIn("/assets/vendor/chime.js", paths)
        for path in paths:
            if path.startswith("/vendor/touchpoint/"):
                self.assertRegex(path.removeprefix("/vendor/touchpoint/"), app.TOUCHPOINT_FILE)
                continue
            self.assertTrue(path.startswith("/assets/"), path)
            name = path.removeprefix("/assets/")
            self.assertRegex(name, app.ASSET)
            if not name.startswith("vendor/"):                 # vendor/ is built by scripts/build_vendor.sh
                self.assertTrue((APP / "web" / name).is_file(), f"{path} is loaded but there's no web/{name}")

    def test_a_call_never_hangs_and_the_face_waits_for_the_call(self):
        talk = (APP / "web" / "widget" / "talk.js").read_text()
        started = talk.split("audioVideoDidStart: () => {")[1].split("audioVideoDidStop")[0]
        self.assertIn("videoOn()", started, "the face starts only once the call's audio has connected")
        self.assertNotIn("if (audioContext) videoOn();", talk, "never alongside a call that is still connecting")
        self.assertIn("CONNECT_WAIT_MS", talk)
        self.assertIn("The call couldn\\'t connect. A VPN or work network can block calls: try another network, or use Chat.", talk)
        self.assertNotIn("carries on as normal", talk, "never claim a call that may not have connected carries on")

    def test_the_dispute_link_opens_in_the_app_only_from_the_dispute_pages_address(self):
        talk = (APP / "web" / "widget" / "talk.js").read_text()
        self.assertIn("words.indexOf(disputePagesUrl)", talk)
        self.assertIn("#k=([A-Za-z0-9_-]{16,128})", talk)


class FakeContact(FakeConnect):
    """Connect's record of a contact, as the flow view reads it."""

    def __init__(self, contact=None, attributes=None):
        super().__init__()
        self.contact, self.attributes = contact or {}, attributes or {}
        self.updated = []

    def update_contact_attributes(self, InstanceId, InitialContactId, Attributes):
        self.updated.append(Attributes)
        self.attributes = {**self.attributes, **Attributes}
        return {}

    def describe_contact(self, InstanceId, ContactId):
        return {"Contact": {"Id": ContactId, **self.contact}}

    def get_contact_attributes(self, InstanceId, InitialContactId):
        return {"Attributes": self.attributes}


class FakeQConnect:
    def __init__(self):
        self.updates = []

    def update_session_data(self, assistantId, sessionId, data):
        self.updates.append((assistantId, sessionId, {d["key"]: d["value"]["stringValue"] for d in data}))
        return {}


class PageMoves(Base):
    """Moving page during a conversation: the attributes the flows route on, and ARIA's known contact reason."""

    ARIA = {"WisdomInfo": {"SessionArn": "arn:aws:wisdom:eu-west-2:1:session/assistant-1/session-9"}}

    def setUp(self):
        super().setUp()
        self.connect = money_api._connect = FakeContact(self.ARIA, {"entry": "returned", "appPage": "accounts",
                                                                    "customerId": JAMES, "ariaStarted": "true"})
        self.qconnect = money_api._qconnect = FakeQConnect()
        self.assistant, money_api.ASSISTANT_ID = money_api.ASSISTANT_ID, "assistant-1"
        _, started = self.post("/api/contact/chat", token=self.verified, page="accounts")
        self.contact = started["contactId"]

    def tearDown(self):
        money_api._qconnect = None
        money_api.ASSISTANT_ID = self.assistant
        super().tearDown()

    def test_moving_to_the_money_hub_tells_aria_and_the_bridge_where_they_are(self):
        status, reply = self.post("/api/contact/page", token=self.verified, contactId=self.contact, page="money_hub", view="goals")
        self.assertEqual((status, reply["ariaTold"]), (200, True))
        self.assertEqual(self.connect.updated[-1], {"appPage": "money_hub", "moneyHubView": "goals"})
        assistant, session, said = self.qconnect.updates[-1]
        self.assertEqual((assistant, session), ("assistant-1", "session-9"))
        self.assertTrue(said["contactReasonSummary"].startswith("Moved to Money Hub:"))
        self.assertIn("Goals tab", said["contactReasonSummary"])
        self.assertEqual(said["topContactReasonCategory"], "money_hub")

    def test_moving_to_the_mortgage_form_sets_what_its_hand_over_reads(self):
        self.post("/api/contact/page", token=self.verified, contactId=self.contact, page="mortgage", stage="property_loan",
                  applicationId=APP_ID)
        self.assertEqual(self.connect.updated[-1], {"appPage": "mortgage", "applicationId": APP_ID, "stage": "property_loan"},
                         "decideHandback routes appPage=mortgage to the form; the mortgage flow reads the application")
        self.assertTrue(self.qconnect.updates[-1][2]["contactReasonSummary"].startswith("Moved to Mortgage application:"))

    def test_a_chosen_payment_is_named_from_the_customers_own_payments(self):
        payment = home.cards(JAMES)["payments"][0]
        self.post("/api/contact/page", token=self.verified, contactId=self.contact, page="card_dispute", paymentId=payment["id"])
        self.assertIn(payment["merchant"], self.qconnect.updates[-1][2]["contactReasonSummary"])

    def test_a_page_move_never_changes_how_the_contact_came_in_or_who_it_is(self):
        for page in ("home", "accounts", "cards", "money_hub", "mortgages", "help", "card_dispute"):
            self.post("/api/contact/page", token=self.verified, contactId=self.contact, page=page)
            for kept in ("entry", "customerId", "authStatus", "LoA", "handbackRoute", "ariaStarted", "handoverSummary"):
                self.assertNotIn(kept, self.connect.updated[-1], (page, kept))
        self.assertEqual(self.connect.attributes["entry"], "returned")

    def test_only_this_links_own_conversation_and_a_real_page(self):
        other = money_api.hub.mint_link("CUST-002", "2").split("#k=")[1]
        self.assertEqual(self.post("/api/contact/page", token=other, contactId=self.contact, page="cards")[0], 404)
        self.assertEqual(self.post("/api/contact/page", token=self.verified, contactId=self.contact, page="admin")[1]["error"],
                         "bad_request")
        self.assertEqual(self.post("/api/contact/page", token=self.verified, contactId=self.contact, page="mortgage",
                                   stage="hacking", applicationId=APP_ID)[0], 400)

    def test_before_aria_has_a_session_only_the_attributes_change(self):
        self.connect.contact = {}
        reply = self.post("/api/contact/page", token=self.verified, contactId=self.contact, page="cards")[1]
        self.assertEqual((reply["ariaTold"], self.qconnect.updates), (False, []))


class BackToAria(Base):
    """22 Oct: back from the dispute assistant on a chat, ARIA waited for the customer to type and, when they did, still
    thought they were with that assistant. The widget now gives her the note as a message when her bot block starts."""

    def setUp(self):
        super().setUp()
        self.connect = money_api._connect = FakeContact({}, {"entry": "returned", "returnedFrom": "card_dispute",
                                                             "returnIntent": "help",
                                                             "returnSummary": "Wants a joint account; dispute submitted."})
        self.contact = self.post("/api/contact/chat", token=self.verified, page="cards")[1]["contactId"]

    def test_the_note_is_the_known_contact_reason_aria_acts_on_once_per_return(self):
        status, reply = self.post("/api/contact/returned", token=self.verified, contactId=self.contact)
        self.assertEqual((status, reply["note"]), (200, "Back from card dispute: Wants a joint account; dispute submitted."))
        self.assertEqual(self.post("/api/contact/returned", token=self.verified, contactId=self.contact)[1]["key"], reply["key"],
                         "the same return: the widget sends it once")
        self.connect.attributes["returnSummary"] = "Wants a mortgage."
        self.assertNotEqual(self.post("/api/contact/returned", token=self.verified, contactId=self.contact)[1]["key"], reply["key"])

    def test_a_colleague_needed_return_carries_the_reason(self):
        self.connect.attributes.update(returnIntent="escalate", returnReason="dispute_ready_for_review")
        note = self.post("/api/contact/returned", token=self.verified, contactId=self.contact)[1]["note"]
        self.assertEqual(note, "Back from card dispute: Colleague needed (dispute_ready_for_review): Wants a joint account; dispute submitted.")

    def test_nothing_to_send_unless_the_chat_came_back_and_only_for_this_links_own_chat(self):
        self.connect.attributes = {"entry": "banking_app", "appPage": "cards"}
        self.assertEqual(self.post("/api/contact/returned", token=self.verified, contactId=self.contact)[1], {"note": "", "key": ""})
        other = money_api.hub.mint_link("CUST-002", "2").split("#k=")[1]
        self.assertEqual(self.post("/api/contact/returned", token=other, contactId=self.contact)[0], 404)

    def test_the_note_matches_the_session_injector_s_words(self):
        sys.path.insert(0, str(ROOT / "scripts" / "lambdas"))
        try:
            import session_injector_qconnect as injector
        except Exception:                                   # the injector needs boto3 at import
            self.skipTest("injector not importable here")
        for attrs in ({"entry": "returned", "returnedFrom": "mortgage", "returnIntent": "help", "returnSummary": "Nothing else: saved at Property and loan."},
                      {"entry": "returned", "returnedFrom": "card_dispute", "returnIntent": "escalate", "returnReason": "vulnerability",
                       "returnSummary": "Upset; bereavement."}):
            expected = injector._returned_reason_vars(attrs["entry"], attrs["returnedFrom"], attrs["returnSummary"],
                                                      attrs["returnIntent"], attrs.get("returnReason", ""), "")["contactReasonSummary"]
            self.assertEqual(journeys.return_note(attrs), expected)

    def test_the_widget_sends_it_when_aria_s_bot_block_starts_and_hides_it(self):
        talk = (APP / "web" / "widget" / "talk.js").read_text()
        self.assertIn("if (live && live.opened && !(item.Content || '').trim()) sendReturnNote();", talk)
        self.assertIn("back.key !== current.returnKey", talk, "once per return")
        self.assertIn("if (item.ParticipantRole === 'CUSTOMER' && isReturnNote(item.Content)) return;", talk)
        for label in journeys.RETURN_LABELS.values():
            self.assertIn(f"'{label}:'", talk)


class HowItWorks(Base):
    """The demo's "how it works" view: on and off at run time, and facts read from Connect's own record."""

    ARIA = {"WisdomInfo": {"SessionArn": "arn:aws:wisdom:eu-west-2:1:session/a/s"}}

    def start_chat(self, contact=None, attributes=None):
        self.connect = money_api._connect = FakeContact(contact, attributes)
        status, started = self.post("/api/contact/chat", token=self.verified, page="home")
        self.assertEqual(status, 200)
        return started["contactId"]

    def test_it_is_off_unless_the_setting_says_on_and_a_missing_setting_is_off(self):
        self.assertFalse(self.post("/api/app/home", token=self.verified)[1]["flowView"])
        self.ssm.value = "off"
        flowview._cached["at"] = -1e12
        self.assertFalse(flowview.enabled())
        self.ssm.value = "on"
        flowview._cached["at"] = -1e12
        self.assertTrue(self.post("/api/app/home", token=self.verified)[1]["flowView"])

    def test_turning_it_off_needs_no_redeploy_and_shows_within_the_cache_time(self):
        self.ssm.value = "on"
        clock = [1000.0]
        self.assertTrue(flowview.enabled(lambda: clock[0]))
        self.ssm.value = "off"
        clock[0] += flowview.CACHE_SECONDS - 1
        self.assertTrue(flowview.enabled(lambda: clock[0]), "read at most every CACHE_SECONDS")
        clock[0] += 2
        self.assertFalse(flowview.enabled(lambda: clock[0]))
        self.assertEqual(self.ssm.reads, 2)

    def test_the_local_preview_can_turn_it_on_without_aws(self):
        os.environ["FLOW_VIEW"] = "on"
        self.assertTrue(flowview.enabled())
        self.assertEqual(self.ssm.reads, 0)

    def test_each_hand_over_the_flow_writes_names_its_specialist(self):
        cases = [({"entry": "card_dispute", "appPage": "card_dispute"}, "card_dispute", "connect"),
                 ({"entry": "aria", "handbackRoute": "card_dispute"}, "card_dispute", "connect"),
                 ({"entry": "money_hub", "handbackRoute": "card_dispute"}, "card_dispute", "connect"),
                 ({"entry": "web_widget"}, "mortgage", "connect"),
                 ({"entry": "phone", "handbackRoute": "mortgage_livesync"}, "mortgage", "connect"),
                 ({"entry": "web_widget", "appPage": "mortgage", "handbackRoute": "mortgage_form"}, "mortgage", "connect"),
                 ({"entry": "returned", "returnedFrom": "card_dispute", "handbackRoute": "returned"}, "", ""),
                 ({"entry": "money_hub", "appPage": "money_hub"}, "", ""),      # the page alone proves nothing
                 ({"entry": "banking_app", "appPage": "home"}, "", ""),
                 ({"entry": "banking_app", "handbackRoute": "end"}, "", "")]
        for attributes, who, basis in cases:
            found = flowview.state(self.ARIA, attributes)
            self.assertEqual((found["specialist"], found["basis"]), (who, basis), attributes)

    def test_back_from_the_dispute_assistant_is_aria_again(self):
        found = flowview.state(self.ARIA, {"entry": "returned", "returnedFrom": "card_dispute", "handbackRoute": "returned",
                                           "appPage": "card_dispute"})
        self.assertEqual((found["specialist"], found["returned"], found["aria"], found["returnedFrom"]), ("", True, True, "card_dispute"))
        mortgage = flowview.state(self.ARIA, {"entry": "returned", "returnedFrom": "mortgage", "handbackRoute": "returned"})
        self.assertEqual((mortgage["specialist"], mortgage["returnedFrom"]), ("", "mortgage"))
        self.assertFalse(flowview.state(self.ARIA, {"entry": "aria"})["returned"])

    def test_a_colleague_is_waiting_once_aria_escalates_and_joined_once_connected(self):
        self.assertEqual(flowview.state({}, {"handbackRoute": "human"})["colleague"], "waiting")
        joined = flowview.state({"AgentInfo": {"ConnectedToAgentTimestamp": "2026-10-20T10:00:00Z"}}, {"handbackRoute": "human"})
        self.assertEqual(joined["colleague"], "joined")
        self.assertEqual(flowview.state({}, {})["colleague"], "")

    def test_aria_ended_and_trouble_come_from_connects_record(self):
        self.assertFalse(flowview.state({}, {})["aria"])
        found = flowview.state({**self.ARIA, "DisconnectTimestamp": "2026-10-20T10:05:00Z"},
                               {"handbackOutcome": "error", "handbackRoute": "end"})
        self.assertEqual((found["aria"], found["ended"], found["trouble"]), (True, True, True))

    def test_the_dispute_is_reported_by_its_stage_never_its_details(self):
        found = flowview.state({}, {}, {"status": "submitted", "formSent": True, "merchant": "ELECTROWORLD", "amount": 499})
        self.assertEqual(found["dispute"], {"status": "submitted", "formSent": True})
        self.assertNotIn("dispute", flowview.state({}, {}, {"status": "withdrawn"}))

    def test_the_journey_answers_only_when_on_and_only_for_this_links_own_conversation(self):
        contact = self.start_chat({**self.ARIA}, {"entry": "banking_app", "handbackRoute": "card_dispute"})
        status, reply = self.post("/api/contact/journey", token=self.verified, contactId=contact)
        self.assertEqual((status, reply["error"]), (404, "flow_view_off"))
        os.environ["FLOW_VIEW"] = "on"
        status, reply = self.post("/api/contact/journey", token=self.verified, contactId=contact)
        self.assertEqual(status, 200)
        self.assertEqual((reply["aria"], reply["specialist"]), (True, "card_dispute"))
        other = money_api.hub.mint_link("CUST-002", "2").split("#k=")[1]
        self.assertEqual(self.post("/api/contact/journey", token=other, contactId=contact)[0], 404)
        self.assertEqual(self.post("/api/contact/journey", token=self.verified, contactId="someone-elses")[0], 404)

    def test_the_money_hub_agent_shows_from_the_bridge_s_mark_from_any_page(self):
        start = {"moneyHubStartedAt": 100.0, "moneyHubFinishedAt": 0}
        found = flowview.state(self.ARIA, {"entry": "banking_app", "appPage": "accounts"}, None, start)
        self.assertEqual((found["specialist"], found["basis"], found["moneyHub"], found["back"]), ("money_hub", "connect", "active", ""))
        done = flowview.state(self.ARIA, {"entry": "banking_app"}, None, {**start, "moneyHubFinishedAt": 130.0})
        self.assertEqual((done["specialist"], done["moneyHub"], done["back"]), ("", "done", "money_hub"))
        # A flow transfer (the dispute assistant) outranks a Money Hub stint the bridge never saw end.
        self.assertEqual(flowview.state(self.ARIA, {"entry": "aria", "handbackRoute": "card_dispute"}, None, start)["specialist"],
                         "card_dispute")
        back = flowview.state(self.ARIA, {"entry": "returned", "returnedFrom": "mortgage", "handbackRoute": "returned"})
        self.assertEqual((back["specialist"], back["back"]), ("", "mortgage"))

    def test_the_key_is_the_one_the_money_hub_bridge_writes(self):
        bridge = (ROOT / "connect-money-hub" / "bridge" / "a2a_bridge.py").read_text()
        self.assertIn(f'SPECIALIST_KEY = "{flowview.SPECIALIST_KEY}"', bridge)

    def test_the_journey_reads_the_money_hub_mark_for_this_contact(self):
        os.environ["FLOW_VIEW"] = "on"
        contact = self.start_chat({**self.ARIA}, {"entry": "banking_app", "appPage": "accounts"})
        money_api.hub.store.put(flowview.SPECIALIST_KEY.format(contact_id=contact),
                                {"moneyHubStartedAt": NOW, "moneyHubFinishedAt": 0})
        reply = self.post("/api/contact/journey", token=self.verified, contactId=contact)[1]
        self.assertEqual((reply["specialist"], reply["moneyHub"]), ("money_hub", "active"))

    def test_the_widget_tells_every_moment_and_the_view_never_touches_the_widget(self):
        talk = (APP / "web" / "widget" / "talk.js").read_text()
        view = (APP / "web" / "flowview" / "flowview.js").read_text()
        for moment in ("tell('starting'", "tell('started'", "tell('microphone')", "tell('connecting')",
                       "tell('connected'", "tell('said'", "tell('video'", "tell('colleague')", "tell('ended'"):
            self.assertIn(moment, talk)
        self.assertIn("addEventListener('assistant'", view)
        self.assertIn("const ariaIn = Boolean(f.aria);", view, "ARIA only on Connect's word, never on any answer")
        self.assertIn("    tell('ended', { words });", talk, "a conversation that never got going still ends the view")
        self.assertNotIn("getElementById", view, "the view builds its own elements and never reaches into the widget")
        self.assertNotIn("innerHTML", view)
        self.assertNotIn("style=", view, "the page's policy allows no inline styles")
        app_js = (APP / "web" / "app.js").read_text()
        self.assertIn("if (shared.me.flowView) import('/assets/flowview/flowview.js')", app_js, "loaded only when on")

    def test_the_deploy_script_makes_the_setting_only_if_missing_and_never_overwrites_it(self):
        script = (APP / "scripts" / "deploy_banking_app.sh").read_text()
        made = next(line for line in script.splitlines() if "run aws ssm put-parameter" in line)
        self.assertNotIn("--overwrite", made)
        self.assertLess(script.index("aws ssm get-parameter"), script.index("run aws ssm put-parameter"))
        self.assertIn('"Action": "ssm:GetParameter"', script)
        self.assertIn('"connect:GetContactAttributes"', script)


if __name__ == "__main__":
    unittest.main()
