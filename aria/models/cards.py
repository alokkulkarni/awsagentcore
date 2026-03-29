"""Pydantic v2 models for debit card and credit card queries."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, ConfigDict


class DebitCardDetailsRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    customer_id: str
    card_last_four: str
    query_subtype: str  # status | block | unblock | limits | lost_stolen | replacement


class DebitCardDetailsResponse(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    card_last_four: str
    card_status: str  # active | blocked | expired | cancelled
    card_type: str
    daily_atm_limit: float
    daily_pos_limit: float
    expiry_masked: str
    replacement_available: bool
    query_subtype: str
    details: dict


class BlockDebitCardRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    customer_id: str
    card_last_four: str
    reason: str  # lost | stolen | fraud
    request_replacement: bool = True


class BlockDebitCardResponse(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    card_last_four: str
    block_status: str  # blocked | failed
    replacement_ordered: bool
    replacement_eta_days: int
    block_reference: str


class CreditCardDetailsRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    customer_id: str
    card_last_four: str
    query_subtype: str  # balance | limit | minimum_payment | statement | interest_rate | dispute


class CreditCardTransaction(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    date: str
    description: str
    amount: float
    type: str  # debit | credit


class CreditCardDetailsResponse(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    card_last_four: str
    card_status: str  # active | blocked | expired | cancelled
    credit_limit: float
    available_credit: float
    current_balance: float
    minimum_payment_amount: float
    minimum_payment_due_date: str
    interest_rate_apr: float
    query_subtype: str
    details: dict
