"""
Tests for chatting and calling from the Money Hub page: who a page contact says
the customer is, what reaches Connect, what reaches the browser, and how the
page context flows through the bridge to the agent. No AWS.
"""

import io
import json
import logging
import sys
import unittest
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[1]
for extra in ("", "api", "bridge", "agent"):
    sys.path.insert(0, str(FOLDER / extra) if extra else str(FOLDER))

import money_api as api  # noqa: E402
from moneyhub import contact  # noqa: E402
from moneyhub.service import MoneyHub  # noqa: E402
from moneyhub.store import MemoryStore  # noqa: E402

JAMES, SARAH = "CUST-001", "CUST-002"
NOW = 1_800_000_000.0


class FakeConnect:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def _reply(self, name, request):
        self.calls.append((name, request))
        if self.fail:
            raise RuntimeError("ThrottlingException")

    def start_web_rtc_contact(self, **request):
        self._reply("call", request)
        return {"ContactId": "c-1", "ParticipantId": "p-1", "ParticipantToken": "pt-secret",
                "ConnectionData": {"Meeting": {"MeetingId": "m-1", "MediaRegion": "eu-west-2",
                                               "MediaPlacement": {"SignalingUrl": "wss://signal.example.chime.aws"}},
                                   "Attendee": {"AttendeeId": "a-1", "JoinToken": "join-secret"}}}

    def start_chat_contact(self, **request):
        self._reply("chat", request)
        return {"ContactId": "c-2", "ParticipantId": "p-2", "ParticipantToken": "pt-chat-secret"}


def http(path, body):
    return {"requestContext": {"http": {"method": "POST"}}, "rawPath": path, "body": json.dumps(body)}


class PageContacts(unittest.TestCase):

    def setUp(self):
        api.hub = MoneyHub(MemoryStore(lambda: NOW), lambda: NOW, page_url="https://hub.example")
        api.CONNECT_INSTANCE_ID, api.CONTACT_FLOW_ID = "inst-1", "flow-1"
        self.connect = FakeConnect()
        api._connect = self.connect
        self.verified = api.hub.mint_link(JAMES, "2").split("#k=")[1]
        self.demo = api.hub.mint_link(JAMES).split("#k=")[1]

    def tearDown(self):
        api.CONNECT_INSTANCE_ID = api.CONTACT_FLOW_ID = ""
        api._connect = None

    def post(self, path, **body):
        reply = api.lambda_handler(http(path, body), None)
        return reply["statusCode"], json.loads(reply["body"])

    def test_a_link_from_a_level_2_contact_starts_a_verified_contact(self):
        status, reply = self.post("/api/contact/call", token=self.verified, view="expected")
        self.assertEqual(status, 200)
        name, request = self.connect.calls[0]
        self.assertEqual((name, request["InstanceId"], request["ContactFlowId"]), ("call", "inst-1", "flow-1"))
        self.assertEqual(request["Attributes"], {"entry": "money_hub", "moneyHubView": "expected",
                                                 "customerId": JAMES, "authStatus": "authenticated",
                                                 "idvStatus": "verified", "LoA": "2", "idvMethod": "money_hub_link"})
        self.assertTrue(reply["verified"])

    def test_a_demo_link_starts_an_anonymous_contact(self):
        self.post("/api/contact/chat", token=self.demo, view="goals")
        attributes = self.connect.calls[0][1]["Attributes"]
        self.assertEqual(attributes, {"entry": "money_hub", "moneyHubView": "goals"},
                         "no customer and no level: ARIA verifies the customer itself")

    def test_the_browser_cannot_choose_the_customer_or_the_level(self):
        self.post("/api/contact/call", token=self.demo, view="<script>", customerId=SARAH, loa="3",
                  authStatus="authenticated", Attributes={"customerId": SARAH})
        attributes = self.connect.calls[0][1]["Attributes"]
        self.assertEqual(attributes, {"entry": "money_hub", "moneyHubView": "out"})
        self.post("/api/contact/call", token=self.verified, customerId=SARAH)
        self.assertEqual(self.connect.calls[1][1]["Attributes"]["customerId"], JAMES)

    def test_a_call_returns_only_what_the_browser_needs_to_join(self):
        _, reply = self.post("/api/contact/call", token=self.verified, view="out")
        self.assertEqual(set(reply), {"contactId", "participantToken", "meeting", "attendee", "region", "verified"})
        self.assertEqual(reply["attendee"]["JoinToken"], "join-secret")
        self.assertEqual(reply["region"], api.REGION)
        self.assertNotIn("AllowedCapabilities", self.connect.calls[0][1], "audio only")

    def test_a_chat_opens_with_a_message_the_page_sends_after_arias_greeting(self):
        _, reply = self.post("/api/contact/chat", token=self.verified, view="transactions")
        request = self.connect.calls[0][1]
        self.assertEqual(request["SupportedMessagingContentTypes"], ["text/plain", "text/markdown"])
        self.assertNotIn("InitialMessage", request, "not documented to reach a Lex bot; the page sends it instead")
        self.assertEqual(set(reply), {"contactId", "participantToken", "region", "verified"})
        source = (FOLDER / "web" / "talk.js").read_text()
        self.assertIn("I'm on my Money Hub page, on the ${tab} tab", source)
        self.assertIn("keepalive: true", source)

    def test_every_contact_is_a_new_one(self):
        self.post("/api/contact/chat", token=self.verified)
        self.post("/api/contact/chat", token=self.verified)
        tokens = {request["ClientToken"] for _, request in self.connect.calls}
        self.assertEqual(len(tokens), 2)

    def test_without_connect_settings_the_page_offers_no_call_or_chat(self):
        api.CONNECT_INSTANCE_ID = ""
        status, reply = self.post("/api/contact/call", token=self.verified)
        self.assertEqual((status, reply["error"]), (503, "talk_unavailable"))
        _, view = self.post("/api/hub", token=self.verified)
        self.assertFalse(view["talk"])
        api.CONNECT_INSTANCE_ID = "inst-1"
        _, view = self.post("/api/hub", token=self.verified)
        self.assertTrue(view["talk"])

    def test_an_expired_or_made_up_link_starts_nothing(self):
        status, _ = self.post("/api/contact/call", token="made-up")
        self.assertEqual(status, 403)
        self.assertEqual(self.connect.calls, [])

    def test_a_connect_failure_is_a_plain_message_and_logs_no_token(self):
        api._connect = FakeConnect(fail=True)
        logs = io.StringIO()
        handler = logging.StreamHandler(logs)
        logging.getLogger().addHandler(handler)
        try:
            status, reply = self.post("/api/contact/call", token=self.verified)
        finally:
            logging.getLogger().removeHandler(handler)
        self.assertEqual((status, reply["error"]), (502, "talk_failed"))
        self.assertNotIn(self.verified, logs.getvalue())
        self.assertNotIn("CUST-001", logs.getvalue())

    def test_the_policy_allows_chime_and_the_participant_service_and_nothing_inline(self):
        headers = api.lambda_handler({"requestContext": {"http": {"method": "GET"}}, "rawPath": "/"}, None)["headers"]
        policy = headers["content-security-policy"]
        for needed in ("https://*.chime.aws", "wss://*.chime.aws", f"https://participant.connect.{api.REGION}.amazonaws.com",
                       f"wss://*.transport.connect.{api.REGION}.amazonaws.com", "script-src 'self';"):
            self.assertIn(needed, policy)
        self.assertNotIn("unsafe", policy)
        self.assertEqual(headers["permissions-policy"], "microphone=(self), camera=(), geolocation=()")
        talk = api.lambda_handler({"requestContext": {"http": {"method": "GET"}}, "rawPath": "/assets/talk.js"}, None)
        self.assertEqual(talk["statusCode"], 200)

    def test_the_talk_script_writes_text_and_keeps_tokens_out_of_storage(self):
        source = (FOLDER / "web" / "talk.js").read_text()
        for banned in ("innerHTML", "insertAdjacentHTML", "localStorage", "sessionStorage", "eval("):
            self.assertNotIn(banned, source)
        self.assertIn("aws/subscribe", source)


class ContactRules(unittest.TestCase):

    def test_only_level_2_or_above_counts_as_verified(self):
        for loa, verified in (("2", True), ("3", True), ("1", False), ("", False), ("two", False), (None, False)):
            self.assertEqual(contact.verified_level(loa), verified, loa)

    def test_links_record_their_level_and_old_links_have_none(self):
        hub = MoneyHub(MemoryStore(lambda: NOW), lambda: NOW, page_url="https://hub.example")
        token = hub.mint_link(JAMES, " 2 ").split("#k=")[1]
        self.assertEqual(hub.link_session(token), {"customerId": JAMES, "loa": "2"})
        hub.store.put("link#old", {"customerId": JAMES, "expiresAt": NOW + 60})
        self.assertEqual(hub.mint_link(JAMES, "high").split("#k=")[0], "https://hub.example/")
        self.assertEqual(hub.link_session(hub.mint_link(JAMES, "high").split("#k=")[1])["loa"], "")


class ThroughTheBridge(unittest.TestCase):

    def test_the_page_view_and_level_reach_the_agent(self):
        import a2a_bridge as bridge
        import test_bridge as tb
        case = tb.Bridge("test_init_session_is_answered_like_sample_a2")
        case.setUp()
        case.attributes = {**tb.VERIFIED, "entry": "money_hub", "moneyHubView": "goals", "LoA": "2"}
        case.start()
        case.post(tb.turn("How am I doing?"))
        payload = case.calls[0][0]
        self.assertEqual((payload["pageView"], payload["loa"]), ("goals", "2"))
        case.calls.clear()
        case.attributes = {**tb.VERIFIED, "entry": "phone", "moneyHubView": "goals"}
        case.start(context="ctx-2")
        case.post(tb.turn("How am I doing?", context="ctx-2"))
        self.assertEqual(case.calls[0][0]["pageView"], "", "only contacts started from the page carry a view")
        self.assertIsNotNone(bridge)


class InTheAgent(unittest.TestCase):

    def test_the_prompt_knows_the_tab_and_links_carry_the_contacts_level(self):
        from money_tools import Recorder, build_tools
        from prompt import system_prompt
        self.assertIn("on the Goals tab", system_prompt("VOICE", "James", "goals"))
        self.assertNotIn("Money Hub page, on the", system_prompt("VOICE", "James", ""))
        self.assertNotIn("Money Hub page, on the", system_prompt("VOICE", "James", "<x>"))
        hub = MoneyHub(MemoryStore(lambda: NOW), lambda: NOW, page_url="https://hub.example")
        tools = {t.__name__: t for t in build_tools(hub, JAMES, "CHAT", Recorder(), "2")}
        token = tools["get_money_hub_link"]()["link"].split("#k=")[1]
        self.assertEqual(hub.link_session(token)["loa"], "2")


if __name__ == "__main__":
    unittest.main()
