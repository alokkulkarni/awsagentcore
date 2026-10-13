"""
Unit tests for the known-contact-reason injection in both session injectors.

Run from the repository root:

    python3 -m unittest discover -s connect-idv-test-harness/tests -v
"""

import json
import unittest

# Importing the harness tests sets up sys.path, the test environment and the
# boto3 stand-in used when boto3 is not installed.
import test_idv_harness as base

import session_injector as plain  # noqa: E402
import session_injector_qconnect as qconnect  # noqa: E402

JAMES, SARAH, DANIEL = base.JAMES, base.SARAH, base.DANIEL
BEGIN, END = "# BEGIN known contact reasons", "# END known contact reasons"


def reason_block(module) -> str:
    with open(module.__file__) as handle:
        source = handle.read()
    return source[source.index(BEGIN):source.index(END)]


class DisclosureGate(unittest.TestCase):
    """A known reason is personal data: it needs real verification before it is shared."""

    def test_phone_match_alone_discloses_nothing(self):
        # "authenticated" with no LoA is what a bare CLI match looks like.
        result = qconnect._build_contact_reason_vars(JAMES, "authenticated", None)
        self.assertEqual(result["hasKnownContactReason"], "false")
        self.assertEqual((result["contactReasonSummary"], result["contactReasons"]), ("", ""))

    def test_unauthenticated_or_low_level_discloses_nothing(self):
        for auth, loa in (("unauthenticated", 3), ("authenticated", 0), ("authenticated", 1)):
            self.assertEqual(qconnect._select_contact_reasons(JAMES, auth, loa), [])

    def test_fraud_block_needs_loa3(self):
        at_loa2 = [r["type"] for r in qconnect._select_contact_reasons(DANIEL, "authenticated", 2)]
        at_loa3 = [r["type"] for r in qconnect._select_contact_reasons(DANIEL, "authenticated", 3)]
        self.assertEqual(at_loa2, ["PAYMENT_FAILED_REPEATED"])
        self.assertEqual(at_loa3, ["CARD_BLOCKED_FRAUD", "PAYMENT_FAILED_REPEATED"])

    def test_unparseable_loa_is_treated_as_absent(self):
        for raw in ("", "high", None):
            self.assertIsNone(qconnect._parse_loa(raw))
        self.assertEqual(qconnect._parse_loa(" 2 "), 2)


class RankingAndShape(unittest.TestCase):

    def test_every_test_customer_has_more_than_one_scenario(self):
        for customer in qconnect._STUB_CUSTOMERS:
            self.assertGreater(len(qconnect._STUB_CONTACT_REASONS[customer]), 1, customer)

    def test_most_likely_reason_comes_first(self):
        result = qconnect._build_contact_reason_vars(JAMES, "authenticated", 2)
        self.assertEqual(result["topContactReason"], "trouble signing in to the mobile app")
        self.assertEqual(result["topContactReasonCategory"], "general_banking")
        types = [r["type"] for r in json.loads(result["contactReasons"])]
        self.assertEqual(types, ["MOBILE_APP_LOGIN_FAILED", "MORTGAGE_APPLICATION_PENDING"])
        self.assertTrue(result["contactReasonSummary"].startswith("(1) trouble signing in"))

    def test_all_values_are_strings_within_the_q_connect_limit(self):
        for customer in qconnect._STUB_CUSTOMERS:
            for value in qconnect._build_contact_reason_vars(customer, "authenticated", 3).values():
                self.assertIsInstance(value, str)
                self.assertLessEqual(len(value), qconnect.SESSION_VALUE_MAX_CHARS)

    def test_reasons_are_capped_and_trimmed_to_fit(self):
        long_detail = "x" * 500
        many = [{"type": f"T{i}", "label": f"reason {i}", "detail": long_detail, "days_ago": i,
                 "priority": i, "topic_category": "general_banking", "min_loa": 2} for i in range(1, 6)]
        original = qconnect._STUB_CONTACT_REASONS[JAMES]
        qconnect._STUB_CONTACT_REASONS[JAMES] = many
        try:
            self.assertEqual(len(qconnect._select_contact_reasons(JAMES, "authenticated", 3)), 3)
            result = qconnect._build_contact_reason_vars(JAMES, "authenticated", 3)
        finally:
            qconnect._STUB_CONTACT_REASONS[JAMES] = original
        self.assertEqual(len(json.loads(result["contactReasons"])), 1, "least likely reasons are dropped first")
        self.assertEqual(result["topContactReason"], "reason 1")

    def test_unknown_customer_has_no_reasons(self):
        self.assertEqual(qconnect._build_contact_reason_vars("CUST-999", "authenticated", 3)["hasKnownContactReason"], "false")


class BothInjectorsAgree(unittest.TestCase):

    def test_the_two_copies_of_the_block_are_identical(self):
        self.assertEqual(reason_block(plain), reason_block(qconnect))

    def test_plain_injector_applies_the_same_gate(self):
        plain.ASSISTANT_ID = ""    # AgentCore / Lex path: no Q Connect call is made

        def invoke(attributes):
            return plain.lambda_handler({"Details": {"ContactData": {
                "ContactId": "contact-1", "Channel": "VOICE",
                "InstanceARN": "arn:aws:connect:eu-west-2:111122223333:instance/abc",
                "CustomerEndpoint": {"Address": "+447911000000"}, "Attributes": attributes}}}, None)

        verified = invoke({"customerId": SARAH, "authStatus": "authenticated", "LoA": "2"})
        self.assertEqual(verified["topContactReason"], "a payment that did not go through")
        # customerId supplied with no LoA and no phone match: nothing vouches for a level.
        no_level = invoke({"customerId": SARAH, "authStatus": "authenticated"})
        self.assertEqual((no_level["hasKnownContactReason"], no_level["contactReasonSummary"]), ("false", ""))

    def test_plain_injector_gives_a_phone_match_the_configured_level(self):
        plain.ASSISTANT_ID = ""
        event = {"Details": {"ContactData": {
            "ContactId": "contact-1", "Channel": "VOICE",
            "InstanceARN": "arn:aws:connect:eu-west-2:111122223333:instance/abc",
            "CustomerEndpoint": {"Address": "+447765309252"}, "Attributes": {}}}}
        result = plain.lambda_handler(event, None)
        self.assertEqual((result["customerId"], result["loa"], result["hasKnownContactReason"]), (JAMES, "3", "true"))
        plain.CLI_MATCH_LOA = ""
        try:
            result = plain.lambda_handler(event, None)
        finally:
            plain.CLI_MATCH_LOA = "3"
        self.assertEqual((result["loa"], result["hasKnownContactReason"]), ("", "false"))


class EndToEndThroughTheHarness(base.SessionInjectorHandoff):
    """Harness verifies the caller, the main flow's injector then discloses by level."""

    def test_level_3_customer_gets_their_reasons_including_the_fraud_block(self):
        call = base.Call(cli="+447911000000")
        call.full_journey(base.line_key(DANIEL))
        call.press(base.YES)
        call.press(call.spoken_code())                               # LoA3 by pre-swap push
        result = self.invoke(call.attributes, cli="+447911000000")
        self.assertEqual(result["topContactReason"], "a block on your debit card")
        self.assertEqual(self.injected["hasKnownContactReason"], "true")
        self.assertIn("blocked yesterday", self.injected["contactReasonSummary"])

    def test_level_2_customer_does_not_get_the_fraud_block(self):
        call = base.Call(cli="+447911000000")
        call.full_journey(base.line_key(JAMES))                      # Daniel on James's phone
        call.press(base.NO, *base.CLAIM[DANIEL])
        call.press(call.spoken_code())                               # email code only: LoA2
        self.assertEqual(call.attributes["LoA"], "2")
        result = self.invoke(call.attributes, cli="+447911000000")
        self.assertEqual(result["topContactReason"], "card payments that were declined")
        self.assertNotIn("CARD_BLOCKED_FRAUD", self.injected["contactReasons"])

    def test_direct_call_gets_the_same_reasons_as_a_call_through_the_harness(self):
        direct = self.invoke({})                                     # James's real CLI, no harness
        self.assertEqual((direct["customerId"], direct["hasKnownContactReason"]), (JAMES, "true"))
        call = base.Call()
        call.press("1", base.line_key(JAMES))                        # quick select James
        through_harness = self.invoke(call.attributes, cli="+447911000000")
        for key in ("topContactReason", "contactReasonSummary", "loa"):
            self.assertEqual(direct[key], through_harness[key], key)

    def test_direct_call_gets_no_reasons_when_a_phone_match_earns_no_level(self):
        qconnect.CLI_MATCH_LOA = ""
        try:
            result = self.invoke({})
        finally:
            qconnect.CLI_MATCH_LOA = "3"
        self.assertEqual((result["customerId"], result["hasKnownContactReason"]), (JAMES, "false"))
        self.assertEqual(self.injected["contactReasonSummary"], "")

    # The inherited tests run again here unchanged, which is intended.


if __name__ == "__main__":
    unittest.main()
