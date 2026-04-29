"""
adapters/__init__.py
====================
Generic async adapter interface for driving conversations against any AI agent.

Concrete implementations:
  - ConnectWebSocketAdapter  (adapters/connect_ws.py)    — Amazon Connect Chat via WebSocket
  - ConnectVoiceAdapter      (adapters/connect_voice.py) — Amazon Connect Voice via WebRTC
                                                           (Polly TTS → WebRTC audio → Transcribe STT)

To add a new agent type, subclass BaseAdapter and implement the four abstract
methods.  The ScenarioRunner depends only on this interface.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class AdapterMessage:
    """A single message received from the agent."""

    role: str          # "agent" | "system" | "customer"
    content: str
    display_name: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    is_noise: bool = False   # True for Connect flow system messages


class SessionEndedError(RuntimeError):
    """
    Raised by an adapter when the remote session has been terminated and no
    further messages can be sent.  This is a normal terminal condition (e.g.
    the agent closed the chat) — callers should treat it as a clean end of
    conversation, not a failure.
    """


class BaseAdapter(ABC):
    """
    Async interface for sending messages to and receiving messages from an AI agent.

    Lifecycle::

        adapter = MyAdapter(...)
        await adapter.connect(session_id="s1", customer_id="CUST-001", authenticated=True)
        await adapter.send_message("Hello")
        msg: AdapterMessage = await adapter.receive(timeout=30.0)
        await adapter.disconnect()

    All implementations must be usable as an async context manager::

        async with MyAdapter(...) as adapter:
            await adapter.send_message("Hello")
            msg = await adapter.receive(timeout=30.0)
    """

    # ── Abstract interface ────────────────────────────────────────────────────

    @abstractmethod
    async def connect(
        self,
        session_id: str,
        customer_id: Optional[str] = None,
        authenticated: bool = False,
        channel: str = "chat",
        scenario_name: str = "",
    ) -> None:
        """
        Establish a connection to the agent.

        For Amazon Connect this means starting a chat contact, creating the
        participant connection, and opening the WebSocket.
        """

    @abstractmethod
    async def send_message(self, content: str, simulate_typing: bool = True) -> None:
        """
        Send a customer message to the agent.

        If *simulate_typing* is True the adapter should emit a typing indicator
        and introduce a human-paced delay before the message is sent.
        """

    @abstractmethod
    async def receive(self, timeout: float = 60.0) -> Optional[AdapterMessage]:
        """
        Wait up to *timeout* seconds for the next non-noise agent message.

        Returns None on timeout.  Noise messages (flow system messages) are
        consumed silently and never returned.
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """Cleanly close the agent session."""

    # ── Context manager ───────────────────────────────────────────────────────

    async def __aenter__(self) -> "BaseAdapter":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.disconnect()
