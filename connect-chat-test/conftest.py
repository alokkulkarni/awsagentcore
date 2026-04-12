"""
conftest.py — pytest configuration and hooks for the Amazon Connect chat test suite.

Responsibilities:
  1. Load scenario YAML files early (pytest_configure) so pytest_generate_tests
     can parametrize the test function at collection time.
  2. Initialise the Zephyr Squad client (if ZEPHYR_ENABLED=true).
  3. Collect per-test pass/fail results via pytest_runtest_makereport.
  4. On session finish: write JSON + HTML reports and update Zephyr executions.

Pattern mirrors amazon_connect_testing/lambda_testing/conftest.py from the
automationTesting project — see that file for the original design reference.
"""

import json
import logging
import os
import warnings
from datetime import datetime, timezone
from typing import Optional

import pytest
from dotenv import load_dotenv

from report_generator import write_html_report, write_json_report
from test_executor import ScenarioResult, load_scenarios

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

load_dotenv()  # reads .env if present; env vars from CI override silently

logger = logging.getLogger(__name__)

_HERE = os.path.dirname(os.path.abspath(__file__))
REPORT_DIR = os.path.join(_HERE, os.environ.get("REPORT_OUTPUT_DIR", "reports"))

# ---------------------------------------------------------------------------
# Module-level singletons (set in pytest_configure, used in sessionfinish)
# ---------------------------------------------------------------------------

_zephyr_client = None          # ZephyrSquadClient | None
_zephyr_execution_map: Optional[dict[str, int]] = None


# ---------------------------------------------------------------------------
# pytest_configure — runs before collection
# ---------------------------------------------------------------------------


def pytest_configure(config) -> None:  # noqa: ANN001
    os.makedirs(REPORT_DIR, exist_ok=True)

    # Load scenarios early so pytest_generate_tests can parametrize
    scenarios_dir = os.environ.get("SCENARIOS_DIR", "scenarios")
    try:
        config._tradder_scenarios = load_scenarios(scenarios_dir)
    except Exception as exc:  # noqa: BLE001
        config._tradder_scenarios = []
        warnings.warn(f"Failed to load scenarios from '{scenarios_dir}': {exc}")

    # Initialise Zephyr client if enabled
    _maybe_init_zephyr()


def _maybe_init_zephyr() -> None:
    """Attempt to initialise the Zephyr Squad client from environment variables."""
    global _zephyr_client, _zephyr_execution_map  # noqa: PLW0603

    if os.environ.get("ZEPHYR_ENABLED", "false").lower() != "true":
        logger.info("Zephyr integration disabled (ZEPHYR_ENABLED != true).")
        return

    required = ("JIRA_BASE_URL", "JIRA_USERNAME", "JIRA_API_TOKEN",
                "JIRA_PROJECT_ID", "ZEPHYR_CYCLE_ID")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        warnings.warn(
            f"Zephyr enabled but missing env vars: {missing}. "
            "Zephyr reporting disabled."
        )
        return

    try:
        from zephyr_client import ZephyrSquadClient  # noqa: PLC0415

        _zephyr_client = ZephyrSquadClient(
            jira_base_url=os.environ["JIRA_BASE_URL"],
            username=os.environ["JIRA_USERNAME"],
            api_token=os.environ["JIRA_API_TOKEN"],
            project_id=os.environ["JIRA_PROJECT_ID"],
            cycle_id=os.environ["ZEPHYR_CYCLE_ID"],
        )
        _zephyr_execution_map = _zephyr_client.get_executions_for_cycle()
        logger.info(
            "Zephyr client ready. %d execution(s) in cycle.",
            len(_zephyr_execution_map),
        )
    except Exception as exc:  # noqa: BLE001
        warnings.warn(
            f"Zephyr client init failed: {exc}. "
            "Tests will still run; Zephyr reporting disabled."
        )
        _zephyr_client = None
        _zephyr_execution_map = None


# ---------------------------------------------------------------------------
# Result collector (same pattern as lambda_testing/conftest.py)
# ---------------------------------------------------------------------------


class _ResultCollector:
    def __init__(self) -> None:
        self.results: list[dict] = []

    def record(
        self,
        name: str,
        outcome: str,
        duration_s: float,
        scenario_result: Optional[ScenarioResult] = None,
        error: Optional[str] = None,
    ) -> None:
        self.results.append(
            {
                "name": name,
                "scenario_name": scenario_result.scenario_name if scenario_result else name,
                "outcome": outcome,
                "duration_s": round(duration_s, 3),
                "error": error,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "zephyr_execution_id": (
                    scenario_result.zephyr_execution_id if scenario_result else None
                ),
                "turns": (
                    [
                        {
                            "turn_index": t.turn_index,
                            "sent": t.sent,
                            "expected": t.expected,
                            "actual": t.actual,
                            "status": t.status,
                            "duration_ms": t.duration_ms,
                            "error_message": t.error_message,
                        }
                        for t in scenario_result.turns
                    ]
                    if scenario_result
                    else []
                ),
            }
        )


_collector = _ResultCollector()


# ---------------------------------------------------------------------------
# pytest_runtest_makereport — capture per-test outcome
# ---------------------------------------------------------------------------


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):  # noqa: ANN001
    outcome = yield
    report = outcome.get_result()

    # Capture at the "call" phase (or "setup" if setup itself failed)
    if report.when == "call" or (report.when == "setup" and report.failed):
        if report.failed:
            status = "FAILED"
            error_text = str(report.longrepr) if report.longrepr else None
        elif report.skipped:
            status = "SKIPPED"
            error_text = str(report.longrepr) if report.longrepr else None
        else:
            status = "PASSED"
            error_text = None

        # Retrieve the ScenarioResult if the test function attached it
        scenario_result: Optional[ScenarioResult] = getattr(
            item, "_scenario_result", None
        )

        _collector.record(
            name=item.name,
            outcome=status,
            duration_s=report.duration,
            scenario_result=scenario_result,
            error=error_text,
        )


# ---------------------------------------------------------------------------
# pytest_sessionfinish — reports + Zephyr write-back
# ---------------------------------------------------------------------------


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ANN001
    results = _collector.results
    if not results:
        return

    passed = sum(1 for r in results if r["outcome"] == "PASSED")
    failed = sum(1 for r in results if r["outcome"] == "FAILED")
    skipped = sum(1 for r in results if r["outcome"] == "SKIPPED")
    errored = sum(1 for r in results if r["outcome"] == "ERROR")
    total = len(results)
    pass_rate = f"{(passed / total * 100):.1f}%" if total else "0%"

    run_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_number": os.environ.get("GITHUB_RUN_NUMBER", "local"),
        "aws_region": os.environ.get("AWS_REGION", ""),
        "connect_instance_id": os.environ.get("CONNECT_INSTANCE_ID", ""),
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "errored": errored,
            "pass_rate": pass_rate,
        },
        "test_cases": results,
    }

    # JSON report
    json_path = os.path.join(REPORT_DIR, "chat_test_report.json")
    write_json_report(run_payload, json_path)

    # HTML report
    html_path = os.path.join(REPORT_DIR, "chat_test_report.html")
    try:
        write_html_report(run_payload, html_path)
    except Exception as exc:  # noqa: BLE001
        warnings.warn(f"HTML report generation failed: {exc}")

    # Zephyr write-back (non-fatal)
    _write_back_to_zephyr(results)

    # Console summary table (same format as lambda_testing/conftest.py)
    _print_console_table(results, passed, failed, skipped, errored, total,
                         json_path, html_path)


def _write_back_to_zephyr(results: list[dict]) -> None:
    """Push execution statuses to Zephyr Squad. Failures are non-fatal."""
    if _zephyr_client is None or _zephyr_execution_map is None:
        return

    from zephyr_client import OUTCOME_TO_ZEPHYR_STATUS, ZephyrAPIError  # noqa: PLC0415

    for result in results:
        # Test node IDs look like "test_chat_scenario[BANK-101]" — extract the key
        issue_key = _extract_issue_key(result["name"])
        if not issue_key:
            continue

        execution_id = _zephyr_execution_map.get(issue_key)
        if execution_id is None:
            logger.warning(
                "No Zephyr execution found for '%s' in cycle %s — skipping.",
                issue_key,
                _zephyr_client.cycle_id,
            )
            continue

        status_code = OUTCOME_TO_ZEPHYR_STATUS.get(result["outcome"], -1)
        comment = _build_zephyr_comment(result)
        execution_time_ms = int(result["duration_s"] * 1000)

        try:
            _zephyr_client.update_execution(
                execution_id=execution_id,
                status=status_code,
                comment=comment,
                execution_time_ms=execution_time_ms,
            )
        except ZephyrAPIError as exc:
            logger.warning(
                "Zephyr update failed for %s (exec %d): %s",
                issue_key, execution_id, exc,
            )


def _extract_issue_key(node_name: str) -> Optional[str]:
    """
    Extract the Zephyr issue key from a pytest node ID.

    E.g. 'test_chat_scenario[BANK-101]' → 'BANK-101'
    """
    if "[" in node_name and "]" in node_name:
        return node_name[node_name.index("[") + 1: node_name.rindex("]")]
    return None


def _build_zephyr_comment(result: dict) -> str:
    """Build a human-readable Zephyr comment from turn results."""
    lines = [f"Automated run #{os.environ.get('GITHUB_RUN_NUMBER', 'local')}"]
    for turn in result.get("turns", []):
        expected_str = ", ".join(f"'{e}'" for e in turn.get("expected", []))
        actual_str = turn.get("actual") or "TIMEOUT"
        status_str = turn.get("status", "?")
        lines.append(
            f"  Turn {turn['turn_index']}: sent={turn['sent']!r} | "
            f"expected=[{expected_str}] | got={actual_str!r} | {status_str}"
        )
    if result.get("error"):
        lines.append(f"Error: {result['error'][:300]}")
    return "\n".join(lines)


def _print_console_table(
    results: list[dict],
    passed: int,
    failed: int,
    skipped: int,
    errored: int,
    total: int,
    json_path: str,
    html_path: str,
) -> None:
    width = 78
    print("\n" + "=" * width)
    print("  AMAZON CONNECT CHAT TEST REPORT")
    print("=" * width)
    print(f"  {'Test Case':<50} {'Result':<10} {'Duration'}")
    print("-" * width)
    for r in results:
        icon = {
            "PASSED": "PASS",
            "FAILED": "FAIL",
            "SKIPPED": "SKIP",
            "ERROR": "ERRO",
        }.get(r["outcome"], "????")
        name = r["name"]
        if len(name) > 48:
            name = name[:45] + "..."
        print(f"  [{icon}]  {name:<48} {r['duration_s']:>6.2f}s")
    print("-" * width)
    print(
        f"  Total: {total}  |  Passed: {passed}  |  Failed: {failed}  |  "
        f"Skipped: {skipped}  |  Errored: {errored}"
    )
    print("=" * width)
    print(f"  JSON  : {json_path}")
    print(f"  HTML  : {html_path}")
    if _zephyr_client:
        print(f"  Zephyr: cycle {_zephyr_client.cycle_id} updated")
    print("=" * width + "\n")
