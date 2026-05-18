from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

DEFAULT_DB_PATH = os.getenv(
    "DB_PATH",
    os.path.join(os.path.dirname(__file__), "data", "brainstorm.db"),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    topics TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    summary TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    topics TEXT DEFAULT '[]',
    tags TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS memory_links (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relationship TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES memories(id),
    FOREIGN KEY (target_id) REFERENCES memories(id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    title, content, topics, tags,
    content='memories', content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, title, content, topics, tags)
    VALUES (new.rowid, new.title, new.content, new.topics, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, title, content, topics, tags)
    VALUES ('delete', old.rowid, old.title, old.content, old.topics, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, title, content, topics, tags)
    VALUES ('delete', old.rowid, old.title, old.content, old.topics, old.tags);
    INSERT INTO memories_fts(rowid, title, content, topics, tags)
    VALUES (new.rowid, new.title, new.content, new.topics, new.tags);
END;

CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    content TEXT DEFAULT '',
    tool_name TEXT DEFAULT '',
    tool_input TEXT DEFAULT '',
    tool_output TEXT DEFAULT '',
    latency_ms INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS audit_log_session_idx ON audit_log(session_id, created_at);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _resolve_db_path(db_path: str | None = None) -> str:
    return db_path or DEFAULT_DB_PATH


def _connect(db_path: str | None = None) -> sqlite3.Connection:
    resolved = _resolve_db_path(db_path)
    _ensure_parent(resolved)
    conn = sqlite3.connect(resolved, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _dump_list(values: list[str] | None) -> str:
    cleaned = []
    for value in values or []:
        if value is None:
            continue
        text = str(value).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return json.dumps(cleaned)


def _load_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        loaded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(loaded, list):
        return []
    return [str(item) for item in loaded if str(item).strip()]


def _merge_lists(*collections: list[str] | None) -> list[str]:
    merged: list[str] = []
    for collection in collections:
        for item in collection or []:
            text = str(item).strip()
            if text and text not in merged:
                merged.append(text)
    return merged


def _with_link_count_query(base_sql: str) -> str:
    return f"""
    SELECT
        m.*,
        (
            SELECT COUNT(*)
            FROM memory_links ml
            WHERE ml.source_id = m.id OR ml.target_id = m.id
        ) AS linked_count
    FROM ({base_sql}) base
    JOIN memories m ON m.id = base.id
    """


def _row_to_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    record = dict(row)
    for field in ("topics", "tags", "related_topics"):
        if field in record:
            record[field] = _load_list(record[field])
    if "linked_count" in record and record["linked_count"] is None:
        record["linked_count"] = 0
    return record


def init_db(db_path: str | None = None) -> dict[str, str]:
    resolved = _resolve_db_path(db_path)
    with _connect(resolved) as conn:
        conn.executescript(SCHEMA)
        conn.commit()
    return {"status": "ok", "db_path": resolved}


def create_session(title: str, topics: list[str] | None = None, db_path: str | None = None) -> dict[str, Any]:
    session_id = str(uuid.uuid4())
    now = _utcnow()
    record = {
        "id": session_id,
        "title": title.strip() or "Untitled Brainstorm",
        "topics": _merge_lists(topics or []),
        "created_at": now,
        "updated_at": now,
        "summary": "",
        "memory_count": 0,
    }
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO sessions (id, title, topics, created_at, updated_at, summary)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                record["id"],
                record["title"],
                _dump_list(record["topics"]),
                record["created_at"],
                record["updated_at"],
                record["summary"],
            ),
        )
        conn.commit()
    return record


def update_session_summary(session_id: str, summary: str, db_path: str | None = None) -> dict[str, Any]:
    updated_at = _utcnow()
    with _connect(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE sessions
            SET summary = ?, updated_at = ?
            WHERE id = ?
            """,
            (summary.strip(), updated_at, session_id),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"Session not found: {session_id}")
        conn.commit()
        row = conn.execute(
            """
            SELECT s.*, (
                SELECT COUNT(*) FROM memories mem WHERE mem.session_id = s.id
            ) AS memory_count
            FROM sessions s
            WHERE s.id = ?
            """,
            (session_id,),
        ).fetchone()
    return _row_to_dict(row)


def save_memory(
    session_id: str,
    title: str,
    content: str,
    topics: list[str] | None = None,
    tags: list[str] | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    memory_id = str(uuid.uuid4())
    created_at = _utcnow()
    clean_topics = _merge_lists(topics or [])
    clean_tags = _merge_lists(tags or [])
    with _connect(db_path) as conn:
        session_row = conn.execute(
            "SELECT id, topics FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if session_row is None:
            raise ValueError(f"Session not found: {session_id}")

        conn.execute(
            """
            INSERT INTO memories (id, session_id, title, content, topics, tags, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                session_id,
                title.strip() or "Untitled Insight",
                content.strip(),
                _dump_list(clean_topics),
                _dump_list(clean_tags),
                created_at,
            ),
        )

        merged_topics = _merge_lists(_load_list(session_row["topics"]), clean_topics)
        conn.execute(
            """
            UPDATE sessions
            SET topics = ?, updated_at = ?
            WHERE id = ?
            """,
            (_dump_list(merged_topics), created_at, session_id),
        )
        conn.commit()

        row = conn.execute(
            """
            SELECT
                m.*,
                0 AS linked_count
            FROM memories m
            WHERE m.id = ?
            """,
            (memory_id,),
        ).fetchone()
    return _row_to_dict(row)


def search_memories(query: str, limit: int = 10, db_path: str | None = None) -> list[dict[str, Any]]:
    clean_query = (query or "").strip()
    with _connect(db_path) as conn:
        if not clean_query:
            rows = conn.execute(
                """
                SELECT
                    m.*,
                    (
                        SELECT COUNT(*)
                        FROM memory_links ml
                        WHERE ml.source_id = m.id OR ml.target_id = m.id
                    ) AS linked_count
                FROM memories m
                ORDER BY m.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [_row_to_dict(row) for row in rows]

        try:
            rows = conn.execute(
                """
                SELECT
                    m.*,
                    (
                        SELECT COUNT(*)
                        FROM memory_links ml
                        WHERE ml.source_id = m.id OR ml.target_id = m.id
                    ) AS linked_count
                FROM memories_fts fts
                JOIN memories m ON m.rowid = fts.rowid
                WHERE memories_fts MATCH ?
                ORDER BY bm25(memories_fts)
                LIMIT ?
                """,
                (clean_query, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            wildcard = f"%{clean_query}%"
            rows = conn.execute(
                """
                SELECT
                    m.*,
                    (
                        SELECT COUNT(*)
                        FROM memory_links ml
                        WHERE ml.source_id = m.id OR ml.target_id = m.id
                    ) AS linked_count
                FROM memories m
                WHERE m.title LIKE ? OR m.content LIKE ? OR m.topics LIKE ? OR m.tags LIKE ?
                ORDER BY m.created_at DESC
                LIMIT ?
                """,
                (wildcard, wildcard, wildcard, wildcard, limit),
            ).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_memories_by_topic(topic: str, limit: int = 20, db_path: str | None = None) -> list[dict[str, Any]]:
    wildcard = f'%"{(topic or "").strip()}"%'
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                m.*,
                (
                    SELECT COUNT(*)
                    FROM memory_links ml
                    WHERE ml.source_id = m.id OR ml.target_id = m.id
                ) AS linked_count
            FROM memories m
            WHERE lower(m.topics) LIKE lower(?)
            ORDER BY m.created_at DESC
            LIMIT ?
            """,
            (wildcard, limit),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def create_link(
    source_id: str,
    target_id: str,
    relationship: str,
    db_path: str | None = None,
) -> dict[str, Any]:
    link_id = str(uuid.uuid4())
    created_at = _utcnow()
    with _connect(db_path) as conn:
        source = conn.execute("SELECT id FROM memories WHERE id = ?", (source_id,)).fetchone()
        target = conn.execute("SELECT id FROM memories WHERE id = ?", (target_id,)).fetchone()
        if source is None or target is None:
            raise ValueError("Both source and target memories must exist before linking")
        conn.execute(
            """
            INSERT INTO memory_links (id, source_id, target_id, relationship, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (link_id, source_id, target_id, relationship.strip(), created_at),
        )
        conn.commit()
    return {
        "id": link_id,
        "source_id": source_id,
        "target_id": target_id,
        "relationship": relationship.strip(),
        "created_at": created_at,
    }


def get_links_for_memory(memory_id: str, db_path: str | None = None) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                ml.id,
                ml.source_id,
                ml.target_id,
                ml.relationship,
                ml.created_at,
                CASE WHEN ml.source_id = ? THEN ml.target_id ELSE ml.source_id END AS related_id,
                CASE WHEN ml.source_id = ? THEN target.title ELSE source.title END AS related_title,
                CASE WHEN ml.source_id = ? THEN target.content ELSE source.content END AS related_content,
                CASE WHEN ml.source_id = ? THEN target.topics ELSE source.topics END AS related_topics
            FROM memory_links ml
            JOIN memories source ON source.id = ml.source_id
            JOIN memories target ON target.id = ml.target_id
            WHERE ml.source_id = ? OR ml.target_id = ?
            ORDER BY ml.created_at DESC
            """,
            (memory_id, memory_id, memory_id, memory_id, memory_id, memory_id),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def list_sessions(limit: int = 20, db_path: str | None = None) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                s.*,
                (
                    SELECT COUNT(*)
                    FROM memories m
                    WHERE m.session_id = s.id
                ) AS memory_count
            FROM sessions s
            ORDER BY s.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_session_memories(session_id: str, db_path: str | None = None) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                m.*,
                (
                    SELECT COUNT(*)
                    FROM memory_links ml
                    WHERE ml.source_id = m.id OR ml.target_id = m.id
                ) AS linked_count
            FROM memories m
            WHERE m.session_id = ?
            ORDER BY m.created_at DESC
            """,
            (session_id,),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def log_audit_event(
    session_id: str,
    event_type: str,
    content: str = "",
    tool_name: str = "",
    tool_input: Any = None,
    tool_output: Any = None,
    latency_ms: int = 0,
    db_path: str | None = None,
) -> None:
    event_id = str(uuid.uuid4())
    created_at = _utcnow()

    def _to_str(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, str):
            return v
        try:
            return json.dumps(v, ensure_ascii=False)
        except Exception:
            return str(v)

    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO audit_log
                (id, session_id, event_type, content, tool_name, tool_input, tool_output, latency_ms, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                session_id,
                event_type,
                _to_str(content),
                tool_name or "",
                _to_str(tool_input),
                _to_str(tool_output),
                int(latency_ms),
                created_at,
            ),
        )
        conn.commit()


def get_audit_log(session_id: str, limit: int = 500, db_path: str | None = None) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, session_id, event_type, content, tool_name,
                   tool_input, tool_output, latency_ms, created_at
            FROM audit_log
            WHERE session_id = ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_session(session_id: str, db_path: str | None = None) -> dict[str, Any] | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None
