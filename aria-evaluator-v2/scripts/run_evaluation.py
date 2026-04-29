#!/usr/bin/env python3
"""
scripts/run_evaluation.py
=========================
CLI entry point for aria-evaluator-v2.

Pipeline
--------
  Phase A — Conversation: run each YAML scenario via the selected channel
            adapter (chat WebSocket or voice WebRTC), save a local transcript
            JSON per scenario.
  Phase B — Evaluate:     run LLM judge on each transcript.
  Phase C — Report:       generate HTML + JSON report.

Usage
-----
  # All scenarios (chat — default)
  python scripts/run_evaluation.py

  # All scenarios over voice (WebRTC + Polly TTS + Transcribe STT)
  python scripts/run_evaluation.py --channel voice

  # One scenario
  python scripts/run_evaluation.py --scenario banking/account_query

  # One scenario over voice
  python scripts/run_evaluation.py --scenario banking/account_query --channel voice

  # Re-evaluate a saved transcript (skip Phase A)
  python scripts/run_evaluation.py --transcript transcripts/account_query_2026-04-28.json

  # Conversation only — save transcripts, skip evaluation and report
  python scripts/run_evaluation.py --conversation-only

  # Custom report output directory
  python scripts/run_evaluation.py --report-dir reports/sprint-42

Required environment variables (or .env file in project root):
  CONNECT_INSTANCE_ID
  CONNECT_REGION
  CONNECT_CONTACT_FLOW_ID  or  CONNECT_CONTACT_FLOW_NAME
  BEDROCK_REGION
  JUDGE_MODEL_ID
  EVAL_CUSTOMER_ID

Additional variables for --channel voice:
  CONNECT_VOICE_FLOW_ID          — Preferred: explicit WebRTC voice contact flow ID.
  CONNECT_VOICE_FLOW_NAME        — Optional: resolve the voice flow by name.
                                   If neither is set, evaluator reuses the chat flow
                                   and warns (chat-only flows usually lead to voice
                                   timeouts with no inbound audio).
  POLLY_VOICE_ID                 — Polly voice (default: Brian)
  POLLY_REGION                   — Polly region (default: CONNECT_REGION)
  TRANSCRIBE_REGION              — Transcribe region (default: CONNECT_REGION)
  VOICE_RESPONSE_TIMEOUT         — Seconds to wait for voice reply (default: 45)
  VOICE_SILENCE_TIMEOUT          — Seconds of silence = end of ARIA utterance (default: 3)
  VOICE_PREFER_RELAY             — Prefer TURN relay ICE candidates (default: 0)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

# ── Path bootstrap ────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from adapters.connect_ws import ConnectWebSocketAdapter
from adapters.connect_voice import ConnectVoiceAdapter, ConnectVoiceAdapterError
from conversation.driver import AgentDriver
from conversation.runner import ScenarioRunner
from judge.llm_judge import LLMJudge
from judge.sentiment import SentimentAnalyser
from report.report_generator import write_html_report, write_json_report
from transcript.models import Transcript, TurnRole

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "WARNING"),
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ── Environment helpers ───────────────────────────────────────────────────────

def _require_env(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        print(f"[ERROR] Required environment variable {name!r} is not set.")
        sys.exit(1)
    return val


def _resolve_flow_id(instance_id: str, region: str) -> str:
    """Return CONNECT_CONTACT_FLOW_ID, auto-discovering from name if needed."""
    flow_id = os.environ.get("CONNECT_CONTACT_FLOW_ID", "").strip()
    if flow_id:
        return flow_id

    flow_name = os.environ.get("CONNECT_CONTACT_FLOW_NAME", "").strip()
    if not flow_name:
        print("[ERROR] Set CONNECT_CONTACT_FLOW_ID or CONNECT_CONTACT_FLOW_NAME.")
        sys.exit(1)

    return _resolve_flow_name(instance_id, region, flow_name, kind="flow")


def _resolve_flow_name(instance_id: str, region: str, flow_name: str, kind: str) -> str:
    """Resolve a Connect contact flow ID by exact name."""
    import boto3
    client = boto3.client("connect", region_name=region)
    paginator = client.get_paginator("list_contact_flows")
    for page in paginator.paginate(InstanceId=instance_id):
        for flow in page.get("ContactFlowSummaryList", []):
            if flow.get("Name") == flow_name:
                found = flow["Id"]
                print(f"  ℹ  Resolved {kind} '{flow_name}' → {found}")
                return found

    print(f"[ERROR] Contact flow '{flow_name}' not found.")
    sys.exit(1)


def _resolve_voice_flow_id(instance_id: str, region: str, fallback_flow_id: str) -> str:
    """
    Resolve the WebRTC voice flow ID.

    Priority:
      1) CONNECT_VOICE_FLOW_ID
      2) CONNECT_VOICE_FLOW_NAME (resolved via ListContactFlows)
      3) fallback chat flow ID (with warning)
    """
    flow_id = os.environ.get("CONNECT_VOICE_FLOW_ID", "").strip()
    if flow_id:
        return flow_id

    flow_name = os.environ.get("CONNECT_VOICE_FLOW_NAME", "").strip()
    if flow_name:
        return _resolve_flow_name(instance_id, region, flow_name, kind="voice flow")

    print(
        "  ⚠  CONNECT_VOICE_FLOW_ID/CONNECT_VOICE_FLOW_NAME not set; "
        f"reusing chat flow ID {fallback_flow_id}. "
        "If that flow is chat-only, voice runs will connect but time out with no inbound audio."
    )
    return fallback_flow_id


# ── Scenario discovery ────────────────────────────────────────────────────────

def _discover_scenarios(scenario_filter: str | None) -> list[Path]:
    """Return all YAML scenario files (optionally filtered by path fragment)."""
    base = ROOT / "scenarios"
    if not base.exists():
        print(f"[ERROR] Scenarios directory not found: {base}")
        sys.exit(1)

    all_files = sorted(base.rglob("*.yaml")) + sorted(base.rglob("*.yml"))

    if scenario_filter:
        # Accept either a full path or a stem substring
        matched = [
            f for f in all_files
            if scenario_filter in str(f) or scenario_filter in f.stem
        ]
        if not matched:
            print(f"[ERROR] No scenario matched filter '{scenario_filter}'")
            sys.exit(1)
        return matched

    return all_files


def _load_scenarios(path: Path) -> list[dict]:
    """Load one YAML file, returning a list of scenario dicts."""
    with open(path) as fh:
        raw = fh.read()
    docs = list(yaml.safe_load_all(raw))
    return [d for d in docs if isinstance(d, dict)]


# ── Phase A: Conversation ─────────────────────────────────────────────────────

async def run_conversations(
    scenario_paths: list[Path],
    instance_id: str,
    flow_id: str,
    region: str,
    customer_id: str,
    customer_name: str,
    display_name: str,
    chat_duration: int,
    response_timeout: float,
    judge_model_id: str,
    bedrock_region: str,
    transcript_dir: Path,
    channel: str = "chat",
    voice_flow_id: str = "",
    polly_voice_id: str = "Brian",
    polly_region: str = "",
    transcribe_region: str = "",
    voice_response_timeout: float = 45.0,
    voice_silence_timeout: float = 3.0,
) -> list[Transcript]:
    """Run all scenarios sequentially and return a list of completed Transcripts."""
    driver = AgentDriver(model_id=judge_model_id, region=bedrock_region)
    transcripts: list[Transcript] = []

    print(f"\n📂 Running {sum(len(_load_scenarios(p)) for p in scenario_paths)} scenario(s)...\n")

    for path in scenario_paths:
        scenarios = _load_scenarios(path)
        if not scenarios:
            continue

        print(f"\n── {path.relative_to(ROOT)} ──")
        for scenario in scenarios:
            # Determine channel: CLI flag overrides scenario YAML field
            effective_channel = channel if channel != "chat" else scenario.get("channel", "chat")
            # Keep scenario metadata aligned with the actual adapter path so
            # transcript channel and judge logic (e.g., voice conciseness) are correct.
            scenario_for_run = dict(scenario)
            scenario_for_run["channel"] = effective_channel

            if effective_channel == "voice":
                adapter = ConnectVoiceAdapter(
                    instance_id=instance_id,
                    contact_flow_id=voice_flow_id,
                    region=region,
                    display_name=display_name,
                    polly_voice_id=polly_voice_id,
                    polly_region=polly_region or region,
                    transcribe_region=transcribe_region or region,
                    response_timeout=voice_response_timeout,
                    silence_timeout=voice_silence_timeout,
                )
            else:
                adapter = ConnectWebSocketAdapter(
                    instance_id=instance_id,
                    contact_flow_id=flow_id,
                    region=region,
                    display_name=display_name,
                    chat_duration_minutes=chat_duration,
                    response_timeout=response_timeout,
                )
            runner = ScenarioRunner(
                adapter=adapter,
                driver=driver,
                transcript_dir=transcript_dir,
                response_timeout=response_timeout if effective_channel == "chat" else voice_response_timeout,
                customer_name=customer_name,
            )
            try:
                transcript = await runner.run(scenario_for_run, customer_id=customer_id)
                transcripts.append(transcript)
            except Exception as exc:
                print(f"    ✗ Scenario failed: {exc}", flush=True)

    return transcripts


# ── Phase B: Evaluate ─────────────────────────────────────────────────────────

def evaluate_transcripts(
    transcripts: list[Transcript],
    judge_model_id: str,
    bedrock_region: str,
    judge_model_id_light: str | None = None,
) -> list[dict]:
    """
    Run LLM judge on all transcripts and return a list of scored scenario dicts.

    judge_model_id_light: optional cheaper model for the LLM judge (e.g. Haiku).
    Falls back to judge_model_id if not provided.
    """
    eval_model = judge_model_id_light or judge_model_id
    judge = LLMJudge(model_id=eval_model, region=bedrock_region)
    sentiment = SentimentAnalyser(model_id=eval_model, region=bedrock_region)
    if eval_model != judge_model_id:
        print(f"  ℹ  Using light judge model: {eval_model}")
    results: list[dict] = []

    for transcript in transcripts:
        print(f"  ⚖  Evaluating: {transcript.scenario_name} … ", end="", flush=True)
        t0 = time.monotonic()

        try:
            scores = judge.evaluate_all_dimensions(transcript)
            sentiment_result = sentiment.analyse(transcript)
        except Exception as exc:
            print(f"FAILED ({exc})")
            results.append({
                "scenario": transcript.scenario_name,
                "channel":  transcript.channel,
                "status":   "ERROR",
                "error":    str(exc),
                "conversation": _transcript_to_conv_dict(transcript),
            })
            continue

        elapsed = time.monotonic() - t0
        print(f"done ({elapsed:.1f}s)")

        results.append({
            "scenario":    transcript.scenario_name,
            "channel":     transcript.channel,
            "status":      "SCORED",
            "scores":      scores,
            "sentiment":   sentiment_result,
            "conversation": _transcript_to_conv_dict(transcript),
        })

    return results


def _transcript_to_conv_dict(transcript: Transcript) -> dict:
    """Convert Transcript to the conversation dict expected by the report template."""
    turns = []
    for i, t in enumerate(transcript.turns):
        if t.role in (TurnRole.CUSTOMER, TurnRole.AGENT):
            turns.append({
                "turn_index": i,
                "role":       t.role.value,
                "content":    t.content,
            })
    return {"turns": turns}


# ── Phase C: Report ───────────────────────────────────────────────────────────

def generate_report(
    scored_scenarios: list[dict],
    report_dir: Path,
    instance_id: str,
    region: str,
    judge_model_id: str,
    started_at: str,
) -> tuple[Path, Path]:
    """Generate HTML + JSON report. Returns (html_path, json_path)."""
    report_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")

    payload = {
        "generated_at":       datetime.now(timezone.utc).isoformat(),
        "connect_instance_id": instance_id,
        "connect_region":     region,
        "judge_model":        judge_model_id,
        "started_at":         started_at,
        "finished_at":        datetime.now(timezone.utc).isoformat(),
        "scenarios":          [s for s in scored_scenarios if s.get("status") != "INJECTION"],
        "injection_results":  [s for s in scored_scenarios if s.get("status") == "INJECTION"],
    }

    html_path = report_dir / f"aria_eval_{ts}.html"
    json_path = report_dir / f"aria_eval_{ts}.json"
    write_html_report(payload, str(html_path))
    write_json_report(payload, str(json_path))
    return html_path, json_path


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="aria-evaluator-v2 — LLM-as-judge for Connect AI Agents (chat & voice)"
    )
    p.add_argument(
        "--scenario", metavar="PATH_OR_STEM",
        help="Run a specific scenario file (path fragment or stem filter).",
    )
    p.add_argument(
        "--transcript", metavar="JSON_PATH",
        help="Re-evaluate a saved transcript JSON (skips Phase A).",
    )
    p.add_argument(
        "--conversation-only", action="store_true",
        help="Run conversations and save transcripts; skip evaluation and report.",
    )
    p.add_argument(
        "--report-dir", metavar="DIR", default=None,
        help="Output directory for HTML/JSON reports (default: EVAL_REPORT_OUTPUT_DIR or ./reports).",
    )
    p.add_argument(
        "--channel", metavar="CHANNEL", default="chat", choices=["chat", "voice"],
        help=(
            "Communication channel for Phase A conversations.  "
            "'chat' (default) uses WebSocket; 'voice' uses WebRTC + Polly TTS + Transcribe STT.  "
            "Individual scenarios can also set 'channel: voice' in their YAML to override."
        ),
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    started_at = datetime.now(timezone.utc).isoformat()

    print(f"\n🚀 ARIA Evaluator v2  starting at {started_at}\n")
    print("  How to run:")
    print("    All scenarios (chat):  python scripts/run_evaluation.py")
    print("    All scenarios (voice): python scripts/run_evaluation.py --channel voice")
    print("    One scenario:          python scripts/run_evaluation.py --scenario banking/account_query")
    print("    Voice scenario:        python scripts/run_evaluation.py --scenario banking/account_query --channel voice")
    print("    Re-evaluate saved:     python scripts/run_evaluation.py --transcript transcripts/foo.json")
    print("    Conversation only:     python scripts/run_evaluation.py --conversation-only\n")

    # ── Env — common ─────────────────────────────────────────────────────────
    instance_id    = _require_env("CONNECT_INSTANCE_ID")
    region         = os.environ.get("CONNECT_REGION", "eu-west-2")
    bedrock_region = os.environ.get("BEDROCK_REGION", region)
    judge_model_id = _require_env("JUDGE_MODEL_ID")
    judge_model_id_light = os.environ.get("JUDGE_MODEL_ID_LIGHT", judge_model_id)
    customer_id    = os.environ.get("EVAL_CUSTOMER_ID", "CUST-001")
    customer_name  = os.environ.get("EVAL_CUSTOMER_NAME", "")
    display_name   = os.environ.get("EVAL_DISPLAY_NAME", "ARIAEvaluatorBot")
    chat_duration  = int(os.environ.get("EVAL_CHAT_DURATION_MINUTES", "60"))
    resp_timeout   = float(os.environ.get("EVAL_RESPONSE_TIMEOUT_SECONDS", "90"))
    report_dir     = Path(args.report_dir or os.environ.get("EVAL_REPORT_OUTPUT_DIR", "./reports"))
    transcript_dir = ROOT / "transcripts"

    # ── Env — voice-specific ──────────────────────────────────────────────────
    polly_voice_id         = os.environ.get("POLLY_VOICE_ID", "Brian")
    polly_region           = os.environ.get("POLLY_REGION", region)
    transcribe_region      = os.environ.get("TRANSCRIBE_REGION", region)
    voice_resp_timeout     = float(os.environ.get("VOICE_RESPONSE_TIMEOUT", "45"))
    voice_silence_timeout  = float(os.environ.get("VOICE_SILENCE_TIMEOUT", "3"))

    flow_id = _resolve_flow_id(instance_id, region)

    voice_flow_id = _resolve_voice_flow_id(instance_id, region, fallback_flow_id=flow_id)

    # ── Phase A or transcript reload ─────────────────────────────────────────
    if args.transcript:
        print(f"  📄 Loading transcript: {args.transcript}")
        transcripts = [Transcript.load(Path(args.transcript))]
    else:
        scenario_paths = _discover_scenarios(args.scenario)
        transcripts = asyncio.run(run_conversations(
            scenario_paths=scenario_paths,
            instance_id=instance_id,
            flow_id=flow_id,
            region=region,
            customer_id=customer_id,
            customer_name=customer_name,
            display_name=display_name,
            chat_duration=chat_duration,
            response_timeout=resp_timeout,
            judge_model_id=judge_model_id,
            bedrock_region=bedrock_region,
            transcript_dir=transcript_dir,
            channel=args.channel,
            voice_flow_id=voice_flow_id,
            polly_voice_id=polly_voice_id,
            polly_region=polly_region,
            transcribe_region=transcribe_region,
            voice_response_timeout=voice_resp_timeout,
            voice_silence_timeout=voice_silence_timeout,
        ))

    if not transcripts:
        print("\n⚠  No transcripts to evaluate.")
        return

    if args.conversation_only:
        print(f"\n✅ Conversation phase complete. {len(transcripts)} transcript(s) saved to {transcript_dir}")
        return

    # ── Phase B: Evaluate ────────────────────────────────────────────────────
    print(f"\n⚖  Evaluating {len(transcripts)} transcript(s)…\n")
    scored = evaluate_transcripts(
        transcripts, judge_model_id, bedrock_region,
        judge_model_id_light=judge_model_id_light,
    )

    # ── Phase C: Report ──────────────────────────────────────────────────────
    print(f"\n📊 Generating report…")
    html_path, json_path = generate_report(
        scored_scenarios=scored,
        report_dir=report_dir,
        instance_id=instance_id,
        region=region,
        judge_model_id=judge_model_id,
        started_at=started_at,
    )
    print(f"\n✅ Report written:")
    print(f"   HTML → {html_path}")
    print(f"   JSON → {json_path}\n")


if __name__ == "__main__":
    main()
