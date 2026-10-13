"""
dispute_store.py
================
Where disputes, page sessions, codes and adviser tokens are kept: one small
key-value table. Two stores with the same behaviour:

    MemoryStore   for tests and local runs
    DynamoStore   the DynamoDB table named by DISPUTE_TABLE_NAME

Every item is a dict stored under one string key. An item may carry
"expiresAt" (seconds since 1970). An expired item is treated as absent on every
read, so correctness never depends on when DynamoDB's time-to-live deletes it.

Writes are conditional: put() succeeds only if the item is in the state the
caller last saw. That is what stops two changes overwriting each other, and
stops one code being claimed twice.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any, Callable

ABSENT = "absent"      # put(..., expect=ABSENT): only if there is no live item under the key


def _live(item: dict | None, now: float) -> dict | None:
    if item is None or ("expiresAt" in item and float(item["expiresAt"]) <= now):
        return None
    return item


class MemoryStore:
    def __init__(self, clock: Callable[[], float]):
        self._items: dict[str, dict] = {}
        self._clock = clock

    def get(self, key: str) -> dict | None:
        return copy.deepcopy(_live(self._items.get(key), self._clock()))

    def put(self, key: str, item: dict, expect: Any = None) -> bool:
        current = _live(self._items.get(key), self._clock())
        if expect == ABSENT and current is not None:
            return False
        if isinstance(expect, int) and (current is None or int(current.get("version", -1)) != expect):
            return False
        self._items[key] = copy.deepcopy(item)
        return True


def _plain(value: Any) -> Any:
    """DynamoDB returns numbers as Decimal. Turn them back into int or float."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


class DynamoStore:
    """Table: partition key "pk" (string); time-to-live attribute "ttl" (seconds)."""

    def __init__(self, table_name: str, clock: Callable[[], float], table: Any = None):
        self._clock = clock
        if table is None:
            import boto3     # in the Lambda runtime; not needed by the tests
            table = boto3.resource("dynamodb").Table(table_name)
        self._table = table

    def get(self, key: str) -> dict | None:
        item = self._table.get_item(Key={"pk": key}, ConsistentRead=True).get("Item")
        if item is None:
            return None
        item = _plain(item)
        item.pop("pk", None)
        item.pop("ttl", None)
        return _live(item, self._clock())

    def put(self, key: str, item: dict, expect: Any = None) -> bool:
        record = {**item, "pk": key}
        if "expiresAt" in item:
            record["ttl"] = int(item["expiresAt"])
        # Attribute names go through aliases, so none can clash with a DynamoDB reserved word.
        condition: dict = {}
        if expect == ABSENT:
            condition = {"ConditionExpression": "attribute_not_exists(#pk) OR #expires <= :now",
                         "ExpressionAttributeNames": {"#pk": "pk", "#expires": "expiresAt"},
                         "ExpressionAttributeValues": {":now": int(self._clock())}}
        elif isinstance(expect, int):
            condition = {"ConditionExpression": "#version = :seen",
                         "ExpressionAttributeNames": {"#version": "version"},
                         "ExpressionAttributeValues": {":seen": expect}}
        try:
            self._table.put_item(Item=record, **condition)
            return True
        except Exception as error:
            if type(error).__name__ == "ConditionalCheckFailedException" or \
                    getattr(error, "response", {}).get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise
