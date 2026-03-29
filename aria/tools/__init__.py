"""Exports all ARIA tools as a flat list for agent registration."""

from aria.tools.pii.detect_redact import pii_detect_and_redact
from aria.tools.pii.vault_store import pii_vault_store
from aria.tools.pii.vault_retrieve import pii_vault_retrieve
from aria.tools.pii.vault_purge import pii_vault_purge
from aria.tools.auth.verify_identity import verify_customer_identity
from aria.tools.auth.initiate_auth import initiate_customer_auth
from aria.tools.auth.validate_auth import validate_customer_auth
from aria.tools.auth.cross_validate import cross_validate_session_identity
from aria.tools.account.account_details import get_account_details
from aria.tools.debit_card.card_details import get_debit_card_details
from aria.tools.debit_card.block_card import block_debit_card
from aria.tools.credit_card.card_details import get_credit_card_details
from aria.tools.mortgage.mortgage_details import get_mortgage_details
from aria.tools.products.product_catalogue import get_product_catalogue
from aria.tools.customer.customer_details import get_customer_details
from aria.tools.knowledge.knowledge_base import search_knowledge_base
from aria.tools.knowledge.feature_parity import get_feature_parity
from aria.tools.analytics.spending_insights import analyse_spending
from aria.tools.escalation.transcript_summary import generate_transcript_summary
from aria.tools.escalation.human_handoff import escalate_to_human_agent

ALL_TOOLS = [
    pii_detect_and_redact,
    pii_vault_store,
    pii_vault_retrieve,
    pii_vault_purge,
    verify_customer_identity,
    initiate_customer_auth,
    validate_customer_auth,
    cross_validate_session_identity,
    get_customer_details,
    get_account_details,
    get_debit_card_details,
    block_debit_card,
    get_credit_card_details,
    get_mortgage_details,
    get_product_catalogue,
    analyse_spending,
    search_knowledge_base,
    get_feature_parity,
    generate_transcript_summary,
    escalate_to_human_agent,
]

__all__ = [
    "ALL_TOOLS",
    "pii_detect_and_redact",
    "pii_vault_store",
    "pii_vault_retrieve",
    "pii_vault_purge",
    "verify_customer_identity",
    "initiate_customer_auth",
    "validate_customer_auth",
    "cross_validate_session_identity",
    "get_customer_details",
    "get_account_details",
    "get_debit_card_details",
    "block_debit_card",
    "get_credit_card_details",
    "get_mortgage_details",
    "get_product_catalogue",
    "analyse_spending",
    "search_knowledge_base",
    "get_feature_parity",
    "generate_transcript_summary",
    "escalate_to_human_agent",
]
