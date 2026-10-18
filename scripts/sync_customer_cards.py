#!/usr/bin/env python3
"""
sync_customer_cards.py
======================
Makes the keypad card check's registry (DynamoDB table aria-customer-cards, read
by the DTMF Lambdas) hold exactly the cards in the sample bank's one copy of its
data (connect-money-hub/moneyhub/data.py), so a card ARIA, the dispute assistant
or internet banking names is a card the keypad check accepts.

DRY RUN BY DEFAULT: it prints what it would add and remove. Add --apply to do it.

    python3 scripts/sync_customer_cards.py              # show the differences
    python3 scripts/sync_customer_cards.py --apply      # make them

Rows are keyed customerId + cardLastFour. Only the sample customers in data.py
are touched; any other customer's rows are left alone.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "connect-money-hub"))

from moneyhub import data  # noqa: E402

TABLE = "aria-customer-cards"
CARD_TYPES = {("debit", "Visa"): "VISA_DEBIT", ("debit", "Mastercard"): "MC_DEBIT",
              ("credit", "Mastercard"): "MC_CREDIT", ("credit", "Visa"): "VISA_CREDIT"}


def wanted() -> dict[tuple[str, str], dict]:
    """(customerId, cardLastFour) -> the row the registry should hold."""
    rows = {}
    for customer_id, held in data.PROFILES.items():
        for card in held["cards"]:
            rows[(customer_id, card["ending"])] = {
                "customerId": customer_id, "cardLastFour": card["ending"], "cardBin": card["bin"],
                "cardType": CARD_TYPES[(card["type"], card["scheme"])], "nickname": card["nickname"], "isActive": True,
            }
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    parser.add_argument("--apply", action="store_true", help="make the changes (otherwise only show them)")
    parser.add_argument("--region", default="eu-west-2")
    args = parser.parse_args()

    import boto3
    table = boto3.resource("dynamodb", region_name=args.region).Table(TABLE)
    items, kwargs = [], {}
    while True:
        page = table.scan(**kwargs)
        items += page.get("Items", [])
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    have = {(i["customerId"], i["cardLastFour"]): i for i in items if i.get("customerId") in data.PROFILES}
    want = wanted()

    add = [row for key, row in want.items() if {k: have.get(key, {}).get(k) for k in row} != row]
    remove = [key for key in have if key not in want]
    for row in add:
        print(f"  {'update' if (row['customerId'], row['cardLastFour']) in have else 'add   '} "
              f"{row['customerId']} {row['cardType']:<10} ending {row['cardLastFour']} (BIN {row['cardBin']})")
    for customer_id, last_four in remove:
        print(f"  remove {customer_id} ending {last_four} (not one of their cards in data.py)")
    if not add and not remove:
        print("The registry already matches data.py.")
        return
    if not args.apply:
        print("DRY RUN: nothing changed. Add --apply to make these changes.")
        return
    for row in add:
        table.put_item(Item=row)
    for customer_id, last_four in remove:
        table.delete_item(Key={"customerId": customer_id, "cardLastFour": last_four})
    print(f"Done: {len(add)} written, {len(remove)} removed.")


if __name__ == "__main__":
    main()
