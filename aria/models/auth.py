"""Pydantic v2 models for the authentication pipeline."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, ConfigDict


class VerifyIdentityRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    header_customer_id: str
    requested_customer_id: str
    session_id: str


class VerifyIdentityResponse(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    identity_match: bool
    risk_score: int  # 0–100
    auth_level: str  # full | partial | none


class InitiateAuthRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    customer_id: str
    auth_method: str
    channel: str  # mobile | web | ivr | branch-kiosk
    session_id: str


class InitiateAuthResponse(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    auth_session_id: str
    challenge_type: str
    status: str  # initiated | already_authenticated | error


class ValidateAuthRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    session_id: str
    customer_id: str
    dob: str
    mobile_last_four: str
    memorable_word: Optional[str] = None


class ValidateAuthResponse(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    auth_status: str  # success | failed | locked
    attempts_remaining: int
    customer_id_verified: str
    auth_level: str  # full | partial | none


class CrossValidateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    header_customer_id: str
    auth_verified_customer_id: str
    body_customer_id: str
    session_id: str


class CrossValidateResponse(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    match_status: str  # match | mismatch
    customer_id: str
    mismatch_fields: list[str]
