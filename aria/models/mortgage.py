"""Pydantic v2 models for mortgage queries."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, ConfigDict


class MortgageDetailsRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    customer_id: str
    mortgage_reference: str
    query_subtype: str  # balance | rate | monthly_payment | overpayment | redemption_statement | term


class MortgageDetailsResponse(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    mortgage_ref_last_four: str
    outstanding_balance: float
    interest_rate: float
    rate_type: str  # fixed | variable | tracker
    rate_valid_until: Optional[str]
    monthly_payment: float
    remaining_term_months: int
    overpayment_allowance_annual: float
    overpayment_used_ytd: float
    redemption_statement_available: bool
    query_subtype: str
    details: dict
