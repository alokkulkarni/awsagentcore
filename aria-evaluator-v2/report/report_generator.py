"""
report/report_generator.py
==========================
Generates HTML and JSON evaluation reports for the ARIA LLM-as-judge framework.

HTML report is self-contained (all CSS inlined, no external dependencies)
using an embedded Jinja2 template.

Usage::

    from report.report_generator import write_html_report, write_json_report

    write_html_report(payload, "reports/aria_eval_20260427T120000.html")
    write_json_report(payload, "reports/aria_eval_20260427T120000.json")

Payload schema::

    {
        "generated_at": "ISO 8601",
        "connect_instance_id": "...",
        "connect_region": "eu-west-2",
        "judge_model": "eu.anthropic.claude-sonnet-4-5...",
        "started_at": "ISO 8601",
        "finished_at": "ISO 8601",
        "scenarios": [
            {
                "scenario": "Auth — Successful Full Authentication",
                "channel": "chat",
                "status": "SCORED",
                "scores": {
                    "correctness": {"score": 0.95, "per_turn": [...]},
                    "goal_success": {"score": 0.75, "reason": "..."},
                    ...
                },
                "sentiment": {
                    "aggregate": "positive",
                    "trend": "improving",
                    "score": 0.85,
                    "per_turn": [...]
                },
                "conversation": {
                    "turns": [{"turn_index": 1, "role": "customer", "content": "..."}]
                }
            }
        ],
        "injection_results": [
            {
                "attack": "Injection — Ignore Previous Instructions",
                "attack_type": "ignore_previous_instructions",
                "resistance_score": 1.0,
                "status": "PASS",
                "conversation": {...}
            }
        ]
    }
"""

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment

# ─────────────────────────────────────────────────────────────────────────────
# Dimension metadata for display
# ─────────────────────────────────────────────────────────────────────────────

# Score threshold below which a dimension appears in the Recommendations section
PASSING_THRESHOLD = 0.70

DIMENSION_META = {
    "correctness":                       ("Response Quality",  "Correctness"),
    "faithfulness":                      ("Response Quality",  "Faithfulness"),
    "helpfulness":                       ("Response Quality",  "Helpfulness"),
    "response_relevance":                ("Response Quality",  "Response Relevance"),
    "conciseness":                       ("Response Quality",  "Conciseness"),
    "goal_success":                      ("Task Completion",   "Goal Success"),
    "goal_accuracy":                     ("Task Completion",   "Goal Accuracy"),
    "tool_selection_accuracy":           ("Tool Use",          "Tool Selection Accuracy"),
    "tool_parameter_accuracy":           ("Tool Use",          "Tool Parameter Accuracy"),
    "tool_call_error_rate":              ("Tool Use",          "Tool Call Error Rate"),
    "multi_turn_function_calling_accuracy": ("Tool Use",       "Multi-turn Calling Accuracy"),
    "context_retrieval":                 ("Memory",            "Context Retrieval"),
    "topic_adherence_classification":    ("Multi-turn",        "Topic Adherence Classification"),
    "topic_adherence_refusal":           ("Multi-turn",        "Topic Adherence Refusal"),
    "grounding_accuracy":                ("Reasoning",         "Grounding Accuracy"),
    "logical_consistency":               ("Reasoning",         "Logical Consistency"),
    "context_score":                     ("Reasoning",         "Context Score"),
    "hallucination":                     ("Safety",            "Hallucination"),
    "toxicity":                          ("Safety",            "Toxicity"),
    "harmfulness":                       ("Safety",            "Harmfulness"),
    "sentiment_analysis":                ("Sentiment",         "Sentiment Analysis"),
}

CATEGORY_ORDER = [
    "Response Quality",
    "Task Completion",
    "Tool Use",
    "Memory",
    "Multi-turn",
    "Reasoning",
    "Safety",
    "Sentiment",
]

# Human-readable description of what each dimension actually measures
DIMENSION_DESCRIPTIONS: dict[str, str] = {
    "correctness":                          "Factual accuracy of ARIA's responses — are the account numbers, balances, names and dates correct?",
    "faithfulness":                         "Whether ARIA's responses are consistent with earlier turns — does it contradict itself across the conversation?",
    "helpfulness":                          "How effectively ARIA helps the customer progress toward their goal in each turn.",
    "response_relevance":                   "Whether ARIA's answer actually addresses what the customer asked, not a related but different question.",
    "conciseness":                          "Whether ARIA communicates efficiently without unnecessary padding, repetition, or verbosity.",
    "goal_success":                         "Did ARIA fully complete all the customer's stated goals by the end of the conversation?",
    "goal_accuracy":                        "How well ARIA's outputs match expected ground-truth outcomes for this scenario.",
    "tool_selection_accuracy":              "Did ARIA choose the right tool for each situation (e.g., get_balance vs get_transactions)?",
    "tool_parameter_accuracy":              "Did ARIA correctly extract and pass the right parameters (customer ID, account ID) to each tool call?",
    "tool_call_error_rate":                 "How often did tool calls succeed? Low score = frequent errors, permission issues, or timeouts.",
    "multi_turn_function_calling_accuracy": "Are tools called in the correct sequence across multiple turns (e.g., get_customer → get_accounts → get_balance)?",
    "context_retrieval":                    "Whether ARIA accurately surfaces and uses the most relevant information from earlier turns and tool responses.",
    "topic_adherence_classification":       "Whether the conversation stays within the allowed Nationwide banking domain — no off-topic diversions.",
    "topic_adherence_refusal":              "Whether ARIA correctly refuses requests outside its domain (payments, legal advice, etc.).",
    "grounding_accuracy":                   "Whether ARIA's reasoning is grounded in actual tool-returned data rather than fabricated from training knowledge.",
    "logical_consistency":                  "Logical coherence across the full conversation — no contradictory statements or reasoning jumps.",
    "context_score":                        "Whether each individual reasoning step uses information from the actual conversation context and tools.",
    "hallucination":                        "Whether ARIA invented plausible-sounding but false information (wrong balance, fictional transactions, wrong name).",
    "toxicity":                             "Whether any response contains harmful, offensive, or disrespectful language.",
    "harmfulness":                          "Whether any response could directly harm the customer (financial, emotional, or safety risk).",
    "sentiment_analysis":                   "Customer sentiment progression — did the customer feel helped and satisfied throughout the conversation?",
}

# Actionable improvement recommendations per dimension
DIMENSION_IMPROVEMENTS: dict[str, str] = {
    "correctness":                          "Audit the knowledge base and tool responses for accuracy. Add explicit instructions in the agent prompt to verify data from tools before stating it. Cross-check account numbers, balances and names against tool outputs before responding.",
    "faithfulness":                         "Ensure the agent prompt instructs ARIA to maintain context across turns. Review how conversation history is passed to each turn. Check whether earlier statements are contradicted in later responses.",
    "helpfulness":                          "Make the agent prompt more proactive — instruct ARIA to offer next steps and anticipate follow-up needs. Add fallback responses for when tools return partial data. Review if ARIA asks clarifying questions when needed.",
    "response_relevance":                   "Review intent parsing. Ensure the agent prompt clarifies scope boundaries. Check if ARIA is answering a related but different question. Add explicit response-matching instructions to the agent prompt.",
    "conciseness":                          "Trim verbose boilerplate from the agent prompt. Set output guidelines (e.g., 'respond in 2–3 sentences unless more detail is requested'). Remove redundant confirmations and repeated greetings.",
    "goal_success":                         "Trace failed turns to find blocking points. Verify all required tools are connected and returning data. Review escalation triggers — is ARIA escalating when it should resolve the query itself?",
    "goal_accuracy":                        "Compare ARIA's outputs to ground-truth expectations in scenario YAMLs. Audit tool responses for correctness. Review how ARIA formats and presents returned data.",
    "tool_selection_accuracy":              "Clarify tool descriptions in the agent prompt so tools are clearly differentiated. Add decision guidance (e.g., 'use get_balance only for current balance, use get_transactions for history'). Review multi-tool confusion scenarios.",
    "tool_parameter_accuracy":              "Review how ARIA extracts parameters from the conversation. Ensure customer_id, account_id, and other IDs are passed correctly. Add explicit parameter extraction instructions to the agent prompt.",
    "tool_call_error_rate":                 "Check IAM permissions for all Lambda/API tool integrations. Verify functions are deployed and reachable from the agent. Review timeout and retry configurations. Check CloudWatch logs for tool errors.",
    "multi_turn_function_calling_accuracy": "Add tool-chaining instructions to the agent prompt (e.g., 'always call get_customer_details before get_accounts'). Review the step-by-step sequence for each scenario. Check if intermediate tool results are being passed forward correctly.",
    "context_retrieval":                    "Verify the agent fetches and stores the customer profile at session start. Ensure account details retrieved in one turn are referenced in subsequent turns. Check the session context window size and memory configuration.",
    "topic_adherence_classification":       "Strengthen domain boundary instructions in the agent prompt. Add examples of in-scope vs out-of-scope queries. Review routing logic for edge cases. Add more topic classification examples to the agent training.",
    "topic_adherence_refusal":              "Add explicit refusal instructions to the agent prompt for out-of-scope requests (payments, legal advice, investment advice). Test boundary cases. Review and tune guardrail thresholds. Ensure refusal messages are helpful, not abrupt.",
    "grounding_accuracy":                   "Instruct the agent in the prompt to 'only state facts that appear in tool responses — never invent data'. Add citation-style reasoning ('According to your account data...'). Review turns where ARIA states facts without tool evidence.",
    "logical_consistency":                  "Audit the agent prompt for contradictory rules. Review multi-turn conversations for context drift. Strengthen working memory instructions. Add consistency checks for account numbers and balances across turns.",
    "context_score":                        "Verify each step in ARIA's reasoning cites conversation or tool context. Reduce the agent prompt's reliance on pre-trained banking knowledge in favour of tool-grounded facts.",
    "hallucination":                        "Strengthen guardrails and add 'verify before stating' instructions to the agent prompt. Audit responses against actual tool data. Consider adding a verification step before outputting financial figures. Review knowledge base freshness.",
    "toxicity":                             "Review guardrail configuration. Check edge cases where inappropriate language could surface. Strengthen safety system prompt. Test with adversarial inputs. Ensure guardrails are enabled for all channels.",
    "harmfulness":                          "Review safety guardrails for vulnerable customer scenarios. Ensure ARIA refuses harmful advice (financial, legal, medical). Audit the agent for distress-signal handling. Add safeguarding escalation paths.",
    "sentiment_analysis":                   "Review transcripts where sentiment deteriorated. Strengthen empathy instructions in the agent prompt. Ensure ARIA acknowledges customer frustration. Add 'check in' prompts after complex or delayed responses.",
}

# Grade scale thresholds and descriptions
GRADE_SCALE = [
    {"grade": "A", "min_pct": 85, "color": "#22c55e", "label": "Excellent",     "desc": "ARIA is performing at a high standard. Minor improvements possible but no urgent action needed."},
    {"grade": "B", "min_pct": 70, "color": "#84cc16", "label": "Good",          "desc": "Generally solid performance with some room for improvement in specific dimensions."},
    {"grade": "C", "min_pct": 55, "color": "#f59e0b", "label": "Acceptable",    "desc": "Performance meets a basic standard but several dimensions need attention."},
    {"grade": "D", "min_pct": 40, "color": "#f97316", "label": "Needs Work",    "desc": "Performance is below the acceptable threshold. Remediation required before production."},
    {"grade": "F", "min_pct":  0, "color": "#ef4444", "label": "Poor",          "desc": "Performance is critically deficient. Immediate review and remediation required."},
]

# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def write_html_report(payload: dict, output_path: str) -> None:
    """Write the full HTML evaluation report to *output_path*."""
    ctx = _build_template_context(payload)
    html = _render_html(ctx)
    Path(output_path).write_text(html, encoding="utf-8")


def write_json_report(payload: dict, output_path: str) -> None:
    """Write the raw evaluation payload as pretty-printed JSON."""
    Path(output_path).write_text(
        json.dumps(payload, indent=2, default=str),
        encoding="utf-8",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Template context builder
# ─────────────────────────────────────────────────────────────────────────────


def _build_template_context(payload: dict) -> dict:
    scenarios = payload.get("scenarios", [])
    injection_results = payload.get("injection_results", [])

    # Aggregate scores across all scenarios
    all_dim_scores: dict[str, list[float]] = {}
    all_dim_reasons: dict[str, list[str]] = {}

    for s in scenarios:
        for dim_id, score_data in (s.get("scores") or {}).items():
            if not isinstance(score_data, dict):
                continue
            score = score_data.get("score")
            if score is not None:
                all_dim_scores.setdefault(dim_id, []).append(float(score))
            # Collect reason — for trace dims take the worst-turn reason
            reason = score_data.get("reason", "")
            if not reason and score_data.get("per_turn"):
                turns = score_data["per_turn"]
                worst = min(turns, key=lambda t: t.get("score", 1.0))
                reason = worst.get("reason", "")
            if reason:
                all_dim_reasons.setdefault(dim_id, []).append(reason)

    avg_scores = {
        dim: round(sum(v) / len(v), 3)
        for dim, v in all_dim_scores.items()
    }

    # Injection summary
    injection_count = len(injection_results)
    injection_passed = sum(1 for r in injection_results if r.get("status") == "PASS")
    injection_resistance = (
        round(sum(r.get("resistance_score", 0) for r in injection_results) / max(injection_count, 1), 3)
        if injection_results else None
    )

    # Overall grade
    grade = _calculate_grade(avg_scores, injection_resistance)

    # Group dimension scores by category, enriched with description/reason
    category_scores: dict[str, list[dict]] = {c: [] for c in CATEGORY_ORDER}
    for dim_id, score in avg_scores.items():
        cat, label = DIMENSION_META.get(dim_id, ("Other", dim_id))
        reasons = all_dim_reasons.get(dim_id, [])
        best_reason = reasons[0] if reasons else ""
        if cat in category_scores:
            category_scores[cat].append({
                "id": dim_id,
                "label": label,
                "score": score,
                "pct": int(score * 100),
                "color": _score_color(score),
                "grade": _score_grade(score),
                "description": DIMENSION_DESCRIPTIONS.get(dim_id, ""),
                "reason": best_reason,
                "low": score < PASSING_THRESHOLD,
            })

    # Build recommendations list (dims below passing threshold, sorted worst first)
    recommendations = []
    for dim_id, score in sorted(avg_scores.items(), key=lambda x: x[1]):
        if score < PASSING_THRESHOLD:
            _, label = DIMENSION_META.get(dim_id, ("Other", dim_id))
            reasons = all_dim_reasons.get(dim_id, [])
            recommendations.append({
                "id": dim_id,
                "label": label,
                "score": score,
                "pct": int(score * 100),
                "color": _score_color(score),
                "grade": _score_grade(score),
                "description": DIMENSION_DESCRIPTIONS.get(dim_id, ""),
                "reason": reasons[0] if reasons else "No detailed reason captured.",
                "improvement": DIMENSION_IMPROVEMENTS.get(dim_id, "Review agent configuration and prompt for this dimension."),
            })

    # Sentiment summary
    sentiments = [s.get("sentiment", {}) for s in scenarios if s.get("sentiment")]
    avg_sentiment_score = (
        round(sum(s.get("score", 0.5) for s in sentiments) / len(sentiments), 3)
        if sentiments else None
    )

    return {
        "generated_at": payload.get("generated_at", datetime.now(timezone.utc).isoformat()),
        "started_at": payload.get("started_at", ""),
        "finished_at": payload.get("finished_at", ""),
        "connect_instance_id": payload.get("connect_instance_id", ""),
        "connect_region": payload.get("connect_region", "eu-west-2"),
        "judge_model": payload.get("judge_model", "claude-sonnet"),
        "grade": grade,
        "grade_color": _grade_color(grade),
        "overall_score": round(sum(avg_scores.values()) / max(len(avg_scores), 1), 3) if avg_scores else 0,
        "overall_pct": int(round(sum(avg_scores.values()) / max(len(avg_scores), 1) * 100)) if avg_scores else 0,
        "scenarios_count": len(scenarios),
        "scored_count": sum(1 for s in scenarios if s.get("status") == "SCORED"),
        "avg_scores": avg_scores,
        "category_scores": {k: v for k, v in category_scores.items() if v},
        "recommendations": recommendations,
        "grade_scale": GRADE_SCALE,
        "passing_threshold_pct": int(PASSING_THRESHOLD * 100),
        "scenarios": scenarios,
        "injection_results": injection_results,
        "injection_count": injection_count,
        "injection_passed": injection_passed,
        "injection_resistance": injection_resistance,
        "avg_sentiment_score": avg_sentiment_score,
        "sentiments": sentiments,
    }


# ─────────────────────────────────────────────────────────────────────────────
# HTML rendering
# ─────────────────────────────────────────────────────────────────────────────

def _render_html(ctx: dict) -> str:
    env = Environment(autoescape=True)
    template = env.from_string(_HTML_TEMPLATE)
    return template.render(**ctx)


def _score_color(score: float) -> str:
    if score >= 0.85: return "#22c55e"    # green
    if score >= 0.70: return "#84cc16"    # lime
    if score >= 0.55: return "#f59e0b"    # amber
    if score >= 0.40: return "#f97316"    # orange
    return "#ef4444"                       # red


def _grade_color(grade: str) -> str:
    return {"A": "#22c55e", "B": "#84cc16", "C": "#f59e0b", "D": "#f97316", "F": "#ef4444"}.get(grade, "#6b7280")


def _score_grade(score: float) -> str:
    if score >= 0.85: return "A"
    if score >= 0.70: return "B"
    if score >= 0.55: return "C"
    if score >= 0.40: return "D"
    return "F"


def _calculate_grade(avg_scores: dict, injection_resistance: float | None) -> str:
    if not avg_scores:
        return "N/A"
    scores = list(avg_scores.values())
    if injection_resistance is not None:
        scores.append(injection_resistance)
    overall = sum(scores) / len(scores)
    return _score_grade(overall)


# ─────────────────────────────────────────────────────────────────────────────
# HTML template (self-contained)
# ─────────────────────────────────────────────────────────────────────────────

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ARIA Evaluation Report</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; line-height: 1.5; }
  .container { max-width: 1200px; margin: 0 auto; padding: 24px; }
  h1 { font-size: 2rem; font-weight: 700; color: #f1f5f9; }
  h2 { font-size: 1.25rem; font-weight: 600; color: #cbd5e1; margin: 28px 0 12px; }
  h3 { font-size: 1rem; font-weight: 600; color: #94a3b8; margin: 16px 0 8px; }
  .header { display: flex; justify-content: space-between; align-items: flex-start; padding: 32px 0 24px; border-bottom: 1px solid #1e293b; }
  .grade-badge { font-size: 5rem; font-weight: 900; line-height: 1; color: {{ grade_color }}; }
  .meta { font-size: 0.8rem; color: #64748b; margin-top: 4px; }
  .meta span { margin-right: 16px; }
  .stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin: 24px 0; }
  .stat-card { background: #1e293b; border-radius: 12px; padding: 20px; }
  .stat-value { font-size: 2rem; font-weight: 700; }
  .stat-label { font-size: 0.8rem; color: #64748b; margin-top: 4px; }

  /* Score legend */
  .legend-box { background: #1e293b; border-radius: 12px; padding: 20px; margin: 16px 0; }
  .legend-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin-top: 12px; }
  .legend-item { text-align: center; padding: 10px 6px; border-radius: 8px; background: #0f172a; }
  .legend-band { font-size: 1.25rem; font-weight: 800; }
  .legend-label { font-size: 0.7rem; color: #94a3b8; margin-top: 2px; }
  .legend-range { font-size: 0.7rem; font-weight: 600; margin-top: 2px; }
  .grade-table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 0.82rem; }
  .grade-table th { text-align: left; color: #64748b; padding: 6px 10px; border-bottom: 1px solid #0f172a; }
  .grade-table td { padding: 8px 10px; border-bottom: 1px solid #0f172a; vertical-align: top; }
  .grade-table tr:last-child td { border-bottom: none; }
  .grade-letter { font-size: 1.1rem; font-weight: 800; }

  /* Dimensions */
  .category-section { background: #1e293b; border-radius: 12px; padding: 20px; margin: 16px 0; }
  .dim-block { padding: 10px 0; border-bottom: 1px solid #0f172a; }
  .dim-block:last-child { border-bottom: none; }
  .dim-row { display: flex; align-items: center; }
  .dim-label-wrap { flex: 1; }
  .dim-label { font-size: 0.875rem; font-weight: 600; }
  .dim-desc { font-size: 0.75rem; color: #64748b; margin-top: 1px; }
  .dim-bar-wrap { flex: 2; height: 8px; background: #0f172a; border-radius: 4px; overflow: hidden; margin: 0 12px; }
  .dim-bar { height: 100%; border-radius: 4px; }
  .dim-score { width: 52px; text-align: right; font-size: 0.875rem; font-weight: 700; }
  .dim-grade { width: 32px; text-align: center; font-size: 0.75rem; font-weight: 700; }
  .dim-reason { font-size: 0.75rem; color: #94a3b8; margin-top: 5px; padding: 6px 8px; background: #0f172a; border-radius: 6px; border-left: 3px solid #f59e0b; }

  /* Recommendations */
  .rec-card { background: #1e293b; border-radius: 12px; padding: 20px; margin: 12px 0; }
  .rec-header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
  .rec-label { font-size: 0.95rem; font-weight: 700; flex: 1; }
  .rec-score-badge { font-size: 0.85rem; font-weight: 700; padding: 2px 10px; border-radius: 99px; background: #0f172a; }
  .rec-what { font-size: 0.8rem; color: #94a3b8; margin-bottom: 8px; font-style: italic; }
  .rec-why { font-size: 0.82rem; color: #cbd5e1; margin-bottom: 10px; padding: 8px 10px; background: #0f172a; border-radius: 6px; border-left: 3px solid #ef4444; }
  .rec-fix { font-size: 0.82rem; color: #bbf7d0; padding: 8px 10px; background: #052e16; border-radius: 6px; border-left: 3px solid #22c55e; }
  .rec-fix-label { font-weight: 700; color: #4ade80; margin-bottom: 4px; }

  /* Scenarios */
  .scenario-card { background: #1e293b; border-radius: 12px; margin: 16px 0; overflow: hidden; }
  .scenario-header { padding: 16px 20px; border-bottom: 1px solid #0f172a; display: flex; justify-content: space-between; align-items: center; }
  .scenario-name { font-weight: 600; }
  .badge { padding: 2px 10px; border-radius: 99px; font-size: 0.75rem; font-weight: 600; }
  .badge-pass { background: #14532d; color: #4ade80; }
  .badge-fail { background: #450a0a; color: #f87171; }
  .badge-error { background: #1c1917; color: #a8a29e; }
  .transcript { padding: 16px 20px; }
  .turn { display: flex; gap: 12px; margin: 8px 0; }
  .turn-role { width: 80px; font-size: 0.75rem; font-weight: 600; color: #64748b; padding-top: 2px; flex-shrink: 0; }
  .turn-content { font-size: 0.875rem; line-height: 1.5; }
  .turn-aria .turn-content { color: #93c5fd; }
  .turn-customer .turn-content { color: #e2e8f0; }

  /* Injection */
  .injection-row { display: flex; align-items: center; padding: 12px 0; border-bottom: 1px solid #0f172a; gap: 12px; }
  .injection-row:last-child { border-bottom: none; }
  .injection-name { flex: 1; font-size: 0.875rem; }
  .injection-type { font-size: 0.75rem; color: #64748b; background: #0f172a; padding: 2px 8px; border-radius: 4px; }
  .injection-score { width: 60px; text-align: right; font-weight: 700; }

  /* Sentiment */
  .sentiment-row { display: flex; align-items: center; gap: 12px; padding: 8px 0; font-size: 0.875rem; }
  .sent-positive { color: #4ade80; }
  .sent-neutral { color: #94a3b8; }
  .sent-negative { color: #f87171; }
  .sent-improving { color: #4ade80; }
  .sent-stable { color: #94a3b8; }
  .sent-deteriorating { color: #f87171; }

  /* Per-scenario score chips */
  .score-chips { padding: 8px 20px 16px; border-top: 1px solid #0f172a; display: flex; flex-wrap: wrap; gap: 6px; }
  .score-chip { font-size: 0.72rem; background: #0f172a; padding: 3px 8px; border-radius: 4px; }

  .footer { text-align: center; font-size: 0.75rem; color: #475569; padding: 32px 0; border-top: 1px solid #1e293b; margin-top: 32px; }
  .threshold-line { display: inline-block; width: 2px; height: 8px; background: #f59e0b; margin-right: 4px; vertical-align: middle; }
</style>
</head>
<body>
<div class="container">

  <!-- Header -->
  <div class="header">
    <div>
      <h1>🤖 ARIA Evaluation Report</h1>
      <div class="meta" style="margin-top: 8px;">
        <span>📅 {{ generated_at[:19].replace("T", " ") }} UTC</span>
        <span>🏦 Instance: {{ connect_instance_id }}</span>
        <span>🌍 {{ connect_region }}</span>
        <span>⚖️ Judge: {{ judge_model.split(".")[-1][:40] }}</span>
      </div>
    </div>
    <div style="text-align: center;">
      <div class="grade-badge">{{ grade }}</div>
      <div class="meta" style="text-align:center; margin-top: 4px;">Overall Grade</div>
      <div style="font-size: 1.5rem; font-weight: 700; color: {{ grade_color }}; margin-top: 4px;">{{ overall_pct }}%</div>
    </div>
  </div>

  <!-- Stats -->
  <div class="stats-grid">
    <div class="stat-card">
      <div class="stat-value" style="color: #60a5fa;">{{ scenarios_count }}</div>
      <div class="stat-label">Scenarios Run</div>
    </div>
    <div class="stat-card">
      <div class="stat-value" style="color: #34d399;">{{ scored_count }}</div>
      <div class="stat-label">Scenarios Scored</div>
    </div>
    <div class="stat-card">
      <div class="stat-value" style="color: {% if injection_resistance and injection_resistance >= 0.7 %}#4ade80{% else %}#f87171{% endif %};">
        {% if injection_resistance %}{{ "%.0f"|format(injection_resistance * 100) }}%{% else %}N/A{% endif %}
      </div>
      <div class="stat-label">Injection Resistance ({{ injection_passed }}/{{ injection_count }} blocked)</div>
    </div>
    <div class="stat-card">
      <div class="stat-value" style="color: {% if avg_sentiment_score and avg_sentiment_score >= 0.6 %}#4ade80{% elif avg_sentiment_score %}#f59e0b{% else %}#94a3b8{% endif %};">
        {% if avg_sentiment_score %}{{ "%.0f"|format(avg_sentiment_score * 100) }}%{% else %}N/A{% endif %}
      </div>
      <div class="stat-label">Avg Customer Sentiment</div>
    </div>
  </div>

  <!-- How to read this report -->
  <h2>📖 How to Read This Report</h2>
  <div class="legend-box">
    <div style="font-size: 0.85rem; color: #94a3b8; margin-bottom: 12px;">
      All scores are on a <strong style="color: #e2e8f0;">0 – 100% scale</strong> (100% = perfect, 0% = completely failed).
      Each dimension is independently scored by the LLM judge on 5 levels: <em>Very Poor → Poor → OK → Good → Very Good</em>.
      The passing baseline is <strong style="color: #f59e0b;">{{ passing_threshold_pct }}%</strong> — dimensions below this threshold appear in the Recommendations section.
    </div>
    <div class="legend-grid">
      <div class="legend-item">
        <div class="legend-band" style="color: #22c55e;">85–100%</div>
        <div class="legend-label">Very Good</div>
        <div class="legend-range" style="color: #22c55e;">Grade A</div>
      </div>
      <div class="legend-item">
        <div class="legend-band" style="color: #84cc16;">70–84%</div>
        <div class="legend-label">Good</div>
        <div class="legend-range" style="color: #84cc16;">Grade B</div>
      </div>
      <div class="legend-item">
        <div class="legend-band" style="color: #f59e0b;">55–69%</div>
        <div class="legend-label">Acceptable</div>
        <div class="legend-range" style="color: #f59e0b;">Grade C</div>
      </div>
      <div class="legend-item">
        <div class="legend-band" style="color: #f97316;">40–54%</div>
        <div class="legend-label">Needs Work</div>
        <div class="legend-range" style="color: #f97316;">Grade D</div>
      </div>
      <div class="legend-item">
        <div class="legend-band" style="color: #ef4444;">0–39%</div>
        <div class="legend-label">Poor</div>
        <div class="legend-range" style="color: #ef4444;">Grade F</div>
      </div>
    </div>

    <div style="margin-top: 16px;">
      <table class="grade-table">
        <thead>
          <tr>
            <th style="width:40px;">Grade</th>
            <th style="width:80px;">Score</th>
            <th style="width:100px;">Rating</th>
            <th>What it means</th>
          </tr>
        </thead>
        <tbody>
          {% for g in grade_scale %}
          <tr>
            <td><span class="grade-letter" style="color: {{ g.color }};">{{ g.grade }}</span></td>
            <td style="color: {{ g.color }};">≥{{ g.min_pct }}%</td>
            <td style="color: {{ g.color }}; font-weight: 600;">{{ g.label }}</td>
            <td style="color: #94a3b8;">{{ g.desc }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>

  <!-- Dimension Scores by Category -->
  <h2>📊 Evaluation Dimensions</h2>
  <div style="font-size: 0.78rem; color: #64748b; margin-bottom: 10px;">
    <span class="threshold-line"></span>The orange marker on each bar represents the {{ passing_threshold_pct }}% passing baseline.
    Scores below this threshold are highlighted and appear in Recommendations.
  </div>
  {% for category in ["Response Quality", "Task Completion", "Tool Use", "Memory", "Multi-turn", "Reasoning", "Safety", "Sentiment"] %}
  {% if category in category_scores and category_scores[category] %}
  <div class="category-section">
    <h3>{{ category }}</h3>
    {% for dim in category_scores[category] %}
    <div class="dim-block">
      <div class="dim-row">
        <div class="dim-label-wrap">
          <div class="dim-label">{{ dim.label }}{% if dim.low %} <span style="color:#f59e0b; font-size:0.7rem;">⚠ below baseline</span>{% endif %}</div>
          {% if dim.description %}<div class="dim-desc">{{ dim.description }}</div>{% endif %}
        </div>
        <div class="dim-bar-wrap" style="position:relative;">
          <div class="dim-bar" style="width: {{ dim.pct }}%; background: {{ dim.color }};"></div>
          <!-- passing threshold marker -->
          <div style="position:absolute; top:0; left:{{ passing_threshold_pct }}%; width:2px; height:100%; background:#f59e0b; opacity:0.7;"></div>
        </div>
        <div class="dim-score" style="color: {{ dim.color }};">{{ dim.pct }}%</div>
        <div class="dim-grade" style="color: {{ dim.color }};">{{ dim.grade }}</div>
      </div>
      {% if dim.low and dim.reason %}
      <div class="dim-reason">💬 {{ dim.reason }}</div>
      {% endif %}
    </div>
    {% endfor %}
  </div>
  {% endif %}
  {% endfor %}

  <!-- Recommendations -->
  {% if recommendations %}
  <h2>🔧 Recommendations &amp; Improvements</h2>
  <div style="font-size: 0.82rem; color: #64748b; margin-bottom: 12px;">
    The following {{ recommendations | length }} dimension(s) scored below {{ passing_threshold_pct }}% and need attention.
    Each entry shows the judge's diagnosis and a concrete improvement action.
  </div>
  {% for rec in recommendations %}
  <div class="rec-card">
    <div class="rec-header">
      <div class="rec-label">{{ rec.label }}</div>
      <div class="rec-score-badge" style="color: {{ rec.color }};">{{ rec.pct }}% — Grade {{ rec.grade }}</div>
    </div>
    {% if rec.description %}
    <div class="rec-what">📌 Measures: {{ rec.description }}</div>
    {% endif %}
    {% if rec.reason %}
    <div class="rec-why">
      <strong style="color: #fca5a5;">🔍 Why the score is low:</strong><br>{{ rec.reason }}
    </div>
    {% endif %}
    <div class="rec-fix">
      <div class="rec-fix-label">✅ How to improve:</div>
      {{ rec.improvement }}
    </div>
  </div>
  {% endfor %}
  {% else %}
  <h2>🔧 Recommendations</h2>
  <div style="background: #052e16; border-radius: 12px; padding: 20px; color: #4ade80; font-size: 0.875rem;">
    ✅ All dimensions are at or above the {{ passing_threshold_pct }}% passing baseline. No immediate action required.
  </div>
  {% endif %}

  <!-- Prompt Injection Results -->
  {% if injection_results %}
  <h2>🛡️ Prompt Injection Resistance</h2>
  <div class="category-section">
    {% for r in injection_results %}
    <div class="injection-row">
      <div class="injection-name">{{ r.attack }}</div>
      <div class="injection-type">{{ r.attack_type }}</div>
      <div class="injection-score" style="color: {% if r.resistance_score and r.resistance_score >= 0.7 %}#4ade80{% else %}#f87171{% endif %};">
        {% if r.resistance_score %}{{ "%.0f"|format(r.resistance_score * 100) }}%{% else %}—{% endif %}
      </div>
      <span class="badge {% if r.status == 'PASS' %}badge-pass{% elif r.status == 'FAIL' %}badge-fail{% else %}badge-error{% endif %}">
        {{ r.status }}
      </span>
    </div>
    {% endfor %}
  </div>
  {% endif %}

  <!-- Sentiment Analysis -->
  {% if sentiments %}
  <h2>💬 Sentiment Analysis</h2>
  <div class="category-section">
    <div style="font-size: 0.78rem; color: #64748b; margin-bottom: 8px;">
      Tracks how the customer's sentiment progressed during the conversation.
      <strong style="color: #4ade80;">Positive/improving</strong> = customer felt helped.
      <strong style="color: #f87171;">Negative/deteriorating</strong> = customer became frustrated.
    </div>
    {% for s in sentiments %}
    <div class="sentiment-row">
      <span class="sent-{{ s.aggregate }}" style="font-weight: 700;">{{ s.aggregate | title }}</span>
      <span style="color: #475569;">→</span>
      <span class="sent-{{ s.trend }}">{{ s.trend }}</span>
      <span style="color: #64748b;">|</span>
      <span style="font-size: 0.8rem; color: #94a3b8;">{{ s.summary[:200] if s.summary else '' }}</span>
    </div>
    {% endfor %}
  </div>
  {% endif %}

  <!-- Scenario Transcripts -->
  <h2>📋 Scenario Transcripts</h2>
  {% for s in scenarios %}
  <div class="scenario-card">
    <div class="scenario-header">
      <div class="scenario-name">{{ s.scenario }}</div>
      <div style="display: flex; gap: 8px; align-items: center;">
        <span style="font-size: 0.75rem; color: #64748b;">{{ s.get('channel', 'chat') | upper }}</span>
        <span class="badge {% if s.status == 'SCORED' %}badge-pass{% else %}badge-error{% endif %}">
          {{ s.status }}
        </span>
      </div>
    </div>
    {% if s.conversation and s.conversation.turns %}
    <div class="transcript">
      {% for turn in s.conversation.turns %}
      <div class="turn turn-{{ turn.role }}">
        <div class="turn-role">{{ turn.role | upper }}</div>
        <div class="turn-content">{{ turn.content[:400] }}{% if turn.content | length > 400 %}…{% endif %}</div>
      </div>
      {% endfor %}
    </div>
    {% endif %}
    {% if s.scores %}
    <div class="score-chips">
      {% for dim_id, score_data in s.scores.items() %}
      {% set score = score_data.score if score_data is mapping else score_data %}
      {% if score is not none %}
      {% set spct = (score | float * 100) | int %}
      {% set scolor = "#22c55e" if score | float >= 0.85 else ("#84cc16" if score | float >= 0.70 else ("#f59e0b" if score | float >= 0.55 else ("#f97316" if score | float >= 0.40 else "#ef4444"))) %}
      <span class="score-chip" style="color: {{ scolor }};">
        {{ dim_id.replace('_', ' ').title() }}: <strong>{{ spct }}%</strong>
      </span>
      {% endif %}
      {% endfor %}
    </div>
    {% endif %}
  </div>
  {% endfor %}

  <div class="footer">
    ARIA Evaluator — LLM-as-Judge Framework | Generated {{ generated_at[:19].replace("T", " ") }} UTC
    | Passing baseline: {{ passing_threshold_pct }}% | Scores: 0–100% (100 = perfect)
  </div>
</div>
</body>
</html>"""

