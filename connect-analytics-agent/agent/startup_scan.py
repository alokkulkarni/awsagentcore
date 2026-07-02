"""Startup resource discovery for Amazon Connect Analytics Agent.

On first launch (or FORCE_RESCAN=true) one elected leader instance scans
every AWS resource associated with the Connect instance and writes a
discovered_resources.json.  All other instances (and subsequent requests)
read from that cached file.

SSE events are broadcast to every connected client so the React frontend
can animate the scan in real time.
"""

import asyncio
import json
import logging
import os
import socket
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError, EndpointResolutionError

LOGGER = logging.getLogger(__name__)

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
RESOURCES_FILE = DATA_DIR / "discovered_resources.json"
LOCK_FILE = DATA_DIR / ".scan_lock"
LEADER_TIMEOUT_SEC = 600  # 10 min — stale lock expiry

# Unique ID for this process boot — used by the frontend to detect server restarts
import uuid as _uuid
BOOT_ID: str = str(_uuid.uuid4())

# ── Shared scan state ─────────────────────────────────────────────────────────

_state: Dict[str, Any] = {
    "running":       False,
    "complete":      False,
    "is_leader":     False,
    "progress":      0.0,
    "phase_id":      "",
    "phase_label":   "",
    "phase_index":   0,
    "total_phases":  8,
    "message":       "Waiting to start…",
    "total_found":   0,
    "found":         {},   # category → count
    "log":           [],   # last 200 log lines
    "error":         None,
    "started_at":    None,
    "completed_at":  None,
}

_sse_queues: List[asyncio.Queue] = []
_scan_task: Optional[asyncio.Task] = None


def get_state() -> Dict[str, Any]:
    return dict(_state)


def register_queue(q: asyncio.Queue) -> None:
    _sse_queues.append(q)


def unregister_queue(q: asyncio.Queue) -> None:
    try:
        _sse_queues.remove(q)
    except ValueError:
        LOGGER.debug('Suppressed exception', exc_info=True)


def needs_scan() -> bool:
    if os.getenv("FORCE_RESCAN", "").lower() == "true":
        return True
    return not RESOURCES_FILE.exists()


def get_resources() -> Optional[Dict]:
    if RESOURCES_FILE.exists():
        try:
            return json.loads(RESOURCES_FILE.read_text())
        except Exception:
            return None
    return None


# ── Leader election ───────────────────────────────────────────────────────────

def _try_become_leader() -> bool:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE.exists():
        try:
            info = json.loads(LOCK_FILE.read_text())
            age = time.time() - info.get("ts", 0)
            if age < LEADER_TIMEOUT_SEC:
                return False
            LOCK_FILE.unlink(missing_ok=True)
        except Exception:
            try:
                LOCK_FILE.unlink(missing_ok=True)
            except Exception:
                LOGGER.debug('Suppressed exception', exc_info=True)
    try:
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as f:
            json.dump({
                "host":  socket.gethostname(),
                "pid":   os.getpid(),
                "ts":    time.time(),
                "scan_id": str(uuid.uuid4()),
            }, f)
        return True
    except FileExistsError:
        return False


def _release_leader() -> None:
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        LOGGER.debug('Suppressed exception', exc_info=True)


# ── SSE helpers ───────────────────────────────────────────────────────────────

async def _emit(event_type: str, **kwargs: Any) -> None:
    """Update shared state and push SSE event to all connected clients."""
    # Merge into state
    for k, v in kwargs.items():
        if k in _state:
            _state[k] = v
    if "log_line" in kwargs:
        _state["log"] = (_state["log"] + [kwargs["log_line"]])[-200:]
    if "found_delta" in kwargs:
        cat, delta = kwargs["found_delta"]
        _state["found"][cat] = _state["found"].get(cat, 0) + delta
        _state["total_found"] = sum(_state["found"].values())

    payload = json.dumps({
        "type": event_type,
        "ts":   datetime.now(timezone.utc).isoformat(),
        **{k: v for k, v in kwargs.items() if k not in ("found_delta",)},
        "progress":    _state["progress"],
        "total_found": _state["total_found"],
        "found":       dict(_state["found"]),
        "phase_index": _state["phase_index"],
    })
    msg = f"data: {payload}\n\n"

    dead = []
    for q in list(_sse_queues):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        unregister_queue(q)


# ── AWS helpers ───────────────────────────────────────────────────────────────

def _client(service: str, region: str) -> Any:
    return boto3.client(service, region_name=region)


def _safe(fn, default=None):
    try:
        return fn()
    except Exception as e:
        LOGGER.debug("AWS call failed: %s", e)
        return default


def _paginate_simple(client, method: str, list_key: str, **kwargs) -> List[Dict]:
    """Generic paginator that handles both get_paginator and nextToken loops."""
    items: List[Dict] = []
    try:
        pager = client.get_paginator(method)
        for page in pager.paginate(**kwargs):
            items.extend(page.get(list_key, []))
    except Exception:
        try:
            fn = getattr(client, method)
            resp = fn(**kwargs)
            items.extend(resp.get(list_key, []))
            while resp.get("NextToken") or resp.get("nextToken"):
                tok = resp.get("NextToken") or resp.get("nextToken")
                resp = fn(**{**kwargs, "NextToken": tok})
                items.extend(resp.get(list_key, []))
        except Exception as e2:
            LOGGER.debug("%s(%s) fallback failed: %s", method, list_key, e2)
    return items


# ── Flow Deep Scan Helpers ──────────────────────────────────────────────────────

_FLOW_DEEP_SCAN_TYPES = {
    "CONTACT_FLOW",
    "CUSTOMER_QUEUE",
    "AGENT_WHISPER",
    "OUTBOUND_WHISPER",
    "AGENT_HOLD",
    "CUSTOMER_HOLD",
}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "enabled"}
    return False


def _parse_lambda_name_from_arn(arn: str) -> str:
    if not arn:
        return ""
    if ":function:" in arn:
        return arn.split(":function:", 1)[1].split(":")[0]
    return arn.split(":")[-1]


def _parse_assistant_id_from_arn(arn: str) -> str:
    if not arn or "assistant/" not in arn:
        return ""
    return arn.split("assistant/", 1)[1].split("/")[0].split(":")[0]


def _parse_lex_bot_alias(alias_arn: str) -> Dict[str, str]:
    bot_id = ""
    alias_id = ""
    if alias_arn and "bot-alias/" in alias_arn:
        tail = alias_arn.split("bot-alias/", 1)[1]
        parts = tail.split("/")
        if parts:
            bot_id = parts[0]
        if len(parts) > 1:
            alias_id = parts[1].split(":")[0]
    return {"alias_arn": alias_arn, "bot_id": bot_id, "alias_id": alias_id}


def _extract_queue_reference(value: Any) -> Optional[Dict[str, str]]:
    if isinstance(value, str) and value:
        if value.startswith("arn:"):
            return {"id": "", "arn": value}
        return {"id": value, "arn": ""}
    if not isinstance(value, dict):
        return None
    queue_id = value.get("Id") or value.get("QueueId") or value.get("id") or ""
    queue_arn = value.get("Arn") or value.get("QueueArn") or value.get("arn") or ""
    if queue_id or queue_arn:
        return {"id": queue_id, "arn": queue_arn}
    return None


def _extract_contact_flow_references(value: Any) -> List[str]:
    refs: List[str] = []
    if isinstance(value, str) and value:
        return [value]
    if not isinstance(value, dict):
        return refs
    for key in ("Arn", "ContactFlowArn", "FlowArn", "Id", "ContactFlowId", "FlowId"):
        ref = value.get(key)
        if isinstance(ref, str) and ref:
            refs.append(ref)
    return refs


def _extract_prompt_text(params: Dict[str, Any]) -> str:
    candidates: List[Any] = [
        params.get("PromptText"),
        params.get("Prompt"),
        params.get("Text"),
        params.get("SSML"),
        params.get("Message"),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
        if isinstance(candidate, dict):
            for key in ("Text", "SSML", "PromptText", "Value", "Message"):
                value = candidate.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return ""


def _extract_dtmf_options(input_mappings: Any) -> List[Dict[str, str]]:
    entries: List[Any] = []
    if isinstance(input_mappings, list):
        entries = input_mappings
    elif isinstance(input_mappings, dict):
        for value in input_mappings.values():
            if isinstance(value, list):
                entries.extend(value)
            else:
                entries.append(value)

    options: List[Dict[str, str]] = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        keypad = entry.get("PhoneKeypad") or entry.get("PhoneKeypadInput") or {}
        if keypad or entry.get("InputType") == "PhoneKeypad":
            if isinstance(keypad, dict):
                key = keypad.get("Value") or keypad.get("Key") or keypad.get("PressedKey") or keypad.get("DtmfKey")
                label = entry.get("Label") or entry.get("Description") or entry.get("Name") or keypad.get("Label") or keypad.get("Value") or ""
            else:
                key = keypad or entry.get("Value") or entry.get("Key")
                label = entry.get("Label") or entry.get("Description") or entry.get("Name") or str(key or "")
            if key is None:
                continue
            option = {"key": str(key), "label": label or str(key)}
            dedupe_key = (option["key"], option["label"])
            if dedupe_key not in seen:
                seen.add(dedupe_key)
                options.append(option)
    return options


def _parse_flow_content(flow_id: str, flow_name: str, content_str: str) -> Dict[str, Any]:
    try:
        content = json.loads(content_str) if isinstance(content_str, str) else content_str
    except Exception as exc:  # pylint: disable=broad-except
        return {
            "flow_id": flow_id,
            "flow_name": flow_name,
            "error": f"Failed to parse flow content: {exc}",
        }

    if not isinstance(content, dict):
        return {
            "flow_id": flow_id,
            "flow_name": flow_name,
            "error": "Flow content was not a JSON object",
        }

    actions = content.get("Actions") or []
    if not isinstance(actions, list):
        actions = []

    block_types: Dict[str, None] = {}
    lambda_arns: Dict[str, None] = {}
    lex_alias_arns: Dict[str, Dict[str, str]] = {}
    assistant_arns: Dict[str, None] = {}
    assistant_ids: Dict[str, None] = {}
    ai_agent_version_arns: Dict[str, None] = {}
    lex_q_connect_agent_arns: Dict[str, None] = {}
    queues_referenced: Dict[tuple, Dict[str, str]] = {}
    sub_flows: Dict[str, None] = {}
    dtmf_menus: List[Dict[str, Any]] = []
    analytics: Dict[str, Any] = {
        "voice_realtime_enabled": False,
        "voice_post_call_enabled": False,
        "voice_automated_interaction_enabled": False,
        "voice_recording_enabled": False,
        "chat_analytics_enabled": False,
        "voice_analytics_language": "",
        "redaction_enabled": False,
    }

    for action in actions:
        if not isinstance(action, dict):
            continue
        block_type = action.get("Type") or ""
        if block_type:
            block_types.setdefault(block_type, None)
        params = action.get("Parameters") or {}
        if not isinstance(params, dict):
            params = {}

        if block_type == "InvokeLambdaFunction":
            arn = params.get("LambdaFunctionARN") or params.get("LambdaFunctionArn") or ""
            if arn:
                lambda_arns.setdefault(arn, None)

        if block_type in {"ConnectParticipantWithLexBot", "GetParticipantInput"}:
            alias_arn = ""
            if isinstance(params.get("LexV2Bot"), dict):
                alias_arn = params.get("LexV2Bot", {}).get("AliasArn", "")
            alias_arn = alias_arn or params.get("BotAliasArn") or ""
            if alias_arn:
                lex_alias_arns.setdefault(alias_arn, _parse_lex_bot_alias(alias_arn))

        if block_type == "ConnectParticipantWithLexBot":
            session_attrs = params.get("LexSessionAttributes") or {}
            if isinstance(session_attrs, dict):
                agent_arn = session_attrs.get("x-amz-lex:q-in-connect:ai-agent-arn") or ""
                if agent_arn:
                    lex_q_connect_agent_arns.setdefault(agent_arn, None)

        if block_type == "CreateWisdomSession":
            assistant_arn = params.get("WisdomAssistantArn") or ""
            if assistant_arn:
                assistant_arns.setdefault(assistant_arn, None)
                assistant_id = _parse_assistant_id_from_arn(assistant_arn)
                if assistant_id:
                    assistant_ids.setdefault(assistant_id, None)
            orchestration = params.get("OrchestrationAIAgentConfiguration") or {}
            if isinstance(orchestration, dict):
                agent_version_arn = orchestration.get("AgentAssistanceAgentVersionArn") or ""
                if agent_version_arn:
                    ai_agent_version_arns.setdefault(agent_version_arn, None)

        if block_type == "UpdateContactRecordingAndAnalyticsBehavior":
            voice_behavior = params.get("VoiceBehavior") or {}
            if isinstance(voice_behavior, dict):
                voice_recording = voice_behavior.get("VoiceRecordingBehavior") or {}
                if isinstance(voice_recording, dict):
                    recorded = voice_recording.get("RecordedParticipants") or []
                    analytics["voice_recording_enabled"] = analytics["voice_recording_enabled"] or bool(recorded) or _as_bool(voice_recording.get("Enabled")) or str(voice_recording.get("IVRRecordingBehavior", "")).lower() == "enabled"
                voice_analytics = voice_behavior.get("VoiceAnalyticsBehavior") or {}
                if isinstance(voice_analytics, dict):
                    modes = voice_analytics.get("AnalyticsModes") or []
                    if isinstance(modes, str):
                        modes = [modes]
                    analytics["voice_realtime_enabled"] = analytics["voice_realtime_enabled"] or "RealTime" in modes
                    analytics["voice_post_call_enabled"] = analytics["voice_post_call_enabled"] or "PostContact" in modes
                    analytics["voice_automated_interaction_enabled"] = analytics["voice_automated_interaction_enabled"] or "AutomatedInteraction" in modes
                    redaction = voice_analytics.get("ConversationalAnalyticsRedactionConfiguration") or {}
                    if isinstance(redaction, dict):
                        analytics["redaction_enabled"] = analytics["redaction_enabled"] or _as_bool(redaction.get("Enabled"))
                    if not analytics["voice_analytics_language"]:
                        for key in ("LanguageCode", "Language", "Locale"):
                            language = voice_analytics.get(key) or voice_behavior.get(key) or params.get(key)
                            if isinstance(language, str) and language:
                                analytics["voice_analytics_language"] = language
                                break
            chat_behavior = params.get("ChatBehavior") or {}
            if isinstance(chat_behavior, dict):
                chat_modes = chat_behavior.get("AnalyticsModes") or chat_behavior.get("ChatAnalyticsModes") or []
                analytics["chat_analytics_enabled"] = analytics["chat_analytics_enabled"] or _as_bool(chat_behavior.get("Enabled")) or bool(chat_modes)

        if block_type == "UpdateContactTargetQueue":
            queue_ref = _extract_queue_reference(params.get("Queue"))
            if queue_ref:
                queues_referenced[(queue_ref.get("id", ""), queue_ref.get("arn", ""))] = queue_ref

        if block_type == "TransferContactToQueue":
            for candidate in (
                params.get("Queue"),
                params.get("QueueArn"),
                params.get("QueueId"),
                params.get("TransferQueue"),
            ):
                queue_ref = _extract_queue_reference(candidate)
                if queue_ref:
                    queues_referenced[(queue_ref.get("id", ""), queue_ref.get("arn", ""))] = queue_ref
            for key in ("ContactFlowId", "ContactFlowArn"):
                ref = params.get(key)
                if isinstance(ref, str) and ref:
                    sub_flows.setdefault(ref, None)

        if block_type == "GetParticipantInput":
            dtmf_options = _extract_dtmf_options(params.get("InputMappings"))
            if dtmf_options:
                dtmf_menus.append({
                    "prompt": _extract_prompt_text(params),
                    "options": dtmf_options,
                })

        if block_type == "UpdateContactEventHooks":
            event_hooks = params.get("EventHooks") or {}
            if isinstance(event_hooks, dict):
                for ref in _extract_contact_flow_references(event_hooks.get("DefaultAgentUI")):
                    sub_flows.setdefault(ref, None)

        if block_type in {"InvokeFlowBlock", "TransferToFlow"}:
            for key in ("ContactFlow", "ContactFlowId", "ContactFlowArn", "Flow", "FlowArn", "FlowId"):
                for ref in _extract_contact_flow_references(params.get(key)):
                    sub_flows.setdefault(ref, None)
                raw_ref = params.get(key)
                if isinstance(raw_ref, str) and raw_ref:
                    sub_flows.setdefault(raw_ref, None)

    q_connect = {
        "assistant_arns": list(assistant_arns.keys()),
        "assistant_ids": list(assistant_ids.keys()),
        "ai_agent_version_arns": list(ai_agent_version_arns.keys()),
        "lex_q_connect_agent_arns": list(lex_q_connect_agent_arns.keys()),
    }

    return {
        "flow_id": flow_id,
        "flow_name": flow_name,
        "block_types": list(block_types.keys()),
        "lambda_functions": [
            {"arn": arn, "name": _parse_lambda_name_from_arn(arn)}
            for arn in lambda_arns.keys()
        ],
        "lex_v2_bots": list(lex_alias_arns.values()),
        "q_connect": q_connect,
        "analytics": analytics,
        "dtmf_menus": dtmf_menus,
        "queues_referenced": list(queues_referenced.values()),
        "sub_flows": list(sub_flows.keys()),
        "has_q_connect": bool(q_connect["assistant_arns"] or q_connect["ai_agent_version_arns"] or q_connect["lex_q_connect_agent_arns"]),
        "has_lex_bot": bool(lex_alias_arns),
        "has_lambda": bool(lambda_arns),
        "has_realtime_analytics": analytics["voice_realtime_enabled"],
    }


# ── Phase 1: Connect Core ─────────────────────────────────────────────────────

async def _phase_connect_core(
    connect, instance_id: str, region: str, result: Dict
) -> None:
    await _emit("phase_start", phase_id="connect_core",
                phase_label="Amazon Connect Core", phase_index=1,
                message="Describing Connect instance…")

    # Instance details
    inst = _safe(lambda: connect.describe_instance(InstanceId=instance_id)
                 .get("Instance", {}), {})
    result["connect"]["instance"] = {
        "id":     inst.get("Id", instance_id),
        "alias":  inst.get("InstanceAlias", ""),
        "arn":    inst.get("Arn", ""),
        "status": inst.get("InstanceStatus", ""),
        "created": str(inst.get("CreatedTime", "")),
    }
    await _emit("item_found", phase_id="connect_core", category="instance",
                name=inst.get("InstanceAlias", instance_id),
                found_delta=("instance", 1),
                log_line=f"✓ Instance: {inst.get('InstanceAlias', instance_id)}")

    # Queues
    await _emit("progress_update", message="Scanning queues…")
    queues = _paginate_simple(connect, "list_queues", "QueueSummaryList",
                              InstanceId=instance_id)
    result["connect"]["queues"] = [
        {"id": q.get("Id",""), "name": q.get("Name",""), "arn": q.get("Arn",""),
         "type": q.get("QueueType", "STANDARD")} for q in queues
    ]
    for q in queues:
        await _emit("item_found", phase_id="connect_core", category="queues",
                    name=q.get("Name","?"), found_delta=("queues", 1),
                    log_line=f"  Queue: {q.get('Name','?')}")
        await asyncio.sleep(0.05)

    # Agents / Users
    await _emit("progress_update", message="Scanning agents…")
    users = _paginate_simple(connect, "list_users", "UserSummaryList",
                             InstanceId=instance_id)
    result["connect"]["agents"] = [
        {"id": u.get("Id",""), "username": u.get("Username",""), "arn": u.get("Arn","")}
        for u in users
    ]
    for u in users:
        await _emit("item_found", phase_id="connect_core", category="agents",
                    name=u.get("Username", u.get("Id","?")), found_delta=("agents", 1),
                    log_line=f"  Agent: {u.get('Username', u.get('Id','?'))}")
        await asyncio.sleep(0.02)

    # Routing profiles
    await _emit("progress_update", message="Scanning routing profiles…")
    profiles = _paginate_simple(connect, "list_routing_profiles",
                                "RoutingProfileSummaryList", InstanceId=instance_id)
    result["connect"]["routing_profiles"] = [
        {"id": rp.get("Id",""), "name": rp.get("Name",""), "arn": rp.get("Arn","")} for rp in profiles
    ]
    await _emit("item_found", phase_id="connect_core", category="routing_profiles",
                name=f"{len(profiles)} profiles", found_delta=("routing_profiles", len(profiles)),
                log_line=f"  Routing profiles: {len(profiles)}")

    # Contact flows
    await _emit("progress_update", message="Scanning contact flows…")
    flows = _paginate_simple(connect, "list_contact_flows", "ContactFlowSummaryList",
                             InstanceId=instance_id)
    result["connect"]["contact_flows"] = [
        {"id": f.get("Id",""), "name": f.get("Name",""), "arn": f.get("Arn",""),
         "type": f.get("ContactFlowType", "")} for f in flows
    ]
    await _emit("item_found", phase_id="connect_core", category="flows",
                name=f"{len(flows)} flows", found_delta=("flows", len(flows)),
                log_line=f"  Contact flows: {len(flows)}")

    # Phone numbers
    await _emit("progress_update", message="Scanning phone numbers…")
    try:
        phones_resp = connect.list_phone_numbers_v2(InstanceId=instance_id, MaxResults=100)
        phones = phones_resp.get("ListPhoneNumbersSummaryList", [])
        while phones_resp.get("NextToken"):
            phones_resp = connect.list_phone_numbers_v2(
                InstanceId=instance_id, MaxResults=100,
                NextToken=phones_resp["NextToken"])
            phones.extend(phones_resp.get("ListPhoneNumbersSummaryList", []))
    except Exception:
        phones = _paginate_simple(connect, "list_phone_numbers", "PhoneNumberSummaryList",
                                  InstanceId=instance_id)
    result["connect"]["phone_numbers"] = [
        {"id": p.get("PhoneNumberId", p.get("Id", "")),
         "number": p.get("PhoneNumber", p.get("PhoneNumber", "")),
         "type": p.get("PhoneNumberType", p.get("PhoneType", "")),
         "country": p.get("PhoneNumberCountryCode", "")} for p in phones
    ]
    await _emit("item_found", phase_id="connect_core", category="phone_numbers",
                name=f"{len(phones)} numbers", found_delta=("phone_numbers", len(phones)),
                log_line=f"  Phone numbers: {len(phones)}")

    # Hours of operation
    hoo = _paginate_simple(connect, "list_hours_of_operations",
                           "HoursOfOperationSummaryList", InstanceId=instance_id)
    result["connect"]["hours_of_operation"] = [
        {"id": h.get("Id",""), "name": h.get("Name",""), "arn": h.get("Arn","")} for h in hoo
    ]

    # Security profiles
    sec = _paginate_simple(connect, "list_security_profiles",
                           "SecurityProfileSummaryList", InstanceId=instance_id)
    result["connect"]["security_profiles"] = [
        {"id": s.get("Id",""), "name": s.get("Name",""), "arn": s.get("Arn","")} for s in sec
    ]

    # Storage configs — discover S3 buckets and Kinesis streams via list (not describe)
    await _emit("progress_update", message="Reading storage configuration…")
    storage_types = [
        "CALL_RECORDINGS", "CHAT_TRANSCRIPTS", "CONTACT_TRACE_RECORDS",
        "AGENT_EVENTS", "REAL_TIME_CONTACT_ANALYSIS_SEGMENTS", "MEDIA_STREAMS",
    ]
    storage: Dict[str, Any] = {}
    for stype in storage_types:
        try:
            resp = connect.list_instance_storage_configs(
                InstanceId=instance_id, ResourceType=stype)
            cfgs = resp.get("StorageConfigs", [])
            if cfgs:
                storage[stype] = cfgs  # list of configs for this type
                LOGGER.info("Storage config %s: %d config(s)", stype, len(cfgs))
        except Exception as exc:
            LOGGER.warning("list_instance_storage_configs(%s) failed: %s", stype, exc)
    result["connect"]["storage_configs"] = storage
    if storage:
        await _emit("item_found", phase_id="connect_core", category="storage_configs",
                    name=f"{len(storage)} storage configs",
                    found_delta=("storage_configs", len(storage)),
                    log_line=f"  Storage configs: {', '.join(storage.keys())}")

    # Extract S3 buckets and Kinesis streams from storage configs
    _STRIP_SUFFIXES = ["/CallRecordings", "/ChatTranscripts", "/Reports", "/ContactTrace",
                       "/Analysis", "/ContactTraceRecords", "/AgentEvents", "/MediaStreams"]

    def _base_prefix(raw: str) -> str:
        p = (raw or "").rstrip("/")
        for suffix in _STRIP_SUFFIXES:
            if p.endswith(suffix):
                return p[: -len(suffix)]
        return p

    s3_buckets: Dict[str, Any] = {}
    kinesis_streams: Dict[str, str] = {}
    for stype, cfgs in storage.items():
        for cfg in (cfgs if isinstance(cfgs, list) else [cfgs]):
            s3c = cfg.get("S3Config", {})
            if s3c and s3c.get("BucketName") and stype not in s3_buckets:
                raw_prefix = s3c.get("BucketPrefix", "")
                s3_buckets[stype] = {
                    "bucket": s3c["BucketName"],
                    "prefix": _base_prefix(raw_prefix),
                    "raw_prefix": raw_prefix,
                }
            ks = cfg.get("KinesisStreamConfig", {})
            if ks and stype not in kinesis_streams:
                kinesis_streams[stype] = ks.get("StreamArn", "")
            kf = cfg.get("KinesisFirehoseConfig", {})
            if kf:
                kinesis_streams[f"{stype}_firehose"] = kf.get("FirehoseArn", "")
    result["_s3_from_config"] = s3_buckets
    result["_kinesis_from_config"] = kinesis_streams


    result["connect"]["totals"] = {
        "queues": len(queues), "agents": len(users),
        "routing_profiles": len(profiles), "contact_flows": len(flows),
        "phone_numbers": len(phones), "storage_configs": len(storage),
    }

    await _emit("phase_complete", phase_id="connect_core",
                phase_label="Amazon Connect Core",
                phase_index=1, progress=0.20,
                log_line="✅ Connect Core scan complete")


# ── Phase 2: Bots & Conversational AI ────────────────────────────────────────

async def _phase_bots(connect, lex_region: str, instance_id: str, result: Dict) -> None:
    await _emit("phase_start", phase_id="bots_ai",
                phase_label="Conversational AI", phase_index=2,
                message="Discovering Lex bots…")

    lex2 = _client("lexv2-models", lex_region)
    lex1 = _client("lex-models", lex_region)

    # Lex V2 bots via Connect
    v2_bots: List[Dict] = []
    try:
        v2_raw = _paginate_simple(connect, "list_bots", "LexBots",
                                  InstanceId=instance_id)
        for entry in v2_raw:
            alias_arn = entry.get("LexBot", {}).get("AliasArn", "")
            if not alias_arn:
                continue
            parts = alias_arn.split(":")
            bot_id = alias_arn.split("/bot-alias/")[-1].split("/")[0] if "/bot-alias/" in alias_arn else ""
            alias_id = alias_arn.split("/")[-1] if alias_arn else ""
            bot_name = bot_id
            try:
                desc = lex2.describe_bot(botId=bot_id)
                bot_name = desc.get("botName", bot_id)
            except Exception:
                LOGGER.debug('Suppressed exception', exc_info=True)
            v2_bots.append({
                "bot_id": bot_id, "bot_name": bot_name,
                "alias_id": alias_id, "alias_arn": alias_arn,
            })
            await _emit("item_found", phase_id="bots_ai", category="lex_v2",
                        name=bot_name, found_delta=("lex_v2_bots", 1),
                        log_line=f"  Lex V2 Bot: {bot_name}")
    except Exception as e:
        LOGGER.warning("list_bots (V2) failed: %s", e)

    # Lex V1 bots via Connect
    v1_bots: List[Dict] = []
    try:
        v1_raw = _paginate_simple(connect, "list_lex_bots", "LexBots",
                                  InstanceId=instance_id)
        for b in v1_raw:
            v1_bots.append({"name": b.get("Name", ""), "alias": b.get("LexAlias", "")})
            await _emit("item_found", phase_id="bots_ai", category="lex_v1",
                        name=b.get("Name", ""), found_delta=("lex_v1_bots", 1),
                        log_line=f"  Lex V1 Bot: {b.get('Name', '')}")
    except Exception:
        LOGGER.debug('Suppressed exception', exc_info=True)

    # Amazon Q in Connect
    q_assistants: List[Dict] = []
    await _emit("progress_update", message="Checking Amazon Q in Connect…")
    try:
        qconn = _client("wisdom", lex_region)
        resp = qconn.list_assistants()
        for a in resp.get("assistantSummaries", []):
            q_assistants.append({
                "id": a.get("assistantId", ""),
                "name": a.get("name", ""),
                "type": a.get("type", ""),
                "status": a.get("status", ""),
            })
            await _emit("item_found", phase_id="bots_ai", category="q_in_connect",
                        name=a.get("name", ""), found_delta=("q_assistants", 1),
                        log_line=f"  Q in Connect: {a.get('name', '')}")
    except Exception:
        LOGGER.debug('Suppressed exception', exc_info=True)

    # Lambda associations from Connect
    await _emit("progress_update", message="Listing Lambda associations…")
    lambda_fns: List[Dict] = []
    try:
        resp = connect.list_lambda_functions(InstanceId=instance_id)
        for arn in resp.get("LambdaFunctions", []):
            name = arn.split(":")[-1] if arn else ""
            lambda_fns.append({"arn": arn, "name": name})
            await _emit("item_found", phase_id="bots_ai", category="lambda_connect",
                        name=name, found_delta=("lambda_associations", 1),
                        log_line=f"  Lambda (Connect): {name}")
    except Exception:
        LOGGER.debug('Suppressed exception', exc_info=True)

    result["bots"] = {"lex_v2": v2_bots, "lex_v1": v1_bots, "q_assistants": q_assistants}
    result["lambda"]["connect_associations"] = lambda_fns

    await _emit("phase_complete", phase_id="bots_ai",
                phase_label="Conversational AI", phase_index=2,
                progress=0.35, log_line="✅ Conversational AI scan complete")


# ── Phase 3: Flow Content Deep Scan ────────────────────────────────────────────

async def _phase_flow_deep_scan(connect, instance_id: str, result: Dict) -> None:
    await _emit("phase_start", phase_id="flow_deep_scan",
                phase_label="Flow Content Deep Scan", phase_index=3,
                message="Deep scanning contact flow content…")

    flows = (result.get("connect") or {}).get("contact_flows", [])
    scannable_flows = [
        flow for flow in flows
        if flow.get("type") in _FLOW_DEEP_SCAN_TYPES
    ]
    total = len(scannable_flows)

    flow_components: Dict[str, Dict[str, Any]] = {}
    flows_by_lambda: Dict[str, List[str]] = {}
    flows_by_lex_bot: Dict[str, List[str]] = {}
    flows_by_q_assistant: Dict[str, List[str]] = {}
    flows_with_realtime_analytics: List[str] = []
    q_connect_ai_agents_in_flows: Dict[str, List[str]] = {}

    for index, flow in enumerate(scannable_flows):
        flow_id = flow.get("id", "")
        flow_name = flow.get("name", flow_id or "unknown")
        await _emit(
            "progress_update",
            message=f"Deep scanning flow {index + 1}/{total}: {flow_name}",
        )

        try:
            response = connect.describe_contact_flow(
                InstanceId=instance_id,
                ContactFlowId=flow_id,
            )
            described_flow = response.get("ContactFlow", {})
            components = _parse_flow_content(
                flow_id,
                flow_name,
                described_flow.get("Content", ""),
            )
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning("describe_contact_flow failed for %s (%s): %s", flow_name, flow_id, exc)
            components = {
                "flow_id": flow_id,
                "flow_name": flow_name,
                "error": str(exc),
            }
            await _emit(
                "progress_update",
                log_line=f"  [Flow deep scan error] {flow_name}: {exc}",
            )

        flow_components[flow_id] = components
        if components.get("error"):
            await _emit(
                "progress_update",
                log_line=f"  [Flow parse error] {flow_name}: {components['error']}",
            )
            await asyncio.sleep(0.05)
            continue

        for lambda_fn in components.get("lambda_functions", []):
            lambda_arn = lambda_fn.get("arn")
            if lambda_arn:
                flows_by_lambda.setdefault(lambda_arn, []).append(flow_id)

        for lex_bot in components.get("lex_v2_bots", []):
            alias_arn = lex_bot.get("alias_arn")
            if alias_arn:
                flows_by_lex_bot.setdefault(alias_arn, []).append(flow_id)

        q_connect = components.get("q_connect") or {}
        for assistant_id in q_connect.get("assistant_ids", []):
            if assistant_id:
                flows_by_q_assistant.setdefault(assistant_id, []).append(flow_id)

        for agent_version_arn in q_connect.get("ai_agent_version_arns", []):
            if agent_version_arn:
                q_connect_ai_agents_in_flows.setdefault(agent_version_arn, []).append(flow_id)

        if components.get("has_q_connect"):
            await _emit(
                "item_found",
                phase_id="flow_deep_scan",
                category="flow_with_q_connect",
                name=flow_name,
                found_delta=("flows_with_q_connect", 1),
                log_line=f"  [Q Connect] {flow_name}",
            )

        if components.get("has_realtime_analytics"):
            flows_with_realtime_analytics.append(flow_id)
            await _emit(
                "item_found",
                phase_id="flow_deep_scan",
                category="flow_realtime_analytics",
                name=flow_name,
                found_delta=("flows_with_realtime_analytics", 1),
                log_line=f"  [Realtime Analytics] {flow_name}",
            )

        await asyncio.sleep(0.05)

    result["connect"]["flow_components"] = flow_components
    result["connect"]["flows_by_lambda"] = {
        arn: sorted(set(flow_ids)) for arn, flow_ids in flows_by_lambda.items()
    }
    result["connect"]["flows_by_lex_bot"] = {
        arn: sorted(set(flow_ids)) for arn, flow_ids in flows_by_lex_bot.items()
    }
    result["connect"]["flows_by_q_assistant"] = {
        assistant_id: sorted(set(flow_ids))
        for assistant_id, flow_ids in flows_by_q_assistant.items()
    }
    result["connect"]["flows_with_realtime_analytics"] = sorted(set(flows_with_realtime_analytics))
    result["connect"]["q_connect_ai_agents_in_flows"] = {
        arn: sorted(set(flow_ids))
        for arn, flow_ids in q_connect_ai_agents_in_flows.items()
    }

    await _emit("phase_complete", phase_id="flow_deep_scan",
                phase_label="Flow Content Deep Scan", phase_index=3,
                progress=0.48,
                log_line=f"✅ Flow deep scan complete ({total} flows)")


# ── Phase 4: Lambda Functions ─────────────────────────────────────────────────

async def _phase_lambda(region: str, result: Dict) -> None:
    await _emit("phase_start", phase_id="lambda_fns",
                phase_label="Lambda Functions", phase_index=4,
                message="Scanning Lambda functions…")

    lam = _client("lambda", region)
    fns: List[Dict] = []
    try:
        pager = lam.get_paginator("list_functions")
        for page in pager.paginate():
            for fn in page.get("Functions", []):
                name = fn.get("FunctionName", "")
                # Heuristic: likely Connect-related
                is_connect = any(kw in name.lower()
                                 for kw in ("connect", "lex", "contact", "ivr",
                                            "queue", "routing", "agent", "chat"))
                fns.append({
                    "name": name,
                    "arn":  fn.get("FunctionArn", ""),
                    "runtime": fn.get("Runtime", ""),
                    "description": fn.get("Description", "")[:80],
                    "is_connect_related": is_connect,
                })
                if is_connect:
                    await _emit("item_found", phase_id="lambda_fns",
                                category="lambda_connect_related",
                                name=name, found_delta=("lambda_functions", 1),
                                log_line=f"  Lambda: {name}")
                    await asyncio.sleep(0.03)
    except Exception as e:
        LOGGER.warning("list_functions failed: %s", e)

    result["lambda"]["all_functions"] = fns
    result["lambda"]["connect_related"] = [f for f in fns if f["is_connect_related"]]

    await _emit("phase_complete", phase_id="lambda_fns",
                phase_label="Lambda Functions", phase_index=4,
                progress=0.58, log_line=f"✅ Lambda: {len(fns)} functions scanned")


# ── Phase 5: Data Storage (S3 + Kinesis) ─────────────────────────────────────

async def _phase_data_storage(region: str, result: Dict) -> None:
    await _emit("phase_start", phase_id="data_storage",
                phase_label="Data Storage", phase_index=5,
                message="Scanning S3 buckets…")

    s3_from_cfg = result.get("_s3_from_config", {})
    kinesis_from_cfg = result.get("_kinesis_from_config", {})

    def _bucket_name(stype: str) -> str:
        entry = s3_from_cfg.get(stype)
        if isinstance(entry, dict):
            return entry.get("bucket", "")
        return entry or ""

    def _bucket_prefix(stype: str) -> str:
        entry = s3_from_cfg.get(stype)
        if isinstance(entry, dict):
            return entry.get("prefix", "")
        return ""

    # S3 — list all, flag Connect-related ones
    s3 = _client("s3", region)
    all_buckets: List[Dict] = []
    cfg_buckets = {_bucket_name(k) for k in s3_from_cfg if _bucket_name(k)}
    connect_buckets: Dict[str, str] = {k: _bucket_name(k) for k in s3_from_cfg if _bucket_name(k)}

    try:
        resp = s3.list_buckets()
        for b in resp.get("Buckets", []):
            name = b.get("Name", "")
            is_connect = any(kw in name.lower()
                             for kw in ("connect", "recording", "ctr", "contact",
                                        "transcript", "kinesis-firehose"))
            all_buckets.append({"name": name, "is_connect": is_connect})
            if is_connect and name not in cfg_buckets:
                connect_buckets[f"DISCOVERED_{len(connect_buckets)}"] = name
            if is_connect:
                await _emit("item_found", phase_id="data_storage", category="s3",
                            name=name, found_delta=("s3_buckets", 1),
                            log_line=f"  S3 Bucket: {name}")
                await asyncio.sleep(0.05)
    except Exception as e:
        LOGGER.warning("list_buckets failed: %s", e)

    result["s3"] = {
        "connect_buckets": connect_buckets,
        "recording_bucket": _bucket_name("CALL_RECORDINGS"),
        "recording_prefix": _bucket_prefix("CALL_RECORDINGS"),
        "transcript_bucket": (
            _bucket_name("CHAT_TRANSCRIPTS")
            or _bucket_name("REAL_TIME_CONTACT_ANALYSIS_SEGMENTS")
        ),
        "transcript_prefix": _bucket_prefix("CHAT_TRANSCRIPTS"),
        "ctr_bucket": _bucket_name("CONTACT_TRACE_RECORDS"),
        "analysis_bucket": _bucket_name("REAL_TIME_CONTACT_ANALYSIS_SEGMENTS"),
        "analysis_prefix": _bucket_prefix("REAL_TIME_CONTACT_ANALYSIS_SEGMENTS"),
        "all_connect_buckets": [b for b in all_buckets if b["is_connect"]],
    }

    # Kinesis streams
    await _emit("progress_update", message="Scanning Kinesis streams…")
    kinesis = _client("kinesis", region)
    all_streams: List[Dict] = []
    try:
        pager = kinesis.get_paginator("list_streams")
        for page in pager.paginate():
            for name in page.get("StreamNames", []):
                is_connect = any(kw in name.lower()
                                 for kw in ("connect", "ctr", "agent", "contact"))
                all_streams.append({"name": name, "is_connect": is_connect})
                if is_connect:
                    await _emit("item_found", phase_id="data_storage",
                                category="kinesis", name=name,
                                found_delta=("kinesis_streams", 1),
                                log_line=f"  Kinesis Stream: {name}")
                    await asyncio.sleep(0.05)
    except Exception as e:
        LOGGER.warning("list_streams failed: %s", e)

    # Kinesis Firehose
    firehose = _client("firehose", region)
    firehose_streams: List[Dict] = []
    try:
        resp = firehose.list_delivery_streams()
        for name in resp.get("DeliveryStreamNames", []):
            is_connect = any(kw in name.lower()
                             for kw in ("connect", "ctr", "contact", "agent"))
            firehose_streams.append({"name": name, "is_connect": is_connect})
            if is_connect:
                await _emit("item_found", phase_id="data_storage",
                            category="firehose", name=name,
                            found_delta=("firehose_streams", 1),
                            log_line=f"  Firehose: {name}")
    except Exception:
        LOGGER.debug('Suppressed exception', exc_info=True)

    # Merge Kinesis from storage configs
    for stype, arn in kinesis_from_cfg.items():
        stream_name = arn.split("/")[-1] if arn else ""
        if stream_name and not any(s["name"] == stream_name for s in all_streams):
            all_streams.append({"name": stream_name, "arn": arn,
                                 "type": stype, "is_connect": True})
            await _emit("item_found", phase_id="data_storage",
                        category="kinesis", name=stream_name,
                        found_delta=("kinesis_streams", 1),
                        log_line=f"  Kinesis (config): {stream_name}")

    result["kinesis"] = {
        "ctr_stream": kinesis_from_cfg.get("CONTACT_TRACE_RECORDS", ""),
        "agent_events_stream": kinesis_from_cfg.get("AGENT_EVENTS", ""),
        "all_streams": all_streams,
        "firehose_streams": firehose_streams,
    }

    await _emit("phase_complete", phase_id="data_storage",
                phase_label="Data Storage", phase_index=5,
                progress=0.70, log_line="✅ Data Storage scan complete")


# ── Phase 6: Analytics (Athena + Glue + CloudWatch) ──────────────────────────

async def _phase_analytics(region: str, result: Dict) -> None:
    await _emit("phase_start", phase_id="analytics",
                phase_label="Analytics", phase_index=6,
                message="Scanning Athena workgroups…")

    # Athena
    athena = _client("athena", region)
    workgroups: List[Dict] = []
    databases: List[Dict] = []
    try:
        pager = athena.get_paginator("list_work_groups")
        for page in pager.paginate():
            for wg in page.get("WorkGroups", []):
                name = wg.get("Name", "")
                workgroups.append({"name": name, "state": wg.get("State", "")})
                await _emit("item_found", phase_id="analytics", category="athena_wg",
                            name=name, found_delta=("athena_workgroups", 1),
                            log_line=f"  Athena WG: {name}")
                # List databases for this WG
                try:
                    db_resp = athena.list_databases(CatalogName="AwsDataCatalog",
                                                    WorkGroup=name)
                    for db in db_resp.get("DatabaseList", []):
                        db_name = db.get("Name", "")
                        is_connect = any(kw in db_name.lower()
                                         for kw in ("connect", "contact", "ctr", "agent"))
                        databases.append({"name": db_name, "workgroup": name,
                                          "is_connect": is_connect})
                        if is_connect:
                            await _emit("item_found", phase_id="analytics",
                                        category="athena_db", name=db_name,
                                        found_delta=("athena_databases", 1),
                                        log_line=f"    DB: {db_name}")
                except Exception:
                    LOGGER.debug('Suppressed exception', exc_info=True)
                await asyncio.sleep(0.05)
    except Exception as e:
        LOGGER.warning("Athena scan failed: %s", e)

    result["athena"] = {"workgroups": workgroups, "databases": databases}

    # Glue
    await _emit("progress_update", message="Scanning Glue catalog…")
    glue = _client("glue", region)
    glue_databases: List[Dict] = []
    try:
        pager = glue.get_paginator("get_databases")
        for page in pager.paginate():
            for db in page.get("DatabaseList", []):
                name = db.get("Name", "")
                is_connect = any(kw in name.lower()
                                 for kw in ("connect", "contact", "ctr", "agent"))
                glue_databases.append({"name": name, "is_connect": is_connect,
                                        "description": db.get("Description", "")})
                if is_connect:
                    await _emit("item_found", phase_id="analytics", category="glue",
                                name=name, found_delta=("glue_databases", 1),
                                log_line=f"  Glue DB: {name}")
    except Exception as e:
        LOGGER.warning("Glue scan failed: %s", e)

    result["glue"] = {"databases": glue_databases}

    # CloudWatch log groups for Connect
    await _emit("progress_update", message="Scanning CloudWatch log groups…")
    cw = _client("logs", region)
    log_groups: List[Dict] = []
    try:
        pager = cw.get_paginator("describe_log_groups")
        for page in pager.paginate(logGroupNamePrefix="/aws/connect"):
            for lg in page.get("logGroups", []):
                name = lg.get("logGroupName", "")
                log_groups.append({"name": name, "size_bytes": lg.get("storedBytes", 0)})
                await _emit("item_found", phase_id="analytics", category="cloudwatch_lg",
                            name=name, found_delta=("log_groups", 1),
                            log_line=f"  CW Log Group: {name}")
    except Exception as e:
        LOGGER.warning("CW log groups failed: %s", e)

    # Also check Lambda log groups
    try:
        pager = cw.get_paginator("describe_log_groups")
        for page in pager.paginate(logGroupNamePrefix="/aws/lambda"):
            for lg in page.get("logGroups", []):
                name = lg.get("logGroupName", "")
                if any(kw in name.lower() for kw in ("connect", "lex", "contact")):
                    log_groups.append({"name": name, "size_bytes": lg.get("storedBytes", 0)})
    except Exception:
        LOGGER.debug('Suppressed exception', exc_info=True)

    result["cloudwatch"] = {"log_groups": log_groups}

    await _emit("phase_complete", phase_id="analytics",
                phase_label="Analytics", phase_index=6,
                progress=0.82, log_line="✅ Analytics scan complete")


# ── Phase 7: AI / ML (Bedrock + Knowledge Bases) ─────────────────────────────

async def _phase_ai_ml(region: str, result: Dict) -> None:
    await _emit("phase_start", phase_id="ai_ml",
                phase_label="AI & Bedrock", phase_index=7,
                message="Scanning Bedrock models…")

    bedrock = _client("bedrock", region)
    models: List[Dict] = []
    try:
        resp = bedrock.list_foundation_models()
        for m in resp.get("modelSummaries", []):
            provider = m.get("providerName", "")
            model_id = m.get("modelId", "")
            name = m.get("modelName", model_id)
            # Filter to on-demand models (not fine-tunable only)
            if "ON_DEMAND" in m.get("inferenceTypesSupported", []):
                models.append({"id": model_id, "name": name, "provider": provider})
        await _emit("item_found", phase_id="ai_ml", category="bedrock_models",
                    name=f"{len(models)} on-demand models",
                    found_delta=("bedrock_models", len(models)),
                    log_line=f"  Bedrock: {len(models)} on-demand models available")
    except Exception as e:
        LOGGER.warning("list_foundation_models failed: %s", e)

    # Bedrock Knowledge Bases
    kb_list: List[Dict] = []
    try:
        br_agent = _client("bedrock-agent", region)
        resp = br_agent.list_knowledge_bases()
        for kb in resp.get("knowledgeBaseSummaries", []):
            name = kb.get("name", "")
            kb_list.append({"id": kb.get("knowledgeBaseId", ""), "name": name,
                             "status": kb.get("status", "")})
            await _emit("item_found", phase_id="ai_ml", category="bedrock_kb",
                        name=name, found_delta=("knowledge_bases", 1),
                        log_line=f"  Bedrock KB: {name}")
    except Exception:
        LOGGER.debug('Suppressed exception', exc_info=True)

    # Amazon Q in Connect Knowledge Bases
    qconn_kbs: List[Dict] = []
    try:
        wisdom = _client("wisdom", region)
        resp = wisdom.list_knowledge_bases()
        for kb in resp.get("knowledgeBaseSummaries", []):
            name = kb.get("name", "")
            qconn_kbs.append({"id": kb.get("knowledgeBaseId", ""), "name": name})
            await _emit("item_found", phase_id="ai_ml", category="qconn_kb",
                        name=name, found_delta=("qconn_knowledge_bases", 1),
                        log_line=f"  Q in Connect KB: {name}")
    except Exception:
        LOGGER.debug('Suppressed exception', exc_info=True)

    result["bedrock"] = {"available_models": models, "knowledge_bases": kb_list}
    result["q_in_connect"] = {
        **result.get("q_in_connect", {}),
        "knowledge_bases": qconn_kbs,
    }

    await _emit("phase_complete", phase_id="ai_ml",
                phase_label="AI & Bedrock", phase_index=7,
                progress=0.90, log_line="✅ AI & Bedrock scan complete")


# ── Phase 8: Security & Account ───────────────────────────────────────────────

async def _phase_security(region: str, instance_id: str, result: Dict) -> None:
    await _emit("phase_start", phase_id="security",
                phase_label="Security & Account", phase_index=8,
                message="Fetching account identity…")

    sts = _client("sts", region)
    identity: Dict = {}
    try:
        identity = sts.get_caller_identity()
        await _emit("item_found", phase_id="security", category="account",
                    name=identity.get("Account", ""),
                    found_delta=("account", 1),
                    log_line=f"  Account: {identity.get('Account', '')} (ARN: {identity.get('Arn', '')})")
    except Exception as e:
        LOGGER.warning("get_caller_identity failed: %s", e)

    result["account"] = {
        "id":  identity.get("Account", os.getenv("AWS_ACCOUNT_ID", "")),
        "arn": identity.get("Arn", ""),
        "user_id": identity.get("UserId", ""),
    }

    await _emit("phase_complete", phase_id="security",
                phase_label="Security & Account", phase_index=8,
                progress=0.96, log_line="✅ Security scan complete")


# ── Main scan orchestrator ────────────────────────────────────────────────────

async def run_scan(instance_id: str, region: str) -> None:
    """Full resource discovery. Called by the leader instance only."""
    global _scan_task

    scan_id = str(uuid.uuid4())
    started = time.time()
    _state["running"] = True
    _state["is_leader"] = True
    _state["started_at"] = datetime.now(timezone.utc).isoformat()
    _state["found"] = {}
    _state["total_found"] = 0
    _state["log"] = []
    _state["error"] = None

    LOGGER.info("Startup scan %s starting (instance=%s region=%s)", scan_id, instance_id, region)

    await _emit("scan_start", scan_id=scan_id,
                instance_id=instance_id, region=region,
                message="Beginning AWS resource discovery…",
                total_phases=8, phase_index=0, progress=0.0)

    # Skeleton result structure
    result: Dict[str, Any] = {
        "scan_id":     scan_id,
        "scanned_at":  _state["started_at"],
        "instance_id": instance_id,
        "region":      region,
        "connect":     {},
        "bots":        {},
        "lambda":      {"all_functions": [], "connect_associations": []},
        "s3":          {},
        "kinesis":     {},
        "athena":      {},
        "glue":        {},
        "cloudwatch":  {},
        "bedrock":     {},
        "q_in_connect": {"assistants": [], "knowledge_bases": []},
        "account":     {},
    }

    connect = _client("connect", region)

    try:
        await _phase_connect_core(connect, instance_id, region, result)
        await _phase_bots(connect, region, instance_id, result)
        await _phase_flow_deep_scan(connect, instance_id, result)
        await _phase_lambda(region, result)
        await _phase_data_storage(region, result)
        await _phase_analytics(region, result)
        await _phase_ai_ml(region, result)
        await _phase_security(region, instance_id, result)

    except Exception as exc:
        LOGGER.exception("Scan phase failed: %s", exc)
        _state["error"] = str(exc)
        await _emit("scan_error", message=str(exc),
                    phase_id=_state.get("phase_id", "unknown"))

    # Finalise
    duration = round(time.time() - started, 1)
    result["duration_sec"] = duration
    result["totals"] = dict(_state["found"])

    # Clean up private staging keys
    result.pop("_s3_from_config", None)
    result.pop("_kinesis_from_config", None)

    # Persist to disk
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RESOURCES_FILE.write_text(json.dumps(result, indent=2, default=str))
    LOGGER.info("Scan complete — %d resources in %.1fs → %s",
                _state["total_found"], duration, RESOURCES_FILE)

    _state["running"] = False
    _state["complete"] = True
    _state["completed_at"] = datetime.now(timezone.utc).isoformat()
    _state["progress"] = 1.0

    await _emit("scan_complete", progress=1.0,
                duration_sec=duration,
                total_found=_state["total_found"],
                resources_file=str(RESOURCES_FILE),
                log_line=f"🎉 Scan complete — {_state['total_found']} resources in {duration}s")

    _release_leader()


async def start_scan_if_needed(instance_id: str, region: str) -> bool:
    """
    Called at server startup.  Returns True if this instance becomes the leader
    and starts scanning, False if scan not needed or another instance is leading.
    """
    global _scan_task

    if not needs_scan():
        # Already have data — mark complete so SSE clients get immediate confirmation
        _state["complete"] = True
        _state["progress"] = 1.0
        _state["message"] = "Resources already discovered"
        _state["total_found"] = sum(
            len(v) if isinstance(v, list) else 1
            for v in (get_resources() or {}).get("totals", {}).values()
        )
        LOGGER.info("Startup scan skipped — %s exists", RESOURCES_FILE)
        return False

    if not instance_id:
        LOGGER.warning("No CONNECT_INSTANCE_ID — skipping startup scan")
        _state["complete"] = True
        _state["error"] = "CONNECT_INSTANCE_ID not set"
        return False

    if not _try_become_leader():
        LOGGER.info("Another instance is leading the scan — watching")
        _state["is_leader"] = False
        return False

    _state["is_leader"] = True
    _scan_task = asyncio.create_task(run_scan(instance_id, region))
    return True
