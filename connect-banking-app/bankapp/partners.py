"""
partners.py
===========
The mortgage and card dispute services, used as they are deployed today. Nothing here changes them.

    Mortgage     the page operations (help code, its status, submit) through its "IAM door": a direct
                 invoke of the main Lambda with {operation, payload}, the way its own page does. The browser
                 never holds the agent token. Its Live Sync keys come from its Touchpoint secret.
    Dispute      the form page's own calls (/api/screen/...), sent to the dispute Lambda as the HTTP request
                 its pages already make, so the in-app form behaves exactly like the dispute page. Its Live
                 Sync keys come from its own Touchpoint secret.

Touchpoint keys are browser keys by design (the ACXD application's deployment key and API key); they are kept
out of code and read here. A failed read is not kept, so it's tried again on the next request.
"""

from __future__ import annotations

import json
import os
import time

MORTGAGE_FUNCTION = os.environ.get("MORTGAGE_FUNCTION_NAME", "")
MORTGAGE_TOUCHPOINT_SECRET = os.environ.get("MORTGAGE_TOUCHPOINT_SECRET", "")
DISPUTE_FUNCTION = os.environ.get("DISPUTE_FUNCTION_NAME", "")
DISPUTE_TOUCHPOINT_SECRET = os.environ.get("DISPUTE_TOUCHPOINT_SECRET", "")
HELP_PHONE_NUMBER = os.environ.get("HELP_PHONE_NUMBER", "")
KEYS_SECONDS = 5 * 60
MORTGAGE_PAGE_OPS = ("createHelpCode", "helpCodeStatus", "submitApplication")
DISPUTE_SCREEN_ROUTES = ("open", "status", "save", "confirm")

_lambda = None
_secrets = None
_keys: dict[str, tuple[float, dict | None]] = {}


class PartnerError(Exception):
    """A partner service refused or couldn't be reached. Carries no customer data."""

    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def lambda_client():
    global _lambda
    if _lambda is None:
        import boto3
        _lambda = boto3.client("lambda")
    return _lambda


def secrets_client():
    global _secrets
    if _secrets is None:
        import boto3
        _secrets = boto3.client("secretsmanager")
    return _secrets


def touchpoint_keys(secret_id: str) -> dict | None:
    """{deploymentKey, apiKey} from a Touchpoint secret, or None if it isn't set up."""
    if not secret_id:
        return None
    kept = _keys.get(secret_id)
    if kept and time.time() < kept[0]:
        return kept[1]
    try:
        raw = secrets_client().get_secret_value(SecretId=secret_id)["SecretString"]
        found = json.loads(raw)
        value = {"deploymentKey": found["deploymentKey"], "apiKey": found["apiKey"]} \
            if found.get("deploymentKey") and found.get("apiKey") else None
    except Exception:                      # not set up, or no permission: Live Sync stays off, the form still works
        return None
    _keys[secret_id] = (time.time() + KEYS_SECONDS, value)
    return value


def _invoke(function: str, event: dict) -> dict:
    if not function:
        raise PartnerError("partner_unavailable", "This service isn't set up for this page yet.", 503)
    try:
        reply = lambda_client().invoke(FunctionName=function, Payload=json.dumps(event).encode())
    except Exception:
        raise PartnerError("partner_unavailable", "We couldn't reach the service just now. Try again in a minute.")
    if reply.get("FunctionError"):
        raise PartnerError("partner_failed", "Something went wrong. Try again.")
    return json.loads(reply["Payload"].read() or b"{}")


def mortgage(operation: str, payload: dict) -> dict:
    """One of the mortgage page operations, through its IAM door."""
    if operation not in MORTGAGE_PAGE_OPS:
        raise PartnerError("not_found", "Not found.", 404)
    answer = _invoke(MORTGAGE_FUNCTION, {"operation": operation, "payload": payload})
    status = int(answer.get("statusCode") or 200)
    body = json.loads(answer.get("body") or "{}") if isinstance(answer.get("body"), str) else answer.get("body") or {}
    if status >= 400:
        raise PartnerError("mortgage_refused", str(body.get("error") or "That didn't work. Try again."),
                           400 if status < 500 else 502)
    return body


def dispute_screen(route: str, body: dict) -> dict:
    """The dispute form's own call (/api/screen/<route>), as its page makes it."""
    if route not in DISPUTE_SCREEN_ROUTES:
        raise PartnerError("not_found", "Not found.", 404)
    answer = _invoke(DISPUTE_FUNCTION, {"requestContext": {"http": {"method": "POST"}},
                                        "rawPath": f"/api/screen/{route}", "body": json.dumps(body)})
    status = int(answer.get("statusCode") or 200)
    reply = json.loads(answer.get("body") or "{}")
    if status >= 400:
        raise PartnerError(str(reply.get("error") or "dispute_refused"), str(reply.get("message") or "That didn't work."),
                           status if status < 500 else 502)
    return reply


def mortgage_config(region: str, instance_id: str, products: list[dict]) -> dict:
    keys = touchpoint_keys(MORTGAGE_TOUCHPOINT_SECRET)
    return {"configured": bool(keys), "region": region, "instanceId": instance_id,
            "helpPhoneNumber": HELP_PHONE_NUMBER, "products": products, "helpCode": bool(MORTGAGE_FUNCTION),
            **(keys or {})}


def dispute_config(region: str, instance_id: str) -> dict:
    keys = touchpoint_keys(DISPUTE_TOUCHPOINT_SECRET)
    return {"configured": bool(keys), "region": region, "instanceId": instance_id, **(keys or {})}
