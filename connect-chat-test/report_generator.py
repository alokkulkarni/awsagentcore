"""
report_generator.py
===================
Generates HTML and JSON test reports for the Amazon Connect chat test suite.

The HTML report is self-contained (all CSS inlined) using an embedded
Jinja2 template — no external template files needed.

Usage::

    from report_generator import write_html_report, write_json_report

    write_html_report(run_payload, "reports/chat_test_report.html")
    write_json_report(run_payload, "reports/chat_test_report.json")

run_payload schema::

    {
        "generated_at": "ISO 8601 string",
        "run_number": "42",               # GITHUB_RUN_NUMBER or "local"
        "aws_region": "eu-west-2",
        "connect_instance_id": "45ec8...",
        "summary": {
            "total": 5, "passed": 4, "failed": 1,
            "skipped": 0, "errored": 0, "pass_rate": "80.0%"
        },
        "test_cases": [
            {
                "name": "test_chat_scenario[BANK-101]",
                "scenario_name": "Verify greeting",
                "outcome": "PASSED",            # PASSED|FAILED|ERROR|SKIPPED
                "duration_s": 4.3,
                "timestamp": "ISO 8601",
                "zephyr_execution_id": 1234,    # int or None
                "turns": [
                    {
                        "turn_index": 1,
                        "sent": "Hello",
                        "expected": ["Welcome"],
                        "actual": "Welcome to Meridian Bank",
                        "status": "PASS",       # PASS|FAIL|TIMEOUT|ERROR
                        "duration_ms": 2100,
                        "error_message": None,
                    }
                ]
            }
        ]
    }
"""

import json
import os
from pathlib import Path
from typing import Optional

from jinja2 import Environment

# ---------------------------------------------------------------------------
# Default colour theme
# ---------------------------------------------------------------------------

_DEFAULT_THEME: dict = {
    "primary": "#232F3E",   # AWS dark navy
    "accent": "#FF9900",    # AWS orange
    "pass": "#1E8449",      # green
    "fail": "#C0392B",      # red
    "warn": "#E67E22",      # amber (TIMEOUT / SKIP)
    "error": "#7D3C98",     # purple (ERROR)
    "bg": "#F5F7FA",
    "card": "#FFFFFF",
    "border": "#DEE2E6",
    "text": "#212529",
    "muted": "#6C757D",
}

# ---------------------------------------------------------------------------
# Jinja2 HTML template (self-contained, no external files)
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Amazon Connect Chat Test Report — Run #{{ run_number }}</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body   { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
           background: {{ theme.bg }}; color: {{ theme.text }}; font-size: 14px;
           line-height: 1.5; }
  a      { color: {{ theme.accent }}; text-decoration: none; }
  code   { font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px;
           background: #eef; padding: 1px 4px; border-radius: 3px; }

  /* Header */
  .header { background: {{ theme.primary }}; color: #fff; padding: 20px 30px;
            display: flex; align-items: center; justify-content: space-between; }
  .header h1 { font-size: 20px; font-weight: 600; letter-spacing: .02em; }
  .header .meta { font-size: 12px; opacity: .75; text-align: right; }

  /* Stats bar */
  .stats { display: flex; gap: 16px; padding: 20px 30px; flex-wrap: wrap; }
  .stat  { flex: 1; min-width: 120px; background: {{ theme.card }}; border: 1px solid {{ theme.border }};
           border-radius: 8px; padding: 16px; text-align: center;
           box-shadow: 0 1px 3px rgba(0,0,0,.06); }
  .stat .value { font-size: 36px; font-weight: 700; line-height: 1; }
  .stat .label { font-size: 12px; color: {{ theme.muted }}; margin-top: 4px; text-transform: uppercase; letter-spacing: .05em; }
  .stat.passed .value { color: {{ theme.pass }}; }
  .stat.failed .value { color: {{ theme.fail }}; }
  .stat.rate   .value { color: {{ theme.accent }}; font-size: 28px; }

  /* Progress bar */
  .progress-wrap { margin: 0 30px 20px; height: 8px; background: {{ theme.border }};
                   border-radius: 4px; overflow: hidden; }
  .progress-fill { height: 100%; background: {{ theme.pass }}; border-radius: 4px;
                   transition: width .4s ease; }

  /* Main table */
  .section { padding: 0 30px 30px; }
  .section h2 { font-size: 15px; font-weight: 600; margin-bottom: 12px;
                color: {{ theme.muted }}; text-transform: uppercase; letter-spacing: .05em; }
  table  { width: 100%; border-collapse: collapse; background: {{ theme.card }};
           border: 1px solid {{ theme.border }}; border-radius: 8px; overflow: hidden;
           box-shadow: 0 1px 3px rgba(0,0,0,.06); }
  thead  { background: {{ theme.primary }}; color: #fff; }
  th     { padding: 10px 14px; text-align: left; font-size: 12px; font-weight: 600;
           letter-spacing: .04em; text-transform: uppercase; }
  td     { padding: 10px 14px; border-top: 1px solid {{ theme.border }}; vertical-align: top; }
  tr:hover td { background: #f8f9fa; }

  /* Status badges */
  .badge { display: inline-block; padding: 2px 10px; border-radius: 12px;
           font-size: 11px; font-weight: 700; letter-spacing: .04em;
           text-transform: uppercase; }
  .badge.passed  { background: #d4edda; color: {{ theme.pass }}; }
  .badge.failed  { background: #f8d7da; color: {{ theme.fail }}; }
  .badge.error   { background: #e8d5f0; color: {{ theme.error }}; }
  .badge.skipped { background: #fff3cd; color: {{ theme.warn }}; }
  .badge.pass    { background: #d4edda; color: {{ theme.pass }}; }
  .badge.fail    { background: #f8d7da; color: {{ theme.fail }}; }
  .badge.timeout { background: #fff3cd; color: {{ theme.warn }}; }

  /* Turn detail */
  details { margin-bottom: 12px; }
  summary { cursor: pointer; background: {{ theme.card }}; border: 1px solid {{ theme.border }};
            border-radius: 6px; padding: 10px 16px; font-weight: 500;
            list-style: none; display: flex; align-items: center; gap: 10px; }
  summary::-webkit-details-marker { display: none; }
  summary::before { content: "▶"; font-size: 10px; transition: transform .2s; }
  details[open] summary::before { transform: rotate(90deg); }
  .turn-table { margin-top: 8px; font-size: 12px; }
  .turn-table th { font-size: 11px; }
  .turn-pass td { background: #f0fff4; }
  .turn-fail td { background: #fff5f5; }
  .turn-timeout td { background: #fffbf0; }
  .turn-error td { background: #fdf4ff; }
  .msg-you { color: {{ theme.primary }}; font-weight: 500; }
  .msg-bot { color: #1a7f64; }

  /* Footer */
  footer { border-top: 1px solid {{ theme.border }}; padding: 16px 30px;
           font-size: 12px; color: {{ theme.muted }}; display: flex;
           justify-content: space-between; flex-wrap: wrap; gap: 8px; }
</style>
</head>
<body>

<div class="header">
  <h1>🤖 Amazon Connect Chat Test Report</h1>
  <div class="meta">
    Run #{{ run_number }}<br>
    {{ generated_at }}<br>
    Region: {{ aws_region }}<br>
    Instance: ***{{ instance_suffix }}
  </div>
</div>

<div class="stats">
  <div class="stat">
    <div class="value">{{ summary.total }}</div>
    <div class="label">Total</div>
  </div>
  <div class="stat passed">
    <div class="value">{{ summary.passed }}</div>
    <div class="label">Passed</div>
  </div>
  <div class="stat failed">
    <div class="value">{{ summary.failed }}</div>
    <div class="label">Failed</div>
  </div>
  <div class="stat">
    <div class="value">{{ summary.errored }}</div>
    <div class="label">Errors</div>
  </div>
  <div class="stat rate">
    <div class="value">{{ summary.pass_rate }}</div>
    <div class="label">Pass Rate</div>
  </div>
</div>

<div class="progress-wrap">
  <div class="progress-fill" style="width: {{ pass_rate_num }}%"></div>
</div>

<div class="section">
  <h2>Test Cases</h2>
  <table>
    <thead>
      <tr>
        <th>#</th>
        <th>Test Key</th>
        <th>Scenario</th>
        <th>Status</th>
        <th>Duration</th>
        <th>Zephyr Exec</th>
        <th>Timestamp</th>
      </tr>
    </thead>
    <tbody>
      {% for tc in test_cases %}
      <tr>
        <td>{{ loop.index }}</td>
        <td><code>{{ tc.name | extract_key }}</code></td>
        <td>{{ tc.scenario_name }}</td>
        <td><span class="badge {{ tc.outcome | lower }}">{{ tc.outcome }}</span></td>
        <td>{{ "%.2f"|format(tc.duration_s) }}s</td>
        <td>{{ tc.zephyr_execution_id if tc.zephyr_execution_id else "—" }}</td>
        <td>{{ tc.timestamp[:19].replace("T", " ") }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>

<div class="section">
  <h2>Turn-by-Turn Detail</h2>
  {% for tc in test_cases %}
  <details {% if tc.outcome != "PASSED" %}open{% endif %}>
    <summary>
      <span class="badge {{ tc.outcome | lower }}">{{ tc.outcome }}</span>
      <code>{{ tc.name | extract_key }}</code> — {{ tc.scenario_name }}
      ({{ "%.2f"|format(tc.duration_s) }}s)
    </summary>
    {% if tc.turns %}
    <table class="turn-table">
      <thead>
        <tr>
          <th>#</th>
          <th>Direction</th>
          <th>Message</th>
          <th>Expected</th>
          <th>Result</th>
          <th>Duration</th>
        </tr>
      </thead>
      <tbody>
        {% for turn in tc.turns %}
        {# "You" row #}
        <tr class="turn-{{ turn.status | lower }}">
          <td rowspan="2">{{ turn.turn_index }}</td>
          <td class="msg-you">You</td>
          <td>{{ turn.sent }}</td>
          <td>
            {% if turn.expected %}
              {{ turn.expected | join(", ") }}
            {% else %}
              <span style="color:#aaa">any</span>
            {% endif %}
          </td>
          <td>—</td>
          <td rowspan="2">{{ turn.duration_ms }}ms</td>
        </tr>
        {# "Bot" row #}
        <tr class="turn-{{ turn.status | lower }}">
          <td class="msg-bot">Bot</td>
          <td>
            {% if turn.actual %}
              {{ turn.actual }}
            {% elif turn.status == "TIMEOUT" %}
              <em style="color:{{ theme.warn }}">⏱ TIMEOUT</em>
            {% else %}
              <em style="color:{{ theme.error }}">{{ turn.error_message or "ERROR" }}</em>
            {% endif %}
          </td>
          <td></td>
          <td><span class="badge {{ turn.status | lower }}">{{ turn.status }}</span></td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <p style="padding: 12px 16px; color: {{ theme.muted }}">No turn detail available.</p>
    {% endif %}
    {% if tc.error %}
    <p style="padding: 8px 16px; color: {{ theme.fail }}; font-size: 12px;">
      <strong>Error:</strong> {{ tc.error }}
    </p>
    {% endif %}
  </details>
  {% endfor %}
</div>

<footer>
  <span>Generated by <strong>amazon-connect-chat-tester</strong></span>
  <span>Zephyr Squad cycle updated: {{ zephyr_updated }}</span>
</footer>

</body>
</html>
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def write_html_report(
    run_payload: dict,
    output_path: str,
    theme: Optional[dict] = None,
) -> None:
    """
    Render the HTML report and write it to *output_path*.

    Args:
        run_payload: The structured report dict (see module docstring).
        output_path: Destination path for the .html file.
        theme:       Optional colour overrides (merged with _DEFAULT_THEME).
    """
    merged_theme = {**_DEFAULT_THEME, **(theme or {})}
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    env = Environment(autoescape=True)
    env.filters["extract_key"] = _extract_key_filter

    template = env.from_string(_HTML_TEMPLATE)

    # Pre-compute the numeric pass rate for the progress bar width
    pass_rate_str = run_payload["summary"].get("pass_rate", "0%")
    try:
        pass_rate_num = float(pass_rate_str.rstrip("%"))
    except ValueError:
        pass_rate_num = 0.0

    # Mask instance ID: show only last 8 characters
    raw_instance = run_payload.get("connect_instance_id", "")
    instance_suffix = raw_instance[-8:] if len(raw_instance) >= 8 else raw_instance

    zephyr_enabled = os.environ.get("ZEPHYR_ENABLED", "false").lower() == "true"

    html = template.render(
        theme=merged_theme,
        pass_rate_num=pass_rate_num,
        instance_suffix=instance_suffix,
        zephyr_updated="yes" if zephyr_enabled else "disabled",
        **run_payload,
    )

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(html)


def write_json_report(run_payload: dict, output_path: str) -> None:
    """Write *run_payload* as indented JSON to *output_path*."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(run_payload, fh, indent=2, default=str)


# ---------------------------------------------------------------------------
# Jinja2 filter
# ---------------------------------------------------------------------------


def _extract_key_filter(node_name: str) -> str:
    """
    Extract issue key from pytest node name.

    'test_chat_scenario[BANK-101]' → 'BANK-101'
    'BANK-101'                     → 'BANK-101'
    """
    if "[" in node_name and "]" in node_name:
        return node_name[node_name.index("[") + 1: node_name.rindex("]")]
    return node_name
