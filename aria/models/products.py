"""Pydantic v2 models for the Meridian Bank product catalogue."""

from typing import Optional
from pydantic import BaseModel, ConfigDict


class Product(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    product_id: str
    name: str
    category: str           # current_account | savings | credit_card | mortgage
    sub_category: str       # e.g. instant_access | fixed_rate | isa | rewards | standard
    tagline: str            # one-line customer-facing description
    key_features: list[str]
    interest_rate: Optional[str] = None   # e.g. "4.75% AER"
    representative_apr: Optional[str] = None  # credit products only
    min_balance: Optional[float] = None
    max_balance: Optional[float] = None
    monthly_fee: Optional[float] = None
    eligibility: str        # brief eligibility note
    how_to_apply: str       # e.g. "Apply in branch, online, or via the app"


class ProductCatalogueResponse(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    category: str
    total_available: int
    products: list[Product]
    excluded_count: int         # number excluded because customer already holds them
    excluded_reason: Optional[str] = None  # human-readable note on what was excluded
