from __future__ import annotations

import contextvars
import json
import os
import time
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from strands import Agent, tool
from strands.models import BedrockModel

import memory_store

load_dotenv()

SYSTEM_PROMPT = """You are a world-class brainstorming facilitator and strategic thinking partner.

## DOMAINS YOU COVER

- **Technology** — AI/ML, cloud, quantum, cybersecurity, edge, AR/VR/XR, robotics, biotech, space tech, semiconductors
- **Financial** — fintech, DeFi, capital markets, investment strategy, valuations, M&A, VC/PE, IPOs, financial modelling, risk
- **Business** — GTM strategy, scaling, org design, competitive positioning, PMF, pricing, partnerships, talent
- **Industry verticals** — healthtech, edtech, retail, manufacturing, energy/cleantech, media, logistics, legal tech, govtech

## HOW TO RESPOND (CRITICAL — READ CAREFULLY)

When the user asks a question or raises a topic, you MUST do all three of these in order:

1. **Answer the question directly and substantively first.** If they ask what the difference between X and Y is, explain it. If they ask how something works, explain it. Never redirect to "where do you want to go deeper?" without first giving a real answer.
2. **Add one non-obvious insight, angle, or connection** they may not have considered.
3. **End with exactly one forward question or direction** to keep momentum.

The response structure is: SUBSTANCE → INSIGHT → ONE QUESTION. Not: acknowledgement → options list.

## STRICT RESPONSE RULES

- Never start a response with words like "Linked.", "Noted.", "Understood.", "Great.", or any acknowledgement of tool calls. Tools run silently. Your first sentence must be substantive content.
- Never skip answering the question to instead ask what direction the user wants. Answer first, then ask.
- Do not list multiple directions and ask the user to pick. Give one clear direction at the end.
- Use `##` for major section headers, `###` for sub-sections.
- Use bullet lists (`-`) or numbered lists (`1.`) — never pipe tables.
- Bold (`**term**`) only the most important 2–3 terms per response.
- Keep paragraphs to 2–3 sentences maximum.
- Use `---` only once per response to separate major sections when needed.
- No nested bullet lists more than 1 level deep.
- Never start a response with a header — always start with a direct sentence.

## FACILITATION APPROACH

1. Challenge assumptions constructively and surface non-obvious angles.
2. Make cross-domain connections when genuinely useful — tech × finance, business × regulation, etc.
3. Identify second and third-order effects where relevant.
4. Suggest frameworks (SWOT, Porter's 5 Forces, Jobs-to-be-Done, etc.) only when they add real clarity.
5. Proactively save key insights using `save_memory` as the conversation progresses.
6. Search past memories when a new topic is raised and weave relevant prior thinking into your answer — never announce you searched.

## MEMORY USAGE

- Run `search_memories` silently at the start of any new topic. Weave findings into your answer naturally.
- Save each key insight or decision point with `save_memory`.
- Link related ideas across sessions with `link_ideas`.
- Never mention memory tool calls in your response. They are background operations.

## TONE

- Do not use emojis. None at all — not in headers, bullets, or inline text.
- Be sharp, direct, and intellectually rigorous.
- Push thinking further without burying the user in walls of text."""

DB_PATH = os.getenv(
    "DB_PATH",
    str(Path(__file__).parent / "data" / "brainstorm.db"),
)
CURRENT_SESSION_ID: str | None = None

_session_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "brainstorm_session_id",
    default=None,
)
_event_emitter_ctx: contextvars.ContextVar[Callable[[dict[str, Any]], None] | None] = contextvars.ContextVar(
    "brainstorm_event_emitter",
    default=None,
)
_audit_ctx: contextvars.ContextVar[Callable[..., None] | None] = contextvars.ContextVar(
    "brainstorm_audit",
    default=None,
)


def set_db_path(db_path: str) -> None:
    global DB_PATH
    DB_PATH = db_path


def bind_runtime(
    session_id: str,
    event_emitter: Callable[[dict[str, Any]], None] | None = None,
    audit_fn: Callable[..., None] | None = None,
) -> None:
    global CURRENT_SESSION_ID
    CURRENT_SESSION_ID = session_id
    _session_ctx.set(session_id)
    _event_emitter_ctx.set(event_emitter)
    _audit_ctx.set(audit_fn)


def _current_session_id() -> str:
    session_id = _session_ctx.get() or CURRENT_SESSION_ID
    if not session_id:
        raise RuntimeError("No active brainstorming session is bound to the agent tools")
    return session_id


def _emit(payload: dict[str, Any]) -> None:
    emitter = _event_emitter_ctx.get()
    if emitter is None:
        return
    try:
        emitter(payload)
    except Exception:
        pass


def _emit_tool(name: str, status: str, content: str | None = None) -> None:
    payload: dict[str, Any] = {"type": "tool", "name": name, "status": status}
    if content:
        payload["content"] = content
    _emit(payload)


def _audit(
    event_type: str,
    tool_name: str = "",
    tool_input: Any = None,
    tool_output: Any = None,
    latency_ms: int = 0,
    content: str = "",
) -> None:
    fn = _audit_ctx.get()
    if fn is None:
        return
    try:
        fn(
            event_type=event_type,
            content=content,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            latency_ms=latency_ms,
        )
    except Exception:
        pass


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


@tool
def save_memory(title: str, content: str, topics: list, tags: list) -> str:
    """Save a key insight or idea to persistent memory for future recall.

    Args:
        title: Short descriptive title for the memory
        content: Full content of the insight or idea
        topics: List of topic categories (e.g. ['fintech', 'AI', 'regulation'])
        tags: List of tags for searchability (e.g. ['risk', 'opportunity', 'trend'])
    """
    _emit_tool("save_memory", "running")
    tool_input = {"title": title, "content": content[:500], "topics": topics, "tags": tags}
    _audit("tool_call", tool_name="save_memory", tool_input=tool_input)
    t0 = time.monotonic()
    try:
        record = memory_store.save_memory(
            _current_session_id(),
            title=title,
            content=content,
            topics=[str(item) for item in topics or []],
            tags=[str(item) for item in tags or []],
            db_path=DB_PATH,
        )
        elapsed = int((time.monotonic() - t0) * 1000)
        _emit_tool("save_memory", "done", record["title"])
        _emit({"type": "memory_saved", "memory": record})
        result = {"status": "ok", "memory_id": record["id"], "title": record["title"]}
        _audit("tool_result", tool_name="save_memory", tool_output=result, latency_ms=elapsed)
        return _json({"status": "ok", "memory_id": record["id"], "title": record["title"], "memory": record})
    except Exception as exc:
        elapsed = int((time.monotonic() - t0) * 1000)
        _emit_tool("save_memory", "error", str(exc))
        _audit("tool_result", tool_name="save_memory", tool_output={"status": "error", "message": str(exc)}, latency_ms=elapsed)
        return _json({"status": "error", "message": str(exc)})


@tool
def search_memories(query: str) -> str:
    """Search through all past brainstorming memories to find relevant insights.

    Args:
        query: Search terms describing what you're looking for
    """
    _emit_tool("search_memories", "running")
    _audit("tool_call", tool_name="search_memories", tool_input={"query": query})
    t0 = time.monotonic()
    try:
        results = memory_store.search_memories(query, db_path=DB_PATH)
        elapsed = int((time.monotonic() - t0) * 1000)
        _emit_tool("search_memories", "done", f"{len(results)} matches")
        _audit("tool_result", tool_name="search_memories", tool_output={"count": len(results), "titles": [r.get("title") for r in results[:10]]}, latency_ms=elapsed)
        return _json({"status": "ok", "results": results})
    except Exception as exc:
        elapsed = int((time.monotonic() - t0) * 1000)
        _emit_tool("search_memories", "error", str(exc))
        _audit("tool_result", tool_name="search_memories", tool_output={"status": "error", "message": str(exc)}, latency_ms=elapsed)
        return _json({"status": "error", "message": str(exc)})


@tool
def get_memories_by_topic(topic: str) -> str:
    """Get all memories related to a specific topic.

    Args:
        topic: The topic to retrieve memories for
    """
    _emit_tool("get_memories_by_topic", "running")
    _audit("tool_call", tool_name="get_memories_by_topic", tool_input={"topic": topic})
    t0 = time.monotonic()
    try:
        results = memory_store.get_memories_by_topic(topic, db_path=DB_PATH)
        elapsed = int((time.monotonic() - t0) * 1000)
        _emit_tool("get_memories_by_topic", "done", f"{len(results)} matches")
        _audit("tool_result", tool_name="get_memories_by_topic", tool_output={"count": len(results)}, latency_ms=elapsed)
        return _json({"status": "ok", "results": results})
    except Exception as exc:
        elapsed = int((time.monotonic() - t0) * 1000)
        _emit_tool("get_memories_by_topic", "error", str(exc))
        _audit("tool_result", tool_name="get_memories_by_topic", tool_output={"status": "error", "message": str(exc)}, latency_ms=elapsed)
        return _json({"status": "error", "message": str(exc)})


@tool
def link_ideas(source_memory_id: str, target_memory_id: str, relationship: str) -> str:
    """Create a link between two related ideas/memories.

    Args:
        source_memory_id: ID of the first memory
        target_memory_id: ID of the second memory
        relationship: Description of how they relate (e.g. 'enables', 'contradicts', 'depends on', 'is example of')
    """
    _emit_tool("link_ideas", "running")
    _audit("tool_call", tool_name="link_ideas", tool_input={"source_memory_id": source_memory_id, "target_memory_id": target_memory_id, "relationship": relationship})
    t0 = time.monotonic()
    try:
        link = memory_store.create_link(
            source_id=source_memory_id,
            target_id=target_memory_id,
            relationship=relationship,
            db_path=DB_PATH,
        )
        elapsed = int((time.monotonic() - t0) * 1000)
        _emit_tool("link_ideas", "done", relationship)
        _audit("tool_result", tool_name="link_ideas", tool_output={"status": "ok", "link_id": link.get("id"), "relationship": relationship}, latency_ms=elapsed)
        return _json({"status": "ok", "link": link})
    except Exception as exc:
        elapsed = int((time.monotonic() - t0) * 1000)
        _emit_tool("link_ideas", "error", str(exc))
        _audit("tool_result", tool_name="link_ideas", tool_output={"status": "error", "message": str(exc)}, latency_ms=elapsed)
        return _json({"status": "error", "message": str(exc)})


@tool
def get_related_ideas(memory_id: str) -> str:
    """Get all ideas linked to a specific memory.

    Args:
        memory_id: The memory ID to find related ideas for
    """
    _emit_tool("get_related_ideas", "running")
    _audit("tool_call", tool_name="get_related_ideas", tool_input={"memory_id": memory_id})
    t0 = time.monotonic()
    try:
        links = memory_store.get_links_for_memory(memory_id, db_path=DB_PATH)
        elapsed = int((time.monotonic() - t0) * 1000)
        _emit_tool("get_related_ideas", "done", f"{len(links)} links")
        _audit("tool_result", tool_name="get_related_ideas", tool_output={"count": len(links)}, latency_ms=elapsed)
        return _json({"status": "ok", "results": links})
    except Exception as exc:
        elapsed = int((time.monotonic() - t0) * 1000)
        _emit_tool("get_related_ideas", "error", str(exc))
        _audit("tool_result", tool_name="get_related_ideas", tool_output={"status": "error", "message": str(exc)}, latency_ms=elapsed)
        return _json({"status": "error", "message": str(exc)})


@tool
def list_sessions() -> str:
    """List all past brainstorming sessions with their titles and topics."""
    _emit_tool("list_sessions", "running")
    _audit("tool_call", tool_name="list_sessions", tool_input={})
    t0 = time.monotonic()
    try:
        sessions = memory_store.list_sessions(db_path=DB_PATH)
        elapsed = int((time.monotonic() - t0) * 1000)
        _emit_tool("list_sessions", "done", f"{len(sessions)} sessions")
        _audit("tool_result", tool_name="list_sessions", tool_output={"count": len(sessions)}, latency_ms=elapsed)
        return _json({"status": "ok", "results": sessions})
    except Exception as exc:
        elapsed = int((time.monotonic() - t0) * 1000)
        _emit_tool("list_sessions", "error", str(exc))
        _audit("tool_result", tool_name="list_sessions", tool_output={"status": "error", "message": str(exc)}, latency_ms=elapsed)
        return _json({"status": "error", "message": str(exc)})


@tool
def get_session_insights(session_id: str) -> str:
    """Get all saved insights from a specific past brainstorming session.

    Args:
        session_id: The session ID to retrieve insights for
    """
    _emit_tool("get_session_insights", "running")
    _audit("tool_call", tool_name="get_session_insights", tool_input={"session_id": session_id})
    t0 = time.monotonic()
    try:
        insights = memory_store.get_session_memories(session_id, db_path=DB_PATH)
        elapsed = int((time.monotonic() - t0) * 1000)
        _emit_tool("get_session_insights", "done", f"{len(insights)} insights")
        _audit("tool_result", tool_name="get_session_insights", tool_output={"count": len(insights)}, latency_ms=elapsed)
        return _json({"status": "ok", "results": insights})
    except Exception as exc:
        elapsed = int((time.monotonic() - t0) * 1000)
        _emit_tool("get_session_insights", "error", str(exc))
        _audit("tool_result", tool_name="get_session_insights", tool_output={"status": "error", "message": str(exc)}, latency_ms=elapsed)
        return _json({"status": "error", "message": str(exc)})


def create_agent(
    session_id: str,
    event_emitter: Callable[[dict[str, Any]], None] | None = None,
    audit_fn: Callable[..., None] | None = None,
) -> Agent:
    global CURRENT_SESSION_ID
    CURRENT_SESSION_ID = session_id
    bind_runtime(session_id, event_emitter, audit_fn)
    model = BedrockModel(
        model_id=os.getenv("BEDROCK_MODEL_ID", "eu.anthropic.claude-sonnet-4-6"),
        region_name=os.getenv("AWS_REGION", "eu-west-1"),
    )
    return Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools=[
            save_memory,
            search_memories,
            get_memories_by_topic,
            link_ideas,
            get_related_ideas,
            list_sessions,
            get_session_insights,
        ],
    )
