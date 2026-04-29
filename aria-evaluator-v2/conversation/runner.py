"""
conversation/runner.py
======================
Orchestrates a single scenario run: drives the conversation via a BaseAdapter,
records every turn into a Transcript, and saves the Transcript as a JSON file.

The ScenarioRunner is deliberately adapter-agnostic — it only depends on
BaseAdapter.  Swap the adapter to target a different agent.

Supported scenario modes
------------------------
mode: scripted   turns:
                   - customer: "Hello, what's my balance?"
                 Fixed list of customer messages; runner sends each in order.

mode: agent      goal: "..."
                 customer_persona: "..."
                 max_turns: 12
                 opening_message: "Hi, I'd like to check my balance"
                 AgentDriver (Bedrock) plays the customer role and decides what
                 to say next based on ARIA's last response.

Usage::

    runner = ScenarioRunner(
        adapter=ConnectWebSocketAdapter(...),
        driver=AgentDriver(model_id="eu.anthropic.claude-..."),
        scenario_dir=Path("scenarios"),
        transcript_dir=Path("transcripts"),
        response_timeout=90.0,
    )
    transcript = await runner.run(scenario_data, customer_id="CUST-001")
    transcript.save(Path("transcripts/account_query_2026-04-28.json"))
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from adapters import AdapterMessage, BaseAdapter, SessionEndedError
from conversation.driver import AgentDriver, GOAL_ACHIEVED
from transcript.models import Transcript, TurnRole

logger = logging.getLogger(__name__)


class ScenarioRunner:
    """
    Runs a single scenario and returns a completed Transcript.

    Parameters
    ----------
    adapter:
        A concrete BaseAdapter (e.g. ConnectWebSocketAdapter).  The runner
        calls connect() / send_message() / receive() / disconnect() only.
    driver:
        AgentDriver instance used for agent-mode scenarios.
        Ignored for scripted scenarios.
    transcript_dir:
        Directory where completed transcripts are auto-saved as JSON.
    response_timeout:
        Default seconds to wait for the agent to respond per turn.
        Scenario YAML ``default_timeout_seconds`` overrides this.
    """

    def __init__(
        self,
        adapter: BaseAdapter,
        driver: AgentDriver,
        transcript_dir: Path = Path("transcripts"),
        response_timeout: float = 90.0,
        customer_name: str = "",
    ) -> None:
        self.adapter = adapter
        self.driver = driver
        self.transcript_dir = transcript_dir
        self.response_timeout = response_timeout
        self.customer_name = customer_name

    # ── Public API ────────────────────────────────────────────────────────────

    async def run(
        self,
        scenario: dict[str, Any],
        customer_id: str = "",
    ) -> Transcript:
        """
        Execute the scenario and return a completed Transcript.

        The Transcript is also saved to ``transcript_dir`` before returning.
        If an error occurs mid-run the partial transcript is saved and
        re-raised so the caller can report the failure.
        """
        scenario_name = scenario.get("name", "unknown")
        scenario_id = _to_id(scenario_name)
        channel = scenario.get("channel", "chat")
        mode = scenario.get("mode", "scripted")
        authenticated = scenario.get("authenticated", False)
        timeout = float(scenario.get("default_timeout_seconds", self.response_timeout))

        transcript = Transcript(
            scenario_id=scenario_id,
            scenario_name=scenario_name,
            customer_id=customer_id,
            channel=channel,
            mode=mode,
        )

        print(f"\n  ▶  {scenario_name}", flush=True)

        try:
            await self.adapter.connect(
                session_id=scenario_id,
                customer_id=customer_id if authenticated else None,
                authenticated=authenticated,
                channel=channel,
                scenario_name=scenario_name,
            )
            transcript.metadata["contact_id"] = getattr(
                self.adapter, "_contact_id", None
            )

            if mode == "scripted":
                await self._run_scripted(scenario, transcript, timeout)
            else:
                await self._run_agent(scenario, transcript, timeout)

        except SessionEndedError:
            # The agent closed the chat — this is a normal terminal condition, not a failure.
            transcript.metadata["session_ended_by_agent"] = True
            logger.info("Scenario %r: session ended by agent (normal)", scenario_name)
        except Exception as exc:
            transcript.metadata["error"] = str(exc)
            logger.error("Scenario %r failed: %s", scenario_name, exc, exc_info=True)
            raise
        finally:
            transcript.end()
            await self.adapter.disconnect()
            self._save_transcript(transcript)

        return transcript

    # ── Scripted mode ─────────────────────────────────────────────────────────

    async def _run_scripted(
        self,
        scenario: dict[str, Any],
        transcript: Transcript,
        timeout: float,
    ) -> None:
        turns = scenario.get("turns", [])
        for i, turn_def in enumerate(turns):
            if isinstance(turn_def, str):
                customer_msg = turn_def.strip()
                turn_timeout = timeout
            elif isinstance(turn_def, dict):
                customer_msg = (
                    turn_def.get("customer")
                    or turn_def.get("send")
                    or turn_def.get("content")
                    or turn_def.get("message")
                    or ""
                ).strip()
                turn_timeout = float(turn_def.get("timeout_seconds", timeout))
            else:
                continue

            if not customer_msg:
                continue

            print(f"    → customer: {customer_msg}", flush=True)
            transcript.add_turn(TurnRole.CUSTOMER, customer_msg)

            t0 = time.monotonic()
            try:
                await self.adapter.send_message(customer_msg, simulate_typing=True)
            except SessionEndedError:
                print(f"    ℹ  Session ended by agent — conversation complete", flush=True)
                transcript.metadata["session_ended_by_agent"] = True
                return
            agent_msg = await self.adapter.receive(timeout=turn_timeout)
            latency_ms = int((time.monotonic() - t0) * 1000)

            if agent_msg is None:
                print(
                    f"    ⏰ TIMEOUT waiting for agent response (turn {i+1}, {turn_timeout:.0f}s)",
                    flush=True,
                )
                transcript.metadata.setdefault("timeouts", []).append(i + 1)
                continue

            print(f"    ← agent: {agent_msg.content[:120]}", flush=True)
            transcript.add_turn(
                TurnRole.AGENT,
                agent_msg.content,
                display_name=agent_msg.display_name,
                latency_ms=latency_ms,
            )

            turn_delay = float(scenario.get("turn_delay_seconds", 1.0))
            if turn_delay > 0:
                await asyncio.sleep(turn_delay)

    # ── Agent mode ────────────────────────────────────────────────────────────

    def _inject_customer_name(self, text: str) -> str:
        """Substitute {customer_name} and {customer_first_name} tokens in scenario text."""
        if not self.customer_name:
            return text
        first_name = self.customer_name.split()[0]
        return text.replace("{customer_name}", self.customer_name) \
                   .replace("{customer_first_name}", first_name)

    async def _run_agent(
        self,
        scenario: dict[str, Any],
        transcript: Transcript,
        timeout: float,
    ) -> None:
        goal = self._inject_customer_name(scenario.get("goal", ""))
        customer_persona = self._inject_customer_name(
            scenario.get("customer_persona", "You are a bank customer.")
        )
        max_turns = int(scenario.get("max_turns", 10))
        opening_message = scenario.get("opening_message", "Hello, I need some help please.")
        turn_delay = float(scenario.get("turn_delay_seconds", 1.5))

        history: list[dict[str, str]] = []
        last_agent_response = ""

        for turn_num in range(max_turns):
            if turn_num == 0:
                # First customer message is always the opening_message.
                customer_msg = opening_message
            else:
                # AgentDriver decides the next customer message.
                result = self.driver.generate_next_message(
                    goal=goal,
                    customer_persona=customer_persona,
                    history=history,
                    last_aria_response=last_agent_response,
                )

                if result is GOAL_ACHIEVED:
                    print(f"    ✅ Goal achieved after {turn_num} turn(s)", flush=True)
                    transcript.metadata["goal_achieved"] = True
                    break

                if result == "[DRIVER_ERROR]":
                    print("    ⚠ Driver error — stopping scenario early", flush=True)
                    transcript.metadata["driver_error"] = True
                    break

                customer_msg = str(result)

            print(f"    → customer: {customer_msg}", flush=True)
            transcript.add_turn(TurnRole.CUSTOMER, customer_msg)
            history.append({"role": "customer", "content": customer_msg})

            t0 = time.monotonic()
            try:
                await self.adapter.send_message(customer_msg, simulate_typing=True)
            except SessionEndedError:
                print(f"    ℹ  Session ended by agent — conversation complete", flush=True)
                transcript.metadata["session_ended_by_agent"] = True
                break

            print(f"    ⏳ waiting for agent", end="", flush=True)
            agent_msg: Optional[AdapterMessage] = None
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                chunk = await self.adapter.receive(timeout=min(remaining, 2.0))
                print(".", end="", flush=True)
                if chunk is not None:
                    # Guard: if the message is identical to what we just sent,
                    # it is a stale echo that slipped through — discard and keep waiting.
                    if chunk.content.strip() == customer_msg.strip():
                        logger.debug("_run_agent: received echo of our own message — discarding")
                        continue
                    agent_msg = chunk
                    break

            elapsed = time.monotonic() - t0
            print(f" ({elapsed:.1f}s)", flush=True)

            if agent_msg is None:
                print(f"    ⏰ TIMEOUT waiting for agent response (turn {turn_num+1})", flush=True)
                transcript.metadata.setdefault("timeouts", []).append(turn_num + 1)
                break

            last_agent_response = agent_msg.content
            print(f"    ← agent:\n{agent_msg.content}\n", flush=True)
            transcript.add_turn(
                TurnRole.AGENT,
                agent_msg.content,
                display_name=agent_msg.display_name,
                latency_ms=int(elapsed * 1000),
            )
            history.append({"role": "aria", "content": agent_msg.content})

            # ── Terminal-event detection (before generating next customer turn) ──
            if _is_escalation_msg(agent_msg.content):
                print(f"    ☎  Agent escalated to human — ending conversation", flush=True)
                transcript.metadata["escalated_to_human"] = True
                transcript.metadata["goal_achieved"] = True  # escalation IS a valid outcome
                break

            if _is_guardrail_block(agent_msg.content):
                print(f"    🛡  Guardrail fired — ending conversation", flush=True)
                transcript.metadata["guardrail_block"] = True
                break

            if turn_delay > 0:
                await asyncio.sleep(turn_delay)
        else:
            print(f"    ℹ max_turns ({max_turns}) reached", flush=True)
            transcript.metadata["max_turns_reached"] = True

    # ── Transcript persistence ────────────────────────────────────────────────

    def _save_transcript(self, transcript: Transcript) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        filename = f"{transcript.scenario_id}_{ts}.json"
        path = self.transcript_dir / filename
        transcript.save(path)
        print(f"    💾 transcript saved → {path}", flush=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

_ESCALATION_PHRASES: list[str] = [
    "connect you to one of my colleague",
    "transfer you to",
    "put you through to",
    "speak to one of our",
    "connecting you to",
    "one of our agents will",
    "please wait while",
    "human agent",
    "live agent",
    "escalating",
]

_GUARDRAIL_PHRASES: list[str] = [
    "blocked output text by guardrail",
    "blocked output text",
    "guardrail",
]


def _is_escalation_msg(content: str) -> bool:
    lower = content.lower()
    return any(phrase in lower for phrase in _ESCALATION_PHRASES)


def _is_guardrail_block(content: str) -> bool:
    lower = content.lower()
    return any(phrase in lower for phrase in _GUARDRAIL_PHRASES)


def _to_id(name: str) -> str:
    """Convert a human-readable scenario name to a safe snake_case id."""
    import re
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")
