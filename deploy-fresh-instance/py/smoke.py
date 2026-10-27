"""Reads everything back once the run is done, and prints where to start.

    check   the instance, every flow (published, and no longer the placeholder), the Lambdas and bot it may call,
            the assistant's knowledge base, the AI agents and their tool counts, every gateway target (READY), the
            two integrations, the designer apps, and the web pages answering. Prints each as OK or MISSING; never
            changes anything.
"""

from __future__ import annotations

import json
import urllib.request

from branch_tools import TOOLS as BRANCH_TOOLS
from common import GREEN, RED, RESET, TEMPLATES, cli, load_json, paged

CONNECT = load_json(TEMPLATES / "connect.json")
LAMBDAS = ("aria-session-injector-qconnect", "aria-handback-recovery", "aria-routing-lookup", "aria-card-dispute",
           "aria-agent-assist-injector")
# Targets the AI agents' tools live on: the gateway script's ten, Money Hub's, the dispute service's, the branch tools.
TARGETS = ("aria-banking-account", "aria-banking-auth", "aria-banking-credit-card", "aria-banking-customer",
           "aria-banking-debit-card", "aria-banking-escalation", "aria-banking-knowledge", "aria-banking-mortgage",
           "aria-banking-pii", "aria-banking-products", "aria-money-hub", "aria-banking-dispute",
           *(t["target"] for t in BRANCH_TOOLS))


def check(ctx) -> None:
    s, connect = ctx.state, ctx.client("connect")
    rows: list[tuple[str, bool, str]] = []

    def row(what: str, good: bool, detail: str = "") -> None:
        rows.append((what, good, detail))

    inst = connect.describe_instance(InstanceId=ctx.instance_id)["Instance"]
    row("Instance", inst["InstanceStatus"] == "ACTIVE", f"{inst['InstanceAlias']} ({inst['InstanceStatus']})")
    for key, flow in CONNECT["flows"].items():
        fid = s.get(f"FLOW_{key.upper()}")
        if not fid:
            row(f"Flow {flow['name']}", False, "not made")
            continue
        got = connect.describe_contact_flow(InstanceId=ctx.instance_id, ContactFlowId=fid)["ContactFlow"]
        actions = len(json.loads(got["Content"]).get("Actions", []))
        row(f"Flow {flow['name']}", got.get("State") == "ACTIVE" and actions > 1, f"{actions} blocks")
    linked = set(paged(connect.list_lambda_functions, "LambdaFunctions", InstanceId=ctx.instance_id))
    for name in LAMBDAS:
        row(f"Lambda {name} on the instance", any(a.endswith(f":function:{name}") for a in linked))
    bots = paged(connect.list_bots, "LexBots", InstanceId=ctx.instance_id, LexVersion="V2")
    row("Lex bot on the instance", any(b.get("LexV2Bot", {}).get("AliasArn") == s.get("LEX_ALIAS_ARN") for b in bots))
    q = ctx.client("qconnect")
    aid = s.get("ASSISTANT_ID")
    if aid:
        links = paged(q.list_assistant_associations, "assistantAssociationSummaries", token="nextToken", assistantId=aid)
        row("Knowledge base on the assistant", any(a["assistantAssociationId"] == s.get("KB_ASSOC_ID") for a in links))
        for key, label in (("ARIA", "ARIA v2"), ("AGENT_ASSIST", "Agent assist"), ("BRIEFING", "Briefing")):
            agent, version = s.get(f"{key}_AGENT_ID"), s.get(f"{key}_AGENT_VERSION")
            if not (agent and version):
                row(f"AI agent {label}", False, "not made")
                continue
            got = q.get_ai_agent(assistantId=aid, aiAgentId=f"{agent}:{version}")["aiAgent"]
            tools = got["configuration"].get("orchestrationAIAgentConfiguration", {}).get("toolConfigurations", [])
            row(f"AI agent {label}", True, f"{agent}:{version}, {len(tools)} tools")
    gid = s.get("GATEWAY_ID")
    if gid:
        ac = ctx.client("bedrock-agentcore-control")
        status = {t["name"]: t["status"] for t in paged(ac.list_gateway_targets, "items", token="nextToken",
                                                        gatewayIdentifier=gid)}
        for name in TARGETS:
            row(f"Gateway target {name}", status.get(name) == "READY", status.get(name, "not made"))
    apps = {a["IntegrationArn"].split("/")[-1] for a in paged(
        connect.list_integration_associations, "IntegrationAssociationSummaryList",
        InstanceId=ctx.instance_id, IntegrationType="APPLICATION")}
    row("MCP gateway integration", s.get("APP_MCP_ID") in apps)
    row("Money Hub A2A integration", s.get("APP_MONEY_HUB_ID") in apps)
    for key, label in (("ACXD_MORTGAGE_ALIAS", "Mortgage assistant (designer)"), ("ACXD_DISPUTE_ALIAS", "Card dispute assistant (designer)")):
        row(label, bool(s.get(key)), s.get(key) or "not deployed")
    for key, label in (("BANKING_APP_URL", "Banking app"), ("MONEY_HUB_URL", "Money Hub page"),
                       ("MORTGAGE_WEB_URL", "Mortgage reference page")):
        url = s.get(key)
        if not url:
            row(label, False, "no URL recorded")
            continue
        try:
            with urllib.request.urlopen(url, timeout=15) as reply:
                row(label, reply.status == 200, url)
        except Exception as err:  # noqa: BLE001
            row(label, False, f"{url}: {err}")

    width = max(len(r[0]) for r in rows)
    for what, good, detail in rows:
        mark = f"{GREEN}OK     {RESET}" if good else f"{RED}MISSING{RESET}"
        print(f"  {mark} {what.ljust(width)}  {detail}")
    missing = [r[0] for r in rows if not r[1]]
    print()
    print(f"{len(rows) - len(missing)} of {len(rows)} checks passed." + (f" Missing: {', '.join(missing)}." if missing else ""))


if __name__ == "__main__":
    cli(__doc__, {"check": check})
