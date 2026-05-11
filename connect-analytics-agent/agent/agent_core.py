import asyncio
import importlib.util
import json
import logging
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s – %(message)s")
LOGGER = logging.getLogger(__name__)

SESSION_HISTORY: Dict[str, List[Dict[str, str]]] = defaultdict(list)

# Maps the tool_name used in requests to the tools/ subdirectory name.
_TOOL_DIR_MAP: Dict[str, str] = {
    "get_realtime_metrics": "realtime_metrics",
    "get_historical_metrics": "historical_metrics",
    "get_agent_states": "agent_states",
    "search_contacts": "search_contacts",
    "get_contact_detail": "contact_detail",
    "get_transcript": "transcript",
    "keyword_search": "keyword_search",
    "get_recording_url": "recording_url",
    "get_bot_metrics": "bot_metrics",
}


class LocalToolInvoker:
    """Calls tool lambda_handler functions directly (in-process) — no Lambda infra required.

    The tools/ directory is mounted into the agent container at /app/tools.
    Each tool follows the standard AgentCore Lambda payload contract, so we can
    build the same event dict and call lambda_handler(event, None) directly.
    """

    def __init__(self, tools_root: Optional[str] = None) -> None:
        self._tools_root = Path(tools_root or os.getenv("TOOLS_ROOT", "/app/tools"))
        self._handlers: Dict[str, Any] = {}
        self._available: bool = self._tools_root.is_dir()

    @property
    def available(self) -> bool:
        return self._available

    def _load_handler(self, tool_name: str) -> Any:
        if tool_name in self._handlers:
            return self._handlers[tool_name]

        subdir = _TOOL_DIR_MAP.get(tool_name)
        if not subdir:
            raise ValueError(f"Unknown local tool: '{tool_name}'")

        handler_path = (self._tools_root / subdir / "handler.py").resolve()

        # Guard against path traversal: resolved path must be inside tools_root
        tools_root_resolved = self._tools_root.resolve()
        try:
            handler_path.relative_to(tools_root_resolved)
        except ValueError as exc:
            raise PermissionError(
                f"Security: handler path '{handler_path}' is outside tools root '{tools_root_resolved}'"
            ) from exc

        if not handler_path.exists():
            raise FileNotFoundError(f"Tool handler not found at: {handler_path}")

        # Ensure shared/ utilities are importable from tools root.
        tools_root_str = str(self._tools_root)
        if tools_root_str not in sys.path:
            sys.path.insert(0, tools_root_str)

        spec = importlib.util.spec_from_file_location(f"tool_{subdir}", handler_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load spec for {handler_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        self._handlers[tool_name] = module.lambda_handler
        return module.lambda_handler

    def invoke(self, tool_name: str, payload: Dict[str, Any]) -> str:
        handler = self._load_handler(tool_name)
        result = handler(payload, None)
        body = (
            result.get("response", {})
            .get("functionResponse", {})
            .get("responseBody", {})
            .get("TEXT", {})
            .get("body")
        )
        if not body:
            return json.dumps(result, indent=2, default=str)
        try:
            return json.dumps(json.loads(body), indent=2, default=str)
        except json.JSONDecodeError:
            return body


class ConnectAnalyticsAgent:
    def __init__(self):
        self.gateway_endpoint = os.getenv("AGENTCORE_GATEWAY_ENDPOINT", "").strip()
        self.model_id = os.getenv("BEDROCK_MODEL_ID", "eu.anthropic.claude-sonnet-4-6")
        self.region_name = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
        self.instance_id = os.getenv("CONNECT_INSTANCE_ID", "")
        self.direct_tool_lambdas = self._load_direct_tool_lambdas()
        self.lambda_client = boto3.client("lambda", region_name=self.region_name)
        self.local_tools = LocalToolInvoker()

    def _load_direct_tool_lambdas(self) -> Dict[str, str]:
        raw = os.getenv("DIRECT_TOOL_LAMBDAS", "{}")
        try:
            loaded = json.loads(raw)
            return loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _system_prompt(self) -> str:
        return (
            "You are an Amazon Connect analytics assistant. You help contact center managers and supervisors "
            "query real-time and historical data about their Amazon Connect contact center.\n\n"
            "You have access to tools that can:\n"
            "- Get real-time agent states (who is busy, available, on a call, etc.)\n"
            "- Get real-time queue metrics (queue depth, oldest contact, etc.)\n"
            "- Get historical performance metrics (handle times, contacts handled, abandonment rates)\n"
            "- Search contact records (CTRs) by various filters\n"
            "- Get detailed information about specific contacts\n"
            "- Retrieve call transcripts (requires Contact Lens to be enabled)\n"
            "- Search calls by keywords in transcripts\n"
            "- Generate links to call recordings\n\n"
            "When answering questions:\n"
            "- Always present data in a clear, readable format\n"
            "- For busiest agent queries, sort by contacts handled or time on calls\n"
            "- For time-based queries without explicit dates, default to today\n"
            "- Format durations as HH:MM:SS\n"
            "- Explain Contact Lens limitations clearly\n\n"
            f"The Amazon Connect instance ID to use is: {self.instance_id or 'not-configured'}"
        )

    def _signed_headers(self, url: str) -> Dict[str, str]:
        session = boto3.session.Session(region_name=self.region_name)
        credentials = session.get_credentials()
        if credentials is None:
            raise RuntimeError("AWS credentials are required to connect to AgentCore Gateway.")
        frozen = credentials.get_frozen_credentials()
        request = AWSRequest(method="GET", url=url)
        SigV4Auth(frozen, "bedrock-agentcore", self.region_name).add_auth(request)
        return dict(request.headers.items())

    def _history_block(self, session_id: Optional[str]) -> str:
        if not session_id or not SESSION_HISTORY.get(session_id):
            return ""
        messages = SESSION_HISTORY[session_id][-8:]
        rendered = []
        for item in messages:
            rendered.append(f"{item['role'].upper()}: {item['content']}")
        return "Conversation history:\n" + "\n".join(rendered) + "\n\n"

    def _remember(self, session_id: Optional[str], role: str, content: str) -> None:
        if not session_id:
            return
        SESSION_HISTORY[session_id].append({"role": role, "content": content})
        SESSION_HISTORY[session_id] = SESSION_HISTORY[session_id][-12:]

    @staticmethod
    def _clean_response(text: str) -> str:
        """Remove empty bullet points and standalone warning symbols that Bedrock sometimes emits."""
        import re as _re
        lines = text.splitlines()
        cleaned = []
        for line in lines:
            stripped = line.strip()
            # Drop lines that are purely empty bullets: "- ", "* ", "• "
            if _re.match(r'^[-*•]\s*$', stripped):
                continue
            # Drop lines that are only a warning/emoji symbol with no surrounding text
            if _re.match(r'^[⚠⚡‼❗❕⚠️]+\s*$', stripped):
                continue
            cleaned.append(line)
        # Collapse runs of 3+ blank lines down to 2
        result = _re.sub(r'\n{3,}', '\n\n', '\n'.join(cleaned))
        return result.strip()

    def _format_with_bedrock(self, question: str, tool_name: str, raw_result: str) -> str:
        """Pass raw tool JSON through Bedrock to produce a natural language answer."""
        region_prefix = self.region_name.split("-")[0]  # "eu", "us", "ap", etc.
        # Cross-region inference profiles are only valid in specific sub-regions.
        # Direct model IDs work everywhere the model is deployed.
        model_candidates = [
            # Latest Claude Sonnet 4.6 cross-region inference profile
            "eu.anthropic.claude-sonnet-4-6",
            # Env-configured model (user override, tried second)
            self.model_id,
            # Older cross-region inference profiles (eu-central-1/eu-west-1/eu-west-3 and us-east-1/us-west-2)
            f"{region_prefix}.anthropic.claude-3-5-sonnet-20241022-v2:0",
            f"{region_prefix}.anthropic.claude-3-5-haiku-20241022-v1:0",
            # Direct model IDs that work without inference profiles (e.g. eu-west-2)
            "anthropic.claude-3-7-sonnet-20250219-v1:0",
            "anthropic.claude-3-5-sonnet-20241022-v2:0",
            "anthropic.claude-3-5-haiku-20241022-v1:0",
            # Newer models requiring inference profiles — tried late as fallback
            "anthropic.claude-haiku-4-5-20251001-v1:0",
            "anthropic.claude-sonnet-4-5-20250929-v1:0",
            # Amazon Nova as final non-Anthropic fallback
            "amazon.nova-lite-v1:0",
        ]
        # Deduplicate preserving order
        seen: set = set()
        candidates = [m for m in model_candidates if not (m in seen or seen.add(m))]  # type: ignore[func-returns-value]

        if tool_name == "conversational":
            # Pure conversational fallback — no tool data involved.
            conv_context = raw_result.get("question", question) if isinstance(raw_result, dict) else question
            prompt = (
                f"{conv_context}\n\n"
                "You are a helpful Amazon Connect analytics assistant. "
                "Answer the question above clearly and concisely in Markdown. "
                "If the question is about data you cannot access right now, explain what data you "
                "can query (queue health, agent states, historical metrics, contact search/transcripts) "
                "and politely ask the user to rephrase.\n"
                "Keep the response under 200 words. Do NOT invent or hallucinate specific metric values."
            )
            bedrock = boto3.client("bedrock-runtime", region_name=self.region_name)
            tried: list = []
            for model_id in candidates:
                try:
                    response = bedrock.converse(
                        modelId=model_id,
                        messages=[{"role": "user", "content": [{"text": prompt}]}],
                        system=[{"text": self._system_prompt()}],
                    )
                    LOGGER.info("Conversational Bedrock fallback succeeded with model '%s'.", model_id)
                    return self._clean_response(response["output"]["message"]["content"][0]["text"])
                except Exception as exc:  # pylint: disable=broad-except
                    tried.append(f"{model_id} ({type(exc).__name__})")
            LOGGER.warning(
                "All %d Bedrock candidates failed for conversational fallback in %s. Tried: %s",
                len(tried), self.region_name, "; ".join(tried),
            )
            # All candidates exhausted — return a safe static reply
            return (
                "I'm sorry, I wasn't able to process that query right now. "
                "You can ask me about **queue health**, **agent states**, "
                "**historical metrics** (e.g. 'average handle time last 7 days'), "
                "or **search for contacts and transcripts**."
            )

        prompt = (
            f"A contact center supervisor asked: \"{question}\"\n\n"
            f"The Amazon Connect data tool '{tool_name}' returned:\n{raw_result}\n\n"
            "Respond in clear, well-structured Markdown that will be rendered in a chat UI.\n"
            "Rules:\n"
            "- Use a short bold heading for the main answer (e.g. **7 Agents Online — 0 Busy**)\n"
            "- Use bullet lists (- item) for per-agent or per-queue breakdowns, NOT pipe tables\n"
            "- Bold the metric value in each bullet (e.g. - BasicQueue: **1 available, 0 on call**)\n"
            "- Add a **Key Insights** section at the end with 1-3 actionable observations\n"
            "- Format all durations as HH:MM:SS\n"
            "- Keep the total response under 300 words\n"
            "- Do NOT use raw | table | syntax\n"
            "- If the data shows no results, explain clearly and suggest why\n"
            "- NEVER produce empty bullet points (a '- ' with no text after it)\n"
            "- NEVER use standalone warning symbols (⚠, ⚠️, !, ⚡) on their own line — write the note as plain text instead\n"
            "- If only one agent or queue has data, state that clearly in a sentence, do NOT generate placeholder empty bullets\n"
            "CHART RULE — if the tool data has 'is_time_series: true', you MUST append a chart block "
            "immediately after your analysis. The block must be valid JSON wrapped in a fenced code block "
            "tagged 'chart-json'. Format:\n"
            "```chart-json\n"
            "{\"title\": \"<chart title>\", \"series\": [\"<metric1>\", \"<metric2>\"], "
            "\"data\": [{\"label\": \"<label>\", \"<metric1>\": <number>, \"<metric2>\": <number>}, ...]}\n"
            "```\n"
            "Label rules: for DAY interval use 'Apr 23' / 'May 1' format. "
            "For HOUR interval use 24-hour 'HH:00' format (e.g. '08:00', '14:00'). "
            "Include ALL metric series from the results (e.g. both CONTACTS_HANDLED and AVG_HANDLE_TIME). "
            "Include every interval bucket from the results array as a data point. "
            "AVG_HANDLE_TIME values are raw seconds — include them as numbers, do NOT convert."
        )
        bedrock = boto3.client("bedrock-runtime", region_name=self.region_name)
        tried: list = []
        for model_id in candidates:
            try:
                response = bedrock.converse(
                    modelId=model_id,
                    messages=[{"role": "user", "content": [{"text": prompt}]}],
                    system=[{"text": self._system_prompt()}],
                )
                LOGGER.info("Bedrock formatting succeeded with model '%s'.", model_id)
                raw_text = response["output"]["message"]["content"][0]["text"]
                return self._clean_response(raw_text)
            except Exception as exc:  # pylint: disable=broad-except
                tried.append(f"{model_id} ({type(exc).__name__})")
        LOGGER.warning(
            "All %d Bedrock candidates failed for tool '%s' in %s. Tried: %s",
            len(tried), tool_name, self.region_name, "; ".join(tried),
        )
        return raw_result

    async def _query_via_gateway(self, message: str, session_id: Optional[str]) -> str:
        from mcp.client.sse import sse_client
        from strands import Agent
        from strands.models.bedrock import BedrockModel
        from strands.tools.mcp import MCPClient

        headers = self._signed_headers(self.gateway_endpoint)
        prompt = self._history_block(session_id) + message
        async with MCPClient(lambda: sse_client(self.gateway_endpoint, headers=headers)) as mcp_client:
            tools = await mcp_client.list_tools_async()
            model = BedrockModel(model_id=self.model_id, region_name=self.region_name)
            agent = Agent(model=model, tools=tools, system_prompt=self._system_prompt())
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(None, agent, prompt)
            text = str(response)
            self._remember(session_id, "user", message)
            self._remember(session_id, "assistant", text)
            return text

    def _parse_specific_date(self, message: str):
        """
        Try to parse a specific calendar date from the message, e.g. '24th april', 'april 24', '24 apr'.
        Returns (start_of_day, end_of_day) in UTC or None if no match.
        """
        lower = message.lower()
        now = datetime.now(timezone.utc)
        MONTHS = {
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
            'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
        }
        # Match "24th april", "24 apr", "april 24", "apr 24"
        m = re.search(
            r'(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*'
            r'|(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+(\d{1,2})(?:st|nd|rd|th)?',
            lower,
        )
        if not m:
            return None
        # Group 1+2 → "24 april" style; Group 3+4 → "april 24" style
        if m.group(1) and m.group(2):
            day, month_key = int(m.group(1)), m.group(2)[:3]
        else:
            day, month_key = int(m.group(4)), m.group(3)[:3]
        month_num = MONTHS.get(month_key)
        if not month_num:
            return None
        year = now.year if month_num <= now.month else now.year - 1
        try:
            day_start = datetime(year, month_num, day, 0, 0, 0, tzinfo=timezone.utc)
            day_end = datetime(year, month_num, day, 23, 59, 59, tzinfo=timezone.utc)
            return day_start, day_end
        except ValueError:
            return None

    def _parse_time_range(self, message: str):
        """
        Extract a (start_time, end_time) pair from natural-language phrases.
        Uses prefix matching so common typos like 'dasy', 'horus', 'weekss' still work.
        Falls back to the last hour when nothing matches.
        """
        lower = message.lower()
        now = datetime.now(timezone.utc)

        # Match "last N <unit>" or "past N <unit>" — capture the full unit word for flexible matching
        m = re.search(r'(?:last|past)\s+(\d+)\s+([a-z]+)', lower)
        if m:
            n = int(m.group(1))
            unit = m.group(2)
            # Prefix-based matching tolerates common typos (dasy, horus, weekss, etc.)
            if unit[:2] in ('mi',):         # minute / min
                return now - timedelta(minutes=n), now
            if unit[:2] in ('ho', 'hr'):    # hour / hr
                return now - timedelta(hours=n), now
            if unit[:2] in ('da',):         # day / days / dasy
                return now - timedelta(days=n), now
            if unit[:2] in ('we',):         # week / weeks
                return now - timedelta(weeks=n), now
            if unit[:2] in ('mo',):         # month / months
                return now - timedelta(days=n * 30), now

        if 'today' in lower:
            return now.replace(hour=0, minute=0, second=0, microsecond=0), now
        if 'this week' in lower:
            monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            return monday, now
        if 'this month' in lower:
            return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), now
        if 'yesterday' in lower:
            yesterday = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            return yesterday, yesterday.replace(hour=23, minute=59, second=59)

        # Specific date: "24th april", "april 24", etc.
        specific = self._parse_specific_date(message)
        if specific:
            return specific

        # Default: last hour
        return now - timedelta(hours=1), now

    def _resolve_date_from_history(self, session_id: Optional[str]) -> Optional[str]:
        """
        Scan the last few conversation turns for the most recently mentioned specific date.
        Returns a plain-text date string like "23rd April" that can be appended to a
        follow-up message so time-range resolution has context.
        """
        if not session_id:
            return None
        history = SESSION_HISTORY.get(session_id, [])
        # Walk backwards through the last 8 messages (most recent first), including assistant echoes.
        for item in reversed(history[-8:]):
            role = str(item.get("role", "")).lower()
            if role and role not in {"user", "assistant"}:
                continue
            content = item.get("content", "")
            if isinstance(content, str):
                candidates = [content]
            elif content:
                candidates = [str(content)]
            else:
                candidates = []
            for candidate in candidates:
                parsed = self._parse_specific_date(candidate)
                if parsed:
                    start_dt = parsed[0]
                    return start_dt.strftime("%-d %B %Y")
        return None

    def _build_routing_message(self, message: str, session_id: Optional[str]) -> str:
        """
        If the current message has no date reference, look back at conversation history
        and prepend the most recently discussed date so tool routing picks it up.
        Short follow-ups like 'hourly breakdown and agent performance' are augmented to
        'hourly breakdown and agent performance [date context: 23 April 2026]' for routing only.
        """
        # Only augment when the current message has no recognisable date
        if self._parse_specific_date(message) is not None:
            return message
        if re.search(r'(?:last|past)\s+\d+|today|yesterday|this week|this month', message.lower()):
            return message
        date_ctx = self._resolve_date_from_history(session_id)
        if date_ctx:
            LOGGER.info(
                "No date in current message — using history date context '%s' for routing.", date_ctx
            )
            return f"{message} [date context: {date_ctx}]"
        return message

    def _infer_tool_request(self, message: str) -> Optional[Dict[str, Any]]:
        lower = message.lower()
        now = datetime.now(timezone.utc)
        start, end = self._parse_time_range(message)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        instance_param = [{"name": "instance_id", "type": "string", "value": self.instance_id}] if self.instance_id else []

        def with_time(tool_name: str, extra: List[Dict[str, Any]]) -> Dict[str, Any]:
            return {
                "tool_name": tool_name,
                "payload": {
                    "actionGroup": "ConnectAnalyticsTools",
                    "function": tool_name,
                    "parameters": instance_param + extra,
                },
            }

        has_time_range = bool(
            re.search(r'(?:last|past)\s+\d+|today|yesterday|this week|this month', lower)
            or self._parse_specific_date(message) is not None
            or "[date context:" in lower  # injected by _build_routing_message for follow-ups
        )
        peak_intent = any(term in lower for term in [
            "peak", "most busy", "busiest time", "when.*busy", "time period", "trend",
            "over the last", "over last", "in last", "in the last", "graphical", "chart",
        ])

        # If a time range is given and query is about activity trends/peaks → historical with DAY interval
        if has_time_range and (peak_intent or any(t in lower for t in ["busy", "active", "volume"])):
            interval = "DAY" if (end - start).days > 2 else "HOUR"
            return with_time(
                "get_historical_metrics",
                [
                    {"name": "start_time", "type": "string", "value": start.isoformat()},
                    {"name": "end_time", "type": "string", "value": end.isoformat()},
                    {"name": "group_by", "type": "string", "value": "QUEUE"},
                    {"name": "interval", "type": "string", "value": interval},
                    {"name": "metrics", "type": "string", "value": "CONTACTS_HANDLED,AVG_HANDLE_TIME"},
                ],
            )

        # Current-state queries (no time range) → real-time snapshot
        if any(term in lower for term in ["busy", "available", "agent state", "who is online", "right now", "currently"]):
            return with_time("get_realtime_metrics", [])
        if "busiest agent" in lower:
            # Default to today for busiest-agent unless user specified a range
            q_start, q_end = self._parse_time_range(message) if re.search(r'last\s+\d+|yesterday|this week|this month', lower) else (start_of_day, now)
            return with_time(
                "get_historical_metrics",
                [
                    {"name": "start_time", "type": "string", "value": q_start.isoformat()},
                    {"name": "end_time", "type": "string", "value": q_end.isoformat()},
                    {"name": "group_by", "type": "string", "value": "AGENT"},
                    {"name": "metrics", "type": "string", "value": "CONTACTS_HANDLED,AVG_HANDLE_TIME"},
                ],
            )
        # Per-agent breakdown: "breakdown by agent", "per agent", "by agent", "each agent",
        # "agent performance", "how many agents", "which agents", "agent count"
        agent_breakdown = any(term in lower for term in [
            "per agent", "by agent", "breakdown", "each agent", "agent performance",
            "agent handled", "agents handled", "agent activity",
            "how many agent", "which agent", "one agent", "agent count",
        ])
        # "hourly breakdown" — follow-up requesting hour-by-hour data for a previously given date
        hourly_intent = any(term in lower for term in [
            "hourly breakdown", "hourly", "hour by hour", "by hour", "per hour",
            "hour breakdown", "time breakdown",
        ])
        if agent_breakdown and hourly_intent:
            return with_time(
                "get_historical_metrics",
                [
                    {"name": "start_time", "type": "string", "value": start.isoformat()},
                    {"name": "end_time", "type": "string", "value": end.isoformat()},
                    {"name": "group_by", "type": "string", "value": "AGENT"},
                    {"name": "interval", "type": "string", "value": "HOUR"},
                    {"name": "metrics", "type": "string", "value": "CONTACTS_HANDLED,AVG_HANDLE_TIME"},
                ],
            )
        if agent_breakdown:
            return with_time(
                "get_historical_metrics",
                [
                    {"name": "start_time", "type": "string", "value": start.isoformat()},
                    {"name": "end_time", "type": "string", "value": end.isoformat()},
                    {"name": "group_by", "type": "string", "value": "AGENT"},
                    {"name": "metrics", "type": "string", "value": "CONTACTS_HANDLED,AVG_HANDLE_TIME"},
                ],
            )
        if hourly_intent:
            return with_time(
                "get_historical_metrics",
                [
                    {"name": "start_time", "type": "string", "value": start.isoformat()},
                    {"name": "end_time", "type": "string", "value": end.isoformat()},
                    {"name": "group_by", "type": "string", "value": "QUEUE"},
                    {"name": "interval", "type": "string", "value": "HOUR"},
                    {"name": "metrics", "type": "string", "value": "CONTACTS_HANDLED,AVG_HANDLE_TIME"},
                ],
            )
        # Agent state / occupancy history
        agent_state_history = any(term in lower for term in [
            "agent state", "state change", "state history", "agent status history",
            "occupancy", "idle time", "online time", "non-productive", "time in state",
            "how long", "availability", "staffed", "scheduled",
        ])
        if agent_state_history and has_time_range:
            return with_time(
                "get_historical_metrics",
                [
                    {"name": "start_time", "type": "string", "value": start.isoformat()},
                    {"name": "end_time", "type": "string", "value": end.isoformat()},
                    {"name": "group_by", "type": "string", "value": "AGENT"},
                    {"name": "intent", "type": "string", "value": "agent_state"},
                    {"name": "metrics", "type": "string", "value": "AGENT_OCCUPANCY,SUM_ONLINE_TIME_AGENT,SUM_IDLE_TIME_AGENT,SUM_NON_PRODUCTIVE_TIME_AGENT,SUM_CONTACT_TIME_AGENT,SUM_AFTER_CONTACT_WORK_TIME,CONTACTS_HANDLED,CONTACTS_MISSED"},
                ],
            )

        # Transfer-related queries
        if any(term in lower for term in ["transfer", "transferred", "warm transfer", "cold transfer"]):
            return with_time(
                "get_historical_metrics",
                [
                    {"name": "start_time", "type": "string", "value": start.isoformat()},
                    {"name": "end_time", "type": "string", "value": end.isoformat()},
                    {"name": "group_by", "type": "string", "value": "QUEUE"},
                    {"name": "intent", "type": "string", "value": "transfer"},
                    {"name": "metrics", "type": "string", "value": "CONTACTS_TRANSFERRED_IN,CONTACTS_TRANSFERRED_OUT,CONTACTS_TRANSFERRED_IN_FROM_QUEUE,CONTACTS_TRANSFERRED_OUT_FROM_QUEUE,CONTACTS_TRANSFERRED_IN_BY_AGENT,CONTACTS_TRANSFERRED_OUT_BY_AGENT,CONTACTS_HANDLED"},
                ],
            )

        # Hold-related queries
        if any(term in lower for term in ["hold time", "on hold", "hold abandon", "placed on hold"]):
            return with_time(
                "get_historical_metrics",
                [
                    {"name": "start_time", "type": "string", "value": start.isoformat()},
                    {"name": "end_time", "type": "string", "value": end.isoformat()},
                    {"name": "group_by", "type": "string", "value": "QUEUE"},
                    {"name": "intent", "type": "string", "value": "hold"},
                    {"name": "metrics", "type": "string", "value": "CONTACTS_ON_HOLD,CONTACTS_HOLD_ABANDONS,AVG_HOLD_TIME,AVG_HOLD_TIME_ALL_CONTACTS,SUM_HOLD_TIME"},
                ],
            )

        # Talk time / silence / non-talk queries
        if any(term in lower for term in ["talk time", "silence", "non-talk", "speaking", "customer talk"]):
            return with_time(
                "get_historical_metrics",
                [
                    {"name": "start_time", "type": "string", "value": start.isoformat()},
                    {"name": "end_time", "type": "string", "value": end.isoformat()},
                    {"name": "group_by", "type": "string", "value": "AGENT"},
                    {"name": "intent", "type": "string", "value": "talk_time"},
                    {"name": "metrics", "type": "string", "value": "AVG_TALK_TIME,SUM_TALK_TIME,PERCENT_TALK_TIME_AGENT,PERCENT_TALK_TIME_CUSTOMER,PERCENT_NON_TALK_TIME,AVG_INTERRUPTIONS_TIME"},
                ],
            )

        # Service level / SLA queries
        if any(term in lower for term in ["service level", "sla", "slo", "within 20", "answered within"]):
            return with_time(
                "get_historical_metrics",
                [
                    {"name": "start_time", "type": "string", "value": start.isoformat()},
                    {"name": "end_time", "type": "string", "value": end.isoformat()},
                    {"name": "group_by", "type": "string", "value": "QUEUE"},
                    {"name": "intent", "type": "string", "value": "queue_health"},
                    {"name": "metrics", "type": "string", "value": "SERVICE_LEVEL,AVG_QUEUE_ANSWER_TIME,CONTACTS_HANDLED,CONTACTS_ABANDONED,ABANDONMENT_RATE,MAX_QUEUED_TIME"},
                ],
            )

        # Agent answer rate / missed contacts
        if any(term in lower for term in ["missed", "not answered", "answer rate", "declined", "non-response", "non response"]):
            return with_time(
                "get_historical_metrics",
                [
                    {"name": "start_time", "type": "string", "value": start.isoformat()},
                    {"name": "end_time", "type": "string", "value": end.isoformat()},
                    {"name": "group_by", "type": "string", "value": "AGENT"},
                    {"name": "intent", "type": "string", "value": "agent_performance"},
                    {"name": "metrics", "type": "string", "value": "CONTACTS_MISSED,AGENT_NON_RESPONSE,AGENT_ANSWER_RATE,CONTACTS_HANDLED,AGENT_OCCUPANCY"},
                ],
            )

        # Routing profile performance
        if any(term in lower for term in ["routing profile", "skill group", "team performance"]):
            return with_time(
                "get_historical_metrics",
                [
                    {"name": "start_time", "type": "string", "value": start.isoformat()},
                    {"name": "end_time", "type": "string", "value": end.isoformat()},
                    {"name": "group_by", "type": "string", "value": "ROUTING_PROFILE"},
                    {"name": "intent", "type": "string", "value": "agent_performance"},
                    {"name": "metrics", "type": "string", "value": "CONTACTS_HANDLED,AVG_HANDLE_TIME,AGENT_OCCUPANCY,CONTACTS_ABANDONED,AVG_QUEUE_ANSWER_TIME,CONTACTS_MISSED"},
                ],
            )
        if "abandoned" in lower:
            return with_time(
                "get_historical_metrics",
                [
                    {"name": "start_time", "type": "string", "value": start.isoformat()},
                    {"name": "end_time", "type": "string", "value": end.isoformat()},
                    {"name": "group_by", "type": "string", "value": "QUEUE"},
                    {"name": "metrics", "type": "string", "value": "CONTACTS_ABANDONED"},
                ],
            )
        if any(term in lower for term in [
            "handle time", "handling time", "avg handle", "average handle",
            "average handling", "contacts handled", "historical", "metrics",
            "acw", "after contact", "queue time", "wait time",
        ]):
            return with_time(
                "get_historical_metrics",
                [
                    {"name": "start_time", "type": "string", "value": start.isoformat()},
                    {"name": "end_time", "type": "string", "value": end.isoformat()},
                    {"name": "group_by", "type": "string", "value": "QUEUE"},
                    {"name": "metrics", "type": "string", "value": "CONTACTS_HANDLED,AVG_HANDLE_TIME,CONTACTS_ABANDONED"},
                ],
            )
        if "transcript" in lower and "contact" in lower:
            contact_id = message.split()[-1].strip()
            return with_time("get_transcript", [{"name": "contact_id", "type": "string", "value": contact_id}])
        if any(term in lower for term in ["recording", "playback"]):
            contact_id = message.split()[-1].strip()
            return with_time("get_recording_url", [{"name": "contact_id", "type": "string", "value": contact_id}])

        # ── Bot / conversational AI queries ────────────────────────────────────
        bot_intent = any(term in lower for term in [
            "bot", "lex", "chatbot", "virtual agent", "ivr bot", "conversational ai",
            "conversational bot", "ai bot", "automated agent", "intent",
        ])
        flow_intent = any(term in lower for term in [
            "flow", "contact flow", "ivr", "inbound flow", "outbound flow",
            "flow metric", "flow performance", "flow outcome",
        ])
        bot_inventory_only = any(term in lower for term in [
            "list bot", "list lex", "which bot", "what bot", "configured bot",
            "bots configured", "bots associated", "how many bot",
        ])

        if bot_inventory_only and (bot_intent or flow_intent):
            return with_time(
                "get_bot_metrics",
                [{"name": "query_type", "type": "string", "value": "inventory"}],
            )

        if bot_intent and flow_intent:
            # Both bot and flow — return all
            return with_time(
                "get_bot_metrics",
                [
                    {"name": "query_type", "type": "string", "value": "all"},
                    {"name": "start_time", "type": "string", "value": start.isoformat()},
                    {"name": "end_time",   "type": "string", "value": end.isoformat()},
                    {"name": "interval",   "type": "string", "value": "DAY" if (end - start).days > 2 else "TOTAL"},
                ],
            )

        if bot_intent:
            # Bot-only metrics — Connect bot metrics + Lex CloudWatch
            qt = "bot_metrics" if has_time_range else "all"
            return with_time(
                "get_bot_metrics",
                [
                    {"name": "query_type", "type": "string", "value": qt},
                    {"name": "start_time", "type": "string", "value": start.isoformat()},
                    {"name": "end_time",   "type": "string", "value": end.isoformat()},
                    {"name": "interval",   "type": "string", "value": "DAY" if (end - start).days > 2 else "TOTAL"},
                ],
            )

        if flow_intent:
            return with_time(
                "get_bot_metrics",
                [
                    {"name": "query_type", "type": "string", "value": "flow_metrics"},
                    {"name": "start_time", "type": "string", "value": start.isoformat()},
                    {"name": "end_time",   "type": "string", "value": end.isoformat()},
                    {"name": "interval",   "type": "string", "value": "DAY" if (end - start).days > 2 else "TOTAL"},
                ],
            )

        # Keyword / transcript search — "find calls mentioning X", "search for X", "calls about X"
        kw_match = re.search(
            r"(?:mention(?:ing)?|containing|about|regarding|with keyword|search(?:ing)?\s+for|find\s+calls?\s+(?:with|about|mentioning)?)\s+['\"]?([a-z0-9 _-]+)['\"]?",
            lower,
        )
        if kw_match:
            keyword = kw_match.group(1).strip().strip("'\"")
            return with_time(
                "keyword_search",
                [
                    {"name": "keyword", "type": "string", "value": keyword},
                    {"name": "start_time", "type": "string", "value": start.isoformat()},
                    {"name": "end_time", "type": "string", "value": end.isoformat()},
                    {"name": "max_results", "type": "string", "value": "25"},
                ],
            )

        return None

    def _invoke_direct_tool(self, request: Dict[str, Any]) -> str:
        tool_name = request["tool_name"]
        target = self.direct_tool_lambdas.get(tool_name)
        if not target:
            raise RuntimeError(
                "AgentCore Gateway is not configured and no direct Lambda fallback was provided for tool "
                f"'{tool_name}'."
            )
        response = self.lambda_client.invoke(
            FunctionName=target,
            InvocationType="RequestResponse",
            Payload=json.dumps(request["payload"]).encode("utf-8"),
        )
        payload = json.loads(response["Payload"].read().decode("utf-8"))
        body = (
            payload.get("response", {})
            .get("functionResponse", {})
            .get("responseBody", {})
            .get("TEXT", {})
            .get("body")
        )
        if not body:
            return json.dumps(payload, indent=2)
        try:
            parsed = json.loads(body)
            return json.dumps(parsed, indent=2, default=str)
        except json.JSONDecodeError:
            return body

    async def query_async(self, message: str, session_id: Optional[str] = None) -> str:
        # Tier 1: Full Strands agent via AgentCore Gateway (cloud/production path).
        if self.gateway_endpoint:
            return await self._query_via_gateway(message, session_id)

        # Build a routing message that inherits date context from conversation history when
        # the current message is a short follow-up with no explicit date reference.
        routing_msg = self._build_routing_message(message, session_id)
        request = self._infer_tool_request(routing_msg)

        # Tier 2: Direct Lambda invocation (deployed Lambdas, no gateway).
        if request and self.direct_tool_lambdas:
            text = self._invoke_direct_tool(request)
            self._remember(session_id, "user", message)
            self._remember(session_id, "assistant", text)
            return text

        # Tier 3: In-process local tools (Docker dev — tools/ mounted at /app/tools).
        # The tool lambda_handler functions are imported directly; no Lambda infra needed.
        # Real AWS credentials + CONNECT_INSTANCE_ID are still required for live Connect data.
        if request and self.local_tools.available:
            try:
                raw = self.local_tools.invoke(request["tool_name"], request["payload"])
                text = self._format_with_bedrock(message, request["tool_name"], raw)
                self._remember(session_id, "user", message)
                self._remember(session_id, "assistant", text)
                return text
            except Exception as exc:  # pylint: disable=broad-except
                LOGGER.warning("Local tool '%s' failed: %s", request["tool_name"], exc)
                return (
                    f"I was unable to retrieve data from the **{request['tool_name']}** tool. "
                    "Please ensure your AWS credentials and `CONNECT_INSTANCE_ID` are set correctly, "
                    "then try again."
                )

        if request and not self.local_tools.available:
            LOGGER.warning("Tools directory not found — cannot invoke '%s'.", request["tool_name"])
            return (
                "The analytics tools are not available in this environment. "
                "In Docker, ensure the `tools/` volume is mounted at `/app/tools` (see `docker-compose.yml`). "
                "Outside Docker, set the `TOOLS_ROOT` environment variable to the tools directory path."
            )

        # Tier 4: No tool matched — use Bedrock directly as a conversational fallback.
        # This handles greetings, capability questions, and queries the pattern matcher misses.
        LOGGER.info("No tool matched for query; falling back to Bedrock conversational response.")
        history = self._history_block(session_id)
        conv_prompt = f"{history}\nUser: {message}" if history else message
        # Re-use _format_with_bedrock's model-candidate rotation so we don't depend on a
        # single model ID being valid in this region.
        text = self._format_with_bedrock(message, "conversational", {"question": conv_prompt})
        self._remember(session_id, "user", message)
        self._remember(session_id, "assistant", text)
        return text

    def query(self, message: str, session_id: Optional[str] = None) -> str:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.query_async(message, session_id=session_id))

        new_loop = asyncio.new_event_loop()
        try:
            return new_loop.run_until_complete(self.query_async(message, session_id=session_id))
        finally:
            new_loop.close()
