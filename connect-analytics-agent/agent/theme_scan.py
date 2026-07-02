"""
Transcript theme discovery for Amazon Connect Analytics Agent.

Given a date range, exhaustively scans every contact whose transcript has
been fully generated and stored (Contact Lens post-call analysis — segments
present and the call is no longer active), extracts discussion themes via
Bedrock seeded with Contact Lens categories/issues where available, and
folds them into a running canonical theme list so the aggregation prompt
stays a fixed size regardless of how many contacts are scanned.

Mirrors startup_scan.py's pattern: one scan runs at a time, shared state
dict, SSE events broadcast to every connected client, a polling snapshot
via get_state().  Unlike startup_scan.py this is triggered per-request
(supervisor picks a date range) rather than once at boot.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import boto3

from contact_scan_utils import enumerate_contacts

LOGGER = logging.getLogger(__name__)

_BATCH_SIZE = 5                    # transcripts per extraction Bedrock call
_MAX_TRANSCRIPT_CHARS = 4000       # per-transcript text cap sent to Bedrock
_MAX_CONTACT_IDS_PER_THEME = 5
_MAX_QUOTES_PER_THEME = 3

# ── Shared scan state ─────────────────────────────────────────────────────────

_state: Dict[str, Any] = {
    "running": False,
    "complete": False,
    "start": None,
    "end": None,
    "message": "No scan started yet.",
    "contacts_found": 0,
    "contacts_scanned": 0,
    "transcripts_used": 0,
    "batches_processed": 0,
    "batches_total": None,
    "error": None,
    "started_at": None,
    "completed_at": None,
    "themes": None,   # {"top_10": [...], "all": [...], "total_themes": N} once available
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


def is_running() -> bool:
    return _state["running"]


async def _emit(event_type: str, **kwargs: Any) -> None:
    """Update shared state and push an SSE event to all connected clients."""
    for k, v in kwargs.items():
        if k in _state:
            _state[k] = v
    payload = json.dumps({
        "type": event_type,
        "ts": datetime.now(timezone.utc).isoformat(),
        **kwargs,
    }, default=str)
    msg = f"data: {payload}\n\n"
    dead = []
    for q in list(_sse_queues):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        unregister_queue(q)


# ── Transcript preparation ──────────────────────────────────────────────────────

def _prepare_transcript_for_prompt(contact_id: str, transcript: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Returns a compact {contact_id, text, categories, issues} dict, or None
    if the transcript has no usable content (still active / not yet stored)."""
    if transcript.get("still_active"):
        return None
    segments = transcript.get("segments") or []
    if not segments:
        return None

    lines: List[str] = []
    issues: set = set()
    for seg in segments:
        speaker = seg.get("speaker") or "UNKNOWN"
        text = (seg.get("text") or "").strip()
        if text:
            lines.append(f"{speaker}: {text}")
        for issue in seg.get("issues_detected") or []:
            label = issue.get("Text") if isinstance(issue, dict) else str(issue)
            if label:
                issues.add(label)

    conversation = "\n".join(lines)
    if not conversation:
        return None
    if len(conversation) > _MAX_TRANSCRIPT_CHARS:
        conversation = conversation[:_MAX_TRANSCRIPT_CHARS] + "\n[...truncated...]"

    categories_raw = transcript.get("categories") or {}
    categories = categories_raw.get("MatchedCategories") if isinstance(categories_raw, dict) else None

    return {
        "contact_id": contact_id,
        "text": conversation,
        "categories": categories or [],
        "issues": sorted(issues),
    }


# ── Bedrock ───────────────────────────────────────────────────────────────────

def _model_candidates(region: str) -> List[str]:
    """Same cross-region fallback cascade used by agent_core.py's _format_with_bedrock."""
    region_prefix = region.split("-")[0]
    configured = os.getenv("BEDROCK_MODEL_ID", "")
    candidates = [m for m in [
        "eu.anthropic.claude-sonnet-4-6",
        configured,
        f"{region_prefix}.anthropic.claude-3-5-sonnet-20241022-v2:0",
        f"{region_prefix}.anthropic.claude-3-5-haiku-20241022-v1:0",
        "anthropic.claude-3-7-sonnet-20250219-v1:0",
        "anthropic.claude-3-5-sonnet-20241022-v2:0",
        "anthropic.claude-3-5-haiku-20241022-v1:0",
        "amazon.nova-lite-v1:0",
    ] if m]
    seen: set = set()
    return [m for m in candidates if not (m in seen or seen.add(m))]


def _bedrock_json(bedrock, region: str, prompt: str, system: str) -> Optional[Any]:
    """Call Bedrock with the standard model-fallback cascade; parse the reply as JSON.
    Returns None if every candidate fails to respond with valid JSON."""
    for model_id in _model_candidates(region):
        try:
            resp = bedrock.converse(
                modelId=model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                system=[{"text": system}],
            )
            text = resp["output"]["message"]["content"][0]["text"].strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text.strip())
        except json.JSONDecodeError as exc:
            LOGGER.warning("Bedrock model '%s' returned non-JSON output during theme scan: %s", model_id, exc)
            continue
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning("Bedrock model '%s' failed during theme scan: %s", model_id, exc)
            continue
    return None


_EXTRACT_SYSTEM_PROMPT = (
    "You are analysing Amazon Connect contact centre transcripts to identify what customers "
    "and agents discussed. For each transcript, identify 1-3 short theme labels (2-5 words, "
    "Title Case, e.g. 'Billing Dispute', 'Password Reset', 'Delivery Delay') describing what the "
    "conversation was actually about. Contact Lens categories/issues are provided as hints where "
    "available, but identify the real topic from the conversation itself, not just the hints. "
    "Respond with ONLY a JSON array, no other text, no markdown fences, in this exact shape: "
    '[{"contact_id": "...", "themes": [{"label": "...", "quote": "..."}]}]. '
    "Each quote must be a short, verbatim excerpt (under 160 characters) from the transcript that "
    "illustrates the theme."
)

_MERGE_SYSTEM_PROMPT = (
    "You maintain a canonical, de-duplicated list of discussion themes found across many "
    "Amazon Connect contact centre transcripts. You will be given the current canonical list "
    "and a batch of new candidate theme mentions. Merge each candidate into an existing canonical "
    "theme if it is clearly the same topic, even if worded differently (e.g. 'Refund Request' and "
    "'Asking For Refund' are the same theme) — increment its count by 1 per merged mention, and add "
    "its contact_id/quote (keep at most 5 contact_ids and 3 example_quotes per theme, keeping the "
    "most illustrative ones). If a candidate does not clearly match any existing canonical theme, "
    "add it as a new canonical theme with count 1. Respond with ONLY the updated canonical JSON "
    "array, no other text, no markdown fences, sorted by count descending, in this exact shape: "
    '[{"theme": "...", "count": N, "contact_ids": ["..."], "example_quotes": ["..."]}]'
)


def _build_extraction_prompt(batch: List[Dict[str, Any]]) -> str:
    parts = []
    for item in batch:
        cats = item.get("categories") or []
        issues = item.get("issues") or []
        parts.append(
            f"TRANSCRIPT (contact_id: {item['contact_id']})\n"
            f"Contact Lens categories: {', '.join(cats) if cats else 'none'}\n"
            f"Contact Lens issues detected: {', '.join(issues) if issues else 'none'}\n"
            f"Conversation:\n{item['text']}\n"
        )
    return "\n---\n".join(parts)


def _extract_batch(bedrock, region: str, batch: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = _bedrock_json(bedrock, region, _build_extraction_prompt(batch), _EXTRACT_SYSTEM_PROMPT)
    if not isinstance(result, list):
        return []
    candidates = []
    for item in result:
        if not isinstance(item, dict):
            continue
        cid = item.get("contact_id")
        for theme in item.get("themes") or []:
            label = (theme.get("label") or "").strip()
            if label:
                candidates.append({
                    "contact_id": cid,
                    "label": label,
                    "quote": (theme.get("quote") or "").strip()[:200],
                })
    return candidates


def _build_merge_prompt(canonical: List[Dict[str, Any]], candidates: List[Dict[str, Any]]) -> str:
    return (
        f"Current canonical themes:\n{json.dumps(canonical)}\n\n"
        f"New candidate theme mentions to merge in:\n{json.dumps(candidates)}\n"
    )


def _naive_merge(canonical: List[Dict[str, Any]], candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Exact-label-match fallback used only when the Bedrock merge call itself fails,
    so a transient model outage never silently drops already-extracted theme data."""
    merged = {t["theme"]: dict(t) for t in canonical}
    for cand in candidates:
        key = cand["label"]
        existing = merged.get(key)
        if existing:
            existing["count"] = existing.get("count", 0) + 1
            if cand["contact_id"] and cand["contact_id"] not in existing["contact_ids"] and len(existing["contact_ids"]) < _MAX_CONTACT_IDS_PER_THEME:
                existing["contact_ids"].append(cand["contact_id"])
            if cand["quote"] and len(existing["example_quotes"]) < _MAX_QUOTES_PER_THEME:
                existing["example_quotes"].append(cand["quote"])
        else:
            merged[key] = {
                "theme": key,
                "count": 1,
                "contact_ids": [cand["contact_id"]] if cand["contact_id"] else [],
                "example_quotes": [cand["quote"]] if cand["quote"] else [],
            }
    return list(merged.values())


def _merge_batch(bedrock, region: str, canonical: List[Dict[str, Any]], candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not candidates:
        return canonical
    result = _bedrock_json(bedrock, region, _build_merge_prompt(canonical, candidates), _MERGE_SYSTEM_PROMPT)
    if not isinstance(result, list):
        LOGGER.warning("Theme merge call failed/invalid — falling back to exact-label-match merge")
        return _naive_merge(canonical, candidates)
    for t in result:
        t["contact_ids"] = (t.get("contact_ids") or [])[:_MAX_CONTACT_IDS_PER_THEME]
        t["example_quotes"] = (t.get("example_quotes") or [])[:_MAX_QUOTES_PER_THEME]
        t["count"] = t.get("count", 0)
    return result


def _ranked(canonical: List[Dict[str, Any]]) -> Dict[str, Any]:
    sorted_themes = sorted(canonical, key=lambda t: t.get("count", 0), reverse=True)
    return {"top_10": sorted_themes[:10], "all": sorted_themes, "total_themes": len(sorted_themes)}


# ── Main pipeline ────────────────────────────────────────────────────────────

async def run_scan(
    start_iso: str,
    end_iso: str,
    instance_id: str,
    region: str,
    invoke_tool: Callable[[str, List[Dict[str, Any]]], Dict[str, Any]],
) -> None:
    started = time.time()
    _state.update({
        "running": True, "complete": False, "error": None,
        "start": start_iso, "end": end_iso,
        "contacts_found": 0, "contacts_scanned": 0, "transcripts_used": 0,
        "batches_processed": 0, "batches_total": None, "themes": None,
        "started_at": datetime.now(timezone.utc).isoformat(), "completed_at": None,
        "message": "Enumerating contacts in range…",
    })
    await _emit("scan_start", start=start_iso, end=end_iso, message="Enumerating contacts in range…")

    canonical: List[Dict[str, Any]] = []

    try:
        connect = boto3.client("connect", region_name=region)

        async def _on_enumerate_progress(count: int) -> None:
            await _emit("enumerating", contacts_found=count, message=f"Found {count} contacts so far…")

        contacts = await enumerate_contacts(connect, instance_id, start_iso, end_iso, _on_enumerate_progress)
        total_batches = max(1, (len(contacts) + _BATCH_SIZE - 1) // _BATCH_SIZE)
        _state["contacts_found"] = len(contacts)
        _state["batches_total"] = total_batches
        await _emit("contacts_found", contacts_found=len(contacts), batches_total=total_batches,
                    message=f"{len(contacts)} contacts in range — fetching transcripts…")

        bedrock = boto3.client("bedrock-runtime", region_name=region)
        batch_prepared: List[Dict[str, Any]] = []

        for i, c in enumerate(contacts):
            _state["contacts_scanned"] = i + 1
            try:
                # invoke_tool does blocking network I/O (Connect/Contact Lens/S3
                # API calls, or a Lambda invoke in cloud mode) — off the event
                # loop so it can't stall other concurrent requests.
                transcript = await asyncio.to_thread(
                    invoke_tool, "get_transcript",
                    [{"name": "contact_id", "type": "string", "value": c["contact_id"]}],
                )
            except Exception as exc:  # pylint: disable=broad-except
                LOGGER.warning("get_transcript failed for %s: %s", c["contact_id"], exc)
                transcript = {}

            prepared = _prepare_transcript_for_prompt(c["contact_id"], transcript)
            if prepared:
                batch_prepared.append(prepared)
                _state["transcripts_used"] += 1

            is_last = i == len(contacts) - 1
            if batch_prepared and (len(batch_prepared) >= _BATCH_SIZE or is_last):
                # Bedrock converse() calls are the slowest step here (can take
                # many seconds each) — off the event loop for the same reason
                # as the transcript fetch above.
                candidates = await asyncio.to_thread(_extract_batch, bedrock, region, batch_prepared)
                if candidates:
                    canonical = await asyncio.to_thread(_merge_batch, bedrock, region, canonical, candidates)
                    _state["themes"] = _ranked(canonical)
                _state["batches_processed"] += 1
                await _emit(
                    "batch_processed",
                    contacts_scanned=_state["contacts_scanned"],
                    transcripts_used=_state["transcripts_used"],
                    batches_processed=_state["batches_processed"],
                    themes=_state["themes"],
                    message=f"Processed {_state['contacts_scanned']}/{len(contacts)} contacts, "
                            f"{_state['transcripts_used']} with stored transcripts…",
                )
                batch_prepared = []

            await asyncio.sleep(0)

    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("Theme scan failed: %s", exc)
        _state["running"] = False
        _state["error"] = str(exc)
        await _emit("scan_error", message=str(exc))
        return

    duration = round(time.time() - started, 1)
    _state["running"] = False
    _state["complete"] = True
    _state["completed_at"] = datetime.now(timezone.utc).isoformat()
    _state["themes"] = _ranked(canonical)
    await _emit(
        "scan_complete",
        themes=_state["themes"],
        duration_sec=duration,
        contacts_found=_state["contacts_found"],
        contacts_scanned=_state["contacts_scanned"],
        transcripts_used=_state["transcripts_used"],
        message=f"Scan complete — {len(canonical)} themes found across {_state['transcripts_used']} stored transcripts.",
    )


def start_scan(
    start_iso: str,
    end_iso: str,
    instance_id: str,
    region: str,
    invoke_tool: Callable[[str, List[Dict[str, Any]]], Dict[str, Any]],
) -> bool:
    """Kick off a scan if none is currently running. Returns True if started."""
    global _scan_task
    if _state["running"]:
        return False
    _scan_task = asyncio.create_task(run_scan(start_iso, end_iso, instance_id, region, invoke_tool))
    return True


# ── MOCK_MODE simulation ─────────────────────────────────────────────────────
# Drives the same state machine / SSE events as a real scan so the frontend
# progress UI, top-10 list, "show all", and per-theme quote drill-down are all
# testable locally without AWS or Bedrock.

_MOCK_THEMES = [
    {"theme": "Billing Dispute", "count": 14,
     "contact_ids": ["mock-1001", "mock-1014", "mock-1027", "mock-1033", "mock-1040"],
     "example_quotes": ["I was charged twice for the same order.", "This fee wasn't on my last statement.", "Can you explain this extra charge?"]},
    {"theme": "Password Reset", "count": 11,
     "contact_ids": ["mock-1002", "mock-1009", "mock-1018", "mock-1044"],
     "example_quotes": ["I'm locked out of my account again.", "The reset link never arrived."]},
    {"theme": "Delivery Delay", "count": 9,
     "contact_ids": ["mock-1003", "mock-1021", "mock-1035"],
     "example_quotes": ["My order was supposed to arrive three days ago.", "Tracking hasn't updated in a week."]},
    {"theme": "Refund Request", "count": 8,
     "contact_ids": ["mock-1004", "mock-1017", "mock-1029"],
     "example_quotes": ["I'd like a refund for the cancelled service.", "Can you process this refund today?"]},
    {"theme": "Product Defect", "count": 7,
     "contact_ids": ["mock-1005", "mock-1023"],
     "example_quotes": ["The item arrived damaged.", "This stopped working after two days."]},
    {"theme": "Subscription Cancellation", "count": 6,
     "contact_ids": ["mock-1006", "mock-1031"],
     "example_quotes": ["I want to cancel my subscription.", "How do I stop the auto-renewal?"]},
    {"theme": "App Login Issue", "count": 5,
     "contact_ids": ["mock-1007"],
     "example_quotes": ["The app keeps crashing when I try to sign in."]},
    {"theme": "Upgrade Enquiry", "count": 5,
     "contact_ids": ["mock-1008"],
     "example_quotes": ["What's involved in upgrading my plan?"]},
    {"theme": "Address Change", "count": 4,
     "contact_ids": ["mock-1010"],
     "example_quotes": ["I need to update my shipping address."]},
    {"theme": "Warranty Claim", "count": 4,
     "contact_ids": ["mock-1011"],
     "example_quotes": ["Is this still covered under warranty?"]},
    {"theme": "Payment Method Update", "count": 3,
     "contact_ids": ["mock-1012"],
     "example_quotes": ["I need to change my card on file."]},
    {"theme": "General Feedback", "count": 2,
     "contact_ids": ["mock-1013"],
     "example_quotes": ["Just wanted to say the last agent was great."]},
]


async def run_mock_scan(start_iso: str, end_iso: str) -> None:
    started = time.time()
    total_contacts = 63
    _state.update({
        "running": True, "complete": False, "error": None,
        "start": start_iso, "end": end_iso,
        "contacts_found": 0, "contacts_scanned": 0, "transcripts_used": 0,
        "batches_processed": 0, "batches_total": None, "themes": None,
        "started_at": datetime.now(timezone.utc).isoformat(), "completed_at": None,
        "message": "Enumerating contacts in range… (mock)",
    })
    await _emit("scan_start", start=start_iso, end=end_iso, message="Enumerating contacts in range… (mock)")
    await asyncio.sleep(0.4)

    total_batches = max(1, (total_contacts + _BATCH_SIZE - 1) // _BATCH_SIZE)
    _state["contacts_found"] = total_contacts
    _state["batches_total"] = total_batches
    await _emit("contacts_found", contacts_found=total_contacts, batches_total=total_batches,
                message=f"{total_contacts} contacts in range — fetching transcripts… (mock)")
    await asyncio.sleep(0.3)

    canonical: List[Dict[str, Any]] = []
    scanned = 0
    for batch_index in range(total_batches):
        batch_contacts = min(_BATCH_SIZE, total_contacts - scanned)
        scanned += batch_contacts
        used = min(scanned, sum(t["count"] for t in _MOCK_THEMES))
        # Reveal themes progressively so the "show all"/ranking UI is visibly live.
        reveal_count = max(1, round(len(_MOCK_THEMES) * (batch_index + 1) / total_batches))
        canonical = _MOCK_THEMES[:reveal_count]

        _state["contacts_scanned"] = scanned
        _state["transcripts_used"] = used
        _state["batches_processed"] = batch_index + 1
        _state["themes"] = _ranked(canonical)
        await _emit(
            "batch_processed",
            contacts_scanned=scanned,
            transcripts_used=used,
            batches_processed=batch_index + 1,
            themes=_state["themes"],
            message=f"Processed {scanned}/{total_contacts} contacts, {used} with stored transcripts… (mock)",
        )
        await asyncio.sleep(0.25)

    duration = round(time.time() - started, 1)
    _state["running"] = False
    _state["complete"] = True
    _state["completed_at"] = datetime.now(timezone.utc).isoformat()
    _state["themes"] = _ranked(_MOCK_THEMES)
    await _emit(
        "scan_complete",
        themes=_state["themes"],
        duration_sec=duration,
        contacts_found=total_contacts,
        contacts_scanned=total_contacts,
        transcripts_used=sum(t["count"] for t in _MOCK_THEMES),
        message=f"Scan complete — {len(_MOCK_THEMES)} themes found across "
                f"{sum(t['count'] for t in _MOCK_THEMES)} stored transcripts. (mock)",
    )


def start_mock_scan(start_iso: str, end_iso: str) -> bool:
    global _scan_task
    if _state["running"]:
        return False
    _scan_task = asyncio.create_task(run_mock_scan(start_iso, end_iso))
    return True
