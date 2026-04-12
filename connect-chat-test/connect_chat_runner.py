#!/usr/bin/env python3
"""
Amazon Connect chat session client.

Uses boto3 connect + connectparticipant to drive a chat conversation
with a Lex bot via Amazon Connect contact flows.
"""

import logging
import time
from typing import Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class ChatStartError(RuntimeError):
    """Raised when the chat session cannot be established."""


class ChatSendError(RuntimeError):
    """Raised when a message cannot be sent to the chat."""


class ConnectChatSession:
    """
    Manages a single Amazon Connect chat session lifecycle.

    Usage::

        with ConnectChatSession(instance_id, contact_flow_id) as session:
            session.send_message("Hello")
            reply = session.receive_response(timeout=10)
    """

    def __init__(
        self,
        instance_id: str,
        contact_flow_id: str,
        region: str = "eu-west-2",
        display_name: str = "AutomationBot",
        chat_duration_minutes: int = 5,
        poll_interval: float = 1.0,
        max_poll_attempts: int = 20,
    ) -> None:
        self.instance_id = instance_id
        self.contact_flow_id = contact_flow_id
        self.region = region
        self.display_name = display_name
        self.chat_duration_minutes = chat_duration_minutes
        self.poll_interval = poll_interval
        self.max_poll_attempts = max_poll_attempts

        self._connect = boto3.client("connect", region_name=region)
        self._participant = boto3.client("connectparticipant", region_name=region)

        self._contact_id: Optional[str] = None
        self._participant_token: Optional[str] = None
        self._connection_token: Optional[str] = None
        # Track message IDs already seen so get_transcript re-polls don't re-match old messages
        self._seen_message_ids: set[str] = set()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Start the Amazon Connect chat contact and establish a participant
        connection.  Must be called before send_message / receive_response.

        Raises ChatStartError on failure.
        """
        try:
            resp = self._connect.start_chat_contact(
                InstanceId=self.instance_id,
                ContactFlowId=self.contact_flow_id,
                ParticipantDetails={"DisplayName": self.display_name},
                ChatDurationInMinutes=self.chat_duration_minutes,
            )
            self._contact_id = resp["ContactId"]
            self._participant_token = resp["ParticipantToken"]
            logger.info("Chat contact started | contact_id=%s", self._contact_id)
        except ClientError as exc:
            raise ChatStartError(
                f"start_chat_contact failed: {exc}"
            ) from exc

        try:
            conn_resp = self._participant.create_participant_connection(
                # CONNECTION_CREDENTIALS is sufficient for polling via get_transcript.
                # WEBSOCKET is only needed for streaming/real-time events (voice/WebRTC).
                Type=["CONNECTION_CREDENTIALS"],
                ParticipantToken=self._participant_token,
            )
            self._connection_token = (
                conn_resp["ConnectionCredentials"]["ConnectionToken"]
            )
            logger.info("Participant connection established.")
        except ClientError as exc:
            # Clean up the orphaned contact before propagating
            self._safe_stop_contact()
            raise ChatStartError(
                f"create_participant_connection failed: {exc}"
            ) from exc

    def send_message(self, text: str) -> None:
        """
        Send a plain-text message to the chat channel.

        Raises ChatSendError on failure.
        """
        if not self._connection_token:
            raise ChatSendError("Session is not started. Call start() first.")
        try:
            self._participant.send_message(
                ContentType="text/plain",
                Content=text,
                ConnectionToken=self._connection_token,
            )
            logger.debug("Sent: %r", text)
        except ClientError as exc:
            raise ChatSendError(
                f"send_message failed for text={text!r}: {exc}"
            ) from exc

    def receive_response(
        self,
        timeout: float,
        poll_interval: Optional[float] = None,
    ) -> Optional[str]:
        """
        Poll get_transcript until a new bot/system message appears.

        Returns the combined text of new bot messages, or None if timed out.

        The _seen_message_ids set prevents re-matching messages from
        previous turns (get_transcript always returns full history).
        """
        interval = poll_interval if poll_interval is not None else self.poll_interval
        deadline = time.monotonic() + timeout
        bot_roles = {"BOT", "SYSTEM", "AGENT"}

        while time.monotonic() < deadline:
            try:
                resp = self._participant.get_transcript(
                    ConnectionToken=self._connection_token,
                    MaxResults=20,
                    ScanDirection="BACKWARD",
                    SortOrder="DESCENDING",
                )
            except ClientError as exc:
                logger.warning("get_transcript failed: %s — retrying.", exc)
                time.sleep(interval)
                continue

            new_msgs = [
                item
                for item in resp.get("Transcript", [])
                if item.get("Type") == "MESSAGE"
                and item.get("ParticipantRole") in bot_roles
                and item.get("Id") not in self._seen_message_ids
            ]

            if new_msgs:
                for msg in new_msgs:
                    self._seen_message_ids.add(msg["Id"])
                # Messages come back DESCENDING; reverse to get chronological order
                combined = " ".join(
                    m["Content"] for m in reversed(new_msgs)
                )
                logger.debug("Received: %r", combined)
                return combined

            time.sleep(interval)

        logger.warning("Timed out after %.1fs waiting for bot response.", timeout)
        return None

    def disconnect(self) -> None:
        """
        Disconnect the participant and end the chat session.
        Safe to call even if the session already expired.
        """
        if not self._connection_token:
            return
        try:
            self._participant.disconnect_participant(
                ConnectionToken=self._connection_token
            )
            logger.info("Participant disconnected.")
        except ClientError as exc:
            # Session may already be expired — log at DEBUG, not ERROR
            logger.debug(
                "disconnect_participant error (session may be expired): %s", exc
            )

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "ConnectChatSession":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.disconnect()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _safe_stop_contact(self) -> None:
        """Best-effort stop of an orphaned contact."""
        if not self._contact_id:
            return
        try:
            self._connect.stop_contact(
                ContactId=self._contact_id,
                InstanceId=self.instance_id,
            )
        except ClientError:
            pass
