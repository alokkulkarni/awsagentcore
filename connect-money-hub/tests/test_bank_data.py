"""
The sample bank's data (moneyhub/data.py) is the one copy every assistant reads. These tests pin the Money Hub's
figures, so adding to the bank never moves them, and check the rest agrees with itself.
"""

import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moneyhub import data  # noqa: E402


class MoneyHubFiguresDontMove(unittest.TestCase):
    # Every generated row, as it was when ARIA, the dispute service and the app started reading this file.
    PINNED = {"CUST-001": (333, 2828.8, "bc910435bdb6caf4"), "CUST-002": (188, 5888.22, "00997f7c21bbe02e")}

    def test_the_generated_current_accounts_are_exactly_as_pinned(self):
        for customer_id, (count, balance, digest) in self.PINNED.items():
            rows = data.generate(customer_id)
            self.assertEqual(len(rows), count)
            self.assertEqual(rows[-1]["balanceAfter"], balance)
            self.assertEqual(hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()[:16], digest)


class TheBankAgreesWithItself(unittest.TestCase):
    def test_the_current_balance_is_the_money_hubs(self):
        for customer_id in data.CUSTOMERS:
            self.assertEqual(data.account(customer_id)["balance"], data.generate(customer_id)[-1]["balanceAfter"])

    def test_debit_card_payments_are_the_current_accounts_own_card_payments(self):
        for customer_id in data.CUSTOMERS:
            account = {(t["date"], t["merchant"], -t["amount"]) for t in data.generate(customer_id)}
            payments = data.card_payments(customer_id, "debit")
            self.assertTrue(payments)
            for p in payments:
                self.assertIn((p["date"], p["merchant"], p["amount"]), account)
            self.assertEqual([p["date"] for p in payments], sorted((p["date"] for p in payments), reverse=True))

    def test_card_payments_are_never_direct_debits_salary_or_transfers(self):
        merchants = {p["merchant"] for p in data.card_payments("CUST-001", "debit")}
        for never in ("NATIONWIDE MORTGAGE", "ACME ENGINEERING LTD SALARY", "TRANSFER TO SAVINGS", "OCTOPUS ENERGY"):
            self.assertNotIn(never, merchants)

    def test_payment_ids_are_unique_and_keep_the_dispute_services_format(self):
        for customer_id in data.PROFILES:
            for kind in ("debit", "credit"):
                ids = [p["transactionId"] for p in data.card_payments(customer_id, kind)]
                self.assertEqual(len(ids), len(set(ids)))
        # Ids the dispute service has always used for these payments still name them
        credit = {p["transactionId"] for p in data.card_payments("CUST-001", "credit")}
        self.assertIn("TXN-2291-20261006-34900", credit)
        self.assertIn("TXN-6612-20261011-8999", {p["transactionId"] for p in data.card_payments("CUST-003", "debit")})

    def test_the_mortgage_payment_is_what_the_current_account_pays(self):
        paid = [t for t in data.generate("CUST-001") if t["merchant"] == "NATIONWIDE MORTGAGE"]
        self.assertEqual(-paid[-1]["amount"], data.mortgage("CUST-001")["monthlyPayment"])

    def test_the_credit_card_balance_is_its_payments(self):
        card = data.credit_card("CUST-001")
        self.assertEqual(card["balance"], round(sum(p["amount"] for p in data.card_payments("CUST-001", "credit")), 2))
        self.assertEqual(card["available"], round(card["limit"] - card["balance"], 2))

    def test_every_ending_names_one_customer(self):
        self.assertEqual(data.owner_of("2291")[0], "CUST-001")
        self.assertEqual(data.owner_of("0617")[0], "CUST-001")
        self.assertEqual(data.owner_of("4821")[1]["type"], "debit")
        self.assertIsNone(data.owner_of("0000"))

    def test_customers_without_a_money_hub_still_have_an_account_and_card_payments(self):
        for customer_id in ("CUST-003", "CUST-004", "CUST-005"):
            self.assertGreater(data.account(customer_id)["balance"], 0)
            self.assertTrue(data.current_account_transactions(customer_id))
            self.assertTrue(data.card_payments(customer_id, "debit"))


if __name__ == "__main__":
    unittest.main()
