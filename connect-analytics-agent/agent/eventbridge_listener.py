"""
EventBridge → SQS contact event listener — full coverage.

Amazon Connect publishes ALL contact state changes to EventBridge:
  source: "aws.connect"
  detail-type: "Amazon Connect Contact Event"

A deploy-time EventBridge rule forwards those events to an SQS standard queue.
This module polls that queue in a daemon thread and maintains an in-memory
registry of ALL active contacts, categorised by type:

  • INBOUND   — customer called/chatted/task in
  • OUTBOUND  — agent or flow placed an outbound call (OUTBOUND / EXTERNAL_OUTBOUND)
  • CALLBACK  — customer requested a callback (CALLBACK / CALLBACK_SCHEDULED)
  • TRANSFER  — contact transferred between queues or agents
  • BOT/IVR   — contact being handled by IVR / conversational-AI (not yet agent)

Contact state lifecycle (Amazon Connect EventBridge — eventType field):
  INITIATED            → contact just created / arrived in system
  QUEUED               → waiting in a queue for a human agent
  CALLBACK_SCHEDULED   → callback queued (will fire later)
  CONNECTED_TO_SYSTEM  → contact being handled by IVR / AI agent / bot
  CONNECTED_TO_AGENT   → human agent answered
  DISCONNECTED / ENDED / MISSED / ERROR / REJECTED / EXPIRED → terminal

Amazon Connect AI Agent (Q) internal contacts:
  When the AI agent handles a voice call, Connect creates a CHILD contact with:
    - relatedContactId = parent VOICE contact ID
    - eventType        = CONNECTED_TO_SYSTEM
    - channel          = CHAT (or VOICE depending on integration)
  These are internal AI session contacts, NOT real customer contacts.
  They are marked isInternalBotSession=True and filtered from UI counts.
  Their arrival causes the PARENT voice contact to be marked isBot=True.

NOTE: Amazon Connect EventBridge Contact Events use "eventType" (not "contactState")
      for the lifecycle state. queueInfo contains "queueArn" but not "queueName"
      directly — we extract the queue ID from the ARN and do a background lookup.

Outbound calls: agentInfo.agentArn is set at INITIATED if an agent placed the call.
Callbacks: initiationMethod=CALLBACK; CALLBACK_SCHEDULED state = scheduled but not yet fired.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

LOGGER = logging.getLogger(__name__)

# ── In-memory store ───────────────────────────────────────────────────────────
# contactId → contact record (all active contacts across all types)
_contacts: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()
_running = False
_thread: Optional[threading.Thread] = None

# ── Name caches (background-populated from Connect API) ───────────────────────
_queue_name_cache: Dict[str, str] = {}   # queueArn  → queue display name
_agent_name_cache: Dict[str, str] = {}   # agentArn  → agent display name

# How long to keep a contact after it reaches a terminal state (so the UI
# can still show it briefly as "recently ended" before it disappears).
_TERMINAL_GRACE_SECONDS = 15  # 15 s — short enough to feel responsive

# Auto-expire active contacts that never received a terminal event.
# Covers the case where DISCONNECTED expired from SQS before listener started.
_STALE_CONTACT_SECONDS = 20 * 60  # 20 minutes

# States that indicate a contact has ended permanently.
# COMPLETED is used by tasks and also appears in contactState for some voice calls.
_TERMINAL_STATES = {"DISCONNECTED", "ENDED", "MISSED", "ERROR", "REJECTED", "EXPIRED", "COMPLETED"}

# Initiation methods categorised
_OUTBOUND_METHODS = {"OUTBOUND", "EXTERNAL_OUTBOUND"}
_CALLBACK_METHODS = {"CALLBACK"}
_TRANSFER_METHODS = {"TRANSFER", "QUEUE_TRANSFER"}


# ── Public API ────────────────────────────────────────────────────────────────

def start(queue_url: str, region: str, poll_interval: int = 5) -> None:
    """Start the background SQS polling daemon thread."""
    global _running, _thread
    if _running:
        return
    _running = True
    _thread = threading.Thread(
        target=_poll_loop,
        args=(queue_url, region, poll_interval),
        daemon=True,
        name="eventbridge-contact-listener",
    )
    _thread.start()
    LOGGER.info("EventBridge contact listener started (queue=%s, region=%s)", queue_url, region)


def stop() -> None:
    """Signal the polling thread to exit."""
    global _running
    _running = False
    LOGGER.info("EventBridge contact listener stopping")


def is_running() -> bool:
    return _running and _thread is not None and _thread.is_alive()


# ── Public query helpers ───────────────────────────────────────────────────────

def get_all_live_contacts() -> List[Dict[str, Any]]:
    """
    All contacts within the active+grace window.
    Includes recently-terminal contacts (for brief "Ended" display in the UI).
    Each contact has contactTerminal (bool) and contactEndedAt (str|None).
    """
    with _lock:
        return _snapshot_active()


def get_active_bot_contacts() -> List[Dict[str, Any]]:
    """IVR/bot contacts currently active — not yet handed to a human agent (backward-compat)."""
    with _lock:
        return [c for c in _snapshot_live_only()
                if c.get("isBot") or (c.get("contactType") == "inbound" and not c.get("escalatedToAgent"))]


def get_outbound_contacts() -> List[Dict[str, Any]]:
    """All outbound calls currently active."""
    with _lock:
        return [c for c in _snapshot_live_only() if c.get("isOutbound")]


def get_callback_contacts() -> List[Dict[str, Any]]:
    """Callback contacts — both 'scheduled' (not yet fired) and 'waiting' (in queue)."""
    with _lock:
        return [c for c in _snapshot_live_only() if c.get("isCallback")]


def get_callbacks_by_queue() -> Dict[str, Dict[str, int]]:
    """
    Returns callback counts keyed by queue name:
      { "Queue A": {"waiting": 2, "scheduled": 1}, ... }
    """
    with _lock:
        result: Dict[str, Dict[str, int]] = {}
        for c in _snapshot_live_only():
            if not c.get("isCallback"):
                continue
            q = c.get("queueName") or "Unknown"
            bucket = result.setdefault(q, {"waiting": 0, "scheduled": 0})
            if c.get("callbackScheduled"):
                bucket["scheduled"] += 1
            else:
                bucket["waiting"] += 1
        return result


def get_outbound_by_agent() -> Dict[str, List[Dict[str, Any]]]:
    """Outbound calls grouped by agentArn."""
    with _lock:
        result: Dict[str, List[Dict[str, Any]]] = {}
        for c in _snapshot_live_only():
            if not c.get("isOutbound"):
                continue
            agent = c.get("outboundAgentArn") or c.get("agentArn") or "Unknown"
            result.setdefault(agent, []).append(c)
        return result


def get_summary() -> Dict[str, int]:
    """
    Aggregate KPI counts across all contact types.
    Only ACTIVE (non-terminal) contacts are counted — so counts drop to zero
    immediately when a call ends, not after the grace period.
    Internal bot-session contacts are excluded from all counts.
    """
    with _lock:
        live = _snapshot_live_only()
        # Exclude internal AI/bot session contacts from all counts — they are system artefacts.
        real = [c for c in live if not c.get("isInternalBotSession")]
        return {
            "total":               len(real),
            "inbound":             sum(1 for c in real if c.get("contactType") == "inbound"),
            "outbound":            sum(1 for c in real if c.get("isOutbound")),
            "callbacks_waiting":   sum(1 for c in real if c.get("isCallback") and not c.get("callbackScheduled")),
            "callbacks_scheduled": sum(1 for c in real if c.get("isCallback") and c.get("callbackScheduled")),
            "bot_handling":        sum(1 for c in real if c.get("isBot")),
            "agent_connected":     sum(1 for c in real if c.get("escalatedToAgent")),
            "transfers":           sum(1 for c in real if c.get("contactType") == "transfer"),
            "voice":               sum(1 for c in real if c.get("channel") == "VOICE"),
            "chat":                sum(1 for c in real if c.get("channel") == "CHAT"),
            "task":                sum(1 for c in real if c.get("channel") == "TASK"),
        }


# ── Private helpers ───────────────────────────────────────────────────────────

def _snapshot_active() -> List[Dict[str, Any]]:
    """
    Must be called with _lock held.
    Returns all non-expired contacts — including recently-terminal ones within the
    grace window so the UI can show a brief "recently ended" state.
    Public fields include:
      contactTerminal (bool)  — True if the contact has ended
      contactEndedAt  (str)   — ISO-8601 timestamp when the terminal event arrived

    NOTE: queue and agent names are resolved from the live cache at snapshot time.
    Background lookup threads may have completed since the contact event was stored,
    so we always prefer fresh cache values over what was stored in the contact record.
    """
    now = datetime.now(timezone.utc).timestamp()
    result = []
    for c in _contacts.values():
        if c.get("_terminal"):
            ended_at = c.get("_terminal_epoch", 0)
            if now - ended_at > _TERMINAL_GRACE_SECONDS:
                continue  # grace period expired — remove from all lists
            public = {k: v for k, v in c.items() if not k.startswith("_")}
            public["contactTerminal"] = True
            public["contactEndedAt"] = (
                datetime.fromtimestamp(ended_at, tz=timezone.utc).isoformat()
                if ended_at else None
            )
        else:
            # Auto-expire stale active contacts that never received a terminal event.
            initiated = c.get("initiatedAt") or c.get("updatedAt", "")
            try:
                epoch = datetime.fromisoformat(initiated.replace("Z", "+00:00")).timestamp()
                if now - epoch > _STALE_CONTACT_SECONDS:
                    continue
            except Exception:  # pylint: disable=broad-except
                pass
            public = {k: v for k, v in c.items() if not k.startswith("_")}
            public["contactTerminal"] = False
            public["contactEndedAt"] = None

        # ── Resolve latest queue/agent names from cache ───────────────────────
        # The contact record stores whatever was available at event time.
        # Background threads may have completed the API lookup since then,
        # so always refresh from the cache before serving the snapshot.
        q_arn = public.get("queueArn", "")
        if q_arn:
            cached_q = _queue_name_cache.get(q_arn, "")
            if cached_q:  # non-empty = resolved (empty string means pending)
                public["queueName"] = cached_q

        a_arn = public.get("agentArn", "")
        if a_arn:
            cached_a = _agent_name_cache.get(a_arn, "")
            if cached_a:  # non-empty = resolved
                public["agentName"] = cached_a

        result.append(public)
    return sorted(result, key=lambda x: x.get("initiatedAt", ""), reverse=True)


def _snapshot_live_only() -> List[Dict[str, Any]]:
    """
    Must be called with _lock held.
    Returns ONLY non-terminal contacts — used for KPI counts so that counts
    drop to zero immediately when a call ends, not after the grace period.
    """
    return [c for c in _snapshot_active() if not c.get("contactTerminal")]


def _contact_type(initiation_method: str, state: str) -> str:
    if initiation_method in _OUTBOUND_METHODS:
        return "outbound"
    if initiation_method in _CALLBACK_METHODS or state == "CALLBACK_SCHEDULED":
        return "callback"
    if initiation_method in _TRANSFER_METHODS:
        return "transfer"
    return "inbound"


def _agent_name_from_arn(agent_arn: str) -> str:
    """Best-effort: return cached human name, or extract ID from ARN last segment."""
    if not agent_arn:
        return ""
    return _agent_name_cache.get(agent_arn) or agent_arn.rstrip("/").rsplit("/", 1)[-1]


def _id_from_arn(arn: str) -> str:
    """Extract the last path segment from any ARN (queue ID, agent ID, etc.)."""
    if not arn:
        return ""
    return arn.rstrip("/").rsplit("/", 1)[-1]


def _parse_connect_arn(arn: str) -> Dict[str, str]:
    """
    Parse an Amazon Connect ARN into usable components.
    Format: arn:aws:connect:<region>:<account>:instance/<INSTANCE_ID>/<type>/<RESOURCE_ID>
    """
    if not arn:
        return {}
    try:
        parts = arn.split(":")
        resource_parts = (parts[5] if len(parts) > 5 else "").split("/")
        return {
            "region":      parts[3] if len(parts) > 3 else "",
            "account":     parts[4] if len(parts) > 4 else "",
            "instance_id": resource_parts[1] if len(resource_parts) > 1 else "",
            "resource_id": resource_parts[3] if len(resource_parts) > 3 else resource_parts[-1],
        }
    except Exception:
        return {}


def _schedule_queue_name_lookup(queue_arn: str) -> None:
    """Background: call Connect API to resolve queue ARN → human name, cache result."""
    if not queue_arn or _queue_name_cache.get(queue_arn):
        return  # already resolved (non-empty); skip if currently pending too
    _queue_name_cache[queue_arn] = ""  # mark as pending to avoid duplicate threads

    def _lookup() -> None:
        try:
            import boto3  # pylint: disable=import-outside-toplevel
            info = _parse_connect_arn(queue_arn)
            if not info.get("instance_id") or not info.get("resource_id"):
                return
            client = boto3.client("connect", region_name=info["region"])
            resp = client.describe_queue(
                InstanceId=info["instance_id"],
                QueueId=info["resource_id"],
            )
            name = resp.get("Queue", {}).get("Name", "")
            if name:
                _queue_name_cache[queue_arn] = name
                LOGGER.info("Queue name resolved: %s → %s", queue_arn, name)
            else:
                # Remove pending marker so next contact event retries
                _queue_name_cache.pop(queue_arn, None)
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning("Queue name lookup failed for %s: %s", queue_arn, exc)
            _queue_name_cache.pop(queue_arn, None)  # allow retry next time

    threading.Thread(target=_lookup, daemon=True, name="queue-name-lookup").start()


def _schedule_agent_name_lookup(agent_arn: str) -> None:
    """Background: call Connect API to resolve agent ARN → first+last name, cache result."""
    if not agent_arn or _agent_name_cache.get(agent_arn):
        return  # already resolved (non-empty means done); skip if pending too briefly
    _agent_name_cache[agent_arn] = ""  # mark as pending

    def _lookup() -> None:
        try:
            import boto3  # pylint: disable=import-outside-toplevel
            info = _parse_connect_arn(agent_arn)
            if not info.get("instance_id") or not info.get("resource_id"):
                return
            client = boto3.client("connect", region_name=info["region"])
            resp = client.describe_user(
                InstanceId=info["instance_id"],
                UserId=info["resource_id"],
            )
            user = resp.get("User", {})
            id_info = user.get("IdentityInfo", {})
            first = id_info.get("FirstName", "")
            last  = id_info.get("LastName", "")
            name  = f"{first} {last}".strip() or user.get("Username", "")
            if name:
                _agent_name_cache[agent_arn] = name
                LOGGER.info("Agent name resolved: %s → %s", agent_arn, name)
            else:
                _agent_name_cache.pop(agent_arn, None)  # allow retry
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning("Agent name lookup failed for %s: %s", agent_arn, exc)
            _agent_name_cache.pop(agent_arn, None)  # allow retry next time

    threading.Thread(target=_lookup, daemon=True, name="agent-name-lookup").start()


def _format_endpoint(endpoint: Optional[dict]) -> Dict[str, str]:
    """
    Normalise a Connect endpoint object into a display-safe dict.

    Amazon Connect supplies:
        { "type": "TELEPHONE_NUMBER", "address": "+441234567890" }
    For chat contacts the type may be "CONTACT_FLOW" or omitted.

    Returns:
        {
          "type":    "TELEPHONE_NUMBER",   # raw endpoint type
          "address": "+441234567890",      # full address (kept for server-side use)
          "display": "****7890",           # masked display — last 4 digits revealed
        }
    An empty dict is returned when no endpoint is present.
    """
    if not endpoint or not isinstance(endpoint, dict):
        return {}
    addr = endpoint.get("address", "")
    etype = endpoint.get("type", "")
    if addr and etype == "TELEPHONE_NUMBER":
        # Keep last 4 digits visible, mask the rest
        visible = addr[-4:] if len(addr) >= 4 else addr
        masked = "*" * max(0, len(addr) - 4) + visible
        display = masked
    else:
        display = addr  # for non-phone endpoints show as-is (no PII to mask)
    return {"type": etype, "address": addr, "display": display}


# ── Private: polling loop ─────────────────────────────────────────────────────

def _poll_loop(queue_url: str, region: str, interval: int) -> None:
    import boto3  # pylint: disable=import-outside-toplevel

    sqs = boto3.client("sqs", region_name=region)
    wait = min(interval, 20)  # SQS long-poll max 20 s

    while _running:
        try:
            resp = sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=wait,
                MessageAttributeNames=["All"],
            )
            for msg in resp.get("Messages", []):
                try:
                    _process_message(msg)
                    sqs.delete_message(
                        QueueUrl=queue_url,
                        ReceiptHandle=msg["ReceiptHandle"],
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    LOGGER.warning("Failed to process contact event message: %s", exc)
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning("SQS poll error: %s", exc)
            time.sleep(max(interval, 5))


def _process_message(msg: dict) -> None:
    """Parse an SQS message and update the registry for ALL contact types."""
    raw = json.loads(msg.get("Body", "{}"))

    # EventBridge → SQS sends directly; EventBridge → SNS → SQS wraps in Notification
    if raw.get("Type") == "Notification":
        event = json.loads(raw.get("Message", "{}"))
    else:
        event = raw

    detail_type = event.get("detail-type", "")

    # Handle Amazon Connect Agent Events separately (agent availability)
    if "Agent Event" in detail_type:
        _process_agent_event(event.get("detail", {}))
        return

    # Main path: Amazon Connect Contact Event
    detail = event.get("detail", {})
    contact_id = detail.get("contactId")
    if not contact_id:
        return

    # Amazon Connect EventBridge Contact Events store lifecycle state in "eventType",
    # NOT "contactState". Values: INITIATED, QUEUED, CONNECTED_TO_SYSTEM,
    # CONNECTED_TO_AGENT, DISCONNECTED, ENDED, MISSED, ERROR, REJECTED, EXPIRED, etc.
    state = (
        detail.get("eventType")
        or detail.get("contactState")
        or detail.get("state")
        or ""
    ).upper()
    channel = detail.get("channel", "VOICE")
    initiation_method = (detail.get("initiationMethod") or "").upper()
    initiated_at = detail.get("initiationTimestamp") or detail.get("eventTimestamp")
    agent_info = detail.get("agentInfo") or {}
    queue_info = detail.get("queueInfo") or {}
    related_contact_id = detail.get("relatedContactId")
    tags = detail.get("tags") or {}

    customer_endpoint = _format_endpoint(detail.get("customerEndpoint"))
    system_endpoint   = _format_endpoint(detail.get("systemEndpoint"))

    # ── Queue info: EventBridge supplies queueArn but NOT queueName.
    # Extract the queue ID from the ARN and schedule a background name lookup.
    queue_arn  = queue_info.get("queueArn", "")
    queue_id   = queue_info.get("queueId") or _id_from_arn(queue_arn)
    if queue_arn:
        _schedule_queue_name_lookup(queue_arn)
    # Use cached name if available, else queue ID from ARN, else "—"
    queue_name = (
        queue_info.get("queueName")
        or (_queue_name_cache.get(queue_arn) if queue_arn else None)
        or queue_id
        or None
    )

    # ── Agent info: schedule background name lookup for human-readable name.
    agent_arn = agent_info.get("agentArn", "")
    if agent_arn:
        _schedule_agent_name_lookup(agent_arn)
    agent_name = _agent_name_from_arn(agent_arn)  # uses cache if already resolved

    ctype = _contact_type(initiation_method, state)
    is_outbound = initiation_method in _OUTBOUND_METHODS
    is_callback = initiation_method in _CALLBACK_METHODS or state == "CALLBACK_SCHEDULED"
    callback_scheduled = state == "CALLBACK_SCHEDULED"
    outbound_agent_arn = agent_arn if is_outbound else None

    # ── Detect internal Amazon Connect AI/bot session contacts ────────────────
    # When the Q in Connect AI agent handles a call it may create a CHILD contact:
    #   relatedContactId  = parent voice contact ID
    #   eventType         = CONNECTED_TO_SYSTEM   ← only reliable signal
    # That child is an internal artefact — NOT a real customer contact.
    #
    # Key rules:
    #   1. ONLY mark a contact as internal when its state is CONNECTED_TO_SYSTEM
    #      AND it has a relatedContactId (pointing to the real customer contact).
    #   2. NEVER mark transfer contacts as internal — initiationMethod TRANSFER/QUEUE_TRANSFER
    #      always means a real contact going to a human agent.
    #   3. NEVER mark a contact as internal if its state is QUEUED or CONNECTED_TO_AGENT
    #      — those states mean human interaction is in progress.
    #   4. Preserve the internal flag across subsequent events for an already-identified
    #      internal contact, UNLESS it later transitions to QUEUED/CONNECTED_TO_AGENT.
    #
    # NOTE: We do NOT use "relatedContactId in _contacts" as a detection signal.
    # Amazon Connect may add relatedContactId to the CUSTOMER contact in later events
    # (e.g., the QUEUED event after bot hand-off) — that would cause false positives.
    _human_interaction_states = {"CONNECTED_TO_AGENT", "QUEUED"}
    is_internal_bot_session = (
        state == "CONNECTED_TO_SYSTEM"
        and bool(related_contact_id)
        and initiation_method not in _TRANSFER_METHODS
        and initiation_method not in _OUTBOUND_METHODS
        and initiation_method not in _CALLBACK_METHODS
    )

    with _lock:
        existing = _contacts.get(contact_id, {})

        # Preserve internal flag for already-identified bot sessions across subsequent events.
        # Exception: if the contact has now progressed to a human-interaction state,
        # strip the internal flag — something mis-classified earlier gets a second chance.
        if not is_internal_bot_session and existing.get("isInternalBotSession"):
            if state not in _human_interaction_states and initiation_method not in _TRANSFER_METHODS:
                is_internal_bot_session = True
            # else: contact transitioned to human interaction — treat as real henceforth

        if state in _TERMINAL_STATES:
            if contact_id in _contacts:
                _contacts[contact_id].update({
                    "contactState": state,
                    "_terminal": True,
                    "_terminal_epoch": datetime.now(timezone.utc).timestamp(),
                    "updatedAt": datetime.now(timezone.utc).isoformat(),
                })
            else:
                _contacts[contact_id] = {
                    "contactId": contact_id,
                    "channel": channel,
                    "initiationMethod": initiation_method,
                    "contactType": ctype,
                    "contactState": state,
                    "isOutbound": is_outbound,
                    "isCallback": is_callback,
                    "isBot": False,
                    "isInternalBotSession": is_internal_bot_session,
                    "escalatedToAgent": bool(agent_arn),
                    "customerEndpoint": customer_endpoint,
                    "systemEndpoint": system_endpoint,
                    "source": "eventbridge",
                    "_terminal": True,
                    "_terminal_epoch": datetime.now(timezone.utc).timestamp(),
                    "updatedAt": datetime.now(timezone.utc).isoformat(),
                }
            # When an internal bot session ends, clear the parent's bot flag
            # only if the parent hasn't already transitioned to QUEUED/agent.
            if is_internal_bot_session and related_contact_id and related_contact_id in _contacts:
                parent = _contacts[related_contact_id]
                if not parent.get("escalatedToAgent") and parent.get("contactState") == "INITIATED":
                    parent["isBot"] = False
            return

        # ── Bot flag logic ────────────────────────────────────────────────────
        # CONNECTED_TO_SYSTEM = contact is explicitly with bot/IVR/AI.
        # QUEUED              = waiting for a human — bot has handed off.
        # CONNECTED_TO_AGENT  = human agent answered.
        # INITIATED with isBot already True = bot flag preserved from child event.
        if state in {"CONNECTED_TO_AGENT", "QUEUED"}:
            is_bot = False  # heading to / with human
        elif state == "CONNECTED_TO_SYSTEM" or is_internal_bot_session:
            is_bot = True
        elif state == "INITIATED":
            # Preserve if a child bot-session event already set this flag
            is_bot = existing.get("isBot", False)
        else:
            is_bot = existing.get("isBot", False)

        escalated = existing.get("escalatedToAgent", False)
        if state == "CONNECTED_TO_AGENT" and agent_arn:
            escalated = True
            is_bot = False

        # Resolve queue name: prefer previously discovered name over raw ID
        resolved_queue_name = (
            queue_name
            or existing.get("queueName")
            or "—"
        )

        _contacts[contact_id] = {
            **existing,
            "contactId": contact_id,
            "channel": channel,
            "initiationMethod": initiation_method,
            "contactType": ctype,
            "contactState": state,
            "initiatedAt": initiated_at or existing.get("initiatedAt"),
            "relatedContactId": related_contact_id or existing.get("relatedContactId"),
            "tags": tags or existing.get("tags", {}),
            "customerEndpoint": customer_endpoint or existing.get("customerEndpoint", {}),
            "systemEndpoint":   system_endpoint   or existing.get("systemEndpoint", {}),
            "queueId":    queue_id    or existing.get("queueId"),
            "queueArn":   queue_arn   or existing.get("queueArn", ""),
            "queueName":  resolved_queue_name,
            "enqueuedAt": queue_info.get("enqueueTimestamp") or existing.get("enqueuedAt"),
            "inQueue": bool(queue_id),
            "agentArn":  agent_arn  or existing.get("agentArn", ""),
            "agentName": agent_name or existing.get("agentName", ""),
            "connectedToAgentAt": agent_info.get("connectedToAgentTimestamp") or existing.get("connectedToAgentAt"),
            "escalatedToAgent": escalated,
            "isBot": is_bot,
            "isInternalBotSession": is_internal_bot_session,
            "isOutbound": is_outbound,
            "outboundAgentArn":  outbound_agent_arn  or existing.get("outboundAgentArn", ""),
            "outboundAgentName": _agent_name_from_arn(outbound_agent_arn or "") or existing.get("outboundAgentName", ""),
            "isCallback": is_callback,
            "callbackScheduled": callback_scheduled,
            "source": "eventbridge",
            "_terminal": False,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }

        # When an AI session contact (CONNECTED_TO_SYSTEM) arrives, mark the
        # PARENT voice contact as bot-handled so it shows in Bot/IVR section.
        if is_internal_bot_session and related_contact_id and related_contact_id in _contacts:
            _contacts[related_contact_id]["isBot"] = True
            _contacts[related_contact_id]["botSessionContactId"] = contact_id
            LOGGER.debug("Parent contact %s marked isBot=True by AI session %s", related_contact_id, contact_id)

        LOGGER.info(
            "Contact %s state→%s type=%s ch=%s bot=%s internal=%s outbound=%s cb=%s initMethod=%s relatedTo=%s",
            contact_id, state, ctype, channel, is_bot, is_internal_bot_session,
            is_outbound, is_callback, initiation_method or "—", related_contact_id or "—",
        )


# ── Agent events (supplemental — tracks agent availability) ──────────────────
_agent_states: Dict[str, Dict[str, Any]] = {}

def _process_agent_event(detail: dict) -> None:
    """
    Track agent availability from Amazon Connect Agent Events.
    These fire when an agent changes status (Available, Busy, AfterCallWork, etc.)
    """
    agent_arn = detail.get("agentArn")
    if not agent_arn:
        return
    snapshot = detail.get("currentAgentSnapshot") or {}
    config = snapshot.get("configuration") or {}
    status = snapshot.get("agentStatus") or {}
    with _lock:
        _agent_states[agent_arn] = {
            "agentArn": agent_arn,
            "agentName": config.get("username") or _agent_name_from_arn(agent_arn),
            "firstName": config.get("firstName", ""),
            "lastName": config.get("lastName", ""),
            "status": status.get("name", ""),
            "statusType": status.get("type", ""),
            "activeContacts": [c.get("contactId") for c in snapshot.get("contacts", [])],
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }
    LOGGER.debug("Agent event: %s → %s", agent_arn, status.get("name"))


def get_agent_states() -> List[Dict[str, Any]]:
    """Return all known agent states from Agent Events."""
    with _lock:
        return list(_agent_states.values())
