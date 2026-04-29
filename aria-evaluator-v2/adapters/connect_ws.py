"""
adapters/connect_ws.py
======================
Amazon Connect Chat adapter using the **WebSocket** participant connection.

This is the same connection pattern the hosted Connect chat widget uses, which
is why it delivers sub-second responses instead of timing out like the old
polling approach.

Key difference vs v1 chat_adapter.py
-------------------------------------
v1 called:
    create_participant_connection(Type=["CONNECTION_CREDENTIALS"])
    → had to poll get_transcript every 1–5 s

v2 calls:
    create_participant_connection(Type=["WEBSOCKET", "CONNECTION_CREDENTIALS"])
    → WebSocket URL returned; agent messages pushed instantly

WebSocket protocol (Amazon Connect Participant)
-----------------------------------------------
1. Connect to ``wss://...`` URL returned by create_participant_connection
2. Send subscription: {"topic": "aws/subscribe", "content": {"topics": ["aws/chat"]}}
3. Receive ack:       {"topic": "aws/subscribe", "statusCode": 200, ...}
4. Agent messages arrive as:
       {"topic": "aws/chat", "contentType": "application/json", "content": "<json>"}
   where the inner JSON has keys:
       Type, ContentType, Content, ParticipantRole, DisplayName, AbsoluteTime, Id
5. Send heartbeat every 30 s: {"topic": "aws/ping"}
6. send_message() still uses boto3 connectparticipant (correct per AWS docs)
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from datetime import datetime, timezone
from typing import Optional

import boto3
import websockets
import websockets.exceptions
from botocore.exceptions import ClientError

from adapters import AdapterMessage, BaseAdapter, SessionEndedError

logger = logging.getLogger(__name__)

# ── Flow noise patterns (same as v1) ─────────────────────────────────────────
_FLOW_NOISE: list[str] = [
    "Let me transfer you to one of our agents",
    "Welcome to Meridian Bank !!",
    "Welcome to Nationwide Building Society !!",
    "Hello !! Welcome to",
]

# Roles that carry agent/system messages from Connect
_BOT_ROLES = {"BOT", "SYSTEM", "AGENT", "CUSTOM_BOT"}

# Default typing speed
_DEFAULT_TYPING_WPM = 60


def _is_flow_noise(content: str) -> bool:
    return any(pattern in content for pattern in _FLOW_NOISE)


class ConnectAdapterError(RuntimeError):
    pass


class ConnectWebSocketAdapter(BaseAdapter):
    """
    Amazon Connect Chat adapter — WebSocket push, no polling.

    Parameters
    ----------
    instance_id:         Connect instance ID
    contact_flow_id:     ID of the contact flow to start
    region:              AWS region (default eu-west-2)
    display_name:        Customer display name shown in the transcript
    chat_duration_minutes: How long the chat session stays open (AWS min 60)
    typing_wpm:          Words-per-minute for the typing simulation
    response_timeout:    Default seconds to wait for an agent response
    """

    def __init__(
        self,
        instance_id: str,
        contact_flow_id: str,
        region: str = "eu-west-2",
        display_name: str = "EvaluatorBot",
        chat_duration_minutes: int = 60,
        typing_wpm: int = _DEFAULT_TYPING_WPM,
        response_timeout: float = 90.0,
    ) -> None:
        self.instance_id = instance_id
        self.contact_flow_id = contact_flow_id
        self.region = region
        self.display_name = display_name
        self.chat_duration_minutes = chat_duration_minutes
        self.typing_wpm = typing_wpm
        self.response_timeout = response_timeout

        self._connect = boto3.client("connect", region_name=region)
        self._participant = boto3.client("connectparticipant", region_name=region)

        self._contact_id: Optional[str] = None
        self._connection_token: Optional[str] = None
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._message_queue: asyncio.Queue[AdapterMessage] = asyncio.Queue()
        self._ws_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

    # ── BaseAdapter implementation ────────────────────────────────────────────

    async def connect(
        self,
        session_id: str,
        customer_id: Optional[str] = None,
        authenticated: bool = False,
        channel: str = "chat",
        scenario_name: str = "",
    ) -> None:
        """
        Start the Connect chat contact and open the WebSocket connection.

        For authenticated sessions, SESSION_START is sent immediately after
        the WebSocket is live and the initial flow greeting has settled.
        ARIA processes SESSION_START silently (calls get_customer_details
        internally) and only greets when the customer sends their first message.
        """
        start_kwargs: dict = dict(
            InstanceId=self.instance_id,
            ContactFlowId=self.contact_flow_id,
            ParticipantDetails={"DisplayName": self.display_name},
            ChatDurationInMinutes=self.chat_duration_minutes,
            Attributes={
                "customerId":         customer_id or "",
                "evaluationScenario": scenario_name,
                "channel":            channel,
                "authStatus":         "authenticated" if authenticated else "unauthenticated",
            },
        )

        try:
            resp = self._connect.start_chat_contact(**start_kwargs)
        except ClientError as exc:
            raise ConnectAdapterError(f"start_chat_contact failed: {exc}") from exc

        self._contact_id = resp["ContactId"]
        participant_token = resp["ParticipantToken"]
        logger.info("Chat contact started | contact_id=%s", self._contact_id)

        # Request BOTH WebSocket AND connection credentials.
        # The WebSocket gives push-based delivery (like the chat widget).
        # CONNECTION_CREDENTIALS is kept for send_message / send_event boto3 calls.
        try:
            conn_resp = self._participant.create_participant_connection(
                Type=["WEBSOCKET", "CONNECTION_CREDENTIALS"],
                ParticipantToken=participant_token,
            )
        except ClientError as exc:
            self._safe_stop()
            raise ConnectAdapterError(
                f"create_participant_connection failed: {exc}"
            ) from exc

        self._connection_token = conn_resp["ConnectionCredentials"]["ConnectionToken"]
        ws_url = conn_resp["Websocket"]["Url"]
        logger.debug("WebSocket URL obtained | contact_id=%s", self._contact_id)

        # Acknowledge the connection so the flow starts.
        try:
            self._participant.send_event(
                ContentType="application/vnd.amazonaws.connect.event.connection.acknowledged",
                ConnectionToken=self._connection_token,
            )
        except ClientError as exc:
            logger.warning("connection.acknowledged send failed (non-fatal): %s", exc)

        # Open the WebSocket and start the receiver/heartbeat background tasks.
        await self._open_websocket(ws_url)

        # Drain the Connect flow greeting (arrives in ~1–5 s).
        # We wait for the queue to be quiet for 3 s (no new messages) or 15 s max.
        await self._drain_noise(stable_secs=3.0, max_wait=15.0)

        # Inject SESSION_START for authenticated sessions.
        # ARIA never replies proactively — it processes silently and greets on
        # the customer's first message.  We send and immediately move on;
        # the per-turn response_timeout (default 90 s) covers Lambda cold starts.
        if authenticated and customer_id:
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
                    ConnectionToken=self._connection_token,
                )
            except ClientError as exc:
                logger.warning("SESSION_START send failed (non-fatal): %s", exc)
            # Brief settle so ARIA has a moment to register SESSION_START before
            # the first customer message arrives.
            await asyncio.sleep(5.0)

    async def send_message(self, content: str, simulate_typing: bool = True) -> None:
        """Send a customer message, optionally simulating human typing speed."""
        if simulate_typing:
            await self._simulate_typing(content)

        if not self._connection_token:
            raise ConnectAdapterError("send_message called before connect()")

        try:
            self._participant.send_message(
                ContentType="text/plain",
                Content=content,
                ConnectionToken=self._connection_token,
            )
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code == "AccessDeniedException":
                raise SessionEndedError(
                    "Chat session ended — connection token revoked (agent closed the chat)"
                ) from exc
            raise ConnectAdapterError(f"send_message failed: {exc}") from exc

    async def receive(self, timeout: float = 60.0) -> Optional[AdapterMessage]:
        """
        Wait for the next real agent message.

        Noise messages (flow greetings) are consumed silently.
        Returns None on timeout.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                msg = await asyncio.wait_for(
                    self._message_queue.get(), timeout=min(remaining, 1.0)
                )
            except asyncio.TimeoutError:
                continue
            if msg.is_noise or msg.role == "customer":
                logger.debug("receive: skipping %s %r", msg.role if msg.role == "customer" else "noise", msg.content[:60])
                continue
            return msg
        return None

    async def disconnect(self) -> None:
        """Close the WebSocket and end the Connect chat contact."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._ws_task:
            self._ws_task.cancel()
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._safe_stop()

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _open_websocket(self, ws_url: str) -> None:
        """Connect to the WebSocket URL and start background tasks."""
        self._ws = await websockets.connect(
            ws_url,
            ping_interval=None,   # we manage heartbeats manually
            open_timeout=15,
        )
        # Subscribe to the chat topic so messages start arriving.
        await self._ws.send(json.dumps({
            "topic": "aws/subscribe",
            "content": {"topics": ["aws/chat"]},
        }))
        # Wait for subscription acknowledgement.
        try:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=10.0)
            ack = json.loads(raw)
            if ack.get("statusCode") != 200:
                logger.warning("WebSocket subscribe ack unexpected: %s", ack)
        except asyncio.TimeoutError:
            logger.warning("No WebSocket subscribe ack received within 10 s")

        self._ws_task = asyncio.create_task(self._ws_receiver())
        self._heartbeat_task = asyncio.create_task(self._ws_heartbeat())
        logger.info("WebSocket open and subscribed | contact_id=%s", self._contact_id)

    async def _ws_receiver(self) -> None:
        """Background task: push all incoming WebSocket messages into the queue."""
        assert self._ws is not None
        try:
            async for raw in self._ws:
                try:
                    envelope = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if envelope.get("topic") != "aws/chat":
                    continue

                content_str = envelope.get("content", "{}")
                try:
                    item = json.loads(content_str)
                except json.JSONDecodeError:
                    continue

                if item.get("Type") != "MESSAGE":
                    continue
                if item.get("ContentType") not in ("text/plain", "text/markdown"):
                    continue

                role = item.get("ParticipantRole", "")
                text = item.get("Content", "").strip()
                display = item.get("DisplayName", role)
                noise = role in _BOT_ROLES and _is_flow_noise(text)

                # Skip echoes of our own sent messages — Connect WS echoes
                # every CUSTOMER message back to us; we don't need them.
                if role == "CUSTOMER":
                    logger.debug("ws_receiver: skipping CUSTOMER echo %r", text[:60])
                    continue

                if role in _BOT_ROLES:
                    r = "agent"
                else:
                    r = "system"

                msg = AdapterMessage(
                    role=r,
                    content=text,
                    display_name=display,
                    is_noise=noise,
                )
                await self._message_queue.put(msg)
                logger.debug(
                    "ws_receiver: role=%s noise=%s content=%r",
                    r, noise, text[:60],
                )
        except websockets.exceptions.ConnectionClosed:
            logger.info("WebSocket connection closed | contact_id=%s", self._contact_id)
        except Exception as exc:
            logger.warning("ws_receiver error: %s", exc)

    async def _ws_heartbeat(self) -> None:
        """Background task: send a ping every 30 s to keep the WebSocket alive."""
        assert self._ws is not None
        try:
            while True:
                await asyncio.sleep(30)
                try:
                    await self._ws.send(json.dumps({"topic": "aws/ping"}))
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    async def _drain_noise(self, stable_secs: float = 3.0, max_wait: float = 15.0) -> None:
        """
        Consume all queued messages until the queue has been idle for *stable_secs*.

        Used after connect() to swallow the Connect flow greeting before the
        customer's first message is sent.
        """
        deadline = time.monotonic() + max_wait
        last_item_at = time.monotonic()
        print("    [drain] waiting for flow", end="", flush=True)
        while time.monotonic() < deadline:
            idle = time.monotonic() - last_item_at
            if idle >= stable_secs:
                break
            try:
                await asyncio.wait_for(self._message_queue.get(), timeout=0.5)
                last_item_at = time.monotonic()
                print(".", end="", flush=True)
            except asyncio.TimeoutError:
                pass
        print(f". done", flush=True)

    async def _simulate_typing(self, text: str) -> None:
        """
        Emit a typing indicator and wait a WPM-proportional delay, then stop.

        This mimics the behaviour of the chat widget's typing bubble so ARIA
        receives realistic inter-message timing.
        """
        if not self._connection_token:
            return
        word_count = max(1, len(text.split()))
        base_secs = (word_count / self.typing_wpm) * 60.0
        jitter = random.uniform(-0.15, 0.25) * base_secs
        delay = max(0.5, base_secs + jitter)

        print(f"    ✍  typing ({word_count} words, ~{delay:.1f}s)... ", end="", flush=True)
        try:
            self._participant.send_event(
                ContentType="application/vnd.amazonaws.connect.event.typing",
                ConnectionToken=self._connection_token,
            )
        except ClientError as exc:
            logger.debug("typing event failed (non-fatal): %s", exc)

        await asyncio.sleep(delay)
        print("↵", flush=True)

    def _safe_stop(self) -> None:
        """Stop the Connect chat contact, ignoring errors."""
        if self._contact_id:
            try:
                self._connect.stop_contact(
                    ContactId=self._contact_id,
                    InstanceId=self.instance_id,
                )
            except ClientError:
                pass
