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

  3. Ownership    — verifies the card belongs to the authenticated customer.

     PRIMARY:  Invokes the aria-banking-mcp-customer Lambda directly
               (Lambda-to-Lambda) using the verify_card_ownership tool.
               Validates using BOTH the BIN (first 6 digits) AND last four
               digits — dual-factor card ownership check. Covers both debit
               and credit cards as registered in the customer profile.

     FALLBACK: If the customer Lambda call fails (timeout, unavailable), falls
               back to the aria-customer-cards DynamoDB table keyed on
               {customerId, cardLastFour}.

     Skipped when customer is unauthenticated and SKIP_OWNERSHIP_IF_UNAUTH
     is "true" (default).

All checks fail-open on service errors: if all checks are unavailable the
Lambda returns validationStatus="validation_service_error" rather than
blocking the customer due to a technical outage.

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
                "customerId":       "CUST-001",
                "authStatus":       "authenticated",
                "dtmf_last_four":   "8901",
                "dtmf_card_bin":    "414900",
                "dtmf_digit_count": "16"
            }
        },
        "Parameters": {
            "cardLastFour": "8901",
            "cardBin":      "414900",
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
    "cardNickname":       "Everyday Debit" | "",   # from customer Lambda if available
    "requiresEscalation": "false",   # "true" when card does not belong to customer
    "errorMessage":       ""
}

Environment variables:
    BIN_TABLE_NAME             DynamoDB BIN table        (default: aria-card-bins)
    CUSTOMER_CARDS_TABLE_NAME  DynamoDB customer cards   (default: aria-customer-cards)
    CUSTOMER_LAMBDA_NAME       Customer MCP Lambda name  (default: aria-banking-mcp-customer-prod)
                               When set, this is used as the PRIMARY ownership check.
                               The DynamoDB table is the fallback when this call fails.
    CARD_OWNERSHIP_API_URL     Optional external ownership check endpoint (deprecated,
                               superseded by CUSTOMER_LAMBDA_NAME)
    CARD_OWNERSHIP_API_KEY_ARN Optional Secrets Manager ARN for API key
    SKIP_OWNERSHIP_IF_UNAUTH   "true" skips ownership for unauthenticated customers
    CONNECT_INSTANCE_ID        Connect instance ID for real-time agent status push
    AWS_REGION                 Defaults to eu-west-2

IAM permissions required:
    dynamodb:GetItem on aria-card-bins
    dynamodb:GetItem on aria-customer-cards
    lambda:InvokeFunction on aria-banking-mcp-customer-prod
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
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BIN_TABLE              = os.environ.get("BIN_TABLE_NAME",             "aria-card-bins")
CARDS_TABLE            = os.environ.get("CUSTOMER_CARDS_TABLE_NAME",  "aria-customer-cards")
CUSTOMER_LAMBDA_NAME   = os.environ.get("CUSTOMER_LAMBDA_NAME",       "aria-banking-mcp-customer-prod")
OWNERSHIP_API_URL      = os.environ.get("CARD_OWNERSHIP_API_URL",     "")
OWNERSHIP_API_KEY_ARN  = os.environ.get("CARD_OWNERSHIP_API_KEY_ARN", "")
SKIP_UNAUTH_OWNERSHIP  = os.environ.get("SKIP_OWNERSHIP_IF_UNAUTH",   "true").lower() == "true"
CONNECT_INSTANCE_ID    = os.environ.get("CONNECT_INSTANCE_ID",        "")
SESSIONS_TABLE         = os.environ.get("SESSIONS_TABLE_NAME",        "dtmf_active_sessions")
REGION                 = os.environ.get("AWS_REGION",                 "eu-west-2")

# ── Security: validate OWNERSHIP_API_URL scheme when set ──────────────────
if OWNERSHIP_API_URL:
    import urllib.parse as _urlparse
    _parsed_ownership_url = _urlparse.urlparse(OWNERSHIP_API_URL)
    if _parsed_ownership_url.scheme != "https" or not _parsed_ownership_url.netloc:
        raise ValueError(
            f"CARD_OWNERSHIP_API_URL must be a full HTTPS URL, got: {OWNERSHIP_API_URL!r}"
        )

_BOTO_CONFIG = Config(
    tcp_keepalive=True,
    max_pool_connections=10,
    retries={"mode": "standard", "max_attempts": 3},
    connect_timeout=5,
    read_timeout=15,
)

dynamodb        = boto3.resource("dynamodb", region_name=REGION, config=_BOTO_CONFIG)
secrets_client  = boto3.client("secretsmanager", region_name=REGION, config=_BOTO_CONFIG)
connect_client  = boto3.client("connect", region_name=REGION, config=_BOTO_CONFIG)
lambda_client   = boto3.client("lambda",  region_name=REGION, config=_BOTO_CONFIG)

_cached_api_key: Optional[str] = None


# ---------------------------------------------------------------------------
# DynamoDB active-session tracker (non-critical — never raises)
# ---------------------------------------------------------------------------

_TERMINAL_STATUSES = frozenset({
    "complete", "failed", "timeout", "validation_failed", "ownership_mismatch",
    "system_error",   # unhandled Lambda exception — flow Error branch taken
})

# How long to keep terminal-status records visible in DynamoDB.
# Must exceed RESULT_DISPLAY_MS (15 s) + POLL_INTERVAL_MS (2 s) in the agent
# panel so the panel always has time to discover the contactId and render the
# result before the record expires via TTL.
_TERMINAL_TTL_SECONDS = 30

# Active sessions stay alive for up to 1 hour to survive queue wait times.
_ACTIVE_TTL_SECONDS = 3600


def _update_session(contact_id: str, status: str) -> None:
    """Keep the dtmf_active_sessions DynamoDB table in sync with the current status.

    For terminal statuses the record is kept alive for _TERMINAL_TTL_SECONDS
    (not deleted immediately) so the agent panel has a guaranteed window to
    discover the contactId via /dtmf-active and display the final result.
    The short TTL ensures DynamoDB cleans up automatically afterwards.

    Previously the record was deleted immediately on terminal status, causing a
    race: if the panel's 2 s discovery poll fired after the Lambda completed
    (~1 s), the contactId was gone and the panel never showed the error state.
    """
    if not contact_id or contact_id == "unknown":
        return
    try:
        import time
        table = dynamodb.Table(SESSIONS_TABLE)
        ttl   = int(time.time()) + (
            _TERMINAL_TTL_SECONDS if status in _TERMINAL_STATUSES else _ACTIVE_TTL_SECONDS
        )
        table.update_item(
            Key={"session_id": "ACTIVE"},
            UpdateExpression="SET #s = :s, #u = :u, #c = :c, #ttl = :ttl",
            ExpressionAttributeNames={
                "#s": "status", "#u": "updated_at",
                "#c": "contact_id", "#ttl": "ttl",
            },
            ExpressionAttributeValues={
                ":s": status,
                ":u": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                ":c": contact_id,
                ":ttl": ttl,
            },
        )
        if status in _TERMINAL_STATUSES:
            logger.info(
                "Session marked terminal (status=%s contact=%s ttl=+%ds)",
                status, contact_id, _TERMINAL_TTL_SECONDS,
            )
        else:
            logger.info("Session updated (status=%s contact=%s)", status, contact_id)
    except Exception as exc:
        logger.warning("_update_session failed: %s", exc)


# ---------------------------------------------------------------------------
# Agent status push (non-critical — never raises)
# ---------------------------------------------------------------------------

def _push_dtmf_status(contact_id: str, status: str, step: str = "", error_msg: str = "") -> None:
    """Push real-time DTMF validation status to human agent CCP and contact record."""
    if not contact_id or not CONNECT_INSTANCE_ID or contact_id == "unknown":
        logger.warning("push_dtmf_status skipped: contact_id=%r instance_id_set=%s",
                       contact_id, bool(CONNECT_INSTANCE_ID))
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
        logger.info("push_dtmf_status OK: status=%s contact=%s", status, contact_id)
    except Exception as exc:
        logger.error("push_dtmf_status FAILED: status=%s contact=%s error=%s",
                     status, contact_id, exc, exc_info=True)
    # Keep DynamoDB session in sync so the launcher/panel can discover the session
    _update_session(contact_id, status)


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


def _ownership_via_customer_lambda(
    customer_id: str,
    last_four: str,
    bin_prefix: str,
) -> Optional[tuple[bool, str, str]]:
    """
    PRIMARY ownership check — invokes aria-banking-mcp-customer-prod and calls
    the verify_card_ownership tool.

    This function validates using BOTH the card BIN (first 6 digits) AND the
    last four digits, covering both debit and credit cards registered to the
    customer in the customer profile.

    Returns
    ───────
    (belongs: bool, card_type: str, card_nickname: str)  on success
    None                                                  on any error (caller falls back to DynamoDB)
    """
    if not CUSTOMER_LAMBDA_NAME:
        return None
    try:
        payload = json.dumps({
            "tool_name": "verify_card_ownership",
            "parameters": {
                "customer_id":    customer_id,
                "card_last_four": last_four,
                "card_bin":       bin_prefix,
            },
        }).encode("utf-8")

        response = lambda_client.invoke(
            FunctionName=CUSTOMER_LAMBDA_NAME,
            InvocationType="RequestResponse",
            Payload=payload,
        )

        # Check for Lambda-level errors (e.g. function threw an unhandled exception)
        if response.get("FunctionError"):
            logger.warning(
                "Customer Lambda returned FunctionError: %s",
                response.get("FunctionError"),
            )
            return None

        body = json.loads(response["Payload"].read().decode("utf-8"))

        if "error" in body:
            logger.warning("Customer Lambda tool error: %s", body["error"])
            return None

        belongs  = bool(body.get("belongs_to_customer", False))
        c_type   = str(body.get("card_type",    ""))
        nickname = str(body.get("card_nickname", ""))
        method   = str(body.get("match_method", ""))

        logger.info(
            "Customer Lambda ownership check: customer=%s belongs=%s type=%s method=%s",
            customer_id, belongs, c_type, method,
        )
        return belongs, c_type, nickname

    except Exception as exc:
        logger.warning(
            "Customer Lambda ownership check failed (will fall back to DynamoDB): %s", exc
        )
        return None


def _ownership_via_dynamodb(customer_id: str, last_four: str, bin_prefix: str) -> bool:
    """Fallback ownership check using the aria-customer-cards DynamoDB table.

    Validates customerId + cardLastFour + cardBin so that two different cards
    that share the same last-four digits (but different BINs) are never
    confused with each other.  Records without a stored cardBin fall back to
    last-four-only matching for backward compatibility.
    """
    table    = dynamodb.Table(CARDS_TABLE)
    response = table.get_item(
        Key={"customerId": customer_id, "cardLastFour": last_four},
        ProjectionExpression="customerId, cardLastFour, cardBin, isActive",
    )
    item = response.get("Item")
    if item is None:
        return False
    if not item.get("isActive", True):
        return False
    # If the record has a stored BIN, it must match exactly.
    stored_bin = item.get("cardBin", "")
    if stored_bin and bin_prefix:
        if stored_bin != bin_prefix:
            logger.info(
                "DynamoDB BIN mismatch: stored=%s provided=%s customer=%s lastFour=****%s",
                stored_bin[:4] + "**", bin_prefix[:4] + "**", customer_id, last_four,
            )
            return False
    return True


def _check_ownership(
    customer_id: str,
    last_four: str,
    bin_prefix: str,
) -> Optional[tuple[bool, str, str]]:
    """
    Check whether a card belongs to the authenticated customer.

    Tries ownership checks in priority order:
      1. aria-banking-mcp-customer Lambda  (CUSTOMER_LAMBDA_NAME) — dual-factor
         (BIN + last four), covers debit AND credit cards from the customer profile.
      2. External API                       (CARD_OWNERSHIP_API_URL)  — deprecated
      3. aria-customer-cards DynamoDB table (CARDS_TABLE)             — fallback

    Returns
    ───────
    (True,  card_type, card_nickname)  — card belongs to customer
    (False, "",        "")             — card does NOT belong to customer
    None                               — all checks failed (service error → fail-open)
    """
    # ── 1. Customer Lambda (primary) ──────────────────────────────────────
    result = _ownership_via_customer_lambda(customer_id, last_four, bin_prefix)
    if result is not None:
        return result   # (belongs: bool, card_type: str, nickname: str)

    # ── 2. External API (legacy / deprecated) ─────────────────────────────
    if OWNERSHIP_API_URL:
        try:
            belongs = _ownership_via_api(customer_id, last_four, bin_prefix)
            return belongs, "", ""
        except Exception as exc:
            logger.warning("Ownership API failed: %s", exc)

    # ── 3. DynamoDB fallback ───────────────────────────────────────────────
    try:
        belongs = _ownership_via_dynamodb(customer_id, last_four, bin_prefix)
        return belongs, "", ""
    except Exception as exc:
        logger.error("DynamoDB ownership check failed: %s", exc)

    return None   # all checks failed → caller will fail-open


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

def handler(event: dict, context) -> dict:
    # Extract contact_id first — needed for error reporting even if handler crashes.
    contact_data  = event.get("Details", {}).get("ContactData", {})
    # Use InitialContactId so attributes are pushed to the original call leg,
    # which is the contact the agent's Streams panel is subscribed to.
    # During DTMF transfer flows the ContactId is the transfer sub-contact;
    # InitialContactId is the original inbound call the agent can see.
    contact_id    = (
        contact_data.get("InitialContactId")
        or contact_data.get("ContactId", "unknown")
    )

    try:
        return _handler_body(event, context, contact_data, contact_id)

    except Exception as exc:
        # Catch-all: push system_error so the agent panel shows the failure
        # and the ACTIVE DynamoDB session is deleted.  Then re-raise so the
        # Connect Lambda block takes its "Error" branch and the flow can
        # reconnect the customer to the agent immediately.
        logger.error(
            "Unhandled exception in validate handler: contact=%s error=%s",
            contact_id, exc, exc_info=True,
        )
        try:
            _push_dtmf_status(contact_id, "system_error",
                              "Technical error — returning to agent")
        except Exception:
            logger.debug("Suppressed exception in DTMF validation cleanup", exc_info=True)
        try:
            _update_session(contact_id, "system_error")   # deletes ACTIVE record
        except Exception:
            logger.debug("Suppressed exception in DTMF validation cleanup", exc_info=True)
        raise   # re-raise → Connect Error branch fires → flow returns customer to agent


def _handler_body(event: dict, context, contact_data: dict, contact_id: str) -> dict:
    """Core validation logic — called by handler() inside a catch-all wrapper."""
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

    # "validating" matches STATUS_MAP key in the agent panel
    _push_dtmf_status(contact_id, "validating", "Checking card details...")

    # ------------------------------------------------------------------
    # Step 1 — Luhn check (only when full card number is available)
    # ------------------------------------------------------------------
    if card_full and card_full.isdigit() and len(card_full) >= 13:
        if not _luhn_check(card_full):
            logger.warning("Luhn check failed contact=%s", contact_id)
            _push_dtmf_status(
                contact_id, "validation_failed",
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
    card_nickname          = ""          # populated by ownership Lambda if match found
    ownership_check_needed = True

    if card_bin and len(card_bin) >= 6:
        bin_record = _lookup_bin(card_bin)
        if bin_record is None:
            logger.warning("BIN %s not found/inactive contact=%s", card_bin[:4] + "**", contact_id)
            _push_dtmf_status(
                contact_id, "validation_failed",
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
            _push_dtmf_status(contact_id, "complete",
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
            # All ownership services unavailable — fail open rather than block customer
            logger.warning("All ownership services unavailable — failing open contact=%s", contact_id)
            _push_dtmf_status(contact_id, "complete",
                              "Card captured (ownership service temporarily unavailable)")
            return {
                "isValid":            "true",
                "validationStatus":   "validation_service_error",
                "validationMessage":  "Card captured — ownership check temporarily unavailable",
                "cardType":           card_type,
                "cardNickname":       "",
                "requiresEscalation": "false",
                "errorMessage":       "Ownership service unavailable",
            }

        belongs, resolved_card_type, card_nickname = result

        # Prefer card type resolved from customer Lambda over BIN table when available
        if resolved_card_type:
            card_type = resolved_card_type.upper()

        if not belongs:
            logger.warning(
                "Card not found on account customerId=%s contact=%s",
                (customer_id[:4] + "***") if customer_id else "?", contact_id,
            )
            _push_dtmf_status(
                contact_id, "ownership_mismatch",
                "Card not found on this account",
                "Card not registered to this customer",
            )
            return {
                "isValid":            "false",
                "validationStatus":   "not_customer_card",
                "validationMessage":  "Card not found on this account — please check and re-enter",
                "cardType":           card_type,
                "cardNickname":       "",
                "requiresEscalation": "true",   # potential fraud signal → escalate
                "errorMessage":       "Card does not belong to authenticated customer",
            }

        logger.info("Ownership confirmed card_type=%s nickname=%r contact=%s",
                    card_type, card_nickname, contact_id)

    # ------------------------------------------------------------------
    # All checks passed
    # ------------------------------------------------------------------
    _push_dtmf_status(contact_id, "complete", "Card validated successfully")
    return {
        "isValid":            "true",
        "validationStatus":   "valid",
        "validationMessage":  "Card validated successfully",
        "cardType":           card_type,
        "cardNickname":       card_nickname,
        "requiresEscalation": "false",
        "errorMessage":       "",
    }
