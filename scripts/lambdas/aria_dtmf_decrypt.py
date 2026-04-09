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

import boto3
from botocore.exceptions import ClientError

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import load_pem_private_key

import aws_encryption_sdk
from aws_encryption_sdk.identifiers import CommitmentPolicy, WrappingAlgorithm
from aws_encryption_sdk.key_providers.raw import RawRSAMasterKeyProvider

logger = logging.getLogger()
logger.setLevel(logging.INFO)

PROVIDER_ID = "AmazonConnect"
DEFAULT_KEY_ID = os.environ.get("CONNECT_KEY_ID", "meridian-connect-key-id")
PRIVATE_KEY_SECRET_ARN = os.environ["PRIVATE_KEY_SECRET_ARN"]
REGION = os.environ.get("AWS_REGION", "eu-west-2")

_cached_private_key_pem: bytes | None = None


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

    client = boto3.client("secretsmanager", region_name=REGION)
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


class _ConnectRSAMasterKeyProvider(RawRSAMasterKeyProvider):
    """
    Subclass of RawRSAMasterKeyProvider that preloads a single RSA private key.
    The provider_id MUST be "AmazonConnect" — this must match what Connect used
    when encrypting the DTMF input.
    """

    provider_id = PROVIDER_ID

    def __init__(self, private_key_pem: bytes, key_id: str):
        super().__init__()
        private_key = load_pem_private_key(
            private_key_pem,
            password=None,
            backend=default_backend(),
        )
        self.add_master_key(key_id)
        self._keys[key_id] = private_key  # internal dict used by parent class

    def _get_raw_key(self, key_id: str):
        if key_id not in self._keys:
            raise KeyError(f"Key ID '{key_id}' not found in provider")
        return self._keys[key_id]


def _decrypt_with_sdk(ciphertext_b64: str, key_id: str) -> str:
    """
    Decrypt Connect DTMF ciphertext using AWS Encryption SDK.
    Connect encrypts using:
      - Provider:   AmazonConnect
      - Algorithm:  RSA/ECB/OAEPWithSHA-512AndMGF1Padding  (RSA_OAEP_SHA512_MGF1)
      - SDK format: AWS Encryption SDK message envelope
    """
    private_key_pem = _get_private_key_pem()
    key_provider = _ConnectRSAMasterKeyProvider(
        private_key_pem=private_key_pem,
        key_id=key_id,
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
    logger.info(
        "DTMF decrypt invoked | ContactId=%s",
        event.get("Details", {}).get("ContactData", {}).get("ContactId", "unknown"),
    )

    parameters = event.get("Details", {}).get("Parameters", {})
    encrypted_value = parameters.get("encryptedValue", "").strip()
    key_id = parameters.get("keyId", DEFAULT_KEY_ID).strip()
    purpose = parameters.get("purpose", "dtmf_input")

    if not encrypted_value:
        logger.error("No encryptedValue parameter provided")
        return {
            "status": "failed",
            "maskedValue": "",
            "digitCount": 0,
            "purpose": purpose,
            "errorMessage": "No encrypted value provided",
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

        # For card_last_four: also return the raw digits so the flow can pass
        # them to the AI agent for card look-up (still never logged).
        # Remove this block if you do NOT want the Lambda to ever return raw digits.
        if purpose in ("card_last_four", "card_verification"):
            result["lastFour"] = plaintext[-4:]

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
