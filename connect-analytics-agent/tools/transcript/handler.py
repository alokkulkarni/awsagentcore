import datetime as _dt
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from shared.connect_utils import build_error_response, build_response, get_instance_id, parse_csv, parse_parameters
from shared.scan_resources import get_contact_lens_bucket_and_prefix

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

ALLOWED_SEGMENT_TYPES = {"TRANSCRIPT", "ISSUES", "CATEGORIES", "SENSITIVE_DATA"}

# ResourceTypes to probe when looking for the Contact Lens S3 output bucket
_CL_STORAGE_RESOURCE_TYPES = ["REAL_TIME_CONTACT_ANALYSIS_SEGMENTS", "CALL_RECORDINGS"]


# ── Sentiment aggregation ──────────────────────────────────────────────────────

def _compute_sentiment_summary(segments: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Aggregate per-utterance sentiment fields into a contact-level sentiment summary.
    Works on segments from any source (CL real-time, Q Connect, post-call).

    Returns a dict:
      {
        "customer": {"counts": {...}, "total_turns": N, "overall": "POSITIVE"|..., "score": -1..+1},
        "agent":    {"counts": {...}, "total_turns": N, "overall": ..., "score": ...},
        "overall":  "POSITIVE" | "NEGATIVE" | "NEUTRAL" | "MIXED",
        "score":    -1.0 .. +1.0   (customer-weighted)
      }
    or None if no sentiment data is present in any segment.
    """
    if not segments:
        return None

    def _role_key(seg: Dict) -> str:
        r = (seg.get("speaker") or seg.get("participantRole") or seg.get("role") or "").upper()
        if seg.get("display_name") == "AI Agent" or r == "BOT":
            return "AGENT"   # AI agent utterances count as agent-side
        if r == "AGENT":
            return "AGENT"
        if r == "CUSTOMER":
            return "CUSTOMER"
        return "OTHER"

    counts: Dict[str, Dict[str, int]] = {
        "CUSTOMER": {"POSITIVE": 0, "NEGATIVE": 0, "NEUTRAL": 0, "MIXED": 0},
        "AGENT":    {"POSITIVE": 0, "NEGATIVE": 0, "NEUTRAL": 0, "MIXED": 0},
    }
    has_any = False

    for seg in segments:
        s = (seg.get("sentiment") or "").upper()
        if s not in ("POSITIVE", "NEGATIVE", "NEUTRAL", "MIXED"):
            continue
        has_any = True
        role = _role_key(seg)
        if role in counts:
            counts[role][s] += 1

    if not has_any:
        return None

    def _summarise(c: Dict[str, int]) -> Dict[str, Any]:
        total = sum(c.values())
        if total == 0:
            return {"counts": c, "total_turns": 0, "overall": "NEUTRAL", "score": 0.0}
        neg_ratio = c["NEGATIVE"] / total
        pos_ratio = c["POSITIVE"] / total
        if neg_ratio >= 0.45:
            label = "NEGATIVE"
        elif pos_ratio >= 0.55:
            label = "POSITIVE"
        elif neg_ratio >= 0.25:
            label = "MIXED"
        else:
            label = "NEUTRAL"
        score = round((c["POSITIVE"] - c["NEGATIVE"]) / total, 2)
        return {"counts": c, "total_turns": total, "overall": label, "score": score}

    cust = _summarise(counts["CUSTOMER"])
    agent = _summarise(counts["AGENT"])

    # Overall contact sentiment = customer-weighted (customers drive escalation risk)
    cust_total = cust["total_turns"]
    agent_total = agent["total_turns"]
    if cust_total + agent_total == 0:
        overall_score = 0.0
    elif cust_total == 0:
        overall_score = agent["score"]
    else:
        # Weight customer 70%, agent 30%
        overall_score = round(cust["score"] * 0.7 + agent["score"] * 0.3, 2)

    if overall_score <= -0.3:
        overall_label = "NEGATIVE"
    elif overall_score >= 0.3:
        overall_label = "POSITIVE"
    elif overall_score < -0.1:
        overall_label = "MIXED"
    else:
        overall_label = "NEUTRAL"

    return {
        "customer": cust,
        "agent":    agent,
        "overall":  overall_label,
        "score":    overall_score,
    }


# ── Q in Connect (Amazon Q Connect) AI session transcript ─────────────────────

def _qconnect_ai_transcript(contact_full: Dict[str, Any], contact_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch the Q in Connect AI agent conversation using qconnect.list_messages().

    The session ARN is stored in:
      - contact_full["WisdomInfo"]["SessionArn"]  (preferred)
      - contact_full["Attributes"]["sessionId"]   (fallback — same ARN value)

    ARN format: arn:aws:wisdom:{region}:{account}:session/{assistantId}/{sessionId}
    """
    session_arn: Optional[str] = None
    wisdom_info = contact_full.get("WisdomInfo") or {}
    if wisdom_info.get("SessionArn"):
        session_arn = wisdom_info["SessionArn"]
    else:
        attrs = contact_full.get("Attributes") or {}
        session_arn = attrs.get("sessionId")

    if not session_arn or ":session/" not in session_arn:
        return None

    try:
        resource_part = session_arn.split(":session/", 1)[1]   # "{assistantId}/{sessionId}"
        assistant_id, session_id = resource_part.split("/", 1)
    except (ValueError, IndexError) as exc:
        LOGGER.info("Cannot parse session ARN %s: %s", session_arn, exc)
        return None

    try:
        qc_client = boto3.client("qconnect")
        response = qc_client.list_messages(
            assistantId=assistant_id,
            sessionId=session_id,
            maxResults=100,
        )
        raw_messages = response.get("messages", [])
        if not raw_messages:
            LOGGER.info("Q Connect session %s has no messages yet for contact %s", session_id, contact_id)
            return None

        # Sort chronologically
        raw_messages.sort(key=lambda m: m.get("timestamp") or "")
        baseline_time = raw_messages[0].get("timestamp") if raw_messages else None
        segments: List[Dict[str, Any]] = []
        for msg in raw_messages:
            text = (msg.get("value") or {}).get("text", {}).get("value", "").strip()
            if not text:
                continue
            participant = (msg.get("participant") or "").upper()
            speaker = "AGENT" if participant == "BOT" else "CUSTOMER"
            display = "AI Agent" if participant == "BOT" else "Customer"

            ts = msg.get("timestamp")
            offset_ms = None
            if ts and baseline_time:
                try:
                    offset_ms = int((ts - baseline_time).total_seconds() * 1000)
                except Exception:  # pylint: disable=broad-except
                    pass

            segments.append({
                "segment_type": "TRANSCRIPT",
                "speaker": speaker,
                "display_name": display,
                "text": text,
                "start_offset_millis": offset_ms,
                "end_offset_millis": offset_ms,
                "sentiment": None,
                "issues_detected": [],
            })

        if not segments:
            return None

        still_active = not contact_full.get("DisconnectTimestamp")
        LOGGER.info("Returning Q Connect AI transcript for contact %s (%d turns)", contact_id, len(segments))
        return {
            "segments": segments,
            "channel": contact_full.get("Channel", "VOICE"),
            "status": "IN_PROGRESS" if still_active else "COMPLETED",
            "source": "qconnect_messages",
            "next_token": response.get("nextToken"),
        }
    except ClientError as exc:
        LOGGER.info("Q Connect list_messages failed for %s: %s", contact_id, exc)
        return None
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.info("Unexpected error fetching Q Connect transcript for %s: %s", contact_id, exc)
        return None

def _realtime_segments(contact_lens_client, instance_id: str, contact_id: str) -> Dict[str, Any]:
    response = contact_lens_client.list_realtime_contact_analysis_segments(
        InstanceId=instance_id,
        ContactId=contact_id,
        MaxResults=100,
    )
    segments: List[Dict[str, Any]] = []
    for segment in response.get("Segments", []):
        transcript = segment.get("Transcript")
        if not transcript:
            continue
        segments.append({
            "segment_type": "TRANSCRIPT",
            "speaker": transcript.get("ParticipantRole"),
            "display_name": transcript.get("ParticipantRole"),
            "text": transcript.get("Content"),
            "start_offset_millis": transcript.get("BeginOffsetMillis"),
            "end_offset_millis": transcript.get("EndOffsetMillis"),
            "sentiment": transcript.get("Sentiment"),
            "issues_detected": transcript.get("IssuesDetected", []),
        })
    return {"segments": segments, "status": "IN_PROGRESS", "source": "realtime", "next_token": response.get("NextToken")}


# ── Post-call analysis — Contact Lens S3 output ───────────────────────────────

def _find_contact_lens_bucket(connect_client, instance_id: str) -> Tuple[Optional[str], str]:
    """Return (bucket, base_key_prefix) for Contact Lens S3 output — uses scan data with live fallback."""
    return get_contact_lens_bucket_and_prefix(instance_id, connect_client)


def _contact_full(connect_client, instance_id: str, contact_id: str) -> Dict[str, Any]:
    """Return the full Contact object from describe_contact, or {} on error."""
    try:
        return connect_client.describe_contact(InstanceId=instance_id, ContactId=contact_id).get("Contact", {})
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.info("describe_contact failed: %s", exc)
        return {}


def _contact_info(connect_client, instance_id: str, contact_id: str) -> Tuple[str, Any, Any]:
    """Return (channel, initiation_timestamp, disconnect_timestamp) for a contact."""
    c = _contact_full(connect_client, instance_id, contact_id)
    return c.get("Channel", "VOICE"), c.get("InitiationTimestamp"), c.get("DisconnectTimestamp")


def _seconds_since_disconnect(disconnect_ts) -> Optional[float]:
    """Return seconds elapsed since the contact disconnected, or None if still active."""
    if not disconnect_ts:
        return None
    try:
        if not hasattr(disconnect_ts, "tzinfo"):
            return None
        now = _dt.datetime.now(tz=_dt.timezone.utc)
        return (now - disconnect_ts.replace(tzinfo=_dt.timezone.utc) if disconnect_ts.tzinfo is None else now - disconnect_ts).total_seconds()
    except Exception:  # pylint: disable=broad-except
        return None


def _automated_interaction_transcript(connect_client, instance_id: str, contact_id: str) -> Optional[Dict[str, Any]]:
    """
    Check describe_contact Recordings for MediaStreamType=AUTOMATED_INTERACTION.
    If found, download and parse the interaction log JSON directly from S3.
    Returns transcript dict or None.
    """
    contact = _contact_full(connect_client, instance_id, contact_id)
    for rec in contact.get("Recordings", []):
        if rec.get("MediaStreamType") == "AUTOMATED_INTERACTION" and rec.get("Status") == "AVAILABLE":
            location = rec.get("Location", "")
            # Location = "{bucket}/{key}"
            parts = location.split("/", 1)
            if len(parts) != 2:
                continue
            bucket, key = parts[0], parts[1]
            LOGGER.info("Found AUTOMATED_INTERACTION log at s3://%s/%s", bucket, key)
            try:
                s3_client = boto3.client("s3")
                obj = s3_client.get_object(Bucket=bucket, Key=key)
                data = json.loads(obj["Body"].read().decode("utf-8"))
                return _parse_automated_interaction_log(data, contact_id)
            except Exception as exc:  # pylint: disable=broad-except
                LOGGER.warning("Failed to download automated interaction log: %s", exc)
    return None


def _parse_automated_interaction_log(data: Dict[str, Any], contact_id: str) -> Dict[str, Any]:
    """
    Parse Amazon Connect AUTOMATED_INTERACTION_LOG JSON into the shared segments format.
    Structure: { "InteractionLogs": [ { "LogType": "Message", "Source": "Customer"|"Lex", "AbsoluteTime": ..., "LogData": { "Content": ... } } ] }
    """
    segments: List[Dict[str, Any]] = []
    baseline_time = None

    for entry in data.get("InteractionLogs", []):
        if entry.get("LogType") != "Message":
            continue
        content = (entry.get("LogData", {}).get("Content") or "").strip()
        if not content:
            continue

        source = entry.get("Source", "")
        # Map Lex/Bot sources to AGENT role for display, Customer stays CUSTOMER
        speaker = "CUSTOMER" if source == "Customer" else "AGENT"
        display = source  # "Customer", "Lex", etc.

        abs_time_str = entry.get("AbsoluteTime")
        offset_ms = None
        if abs_time_str:
            try:
                abs_time = _dt.datetime.fromisoformat(abs_time_str.replace("Z", "+00:00"))
                if baseline_time is None:
                    baseline_time = abs_time
                offset_ms = int((abs_time - baseline_time).total_seconds() * 1000)
            except Exception:  # pylint: disable=broad-except
                pass

        segments.append({
            "segment_type": "TRANSCRIPT",
            "speaker": speaker,
            "display_name": display,
            "text": content,
            "start_offset_millis": offset_ms,
            "end_offset_millis": offset_ms,
            "sentiment": None,
            "issues_detected": [],
        })

    return {
        "segments": segments,
        "channel": "VOICE",
        "status": "COMPLETED",
        "source": "automated_interaction_log",
        "contact_id": contact_id,
        "next_token": None,
    }


def _search_s3_for_analysis(s3_client, bucket: str, prefix: str, contact_id: str, channel: str, initiation_time) -> Optional[str]:
    """Return the S3 key of the Contact Lens analysis JSON or chat transcript JSON, or None."""
    channel_path = "Chat" if channel == "CHAT" else "Voice"

    search_prefixes: List[str] = []
    if initiation_time:
        date_path = initiation_time.strftime("%Y/%m/%d")
        if channel == "CHAT":
            # Native Connect chat transcripts path
            search_prefixes.append(f"{prefix}/ChatTranscripts/{date_path}/{contact_id}")
            search_prefixes.append(f"{prefix}/UnprocessedChatTranscripts/{date_path}/{contact_id}")
        # Contact Lens analysis path (both Voice and Chat)
        search_prefixes.append(f"{prefix}/Analysis/{channel_path}/{date_path}/{contact_id}")
        search_prefixes.append(f"{prefix}/ContactLens/{channel_path}/{date_path}/{contact_id}")
    # Broad fallbacks
    if channel == "CHAT":
        search_prefixes.append(f"{prefix}/ChatTranscripts")
    search_prefixes.append(f"{prefix}/Analysis/{channel_path}")

    for sp in search_prefixes:
        try:
            response = s3_client.list_objects_v2(Bucket=bucket, Prefix=sp, MaxKeys=10)
            for obj in response.get("Contents", []):
                key = obj["Key"]
                if key.endswith(".json") and contact_id in key:
                    LOGGER.info("Found transcript/analysis at s3://%s/%s", bucket, key)
                    return key
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.info("S3 list under prefix %s failed: %s", sp, exc)

    return None


def _parse_contact_lens_json(data: Dict[str, Any], contact_id: str, channel: str) -> Dict[str, Any]:
    """Parse Contact Lens post-call analysis JSON into the shared segments format."""
    segments: List[Dict[str, Any]] = []
    for turn in data.get("Transcript", []):
        segments.append({
            "segment_type": "TRANSCRIPT",
            "speaker": turn.get("ParticipantRole"),
            "display_name": turn.get("ParticipantRole"),
            "text": turn.get("Content"),
            "start_offset_millis": turn.get("BeginOffsetMillis"),
            "end_offset_millis": turn.get("EndOffsetMillis"),
            "sentiment": turn.get("Sentiment"),
            "issues_detected": turn.get("IssuesDetected", []),
        })
    return {
        "segments": segments,
        "channel": data.get("Channel", channel),
        "status": "COMPLETED",
        "source": "s3_contact_lens",
        "conversation_characteristics": data.get("ConversationCharacteristics"),
        "categories": data.get("Categories"),
        "next_token": None,
    }


def _parse_chat_transcript_json(data: Dict[str, Any], contact_id: str) -> Dict[str, Any]:
    """Parse the native Amazon Connect chat transcript JSON (ChatTranscripts/) into segments format."""
    segments: List[Dict[str, Any]] = []
    baseline_time: Optional[Any] = None

    for turn in data.get("Transcript", []):
        if turn.get("Type") != "MESSAGE":
            continue  # skip join/leave/ended events
        content = (turn.get("Content") or "").strip()
        if not content:
            continue  # skip empty system messages

        abs_time_str = turn.get("AbsoluteTime")
        offset_ms = None
        if abs_time_str:
            try:
                abs_time = _dt.datetime.fromisoformat(abs_time_str.replace("Z", "+00:00"))
                if baseline_time is None:
                    baseline_time = abs_time
                offset_ms = int((abs_time - baseline_time).total_seconds() * 1000)
            except Exception:  # pylint: disable=broad-except
                pass

        segments.append({
            "segment_type": "TRANSCRIPT",
            "speaker": turn.get("ParticipantRole"),
            "display_name": turn.get("DisplayName") or turn.get("ParticipantRole"),
            "text": content,
            "start_offset_millis": offset_ms,
            "end_offset_millis": offset_ms,
            "sentiment": None,
            "issues_detected": [],
        })
    return {
        "segments": segments,
        "channel": "CHAT",
        "status": "COMPLETED",
        "source": "s3_chat_transcript",
        "next_token": None,
    }


def _s3_post_call_transcript(connect_client, instance_id: str, contact_id: str) -> Optional[Dict[str, Any]]:
    """Attempt to fetch the post-call transcript/analysis JSON from S3."""
    bucket, prefix = _find_contact_lens_bucket(connect_client, instance_id)
    if not bucket:
        LOGGER.info("No Contact Lens S3 bucket found — cannot load post-call transcript")
        return None

    channel, initiation_time, _ = _contact_info(connect_client, instance_id, contact_id)
    s3_client = boto3.client("s3")
    key = _search_s3_for_analysis(s3_client, bucket, prefix, contact_id, channel, initiation_time)
    if not key:
        LOGGER.info("Transcript/analysis JSON not found in S3 for contact %s", contact_id)
        return None

    try:
        obj = s3_client.get_object(Bucket=bucket, Key=key)
        data = json.loads(obj["Body"].read().decode("utf-8"))
        # Distinguish native chat transcript from Contact Lens analysis by key path
        if "/ChatTranscripts/" in key or "/UnprocessedChatTranscripts/" in key:
            return _parse_chat_transcript_json(data, contact_id)
        return _parse_contact_lens_json(data, contact_id, channel)
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.info("Failed to download/parse transcript from s3://%s/%s: %s", bucket, key, exc)
        return None


# ── Lambda handler ─────────────────────────────────────────────────────────────

# Contact Lens post-call analysis is generated asynchronously after a call ends.
# These constants define when we consider a contact "still processing" vs "truly missing".
_PROCESSING_WINDOW_SECONDS = 5 * 60   # 5 minutes — analysis usually ready within this
_REALTIME_WINDOW_SECONDS   = 30 * 60  # 30 min — realtime API stays queryable this long


def lambda_handler(event, _context):
    params: Dict[str, Any] = {}
    try:
        params = parse_parameters(event.get("parameters"))
        instance_id = get_instance_id(params)
        contact_id = params.get("contact_id")
        if not contact_id:
            raise ValueError("contact_id is required.")

        segment_types = [s.upper() for s in parse_csv(params.get("segment_types"))] or ["TRANSCRIPT"]
        invalid = [s for s in segment_types if s not in ALLOWED_SEGMENT_TYPES]
        if invalid:
            raise ValueError(f"Unsupported segment_types: {', '.join(invalid)}")

        connect_client = boto3.client("connect")

        # Fetch contact details once — we need channel + disconnect time for decisions.
        contact_full = _contact_full(connect_client, instance_id, contact_id)
        channel = contact_full.get("Channel", "VOICE")
        disconnect_ts = contact_full.get("DisconnectTimestamp")
        secs_since_end = _seconds_since_disconnect(disconnect_ts)
        still_active = secs_since_end is None  # no disconnect timestamp → call in progress

        # ── Step A: Always collect Q Connect AI session messages (bot phase history) ──────────
        # These are available for any contact that went through a Q in Connect flow block.
        # We fetch BEFORE CL real-time so we can merge them with the human-agent phase.
        qc_result   = _qconnect_ai_transcript(contact_full, contact_id)
        qc_segments: List[Dict[str, Any]] = qc_result.get("segments", []) if qc_result else []
        if qc_segments:
            LOGGER.info("Q Connect: %d AI-agent segments for contact %s", len(qc_segments), contact_id)

        # ── Step B: Real-time Contact Lens (human-agent phase, active during call + ~30 min) ─
        # A successful API call with 0 segments → CL IS configured but hasn't produced output.
        # An exception → CL is not configured for this contact.
        cl_realtime_enabled = False
        cl_segments: List[Dict[str, Any]] = []
        try:
            cl_client = boto3.client("connect-contact-lens")
            rt_result = _realtime_segments(cl_client, instance_id, contact_id)
            cl_realtime_enabled = True  # API call succeeded → CL is configured
            cl_segments = rt_result.get("segments", [])
            if cl_segments:
                LOGGER.info("CL real-time: %d segments for contact %s", len(cl_segments), contact_id)
            else:
                LOGGER.info("CL real-time enabled for %s but no segments yet", contact_id)
        except ClientError as exc:
            err_code = exc.response.get("Error", {}).get("Code", "")
            if err_code in ("ResourceNotFoundException", "ContactNotFoundException"):
                LOGGER.info("Contact Lens real-time not configured for contact %s", contact_id)
            elif err_code == "AccessDeniedException":
                LOGGER.warning("Access denied for CL real-time on %s — check IAM permissions", contact_id)
            else:
                LOGGER.info("CL real-time API error for %s: %s", contact_id, exc)
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.info("CL real-time unavailable for %s: %s", contact_id, exc)

        # ── Step C: Merge Q Connect history + CL real-time into one unified transcript ────────
        # Q Connect = bot/AI phase (always first in time)
        # CL real-time = human-agent phase (appended after bot history)
        # Together they give the complete end-to-end conversation view.
        all_segments = qc_segments + cl_segments
        if all_segments:
            if qc_segments and cl_segments:
                source = "merged"
            elif qc_segments:
                source = "qconnect_messages"
            else:
                source = "cl_realtime"
            LOGGER.info(
                "Returning %s transcript for %s (qc=%d cl=%d total=%d)",
                source, contact_id, len(qc_segments), len(cl_segments), len(all_segments),
            )
            sentiment_summary = _compute_sentiment_summary(all_segments)
            return build_response(event, {
                "contact_id":          contact_id,
                "segment_types":       segment_types,
                "still_active":        still_active,
                "segments":            all_segments,
                "status":              "IN_PROGRESS" if still_active else "COMPLETED",
                "source":              source,
                "channel":             channel,
                "cl_realtime_enabled": cl_realtime_enabled,
                "qc_segments_count":   len(qc_segments),
                "cl_segments_count":   len(cl_segments),
                "sentiment_summary":   sentiment_summary,
            })

        # 2. AI agent AUTOMATED_INTERACTION recording log (Q in Connect / Nova Sonic).
        #    This is usually available within seconds of the call ending.
        ai_result = _automated_interaction_transcript(connect_client, instance_id, contact_id)
        if ai_result:
            LOGGER.info("Returning AI interaction log for %s (%d turns)", contact_id, len(ai_result.get("segments", [])))
            return build_response(event, {
                "contact_id": contact_id,
                "segment_types": segment_types,
                "still_active": still_active,
                **ai_result,
            })

        # 3. Post-call Contact Lens analysis from S3 (available 2–5 min after call ends).
        s3_result = _s3_post_call_transcript(connect_client, instance_id, contact_id)
        if s3_result:
            LOGGER.info("Returning S3 post-call analysis for %s", contact_id)
            return build_response(event, {
                "contact_id": contact_id,
                "segment_types": segment_types,
                "still_active": False,
                **s3_result,
            })

        # 4. Nothing found — determine WHY and set appropriate status for the UI.
        if still_active:
            if cl_realtime_enabled:
                # Contact Lens real-time IS configured (API succeeded) but no segments yet.
                # Transcription may not have started (early in call, bot intro, or CCP lag).
                # Tell the UI to retry in ~10 seconds.
                msg = (
                    "Real-time transcription is enabled and initialising. "
                    "Segments will appear as the conversation progresses — please retry in a few seconds."
                )
                return build_response(
                    event,
                    {"contact_id": contact_id, "segments": [], "channel": channel,
                     "status": "ACTIVE_CL_STARTING", "still_active": True, "processing": False,
                     "retry_after_seconds": 4, "message": msg},
                    status_code=200,
                )
            # Contact Lens real-time not configured in this contact flow.
            # Check if this is an AI agent call (WisdomInfo present but no QC messages yet).
            has_wisdom = bool((contact_full.get("WisdomInfo") or {}).get("SessionArn"))
            if has_wisdom:
                msg = (
                    "AI agent is handling this call. The Q in Connect session has been located "
                    "but contains no messages yet. Retrying in 10 seconds…"
                )
                return build_response(
                    event,
                    {"contact_id": contact_id, "segments": [], "channel": channel,
                     "status": "ACTIVE_CL_STARTING", "still_active": True, "processing": False,
                     "retry_after_seconds": 4, "message": msg},
                    status_code=200,
                )
            msg = (
                "This contact is still active but no real-time transcript is available. "
                "To enable real-time transcription: open the contact flow in Amazon Connect, "
                "add a 'Set recording and analytics behaviour' block, and enable "
                "'Contact Lens real-time analysis'."
            )
            return build_response(
                event,
                {"contact_id": contact_id, "segments": [], "channel": channel,
                 "status": "ACTIVE_NO_REALTIME", "still_active": True, "processing": False, "message": msg},
                status_code=200,
            )

        if secs_since_end is not None and secs_since_end < _PROCESSING_WINDOW_SECONDS:
            # Call ended recently — Contact Lens is still generating the post-call analysis.
            remaining = max(0, int(_PROCESSING_WINDOW_SECONDS - secs_since_end))
            mins = remaining // 60
            secs = remaining % 60
            wait_hint = f"{mins}m {secs}s" if mins else f"{secs}s"
            msg = (
                f"Contact Lens is still processing this contact. "
                f"Post-call analysis is typically ready within 5 minutes of a call ending. "
                f"Please retry in approximately {wait_hint}."
            )
            return build_response(
                event,
                {"contact_id": contact_id, "segments": [], "channel": channel,
                 "status": "PROCESSING", "still_active": False,
                 "processing": True,
                 "retry_after_seconds": min(30, remaining),
                 "message": msg},
                status_code=200,
            )

        # Call ended > 5 min ago and still nothing — likely a config or permissions issue.
        if channel == "VOICE":
            msg = (
                "No transcript found for this voice contact. "
                "The call ended more than 5 minutes ago so Contact Lens should have processed it by now. "
                "Check that: (1) the contact flow has 'Set recording and analytics behaviour' with "
                "Contact Lens enabled, (2) this account has s3:GetObject and s3:ListBucket permissions "
                "on the Contact Lens output S3 bucket, and (3) Contact Lens is enabled in the "
                "Amazon Connect Analytics tools settings."
            )
        else:
            msg = (
                "No transcript found for this contact. "
                "Check that CHAT_TRANSCRIPTS storage is configured in the Connect instance "
                "and that this account has s3:GetObject permission on the output bucket."
            )
        return build_response(
            event,
            {"contact_id": contact_id, "segments": [], "channel": channel,
             "status": "NOT_FOUND", "still_active": False, "processing": False, "message": msg},
            status_code=200,
        )

    except (ClientError, BotoCoreError) as exc:
        LOGGER.exception("Failed to fetch transcript segments")
        return build_error_response(event, "Unable to fetch Amazon Connect transcript", status_code=502)
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("Unexpected error while fetching transcript segments")
        return build_error_response(event, "An unexpected error occurred while fetching the transcript", status_code=500)
