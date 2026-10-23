"""Stores values you paste (read from stdin, never from the command line and never printed) in Secrets Manager.

    put NAME        stdin is the secret's JSON. Creates the secret (tagged) or adds a new version to one this run
                    made. A secret someone else made is never changed.
    exists NAME     exit 0 if the secret exists (for deploy.sh to decide whether to ask)
"""

from __future__ import annotations

import json
import sys

from common import TAGS, cli, fail, ok


def put(ctx) -> None:
    sm = ctx.client("secretsmanager")
    if len(ctx.extra) != 1:
        fail("put needs the secret's name.")
    name = ctx.extra[0]
    value = sys.stdin.read().strip()
    try:
        json.loads(value)
    except ValueError:
        fail("The value isn't JSON (nothing stored).")
    try:
        found = sm.describe_secret(SecretId=name)
    except sm.exceptions.ResourceNotFoundException:
        sm.create_secret(Name=name, SecretString=value, Tags=[{"Key": k, "Value": v} for k, v in TAGS.items()],
                         Description="deploy-fresh-instance")
        ok(f"Secret {name} created")
        return
    if not any(t["Key"] == "project" and t["Value"] == TAGS["project"] for t in found.get("Tags", [])):
        fail(f"Secret {name} exists and wasn't made by deploy-fresh-instance. Not changing it.")
    sm.put_secret_value(SecretId=name, SecretString=value)
    ok(f"Secret {name}: new version stored")


def exists(ctx) -> None:
    sm = ctx.client("secretsmanager")
    try:
        sm.describe_secret(SecretId=ctx.extra[0])
    except sm.exceptions.ResourceNotFoundException:
        sys.exit(1)


if __name__ == "__main__":
    cli(__doc__, {"put": put, "exists": exists})
