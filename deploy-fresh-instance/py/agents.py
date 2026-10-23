"""The Connect AI agents: ARIA (v2, the orchestrator customers talk to) and the advisers' agent-assist and briefing
agents. Each: its prompt (published version), its configuration moved onto this instance (rebase.py: the gateway's
tool IDs, the knowledge base association, the guardrail, the Money Hub collaborator, the instance), only the gateway
tools that exist here, then a published version linked to its security profiles (an agent's tool calls run with
those, and fail without them).

    aria            connect-bot-flow-modular/ai-agent: prompt/aria-orchestration-prompt-v2.yaml + agent JSON
    agent-assist    connect-agent-assist/prompts/agent-assist-prompt-v3.yaml + the agent in ai-agent/reference/other-agents.json
    briefing        connect-agent-assist/prompts/agent-briefing-prompt-v1.yaml + the same file's briefing agent
"""

from __future__ import annotations

import json

from common import ROOT, TAGS, cli, fail, load_json, ok, paged, warn
from integrations import _tools
from rebase import MissingValue, rebase_checked

AI_AGENT = ROOT / "connect-bot-flow-modular" / "ai-agent"
ASSIST = ROOT / "connect-agent-assist" / "prompts"
OTHERS = load_json(AI_AGENT / "reference" / "other-agents.json")
ARIA = load_json(AI_AGENT / "agent" / "aria-conversation-agent-v2.json")


def _other(name: str) -> dict:
    agent = OTHERS[name]
    return agent.get("aiAgent", agent)


SPECS = {
    "aria": {
        "agent_name": ARIA["name"], "description": ARIA["description"], "type": ARIA["type"],
        "configuration": ARIA["configuration"], "prompt_file": AI_AGENT / ARIA["prompt"]["file"],
        "prompt": {k: ARIA["prompt"][k] for k in ("name", "modelId", "apiFormat", "type", "templateType")},
        "profiles": ("SP_ADMIN", "SP_AGENT", "SP_COLLABORATORS"),
    },
    "agent_assist": {
        "agent_name": "my-agent-assistant-agent", "description": "Helps advisers during a call (ARIA hand-offs)",
        "type": "ORCHESTRATION", "configuration": _other("my-agent-assistant-agent")["configuration"],
        "prompt_file": ASSIST / "agent-assist-prompt-v3.yaml",
        "prompt": {"name": "agent-assistance-prompt", "modelId": "global.anthropic.claude-sonnet-5",
                   "apiFormat": "MESSAGES", "type": "ORCHESTRATION", "templateType": "TEXT"},
        "profiles": ("SP_ADMIN", "SP_AGENT"),
    },
    "briefing": {
        "agent_name": "my-agent-briefing-agent", "description": "Briefs the adviser when a call arrives",
        "type": "ORCHESTRATION", "configuration": _other("my-agent-briefing-agent")["configuration"],
        "prompt_file": ASSIST / "agent-briefing-prompt-v1.yaml",
        "prompt": {"name": "my-briefing-agent-prompt", "modelId": "eu.anthropic.claude-haiku-4-5-20251001-v1:0",
                   "apiFormat": "MESSAGES", "type": "ORCHESTRATION", "templateType": "TEXT"},
        "profiles": ("SP_ADMIN", "SP_AGENT"),
    },
}


def _prompt(ctx, key: str, spec: dict) -> str:
    q, aid, upper = ctx.client("qconnect"), ctx.state.need("ASSISTANT_ID"), key.upper()
    meta = spec["prompt"]
    model = ctx.state.get(f"{upper}_MODEL_ID") or meta["modelId"]          # config can override per region
    text = rebase_checked(spec["prompt_file"].read_text(), ctx.state, meta["name"])
    pid = ctx.state.get(f"{upper}_PROMPT_ID")
    if not pid:
        have = [p for p in paged(q.list_ai_prompts, "aiPromptSummaries", token="nextToken", assistantId=aid)
                if p["name"] == meta["name"]]
        pid = have[0]["aiPromptId"] if have else q.create_ai_prompt(
            assistantId=aid, name=meta["name"], type=meta["type"], templateType=meta["templateType"], modelId=model,
            apiFormat=meta["apiFormat"], visibilityStatus="PUBLISHED", tags=TAGS,
            templateConfiguration={"textFullAIPromptEditTemplateConfiguration": {"text": text}})["aiPrompt"]["aiPromptId"]
        ctx.state.set(f"{upper}_PROMPT_ID", pid)
    if not ctx.state.get(f"{upper}_PROMPT_VERSION"):
        ctx.state.set(f"{upper}_PROMPT_VERSION", q.create_ai_prompt_version(assistantId=aid, aiPromptId=pid)["versionNumber"])
    ok(f"Prompt {meta['name']}: {pid}:{ctx.state.get(f'{upper}_PROMPT_VERSION')} ({model})")
    return f"{pid}:{ctx.state.get(f'{upper}_PROMPT_VERSION')}"


def _configuration(ctx, key: str, spec: dict, prompt: str) -> dict:
    text = json.dumps(spec["configuration"])
    if key == "aria":
        if text.count("${PROMPT_ID_V2}") != 1:
            fail("ARIA's configuration must name its prompt once (${PROMPT_ID_V2}).")
        text = text.replace("${PROMPT_ID_V2}", prompt)
    config = json.loads(rebase_checked(text, ctx.state, spec["agent_name"]))
    body = config["orchestrationAIAgentConfiguration"]
    available, gid = set(_tools(ctx)), ctx.state.need("GATEWAY_ID")
    kept, dropped = [], []
    for tool in body.get("toolConfigurations", []):
        tool_id = tool.get("toolId", "")
        if tool.get("toolType") == "MODEL_CONTEXT_PROTOCOL" and tool_id.startswith(f"gateway_{gid}__"):
            if tool_id[len(f"gateway_{gid}__"):] not in available:
                dropped.append(tool["toolName"])
                continue
        kept.append(tool)
    body["toolConfigurations"] = kept
    if dropped:
        warn(f"{spec['agent_name']}: left out tools this gateway doesn't have: {', '.join(dropped)}")
    return config


def _agent(ctx, key: str) -> None:
    spec, q, connect = SPECS[key], ctx.client("qconnect"), ctx.client("connect")
    aid, upper = ctx.state.need("ASSISTANT_ID"), key.upper()
    try:
        prompt = _prompt(ctx, key, spec)
        config = _configuration(ctx, key, spec, prompt)
    except MissingValue as err:
        fail(f"{spec['agent_name']} needs {err}. Run the steps that make it first.")
    agent_id = ctx.state.get(f"{upper}_AGENT_ID")
    if not agent_id:
        have = [a for a in paged(q.list_ai_agents, "aiAgentSummaries", token="nextToken", assistantId=aid)
                if a["name"] == spec["agent_name"]]
        agent_id = have[0]["aiAgentId"] if have else q.create_ai_agent(
            assistantId=aid, name=spec["agent_name"], type=spec["type"], visibilityStatus="PUBLISHED",
            description=spec["description"], configuration=config, tags=TAGS)["aiAgent"]["aiAgentId"]
        ctx.state.set(f"{upper}_AGENT_ID", agent_id)
    if not ctx.state.get(f"{upper}_AGENT_VERSION"):
        ctx.state.set(f"{upper}_AGENT_VERSION", q.create_ai_agent_version(assistantId=aid, aiAgentId=agent_id)["versionNumber"])
    version = ctx.state.get(f"{upper}_AGENT_VERSION")
    base = f"arn:aws:wisdom:{ctx.region}:{ctx.account}:ai-agent/{aid}/{agent_id}"
    profiles = [{"Id": ctx.state.need(p)} for p in spec["profiles"]]
    for arn in (base, f"{base}:{version}"):
        connect.associate_security_profiles(InstanceId=ctx.instance_id, EntityType="AI_AGENT", EntityArn=arn,
                                            SecurityProfiles=profiles)
    ctx.state.set(f"{upper}_AGENT_ARN", f"{base}:{version}")
    tools = len(config["orchestrationAIAgentConfiguration"].get("toolConfigurations", []))
    ok(f"{spec['agent_name']}: {agent_id}:{version}, {tools} tools, linked to {len(profiles)} security profiles")


if __name__ == "__main__":
    cli(__doc__, {"aria": lambda c: _agent(c, "aria"), "agent-assist": lambda c: _agent(c, "agent_assist"),
                  "briefing": lambda c: _agent(c, "briefing")})
