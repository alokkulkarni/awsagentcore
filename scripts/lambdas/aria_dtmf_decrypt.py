"""
aria_dtmf_decrypt.py — Amazon Connect DTMF decryption Lambda
Meridian Bank / ARIA AgentCore

Purpose:
    Decrypts the ciphertext produced by the Amazon Connect "Store customer input"
    block (with "Encrypt entry" enabled).  Connect uses public-key RSA encryption
    (RSA/ECB/OAEPWithSHA-512AndMGF1Padding via the AWS Encryption SDK).
    The matching RSA private key is stored in AWS Secrets Manager, which uses
    a KMS CMK to encrypt the key at rest.

Invoke from a Connect flow Lambda block immediately after a successful
"Store customer input" block.

Expected event payload (passed automatically by Connect Lambda block):
{
    "Details": {
        "ContactData": {
            "ContactId": "...",
            "Attributes": {
                "collectionPurpose": "card_verification"  # optional context
            },
            "Parameters": {}
        },
        "Parameters": {
            "encryptedValue": "base64ciphertext==",   # $.StoredCustomerInput
            "keyId":          "meridian-connect-key-id",  # optional override
            "purpose":        "card_last_four"        # optional context
        }
    }
}

Returns:
{
    "status":         "success" | "failed",
    "maskedValue":    "****4821",          # safe to display to agent
    "digitCount":     4,                   # how many digits were collected
    "purpose":        "card_last_four",
    "errorMessage":   ""                   # populated on failure only
}

Environment variables:
    PRIVATE_KEY_SECRET_ARN  — Secrets Manager ARN of the PEM private key
    CONNECT_KEY_ID          — default key ID (overridden by event parameter)
    AWS_REGION              — set automatically by Lambda runtime

IAM permissions required:
    secretsmanager:GetSecretValue  on PRIVATE_KEY_SECRET_ARN
    kms:Decrypt                    on the KMS key protecting the secret
"""

import json
import logging
import os
import base64
import re

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

_BOTO_CONFIG = Config(
    tcp_keepalive=True,
    max_pool_connections=10,
    retries={"mode": "standard", "max_attempts": 3},
    connect_timeout=5,
    read_timeout=15,
)

import aws_encryption_sdk
from aws_encryption_sdk.identifiers import CommitmentPolicy, EncryptionKeyType, WrappingAlgorithm
from aws_encryption_sdk.internal.crypto.wrapping_keys import WrappingKey
from aws_encryption_sdk.key_providers.raw import RawMasterKey

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

PROVIDER_ID            = "AmazonConnect"
DEFAULT_KEY_ID         = os.environ.get("CONNECT_KEY_ID",         "meridian-connect-key-id")
PRIVATE_KEY_SECRET_ARN = os.environ["PRIVATE_KEY_SECRET_ARN"]
REGION                 = os.environ.get("AWS_REGION",             "eu-west-2")
CONNECT_INSTANCE_ID    = os.environ.get("CONNECT_INSTANCE_ID",   "")

# Matches a real Connect key ID (UUID format)
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

_cached_private_key_pem: bytes | None = None
_connect_client = None
_secrets_client = None


def _get_connect_client():
    global _connect_client
    if _connect_client is None:
        _connect_client = boto3.client("connect", region_name=REGION, config=_BOTO_CONFIG)
    return _connect_client


def _get_secrets_client():
    global _secrets_client
    if _secrets_client is None:
        _secrets_client = boto3.client("secretsmanager", region_name=REGION, config=_BOTO_CONFIG)
    return _secrets_client


def _push_system_error(contact_id: str) -> None:
    """Best-effort: set dtmf_status=system_error on the contact so the agent
    panel shows the failure immediately.  Never raises — called from exception handler."""
    if not contact_id or contact_id == "unknown" or not CONNECT_INSTANCE_ID:
        return
    try:
        _get_connect_client().update_contact_attributes(
            InitialContactId=contact_id,
            InstanceId=CONNECT_INSTANCE_ID,
            Attributes={"dtmf_status": "system_error"},
        )
        logger.info("system_error pushed to contact: %s", contact_id)
    except Exception as push_exc:
        logger.warning("Could not push system_error to contact %s: %s", contact_id, push_exc)


def _get_private_key_pem() -> bytes:
    """
    Retrieve RSA private key PEM from Secrets Manager.
    Secrets Manager transparently decrypts via KMS when the secret is fetched.
    Result is module-level cached so repeated invocations within the same
    Lambda execution environment skip the Secrets Manager round-trip.
    """
    global _cached_private_key_pem
    if _cached_private_key_pem is not None:
        return _cached_private_key_pem

    client = _get_secrets_client()
    try:
        response = client.get_secret_value(SecretId=PRIVATE_KEY_SECRET_ARN)
        pem = response["SecretString"]
        if isinstance(pem, str):
            pem = pem.encode("utf-8")
        _cached_private_key_pem = pem
        logger.info("RSA private key loaded from Secrets Manager")
        return _cached_private_key_pem
    except ClientError as e:
        logger.error("Failed to retrieve private key: %s", e)
        raise


def _decrypt_with_sdk(ciphertext_b64: str, key_id: str) -> str:
    """
    Decrypt Connect DTMF ciphertext using AWS Encryption SDK.
    Connect encrypts using:
      - Provider:   AmazonConnect  (must match exactly)
      - Algorithm:  RSA/ECB/OAEPWithSHA-512AndMGF1Padding  (RSA_OAEP_SHA512_MGF1)
      - SDK format: AWS Encryption SDK message envelope
    See: https://docs.aws.amazon.com/connect/latest/adminguide/encrypt-data.html
    """
    private_key_pem = _get_private_key_pem()

    wrapping_key = WrappingKey(
        wrapping_algorithm=WrappingAlgorithm.RSA_OAEP_SHA512_MGF1,
        wrapping_key=private_key_pem,
        wrapping_key_type=EncryptionKeyType.PRIVATE,
    )

    key_provider = RawMasterKey(
        provider_id=PROVIDER_ID,
        key_id=key_id,
        wrapping_key=wrapping_key,
    )

    enc_client = aws_encryption_sdk.EncryptionSDKClient(
        commitment_policy=CommitmentPolicy.FORBID_ENCRYPT_ALLOW_DECRYPT
    )

    ciphertext_bytes = base64.b64decode(ciphertext_b64)
    plaintext_bytes, _ = enc_client.decrypt(
        source=ciphertext_bytes,
        key_provider=key_provider,
    )
    return plaintext_bytes.decode("utf-8")


def _luhn_check(digits: str) -> bool:
    """Return True if digits pass the Luhn check (ISO/IEC 7812)."""
    if not digits or not digits.isdigit():
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _mask_digits(digits: str) -> str:
    """
    Return a masked display string safe to show to agents.
    Shows last 4 digits: ****4821
    For short inputs (e.g. 4-digit PIN): ****
    """
    if len(digits) <= 4:
        return "*" * len(digits)
    return "*" * (len(digits) - 4) + digits[-4:]


def handler(event: dict, context) -> dict:
    # Extract contact_id early so we can push status on any exception.
    contact_id = (
        event.get("Details", {}).get("ContactData", {}).get("InitialContactId")
        or event.get("Details", {}).get("ContactData", {}).get("ContactId", "unknown")
    )
    logger.info("DTMF decrypt invoked | ContactId=%s", contact_id)

    try:
        return _handler_body(event, contact_id)
    except Exception as exc:
        # Catch-all: push system_error to the agent panel, then re-raise so
        # the Connect Lambda block takes its Error branch and the flow can
        # reconnect the customer to the agent without leaving them on hold.
        logger.error(
            "Unhandled exception in decrypt handler: contact=%s error=%s",
            contact_id, exc, exc_info=True,
        )
        _push_system_error(contact_id)
        raise   # re-raise → Connect Error branch fires → flow returns customer to agent


def _handler_body(event: dict, contact_id: str) -> dict:
    """Core decryption logic — called by handler() inside a catch-all wrapper."""
    parameters = event.get("Details", {}).get("Parameters", {})
    encrypted_value = parameters.get("encryptedValue", "").strip()
    purpose = parameters.get("purpose", "dtmf_input")

    # Use key ID from flow parameter only if it looks like a real UUID.
    # Falls back to CONNECT_KEY_ID env var so the Lambda works even when the
    # flow passes a placeholder like "connectKeyId".
    key_id_param = parameters.get("keyId", "").strip()
    key_id = key_id_param if _UUID_RE.match(key_id_param) else DEFAULT_KEY_ID

    # Debug: log full event to diagnose parameter mapping issues in the Connect flow
    logger.info(
        "DEBUG | params_keys=%s | encryptedValue_len=%d | encryptedValue_prefix=%r | keyId_param=%r | key_id_resolved=%s | purpose=%s",
        list(parameters.keys()),
        len(encrypted_value),
        encrypted_value[:40] if encrypted_value else "",
        key_id_param,
        key_id,
        purpose,
    )
    logger.info("DEBUG full event: %s", json.dumps(event))

    if not encrypted_value:
        logger.error("No encryptedValue parameter provided")
        return {
            "status": "failed",
            "maskedValue": "",
            "digitCount": 0,
            "purpose": purpose,
            "errorMessage": "No encrypted value provided",
        }

    # AWS Encryption SDK envelopes are large — a ciphertext shorter than 100
    # base64 chars almost certainly means the Connect flow block does not have
    # "Encrypt entry" enabled, and raw digits are being passed instead.
    if len(encrypted_value) < 100:
        logger.error(
            "encryptedValue is too short (%d chars) — likely unencrypted DTMF digits. "
            "Ensure 'Encrypt entry' is enabled on the 'Store customer input' block "
            "and the correct X.509 certificate key is selected.",
            len(encrypted_value),
        )
        return {
            "status": "failed",
            "maskedValue": "",
            "digitCount": 0,
            "purpose": purpose,
            "errorMessage": "encryptedValue too short — encryption not configured in Connect flow",
        }

    try:
        plaintext = _decrypt_with_sdk(encrypted_value, key_id)

        if not plaintext.isdigit():
            logger.error("Decrypted value is not numeric — possible decryption error")
            return {
                "status": "failed",
                "maskedValue": "",
                "digitCount": 0,
                "purpose": purpose,
                "errorMessage": "Decrypted value is not numeric",
            }

        masked = _mask_digits(plaintext)
        logger.info(
            "Decryption successful | purpose=%s digits=%d masked=%s",
            purpose,
            len(plaintext),
            masked,
        )

        result = {
            "status": "success",
            "maskedValue": masked,
            "digitCount": len(plaintext),
            "purpose": purpose,
            "errorMessage": "",
        }

        # Return last four digits and Luhn validity for card look-up / validation Lambda.
        if purpose in ("card_last_four", "card_verification", "full_card_number"):
            result["lastFour"] = plaintext[-4:]
            result["luhnValid"] = "true" if _luhn_check(plaintext) else "false"

        # Return the BIN (first 6 digits) for real-time BIN validation.
        # BINs are not PCI-sensitive — they are publicly used by all payment
        # processors for card type identification and routing.
        if len(plaintext) >= 6:
            result["cardBin"] = plaintext[:6]

        # Signal CVV capture without echoing the raw digits (PCI compliance).
        if purpose == "cvv":
            result["cvvCaptured"] = "true"

        return result

    except Exception as e:
        logger.error("Decryption failed: %s", e, exc_info=True)
        return {
            "status": "failed",
            "maskedValue": "",
            "digitCount": 0,
            "purpose": purpose,
            "errorMessage": "Decryption error",
        }
