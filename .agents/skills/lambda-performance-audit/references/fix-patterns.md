# Fix Patterns — Before & After Examples

## CLIENT_IN_HANDLER

**Before**
```python
import boto3

def lambda_handler(event, context):
    client = boto3.client("connect")  # recreated every invocation
    return client.get_current_metric_data(InstanceId=event["instance_id"])
```

**After**
```python
import boto3
from botocore.config import Config

_BOTO_CONFIG = Config(
    tcp_keepalive=True,
    max_pool_connections=10,
    retries={"mode": "standard", "max_attempts": 3},
    connect_timeout=5,
    read_timeout=15,
)
_CONNECT_CLIENT = boto3.client("connect", config=_BOTO_CONFIG)


def lambda_handler(event, context):
    return _CONNECT_CLIENT.get_current_metric_data(InstanceId=event["instance_id"])
```

**Lazy-init pattern**
```python
import os
from typing import Any

_CONNECT_CLIENT = None


def _get_connect() -> Any:
    global _CONNECT_CLIENT
    if _CONNECT_CLIENT is None:
        _CONNECT_CLIENT = boto3.client("connect", region_name=os.environ["AWS_REGION"], config=_BOTO_CONFIG)
    return _CONNECT_CLIENT
```

**Notes**
- Use module-level clients when configuration is static.
- Use lazy init only when client creation depends on runtime configuration.

## MISSING_BOTO_CONFIG

**Before**
```python
_CONNECT = boto3.client("connect")
```

**After**
```python
from botocore.config import Config

_BOTO_CONFIG = Config(
    tcp_keepalive=True,
    max_pool_connections=10,
    retries={"mode": "standard", "max_attempts": 3},
    connect_timeout=5,
    read_timeout=15,
)
_CONNECT = boto3.client("connect", config=_BOTO_CONFIG)
```

**Notes**
- Keep the config in one reusable module-level constant.
- Apply the same config to resources where appropriate.

## MISSING_CONFIG_IMPORT

**Before**
```python
import boto3

_CLIENT = boto3.client("s3")
```

**After**
```python
import boto3
from botocore.config import Config

_CLIENT = boto3.client("s3", config=Config(tcp_keepalive=True))
```

**Notes**
- `from botocore import config` also satisfies the audit.
- Prefer importing `Config` directly for readability.

## HARDCODED_LOG_LEVEL

**Before**
```python
import logging

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)
```

**After**
```python
import logging
import os

LOGGER = logging.getLogger()
LOGGER.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
```

**Notes**
- Works for literal strings like `"DEBUG"` too.
- Keep default level conservative; `INFO` is a common default.

## MISSING_INVOCATION_LOG

**Before**
```python
def lambda_handler(event, context):
    do_work(event)
    return {"ok": True}
```

**After**
```python
import json
import logging

logger = logging.getLogger(__name__)


def lambda_handler(event, context):
    logger.info(json.dumps({"event": "lambda_invoked", "function": context.function_name}))
    do_work(event)
    return {"ok": True}
```

**Notes**
- Put the log in the first few statements of the handler.
- Prefer JSON so CloudWatch Insights can parse it reliably.

## UNCACHED_PAGINATOR

**Before**
```python
def _list_users(client, instance_id):
    paginator = client.get_paginator("list_users")
    return [item for page in paginator.paginate(InstanceId=instance_id) for item in page["UserSummaryList"]]
```

**After**
```python
import time

_CACHE = {}
_CACHE_TTL = 300


def _list_users(client, instance_id):
    key = f"users:{instance_id}"
    cached = _CACHE.get(key)
    if cached is not None and (time.time() - cached["ts"]) < _CACHE_TTL:
        return cached["value"]
    paginator = client.get_paginator("list_users")
    value = [item for page in paginator.paginate(InstanceId=instance_id) for item in page["UserSummaryList"]]
    _CACHE[key] = {"value": value, "ts": time.time()}
    return value
```

**Notes**
- Cache only reasonably stable list APIs.
- A 300 second TTL is a good default for Connect metadata.

## API_CALL_IN_LOOP

**Before**
```python
results = []
for agent_id in agent_ids:
    results.append(connect.describe_user(InstanceId=instance_id, UserId=agent_id))
```

**After**
```python
user_cache = {}
results = []
for agent_id in agent_ids:
    if agent_id not in user_cache:
        user_cache[agent_id] = connect.describe_user(InstanceId=instance_id, UserId=agent_id)
    results.append(user_cache[agent_id])
```

**Notes**
- Prefer batch APIs where AWS exposes them.
- If batching is impossible, cache or pre-group the workload.

## HARDCODED_REGION

**Before**
```python
_CONNECT = boto3.client("connect", region_name="us-east-1")
```

**After**
```python
import os

_CONNECT = boto3.client("connect", region_name=os.environ.get("AWS_REGION"), config=_BOTO_CONFIG)
```

**Notes**
- In Lambda, omitting `region_name` is often simplest.
- Use `AWS_REGION` only when you must be explicit.

## BROAD_EXCEPT

**Before**
```python
try:
    return _CONNECT.list_users(InstanceId=instance_id)
except Exception:
    logger.exception("failed")
    raise
```

**After**
```python
from botocore.exceptions import BotoCoreError, ClientError

try:
    return _CONNECT.list_users(InstanceId=instance_id)
except (ClientError, BotoCoreError):
    logger.exception("AWS API failure")
    raise
except Exception:
    logger.exception("Unexpected failure")
    raise
```

**Notes**
- The broad catch is acceptable only after specific boto3 exceptions.
- Prefer `logger.exception()` so stack traces are preserved.
