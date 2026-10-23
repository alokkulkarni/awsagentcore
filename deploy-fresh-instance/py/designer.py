"""The agentic CX designer (the mortgage and card dispute assistants), through its SDK (acxd/).

    store-access    stdin: the new workspace's API key and ID. Checks they work, stores them as the mortgage stack's
                    designer access secret ({apiKey, workspaceId}), then runs the stack's sync function, which writes
                    the mortgage_api_key secret into the workspace
    create          rebuilds the captured apps in the new workspace (acxd/create.mjs), deploys them, and records each
                    app's ID and production alias code. The key is read from Secrets Manager, never from the command line
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from common import PACKAGE, TAGS, cli, fail, info, ok

ACXD = PACKAGE / "acxd"
APP_NAMES = {"mortgage": ("ACXD_MORTGAGE_APP_NAME", "Mortgage application"),
             "dispute": ("ACXD_DISPUTE_APP_NAME", "Card dispute")}


def _node(script: str, env: dict, *args: str) -> None:
    if not (ACXD / "node_modules" / "amazon-connect-acxd-sdk").exists():
        info("Installing the designer SDK (npm ci)...")
        subprocess.run(["npm", "ci" if (ACXD / "package-lock.json").exists() else "install", "--no-audit", "--no-fund"],
                       cwd=ACXD, check=True)
    subprocess.run(["node", str(ACXD / script), *args], cwd=ACXD, env={**os.environ, **env}, check=True)


def store_access(ctx) -> None:
    key, workspace = sys.stdin.readline().strip(), sys.stdin.readline().strip()
    if not key.startswith("acxd_") or not workspace:
        fail("Need the API key (starts acxd_) and the workspace ID.")
    _node("verify.mjs", {"ACXD_API_KEY": key, "ACXD_WORKSPACE_ID": workspace, "ACXD_REGION": ctx.region})
    secret = ctx.state.need("MORTGAGE_ACXD_ACCESS_SECRET")
    sm = ctx.client("secretsmanager")
    value = json.dumps({"apiKey": key, "workspaceId": workspace})
    try:
        sm.describe_secret(SecretId=secret)
        sm.put_secret_value(SecretId=secret, SecretString=value)
    except sm.exceptions.ResourceNotFoundException:
        sm.create_secret(Name=secret, SecretString=value, Description="Designer access (deploy-fresh-instance)",
                         Tags=[{"Key": k, "Value": v} for k, v in TAGS.items()])
    ctx.state.set("ACXD_WORKSPACE_ID", workspace)
    ok(f"Designer access stored in {secret}")
    reply = ctx.client("lambda").invoke(FunctionName=ctx.state.need("MORTGAGE_ACXD_SYNC_FUNCTION"),
                                        Payload=json.dumps({"action": "sync"}).encode())
    body = reply["Payload"].read().decode()
    if reply.get("FunctionError"):
        fail(f"The mortgage stack's sync function failed: {body[:300]}")
    ok(f"mortgage_api_key written to the workspace ({body[:120]})")


def create(ctx) -> None:
    access = json.loads(ctx.client("secretsmanager").get_secret_value(
        SecretId=ctx.state.need("MORTGAGE_ACXD_ACCESS_SECRET"))["SecretString"])
    result = Path(ctx.state.path).parent / f"{ctx.state.need('INSTANCE_ALIAS')}-acxd.json"
    _node("create.mjs", {"ACXD_API_KEY": access["apiKey"], "ACXD_WORKSPACE_ID": access["workspaceId"],
                         "ACXD_REGION": ctx.region, "AWS_REGION": ctx.region,
                         "MORTGAGE_ENDPOINT_URL": ctx.state.need("MORTGAGE_ENDPOINT_URL"),
                         "DISPUTE_ACXD_URL": ctx.state.need("DISPUTE_ACXD_URL")}, str(result))
    apps = json.loads(result.read_text())["applications"]
    for kind, (setting, default) in APP_NAMES.items():
        name = ctx.state.get(setting) or default
        app = apps.get(name)
        if not app or not app.get("aliases", {}).get("production"):
            fail(f"No deployed designer app called {name!r} (made: {', '.join(apps) or 'none'}). "
                 f"Set {setting} in your config to its name.")
        ctx.state.set(f"ACXD_{kind.upper()}_APP_ID", app["applicationId"])
        ctx.state.set(f"ACXD_{kind.upper()}_ALIAS", app["aliases"]["production"])
        ok(f"{name}: {app['applicationId']}, production alias {app['aliases']['production']}")


if __name__ == "__main__":
    cli(__doc__, {"store-access": store_access, "create": create})
