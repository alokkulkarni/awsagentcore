"""
history.py
==========
Connect's conversation history, made into the message list a Strands agent accepts.
"""

from __future__ import annotations


def to_messages(history: list[dict]) -> tuple[list[dict], str]:
    """
    Connect's history as Strands messages: starting with the customer, alternating,
    same-role turns merged. Anything ARIA said before the customer's first words
    is returned separately, as context for the system prompt.
    """
    messages, preface = [], []
    for turn in history or []:
        role = "user" if turn.get("role") == "user" else "assistant"
        text = str(turn.get("text") or "").strip()
        if not text:
            continue
        if not messages and role == "assistant":
            preface.append(text)
            continue
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"][0]["text"] += "\n" + text
        else:
            messages.append({"role": role, "content": [{"text": text}]})
    if messages and messages[-1]["role"] == "user":       # the new input is the next user turn
        last = messages.pop()["content"][0]["text"]
        preface.append(f"(The customer had also said: {last})")
    return messages, " ".join(preface)
