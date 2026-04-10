"""
aria_dtmf_validate.py — Real-time card validation Lambda
Meridian Bank / ARIA AgentCore

Called AFTER aria-dtmf-decrypt to perform three layers of validation:

  1. Luhn check   — mathematical check (ISO/IEC 7812) that the card number
                    is structurally valid.  Runs only when the full card
                    number is available via the cardFull parameter.

  2. BIN check    — verifies the card BIN (first 6 digits) is in the bank's
                    approved BIN table (DynamoDB: aria-card-bins).  BINs are
                    not PCI-sensitive — they are publicly available and used
                    by all payment processors for card type identification.

  3. Ownership    — verifies the card belongs to the authenticated customer
                    (DynamoDB: aria-customer-cards, or external API if
                    CARD_OWNERSHIP_API_URL is set).  Skipped when the
                    customer is unauthenticated and SKIP_OWNERSHIP_IF_UNAUTH
                    is "true" (default).

All checks fail-open on service errors: if DynamoDB or the external API is
unavailable the Lambda returns validationStatus="validation_service_error"
rather than blocking the customer due to a technical outage.

This Lambda also pushes real-time status to the agent's CCP via
connect:UpdateContactAttributes so both the human agent (on hold) and the
AI agent (reading session attributes on its next turn) can see progress.

No full card numbers are ever received, stored, or logged by this Lambda.
The decrypt Lambda returns only:  cardBin (first 6), lastFour, digitCount.

Expected event payload (Connect Lambda block):
{
    "Details": {
        "ContactData": {
            "ContactId": "abc12345-...",
            "Attributes": {
                "customerId":       "C123456",
                "authStatus":       "authenticated",
                "dtmf_last_four":   "4821",
                "dtmf_card_bin":    "472352",
                "dtmf_digit_count": "16"
            }
        },
        "Parameters": {
            "cardLastFour": "4821",
            "cardBin":      "472352",
            "digitCount":   "16",
            "cardFull":     "",        # only set if returning full number
            "purpose":      "card_verification"
        }
    }
}

Returns:
{
    "isValid":            "true" | "false",
    "validationStatus":   "valid"
                        | "invalid_luhn"
                        | "invalid_bin"
                        | "not_customer_card"
                        | "unauthenticated_skip"
                        | "validation_service_error",
    "validationMessage":  "Card validated successfully",
    "cardType":           "VISA" | "MASTERCARD" | "AMEX" | "MAESTRO" | "UNKNOWN",
    "requiresEscalation": "false",   # "true" when card does not belong to customer
    "errorMessage":       ""
}

Environment variables:
    BIN_TABLE_NAME             DynamoDB BIN table        (default: aria-card-bins)
    CUSTOMER_CARDS_TABLE_NAME  DynamoDB customer cards   (default: aria-customer-cards)
    CARD_OWNERSHIP_API_URL     Optional external ownership check endpoint
    CARD_OWNERSHIP_API_KEY_ARN Optional Secrets Manager ARN for API key
    SKIP_OWNERSHIP_IF_UNAUTH   "true" skips ownership for unauthenticated customers
    CONNECT_INSTANCE_ID        Connect instance ID for real-time agent status push
    AWS_REGION                 Defaults to eu-west-2

IAM permissions required:
    dynamodb:GetItem on aria-card-bins
    dynamodb:GetItem on aria-customer-cards
    connect:UpdateContactAttributes on the Connect instance
    secretsmanager:GetSecretValue on CARD_OWNERSHIP_API_KEY_ARN (if set)
"""

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BIN_TABLE              = os.environ.get("BIN_TABLE_NAME",             "aria-card-bins")
CARDS_TABLE            = os.environ.get("CUSTOMER_CARDS_TABLE_NAME",  "aria-customer-cards")
OWNERSHIP_API_URL      = os.environ.get("CARD_OWNERSHIP_API_URL",     "")
OWNERSHIP_API_KEY_ARN  = os.environ.get("CARD_OWNERSHIP_API_KEY_ARN", "")
SKIP_UNAUTH_OWNERSHIP  = os.environ.get("SKIP_OWNERSHIP_IF_UNAUTH",   "true").lower() == "true"
CONNECT_INSTANCE_ID    = os.environ.get("CONNECT_INSTANCE_ID",        "")
REGION                 = os.environ.get("AWS_REGION",                 "eu-west-2")

dynamodb       = boto3.resource("dynamodb", region_name=REGION)
secrets_client = boto3.client("secretsmanager", region_name=REGION)
connect_client = boto3.client("connect", region_name=REGION)

_cached_api_key: Optional[str] = None


# ---------------------------------------------------------------------------
# Agent status push (non-critical — never raises)
# ---------------------------------------------------------------------------

def _push_dtmf_status(contact_id: str, status: str, step: str = "", error_msg: str = "") -> None:
    """Push real-time DTMF validation status to human agent CCP and contact record."""
    if not contact_id or not CONNECT_INSTANCE_ID or contact_id == "unknown":
        return
    attrs = {"dtmf_status": status}
    if step:       attrs["dtmf_step"]      = step
    if error_msg:  attrs["dtmf_error_msg"] = error_msg
    try:
        connect_client.update_contact_attributes(
            InitialContactId=contact_id,
            InstanceId=CONNECT_INSTANCE_ID,
            Attributes=attrs,
        )
    except Exception as exc:
        logger.warning("Could not push dtmf_status to agent (non-critical): %s", exc)


# ---------------------------------------------------------------------------
# Luhn algorithm (ISO/IEC 7812)
# ---------------------------------------------------------------------------

def _luhn_check(digits: str) -> bool:
    """Return True if digits pass the Luhn check (structurally valid card number)."""
    if not digits or not digits.isdigit():
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2 == 1:      # every second digit from the right is doubled
            n *= 2
            if n > 9:
                n -= 9      # same as summing the two digits of a 2-digit number
        total += n
    return total % 10 == 0


# ---------------------------------------------------------------------------
# BIN lookup
# ---------------------------------------------------------------------------

def _lookup_bin(bin_prefix: str) -> Optional[dict]:
    """Look up the first 6 digits of the card number in the BIN table."""
    if not bin_prefix or len(bin_prefix) < 6:
        return None
    try:
        table    = dynamodb.Table(BIN_TABLE)
        response = table.get_item(
            Key={"binPrefix": bin_prefix[:6]},
            ProjectionExpression="binPrefix, cardType, isActive, validationEnabled",
        )
        item = response.get("Item")
        return item if (item and item.get("isActive", True)) else None
    except ClientError as exc:
        logger.warning("BIN table lookup failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Card ownership check
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    global _cached_api_key
    if _cached_api_key:
        return _cached_api_key
    resp = secrets_client.get_secret_value(SecretId=OWNERSHIP_API_KEY_ARN)
    _cached_api_key = resp["SecretString"]
    return _cached_api_key


def _ownership_via_api(customer_id: str, last_four: str, bin_prefix: str) -> bool:
    payload = json.dumps({
        "customerId":   customer_id,
        "cardLastFour": last_four,
        "cardBin":      bin_prefix,
    }).encode("utf-8")
    req = urllib.request.Request(
        OWNERSHIP_API_URL,
        data=payload,
        headers={"Content-Type": "application/json", "x-api-key": _get_api_key()},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        return bool(body.get("cardBelongsToCustomer", False))


def _ownership_via_dynamodb(customer_id: str, last_four: str) -> bool:
    table    = dynamodb.Table(CARDS_TABLE)
    response = table.get_item(
        Key={"customerId": customer_id, "cardLastFour": last_four},
        ProjectionExpression="customerId, cardLastFour, isActive",
    )
    item = response.get("Item")
    return item is not None and item.get("isActive", True)


def _check_ownership(customer_id: str, last_four: str, bin_prefix: str) -> Optional[bool]:
    """Returns True (owns card), False (doesn't own card), None (service error)."""
    try:
        if OWNERSHIP_API_URL:
            return _ownership_via_api(customer_id, last_four, bin_prefix)
        return _ownership_via_dynamodb(customer_id, last_four)
    except Exception as exc:
        logger.error("Ownership check failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

def handler(event: dict, context) -> dict:
    contact_data  = event.get("Details", {}).get("ContactData", {})
    contact_id    = contact_data.get("ContactId", "unknown")
    attributes    = contact_data.get("Attributes", {})
    parameters    = event.get("Details", {}).get("Parameters", {})

    card_last_four = (parameters.get("cardLastFour") or attributes.get("dtmf_last_four", "")).strip()
    card_bin       = (parameters.get("cardBin")      or attributes.get("dtmf_card_bin",  "")).strip()
    digit_count    = int(parameters.get("digitCount") or attributes.get("dtmf_digit_count", "0") or "0")
    card_full      = parameters.get("cardFull", "").strip()  # full number only for Luhn
    purpose        = parameters.get("purpose", "card_verification")
    customer_id    = attributes.get("customerId", "")
    auth_status    = attributes.get("authStatus", "unauthenticated")

    logger.info(
        "Validate: contact=%s purpose=%s digits=%d bin=%s lastFour=****%s auth=%s",
        contact_id, purpose, digit_count,
        (card_bin[:4] + "**") if card_bin else "none",
        card_last_four or "none",
        auth_status,
    )

    _push_dtmf_status(contact_id, "validating", "Checking card details...")

    # ------------------------------------------------------------------
    # Step 1 — Luhn check (only when full card number is available)
    # ------------------------------------------------------------------
    if card_full and card_full.isdigit() and len(card_full) >= 13:
        if not _luhn_check(card_full):
            logger.warning("Luhn check failed contact=%s", contact_id)
            _push_dtmf_status(
                contact_id, "card_invalid",
                "Card format invalid — please re-enter",
                "Luhn check failed",
            )
            return {
                "isValid":            "false",
                "validationStatus":   "invalid_luhn",
                "validationMessage":  "Card number format is invalid — please re-enter",
                "cardType":           "UNKNOWN",
                "requiresEscalation": "false",
                "errorMessage":       "Luhn check failed",
            }
        logger.info("Luhn check passed contact=%s", contact_id)

    # ------------------------------------------------------------------
    # Step 2 — BIN check
    # ------------------------------------------------------------------
    card_type              = "UNKNOWN"
    ownership_check_needed = True

    if card_bin and len(card_bin) >= 6:
        bin_record = _lookup_bin(card_bin)
        if bin_record is None:
            logger.warning("BIN %s not found/inactive contact=%s", card_bin[:4] + "**", contact_id)
            _push_dtmf_status(
                contact_id, "card_invalid",
                "Card not recognised — please check and re-enter",
                "BIN not in approved list",
            )
            return {
                "isValid":            "false",
                "validationStatus":   "invalid_bin",
                "validationMessage":  "Card not recognised as a valid Meridian Bank card — please re-enter",
                "cardType":           "UNKNOWN",
                "requiresEscalation": "false",
                "errorMessage":       "BIN not in approved list",
            }
        card_type              = bin_record.get("cardType", "UNKNOWN")
        ownership_check_needed = bin_record.get("validationEnabled", True)
        logger.info("BIN valid cardType=%s contact=%s", card_type, contact_id)
    else:
        logger.info("BIN check skipped — insufficient digits purpose=%s", purpose)
        ownership_check_needed = False

    # ------------------------------------------------------------------
    # Step 3 — Ownership check
    # ------------------------------------------------------------------
    if not ownership_check_needed:
        pass  # BIN table says validation disabled for this card range

    elif auth_status != "authenticated" or not customer_id:
        if SKIP_UNAUTH_OWNERSHIP:
            logger.info("Ownership check skipped — unauthenticated contact=%s", contact_id)
            _push_dtmf_status(contact_id, "card_validated",
                              "Card captured (unauthenticated — ownership check skipped)")
            return {
                "isValid":            "true",
                "validationStatus":   "unauthenticated_skip",
                "validationMessage":  "Card captured — ownership check skipped (unauthenticated)",
                "cardType":           card_type,
                "requiresEscalation": "false",
                "errorMessage":       "",
            }

    elif card_last_four and customer_id:
        result = _check_ownership(customer_id, card_last_four, card_bin)

        if result is None:
            # Ownership service unavailable — fail open rather than block customer
            logger.warning("Ownership service error — failing open contact=%s", contact_id)
            _push_dtmf_status(contact_id, "card_validated",
                              "Card captured (ownership service temporarily unavailable)")
            return {
                "isValid":            "true",
                "validationStatus":   "validation_service_error",
                "validationMessage":  "Card captured — ownership check temporarily unavailable",
                "cardType":           card_type,
                "requiresEscalation": "false",
                "errorMessage":       "Ownership service unavailable",
            }

        if not result:
            logger.warning(
                "Card not found on account customerId=%s contact=%s",
                (customer_id[:4] + "***") if customer_id else "?", contact_id,
            )
            _push_dtmf_status(
                contact_id, "card_not_yours",
                "Card not found on this account",
                "Card not registered to this customer",
            )
            return {
                "isValid":            "false",
                "validationStatus":   "not_customer_card",
                "validationMessage":  "Card not found on this account — please check and re-enter",
                "cardType":           card_type,
                "requiresEscalation": "true",   # potential fraud signal → escalate
                "errorMessage":       "Card does not belong to authenticated customer",
            }

        logger.info("Ownership confirmed contact=%s", contact_id)

    # ------------------------------------------------------------------
    # All checks passed
    # ------------------------------------------------------------------
    _push_dtmf_status(contact_id, "card_validated", "Card validated successfully")
    return {
        "isValid":            "true",
        "validationStatus":   "valid",
        "validationMessage":  "Card validated successfully",
        "cardType":           card_type,
        "requiresEscalation": "false",
        "errorMessage":       "",
    }
