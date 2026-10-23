"""Moves the repo's committed flow and agent JSON onto the new instance.

Every builder in the repo (build_flows.py, build_mortgage_handover_flow.py, connect-agent-assist's builders,
ai-agent/build_agent.py) bakes in the IDs of the system as it runs today. Rather than parameterise each one, this
swaps each old ID (templates/live-map.json) for the new ID of the resource with the same name (the state file),
then refuses to hand back anything that still carries an old ID: a flow that points at the old instance would
import fine and fail on the first call.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from common import TEMPLATES, State, load_json

LIVE = load_json(TEMPLATES / "live-map.json")


class MissingValue(Exception):
    """A new ID this text needs isn't in the state yet (its step hasn't run, or was skipped)."""


@dataclass
class Swap:
    old: str          # a literal, or a regex when versioned
    new: str
    versioned: bool = False   # old ID optionally followed by ":<version>": every version becomes new (with its version)


def _need(state: State, key: str, old: str) -> str:
    value = state.get(key)
    if not value:
        raise MissingValue(f"{key} (to replace {old})")
    return value


def swaps(state: State) -> list[Swap]:
    """Old → new, most specific first (versioned agent and guardrail ARNs before the account and region)."""
    out: list[Swap] = []
    lazy: list[tuple[str, str]] = []       # (old, state key): resolved only if the old value is in the text

    def add(old: str, key: str) -> None:
        lazy.append((old, key))

    for name, old in LIVE["flows"].items():
        add(old, "FLOW_MAIN" if name == "legacy_conversation_bot_flow" else f"FLOW_{name.upper()}")
    for name, old in LIVE["modules"].items():
        add(old, f"MODULE_{name.upper()}")
    add(LIVE["instance"], "INSTANCE_ID")
    add(LIVE["assistant"], "ASSISTANT_ID")
    add(LIVE["kb_association"], "KB_ASSOC_ID")
    add(LIVE["gateway"], "GATEWAY_ID")
    add(LIVE["apps"]["money_hub"], "APP_MONEY_HUB_ID")
    for name, old in LIVE["hours"].items():
        add(old, "HOURS_BASIC")
    for key, old in (("ACXD_WORKSPACE_ID", LIVE["acxd"]["workspace"]),
                     ("ACXD_MORTGAGE_APP_ID", LIVE["acxd"]["mortgage_app"]),
                     ("ACXD_MORTGAGE_ALIAS", LIVE["acxd"]["mortgage_alias"]),
                     ("ACXD_DISPUTE_APP_ID", LIVE["acxd"]["dispute_app"]),
                     ("ACXD_DISPUTE_ALIAS", LIVE["acxd"]["dispute_alias"])):
        add(old, key)
    # The Lex alias appears as "<bot>/<alias>" inside its ARN.
    lazy.append((LIVE["lex_bot_alias"], "LEX_BOT_ALIAS_PATH"))
    queues = json.loads(state.get("QUEUES_JSON") or "{}")
    for name, old in LIVE["queues"].items():
        lazy.append((old, f"QUEUES_JSON[{name}]"))

    resolved = []
    for old, key in lazy:
        if key.startswith("QUEUES_JSON["):
            name = key[len("QUEUES_JSON["):-1]
            resolved.append((old, queues.get(name), key))
        else:
            resolved.append((old, state.get(key), key))
    # Versioned: AI agents, prompts and the guardrail are referenced as id:version.
    for name, old in LIVE["ai_agents"].items():
        out.append(Swap(old, f"{state.get(f'{name.upper()}_AGENT_ID') or ''}:{state.get(f'{name.upper()}_AGENT_VERSION') or ''}",
                        versioned=True))
    for name, old in LIVE["ai_prompts"].items():
        out.append(Swap(old, f"{state.get(f'{name.upper()}_PROMPT_ID') or ''}:{state.get(f'{name.upper()}_PROMPT_VERSION') or ''}",
                        versioned=True))
    out.append(Swap(LIVE["guardrail"], f"{state.get('GUARDRAIL_ID') or ''}:{state.get('GUARDRAIL_VERSION') or ''}",
                    versioned=True))
    for old, new, key in resolved:
        out.append(Swap(old, new or f"\x00MISSING:{key}"))
    out.append(Swap(LIVE["account"], state.get("ACCOUNT_ID") or "\x00MISSING:ACCOUNT_ID"))
    if state.get("REGION") and state.get("REGION") != LIVE["region"]:
        out.append(Swap(f":{LIVE['region']}:", f":{state.get('REGION')}:"))
        out.append(Swap(f".{LIVE['region']}.", f".{state.get('REGION')}."))
    return out


def rebase(text: str, state: State) -> str:
    """text with every old ID swapped. Raises MissingValue naming each new ID it still needs."""
    missing = []
    for swap in swaps(state):
        if swap.versioned:
            pattern = re.compile(re.escape(swap.old) + r"(:\d+|:\$LATEST)?")
            if not pattern.search(text):
                continue
            new_id, _, version = swap.new.partition(":")
            if not new_id or not version:
                missing.append(f"the new ID and version for {swap.old}")
                continue
            # A bare ID (no version) is replaced by the bare new ID; id:version by the new id:version.
            text = pattern.sub(lambda m: f"{new_id}:{version}" if m.group(1) else new_id, text)
        elif swap.old in text:
            if swap.new.startswith("\x00MISSING:"):
                missing.append(f"{swap.new[len(chr(0) + 'MISSING:'):]} (to replace {swap.old})")
                continue
            text = text.replace(swap.old, swap.new)
    if missing:
        raise MissingValue("; ".join(sorted(set(missing))))
    return text


def leftovers(text: str) -> list[str]:
    """Old IDs still in text (each with a little context): must be empty before anything is sent to AWS."""
    olds = [LIVE["account"], LIVE["instance"], LIVE["assistant"], LIVE["kb_association"], LIVE["guardrail"],
            LIVE["gateway"], LIVE["lex_bot_alias"], LIVE["apps"]["money_hub"]]
    for group in ("flows", "modules", "queues", "hours", "ai_agents", "ai_prompts", "acxd"):
        olds += list(LIVE[group].values())
    found = []
    for old in olds:
        at = text.find(old)
        if at >= 0:
            found.append(f"{old} … {text[max(0, at - 40):at + len(old) + 20]!r}")
    return found


def rebase_checked(text: str, state: State, what: str) -> str:
    out = rebase(text, state)
    left = leftovers(out)
    if left:
        raise MissingValue(f"{what} still has old IDs: " + "; ".join(left[:5]))
    return out
