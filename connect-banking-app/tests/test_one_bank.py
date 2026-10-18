"""
Every assistant and page sees the same bank. The same customer, asked through ARIA's tools, ARIA's greeting (the
session injector), the card dispute service, the Money Hub and the internet banking pages, gives the same accounts,
cards, balances and payments, because all of them read connect-money-hub/moneyhub/data.py.
"""

import os
import sys
import types
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
sys.path[:0] = [str(APP), str(ROOT / "connect-money-hub"), str(ROOT / "connect-card-dispute" / "lambda"),
                str(ROOT / "scripts" / "lambdas"), str(ROOT / "scripts" / "lambdas" / "mcp_tools")]
os.environ.setdefault("MOCK_DATA", "true")          # as ARIA's account and customer Lambdas run

try:                                                 # the injector makes boto3 clients at import; no AWS is called
    import boto3  # noqa: F401
except ImportError:
    _boto3 = types.ModuleType("boto3")
    _boto3.client = _boto3.resource = lambda *a, **k: object()
    _config = types.ModuleType("botocore.config")
    _config.Config = lambda *a, **k: None
    _exceptions = types.ModuleType("botocore.exceptions")
    _exceptions.ClientError = type("ClientError", (Exception,), {})
    sys.modules.update({"boto3": _boto3, "botocore": types.ModuleType("botocore"),
                        "botocore.config": _config, "botocore.exceptions": _exceptions})

import aria_account_handler as account_tool  # noqa: E402
import aria_credit_card_handler as credit_tool  # noqa: E402
import aria_customer_handler as customer_tool  # noqa: E402
import aria_debit_card_handler as debit_tool  # noqa: E402
import aria_mortgage_handler as mortgage_tool  # noqa: E402
import dispute_model  # noqa: E402
import session_injector_qconnect as injector  # noqa: E402
from bankapp import home  # noqa: E402
from moneyhub.service import MoneyHub  # noqa: E402
from moneyhub.store import MemoryStore  # noqa: E402

JAMES = "CUST-001"


def tool(module, name, **params):
    return module.lambda_handler({"toolName": f"aria___{name}", "parameters": params}, None)


class EveryoneSeesTheSameJames(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.hub = MoneyHub(MemoryStore(lambda: 1_790_000_000), lambda: 1_790_000_000)
        cls.page = home.accounts(cls.hub, JAMES)
        cls.page_rows = {a["id"]: a for a in cls.page["accounts"]}
        cls.cards_page = home.cards(JAMES)
        cls.greeting = injector._lookup_customer(JAMES)
        cls.profile = tool(customer_tool, "get_customer_details", customer_id=JAMES)

    def test_the_same_cards_everywhere(self):
        greeting = {c["last_four"] for c in self.greeting["cards"]}
        tools = {c["last_four"] for c in self.profile["debit_cards"] + self.profile["credit_cards"]}
        disputes = {c["card_last_four"] for c in dispute_model.customer_cards(JAMES)}
        page = {c["ending"] for c in self.cards_page["cards"]}
        self.assertEqual(greeting, {"4821", "2291"})
        self.assertEqual(greeting, tools)
        self.assertEqual(greeting, disputes)
        self.assertEqual(greeting, page)

    def test_the_same_accounts_and_balance_everywhere(self):
        greeting = {a["masked"][-4:] for a in self.greeting["accounts"]}
        tools = {a["number_last_four"] for a in self.profile["accounts"]}
        page = {self.page_rows["current"]["ending"], self.page_rows["savings"]["ending"]}
        self.assertEqual(greeting, tools)
        self.assertEqual(greeting, page)
        balance = tool(account_tool, "get_account_balance", customer_id=JAMES)
        self.assertEqual(balance["account_number_last_four"], self.page_rows["current"]["ending"])
        self.assertEqual(balance["available_balance"], self.hub.overview(JAMES)["balance"])
        self.assertEqual(balance["available_balance"], self.page_rows["current"]["balance"])
        saver = tool(account_tool, "get_account_balance", customer_id=JAMES, account_type="savings")
        self.assertEqual(saver["available_balance"], self.page_rows["savings"]["balance"])
        self.assertIn(f"current account ending {self.page_rows['current']['ending']}",
                      injector._build_product_summary(self.greeting))

    def test_aria_lists_the_current_account_the_money_hub_and_the_app_show(self):
        listed = tool(account_tool, "get_recent_transactions", customer_id=JAMES, limit=5)["transactions"]
        money_hub = self.hub.list_transactions(JAMES, per_page=5)["transactions"]
        self.assertEqual([(t["date"], t["description"], t["amount"]) for t in listed],
                         [(t["date"], t["merchant"], t["amount"]) for t in money_hub])

    def test_aria_names_the_card_payments_the_dispute_assistant_and_the_cards_page_list(self):
        for kind, module, ending in (("debit", debit_tool, "4821"), ("credit", credit_tool, "2291")):
            name = f"get_{kind}_card_details"
            aria = tool(module, name, customer_id=JAMES, card_last_four=ending,
                        query_subtype="transactions")["recent_transactions"]
            disputes = dispute_model.card_transactions(JAMES, kind)
            page = [p for p in self.cards_page["payments"] if p["card"] == kind]
            for said, held, shown in zip(aria, disputes, page):
                self.assertEqual(said["transaction_id"], held["transaction_id"], kind)
                self.assertEqual(said["transaction_id"], shown["id"], kind)
                self.assertEqual((said["description"], -said["amount"]), (held["merchant"], float(held["amount"])), kind)

    def test_the_credit_card_balance_is_its_payments(self):
        card = tool(credit_tool, "get_credit_card_details", customer_id=JAMES, card_last_four="2291")
        paid = sum(float(t["amount"]) for t in dispute_model.card_transactions(JAMES, "credit"))
        self.assertAlmostEqual(card["outstanding_balance"], paid, places=2)

    def test_the_mortgage_aria_quotes_is_the_one_the_account_pays(self):
        reference = self.greeting["mortgages"][0]
        mortgage = tool(mortgage_tool, "get_mortgage_details", customer_id=JAMES, mortgage_reference=reference)
        self.assertEqual(mortgage["monthly_payment"], self.page_rows["mortgage"]["monthly"])
        self.assertTrue(reference.endswith(self.page_rows["mortgage"]["ending"]))

    def test_the_keypad_check_accepts_the_cards_aria_names_and_nothing_else(self):
        check = lambda last_four, bin_: customer_tool.lambda_handler(  # noqa: E731
            {"toolName": "verify_card_ownership",
             "parameters": {"customer_id": JAMES, "card_last_four": last_four, "card_bin": bin_}}, None)
        self.assertTrue(check("4821", "414900")["belongs_to_customer"])
        self.assertTrue(check("2291", "531908")["belongs_to_customer"])
        self.assertFalse(check("8901", "414900")["belongs_to_customer"], "James's old card number is gone")
        self.assertNotEqual(check("2291", "414900")["match_method"], "bin_and_last_four", "a wrong BIN never fully matches")

    def test_no_customer_can_see_another_customers_card_account_or_mortgage(self):
        sarah, margaret = "CUST-002", "CUST-003"
        for module, name, ending in ((debit_tool, "get_debit_card_details", "4821"),
                                     (credit_tool, "get_credit_card_details", "2291")):
            self.assertIn("error", tool(module, name, customer_id=sarah, card_last_four=ending, query_subtype="transactions"))
            self.assertIn("error", tool(module, name, card_last_four=ending), "no customer, no answer")
        spending = __import__("aria_products_handler")
        self.assertIn("error", spending.lambda_handler({"toolName": "x___analyse_spending", "parameters": {
            "customer_id": sarah, "source_ref_last_four": "0617"}}, None)["result"])
        self.assertIn("error", tool(mortgage_tool, "get_mortgage_details", customer_id=margaret,
                                    mortgage_reference="MR-****-8842"))
        self.assertIn("error", tool(mortgage_tool, "get_mortgage_details", mortgage_reference="MR-****-8842"))
        self.assertEqual(tool(debit_tool, "get_debit_card_details", customer_id=sarah, card_last_four="3317")["card_last_four"],
                         "3317", "her own card still works")

    def test_every_customer_has_one_name(self):
        for customer_id in injector._STUB_CUSTOMERS:
            greeting = injector._lookup_customer(customer_id)["preferred_name"]
            self.assertEqual(tool(customer_tool, "get_customer_details", customer_id=customer_id)["name"], greeting)
            self.assertEqual(home.first_name(customer_id), greeting)


if __name__ == "__main__":
    unittest.main()
