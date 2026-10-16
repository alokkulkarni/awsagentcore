"""
transcript.py
=============
What was said on a call from the Money Hub page, for the page to show as it
happens. A call is audio only, so the words come from the Amazon Q in Connect
session behind ARIA: Connect writes each turn there as text (the customer's
words as speech-to-text, and every reply, whether ARIA's or the Money Hub
agent's). Contact Lens has no real-time transcript for a call that hasn't
reached a person, so it isn't used.

The page Lambda reads the session (qconnect ListMessages) only for contacts
that the same page link started; this turns its messages into lines.
"""

from __future__ import annotations

CUSTOMER, ASSISTANT = "customer", "assistant"


def to_lines(messages: list[dict]) -> list[dict]:
    """Q in Connect messages (any order) as [{at, who, text}], oldest first, empty ones left out."""
    lines = []
    for message in messages:
        text = " ".join(str(((message.get("value") or {}).get("text") or {}).get("value") or "").split())
        if not text:
            continue
        at = message.get("timestamp")
        lines.append({"at": at.isoformat() if hasattr(at, "isoformat") else str(at or ""),
                      "who": CUSTOMER if message.get("participant") == "CUSTOMER" else ASSISTANT,
                      "text": text})
    return sorted(lines, key=lambda line: line["at"])
