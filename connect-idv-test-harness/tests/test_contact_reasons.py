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
        phone_only = invoke({"customerId": SARAH, "authStatus": "authenticated"})
        self.assertEqual((phone_only["hasKnownContactReason"], phone_only["contactReasonSummary"]), ("false", ""))


class EndToEndThroughTheHarness(base.SessionInjectorHandoff):
    """Harness verifies the caller, the main flow's injector then discloses by level."""

    def journey(self, customer, *keys):
        call = base.Call()
        call.full_journey(base.line_key(customer))
        call.press(*keys)
        call.press(call.spoken_code(), "2")
        return self.invoke(call.attributes, cli="+447911000000")

    def test_push_verified_customer_gets_their_reasons(self):
        result = self.journey(DANIEL, base.PAYEE, base.YES)          # LoA3 by pre-swap push
        self.assertEqual(result["topContactReason"], "a block on your debit card")
        self.assertEqual(self.injected["hasKnownContactReason"], "true")
        self.assertIn("blocked yesterday", self.injected["contactReasonSummary"])

    def test_quick_select_gets_loa2_reasons_only(self):
        call = base.Call()
        call.press("1", base.line_key(DANIEL))
        result = self.invoke(call.attributes)
        self.assertEqual(result["topContactReason"], "card payments that were declined")
        self.assertNotIn("CARD_BLOCKED_FRAUD", self.injected["contactReasons"])

    def test_direct_call_to_the_main_flow_gets_no_reasons(self):
        result = self.invoke({})                                     # James's real CLI, no harness
        self.assertEqual((result["customerId"], result["hasKnownContactReason"]), (JAMES, "false"))
        # Empty values are dropped before the Q Connect call, so nothing is injected.
        self.assertEqual(self.injected["contactReasonSummary"], "")
        self.assertEqual(self.injected["contactReasons"], "")

    # The inherited tests run again here unchanged, which is intended.


if __name__ == "__main__":
    unittest.main()
