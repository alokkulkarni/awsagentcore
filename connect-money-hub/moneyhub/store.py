"""
store.py
========
Where the Money Hub keeps what customers change: their own categories for
transactions, their savings goals, page links, and the Connect bridge's
conversation sessions. One DynamoDB table (key "pk"); an in-memory store with
the same behaviour for tests and local runs.

Items may carry "expiresAt" (seconds since 1970); an expired item reads as
absent. The table's time-to-live attribute "ttl" cleans them up later.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Callable


def _live(item: dict | None, now: float) -> dict | None:
    if item is None or ("expiresAt" in item and float(item["expiresAt"]) <= now):
        return None
    return item


class MemoryStore:
    def __init__(self, clock: Callable[[], float]):
        self.clock, self.items = clock, {}

    def get(self, key: str) -> dict | None:
        item = _live(self.items.get(key), self.clock())
        return json.loads(json.dumps(item)) if item else None

    def put(self, key: str, item: dict) -> None:
        self.items[key] = json.loads(json.dumps(item))


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _storable(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _storable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_storable(v) for v in value]
    return value


class DynamoStore:
    def __init__(self, table_name: str, clock: Callable[[], float], table: Any = None):
        if table is None:
            import boto3
            table = boto3.resource("dynamodb").Table(table_name)
        self.table, self.clock = table, clock

    def get(self, key: str) -> dict | None:
        item = self.table.get_item(Key={"pk": key}, ConsistentRead=True).get("Item")
        if item:
            item = _plain(item)
            item.pop("pk", None)
            item.pop("ttl", None)
        return _live(item, self.clock())

    def put(self, key: str, item: dict) -> None:
        row = {"pk": key, **_storable(item)}
        if "expiresAt" in item:
            row["ttl"] = int(float(item["expiresAt"])) + 3600
        self.table.put_item(Item=row)
