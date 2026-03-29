"""Pydantic v2 models for the PII detection and vault pipeline."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, ConfigDict


class PIIDetectRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    input_text: str
    session_id: str
    pii_types: list[str]


class PIIDetectResponse(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    redacted_text: str
    pii_map: dict[str, str]
    pii_detected: bool
    risk_classification: str  # low | medium | high


class PIIVaultStoreRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    session_id: str
    pii_map: dict[str, str]
    ttl_seconds: int = 900


class PIIVaultStoreResponse(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    vault_status: str
    vault_refs: dict[str, str]
    expiry: str


class PIIVaultRetrieveRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    session_id: str
    vault_refs: list[str]
    purpose: str  # auth_validation | tool_param | spoken_response | escalation_handoff


class PIIVaultRetrieveResponse(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    resolved_values: dict[str, Optional[str]]
    retrieval_status: str  # success | not_found | expired


class PIIVaultPurgeRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    session_id: str
    purge_reason: str  # session_end | timeout | security_event | escalation


class PIIVaultPurgeResponse(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    purge_status: str
    tokens_purged: int
