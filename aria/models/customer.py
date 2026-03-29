"""Pydantic v2 models for customer profile."""

from typing import Optional
from pydantic import BaseModel, ConfigDict


class CustomerAccount(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    account_number_masked: str   # e.g. "****4821"
    account_type: str            # current | savings | isa | joint
    nickname: Optional[str]      # e.g. "Main Account", "Holiday Savings"
    currency: str = "GBP"
    sort_code_masked: str        # e.g. "20-**-67"
    is_primary: bool = False


class CustomerCard(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    card_last_four: str
    card_type: str               # debit | credit
    card_scheme: str             # Visa | Mastercard
    nickname: Optional[str]      # e.g. "Everyday Card", "Rewards Card"
    status: str                  # active | blocked | expired | pending
    linked_account_masked: Optional[str]  # masked account number card is linked to


class VulnerabilityFlag(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    flag_type: str               # financial_difficulty | bereavement | mental_health | elderly | disability | other
    requires_extra_time: bool = False
    requires_simplified_language: bool = False
    refer_to_specialist: bool = False  # if True, offer to transfer to specialist team


class CustomerDetailsResponse(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    customer_id: str
    first_name: str
    last_name: str
    full_name: str
    preferred_name: str
    email_masked: str
    mobile_last_four: str
    registered_address_masked: str
    customer_since_year: int
    status: str                  # active | suspended | closed

    accounts: list[CustomerAccount] = []
    cards: list[CustomerCard] = []
    mortgage_refs_masked: list[str] = []  # e.g. ["MR-****-GB"]

    vulnerability: Optional[VulnerabilityFlag] = None
