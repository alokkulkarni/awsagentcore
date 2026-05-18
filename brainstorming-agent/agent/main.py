from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import memory_store
import safety
from strands_agent import bind_runtime, create_agent, set_db_path

load_dotenv()

APP_DIR = Path(__file__).parent
DB_PATH = os.getenv("DB_PATH", str(APP_DIR / "data" / "brainstorm.db"))
MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "eu.anthropic.claude-sonnet-4-6")


class SessionCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    topics: list[str] = Field(default_factory=list)


class SessionSummaryRequest(BaseModel):
    summary: str = Field(..., min_length=1)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await asyncio.to_thread(memory_store.init_db, DB_PATH)
    set_db_path(DB_PATH)
    yield


app = FastAPI(title="Brainstorming Agent", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _check_db_connection() -> str:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("SELECT 1")
    finally:
        conn.close()
    return "connected"


def _clean_response(text: Any) -> str:
    if text is None:
        return ""
    return str(text).strip()


def _extract_response_text(agent: Any, result: Any, start_index: int) -> str:
    text = _clean_response(result)
    if text:
        return text

    for message in reversed(agent.messages[start_index:]):
        if message.get("role") != "assistant":
            continue
        content = message.get("content", [])
        if isinstance(content, str):
            candidate = _clean_response(content)
            if candidate:
                return candidate
            continue
        for block in content:
            if isinstance(block, str):
                candidate = _clean_response(block)
            elif isinstance(block, dict):
                candidate = _clean_response(block.get("text") or block.get("content"))
            else:
                candidate = ""
            if candidate:
                return candidate
    return ""


async def _drain_events(websocket: WebSocket, queue: asyncio.Queue[dict[str, Any]]) -> None:
    while not queue.empty():
        event = await queue.get()
        await websocket.send_json(event)


def _stream_chunks(text: str) -> list[str]:
    words = text.split()
    chunks: list[str] = []
    for index, word in enumerate(words):
        suffix = " " if index < len(words) - 1 else ""
        chunks.append(f"{word}{suffix}")
    return chunks


@app.get("/health")
async def health() -> dict[str, str]:
    db_status = await asyncio.to_thread(_check_db_connection)
    return {"status": "ok", "model": MODEL_ID, "db": db_status}


@app.post("/sessions")
async def create_session(request: SessionCreateRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            memory_store.create_session,
            request.title,
            request.topics,
            DB_PATH,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/sessions")
async def list_sessions() -> list[dict[str, Any]]:
    return await asyncio.to_thread(memory_store.list_sessions, 50, DB_PATH)


@app.get("/sessions/{session_id}/memories")
async def get_session_memories(session_id: str) -> list[dict[str, Any]]:
    return await asyncio.to_thread(memory_store.get_session_memories, session_id, DB_PATH)


@app.get("/sessions/{session_id}/audit")
async def get_session_audit(session_id: str, limit: int = Query(500)) -> list[dict[str, Any]]:
    return await asyncio.to_thread(memory_store.get_audit_log, session_id, limit, DB_PATH)


@app.get("/memories/search")
async def search_memories(q: str = Query("", alias="q")) -> list[dict[str, Any]]:
    return await asyncio.to_thread(memory_store.search_memories, q, 25, DB_PATH)


@app.get("/memories/{memory_id}/links")
async def get_memory_links(memory_id: str) -> list[dict[str, Any]]:
    return await asyncio.to_thread(memory_store.get_links_for_memory, memory_id, DB_PATH)


@app.post("/sessions/{session_id}/summary")
async def save_session_summary(
    session_id: str,
    request: SessionSummaryRequest,
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            memory_store.update_session_summary,
            session_id,
            request.summary,
            DB_PATH,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.websocket("/ws/{session_id}")
async def brainstorm_ws(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def emit_event(event: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(event_queue.put_nowait, event)

    def audit_fn(
        event_type: str,
        content: str = "",
        tool_name: str = "",
        tool_input: Any = None,
        tool_output: Any = None,
        latency_ms: int = 0,
    ) -> None:
        try:
            memory_store.log_audit_event(
                session_id=session_id,
                event_type=event_type,
                content=content,
                tool_name=tool_name,
                tool_input=tool_input,
                tool_output=tool_output,
                latency_ms=latency_ms,
                db_path=DB_PATH,
            )
        except Exception:
            pass

    agent = create_agent(session_id, event_emitter=emit_event, audit_fn=audit_fn)

    session_record = await asyncio.to_thread(memory_store.get_session, session_id, DB_PATH)
    session_topics: list[str] = session_record.get("topics", []) if session_record else []
    recent_assistant_texts: list[str] = []

    # Send a ping every 30s so nginx doesn't drop the idle connection
    async def _ping_loop() -> None:
        while True:
            await asyncio.sleep(30)
            try:
                await websocket.send_json({"type": "ping"})
            except Exception:
                return

    ping_task = asyncio.create_task(_ping_loop())
    try:
        while True:
            try:
                try:
                    data = await asyncio.wait_for(websocket.receive_json(), timeout=60)
                except asyncio.TimeoutError:
                    try:
                        await websocket.send_json({"type": "ping"})
                    except Exception:
                        break
                    continue

                msg_type = data.get("type")
                if msg_type in ("ping", "pong"):
                    continue
                if msg_type != "message":
                    continue

                user_message = str(data.get("content", "")).strip()
                if not user_message:
                    await websocket.send_json({"type": "error", "content": "Message content is required."})
                    continue

                # ── Input safety guard ────────────────────────────────────────
                input_check = safety.check_harmful_content(user_message)
                if input_check["blocked"]:
                    await asyncio.to_thread(
                        memory_store.log_audit_event,
                        session_id, "content_blocked",
                        user_message[:300],
                        input_check["category"] or "",
                        {
                            "source": "user_input",
                            "matched_text": input_check.get("matched_text"),
                            "rule_pattern": input_check.get("rule_pattern"),
                        },
                        {
                            "category": input_check["category"],
                            "reason": input_check["reason"],
                            "reply": input_check["reply"],
                        },
                        0, DB_PATH,
                    )
                    await websocket.send_json({
                        "type": "safety_blocked",
                        "category": input_check["category"],
                        "reason": input_check["reason"],
                        "reply": input_check["reply"],
                    })
                    continue

                await asyncio.to_thread(
                    memory_store.log_audit_event,
                    session_id, "user_message", user_message, "", None, None, 0, DB_PATH,
                )

                invoke_start = loop.time()

                async def run_agent_call() -> str:
                    def _invoke() -> str:
                        bind_runtime(session_id, emit_event, audit_fn)
                        start_index = len(agent.messages)
                        result = agent(user_message)
                        return _extract_response_text(agent, result, start_index)

                    return await asyncio.to_thread(_invoke)

                task = asyncio.create_task(run_agent_call())

                while not task.done():
                    try:
                        event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                        await websocket.send_json(event)
                    except asyncio.TimeoutError:
                        continue

                response_text = await task
                await _drain_events(websocket, event_queue)

                latency_ms = int((loop.time() - invoke_start) * 1000)

                if not response_text:
                    response_text = "I've thought through that angle, but I need a little more detail to respond well. Could you sharpen the core question or constraint?"

                # ── Output safety guard ───────────────────────────────────────
                output_check = safety.check_harmful_content(response_text)
                if output_check["blocked"]:
                    await asyncio.to_thread(
                        memory_store.log_audit_event,
                        session_id, "content_blocked", "[agent output blocked]",
                        output_check["category"] or "",
                        {
                            "source": "agent_output",
                            "matched_text": output_check.get("matched_text"),
                            "rule_pattern": output_check.get("rule_pattern"),
                        },
                        {
                            "category": output_check["category"],
                            "reason": output_check["reason"],
                            "reply": output_check["reply"],
                        },
                        0, DB_PATH,
                    )
                    response_text = "I'm not able to continue in that direction. Let's refocus — what aspect of the topic would you like to explore next?"

                # ── Drift + bias analysis ─────────────────────────────────────
                drift_result = safety.analyze_drift(session_topics, response_text, recent_assistant_texts)
                bias_result = safety.analyze_bias(response_text)
                safety_data = {**drift_result, **bias_result}

                await asyncio.to_thread(
                    memory_store.log_audit_event,
                    session_id, "safety_analysis",
                    f"Drift {drift_result['drift_score']}/100 · Bias {bias_result['bias_score']}/100",
                    "", None, safety_data, 0, DB_PATH,
                )

                # ── Log assistant response ────────────────────────────────────
                await asyncio.to_thread(
                    memory_store.log_audit_event,
                    session_id, "assistant_response", response_text, "", None, None, latency_ms, DB_PATH,
                )

                recent_assistant_texts.append(response_text)
                if len(recent_assistant_texts) > 6:
                    recent_assistant_texts.pop(0)

                for chunk in _stream_chunks(response_text):
                    await websocket.send_json({"type": "token", "content": chunk})
                    await asyncio.sleep(0.02)

                await websocket.send_json({"type": "done", "content": response_text})
                await websocket.send_json({"type": "safety_analysis", **safety_data})

            except WebSocketDisconnect:
                break
            except Exception as exc:
                try:
                    await asyncio.to_thread(
                        memory_store.log_audit_event,
                        session_id, "error", str(exc), "", None, None, 0, DB_PATH,
                    )
                    await websocket.send_json({"type": "error", "content": str(exc)})
                except Exception:
                    break
    finally:
        ping_task.cancel()
        try:
            await ping_task
        except asyncio.CancelledError:
            pass
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8200, reload=True)
