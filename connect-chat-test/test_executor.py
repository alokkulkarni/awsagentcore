"""
Test scenario orchestration.

Loads YAML scenario definitions and executes them through Amazon Connect
chat sessions, returning structured ScenarioResult objects with per-turn
detail for reporting and Zephyr write-back.
"""

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from connect_chat_runner import (
    ChatSendError,
    ChatStartError,
    ConnectChatSession,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TurnResult:
    """Result of a single conversation turn (send + receive + assert)."""

    turn_index: int
    sent: str
    expected: list[str]          # [] when no expect_contains defined
    actual: Optional[str]        # None on TIMEOUT or ERROR
    status: str                  # PASS | FAIL | TIMEOUT | ERROR
    duration_ms: int
    error_message: Optional[str] = None


@dataclass
class ScenarioResult:
    """Result of an entire scenario (all turns)."""

    zephyr_issue_key: str
    scenario_name: str
    overall_status: str          # PASSED | FAILED | ERROR
    turns: list[TurnResult] = field(default_factory=list)
    started_at: str = ""         # ISO 8601
    finished_at: str = ""        # ISO 8601
    duration_ms: int = 0
    zephyr_execution_id: Optional[int] = None
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# Scenario loading
# ---------------------------------------------------------------------------


def load_scenarios(scenarios_dir: str) -> list[dict]:
    """
    Load all *.yaml / *.yml scenario files from *scenarios_dir*.

    Handles multi-document YAML files (separated by ``---``).
    Validates that each document has the required fields.

    Returns a flat list of scenario dicts, each guaranteed to have:
      - zephyr_issue_key  (str)
      - name              (str)
      - contact_flow_id   (str)  – falls back to CONNECT_CONTACT_FLOW_ID env var
      - turns             (list of dicts)

    Raises FileNotFoundError if *scenarios_dir* doesn't exist.
    Raises ValueError on missing required fields.
    """
    base = Path(scenarios_dir)
    if not base.exists():
        raise FileNotFoundError(
            f"Scenarios directory not found: {base.resolve()}\n"
            "Create it and add at least one *.yaml scenario file."
        )

    scenario_files = sorted(base.glob("**/*.yaml")) + sorted(
        base.glob("**/*.yml")
    )
    if not scenario_files:
        raise FileNotFoundError(
            f"No *.yaml / *.yml files found under {base.resolve()}"
        )

    scenarios: list[dict] = []
    for path in scenario_files:
        with path.open(encoding="utf-8") as fh:
            for doc in yaml.safe_load_all(fh):
                if doc is None:
                    continue
                _validate_scenario(doc, str(path))
                _apply_defaults(doc)
                scenarios.append(doc)

    logger.info("Loaded %d scenario(s) from %s", len(scenarios), scenarios_dir)
    return scenarios


def _validate_scenario(doc: dict, path: str) -> None:
    for required_field in ("zephyr_issue_key", "name", "turns"):
        if not doc.get(required_field):
            raise ValueError(
                f"Scenario in {path} is missing required field '{required_field}'"
            )
    if not isinstance(doc["turns"], list) or len(doc["turns"]) == 0:
        raise ValueError(
            f"Scenario '{doc['zephyr_issue_key']}' in {path} has an empty 'turns' list"
        )
    for i, turn in enumerate(doc["turns"]):
        if not turn.get("send"):
            raise ValueError(
                f"Scenario '{doc['zephyr_issue_key']}' turn #{i + 1} is missing 'send'"
            )


def _apply_defaults(doc: dict) -> None:
    """Fill in contact_flow_id from env if not in the YAML document."""
    if not doc.get("contact_flow_id"):
        flow_id = os.environ.get("CONNECT_CONTACT_FLOW_ID", "")
        if not flow_id:
            raise ValueError(
                f"Scenario '{doc['zephyr_issue_key']}' has no 'contact_flow_id' "
                "and CONNECT_CONTACT_FLOW_ID environment variable is not set."
            )
        doc["contact_flow_id"] = flow_id


# ---------------------------------------------------------------------------
# Scenario execution
# ---------------------------------------------------------------------------


def execute_scenario(
    scenario: dict,
    instance_id: str,
    region: str,
    default_timeout: float,
    poll_interval: float,
    max_poll_attempts: int,
    chat_duration_minutes: int,
) -> ScenarioResult:
    """
    Execute a single scenario through an Amazon Connect chat session.

    Execution continues through all turns even if an individual turn fails,
    so the report shows the full picture rather than stopping at the first
    failure.

    Returns a ScenarioResult with overall_status PASSED only when every
    turn's status is PASS.
    """
    key = scenario["zephyr_issue_key"]
    name = scenario["name"]
    contact_flow_id = scenario["contact_flow_id"]
    turns_config: list[dict] = scenario["turns"]

    started_at = datetime.now(timezone.utc).isoformat()
    wall_start = time.monotonic()

    result = ScenarioResult(
        zephyr_issue_key=key,
        scenario_name=name,
        overall_status="PASSED",
        started_at=started_at,
    )

    session = ConnectChatSession(
        instance_id=instance_id,
        contact_flow_id=contact_flow_id,
        region=region,
        display_name="AutomationBot",
        chat_duration_minutes=chat_duration_minutes,
        poll_interval=poll_interval,
        max_poll_attempts=max_poll_attempts,
    )

    # Attempt to start the chat session
    try:
        session.start()
    except ChatStartError as exc:
        logger.error("Session start failed for %s: %s", key, exc)
        result.overall_status = "ERROR"
        result.error_message = str(exc)
        # Mark every turn as ERROR since we couldn't even start
        result.turns = [
            TurnResult(
                turn_index=i + 1,
                sent=t.get("send", ""),
                expected=_normalise_expect(t.get("expect_contains")),
                actual=None,
                status="ERROR",
                duration_ms=0,
                error_message="Chat session failed to start",
            )
            for i, t in enumerate(turns_config)
        ]
        _finalise(result, wall_start)
        return result

    # Execute each conversation turn
    try:
        for idx, turn_cfg in enumerate(turns_config):
            turn = _execute_turn(
                session=session,
                turn_index=idx + 1,
                turn_cfg=turn_cfg,
                default_timeout=default_timeout,
            )
            result.turns.append(turn)
            if turn.status != "PASS":
                result.overall_status = "FAILED"
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error executing scenario %s", key)
        result.overall_status = "ERROR"
        result.error_message = str(exc)
    finally:
        session.disconnect()

    _finalise(result, wall_start)
    return result


def _execute_turn(
    session: ConnectChatSession,
    turn_index: int,
    turn_cfg: dict,
    default_timeout: float,
) -> TurnResult:
    """Execute a single send → receive → assert turn."""
    sent = turn_cfg["send"]
    expected = _normalise_expect(turn_cfg.get("expect_contains"))
    timeout = float(turn_cfg.get("timeout_seconds", default_timeout))

    turn_start = time.monotonic()

    # Send
    try:
        session.send_message(sent)
    except ChatSendError as exc:
        return TurnResult(
            turn_index=turn_index,
            sent=sent,
            expected=expected,
            actual=None,
            status="ERROR",
            duration_ms=int((time.monotonic() - turn_start) * 1000),
            error_message=str(exc),
        )

    # Receive
    actual = session.receive_response(timeout=timeout)
    duration_ms = int((time.monotonic() - turn_start) * 1000)

    if actual is None:
        return TurnResult(
            turn_index=turn_index,
            sent=sent,
            expected=expected,
            actual=None,
            status="TIMEOUT",
            duration_ms=duration_ms,
            error_message=f"No bot response within {timeout}s",
        )

    # Assert
    if expected:
        all_match = all(e.lower() in actual.lower() for e in expected)
        status = "PASS" if all_match else "FAIL"
    else:
        status = "PASS"

    return TurnResult(
        turn_index=turn_index,
        sent=sent,
        expected=expected,
        actual=actual,
        status=status,
        duration_ms=duration_ms,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise_expect(value) -> list[str]:
    """Coerce expect_contains to a list of strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _finalise(result: ScenarioResult, wall_start: float) -> None:
    result.finished_at = datetime.now(timezone.utc).isoformat()
    result.duration_ms = int((time.monotonic() - wall_start) * 1000)
