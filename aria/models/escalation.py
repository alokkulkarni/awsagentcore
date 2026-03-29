"""Pydantic v2 models for escalation and human handoff."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, ConfigDict


class TranscriptSummaryRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    session_id: str
    include_vault_refs: bool
    summary_format: str  # structured | plain


class TranscriptSummary(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    session_id: str
    channel: str
    call_start: str
    auth_status: str
    auth_method: str
    auth_level: str
    customer_id: str
    query_type: str
    query_detail: str
    actions_taken: list[str]
    escalation_reason: str
    risk_score: int
    pii_vault_refs: dict[str, str]


class TranscriptSummaryResponse(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    summary: TranscriptSummary


class EscalateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    session_id: str
    customer_id: str
    escalation_reason: str  # rate_switch_advice | fraud_dispute | customer_request | vulnerability | security_event | tool_failure
    auth_status: str
    auth_level: str
    risk_score: int
    transcript_summary: dict
    verified_pii: dict
    query_context: dict
    priority: str  # standard | urgent | safeguarding


class EscalateResponse(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    handoff_status: str  # accepted | queued | failed
    agent_id: str
    estimated_wait_seconds: int
    handoff_ref: str
