"""
channels/voice_adapter.py
=========================
Fetches Contact Lens real-time or post-call analysis transcripts for a
completed Amazon Connect voice call and converts them into a ConversationLog
that the LLM-as-judge can evaluate.

This adapter does NOT make live calls. It is a post-hoc evaluator — you run
a real call first, then pass the ContactId here.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from channels.chat_adapter import ConversationLog, Turn

logger = logging.getLogger(__name__)


class VoiceAdapterError(RuntimeError):
    """Raised when the voice adapter cannot fetch or parse a transcript."""


class ARIAVoiceAdapter:
    """
    Fetches a Contact Lens transcript for a completed voice call.

    Attempts real-time analysis first (available for calls with Contact Lens
    real-time enabled), then falls back to post-call analysis.

    Usage::

        adapter = ARIAVoiceAdapter(instance_id=..., region="eu-west-2")
        log = adapter.fetch_transcript("abc-contact-id")
    """

    def __init__(self, instance_id: str, region: str = "eu-west-2") -> None:
        self.instance_id = instance_id
        self.region = region
        self._lens = boto3.client("connect-contact-lens", region_name=region)
        self._connect = boto3.client("connect", region_name=region)

    def fetch_transcript(self, contact_id: str) -> ConversationLog:
        """
        Fetch and parse a Contact Lens transcript, returning a ConversationLog.

        Args:
            contact_id: Amazon Connect ContactId for a completed voice call.

        Returns:
            ConversationLog with turns extracted from the Contact Lens transcript.
        """
        log = ConversationLog(
            scenario_name=f"Voice call {contact_id}",
            channel="voice",
            contact_id=contact_id,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        segments = self._get_all_segments(contact_id)
        if not segments:
            raise VoiceAdapterError(
                f"No Contact Lens transcript found for contact_id={contact_id}. "
                "Check that Contact Lens real-time analytics is enabled for the instance "
                "and that the call has completed."
            )

        turn_index = 0
        for seg in segments:
            transcript = seg.get("Transcript")
            if not transcript:
                continue

            participant = transcript.get("ParticipantRole", "UNKNOWN")
            content = transcript.get("Content", "")
            begin_offset = transcript.get("BeginOffsetMillis", 0)

            # Map Connect roles to evaluator roles
            role = "customer" if participant == "CUSTOMER" else "aria"
            turn_index += 1

            log.turns.append(Turn(
                turn_index=turn_index,
                role=role,
                content=content,
                timestamp=_offset_to_iso(log.started_at, begin_offset),
                status="ok",
            ))

        log.finished_at = datetime.now(timezone.utc).isoformat()
        log.status = "completed"
        return log

    # ── Private ─────────────────────────────────────────────────────────────

    def _get_all_segments(self, contact_id: str) -> list[dict]:
        """Paginate through all Contact Lens transcript segments."""
        segments = []
        next_token = None

        while True:
            kwargs: dict = {"InstanceId": self.instance_id, "ContactId": contact_id}
            if next_token:
                kwargs["NextToken"] = next_token

            try:
                resp = self._lens.list_realtime_contact_analysis_segments(**kwargs)
            except ClientError as exc:
                error_code = exc.response["Error"]["Code"]
                if error_code in ("ResourceNotFoundException", "AccessDeniedException"):
                    logger.warning(
                        "Contact Lens real-time segments unavailable for %s (%s). "
                        "Trying post-call analysis.",
                        contact_id, error_code,
                    )
                    return self._get_post_call_segments(contact_id)
                raise VoiceAdapterError(
                    f"list_realtime_contact_analysis_segments failed: {exc}"
                ) from exc

            segments.extend(resp.get("Segments", []))
            next_token = resp.get("NextToken")
            if not next_token:
                break

        return segments

    def _get_post_call_segments(self, contact_id: str) -> list[dict]:
        """Attempt to retrieve post-call Contact Lens transcript via the v2 segments API."""
        try:
            resp = self._connect.describe_contact(
                InstanceId=self.instance_id,
                ContactId=contact_id,
            )
            logger.info(
                "Post-call fallback: contact %s metadata: %s",
                contact_id, resp.get("Contact", {}),
            )
        except ClientError:
            pass

        # Use list_realtime_contact_analysis_segments_v2 — works for both in-progress
        # and completed contacts when Contact Lens real-time analysis is enabled.
        segments: list[dict] = []
        next_token = None
        while True:
            kwargs: dict = {
                "InstanceId": self.instance_id,
                "ContactId": contact_id,
                "SegmentTypes": ["TRANSCRIPT"],
            }
            if next_token:
                kwargs["NextToken"] = next_token
            try:
                resp = self._lens.list_realtime_contact_analysis_segments_v2(**kwargs)
            except ClientError as exc:
                logger.warning(
                    "Post-call analysis via v2 API failed for %s: %s. "
                    "Enable Contact Lens real-time analysis on the Connect instance.",
                    contact_id, exc,
                )
                break
            segments.extend(resp.get("Segments", []))
            next_token = resp.get("NextToken")
            if not next_token:
                break

        if not segments:
            logger.warning(
                "No post-call transcript retrieved for contact %s. "
                "Contact Lens real-time analysis must be enabled for post-call evaluation.",
                contact_id,
            )
        return segments


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _offset_to_iso(base_iso: str, offset_ms: int) -> str:
    """Convert a millisecond offset from call start to an ISO 8601 timestamp."""
    try:
        from datetime import timedelta
        base = datetime.fromisoformat(base_iso.replace("Z", "+00:00"))
        return (base + timedelta(milliseconds=offset_ms)).isoformat()
    except Exception:
        return base_iso
