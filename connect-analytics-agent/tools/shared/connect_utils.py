import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def parse_parameters(event_params: Optional[Iterable[Dict[str, Any]]]) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    for item in event_params or []:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("Name")
        if not name:
            continue
        value = item.get("value")
        if isinstance(value, str):
            value = value.strip()
        params[name] = value
    return params


def build_response(event: Dict[str, Any], result: Any, status_code: int = 200) -> Dict[str, Any]:
    body = json.dumps(
        {
            "statusCode": status_code,
            "success": 200 <= status_code < 300,
            "data": result,
        },
        default=_json_default,
    )
    return {
        "response": {
            "actionGroup": event.get("actionGroup", "ConnectAnalyticsTools"),
            "function": event.get("function", "unknown"),
            "functionResponse": {
                "responseBody": {
                    "TEXT": {
                        "body": body,
                    }
                }
            },
        }
    }


def build_error_response(event: Dict[str, Any], error_msg: str, status_code: int = 500) -> Dict[str, Any]:
    return build_response(event, {"error": error_msg}, status_code=status_code)


def get_instance_id(params: Dict[str, Any]) -> str:
    instance_id = params.get("instance_id") or os.getenv("CONNECT_INSTANCE_ID")
    if not instance_id:
        raise ValueError("Amazon Connect instance_id is required either as a parameter or CONNECT_INSTANCE_ID env var.")
    return str(instance_id)


def parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    if not dt_str:
        return None
    normalized = str(dt_str).strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "00:00:00"
    total_seconds = max(int(float(seconds)), 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def parse_csv(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]
