"""
Shared resource cache backed by the startup scan (discovered_resources.json).

Tools call helpers like get_queue_id_map(), get_routing_profiles(), etc.
instead of making redundant list_queues / list_routing_profiles API calls.

If scan data is unavailable (pre-scan or Lambda deployment without volume mount),
every helper falls back transparently to a live AWS API call so nothing breaks.

Cache TTL: 5 minutes in-process — tools pick up a rescan automatically.
"""

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import BotoCoreError, ClientError

LOGGER = logging.getLogger(__name__)

# Path must match what startup_scan.py writes — overrideable via env var
_DATA_DIR = os.getenv("DATA_DIR", "/app/data")
_RESOURCES_FILE = os.path.join(_DATA_DIR, "discovered_resources.json")

_CACHE_TTL_SECONDS = 300  # 5 minutes

# ── In-process cache ───────────────────────────────────────────────────────────
_cache_lock = threading.Lock()
_cache_data: Optional[Dict[str, Any]] = None
_cache_loaded_at: float = 0.0


def _load() -> Optional[Dict[str, Any]]:
    """Return scan data from file with TTL caching. Returns None if unavailable."""
    global _cache_data, _cache_loaded_at  # pylint: disable=global-statement
    now = time.monotonic()
    with _cache_lock:
        if _cache_data is not None and (now - _cache_loaded_at) < _CACHE_TTL_SECONDS:
            return _cache_data
        try:
            with open(_RESOURCES_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            _cache_data = data
            _cache_loaded_at = now
            LOGGER.debug("scan_resources: loaded %s", _RESOURCES_FILE)
            return data
        except FileNotFoundError:
            LOGGER.debug("scan_resources: %s not found — will use live API", _RESOURCES_FILE)
            _cache_data = None
            return None
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning("scan_resources: failed to read %s: %s", _RESOURCES_FILE, exc)
            _cache_data = None
            return None


def invalidate_cache() -> None:
    """Force next access to reload from disk (call after a rescan)."""
    global _cache_data, _cache_loaded_at  # pylint: disable=global-statement
    with _cache_lock:
        _cache_data = None
        _cache_loaded_at = 0.0


# ── Helpers ────────────────────────────────────────────────────────────────────

def get_instance_region() -> str:
    """Return AWS region from scan data or env var."""
    data = _load()
    if data and data.get("region"):
        return data["region"]
    return os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))


def get_account_id() -> Optional[str]:
    """Return AWS account ID from scan data, or fetch live via STS."""
    data = _load()
    if data:
        account_id = (data.get("account") or {}).get("id")
        if account_id:
            return account_id
    try:
        return boto3.client("sts").get_caller_identity()["Account"]
    except Exception:  # pylint: disable=broad-except
        return None


def get_instance_arn(instance_id: str) -> str:
    """Build the Connect instance ARN using scan data where possible."""
    region = get_instance_region()
    account_id = get_account_id() or "unknown"
    return f"arn:aws:connect:{region}:{account_id}:instance/{instance_id}"


# ── Queues ─────────────────────────────────────────────────────────────────────

def get_queues(instance_id: str, connect_client=None) -> List[Dict[str, Any]]:
    """
    Return list of queues [{id, name, arn, type}].
    Uses scan data; falls back to live list_queues API.
    """
    data = _load()
    if data:
        scanned_instance = (data.get("connect") or {}).get("instance", {}).get("id", "")
        if not scanned_instance or scanned_instance == instance_id:
            queues = (data.get("connect") or {}).get("queues", [])
            if queues:
                LOGGER.debug("scan_resources: using %d cached queues", len(queues))
                return queues

    # Fallback: live API
    LOGGER.debug("scan_resources: get_queues falling back to live API")
    client = connect_client or boto3.client("connect")
    queues: List[Dict[str, Any]] = []
    try:
        paginator = client.get_paginator("list_queues")
        for page in paginator.paginate(InstanceId=instance_id, QueueTypes=["STANDARD", "AGENT"]):
            for q in page.get("QueueSummaryList", []):
                queues.append({
                    "id": q.get("Id", ""),
                    "name": q.get("Name", q.get("Id", "")),
                    "arn": q.get("Arn", ""),
                    "type": q.get("QueueType", "STANDARD"),
                })
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.warning("scan_resources: list_queues failed: %s", exc)
    return queues


def get_queue_id_map(instance_id: str, connect_client=None) -> Dict[str, str]:
    """Return {queue_id: queue_name} mapping."""
    return {q["id"]: q["name"] for q in get_queues(instance_id, connect_client) if q.get("id")}


def get_queue_ids(instance_id: str, connect_client=None) -> List[str]:
    """Return list of all queue IDs."""
    return [q["id"] for q in get_queues(instance_id, connect_client) if q.get("id")]


def get_queue_name_to_id(instance_id: str, connect_client=None) -> Dict[str, str]:
    """Return {queue_name: queue_id} mapping (case-insensitive lookup)."""
    return {q["name"].lower(): q["id"] for q in get_queues(instance_id, connect_client) if q.get("name")}


# ── Agents ─────────────────────────────────────────────────────────────────────

def get_agents(instance_id: str, connect_client=None) -> List[Dict[str, Any]]:
    """
    Return list of agents [{id, username, first_name, last_name, arn}].
    Uses scan data; falls back to live list_users API.
    """
    data = _load()
    if data:
        scanned_instance = (data.get("connect") or {}).get("instance", {}).get("id", "")
        if not scanned_instance or scanned_instance == instance_id:
            agents = (data.get("connect") or {}).get("agents", [])
            if agents:
                return agents

    LOGGER.debug("scan_resources: get_agents falling back to live API")
    client = connect_client or boto3.client("connect")
    agents: List[Dict[str, Any]] = []
    try:
        paginator = client.get_paginator("list_users")
        for page in paginator.paginate(InstanceId=instance_id):
            for u in page.get("UserSummaryList", []):
                agents.append({
                    "id": u.get("Id", ""),
                    "username": u.get("Username", ""),
                    "arn": u.get("Arn", ""),
                })
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.warning("scan_resources: list_users failed: %s", exc)
    return agents


def get_agent_id_map(instance_id: str, connect_client=None) -> Dict[str, str]:
    """Return {agent_id: username} mapping."""
    return {a["id"]: a.get("username", a["id"]) for a in get_agents(instance_id, connect_client) if a.get("id")}


# ── Routing Profiles ───────────────────────────────────────────────────────────

def get_routing_profiles(instance_id: str, connect_client=None) -> List[Dict[str, Any]]:
    """
    Return list of routing profiles [{id, name, arn}].
    Uses scan data; falls back to live list_routing_profiles API.
    """
    data = _load()
    if data:
        scanned_instance = (data.get("connect") or {}).get("instance", {}).get("id", "")
        if not scanned_instance or scanned_instance == instance_id:
            profiles = (data.get("connect") or {}).get("routing_profiles", [])
            if profiles:
                return profiles

    LOGGER.debug("scan_resources: get_routing_profiles falling back to live API")
    client = connect_client or boto3.client("connect")
    profiles: List[Dict[str, Any]] = []
    try:
        paginator = client.get_paginator("list_routing_profiles")
        for page in paginator.paginate(InstanceId=instance_id):
            for rp in page.get("RoutingProfileSummaryList", []):
                profiles.append({
                    "id": rp.get("Id", ""),
                    "name": rp.get("Name", rp.get("Id", "")),
                    "arn": rp.get("Arn", ""),
                })
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.warning("scan_resources: list_routing_profiles failed: %s", exc)
    return profiles


def get_routing_profile_id_map(instance_id: str, connect_client=None) -> Dict[str, str]:
    """Return {routing_profile_id: name} mapping."""
    return {
        rp["id"]: rp["name"]
        for rp in get_routing_profiles(instance_id, connect_client)
        if rp.get("id")
    }


# ── S3 Buckets ────────────────────────────────────────────────────────────────

def _get_s3_data() -> Dict[str, Any]:
    data = _load()
    return (data or {}).get("s3", {})


def get_recording_bucket() -> Optional[str]:
    """Return the S3 bucket name used for call recordings, or None."""
    bucket = _get_s3_data().get("recording_bucket", "")
    return bucket if bucket else None


def get_transcript_bucket() -> Optional[str]:
    """Return the S3 bucket name used for Contact Lens / chat transcripts, or None."""
    s3 = _get_s3_data()
    for key in ("transcript_bucket", "analysis_bucket"):
        bucket = s3.get(key, "")
        if bucket:
            return bucket
    return None


def get_ctr_bucket() -> Optional[str]:
    """Return the S3 bucket name used for CTRs, or None."""
    bucket = _get_s3_data().get("ctr_bucket", "")
    return bucket if bucket else None


def get_all_connect_s3_buckets() -> List[str]:
    """Return names of all S3 buckets associated with this Connect instance."""
    buckets = _get_s3_data().get("all_connect_buckets", [])
    return [b["name"] for b in buckets if isinstance(b, dict) and b.get("name")]


def get_contact_lens_bucket_and_prefix(
    instance_id: str,
    connect_client=None,
) -> Tuple[Optional[str], str]:
    """
    Return (bucket, base_prefix) for Connect transcript/analysis S3 output.
    Tries scan data first (bucket + prefix both), then live list_instance_storage_configs.
    """
    _STRIP_SUFFIXES = ["/CallRecordings", "/ChatTranscripts", "/Reports", "/ContactTrace",
                       "/Analysis", "/ContactTraceRecords", "/AgentEvents", "/MediaStreams"]

    def _strip_suffix(prefix: str) -> str:
        p = (prefix or "").rstrip("/")
        for suffix in _STRIP_SUFFIXES:
            if p.endswith(suffix):
                return p[: -len(suffix)]
        return p

    # Try transcript bucket from scan (has correct base prefix if populated)
    s3 = _get_s3_data()
    bkt = s3.get("transcript_bucket", "")
    prefix = s3.get("transcript_prefix", "")
    if bkt:
        return bkt, prefix

    bkt = s3.get("recording_bucket", "")
    prefix = s3.get("recording_prefix", "")
    if bkt:
        return bkt, prefix

    # Live API — most reliable when scan data is absent
    # Priority: CHAT_TRANSCRIPTS > CALL_RECORDINGS > REAL_TIME_CONTACT_ANALYSIS_SEGMENTS
    client = connect_client or boto3.client("connect")
    for resource_type in [
        "CHAT_TRANSCRIPTS",
        "CALL_RECORDINGS",
        "REAL_TIME_CONTACT_ANALYSIS_SEGMENTS",
    ]:
        try:
            resp = client.list_instance_storage_configs(
                InstanceId=instance_id,
                ResourceType=resource_type,
            )
            for cfg in resp.get("StorageConfigs", []):
                if cfg.get("StorageType") == "S3":
                    s3_cfg = cfg.get("S3Config", {})
                    bkt = s3_cfg.get("BucketName")
                    prefix = _strip_suffix(s3_cfg.get("BucketPrefix") or "")
                    if bkt:
                        LOGGER.info(
                            "scan_resources: resolved bucket=%s prefix='%s' via %s",
                            bkt, prefix, resource_type,
                        )
                        return bkt, prefix
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.debug("list_instance_storage_configs(%s) failed: %s", resource_type, exc)

    return None, ""


# ── Kinesis ────────────────────────────────────────────────────────────────────

def get_ctr_kinesis_stream() -> Optional[str]:
    """Return Kinesis stream name/ARN for CTRs, or None."""
    data = _load()
    if data:
        stream = (data.get("kinesis") or {}).get("ctr_stream", "")
        return stream if stream else None
    return None


def get_agent_events_stream() -> Optional[str]:
    """Return Kinesis stream name/ARN for agent events, or None."""
    data = _load()
    if data:
        stream = (data.get("kinesis") or {}).get("agent_events_stream", "")
        return stream if stream else None
    return None


# ── Bots ───────────────────────────────────────────────────────────────────────

def get_lex_v2_bots() -> List[Dict[str, Any]]:
    """Return Lex V2 bots discovered during scan."""
    data = _load()
    if data:
        return (data.get("bots") or {}).get("lex_v2", [])
    return []


def get_q_assistants() -> List[Dict[str, Any]]:
    """Return Amazon Q / Contact Lens AI assistants discovered during scan."""
    data = _load()
    if data:
        return (data.get("bots") or {}).get("q_assistants", [])
    return []


# ── Contact Flow Components ────────────────────────────────────────────────────


def _get_cached_connect_data(instance_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    data = _load()
    if not data:
        return None
    connect = data.get("connect") or {}
    scanned_instance = connect.get("instance", {}).get("id", "")
    if instance_id and scanned_instance and scanned_instance != instance_id:
        return None
    return connect


def get_contact_flows(instance_id: str, connect_client=None) -> List[Dict[str, Any]]:
    """Return list of contact flows with basic metadata (id, name, arn, type)."""
    connect = _get_cached_connect_data(instance_id)
    if connect:
        flows = connect.get("contact_flows", [])
        if flows:
            return flows

    LOGGER.debug("scan_resources: get_contact_flows falling back to live API")
    client = connect_client or boto3.client("connect")
    flows: List[Dict[str, Any]] = []
    try:
        paginator = client.get_paginator("list_contact_flows")
        for page in paginator.paginate(InstanceId=instance_id):
            for flow in page.get("ContactFlowSummaryList", []):
                flows.append({
                    "id": flow.get("Id", ""),
                    "name": flow.get("Name", flow.get("Id", "")),
                    "arn": flow.get("Arn", ""),
                    "type": flow.get("ContactFlowType", ""),
                })
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.warning("scan_resources: list_contact_flows failed: %s", exc)
    return flows


def get_flow_components(flow_id: str) -> Optional[Dict[str, Any]]:
    """Return the parsed component data for a specific flow_id, or None."""
    return get_all_flow_components().get(flow_id)


def get_all_flow_components() -> Dict[str, Dict[str, Any]]:
    """Return the full {flow_id: components} mapping."""
    connect = _get_cached_connect_data()
    if connect:
        return connect.get("flow_components", {})
    return {}


def get_flows_using_lambda(lambda_arn: str) -> List[str]:
    """Return list of flow_ids that invoke the given Lambda ARN."""
    connect = _get_cached_connect_data()
    if connect:
        return list((connect.get("flows_by_lambda") or {}).get(lambda_arn, []))
    return []


def get_flows_using_lex_bot(bot_alias_arn: str) -> List[str]:
    """Return list of flow_ids that use the given Lex V2 bot alias ARN."""
    connect = _get_cached_connect_data()
    if connect:
        return list((connect.get("flows_by_lex_bot") or {}).get(bot_alias_arn, []))
    return []


def get_flows_using_q_assistant(assistant_id: str) -> List[str]:
    """Return list of flow_ids that have a CreateWisdomSession block for this assistant."""
    connect = _get_cached_connect_data()
    if connect:
        return list((connect.get("flows_by_q_assistant") or {}).get(assistant_id, []))
    return []


def get_q_assistants_for_instance() -> List[Dict[str, Any]]:
    """Return all Q Connect assistants discovered, with their AI agent details."""
    connect = _get_cached_connect_data() or {}
    components = connect.get("flow_components", {})
    assistants: List[Dict[str, Any]] = []
    for assistant in get_q_assistants():
        entry = dict(assistant)
        assistant_id = entry.get("id", "")
        flow_ids = list((connect.get("flows_by_q_assistant") or {}).get(assistant_id, []))
        ai_agent_version_arns: List[str] = []
        lex_q_connect_agent_arns: List[str] = []
        for flow_id in flow_ids:
            q_connect = (components.get(flow_id) or {}).get("q_connect") or {}
            for arn in q_connect.get("ai_agent_version_arns", []):
                if arn and arn not in ai_agent_version_arns:
                    ai_agent_version_arns.append(arn)
            for arn in q_connect.get("lex_q_connect_agent_arns", []):
                if arn and arn not in lex_q_connect_agent_arns:
                    lex_q_connect_agent_arns.append(arn)
        entry["flow_ids"] = flow_ids
        entry["flow_count"] = len(flow_ids)
        entry["ai_agent_version_arns"] = ai_agent_version_arns
        entry["lex_q_connect_agent_arns"] = lex_q_connect_agent_arns
        assistants.append(entry)
    return assistants


def get_flows_with_realtime_analytics() -> List[str]:
    """Return flow_ids that have Contact Lens real-time analytics enabled."""
    connect = _get_cached_connect_data()
    if connect:
        return list(connect.get("flows_with_realtime_analytics", []))
    return []


def get_flow_analytics_config(flow_id: str) -> Optional[Dict[str, Any]]:
    """Return the analytics config dict for a flow, or None."""
    components = get_flow_components(flow_id)
    if components and isinstance(components.get("analytics"), dict):
        return components["analytics"]
    return None


def get_primary_q_assistant_id(instance_id: str, connect_client=None) -> Optional[str]:
    """
    Return the primary Q Connect assistant ID for this Connect instance.
    Prefers the assistant used by the most contact flows; falls back to
    the first AGENT-type assistant from list_assistants.
    """
    connect = _get_cached_connect_data(instance_id)
    if connect:
        flow_map = connect.get("flows_by_q_assistant") or {}
        if flow_map:
            ranked = sorted(
                ((assistant_id, len(flow_ids)) for assistant_id, flow_ids in flow_map.items() if assistant_id),
                key=lambda item: (-item[1], item[0]),
            )
            if ranked:
                return ranked[0][0]

    client = connect_client if connect_client and hasattr(connect_client, "list_assistants") else boto3.client(
        "wisdom",
        region_name=get_instance_region(),
    )
    fallback_id: Optional[str] = None
    next_token: Optional[str] = None
    try:
        while True:
            kwargs = {"nextToken": next_token} if next_token else {}
            response = client.list_assistants(**kwargs)
            for assistant in response.get("assistantSummaries", []):
                assistant_id = assistant.get("assistantId")
                if assistant_id and not fallback_id:
                    fallback_id = assistant_id
                if assistant.get("type") == "AGENT" and assistant_id:
                    return assistant_id
            next_token = response.get("nextToken")
            if not next_token:
                break
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.warning("scan_resources: list_assistants failed: %s", exc)
    return fallback_id


def get_all_dtmf_menus() -> Dict[str, List[Dict]]:
    """Return {flow_id: [dtmf_menu, ...]} for all flows with DTMF menus."""
    menus: Dict[str, List[Dict]] = {}
    for flow_id, components in get_all_flow_components().items():
        dtmf_menus = components.get("dtmf_menus") or []
        if dtmf_menus:
            menus[flow_id] = dtmf_menus
    return menus


# ── Bedrock ────────────────────────────────────────────────────────────────────

def get_bedrock_models() -> List[Dict[str, Any]]:
    """Return Bedrock foundation models available in this region."""
    data = _load()
    if data:
        return (data.get("bedrock") or {}).get("available_models", [])
    return []


def get_knowledge_bases() -> List[Dict[str, Any]]:
    """Return Bedrock knowledge bases discovered during scan."""
    data = _load()
    if data:
        return (data.get("bedrock") or {}).get("knowledge_bases", [])
    return []
