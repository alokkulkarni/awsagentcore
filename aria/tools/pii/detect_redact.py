"""Detects and redacts PII from raw customer input."""

import re
from strands import tool
from aria.models.pii import PIIDetectResponse

# In-memory stub — replace with real PII detection service (e.g., AWS Comprehend)
_PII_PATTERNS: dict[str, str | None] = {
    "account_number": r'\b\d{8}\b',
    "sort_code": r'\b\d{2}-\d{2}-\d{2}\b',
    "card_number": r'\b(?:\d[ -]?){13,16}\b',
    "mobile": r'\b07\d{9}\b',
    "nino": r'\b[A-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b',
    "email": r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
    "dob": r'\b\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}\b',
    "name": r'\b[A-Z][a-z]+ [A-Z][a-z]+\b',
    "mortgage_ref": r'\bMR-[A-Z0-9]+-[A-Z]{2}\b',
    "address": r'\b\d+\s[A-Z][a-z]+ (Street|Road|Avenue|Lane|Drive|Close|Way)\b',
    "memorable_word": None,  # context-dependent, handled separately
}


@tool
def pii_detect_and_redact(input_text: str, session_id: str, pii_types: list[str]) -> dict:
    """
    Detects and redacts PII from raw customer input before it enters model reasoning.
    Returns a redacted version of the text and a pii_map of token -> original value.
    Must be called on every customer utterance before any processing.
    pii_types is a list of PII category names to scan for, e.g.:
    ['account_number', 'sort_code', 'card_number', 'mobile', 'nino', 'email',
     'dob', 'name', 'mortgage_ref', 'address'].
    The pii_map returned must be passed immediately to pii_vault_store when pii_detected is true.
    """
    redacted = input_text
    pii_map: dict[str, str] = {}
    counters: dict[str, int] = {}

    for pii_type in pii_types:
        pattern = _PII_PATTERNS.get(pii_type)
        if not pattern:
            continue
        matches = list(re.finditer(pattern, redacted))
        for match in matches:
            counters[pii_type] = counters.get(pii_type, 0) + 1
            token_key = f"PII_{pii_type.upper()}_{counters[pii_type]:03d}"
            pii_map[token_key] = match.group(0)
            redacted = redacted.replace(match.group(0), f"[{token_key}]", 1)

    risk = "high" if len(pii_map) >= 3 else "medium" if len(pii_map) >= 1 else "low"

    return PIIDetectResponse(
        redacted_text=redacted,
        pii_map=pii_map,
        pii_detected=bool(pii_map),
        risk_classification=risk,
    ).model_dump()
