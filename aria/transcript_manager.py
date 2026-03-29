"""ARIA Transcript Manager — saves conversation transcripts for training and validation.

**Local mode** (default — when running via ``main.py``):
  Writes a Markdown ``.md`` file to ``TRANSCRIPT_DIR`` (default: ``./transcripts``).
  File path: ``transcripts/{customer_id or 'anonymous'}/{YYYY-MM-DD}/{HH-MM-SS}_{session_id[:8]}.md``

**S3 mode** (AgentCore / cloud deployment):
  Writes the same Markdown content to Amazon S3 when ``TRANSCRIPT_S3_BUCKET`` is set.
  S3 key: ``{prefix}/{customer_id}/{YYYY}/{MM}/{DD}/{HH-MM-SS}_{session_id}.md``
  Set ``TRANSCRIPT_S3_PREFIX`` to override the key prefix (default: ``transcripts``).

**Both** (set ``TRANSCRIPT_STORE=both``):
  Writes to local file AND S3 simultaneously.  Useful for local testing with a
  real S3 bucket, or during the migration from local to cloud deployment.

Environment variables
---------------------
TRANSCRIPT_DIR         Local directory for .md files.  Default: ``./transcripts``
TRANSCRIPT_S3_BUCKET   S3 bucket name.  Required for S3 / cloud mode.
TRANSCRIPT_S3_PREFIX   S3 key prefix.   Default: ``transcripts``
TRANSCRIPT_STORE       ``local`` | ``s3`` | ``both``.
                       Auto-detected: ``s3`` when TRANSCRIPT_S3_BUCKET is set,
                       ``local`` otherwise.  Override with this variable.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("aria.transcript")

# ---------------------------------------------------------------------------
# Configuration (read once at import time)
# ---------------------------------------------------------------------------

_TRANSCRIPT_DIR    = os.getenv("TRANSCRIPT_DIR",    "./transcripts")
_S3_BUCKET         = os.getenv("TRANSCRIPT_S3_BUCKET", "").strip()
_S3_PREFIX         = os.getenv("TRANSCRIPT_S3_PREFIX", "transcripts").strip("/")

def _resolve_store() -> str:
    explicit = os.getenv("TRANSCRIPT_STORE", "").strip().lower()
    if explicit in ("local", "s3", "both"):
        return explicit
    return "s3" if _S3_BUCKET else "local"

_STORE = _resolve_store()


# ---------------------------------------------------------------------------
# TranscriptManager
# ---------------------------------------------------------------------------

class TranscriptManager:
    """Records an ARIA conversation and saves it as a Markdown file.

    Usage::

        tm = TranscriptManager(
            session_id="abc-123",
            customer_id="CUST-001",
            channel="chat",
            authenticated=True,
        )
        tm.add_turn("ARIA",     "Hello James! How can I help?")
        tm.add_turn("Customer", "What is my balance?")
        tm.add_turn("ARIA",     "Your balance is £5,240.00.")
        tm.save()   # writes .md file and/or uploads to S3
    """

    def __init__(
        self,
        session_id:    str,
        customer_id:   Optional[str],
        channel:       str,
        authenticated: bool,
    ) -> None:
        self.session_id    = session_id
        self.customer_id   = customer_id or "anonymous"
        self.channel       = channel
        self.authenticated = authenticated
        self._started_at   = datetime.now(timezone.utc)
        self._turns: list[dict] = []   # {"role": str, "text": str, "ts": datetime}
        self._ended_at: Optional[datetime] = None
        self._saved = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_turn(self, role: str, text: str) -> None:
        """Append a conversation turn.

        Args:
            role: ``"ARIA"`` or ``"Customer"``
            text: The spoken/typed utterance.
        """
        cleaned = self._strip_markdown(text).strip()
        if not cleaned:
            return
        self._turns.append({
            "role": role,
            "text": cleaned,
            "ts":   datetime.now(timezone.utc),
        })

    def save(self) -> None:
        """Finalise and save the transcript.  Safe to call multiple times."""
        if self._saved:
            return
        self._saved      = True
        self._ended_at   = datetime.now(timezone.utc)
        content          = self._render_markdown()
        filename         = self._build_filename()

        store = _STORE
        if store in ("local", "both"):
            self._save_local(filename, content)
        if store in ("s3", "both") and _S3_BUCKET:
            self._save_s3(filename, content)

    # ------------------------------------------------------------------
    # Markdown renderer
    # ------------------------------------------------------------------

    def _render_markdown(self) -> str:
        started  = self._started_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        ended    = self._ended_at.strftime("%Y-%m-%d %H:%M:%S UTC") if self._ended_at else "—"
        duration = ""
        if self._ended_at:
            secs = int((self._ended_at - self._started_at).total_seconds())
            duration = f"{secs // 60}m {secs % 60}s"

        lines = [
            "# ARIA Session Transcript",
            "",
            "| Field | Value |",
            "|-------|-------|",
            f"| **Session ID** | `{self.session_id}` |",
            f"| **Customer ID** | `{self.customer_id}` |",
            f"| **Channel** | {self.channel} |",
            f"| **Started** | {started} |",
            f"| **Authenticated** | {'Yes' if self.authenticated else 'No'} |",
            "",
            "---",
            "",
        ]

        for turn in self._turns:
            ts_str = turn["ts"].strftime("%H:%M:%S")
            lines.append(f"**[{ts_str}] {turn['role']}:** {turn['text']}")
            lines.append("")

        lines += [
            "---",
            "",
            f"*Session ended: {ended}*  ",
        ]
        if duration:
            lines.append(f"*Duration: {duration}*")

        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # Filename / key builder
    # ------------------------------------------------------------------

    def _build_filename(self) -> str:
        """Return a path-like string: ``{customer_id}/{YYYY-MM-DD}/{HH-MM-SS}_{session_id[:8]}.md``"""
        date_str = self._started_at.strftime("%Y-%m-%d")
        time_str = self._started_at.strftime("%H-%M-%S")
        sid8     = self.session_id.replace("-", "")[:8]
        safe_cid = re.sub(r"[^\w\-]", "_", self.customer_id)
        return f"{safe_cid}/{date_str}/{time_str}_{sid8}.md"

    # ------------------------------------------------------------------
    # Local save
    # ------------------------------------------------------------------

    def _save_local(self, filename: str, content: str) -> None:
        path = Path(_TRANSCRIPT_DIR) / filename
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            logger.info("Transcript saved → %s", path)
        except Exception as exc:
            logger.error("Failed to save local transcript: %s", exc)

    # ------------------------------------------------------------------
    # S3 save
    # ------------------------------------------------------------------

    def _save_s3(self, filename: str, content: str) -> None:
        # filename is already {customer_id}/{date}/{time_sid}.md
        # Build full S3 key replacing the date component with YYYY/MM/DD for
        # better partitioning (Athena / Glue friendly).
        parts = filename.split("/", maxsplit=2)
        if len(parts) == 3:
            cid, date_str, rest = parts
            yyyy, mm, dd = date_str.split("-")
            s3_key = f"{_S3_PREFIX}/{cid}/{yyyy}/{mm}/{dd}/{rest}"
        else:
            s3_key = f"{_S3_PREFIX}/{filename}"

        try:
            import boto3
            s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION", "us-east-1"))
            s3.put_object(
                Bucket=_S3_BUCKET,
                Key=s3_key,
                Body=content.encode("utf-8"),
                ContentType="text/markdown",
                Metadata={
                    "session-id":    self.session_id,
                    "customer-id":   self.customer_id,
                    "channel":       self.channel,
                    "authenticated": "true" if self.authenticated else "false",
                },
            )
            logger.info("Transcript uploaded → s3://%s/%s", _S3_BUCKET, s3_key)
        except Exception as exc:
            logger.error("Failed to upload transcript to S3: %s", exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """Remove basic markdown so transcripts stay readable as plain text."""
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = re.sub(r"\*(.+?)\*",     r"\1", text)
        text = re.sub(r"__(.+?)__",     r"\1", text)
        text = re.sub(r"_(.+?)_",       r"\1", text)
        text = re.sub(r"#{1,6}\s*",     "",    text)
        text = re.sub(r"^\s*[-*]\s+",   "",    text, flags=re.MULTILINE)
        return text
