"""
judge/agentcore_evaluators.py
=============================
Wrapper around the Amazon Bedrock AgentCore CreateEvaluator API.

Use this to register the evaluator_configs/*.json definitions as custom
AgentCore evaluators so they can also be used in AgentCore's native
online/on-demand evaluation pipelines for any AgentCore-deployed agents.

Note: ARIA itself is a Connect AI Agent (not AgentCore-deployed), so these
registrations are optional — the LLM judge in llm_judge.py is the primary
evaluation path. However, registering them allows use with any future
AgentCore-deployed agent in the same account.

Usage::

    python scripts/register_evaluators.py
"""

import json
import logging
from pathlib import Path
from typing import Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Evaluation level mapping: dimension ID → AgentCore level
LEVEL_MAP = {
    "TRACE": "TRACE",
    "SESSION": "SESSION",
    "TOOL_CALL": "TOOL_CALL",
}


class AgentCoreEvaluatorRegistry:
    """
    Registers and manages AgentCore custom evaluators.

    Usage::

        registry = AgentCoreEvaluatorRegistry(region="eu-west-2", account_id="123456789012")
        results = registry.register_all(configs_dir="evaluator_configs/")
    """

    def __init__(self, region: str = "eu-west-2", account_id: str = "") -> None:
        self.region = region
        self.account_id = account_id
        # AgentCore uses the bedrock-agentcore client
        self._client = boto3.client("bedrock-agentcore", region_name=region)

    def register_all(self, configs_dir: str = "evaluator_configs") -> list[dict]:
        """
        Walk the configs_dir and register every *.json file as an AgentCore evaluator.

        Returns a list of registration results:
          [{"file": "...", "name": "...", "evaluator_id": "...", "status": "created"|"error"}]
        """
        configs_path = Path(configs_dir)
        results = []

        for json_file in sorted(configs_path.rglob("*.json")):
            result = self._register_from_file(json_file)
            results.append(result)
            status = result["status"]
            logger.info(
                "[%s] %s → %s",
                "✓" if status == "created" else "✗",
                json_file.name,
                result.get("evaluator_id", result.get("error")),
            )

        return results

    def register_one(self, name: str, config: dict, level: str) -> dict:
        """Register a single evaluator config with AgentCore."""
        try:
            resp = self._client.create_evaluator(
                name=name,
                evaluatorConfiguration=config,
                evaluationLevel=level,
            )
            return {
                "name": name,
                "evaluator_id": resp.get("evaluatorId"),
                "evaluator_arn": resp.get("evaluatorArn"),
                "status": "created",
            }
        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            if error_code == "ConflictException":
                logger.info("Evaluator '%s' already exists — skipping.", name)
                return {"name": name, "status": "already_exists"}
            return {"name": name, "status": "error", "error": str(exc)}

    def list_evaluators(self) -> list[dict]:
        """List all custom evaluators registered in this account/region."""
        evaluators = []
        next_token = None

        while True:
            kwargs = {}
            if next_token:
                kwargs["nextToken"] = next_token
            try:
                resp = self._client.list_evaluators(**kwargs)
            except ClientError as exc:
                logger.error("list_evaluators failed: %s", exc)
                break

            evaluators.extend(resp.get("evaluators", []))
            next_token = resp.get("nextToken")
            if not next_token:
                break

        return evaluators

    def delete_evaluator(self, evaluator_id: str) -> bool:
        """Delete a registered evaluator by ID."""
        try:
            self._client.delete_evaluator(evaluatorId=evaluator_id)
            return True
        except ClientError as exc:
            logger.error("delete_evaluator failed for %s: %s", evaluator_id, exc)
            return False

    # ── Private ─────────────────────────────────────────────────────────────

    def _register_from_file(self, json_file: Path) -> dict:
        try:
            with json_file.open() as fh:
                config_data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            return {"file": str(json_file), "status": "error", "error": str(exc)}

        # Extract metadata from the config envelope
        name = config_data.get("name", json_file.stem.replace("_", "-"))
        level = config_data.get("evaluationLevel", "TRACE")
        evaluator_config = config_data.get("config", config_data)

        result = self.register_one(name=name, config=evaluator_config, level=level)
        result["file"] = str(json_file)
        return result
