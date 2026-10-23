"""Every contact flow and flow module ARIA's system uses.

The flows transfer to each other in a circle (ARIA → card dispute → back to ARIA; human handover → agent assist →
screen pop), so none can be created complete first. So:

    shells      create each flow and module with placeholder content (one Disconnect block) to get its ID
    fill        each flow's real content: the repo's committed JSON moved onto this instance (rebase.py), or the
                card dispute builder run with this instance's IDs; checked for old IDs, then sent to Connect.
                Connect checks every reference on the way in, so a flow that names a missing Lambda, bot, queue
                or flow is refused with the reason, and nothing half-done is published.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from common import ROOT, TAGS, TEMPLATES, cli, fail, info, load_json, ok, paged
from rebase import MissingValue, rebase_checked

CONNECT = load_json(TEMPLATES / "connect.json")
FLOW_STUB = {"Version": "2019-10-30", "StartAction": "end",
             "Actions": [{"Identifier": "end", "Type": "DisconnectParticipant", "Parameters": {}, "Transitions": {}}]}
MODULE_STUB = {"Version": "2019-10-30", "StartAction": "done",
               "Actions": [{"Identifier": "done", "Type": "EndFlowModuleExecution", "Parameters": {}, "Transitions": {}}]}

# Where each flow's content comes from. card_dispute is generated (its builder takes every ID as an argument).
SOURCES = {
    "main": ROOT / "connect-bot-flow-modular/flows/aria-conversation-bot-flow.json",
    "mortgage_handover": ROOT / "connect-bot-flow-modular/flows/mortgage-live-sync-handover.json",
    "human_handover": TEMPLATES / "flows/aria-human-handover.json",
    "mortgage_entry": TEMPLATES / "flows/mortgage-live-sync-entry.json",
    "agent_assist": ROOT / "connect-agent-assist/flows/aria-agent-assist-flow.json",
    "screen_pop": ROOT / "connect-agent-assist/flows/aria-agent-screen-pop-flow.json",
}


def shells(ctx) -> None:
    connect = ctx.client("connect")
    iid = ctx.instance_id
    flows = {f["Name"]: f["Id"] for f in paged(connect.list_contact_flows, "ContactFlowSummaryList", InstanceId=iid)}
    for key, flow in CONNECT["flows"].items():
        state_key = f"FLOW_{key.upper()}"
        if ctx.state.get(state_key):
            continue
        fid = flows.get(flow["name"]) or connect.create_contact_flow(
            InstanceId=iid, Name=flow["name"], Type=flow["type"], Content=json.dumps(FLOW_STUB),
            Description="deploy-fresh-instance (placeholder until the fill step)", Status="PUBLISHED", Tags=TAGS,
        )["ContactFlowId"]
        ctx.state.set(state_key, fid)
        ok(f"Flow {flow['name']}: {fid}")
    modules = {m["Name"]: m["Id"] for m in paged(connect.list_contact_flow_modules, "ContactFlowModulesSummaryList",
                                                 InstanceId=iid)}
    for key, module in CONNECT["modules"].items():
        state_key = f"MODULE_{key.upper()}"
        if ctx.state.get(state_key):
            continue
        mid = modules.get(module["name"]) or connect.create_contact_flow_module(
            InstanceId=iid, Name=module["name"], Content=json.dumps(MODULE_STUB),
            Description="deploy-fresh-instance (placeholder until the fill step)", Tags=TAGS)["Id"]
        ctx.state.set(state_key, mid)
        ok(f"Module {module['name']}: {mid}")


def _card_dispute_content(ctx) -> str:
    out = Path(ctx.state.path).parent / f"{ctx.state.need('INSTANCE_ALIAS')}-flows" / "card-dispute-flow.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    s = ctx.state
    for key in ("ACXD_WORKSPACE_ID", "ACXD_DISPUTE_APP_ID", "ACXD_DISPUTE_ALIAS", "FLOW_HUMAN_HANDOVER", "FLOW_MAIN"):
        if not s.get(key):
            raise MissingValue(key)              # listed with the other flows that couldn't be filled
    cmd = [sys.executable, str(ROOT / "connect-card-dispute/flows/build_card_dispute_flow.py"),
           "--region", ctx.region, "--account-id", ctx.account, "--instance-id", ctx.instance_id,
           "--workspace-id", s.need("ACXD_WORKSPACE_ID"), "--application-id", s.need("ACXD_DISPUTE_APP_ID"),
           "--alias", s.need("ACXD_DISPUTE_ALIAS"), "--handover-flow-id", s.need("FLOW_HUMAN_HANDOVER"),
           "--aria-flow-id", s.need("FLOW_MAIN"), "--output", str(out)]
    subprocess.run(cmd, check=True)
    return out.read_text()


def _render(ctx, key: str) -> str:
    text = _card_dispute_content(ctx) if key == "card_dispute" else SOURCES[key].read_text()
    rendered = rebase_checked(text, ctx.state, key)
    json.loads(rendered)                       # still JSON after the swaps
    out = Path(ctx.state.path).parent / f"{ctx.state.need('INSTANCE_ALIAS')}-flows" / f"{key}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered)                   # kept, so you can see exactly what was sent
    return rendered


def _send(ctx, what: str, call, **params) -> bool:
    try:
        call(**params)
        return True
    except ctx.client("connect").exceptions.InvalidContactFlowException as err:
        problems = err.response.get("problems") or err.response.get("Error", {})
        print(f"\033[0;31m[FAIL] Connect refused {what}: {json.dumps(problems)[:1500]}\033[0m")
    except ctx.client("connect").exceptions.InvalidContactFlowModuleException as err:
        print(f"\033[0;31m[FAIL] Connect refused {what}: {json.dumps(err.response.get('Problems') or err.response)[:1500]}\033[0m")
    return False


def fill(ctx) -> None:
    connect = ctx.client("connect")
    iid = ctx.instance_id
    only = set(ctx.extra)
    failed = []
    for key, module in CONNECT["modules"].items():
        if only and key not in only:
            continue
        try:
            content = rebase_checked((ROOT / module["file"]).read_text(), ctx.state, module["name"])
        except MissingValue as err:
            failed.append(f"{module['name']}: needs {err}")
            continue
        if _send(ctx, module["name"], connect.update_contact_flow_module_content, InstanceId=iid,
                 ContactFlowModuleId=ctx.state.need(f"MODULE_{key.upper()}"), Content=content):
            ok(f"Module {module['name']} filled")
        else:
            failed.append(module["name"])
    # Order matters only for readability: every target already exists as a shell.
    for key in ("screen_pop", "agent_assist", "human_handover", "mortgage_handover", "mortgage_entry", "card_dispute", "main"):
        if only and key not in only:
            continue
        name = CONNECT["flows"][key]["name"]
        try:
            content = _render(ctx, key)
        except MissingValue as err:
            failed.append(f"{name}: needs {err}")
            continue
        if _send(ctx, name, connect.update_contact_flow_content, InstanceId=iid,
                 ContactFlowId=ctx.state.need(f"FLOW_{key.upper()}"), Content=content):
            ok(f"Flow {name} filled and published")
        else:
            failed.append(name)
    if failed:
        fail("Not filled: " + "; ".join(failed) + ". Fix what it names, then run this step again "
             "(it only sends content; the flows' IDs don't change).")
    info(f"Each flow's content as sent: {Path(ctx.state.path).parent / (ctx.state.need('INSTANCE_ALIAS') + '-flows')}")


if __name__ == "__main__":
    cli(__doc__, {"shells": shells, "fill": fill})
