"""
Session store abstraction for chat history.

Backends
--------
  SqliteSessionStore   (local / Docker)  — default, stores in /data/sessions.db
  DynamoDBSessionStore (cloud)           — set SESSION_BACKEND=dynamodb
                                           Requires: SESSION_TABLE_NAME
                                           Optional: SESSION_BUCKET_NAME (for large sessions)

Usage
-----
  store = create_session_store()
"""

import json
import logging
import os
import sqlite3
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

LOGGER = logging.getLogger(__name__)
MAX_SESSIONS = 100


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Abstract base ──────────────────────────────────────────────────────────────

class SessionStore(ABC):
    @abstractmethod
    def list_sessions(self) -> List[Dict]:
        """Return summaries (id, title, createdAt, updatedAt) — no messages."""

    @abstractmethod
    def get_session(self, session_id: str) -> Optional[Dict]:
        """Return full session dict including messages, or None if not found."""

    @abstractmethod
    def upsert_session(self, session: Dict) -> None:
        """Create or fully replace a session (including messages)."""

    @abstractmethod
    def delete_session(self, session_id: str) -> None:
        """Delete one session by id."""

    @abstractmethod
    def delete_all(self) -> None:
        """Delete every session."""


# ── SQLite backend ─────────────────────────────────────────────────────────────

class SqliteSessionStore(SessionStore):
    """Thread-safe SQLite store. Uses a per-thread connection."""

    def __init__(self, db_path: str = "/app/data/sessions.db"):
        self._db_path = db_path
        self._local = threading.local()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        LOGGER.info("SqliteSessionStore ready at %s", db_path)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        if not getattr(self._local, "conn", None):
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id          TEXT PRIMARY KEY,
                    title       TEXT NOT NULL DEFAULT 'New session',
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL,
                    messages    TEXT NOT NULL DEFAULT '[]'
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC)"
            )
            conn.commit()

    # ── Public API ─────────────────────────────────────────────────────────────

    def list_sessions(self) -> List[Dict]:
        rows = self._conn().execute(
            "SELECT id, title, created_at, updated_at FROM sessions"
            " ORDER BY updated_at DESC LIMIT ?",
            (MAX_SESSIONS,),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "createdAt": r["created_at"],
                "updatedAt": r["updated_at"],
            }
            for r in rows
        ]

    def get_session(self, session_id: str) -> Optional[Dict]:
        row = self._conn().execute(
            "SELECT id, title, created_at, updated_at, messages"
            " FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "title": row["title"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "messages": json.loads(row["messages"]),
        }

    def upsert_session(self, session: Dict) -> None:
        messages_json = json.dumps(session.get("messages", []))
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, title, created_at, updated_at, messages)
                VALUES (:id, :title, :createdAt, :updatedAt, :messages)
                ON CONFLICT(id) DO UPDATE SET
                    title      = excluded.title,
                    updated_at = excluded.updated_at,
                    messages   = excluded.messages
                """,
                {
                    "id": session["id"],
                    "title": session.get("title", "New session"),
                    "createdAt": session.get("createdAt", _now()),
                    "updatedAt": session.get("updatedAt", _now()),
                    "messages": messages_json,
                },
            )
            conn.commit()
        self._prune()

    def delete_session(self, session_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()

    def delete_all(self) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM sessions")
            conn.commit()

    def _prune(self):
        with self._conn() as conn:
            conn.execute(
                """
                DELETE FROM sessions WHERE id NOT IN (
                    SELECT id FROM sessions ORDER BY updated_at DESC LIMIT ?
                )
                """,
                (MAX_SESSIONS,),
            )
            conn.commit()


# ── DynamoDB + S3 backend ──────────────────────────────────────────────────────

class DynamoDBSessionStore(SessionStore):
    """
    Cloud backend.
    - Session metadata + small message payloads → DynamoDB (SESSION_TABLE_NAME)
    - Large message payloads (> 300 KB) → S3   (SESSION_BUCKET_NAME)

    DynamoDB table key schema:  HASH key "id" (String)
    """

    _S3_THRESHOLD = 300_000  # bytes

    def __init__(self):
        import boto3  # lazy import so SQLite path has no boto3 dep
        self._table_name = os.environ["SESSION_TABLE_NAME"]
        self._bucket = os.environ.get("SESSION_BUCKET_NAME")
        region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        ddb = boto3.resource("dynamodb", region_name=region)
        self._table = ddb.Table(self._table_name)
        self._s3 = boto3.client("s3", region_name=region) if self._bucket else None
        LOGGER.info(
            "DynamoDBSessionStore ready — table=%s bucket=%s", self._table_name, self._bucket
        )

    def list_sessions(self) -> List[Dict]:
        resp = self._table.scan(
            ProjectionExpression="id, title, createdAt, updatedAt",
            Limit=MAX_SESSIONS,
        )
        items = resp.get("Items", [])
        items.sort(key=lambda x: x.get("updatedAt", ""), reverse=True)
        return items

    def get_session(self, session_id: str) -> Optional[Dict]:
        resp = self._table.get_item(Key={"id": session_id})
        item = resp.get("Item")
        if not item:
            return None
        if item.get("messagesS3Key") and self._s3:
            obj = self._s3.get_object(Bucket=self._bucket, Key=item["messagesS3Key"])
            item["messages"] = json.loads(obj["Body"].read())
            del item["messagesS3Key"]
        elif isinstance(item.get("messages"), str):
            item["messages"] = json.loads(item["messages"])
        else:
            item.setdefault("messages", [])
        return item

    def upsert_session(self, session: Dict) -> None:
        messages_json = json.dumps(session.get("messages", []))
        item: Dict[str, Any] = {
            "id": session["id"],
            "title": session.get("title", "New session"),
            "createdAt": session.get("createdAt", _now()),
            "updatedAt": session.get("updatedAt", _now()),
        }
        if self._s3 and len(messages_json.encode()) > self._S3_THRESHOLD:
            key = f"sessions/{session['id']}/messages.json"
            self._s3.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=messages_json.encode(),
                ContentType="application/json",
            )
            item["messagesS3Key"] = key
        else:
            item["messages"] = messages_json
        self._table.put_item(Item=item)

    def delete_session(self, session_id: str) -> None:
        item = self.get_session(session_id)
        if item and item.get("messagesS3Key") and self._s3:
            try:
                self._s3.delete_object(Bucket=self._bucket, Key=item["messagesS3Key"])
            except Exception:  # pylint: disable=broad-except
                LOGGER.debug('Suppressed exception', exc_info=True)
        self._table.delete_item(Key={"id": session_id})

    def delete_all(self) -> None:
        resp = self._table.scan(ProjectionExpression="id")
        with self._table.batch_writer() as batch:
            for item in resp.get("Items", []):
                batch.delete_item(Key={"id": item["id"]})


# ── Factory ────────────────────────────────────────────────────────────────────

_store: Optional[SessionStore] = None
_store_lock = threading.Lock()


def create_session_store() -> SessionStore:
    """Return singleton session store. Thread-safe."""
    global _store  # pylint: disable=global-statement
    if _store is None:
        with _store_lock:
            if _store is None:
                backend = os.environ.get("SESSION_BACKEND", "sqlite").lower()
                if backend == "dynamodb":
                    _store = DynamoDBSessionStore()
                else:
                    # Default lives under DATA_DIR (the writable volume) — the
                    # container runs as a non-root user that cannot mkdir /data.
                    db_path = os.environ.get("SESSION_DB_PATH") or os.path.join(
                        os.environ.get("DATA_DIR", "/app/data"), "sessions.db"
                    )
                    _store = SqliteSessionStore(db_path=db_path)
    return _store
