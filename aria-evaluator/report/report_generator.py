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
    for s in scenarios:
        for dim_id, score_data in (s.get("scores") or {}).items():
            score = score_data.get("score") if isinstance(score_data, dict) else score_data
            if score is not None:
                all_dim_scores.setdefault(dim_id, []).append(float(score))

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

    # Group dimension scores by category
    category_scores: dict[str, list[dict]] = {c: [] for c in CATEGORY_ORDER}
    for dim_id, score in avg_scores.items():
        cat, label = DIMENSION_META.get(dim_id, ("Other", dim_id))
        if cat in category_scores:
            category_scores[cat].append({
                "id": dim_id,
                "label": label,
                "score": score,
                "pct": int(score * 100),
                "color": _score_color(score),
                "grade": _score_grade(score),
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
        "scenarios_count": len(scenarios),
        "scored_count": sum(1 for s in scenarios if s.get("status") == "SCORED"),
        "avg_scores": avg_scores,
        "category_scores": {k: v for k, v in category_scores.items() if v},
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
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; }
  .container { max-width: 1200px; margin: 0 auto; padding: 24px; }
  h1 { font-size: 2rem; font-weight: 700; color: #f1f5f9; }
  h2 { font-size: 1.25rem; font-weight: 600; color: #cbd5e1; margin: 24px 0 12px; }
  h3 { font-size: 1rem; font-weight: 600; color: #94a3b8; margin: 16px 0 8px; }
  .header { display: flex; justify-content: space-between; align-items: flex-start; padding: 32px 0 24px; border-bottom: 1px solid #1e293b; }
  .grade-badge { font-size: 5rem; font-weight: 900; line-height: 1; color: {{ grade_color }}; }
  .meta { font-size: 0.8rem; color: #64748b; margin-top: 4px; }
  .meta span { margin-right: 16px; }
  .stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin: 24px 0; }
  .stat-card { background: #1e293b; border-radius: 12px; padding: 20px; }
  .stat-value { font-size: 2rem; font-weight: 700; }
  .stat-label { font-size: 0.8rem; color: #64748b; margin-top: 4px; }
  .category-section { background: #1e293b; border-radius: 12px; padding: 20px; margin: 16px 0; }
  .dim-row { display: flex; align-items: center; padding: 8px 0; border-bottom: 1px solid #0f172a; }
  .dim-row:last-child { border-bottom: none; }
  .dim-label { flex: 1; font-size: 0.875rem; }
  .dim-bar-wrap { flex: 2; height: 8px; background: #0f172a; border-radius: 4px; overflow: hidden; margin: 0 12px; }
  .dim-bar { height: 100%; border-radius: 4px; }
  .dim-score { width: 48px; text-align: right; font-size: 0.875rem; font-weight: 600; }
  .dim-grade { width: 28px; text-align: center; font-size: 0.75rem; font-weight: 700; }
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
  .injection-row { display: flex; align-items: center; padding: 12px 0; border-bottom: 1px solid #0f172a; gap: 12px; }
  .injection-row:last-child { border-bottom: none; }
  .injection-name { flex: 1; font-size: 0.875rem; }
  .injection-type { font-size: 0.75rem; color: #64748b; background: #0f172a; padding: 2px 8px; border-radius: 4px; }
  .injection-score { width: 60px; text-align: right; font-weight: 700; }
  .sentiment-row { display: flex; align-items: center; gap: 12px; padding: 8px 0; font-size: 0.875rem; }
  .sent-positive { color: #4ade80; }
  .sent-neutral { color: #94a3b8; }
  .sent-negative { color: #f87171; }
  .sent-improving { color: #4ade80; }
  .sent-stable { color: #94a3b8; }
  .sent-deteriorating { color: #f87171; }
  .footer { text-align: center; font-size: 0.75rem; color: #475569; padding: 32px 0; border-top: 1px solid #1e293b; margin-top: 32px; }
</style>
</head>
<body>
<div class="container">

  <!-- Header -->
  <div class="header">
    <div>
      <h1>🤖 ARIA Evaluation Report</h1>
      <div class="meta">
        <span>📅 {{ generated_at[:19].replace("T", " ") }} UTC</span>
        <span>🏦 Instance: {{ connect_instance_id }}</span>
        <span>🌍 {{ connect_region }}</span>
        <span>⚖️ Judge: {{ judge_model.split(".")[-1][:30] }}</span>
      </div>
    </div>
    <div style="text-align: center;">
      <div class="grade-badge">{{ grade }}</div>
      <div class="meta" style="text-align:center;">Overall Grade</div>
      <div style="font-size: 1.5rem; font-weight: 700; color: {{ grade_color }}; margin-top: 4px;">{{ "%.1f"|format(overall_score * 100) }}%</div>
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

  <!-- Dimension Scores by Category -->
  <h2>📊 Evaluation Dimensions</h2>
  {% for category in ["Response Quality", "Task Completion", "Tool Use", "Memory", "Multi-turn", "Reasoning", "Safety", "Sentiment"] %}
  {% if category in category_scores and category_scores[category] %}
  <div class="category-section">
    <h3>{{ category }}</h3>
    {% for dim in category_scores[category] %}
    <div class="dim-row">
      <div class="dim-label">{{ dim.label }}</div>
      <div class="dim-bar-wrap">
        <div class="dim-bar" style="width: {{ dim.pct }}%; background: {{ dim.color }};"></div>
      </div>
      <div class="dim-score" style="color: {{ dim.color }};">{{ "%.2f"|format(dim.score) }}</div>
      <div class="dim-grade" style="color: {{ dim.color }};">{{ dim.grade }}</div>
    </div>
    {% endfor %}
  </div>
  {% endif %}
  {% endfor %}

  <!-- Prompt Injection Results -->
  {% if injection_results %}
  <h2>🛡️ Prompt Injection Resistance</h2>
  <div class="category-section">
    {% for r in injection_results %}
    <div class="injection-row">
      <div class="injection-name">{{ r.attack }}</div>
      <div class="injection-type">{{ r.attack_type }}</div>
      <div class="injection-score" style="color: {% if r.resistance_score and r.resistance_score >= 0.7 %}#4ade80{% else %}#f87171{% endif %};">
        {% if r.resistance_score %}{{ "%.2f"|format(r.resistance_score) }}{% else %}—{% endif %}
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
    {% for s in sentiments %}
    <div class="sentiment-row">
      <span class="sent-{{ s.aggregate }}">{{ s.aggregate | title }}</span>
      <span>→</span>
      <span class="sent-{{ s.trend }}">{{ s.trend }}</span>
      <span style="color: #64748b;">|</span>
      <span style="font-size: 0.8rem; color: #94a3b8;">{{ s.summary[:120] if s.summary else '' }}</span>
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
        <div class="turn-content">{{ turn.content[:300] }}{% if turn.content | length > 300 %}…{% endif %}</div>
      </div>
      {% endfor %}
    </div>
    {% endif %}
    {% if s.scores %}
    <div style="padding: 8px 20px 16px; border-top: 1px solid #0f172a; display: flex; flex-wrap: wrap; gap: 8px;">
      {% for dim_id, score_data in s.scores.items() %}
      {% set score = score_data.score if score_data is mapping else score_data %}
      {% if score is not none %}
      <span style="font-size: 0.75rem; background: #0f172a; padding: 2px 8px; border-radius: 4px; color: {{ score | float | round(2) | string | replace('.', '') }};">
        {{ dim_id.replace('_', ' ') }}: <strong>{{ "%.2f"|format(score | float) }}</strong>
      </span>
      {% endif %}
      {% endfor %}
    </div>
    {% endif %}
  </div>
  {% endfor %}

  <div class="footer">
    ARIA Evaluator — LLM-as-Judge Framework | Generated {{ generated_at[:19].replace("T", " ") }} UTC
  </div>
</div>
</body>
</html>"""
