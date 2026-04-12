"""
test_connect_chat.py
====================
Pytest test module for Amazon Connect chat channel automation.

Each scenario defined in the scenarios/ directory becomes one parametrized
test case. The zephyr_issue_key from the YAML is used as the pytest node
ID suffix, enabling selective test execution:

    pytest -k BANK-101              # run one scenario
    pytest -k "BANK-101 or BANK-102"  # run two specific scenarios
    pytest                          # run all scenarios

Scenarios are loaded at collection time by conftest.pytest_configure
and stored on config._tradder_scenarios. No filesystem access happens
inside the test function itself.
"""

import os

import pytest

from test_executor import ScenarioResult, execute_scenario


# ---------------------------------------------------------------------------
# Dynamic parametrization from loaded scenarios
# ---------------------------------------------------------------------------


def pytest_generate_tests(metafunc):  # noqa: ANN001
    """
    Inject scenario dicts as parametrize parameters when the test function
    requests the 'scenario' fixture.

    Uses config._tradder_scenarios set by conftest.pytest_configure so
    scenarios are available at collection time without re-loading YAML files.
    """
    if "scenario" in metafunc.fixturenames:
        scenarios = getattr(metafunc.config, "_tradder_scenarios", [])
        if not scenarios:
            # No scenarios loaded — parametrize with empty list so pytest
            # reports "no tests ran" rather than a collection error.
            metafunc.parametrize("scenario", [], ids=[])
            return
        metafunc.parametrize(
            "scenario",
            scenarios,
            ids=[s["zephyr_issue_key"] for s in scenarios],
        )


# ---------------------------------------------------------------------------
# Test function
# ---------------------------------------------------------------------------


def test_chat_scenario(scenario, request):  # noqa: ANN001
    """
    Execute a single Amazon Connect chat scenario and assert all turns pass.

    The ScenarioResult is attached to the pytest item so that conftest's
    pytest_runtest_makereport hook can include per-turn detail in the
    reports and Zephyr write-back.
    """
    instance_id = os.environ.get("CONNECT_INSTANCE_ID", "")
    region = os.environ.get("AWS_REGION", "eu-west-2")

    if not instance_id:
        pytest.skip("CONNECT_INSTANCE_ID not set — skipping Connect chat tests.")

    result: ScenarioResult = execute_scenario(
        scenario=scenario,
        instance_id=instance_id,
        region=region,
        default_timeout=float(os.environ.get("CHAT_TIMEOUT_SECONDS", "10")),
        poll_interval=float(os.environ.get("CHAT_POLL_INTERVAL_SECONDS", "1")),
        max_poll_attempts=int(os.environ.get("CHAT_MAX_POLL_ATTEMPTS", "20")),
        chat_duration_minutes=int(os.environ.get("CHAT_DURATION_MINUTES", "5")),
    )

    # Attach to pytest item for conftest.pytest_runtest_makereport
    request.node._scenario_result = result

    # Fail the test if the scenario did not pass
    if result.overall_status != "PASSED":
        failed_turns = [
            f"  Turn {t.turn_index}: sent={t.sent!r} | "
            f"expected={t.expected} | got={t.actual!r} | [{t.status}]"
            + (f"\n    Error: {t.error_message}" if t.error_message else "")
            for t in result.turns
            if t.status != "PASS"
        ]
        pytest.fail(
            f"Scenario '{result.scenario_name}' [{result.zephyr_issue_key}] "
            f"{result.overall_status} after {result.duration_ms}ms\n"
            + "\n".join(failed_turns),
            pytrace=False,
        )
