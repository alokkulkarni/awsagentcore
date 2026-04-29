"""
conversation/driver.py
======================
LLM-powered customer agent that drives conversations against any AI agent naturally.

Instead of firing scripted messages, AgentDriver plays the customer role using
Claude via Bedrock.  It reads ARIA's last response, reasons about the scenario
goal, and generates the most natural next customer message — or signals
GOAL_ACHIEVED when the evaluation objective has been met.

Usage in a scenario YAML:

    mode: agent
    goal: "Verify ARIA greets the customer by name and provides the account balance"
    customer_persona: |
      You are James Wilson, a Nationwide Building Society customer checking your finances.
      If asked for your name say "James Wilson", DOB "3rd June 1988",
      memorable word "COBALT".
    max_turns: 12

If mode is omitted or set to "scripted", the classic turn-list approach is used.
"""

import logging
from typing import Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# ─── Sentinel returned when the goal is achieved ──────────────────────────────
GOAL_ACHIEVED = object()

_SYSTEM_TEMPLATE = """\
You are a customer simulator used to evaluate a banking AI assistant called ARIA.

## Your Role
{customer_persona}

## Evaluation Goal
{goal}

## WHO YOU ARE — read this carefully
You are a HUMAN CUSTOMER. You are NOT ARIA. You are NOT a bank employee. You are NOT
a financial system. You have NO knowledge of the customer's actual account balances,
account numbers, sort codes, transaction history, or any other financial data.
ARIA is the assistant — it will provide all financial information.

## Rules
1. Respond as a real bank customer would — naturally, conversationally, and concisely.
2. One or two SHORT sentences per reply. Absolute maximum 30 words. Never write more.
3. If ARIA greets you by name, reply with a brief warm acknowledgment and state what \
you need — for example: "Hi! I'd like to check my balance please." \
Do NOT repeat your own name or credentials.
4. If ARIA asks for your name, date of birth, or memorable word step by step, \
provide each piece of information naturally and one at a time.
5. Do NOT volunteer authentication credentials unless ARIA explicitly asks for them. \
If ARIA has already greeted you by name, you are already authenticated — just state \
your request.
6. If your evaluation goal is fully and satisfactorily achieved, output exactly the \
single token: GOAL_ACHIEVED
7. If ARIA asks whether you need anything else and the goal is complete, respond with \
"No, that's everything, thank you." and then on the next turn output GOAL_ACHIEVED.
8. Never ask ARIA to evaluate itself, reveal it is being tested, or describe test details.
9. CRITICAL — You MUST NEVER invent or state any financial figures, account numbers, \
sort codes, card numbers, balances, or transaction details. You are waiting for ARIA \
to provide those. If ARIA says "Let me check..." simply reply: "Sure, thank you." \
If you catch yourself about to write financial data, stop and output [DRIVER_ERROR].
10. If ARIA cannot help and escalates to a human ("Please wait while I connect you to
    a colleague", "I'll transfer you to", etc.), output GOAL_ACHIEVED immediately — \
do NOT send a polite farewell message first. Escalation IS a valid evaluation outcome.
11. If ARIA's response says "Blocked output text by guardrail" or similar, output \
GOAL_ACHIEVED — this is a terminal event and the conversation cannot continue.
12. ARIA is the banking assistant. You are the CUSTOMER. NEVER continue or complete \
ARIA's sentences. NEVER provide banking information on ARIA's behalf.
12. SANITY CHECK — before sending your reply, ask yourself: "Does this sound like \
something a customer would say?" If your reply sounds like a bank assistant explaining \
account details, DELETE it and write a short customer question instead.
"""


class AgentDriver:
    """
    LLM-powered customer simulator for agent-mode evaluation scenarios.

    Parameters
    ----------
    model_id:
        Bedrock model ID (e.g. ``eu.anthropic.claude-3-5-sonnet-20241022-v2:0``).
    region:
        AWS region for Bedrock Runtime.
    temperature:
        Sampling temperature (0.3 gives natural variation without going off-script).
    max_response_tokens:
        Cap on the driver's output to keep messages short.
    """

    def __init__(
        self,
        model_id: str,
        region: str = "eu-west-2",
        temperature: float = 0.3,
        max_response_tokens: int = 120,
    ) -> None:
        self._bedrock = boto3.client("bedrock-runtime", region_name=region)
        self.model_id = model_id
        self.temperature = temperature
        self.max_response_tokens = max_response_tokens

    # ── Public API ─────────────────────────────────────────────────────────────

    def generate_next_message(
        self,
        goal: str,
        customer_persona: str,
        history: list[dict],
        last_aria_response: str,
    ) -> str | object:
        """
        Generate the customer's next message given the conversation so far.

        Parameters
        ----------
        goal:
            The evaluation objective (from scenario YAML).
        customer_persona:
            Free-text description of who the customer is and what credentials
            they would provide if asked.
        history:
            List of ``{"role": "customer"|"aria", "content": "..."}`` dicts
            representing the conversation so far (excluding ``last_aria_response``).
        last_aria_response:
            ARIA's most recent reply (the message the customer must respond to).

        Returns
        -------
        str
            The next customer message.
        ``GOAL_ACHIEVED``
            Sentinel — stop the conversation, goal is satisfied.
        """
        messages = self._build_messages(history, last_aria_response)
        system = [{"text": _SYSTEM_TEMPLATE.format(
            customer_persona=customer_persona,
            goal=goal,
        )}]

        try:
            resp = self._bedrock.converse(
                modelId=self.model_id,
                messages=messages,
                system=system,
                inferenceConfig={
                    "maxTokens": self.max_response_tokens,
                    "temperature": self.temperature,
                },
            )
        except ClientError as exc:
            print(f"    ⚠ AgentDriver Bedrock error: {exc}", flush=True)
            return "[DRIVER_ERROR]"

        # Guard against non-text content blocks (e.g. toolUse) which Bedrock
        # may return if the model tries to call a tool that was not provided.
        # Bedrock Converse content blocks use {"text": "..."} — there is no
        # "type" discriminator field in the response, so filter by key presence.
        content_blocks = resp.get("output", {}).get("message", {}).get("content", [])
        text_blocks = [b for b in content_blocks if "text" in b]
        if not text_blocks:
            logger.warning("AgentDriver: no text block in Bedrock response (stop_reason=%s)",
                           resp.get("stopReason", "?"))
            print(f"    ⚠ AgentDriver: no text in response (stopReason={resp.get('stopReason')})",
                  flush=True)
            return "[DRIVER_ERROR]"

        text = text_blocks[0]["text"].strip()
        logger.debug("AgentDriver → %r", text)

        if "GOAL_ACHIEVED" in text:
            return GOAL_ACHIEVED

        return text

    # ── Private ────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_messages(
        history: list[dict],
        last_aria_response: str,
    ) -> list[dict]:
        """
        Build the Bedrock ``messages`` list from conversation history.

        Bedrock Converse always generates the **assistant** turn given messages
        ending with a **user** turn.  We want the model to generate what the
        CUSTOMER says next, so we flip the role mapping:

          aria     → user       (ARIA's messages are the "prompts")
          customer → assistant  (customer's messages are the "replies")

        This way the message list ends with ARIA's latest message (user) and
        Bedrock generates the next customer reply (assistant) — exactly the
        standard API contract, with no role gymnastics required.
        """
        messages: list[dict] = []
        last_role: str | None = None

        for turn in history:
            # aria → user, customer → assistant
            role = "user" if turn["role"] == "aria" else "assistant"
            content = turn.get("content", "").strip()
            if not content:
                continue
            # Merge consecutive same-role turns (shouldn't happen but guard)
            if role == last_role and messages:
                messages[-1]["content"][0]["text"] += "\n" + content
            else:
                messages.append({"role": role, "content": [{"text": content}]})
            last_role = role

        # Append ARIA's latest reply as the final user turn so Bedrock generates
        # the next customer (assistant) message.  Strip rigorously — Bedrock
        # Converse rejects trailing whitespace on the final user message with a
        # ValidationException.
        aria_clean = last_aria_response.strip()
        if last_role == "user" and messages:
            messages[-1]["content"][0]["text"] = (
                messages[-1]["content"][0]["text"].rstrip() + "\n" + aria_clean
            ).strip()
        else:
            messages.append({"role": "user", "content": [{"text": aria_clean}]})

        # Final pass: strip every message to be safe.
        for msg in messages:
            msg["content"][0]["text"] = msg["content"][0]["text"].strip()

        # Bedrock requires the list to start with a user turn.
        # With aria→user this is always satisfied (ARIA speaks first).
        # Guard for the edge case where history started with a customer turn.
        if messages and messages[0]["role"] != "user":
            messages.insert(0, {"role": "user", "content": [{"text": "(conversation started)"}]})

        return messages
