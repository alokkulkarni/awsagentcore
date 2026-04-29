"""
channels/chat_adapter.py
========================
Thin wrapper around the Amazon Connect Chat API that drives a scripted
multi-turn conversation with ARIA and returns a structured ConversationLog.

Builds on the same approach as connect-chat-test/connect_chat_runner.py
but extends it with:
  - Per-turn metadata (latency, ARIA role)
  - Tool call detection from ARIA's response text
  - Structured ConversationLog returned for LLM-as-judge evaluation
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Flow noise patterns — messages sent by the Connect flow itself (not by the
# AI agent) that should never appear as ARIA's "response" in the evaluation.
#
# IMPORTANT: patterns must be specific enough to avoid false-positive matches
# against real ARIA responses.  ARIA itself greets with phrases like
# "welcome to Nationwide Building Society chat. I'm ARIA…" so a generic
# "Welcome to Nationwide" pattern would wrongly suppress ARIA's greeting.
#
# Use the most distinctive fragment of each flow-injected message:
#   • "Let me transfer you to one of our agents"  — unique to flow routing
#   • "Welcome to Meridian Bank !!" — the "!!" is characteristic of flow blocks
#   • "Hello !!" — Connect flow blocks often prefix with "Hello !!"
#
# Per the Amazon Connect Participant API docs, both the Connect flow system
# messages AND Amazon Connect AI Agent (ARIA) messages may appear with
# ParticipantRole "SYSTEM".  The CUSTOM_BOT role is valid for AI agents but
# may also appear as SYSTEM depending on instance configuration, so content-
# based filtering is required to distinguish flow noise from real AI responses.
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_FLOW_NOISE: list[str] = [
    "Let me transfer you to one of our agents",
    "Welcome to Meridian Bank !!",
    "Welcome to Nationwide Building Society !!",
    "Hello !! Welcome to",
]

# ─────────────────────────────────────────────────────────────────────────────
# Dataclasses
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Turn:
    """A single send → receive turn in the conversation."""

    turn_index: int
    role: str                    # "customer" | "aria"
    content: str
    timestamp: str               # ISO 8601
    latency_ms: Optional[int] = None
    status: str = "ok"           # ok | timeout | error
    error: Optional[str] = None
    # Populated by judge layer after evaluation
    tool_calls_detected: list[str] = field(default_factory=list)


@dataclass
class ConversationLog:
    """Full conversation between the evaluator bot and ARIA."""

    scenario_name: str
    channel: str = "chat"
    contact_id: Optional[str] = None
    customer_id: str = "EVAL-001"
    started_at: str = ""
    finished_at: str = ""
    turns: list[Turn] = field(default_factory=list)
    total_latency_ms: int = 0
    status: str = "completed"    # completed | error | partial
    error: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────


class AdapterError(RuntimeError):
    """Raised when the chat adapter cannot complete a scenario."""


# ─────────────────────────────────────────────────────────────────────────────
# ARIAChatAdapter
# ─────────────────────────────────────────────────────────────────────────────


class ARIAChatAdapter:
    """
    Drives a scripted multi-turn chat conversation with ARIA through Amazon Connect.

    Usage::

        adapter = ARIAChatAdapter(instance_id=..., contact_flow_id=..., region="eu-west-2")
        log = adapter.run_scenario(scenario_dict, customer_id="EVAL-001")
    """

    def __init__(
        self,
        instance_id: str,
        contact_flow_id: str | None = None,
        contact_flow_name: str | None = None,
        region: str = "eu-west-2",
        display_name: str = "ARIAEvaluatorBot",
        response_timeout: float = 30.0,
        poll_interval: float = 0.5,
        chat_duration_minutes: int = 60,
        judge_model_id: str = "eu.anthropic.claude-3-5-sonnet-20241022-v2:0",
        bedrock_region: str | None = None,
        flow_noise_patterns: list[str] | None = None,
        simulate_typing: bool = True,
        typing_wpm: int = 45,
    ) -> None:
        if not contact_flow_id and not contact_flow_name:
            raise ValueError("Provide either contact_flow_id or contact_flow_name.")
        self.instance_id = instance_id
        self._contact_flow_id = contact_flow_id
        self._contact_flow_name = contact_flow_name
        self.region = region
        self.display_name = display_name
        self.response_timeout = response_timeout
        self.poll_interval = poll_interval
        self.chat_duration_minutes = chat_duration_minutes
        self._judge_model_id = judge_model_id
        self._region = bedrock_region or region
        self._flow_noise = (
            flow_noise_patterns if flow_noise_patterns is not None
            else _DEFAULT_FLOW_NOISE
        )
        self.simulate_typing = simulate_typing
        self.typing_wpm = typing_wpm
        # Preserved ARIA greeting from authenticated drain — consumed by _run_agent_mode.
        self._initial_aria_greeting: str | None = None

        self._connect = boto3.client("connect", region_name=region)
        self._participant = boto3.client("connectparticipant", region_name=region)
        self._resolved_flow_id: str | None = None  # cached after first lookup

    @property
    def contact_flow_id(self) -> str:
        """Return the flow ID, auto-discovering it by name if only a name was given."""
        if self._resolved_flow_id:
            return self._resolved_flow_id
        if self._contact_flow_id:
            self._resolved_flow_id = self._contact_flow_id
            return self._resolved_flow_id
        # Auto-discover by name
        name = self._contact_flow_name
        logger.info("Resolving contact flow by name: %s", name)
        paginator = self._connect.get_paginator("list_contact_flows")
        for page in paginator.paginate(InstanceId=self.instance_id):
            for flow in page.get("ContactFlowSummaryList", []):
                if flow.get("Name") == name:
                    self._resolved_flow_id = flow["Id"]
                    logger.info("Resolved flow %r → %s", name, self._resolved_flow_id)
                    return self._resolved_flow_id
        raise AdapterError(
            f"No contact flow named {name!r} found in instance {self.instance_id}. "
            "Check CONNECT_CONTACT_FLOW_NAME or set CONNECT_CONTACT_FLOW_ID instead."
        )

    # ── Public ──────────────────────────────────────────────────────────────

    def _is_flow_noise(self, content: str) -> bool:
        """Return True for Connect-flow system messages that are not real ARIA responses."""
        return any(p in content for p in self._flow_noise)

    def run_conversation(self, messages: list[str], name: str = "unnamed", customer_id: str = "EVAL-001") -> "ConversationLog":
        """Convenience wrapper: accepts a plain list of customer message strings."""
        scenario = {
            "name": name,
            "turns": [{"send": m} for m in messages],
        }
        return self.run_scenario(scenario, customer_id=customer_id)

    def warmup(self, timeout: float = 60.0) -> bool:
        """
        Send a warm-up message to trigger Lambda initialisation before the first scenario.

        Starts a chat contact, sends "Hello", and waits up to *timeout* seconds for ARIA
        to respond.  Returns True when ARIA responds (Lambda is now warm), False on timeout.
        A timeout is non-fatal — evaluation will continue; the first real scenario may still
        succeed once Lambda completes its cold start.
        """
        print("  🔥 Warming up Lambda (this may take up to 60 s on a cold start)...", end="", flush=True)
        seen_ids: set[str] = set()
        try:
            contact_id, _pt, connection_token = self._start_session(
                customer_id="WARMUP-001",
                scenario_name="warmup",
                seen_ids=seen_ids,
                authenticated=False,
                channel="chat",
                preserve_aria=False,
            )
        except AdapterError as exc:
            print(f" ✗ warmup session failed: {exc}", flush=True)
            return False

        old_simulate = self.simulate_typing
        self.simulate_typing = False  # no typing delay during warmup
        try:
            self._send_message(connection_token, "Hello")
            response = self._poll_response(connection_token, timeout=timeout, seen_ids=seen_ids)
        except AdapterError:
            response = None
        finally:
            self.simulate_typing = old_simulate
            try:
                self._disconnect(connection_token)
            except Exception:
                pass

        if response:
            print(" ✓ Lambda warm — ARIA responded", flush=True)
            return True
        print(f" ⚠ Lambda still cold after {timeout:.0f}s — continuing anyway", flush=True)
        return False

    def _simulate_human_typing(self, connection_token: str, text: str) -> None:
        """
        Simulate a human typing before sending a message.

        Sends a Connect typing event (visible in the Connect dashboard as "customer is typing")
        and sleeps for a duration proportional to word count at self.typing_wpm words per minute,
        with ±20% random jitter for naturalness.  Delay is clamped to [0.8 s, 8.0 s].
        """
        if not self.simulate_typing:
            return
        import random
        word_count = max(1, len(text.split()))
        base_delay = (word_count / self.typing_wpm) * 60.0
        jitter = random.uniform(-0.2, 0.2) * base_delay
        delay = max(0.8, min(8.0, base_delay + jitter))
        print(f"    ✍  typing ({word_count} words, ~{delay:.1f}s)...", end="", flush=True)
        try:
            self._participant.send_event(
                ContentType="application/vnd.amazonaws.connect.event.typing",
                ConnectionToken=connection_token,
            )
        except ClientError as exc:
            logger.debug("Typing event send failed (non-fatal): %s", exc)
        time.sleep(delay)
        print(" ↵", flush=True)

    def run_scenario(self, scenario: dict, customer_id: str = "EVAL-001") -> "ConversationLog":
        """
        Execute a scenario and return a ConversationLog.

        Supports two modes selected by ``scenario["mode"]``:

        **scripted** (default)
            Fires the ``turns`` list in order.  Each turn must have a ``send:`` key.

        **agent**
            Drives the conversation with an LLM playing the customer role.
            Requires ``goal`` and ``customer_persona`` in the scenario dict.
            ``turns`` is ignored in agent mode; use ``max_turns`` to cap the session.

        Optional top-level keys (both modes):
            authenticated: true   # Pass SESSION_START as InitialMessage so ARIA skips auth
            channel: chat         # defaults to "chat"
            turn_delay_seconds: 2.0
        """
        name = scenario.get("name", "unnamed")
        mode = scenario.get("mode", "scripted")
        authenticated = bool(scenario.get("authenticated", False))
        channel = scenario.get("channel", "chat")

        log = ConversationLog(
            scenario_name=name,
            customer_id=customer_id,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        self._initial_aria_greeting = None  # reset before each scenario
        seen_ids: set[str] = set()
        # In agent + authenticated mode: preserve ARIA's personalized greeting so the
        # driver can respond to it naturally rather than jumping straight to the goal.
        preserve_aria = authenticated and mode == "agent"
        contact_id, participant_token, connection_token = self._start_session(
            customer_id=customer_id,
            scenario_name=name,
            seen_ids=seen_ids,
            authenticated=authenticated,
            channel=channel,
            preserve_aria=preserve_aria,
        )
        log.contact_id = contact_id

        try:
            if mode == "agent":
                self._run_agent_mode(scenario, log, connection_token, seen_ids)
            else:
                self._run_scripted_mode(scenario, log, connection_token, seen_ids)
        except Exception as exc:
            log.status = "error"
            log.error = str(exc)
            logger.exception("Error executing scenario '%s'", name)
        finally:
            self._disconnect(connection_token)
            log.finished_at = datetime.now(timezone.utc).isoformat()

        return log

    def _run_scripted_mode(
        self,
        scenario: dict,
        log: "ConversationLog",
        connection_token: str,
        seen_ids: set,
    ) -> None:
        """Execute the fixed ``turns`` list in order."""
        turns_cfg: list[dict] = scenario.get("turns", [])
        turn_delay = float(scenario.get("turn_delay_seconds", 1.5))
        turn_index = 0

        for cfg in turns_cfg:
            turn_index += 1
            sent_text = cfg["send"]
            timeout = float(cfg.get("timeout_seconds", self.response_timeout))

            log.turns.append(Turn(
                turn_index=turn_index,
                role="customer",
                content=sent_text,
                timestamp=datetime.now(timezone.utc).isoformat(),
            ))

            print(f"    → customer: {sent_text[:80]}")
            self._simulate_human_typing(connection_token, sent_text)
            self._send_message(connection_token, sent_text)

            turn_index += 1
            t0 = time.monotonic()
            aria_response = self._poll_response(
                connection_token=connection_token,
                timeout=timeout,
                seen_ids=seen_ids,
            )
            latency_ms = int((time.monotonic() - t0) * 1000)
            log.total_latency_ms += latency_ms

            if aria_response is None:
                print(f"    ← ARIA: [TIMEOUT after {timeout:.0f}s]")
                log.turns.append(Turn(
                    turn_index=turn_index,
                    role="aria",
                    content="",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    latency_ms=latency_ms,
                    status="timeout",
                    error=f"No ARIA response within {timeout}s",
                ))
                log.status = "partial"
            else:
                print(f"    ← ARIA: {aria_response}")
                log.turns.append(Turn(
                    turn_index=turn_index,
                    role="aria",
                    content=aria_response,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    latency_ms=latency_ms,
                    status="ok",
                ))
                time.sleep(turn_delay)

    def _run_agent_mode(
        self,
        scenario: dict,
        log: "ConversationLog",
        connection_token: str,
        seen_ids: set,
    ) -> None:
        """Drive the conversation with an LLM playing the customer role."""
        from channels.agent_driver import AgentDriver, GOAL_ACHIEVED

        goal = scenario.get("goal", "Complete the customer service interaction.")
        customer_persona = scenario.get(
            "customer_persona",
            "You are a generic bank customer. Be polite and answer questions as asked.",
        )
        max_turns = int(scenario.get("max_turns", 14))
        default_timeout = float(scenario.get("default_timeout_seconds", self.response_timeout))
        turn_delay = float(scenario.get("turn_delay_seconds", 1.5))
        opening_message = scenario.get("opening_message", "Hello, I need some help please.")

        driver = AgentDriver(
            model_id=self._judge_model_id,
            region=self._region,
        )

        history: list[dict] = []
        turn_index = 0

        # ── Greeting phase ─────────────────────────────────────────────────────
        # For authenticated sessions the drain preserved ARIA's personalized
        # greeting (e.g. "Hello Emma, I can see your accounts…") rather than
        # draining it.  Show it, add it to the log, and let the driver generate
        # a natural first reply — rather than firing the opening_message cold.
        initial_greeting = self._initial_aria_greeting
        self._initial_aria_greeting = None  # consume so it is only used once

        if initial_greeting:
            turn_index += 1
            print(f"    ← ARIA (greeting): {initial_greeting}")
            log.turns.append(Turn(
                turn_index=turn_index,
                role="aria",
                content=initial_greeting,
                timestamp=datetime.now(timezone.utc).isoformat(),
                latency_ms=0,
                status="ok",
            ))
            history.append({"role": "aria", "content": initial_greeting})

            time.sleep(turn_delay)
            next_customer_msg = driver.generate_next_message(
                goal=goal,
                customer_persona=customer_persona,
                history=[],
                last_aria_response=initial_greeting,
            )
            if next_customer_msg is GOAL_ACHIEVED:
                print("    ✅ Goal achieved — driver signalled GOAL_ACHIEVED")
                log.status = "complete"
                return
        else:
            next_customer_msg = opening_message

        while turn_index // 2 < max_turns:
            # ── Customer sends ─────────────────────────────────────────────────
            if next_customer_msg == "[DRIVER_ERROR]":
                print("    ⚠ Driver error — stopping scenario early")
                log.status = "partial"
                break

            turn_index += 1
            log.turns.append(Turn(
                turn_index=turn_index,
                role="customer",
                content=next_customer_msg,
                timestamp=datetime.now(timezone.utc).isoformat(),
            ))
            history.append({"role": "customer", "content": next_customer_msg})
            print(f"    → customer: {next_customer_msg[:120]}")
            try:
                self._simulate_human_typing(connection_token, next_customer_msg)
                self._send_message(connection_token, next_customer_msg)
            except AdapterError as exc:
                if str(exc) == "SESSION_ENDED":
                    print("    ✅ Session ended by ARIA — conversation complete")
                    log.status = "complete"
                    return
                raise

            # ── ARIA responds ──────────────────────────────────────────────────
            turn_index += 1
            t0 = time.monotonic()
            aria_response = self._poll_response(
                connection_token=connection_token,
                timeout=default_timeout,
                seen_ids=seen_ids,
            )
            latency_ms = int((time.monotonic() - t0) * 1000)
            log.total_latency_ms += latency_ms

            if aria_response is None:
                print(f"    ← ARIA: [TIMEOUT after {default_timeout:.0f}s]")
                log.turns.append(Turn(
                    turn_index=turn_index,
                    role="aria",
                    content="",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    latency_ms=latency_ms,
                    status="timeout",
                    error=f"No ARIA response within {default_timeout}s",
                ))
                log.status = "partial"
                break

            print(f"    ← ARIA: {aria_response}")
            log.turns.append(Turn(
                turn_index=turn_index,
                role="aria",
                content=aria_response,
                timestamp=datetime.now(timezone.utc).isoformat(),
                latency_ms=latency_ms,
                status="ok",
            ))
            history.append({"role": "aria", "content": aria_response})

            time.sleep(turn_delay)

            # ── Driver decides next move ───────────────────────────────────────
            next_customer_msg = driver.generate_next_message(
                goal=goal,
                customer_persona=customer_persona,
                history=history[:-1],   # exclude the last aria entry (passed as arg)
                last_aria_response=aria_response,
            )

            if next_customer_msg is GOAL_ACHIEVED:
                print("    ✅ Goal achieved — driver signalled GOAL_ACHIEVED")
                log.status = "complete"
                break
            # [DRIVER_ERROR] will be caught at the top of the next loop iteration.

    # ── Private ─────────────────────────────────────────────────────────────

    def _start_session(
        self,
        customer_id: str,
        scenario_name: str,
        seen_ids: set,
        authenticated: bool = False,
        channel: str = "chat",
        preserve_aria: bool = False,
    ) -> tuple[str, str, str]:
        """Start a Connect chat contact and return (contact_id, participant_token, connection_token).

        For authenticated sessions we deliberately do NOT use InitialMessage.
        Instead we:
          1. Start the chat contact with no InitialMessage.
          2. Drain the Connect-flow greeting messages (~3-5 s).
          3. Send SESSION_START as a regular customer message so ARIA can receive it
             after it has fully joined the contact.
          4. Poll for ARIA's personalised greeting (up to 45 s, covers Lambda cold start).
          5. Store the greeting in self._initial_aria_greeting so _run_agent_mode can
             give it to the driver as context before the first customer turn.

        Sending SESSION_START as InitialMessage caused a race: ARIA was still running
        the get_customer_details tool call when the opening_message arrived, so it
        would never respond.
        """
        start_kwargs: dict = dict(
            InstanceId=self.instance_id,
            ContactFlowId=self.contact_flow_id,
            ParticipantDetails={"DisplayName": self.display_name},
            ChatDurationInMinutes=self.chat_duration_minutes,
            Attributes={
                "customerId": customer_id,
                "evaluationScenario": scenario_name,
                "channel": channel,
                "authStatus": "authenticated" if authenticated else "unauthenticated",
            },
        )

        try:
            resp = self._connect.start_chat_contact(**start_kwargs)
        except ClientError as exc:
            raise AdapterError(f"start_chat_contact failed: {exc}") from exc

        contact_id = resp["ContactId"]
        participant_token = resp["ParticipantToken"]

        try:
            conn_resp = self._participant.create_participant_connection(
                Type=["CONNECTION_CREDENTIALS"],
                ParticipantToken=participant_token,
            )
            connection_token = conn_resp["ConnectionCredentials"]["ConnectionToken"]
        except ClientError as exc:
            self._safe_stop(contact_id)
            raise AdapterError(f"create_participant_connection failed: {exc}") from exc

        # Signal to the flow that the customer participant is ready.
        # Without this event the flow sits waiting and never sends its initial greeting.
        try:
            self._participant.send_event(
                ContentType="application/vnd.amazonaws.connect.event.connection.acknowledged",
                ConnectionToken=connection_token,
            )
        except ClientError as exc:
            logger.warning("send connection.acknowledged event failed (non-fatal): %s", exc)

        # Phase 1: drain the Connect-flow greeting (usually arrives within 3-5 s).
        self._drain_until_stable(
            connection_token,
            seen_ids=seen_ids,
            stable_secs=3.0,
            max_wait=20.0,
            wait_for_aria_response=False,
            preserve_first_aria=False,
        )
        self._initial_aria_greeting = None

        if authenticated and customer_id:
            # Phase 2: send SESSION_START now that the connection is live and the
            # flow greeting has been drained.  ARIA processes it silently — it
            # calls get_customer_details and loads the customer profile, then
            # greets by name when the customer sends their first message.
            # We do NOT poll for a response here: ARIA never replies proactively
            # to SESSION_START; it only greets when the customer speaks.
            session_start = (
                f"SESSION_START: An authenticated customer has connected. "
                f"X-Channel-Auth: authenticated. "
                f"X-Customer-ID: {customer_id}. "
                f"X-Channel: {channel}. "
                f"X-Locale: en-GB. "
                f"Call get_customer_details with this customer ID to fetch their profile, "
                f"then greet them by their preferred_name and ask how you can help today. "
                f"Do not ask the customer to re-verify their identity."
            )
            print(f"    [auth] sending SESSION_START for customer {customer_id}", flush=True)
            try:
                self._participant.send_message(
                    ContentType="text/plain",
                    Content=session_start,
                    ConnectionToken=connection_token,
                )
            except ClientError as exc:
                logger.warning("SESSION_START send failed (non-fatal): %s", exc)
            # Wait briefly after SESSION_START so ARIA can ingest it before the
            # customer's first message arrives.  ARIA never sends a proactive reply
            # to SESSION_START — it processes it silently (calling get_customer_details)
            # and only greets once the customer speaks.  We therefore do NOT wait for
            # an ARIA response here; we simply let the transcript settle for ~3 s
            # (long enough for the API round-trip) and rely on the per-turn
            # response_timeout (default 90 s) to cover any Lambda cold-start delay
            # when the first customer message is sent.
            preserved = self._drain_until_stable(
                connection_token,
                seen_ids=seen_ids,
                stable_secs=3.0,
                max_wait=30.0,
                wait_for_aria_response=False,
                preserve_first_aria=preserve_aria,
            )
            if preserve_aria and preserved:
                self._initial_aria_greeting = preserved

        return contact_id, participant_token, connection_token

    def _drain_until_stable(
        self,
        connection_token: str,
        seen_ids: set,
        stable_secs: float = 2.0,
        max_wait: float = 20.0,
        wait_for_aria_response: bool = False,
        preserve_first_aria: bool = False,
    ) -> Optional[str]:
        """Poll the transcript until it has been stable for *stable_secs*.

        Per the Amazon Connect Participant API, ARIA (Amazon Connect AI Agent)
        messages may appear with ParticipantRole "CUSTOM_BOT" or "SYSTEM",
        depending on instance configuration.  Flow system messages (Connect flow
        "Send chat message" blocks) also appear as "SYSTEM".  Content-based
        filtering via _is_flow_noise() is therefore required to distinguish them.

        When *wait_for_aria_response* is True (authenticated sessions), also
        wait until at least one real ARIA message (not flow noise) has appeared.

        When *preserve_first_aria* is True, the chronologically earliest real
        ARIA message is NOT added to seen_ids so that _run_agent_mode can
        present it to the driver as ARIA's opening greeting.  Flow noise
        messages ("Hello !! Welcome…") are always drained regardless.

        Returns the preserved message content, or None.
        """
        bot_roles = {"BOT", "SYSTEM", "AGENT", "CUSTOM_BOT"}
        deadline = time.monotonic() + max_wait
        last_change = time.monotonic()
        known_count = 0
        aria_seen = False

        label = "flow + ARIA init" if wait_for_aria_response else "flow"
        print(f"    [drain] waiting for {label}", end="", flush=True)
        while time.monotonic() < deadline:
            try:
                resp = self._participant.get_transcript(
                    ConnectionToken=connection_token,
                    MaxResults=30,
                    ScanDirection="BACKWARD",
                    SortOrder="DESCENDING",
                )
            except ClientError:
                time.sleep(0.5)
                continue

            items = resp.get("Transcript", [])

            # aria_seen counts only real ARIA messages, not flow noise.
            if not aria_seen:
                for i in items:
                    if (i.get("ParticipantRole") in bot_roles
                            and i.get("Type") == "MESSAGE"
                            and not self._is_flow_noise(i.get("Content", ""))):
                        aria_seen = True
                        role = i.get("ParticipantRole", "?")
                        name = i.get("DisplayName", "")
                        snippet = i.get("Content", "")[:60].replace("\n", " ")
                        logger.debug(
                            "drain: first real ARIA msg role=%s name=%r content=%r",
                            role, name, snippet,
                        )
                        break

            if len(items) != known_count:
                known_count = len(items)
                last_change = time.monotonic()
                print(".", end="", flush=True)

            stable = time.monotonic() - last_change >= stable_secs
            ready = not wait_for_aria_response or aria_seen
            if stable and ready:
                preserved_content: Optional[str] = None
                preserve_id: Optional[str] = None

                if preserve_first_aria:
                    # Collect real (non-noise) ARIA messages.
                    # items is DESCENDING so the last element is the EARLIEST.
                    aria_msgs = [
                        i for i in items
                        if i.get("ParticipantRole") in bot_roles
                        and i.get("Type") == "MESSAGE"
                        and not self._is_flow_noise(i.get("Content", ""))
                    ]
                    if aria_msgs:
                        earliest = aria_msgs[-1]
                        preserve_id = earliest.get("Id")
                        preserved_content = earliest.get("Content", "").strip()

                # Drain everything except the preserved ARIA greeting.
                for item in items:
                    msg_id = item.get("Id")
                    if msg_id and msg_id != preserve_id:
                        seen_ids.add(msg_id)

                drained = known_count - (1 if preserve_id else 0)
                if preserve_id:
                    print(
                        f" done ({drained} drained, ARIA greeting preserved)",
                        flush=True,
                    )
                else:
                    reason = "aria+stable" if (aria_seen and wait_for_aria_response) else "stable"
                    print(f" done ({known_count} drained, {reason})", flush=True)
                return preserved_content

            time.sleep(0.5)

        # Timeout — log what was found, drain everything, nothing preserved.
        try:
            resp = self._participant.get_transcript(
                ConnectionToken=connection_token,
                MaxResults=30,
                ScanDirection="BACKWARD",
                SortOrder="DESCENDING",
            )
            final_items = resp.get("Transcript", [])
            for item in final_items:
                msg_id = item.get("Id")
                if msg_id:
                    seen_ids.add(msg_id)
            # If waiting for ARIA but none arrived, show all transcript items so
            # the operator can see why (wrong role? flow noise pattern too broad?).
            if wait_for_aria_response and not aria_seen:
                print(f"\n    [drain] TIMEOUT — no real ARIA response in {max_wait:.0f}s.",
                      flush=True)
                for item in final_items:
                    role = item.get("ParticipantRole", "?")
                    name = item.get("DisplayName", "")
                    snippet = item.get("Content", "")[:80].replace("\n", " ")
                    is_noise = self._is_flow_noise(item.get("Content", ""))
                    print(
                        f"      [{role}/{name}] {'(noise)' if is_noise else '      '} {snippet!r}",
                        flush=True,
                    )
            else:
                print(f" timeout ({known_count} msgs, aria_seen={aria_seen})", flush=True)
        except ClientError:
            print(f" timeout (drain failed)", flush=True)
        return None

    def _send_message(self, connection_token: str, text: str) -> None:
        try:
            self._participant.send_message(
                ContentType="text/plain",
                Content=text,
                ConnectionToken=connection_token,
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code == "AccessDeniedException":
                # Connection token has expired — ARIA ended the session.
                raise AdapterError("SESSION_ENDED") from exc
            raise AdapterError(f"send_message failed: {exc}") from exc

    def _poll_response(
        self,
        connection_token: str,
        timeout: float,
        seen_ids: set[str],
    ) -> Optional[str]:
        """Poll get_transcript until a new ARIA message arrives or timeout."""
        deadline = time.monotonic() + timeout
        bot_roles = {"BOT", "SYSTEM", "AGENT", "CUSTOM_BOT"}

        print(f"    ⏳ waiting for ARIA", end="", flush=True)
        while time.monotonic() < deadline:
            try:
                resp = self._participant.get_transcript(
                    ConnectionToken=connection_token,
                    MaxResults=30,
                    ScanDirection="BACKWARD",
                    SortOrder="DESCENDING",
                )
            except ClientError as exc:
                logger.warning("get_transcript failed: %s — retrying", exc)
                time.sleep(self.poll_interval)
                continue

            transcript = resp.get("Transcript", [])

            # Collect new ARIA messages; silently drain any flow noise so it
            # never surfaces as an "ARIA response" to the customer's message.
            candidates = [
                item for item in transcript
                if item.get("Type") == "MESSAGE"
                and item.get("ParticipantRole") in bot_roles
                and item.get("Id") not in seen_ids
            ]
            # Separate real responses from flow noise.
            new_msgs = []
            for item in candidates:
                if self._is_flow_noise(item.get("Content", "")):
                    seen_ids.add(item["Id"])  # drain silently
                else:
                    new_msgs.append(item)

            if new_msgs:
                for msg in new_msgs:
                    seen_ids.add(msg["Id"])
                all_msgs = list(reversed(new_msgs))

                # ARIA often streams multi-part responses (tool call → result → prose).
                # Use adaptive backoff: start at 0.3 s, double on each pass that finds new
                # parts (cap at 1.5 s), and stop immediately when a pass finds nothing new.
                # This saves 4–6 s of fixed overhead per turn on single-part responses.
                follow_wait = 0.3
                for _ in range(8):
                    time.sleep(follow_wait)
                    try:
                        follow_resp = self._participant.get_transcript(
                            ConnectionToken=connection_token,
                            MaxResults=30,
                            ScanDirection="BACKWARD",
                            SortOrder="DESCENDING",
                        )
                        candidates2 = [
                            item for item in follow_resp.get("Transcript", [])
                            if item.get("Type") == "MESSAGE"
                            and item.get("ParticipantRole") in bot_roles
                            and item.get("Id") not in seen_ids
                        ]
                        more = []
                        for item in candidates2:
                            if self._is_flow_noise(item.get("Content", "")):
                                seen_ids.add(item["Id"])
                            else:
                                more.append(item)
                        if not more:
                            break
                        for msg in more:
                            seen_ids.add(msg["Id"])
                        all_msgs.extend(reversed(more))
                        follow_wait = min(follow_wait * 2, 1.5)
                    except ClientError:
                        break

                elapsed = time.monotonic() - (deadline - timeout)
                combined = "\n".join(m["Content"] for m in all_msgs)
                print(f" ({elapsed:.1f}s) ✓", flush=True)
                return combined

            time.sleep(self.poll_interval)
            print(".", end="", flush=True)

        elapsed = timeout
        print(f" TIMEOUT after {elapsed:.0f}s", flush=True)
        # Dump entire transcript so we can diagnose why ARIA didn't respond.
        try:
            diag = self._participant.get_transcript(
                ConnectionToken=connection_token,
                MaxResults=50,
                ScanDirection="BACKWARD",
                SortOrder="DESCENDING",
            )
            print("    [poll-timeout] transcript dump:", flush=True)
            for item in reversed(diag.get("Transcript", [])):
                role = item.get("ParticipantRole", "?")
                name = item.get("DisplayName", "")
                typ  = item.get("Type", "?")
                msg_id = item.get("Id", "?")[:8]
                content = item.get("Content", "")[:100].replace("\n", " ")
                in_seen = msg_id in {s[:8] for s in seen_ids}
                noise = self._is_flow_noise(item.get("Content", "")) if typ == "MESSAGE" else False
                print(
                    f"      [{role}/{name}] {typ}"
                    f"{' (seen)' if in_seen else ''}"
                    f"{' (noise)' if noise else ''}"
                    f" [{msg_id}] {content!r}",
                    flush=True,
                )
        except ClientError as exc:
            print(f"    [poll-timeout] transcript dump failed: {exc}", flush=True)
        return None

    def _disconnect(self, connection_token: str) -> None:
        try:
            self._participant.disconnect_participant(ConnectionToken=connection_token)
        except ClientError:
            pass

    def _safe_stop(self, contact_id: str) -> None:
        try:
            self._connect.stop_contact(ContactId=contact_id, InstanceId=self.instance_id)
        except ClientError:
            pass
