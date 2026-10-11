"""
Unit tests for the ARIA ID&V test harness.

Run from the repository root (no AWS access or extra packages needed):

    python3 -m unittest discover -s connect-idv-test-harness/tests -v

Each test drives the Lambda handler exactly as the contact flow does: one
"start" invocation, then one "step" per keypad entry, feeding the returned
idvState back in as a contact attribute.
"""

import os
import re
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "connect-idv-test-harness" / "lambda"))
sys.path.insert(0, str(ROOT / "scripts" / "lambdas"))

# session_injector_qconnect creates boto3 clients at import time. The tests
# never call AWS, so a stand-in module is enough when boto3 is not installed.
try:
    import boto3  # noqa: F401
except ModuleNotFoundError:
    class _FakeClientError(Exception):
        def __init__(self, response=None, operation_name=""):
            super().__init__(operation_name)
            self.response = response or {}

    class _FakeClient:
        def __getattr__(self, name):
            def call(**kwargs):
                raise _FakeClientError({"Error": {"Code": "ResourceNotFoundException"}}, name)
            return call

    _boto3 = types.ModuleType("boto3")
    _boto3.client = lambda *a, **k: _FakeClient()
    _botocore = types.ModuleType("botocore")
    _config = types.ModuleType("botocore.config")
    _config.Config = lambda **k: None
    _exceptions = types.ModuleType("botocore.exceptions")
    _exceptions.ClientError = _FakeClientError
    sys.modules.update({"boto3": _boto3, "botocore": _botocore,
                        "botocore.config": _config, "botocore.exceptions": _exceptions})

SECRET = "unit-test-secret-0123456789"
os.environ["IDV_TEST_HARNESS_ENABLED"] = "true"
os.environ["IDV_TEST_SIGNING_SECRET"] = SECRET
os.environ.setdefault("AWS_DEFAULT_REGION", "eu-west-2")
os.environ["ASSISTANT_ID"] = "test-assistant"

import aria_idv_test_harness as harness  # noqa: E402
import idv_policy as policy  # noqa: E402
import idv_test_data as data  # noqa: E402
import idv_verifiers as verifiers  # noqa: E402
import session_injector_qconnect as injector  # noqa: E402

JAMES, SARAH, MARGARET, DANIEL, ETHEL = "CUST-001", "CUST-002", "CUST-003", "CUST-004", "CUST-005"


class Call:
    """A simulated contact: remembers attributes between invocations like Connect does."""

    def __init__(self, channel="VOICE", cli="+447911000000", attributes=None, contact_id="contact-1"):
        self.channel, self.cli, self.contact_id = channel, cli, contact_id
        self.attributes = dict(attributes or {})
        self.reply = self._invoke("start")

    def _invoke(self, operation, digits=""):
        event = {"Details": {
            "ContactData": {"ContactId": self.contact_id, "Channel": self.channel,
                            "CustomerEndpoint": {"Address": self.cli}, "Attributes": dict(self.attributes)},
            "Parameters": {"operation": operation, "input": digits}}}
        reply = harness.handler(event, None)
        assert all(isinstance(v, str) for v in reply.values()), "Connect STRING_MAP needs string values"
        self.attributes.update({k: v for k, v in reply.items() if k not in ("action", "prompt")})
        return reply

    def press(self, *entries):
        for digits in entries:
            self.reply = self._invoke("step", digits)
        return self.reply

    def spoken_code(self):
        """The push number or OTP the harness reads out for the tester."""
        match = re.search(r"(?:key|The code is) ((?:\d ?)+)", self.reply["prompt"])
        return match.group(1).replace(" ", "")

    def full_journey(self, line, scenario="1"):
        return self.press("2", line, scenario)


def line_key(customer_id):
    return str(data.customer_ids().index(customer_id) + 1)


SHARED, WITHHELD, INTERNATIONAL = "6", "7", "8"
YES, NO = "1", "2"
GENERAL, FREEZE, STOLEN, BALANCE, ADDRESS, PAYEE, THIRD_PARTY = "1", "2", "3", "4", "5", "6", "7"


class QuickSelectTests(unittest.TestCase):
    """Requirement: pick any injector test customer whatever number you call from."""

    def test_every_injector_customer_is_selectable_from_the_same_cli(self):
        for index, customer in enumerate(data.customer_ids(), start=1):
            reply = Call().press("1", str(index))
            self.assertEqual(reply["action"], "handoff")
            self.assertEqual(reply["customerId"], customer)
            self.assertEqual(reply["authStatus"], "authenticated")
            self.assertIn("TEST_QUICK_SELECT_BYPASS", reply["reasonCodes"])

    def test_menu_is_built_from_the_injector_registry(self):
        prompt = Call().press("1")["prompt"]
        for customer in injector._STUB_CUSTOMERS.values():
            self.assertIn(customer["preferred_name"], prompt)

    def test_quick_select_by_contact_attribute(self):
        reply = Call(attributes={"idvTestCustomerId": MARGARET}).reply
        self.assertEqual((reply["action"], reply["customerId"]), ("handoff", MARGARET))


class OptionA_OwnPhonePush(unittest.TestCase):

    def test_push_with_number_matching_reaches_loa3(self):
        call = Call()
        reply = call.full_journey(line_key(JAMES))
        self.assertIn("Thanks for calling Meridian Bank", reply["prompt"])
        self.assertNotIn("James", reply["prompt"], "no name before verification")
        self.assertEqual(reply["LoA"], "1")
        self.assertEqual(reply["customerId"], "", "candidate is never released below LoA2")

        reply = call.press(ADDRESS)
        self.assertIn("account linked to the number you're calling from", reply["prompt"])
        reply = call.press(YES)
        self.assertIn("notification to your Meridian Bank app", reply["prompt"])
        reply = call.press(call.spoken_code())
        self.assertIn("Thanks, James, that's confirmed", reply["prompt"])
        self.assertEqual((reply["LoA"], reply["idvMethod"], reply["cliRelationship"]), ("3", "push", "MATCH"))
        self.assertEqual(reply["idvDecision"], "PERMIT")
        self.assertIn("NOTIFY_OLD_CHANNEL_24H", reply["idvObligations"])
        self.assertEqual(call.press("2")["customerId"], JAMES)

    def test_push_timeout_falls_back_to_sms_otp_plus_kba(self):
        call = Call()
        call.full_journey(line_key(JAMES))
        call.press(ADDRESS, YES)
        reply = call.press("Timeout")
        self.assertIn("I haven't seen that come through", reply["prompt"])
        self.assertIn("text a six-digit code", reply["prompt"])
        reply = call.press(call.spoken_code())
        self.assertIn("2nd and 5th digits", reply["prompt"])
        self.assertEqual(reply["LoA"], "2")
        reply = call.press("81")   # security number 482916 -> 2nd digit 8, 5th digit 1
        self.assertEqual((reply["LoA"], reply["idvDecision"]), ("3", "PERMIT"))
        self.assertEqual(reply["idvMethod"], "kba+otp_sms")

    def test_wrong_number_then_failed_fallback_fails_without_hints(self):
        call = Call()
        call.full_journey(line_key(JAMES))
        call.press(ADDRESS, YES)
        call.press("0")                       # decline the push
        reply = call.press("000000", "000000")  # two wrong OTPs
        reply = call.press("00", "00") if "2nd and 5th" in reply["prompt"] else reply
        self.assertIn("I wasn't able to confirm it's you", reply["prompt"])
        self.assertEqual(reply["idvDecision"], "DENY")
        for leak in ("code", "security number", "push", "digits"):
            self.assertNotIn(leak, reply["prompt"].split("Test harness:")[0])
        self.assertEqual(call.press("2")["customerId"], "")

    def test_balance_needs_only_one_factor(self):
        call = Call()
        call.full_journey(line_key(ETHEL))    # Ethel has no app
        call.press(BALANCE, YES)
        self.assertIn("text a six-digit code", call.reply["prompt"])
        reply = call.press(call.spoken_code())
        self.assertEqual((reply["LoA"], reply["idvDecision"]), ("2", "PERMIT"))


class OptionB_BorrowedPhone(unittest.TestCase):

    def test_no_answer_drops_candidate_and_verifies_on_claimed_customers_channels(self):
        call = Call()
        call.full_journey(line_key(JAMES))     # the phone belongs to James
        call.press(BALANCE)
        reply = call.press(NO)                 # ...but the caller is Sarah
        self.assertIn("date of birth", reply["prompt"])
        self.assertEqual((reply["cliRelationship"], reply["LoA"]), ("MISMATCH", "0"))
        call.press("22071990")
        reply = call.press("3317")
        self.assertIn("email address we hold", reply["prompt"], "OTP must not go to the phone on the line")
        reply = call.press(call.spoken_code())
        self.assertIn("Thanks, Sarah", reply["prompt"])
        self.assertEqual((reply["LoA"], reply["idvMethod"]), ("2", "otp_email"))
        reply = call.press("2")
        self.assertEqual((reply["customerId"], reply["cliRelationship"]), (SARAH, "MISMATCH"))
        self.assertNotIn("James", " ".join(call.attributes.get(k, "") for k in ("idvSummary", "reasonCodes")))

    def test_email_otp_plus_kba_stays_loa2_so_address_change_is_refused(self):
        call = Call()
        call.full_journey(line_key(JAMES))
        call.press(ADDRESS, NO, "22071990", "3317")
        reply = call.press(call.spoken_code())
        self.assertIn("I wasn't able to confirm it's you", reply["prompt"])
        self.assertEqual((reply["LoA"], reply["idvDecision"]), ("2", "DENY"))

    def test_app_on_second_device_gives_loa3_from_a_borrowed_phone(self):
        call = Call()
        call.full_journey(line_key(SARAH))     # Margaret calls from Sarah's phone
        call.press(ADDRESS, NO, "09111958", "6612")
        self.assertIn("notification to your Meridian Bank app", call.reply["prompt"])
        reply = call.press(call.spoken_code())
        self.assertEqual((reply["LoA"], reply["cliRelationship"]), ("3", "MISMATCH"))

    def test_shared_landline_and_withheld_number_go_straight_to_claimed_identity(self):
        for line in (SHARED, WITHHELD):
            call = Call()
            call.full_journey(line)
            reply = call.press(BALANCE)
            self.assertIn("date of birth", reply["prompt"])
            self.assertEqual(reply["LoA"], "0")

    def test_stolen_phone_is_removed_from_push_targets(self):
        call = Call()
        call.full_journey(line_key(JAMES))     # Sarah on a friend's phone; her own was stolen
        call.press(STOLEN, NO, "22071990")
        reply = call.press("3317")
        self.assertIn("I've frozen your cards", reply["prompt"])
        self.assertEqual(reply["LoA"], "1", "protective action is allowed without verification")
        reply = call.press("1", ADDRESS)
        self.assertNotIn("notification to your", reply["prompt"])
        self.assertIn("email address we hold", reply["prompt"])

    def test_unresolved_claimed_identity_fails_neutrally_after_two_tries(self):
        call = Call()
        call.full_journey(WITHHELD)
        call.press(BALANCE, "01011900", "0000")
        self.assertIn("Let's try once more", call.reply["prompt"])
        reply = call.press("01011900", "0000")
        self.assertIn("I wasn't able to confirm it's you", reply["prompt"])


class OptionC_NetworkSignals(unittest.TestCase):

    def test_sim_swap_disables_otp_and_accepts_only_a_pre_swap_device(self):
        call = Call()
        reply = call.full_journey(line_key(DANIEL))   # SIM swapped 2 days ago, divert on
        self.assertEqual(reply["LoA"], "0", "a high-risk CLI is worth nothing")
        self.assertIn("SIM_SWAP_RECENT", reply["reasonCodes"])
        call.press(PAYEE, YES)
        prompt = call.reply["prompt"]
        self.assertIn("I need to confirm this through your Meridian Bank app", prompt)
        for secret_signal in ("SIM", "swap", "divert", "risk"):
            self.assertNotIn(secret_signal, prompt.split("Test harness:")[0])
        reply = call.press(call.spoken_code())
        self.assertEqual((reply["LoA"], reply["idvDecision"]), ("3", "PERMIT"))
        self.assertIn("HOLD_72H", reply["idvObligations"])
        self.assertIn("has anyone asked you to move money", reply["prompt"])

    def test_high_risk_without_trusted_device_raises_a_fraud_case(self):
        call = Call()
        call.full_journey(line_key(DANIEL), scenario="3")   # app unreachable too
        reply = call.press(PAYEE, YES)
        self.assertIn("I wasn't able to confirm it's you", reply["prompt"])
        self.assertNotIn("code", reply["prompt"].split("Test harness:")[0])
        self.assertIn("FRAUD_CASE_RAISED", reply["reasonCodes"])

    def test_high_risk_still_allows_protective_action(self):
        call = Call()
        call.full_journey(line_key(JAMES), scenario="2")
        reply = call.press(FREEZE, YES)
        self.assertIn("I've frozen your cards", reply["prompt"])

    def test_risk_raises_the_level_needed_for_a_balance(self):
        self.assertEqual(policy.required_loa("balance", "LOW")[0], 2)
        self.assertEqual(policy.required_loa("balance", "HIGH")[0], 3)

    def test_third_party_pressure_gets_a_route_not_an_exception(self):
        call = Call()
        call.full_journey(line_key(JAMES))
        reply = call.press(THIRD_PARTY)
        self.assertIn("I can only make changes with the account holder", reply["prompt"])
        self.assertIn("THIRD_PARTY_CLAIM", reply["reasonCodes"])
        self.assertEqual(reply["LoA"], "1")


class OptionD_AppToCallHandoff(unittest.TestCase):

    def test_in_app_call_token_inherits_loa3_with_no_questions(self):
        token = verifiers.mint_token("call", JAMES, SECRET, loa=3)
        call = Call(attributes={"idvCallToken": token})
        self.assertIn("Hi James, thanks for calling from the app. You're already verified",
                      call.reply["prompt"])
        self.assertEqual((call.reply["LoA"], call.reply["idvMethod"]), ("3", "app_handoff"))
        self.assertEqual(call.press(ADDRESS)["idvDecision"], "PERMIT")

    def test_expired_or_forged_call_token_is_ignored(self):
        expired = verifiers.mint_token("call", JAMES, SECRET, ttl=-10)
        forged = verifiers.mint_token("call", JAMES, "some-other-secret-000000")
        for token in (expired, forged, "garbage"):
            reply = Call(attributes={"idvCallToken": token}).reply
            self.assertEqual(reply["LoA"], "0")
            self.assertIn("PREAUTH_TOKEN_INVALID", reply["reasonCodes"])

    def test_dial_code_is_loa3_only_when_cli_is_the_registered_mobile(self):
        code = verifiers.dial_code_for(JAMES, SECRET)
        own = Call()
        own.press("3", line_key(JAMES), "1")
        self.assertEqual(own.press(code)["LoA"], "3")
        other = Call()
        other.press("3", line_key(SARAH), "1")
        self.assertEqual(other.press(code)["LoA"], "2")


class OptionE_AuthenticatedChat(unittest.TestCase):

    def chat(self, **attributes):
        return Call(channel="CHAT", cli="", attributes=attributes).reply

    def test_signed_session_starts_at_loa2(self):
        token = verifiers.mint_token("session", SARAH, SECRET, loa=2)
        reply = self.chat(idvSessionToken=token, idvIntent="balance")
        self.assertEqual((reply["action"], reply["LoA"], reply["idvDecision"]), ("handoff", "2", "PERMIT"))
        self.assertEqual(reply["customerId"], SARAH)

    def test_payment_needs_in_app_step_up_bound_to_the_request(self):
        session = verifiers.mint_token("session", SARAH, SECRET, loa=2)
        reply = self.chat(idvSessionToken=session, idvIntent="new_payee_payment")
        self.assertEqual((reply["LoA"], reply["idvDecision"]), ("2", "STEP_UP"))

        sca = verifiers.mint_token("sca", SARAH, SECRET, intent="new_payee_payment")
        reply = self.chat(idvSessionToken=session, idvIntent="new_payee_payment", idvStepUpToken=sca)
        self.assertEqual((reply["LoA"], reply["idvDecision"]), ("3", "PERMIT"))

        wrong_intent = verifiers.mint_token("sca", SARAH, SECRET, intent="change_contact_details")
        wrong_customer = verifiers.mint_token("sca", JAMES, SECRET, intent="new_payee_payment")
        for bad in (wrong_intent, wrong_customer):
            reply = self.chat(idvSessionToken=session, idvIntent="new_payee_payment", idvStepUpToken=bad)
            self.assertEqual(reply["LoA"], "2")

    def test_unauthenticated_chat_is_loa0_and_never_asks_kba(self):
        reply = self.chat(idvIntent="balance")
        self.assertEqual((reply["action"], reply["LoA"], reply["customerId"]), ("handoff", "0", ""))
        self.assertIn("NO_KBA_OVER_CHAT", reply["reasonCodes"])

    def test_hosted_widget_prefixed_attributes_are_read(self):
        token = verifiers.mint_token("session", ETHEL, SECRET, loa=2)
        self.assertEqual(self.chat(**{"HostedWidget-idvSessionToken": token})["customerId"], ETHEL)

    def test_session_token_cannot_claim_more_than_loa2(self):
        token = verifiers.mint_token("session", SARAH, SECRET, loa=3)
        self.assertEqual(self.chat(idvSessionToken=token)["LoA"], "2")


class OptionF_Guardrails(unittest.TestCase):
    """Only signed receipts accepted by the policy engine can change assurance."""

    def ctx(self, **overrides):
        base = {"contact_id": "contact-1", "customer_id": JAMES, "profile": data.profile_for(JAMES),
                "risk": "LOW", "cli_relationship": "MATCH", "channel": "voice", "loa": 1,
                "evidence": [], "used_nonces": [], "attempts": {}}
        return {**base, **overrides}

    def test_valid_receipt_raises_level(self):
        receipt = verifiers.issue_receipt("push", JAMES, "contact-1", "balance", SECRET)
        self.assertEqual(policy.accept_receipt(receipt, self.ctx(), SECRET)["loa"], 3)

    def test_receipt_is_rejected_when_forged_replayed_or_misbound(self):
        good = verifiers.issue_receipt("push", JAMES, "contact-1", "balance", SECRET)
        nonce = verifiers.verify_token(good, SECRET)["nonce"]
        cases = {
            "RECEIPT_INVALID_SIGNATURE": (verifiers.issue_receipt("push", JAMES, "contact-1", "", "attacker-secret-00000"), {}),
            "RECEIPT_REPLAYED": (good, {"used_nonces": [nonce]}),
            "RECEIPT_WRONG_CONTACT": (good, {"contact_id": "another-contact"}),
            "RECEIPT_WRONG_CUSTOMER": (good, {"customer_id": SARAH}),
            "RECEIPT_EXPIRED": (verifiers.issue_receipt("push", JAMES, "contact-1", "", SECRET, now=1.0), {}),
            "METHOD_NOT_ALLOWED_AT_HIGH_RISK": (verifiers.issue_receipt("otp_sms", JAMES, "contact-1", "", SECRET), {"risk": "HIGH"}),
        }
        for reason, (receipt, overrides) in cases.items():
            result = policy.accept_receipt(receipt, self.ctx(**overrides), SECRET)
            self.assertEqual((result["accepted"], result["loa"], result["reason"]), (False, 1, reason))

    def test_tampered_state_cannot_raise_the_level(self):
        call = Call()
        call.full_journey(line_key(JAMES))
        state = verifiers.verify_token(call.attributes["idvState"], SECRET)
        state.update({"loa": 3, "cand": JAMES})
        call.attributes["idvState"] = verifiers.sign_token(state, "attacker-secret-00000")
        reply = call.press(ADDRESS)
        self.assertEqual(reply["LoA"], "0", "forged state is discarded and the harness restarts")
        self.assertEqual(reply["customerId"], "")

    def test_refuses_to_run_unless_explicitly_enabled(self):
        os.environ["IDV_TEST_HARNESS_ENABLED"] = "false"
        try:
            reply = Call().reply
        finally:
            os.environ["IDV_TEST_HARNESS_ENABLED"] = "true"
        self.assertEqual((reply["action"], reply["reasonCodes"]), ("end", "HARNESS_DISABLED"))

    def test_invalid_input_is_repeated_then_ends(self):
        call = Call()
        self.assertIn("Sorry, I didn't get that", call.press("9")["prompt"])
        self.assertEqual(call.press("9", "9")["action"], "end")


class SessionInjectorHandoff(unittest.TestCase):
    """The main flow's injector re-resolves the customer the harness handed over."""

    def setUp(self):
        self.injected = {}
        injector.ASSISTANT_ID = "test-assistant"
        injector._resolve_wisdom_session_id = lambda instance_id, contact_id: "session-arn"
        injector._get_cross_channel_transcript = lambda attrs: {}
        injector._inject_session_data = lambda assistant_id, session_id, data: self.injected.update(data) or True

    def invoke(self, attributes, cli="+447765309252"):
        event = {"Details": {"ContactData": {
            "ContactId": "contact-1", "Channel": "VOICE",
            "InstanceARN": "arn:aws:connect:eu-west-2:111122223333:instance/abc",
            "CustomerEndpoint": {"Address": cli}, "Attributes": attributes}}}
        return injector.handler(event, None)

    def test_selected_customer_wins_over_the_real_cli(self):
        call = Call(cli="+447765309252")       # James's real number...
        call.press("1", line_key(ETHEL))       # ...but the tester selects Ethel
        result = self.invoke(call.attributes)
        self.assertEqual((result["customerId"], result["preferredName"]), (ETHEL, "Ethel"))
        self.assertEqual(self.injected["loa"], "2")
        self.assertEqual(self.injected["idvMethod"], "test_quick_select")

    def test_unverified_caller_is_not_upgraded_by_cli(self):
        call = Call(cli="+447765309252")
        call.full_journey(line_key(JAMES))
        call.press(GENERAL, "2")               # general info only: stays LoA1
        result = self.invoke(call.attributes)
        self.assertEqual((result["customerId"], result["authStatus"]), ("", "unauthenticated"))
        self.assertNotIn("preferredName", self.injected)

    def test_contacts_without_idv_behave_exactly_as_before(self):
        result = self.invoke({})
        self.assertEqual((result["customerId"], result["authStatus"]), (JAMES, "authenticated"))
        self.assertNotIn("loa", self.injected)


if __name__ == "__main__":
    unittest.main()
