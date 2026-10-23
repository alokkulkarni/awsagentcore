"""Before anything is created: the right account, nothing in the way, and every tool the scripts need.

    check           refuses the account today's system runs in, and (on a first run) any account where aria-*
                    Lambdas or tables already exist: every script uses fixed names, so it would quietly reuse them
                    and wire the new instance to someone else's resources. Then checks the tools.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from common import TEMPLATES, cli, fail, info, load_json, ok, warn

LIVE = load_json(TEMPLATES / "live-map.json")
ALIAS = re.compile(r"^[a-z][a-z0-9-]{2,36}[a-z0-9]$")


def _version(cmd: list[str]) -> str:
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return done.stdout + done.stderr               # some tools print their version on stderr
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _at_least(text: str, minimum: tuple[int, ...]) -> bool:
    found = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    if not found:
        return False
    have = tuple(int(x or 0) for x in found.groups())
    return have >= minimum + (0,) * (3 - len(minimum))


def check(ctx) -> None:
    s = ctx.state
    alias = s.need("INSTANCE_ALIAS")
    if not ALIAS.match(alias):
        fail(f"INSTANCE_ALIAS {alias!r}: use 4-38 lowercase letters, digits and hyphens, starting with a letter "
             "(it names the instance, its URL, and several buckets).")
    account = ctx.client("sts").get_caller_identity()["Account"]
    if account == LIVE["account"]:
        fail(f"You're signed in to {account}, where today's system runs. This script only builds a fresh copy in "
             "another account. Sign in to the new account (AWS_PROFILE) and run it again.")
    if s.get("ACCOUNT_ID") and s.get("ACCOUNT_ID") != account:
        fail(f"This state file belongs to account {s.get('ACCOUNT_ID')}, but you're signed in to {account}.")
    s.set("ACCOUNT_ID", account)
    ok(f"Account {account}, region {ctx.region}")

    if not s.get("PREFLIGHT_DONE"):
        lam, ddb = ctx.client("lambda"), ctx.client("dynamodb")
        names = [f["FunctionName"] for page in lam.get_paginator("list_functions").paginate() for f in page["Functions"]]
        names += [t for page in ddb.get_paginator("list_tables").paginate() for t in page["TableNames"]]
        clash = [n for n in names if n.startswith(("aria-", "mortgage-livesync-"))]
        if clash:
            fail("This account already has resources with the names this system uses: "
                 f"{', '.join(clash[:8])}{'…' if len(clash) > 8 else ''}. The scripts would reuse them. "
                 "Use an empty account (the instance is meant to be a fresh copy).")
        ok("No aria-* or mortgage-livesync-* resources in the way")

    problems = []
    aws = _version(["aws", "--version"])
    if not _at_least(aws.split("aws-cli/")[-1] if "aws-cli/" in aws else "", (2, 38)):
        problems.append(f"AWS CLI 2.38 or later (found: {aws.strip()[:40] or 'none'}). Older ones drop "
                        "multiAgentConfigurations without a word.")
    try:
        import boto3
        session = boto3.session.Session()
        for service in ("bedrock-agentcore-control", "s3vectors", "qconnect"):
            if service not in session.get_available_services():
                problems.append(f"boto3 too old: it doesn't know {service} (pip install -U boto3).")
        shapes = session._session.get_service_model("qconnect").shape_names
        if "MultiAgentConfiguration" not in shapes:
            problems.append("boto3 too old for Connect AI agent collaborators (pip install -U boto3).")
    except ImportError:
        problems.append("Python boto3 (pip install boto3).")
    for tool, minimum, why in (("node", (20,), "the agentic CX designer SDK, the web bundles"),
                               ("npm", (9,), "web bundles"), ("sam", (1, 100), "the mortgage backend"),
                               ("docker", (20,), "the Money Hub agent image")):
        if not shutil.which(tool):
            problems.append(f"{tool} ({why}).")
        elif not _at_least(_version([tool, "--version"]), minimum):
            problems.append(f"{tool} {'.'.join(map(str, minimum))} or later ({why}).")
    if shutil.which("docker") and "buildx" not in _version(["docker", "buildx", "version"]).lower():
        problems.append("docker buildx (the Money Hub agent is an ARM64 image).")
    for tool in ("jq", "zip", "curl", "openssl"):
        if not shutil.which(tool):
            problems.append(f"{tool}.")
    mortgage = s.get("MORTGAGE_REPO", "")
    if not (mortgage and Path(mortgage, "scripts/deploy-backend.sh").exists()):
        problems.append(f"MORTGAGE_REPO ({mortgage or 'not set'}) must be a checkout of connect-livesync-mortgage.")
    if problems:
        fail("Missing or too old:\n  - " + "\n  - ".join(problems))
    ok("Tools: AWS CLI, boto3, node, npm, sam, docker buildx, jq, zip, curl, openssl")

    if not (TEMPLATES / "acxd" / "index.json").exists():
        warn("No agentic CX designer templates yet (templates/acxd). The designer phase will stop and ask you to run "
             "`./deploy.sh capture-acxd` against today's workspace first.")
    info("Bedrock model access: the knowledge base uses Titan text embeddings v2; ARIA uses Claude Sonnet 4.5, the "
         "agent-assist agent Claude Sonnet 5, the briefing agent and Money Hub Claude Haiku 4.5. In a new account, "
         "open Bedrock → Model access once and accept any terms Anthropic asks for, or those steps fail.")
    s.set("PREFLIGHT_DONE", "1")


if __name__ == "__main__":
    cli(__doc__, {"check": check})
