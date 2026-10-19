"""
main.py
=======
The Money Hub agent: a Strands agent served by AgentCore Runtime (HTTP
protocol: POST /invocations, GET /ping on port 8080, provided by
BedrockAgentCoreApp).

The bridge calls it once per customer turn with:
    {"customerId", "channel": "VOICE"|"CHAT", "firstName", "history": [{role, text}], "input"}
and gets back:
    {"reply", "finish": null | {"type": "COMPLETE"|"ESCALATE", "reason"},
     "tools": [{name, input, output, ok, startNs, endNs}], "model", "usage": {input, output},
     "startNs", "endNs"}

Stateless: the bridge keeps the conversation and sends it each turn, so any
runtime instance can answer and nothing is lost if one restarts.

The customer ID comes from the bridge (Connect's record of the contact), never
from the conversation. It is bound into the tools; the model can't change it.

ENVIRONMENT VARIABLES (set on the runtime; none are secrets)
    MODEL_ID           Bedrock model or inference profile (default eu.anthropic.claude-haiku-4-5-20251001-v1:0;
                       Haiku 5.5's profile is listed in eu-west-2 but not enabled on this account)
    MONEY_HUB_TABLE    DynamoDB table for categories, goals and links
    PUBLIC_BASE_URL    The Money Hub page's address, for links
    AWS_REGION         set by AgentCore
"""

from __future__ import annotations

import logging
import os
import time

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent, tool
from strands.models import BedrockModel, CacheConfig

from history import to_messages
from money_tools import Recorder, build_tools
from moneyhub import data
from moneyhub.service import MoneyHub
from moneyhub.store import DynamoStore, MemoryStore
from prompt import system_blocks

try:                                           # community tools; the agent still works without them
    from strands_tools import calculator     # current_time is deprecated; the tools give the data's own date
    COMMUNITY_TOOLS = [calculator]
except ImportError:                            # pragma: no cover
    COMMUNITY_TOOLS = []

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger("money-hub-agent")

MODEL_ID = os.environ.get("MODEL_ID", "eu.anthropic.claude-haiku-4-5-20251001-v1:0")
_TABLE = os.environ.get("MONEY_HUB_TABLE", "")
hub = MoneyHub(DynamoStore(_TABLE, time.time) if _TABLE else MemoryStore(time.time), time.time,
               page_url=os.environ.get("PUBLIC_BASE_URL", ""))
# Prompt caching: the tool definitions and the fixed part of the system prompt are the same on every turn and for
# every customer, and the conversation so far is the same as last turn's plus one exchange. Cache points on all three
# (Strands places them; the system prompt's is hand-placed in prompt.system_blocks) mean each turn reads only what's
# new. Before this, every turn re-read ~16,000 input tokens (19 Oct: no cached tokens at all).
CACHE = CacheConfig(strategy="auto", tools_ttl=True)
model = BedrockModel(model_id=MODEL_ID, region_name=os.environ.get("AWS_REGION", "eu-west-2"),
                     max_tokens=700, temperature=0.2, cache_config=CACHE)
# On a call, a hard cap on output keeps each spoken turn short; chat gets room for a short list.
voice_model = BedrockModel(model_id=MODEL_ID, region_name=os.environ.get("AWS_REGION", "eu-west-2"),
                           max_tokens=300, temperature=0.2, cache_config=CACHE)
app = BedrockAgentCoreApp()


def _usage(result) -> dict:
    usage = getattr(getattr(result, "metrics", None), "accumulated_usage", None) or {}
    return {"input": int(usage.get("inputTokens", 0) or 0), "output": int(usage.get("outputTokens", 0) or 0),
            "cacheRead": int(usage.get("cacheReadInputTokens", 0) or 0),
            "cacheWrite": int(usage.get("cacheWriteInputTokens", 0) or 0)}


@app.entrypoint
def invoke(payload: dict) -> dict:
    started = time.time_ns()
    customer_id = str(payload.get("customerId") or "")
    channel = "CHAT" if payload.get("channel") == "CHAT" else "VOICE"
    text = str(payload.get("input") or "").strip()
    if not customer_id or not text:
        return {"reply": "Sorry, I didn't catch that.", "finish": None, "tools": [], "model": MODEL_ID,
                "usage": {}, "startNs": started, "endNs": time.time_ns()}
    recorder = Recorder()
    messages, preface = to_messages(payload.get("history") or [])
    today = data.as_of()
    prompt = system_blocks(channel, str(payload.get("firstName") or ""), str(payload.get("pageView") or ""),
                           f"{today.day} {today:%B %Y}", preface)
    agent = Agent(model=model if channel == "CHAT" else voice_model, system_prompt=prompt, messages=messages,
                  callback_handler=None,
                  tools=[tool(t) for t in build_tools(hub, customer_id, channel, recorder, str(payload.get("loa") or ""))] + COMMUNITY_TOOLS)
    result = agent(text)
    reply = str(result).strip() or "Sorry, could you say that again?"
    usage = _usage(result)
    logger.info("turn tools=%d finish=%s ms=%d input=%d cacheRead=%d cacheWrite=%d", len(recorder.calls),
                recorder.finish["type"] if recorder.finish else "-", (time.time_ns() - started) // 1_000_000,
                usage["input"], usage["cacheRead"], usage["cacheWrite"])
    return {"reply": reply, "finish": recorder.finish, "tools": recorder.calls, "model": MODEL_ID,
            "usage": usage, "startNs": started, "endNs": time.time_ns()}


if __name__ == "__main__":
    app.run()
