"""
Zephyr Squad (ZAPI) client for writing test execution results back to Jira.

Zephyr Squad uses the Jira REST API extension:
  Base URL : {jira_base_url}/rest/zapi/latest/
  Auth     : HTTP Basic with Jira username + API token

Zephyr Squad execution status codes:
  -1 = UNEXECUTED
   1 = PASS
   2 = FAIL
   3 = WIP (Work In Progress)
   4 = BLOCKED

This module is only imported when ZEPHYR_ENABLED=true in the environment.
All Zephyr failures are non-fatal — tests still run and produce reports
regardless of Zephyr availability.
"""

import logging
import time
from typing import Optional

import requests
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)

# Mapping from pytest outcome strings to Zephyr status codes
OUTCOME_TO_ZEPHYR_STATUS: dict[str, int] = {
    "PASSED": 1,
    "FAILED": 2,
    "ERROR": 4,
    "SKIPPED": -1,
}


class ZephyrAPIError(RuntimeError):
    """Raised when a Zephyr ZAPI call fails after all retries."""

    def __init__(self, message: str, status_code: int, response_body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class ZephyrSquadClient:
    """
    Thin wrapper around Zephyr Squad's ZAPI REST API.

    Handles retries (exponential back-off) on 429 and 5xx responses.
    401 / 404 are not retried — they indicate configuration errors.
    """

    def __init__(
        self,
        jira_base_url: str,
        username: str,
        api_token: str,
        project_id: str,
        cycle_id: str,
        timeout: int = 30,
    ) -> None:
        self._base = jira_base_url.rstrip("/") + "/rest/zapi/latest"
        self._session = requests.Session()
        self._session.auth = HTTPBasicAuth(username, api_token)
        self._session.headers.update({"Content-Type": "application/json"})
        self.project_id = str(project_id)
        self.cycle_id = str(cycle_id)
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_executions_for_cycle(self) -> dict[str, int]:
        """
        Fetch all test executions in the configured cycle.

        Returns a mapping of {issueKey: executionId} so that
        pytest_sessionfinish can look up execution IDs by Zephyr issue key.
        """
        resp = self._request(
            "GET",
            f"/execution?cycleId={self.cycle_id}&projectId={self.project_id}",
        )
        data = resp.json()

        result: dict[str, int] = {}
        # ZAPI returns executions as a dict keyed by execution ID string
        for exec_id_str, exec_data in data.get("executions", {}).items():
            issue_key = exec_data.get("issueKey", "")
            if issue_key:
                result[issue_key] = int(exec_id_str)

        logger.info(
            "Fetched %d execution(s) from cycle %s (project %s)",
            len(result),
            self.cycle_id,
            self.project_id,
        )
        return result

    def update_execution(
        self,
        execution_id: int,
        status: int,
        comment: str,
        execution_time_ms: int,
    ) -> None:
        """
        Update the result of a specific test execution in Zephyr Squad.

        Args:
            execution_id:     The ZAPI execution ID (from get_executions_for_cycle).
            status:           Zephyr status code (1=PASS, 2=FAIL, 4=BLOCKED, -1=UNEXECUTED).
            comment:          Free-text comment (truncated to 1000 chars by ZAPI).
            execution_time_ms: Wall-clock test duration in milliseconds.
        """
        payload = {
            "status": str(status),
            "comment": comment[:1000],
            "executionTime": execution_time_ms,
        }
        self._request("PUT", f"/execution/{execution_id}/execute", json=payload)
        logger.info(
            "Updated execution %d → status %d (%s)",
            execution_id,
            status,
            _status_label(status),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        max_retries: int = 3,
        **kwargs,
    ) -> requests.Response:
        """
        Make an HTTP request with exponential back-off on transient failures.

        Raises ZephyrAPIError on permanent failure or after max_retries exhausted.
        """
        url = self._base + path
        delay = 1.0

        for attempt in range(1, max_retries + 1):
            try:
                resp = self._session.request(
                    method, url, timeout=self._timeout, **kwargs
                )
            except requests.RequestException as exc:
                logger.warning(
                    "Zephyr %s %s network error (attempt %d/%d): %s",
                    method, path, attempt, max_retries, exc,
                )
                if attempt == max_retries:
                    raise ZephyrAPIError(str(exc), status_code=0) from exc
                time.sleep(delay)
                delay *= 2
                continue

            # Transient server errors — retry
            if resp.status_code == 429 or resp.status_code >= 500:
                logger.warning(
                    "Zephyr %s %s → %d (attempt %d/%d), retrying in %.1fs",
                    method, path, resp.status_code, attempt, max_retries, delay,
                )
                if attempt == max_retries:
                    raise ZephyrAPIError(
                        f"{method} {path} failed with HTTP {resp.status_code}",
                        status_code=resp.status_code,
                        response_body=resp.text[:500],
                    )
                time.sleep(delay)
                delay *= 2
                continue

            # Permanent client errors — never retry
            if not resp.ok:
                raise ZephyrAPIError(
                    f"{method} {path} → HTTP {resp.status_code}: {resp.text[:200]}",
                    status_code=resp.status_code,
                    response_body=resp.text[:500],
                )

            logger.debug("%s %s → %d", method, path, resp.status_code)
            return resp

        # Should be unreachable, but satisfies type-checkers
        raise ZephyrAPIError("Max retries exceeded", status_code=0)


def _status_label(code: int) -> str:
    return {1: "PASS", 2: "FAIL", 3: "WIP", 4: "BLOCKED", -1: "UNEXECUTED"}.get(
        code, str(code)
    )
