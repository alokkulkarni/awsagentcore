"""Pydantic v2 models for account queries."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, ConfigDict


class AccountDetailsRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    customer_id: str
    account_number: str
    query_subtype: str  # balance | transactions | statement | standing_orders


class Transaction(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    date: str
    description: str
    amount: float
    type: str  # debit | credit
    running_balance: float


class AccountDetailsResponse(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    account_number_last_four: str
    sort_code_last_two: str
    account_type: str
    available_balance: float
    cleared_balance: float
    currency: str
    recent_transactions: list[Transaction]
    standing_orders: list[dict]
    statement_url: Optional[str]
    query_subtype: str
