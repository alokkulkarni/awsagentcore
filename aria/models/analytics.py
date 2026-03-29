"""Pydantic v2 models for transaction spending insights."""

from typing import Optional
from pydantic import BaseModel, ConfigDict


class CategorisedTransaction(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    date: str           # YYYY-MM-DD
    description: str    # merchant name
    amount: float       # negative = debit/spend, positive = credit/refund
    category: str       # dining, groceries, transport, etc.
    currency: str = "GBP"


class CategorySummary(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    category: str
    total_spend: float          # absolute value (always positive)
    transaction_count: int
    largest_transaction: float
    transactions: list[CategorisedTransaction]


class SpendingInsightResponse(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_ref_last_four: str
    source_type: str            # current_account | credit_card
    date_from: str
    date_to: str
    category_filter: Optional[str] = None   # the canonical category searched, if filtered
    categories: list[CategorySummary]
    grand_total_spend: float    # sum of all debits in period
    grand_total_credits: float  # sum of all credits in period
    total_transactions: int
    currency: str = "GBP"
    note: Optional[str] = None
