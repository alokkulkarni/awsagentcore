"""
transcript/models.py
====================
Local conversation transcript — the canonical artifact produced by a single
evaluation run.

The transcript is written to disk as JSON so that:
  - Evaluations can be replayed without re-running the conversation.
  - Transcripts can be inspected and shared for debugging.
  - The LLM judge reads the local file, not the live Connect API.

Usage::

    transcript = Transcript(scenario_id="account_query", scenario_name="Balance Enquiry")
    transcript.add_turn(TurnRole.CUSTOMER, "Hi, what's my balance?")
    transcript.add_turn(TurnRole.AGENT, "Hi James, your balance is £1,234.56.", latency_ms=820)
    transcript.end()
    transcript.save(Path("transcripts/account_query_2026-04-28T09-52.json"))

    # Later — reload and evaluate
    t2 = Transcript.load(Path("transcripts/account_query_2026-04-28T09-52.json"))
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class TurnRole(str, Enum):
    CUSTOMER = "customer"
    AGENT    = "agent"
    SYSTEM   = "system"


@dataclass
class Turn:
    """A single message in the conversation."""

    role: TurnRole
    content: str
    display_name: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    latency_ms: Optional[int] = None   # ms from send → receive (agent turns only)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["role"] = self.role.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Turn":
        d = dict(d)
        d["role"] = TurnRole(d["role"])
        return cls(**d)


@dataclass
class Transcript:
    """
    Full conversation transcript for one scenario run.

    Attributes
    ----------
    scenario_id:    snake_case identifier from the YAML file stem
    scenario_name:  human-readable name from the YAML ``name:`` field
    customer_id:    value of EVAL_CUSTOMER_ID used for this run
    channel:        "chat" | "voice"
    mode:           "scripted" | "agent"
    turns:          ordered list of conversation turns
    started_at:     ISO-8601 UTC when connect() was called
    ended_at:       ISO-8601 UTC when disconnect() was called (None until then)
    metadata:       free-form dict for adapter-specific extras (contact_id, etc.)
    """

    scenario_id:   str
    scenario_name: str
    customer_id:   str = ""
    channel:       str = "chat"
    mode:          str = "scripted"
    turns:         list[Turn] = field(default_factory=list)
    started_at:    str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    ended_at:      Optional[str] = None
    metadata:      dict[str, Any] = field(default_factory=dict)

    # ── Mutation helpers ──────────────────────────────────────────────────────

    def add_turn(
        self,
        role: TurnRole,
        content: str,
        display_name: str = "",
        latency_ms: Optional[int] = None,
    ) -> Turn:
        turn = Turn(
            role=role,
            content=content,
            display_name=display_name,
            latency_ms=latency_ms,
        )
        self.turns.append(turn)
        return turn

    def end(self) -> None:
        """Record the end timestamp."""
        self.ended_at = datetime.now(timezone.utc).isoformat()

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "2.0",
            "scenario_id":    self.scenario_id,
            "scenario_name":  self.scenario_name,
            "customer_id":    self.customer_id,
            "channel":        self.channel,
            "mode":           self.mode,
            "started_at":     self.started_at,
            "ended_at":       self.ended_at,
            "metadata":       self.metadata,
            "turns":          [t.to_dict() for t in self.turns],
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))

    @classmethod
    def load(cls, path: Path) -> "Transcript":
        raw = json.loads(path.read_text())
        turns = [Turn.from_dict(t) for t in raw.pop("turns", [])]
        raw.pop("schema_version", None)
        return cls(turns=turns, **raw)

    # ── Compatibility bridge for v1 judge ─────────────────────────────────────

    def to_conversation_log_dict(self) -> dict[str, Any]:
        """
        Return a dict that mirrors the v1 ``ConversationLog`` structure so that
        ported judge code can consume this transcript without modification.
        """
        v1_turns = []
        for t in self.turns:
            if t.role == TurnRole.CUSTOMER:
                v1_turns.append({
                    "role": "customer",
                    "content": t.content,
                    "timestamp": t.timestamp,
                    "aria_response": None,
                    "latency_ms": None,
                    "tool_calls": [],
                })
            elif t.role == TurnRole.AGENT and v1_turns:
                last = v1_turns[-1]
                if last["aria_response"] is None:
                    last["aria_response"] = t.content
                    last["latency_ms"] = t.latency_ms

        return {
            "scenario_name": self.scenario_name,
            "customer_id":   self.customer_id,
            "turns":         v1_turns,
            "metadata":      self.metadata,
        }

    # ── Display helpers ───────────────────────────────────────────────────────

    @property
    def agent_turns(self) -> list[Turn]:
        return [t for t in self.turns if t.role == TurnRole.AGENT]

    @property
    def customer_turns(self) -> list[Turn]:
        return [t for t in self.turns if t.role == TurnRole.CUSTOMER]

    @property
    def turn_count(self) -> int:
        return len([t for t in self.turns if t.role in (TurnRole.CUSTOMER, TurnRole.AGENT)])

    def __repr__(self) -> str:
        return (
            f"Transcript(scenario={self.scenario_id!r}, "
            f"turns={self.turn_count}, ended={self.ended_at is not None})"
        )
