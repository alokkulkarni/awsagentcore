# AWS Lambda Performance Rules Reference

## Official Sources

- https://docs.aws.amazon.com/lambda/latest/dg/best-practices.html
- https://docs.aws.amazon.com/lambda/latest/dg/python-handler.html
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtime-environment.html

## Rules Catalog

### CLIENT_IN_HANDLER [CRITICAL]

**What it means**  
`boto3.client()` or `boto3.resource()` is created inside `lambda_handler`.

**Why it matters**  
Every invocation pays for a new SDK session, connection setup, and possible DNS work. On warm invocations this can add ~50-300ms of avoidable latency.

**Before**
```python
import boto3

def lambda_handler(event, context):
    client = boto3.client("connect")
    return client.list_queues(InstanceId=event["instance_id"])
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
    return _CONNECT_CLIENT.list_queues(InstanceId=event["instance_id"])
```

### MISSING_BOTO_CONFIG [HIGH]

**What it means**  
A boto3 client or resource is created without `botocore.config.Config`.

**Why it matters**  
Without keepalive, retries, and sensible timeouts, Lambda loses connection reuse and becomes less resilient to transient AWS API failures.

**Before**
```python
import boto3

_CONNECT_CLIENT = boto3.client("connect")
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
```

### MISSING_CONFIG_IMPORT [HIGH]

**What it means**  
The file uses boto3 but does not import `Config`.

**Why it matters**  
Without the import, the recommended Lambda connection configuration cannot be applied consistently.

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

### HARDCODED_LOG_LEVEL [MEDIUM]

**What it means**  
`logger.setLevel(logging.INFO)` or a string literal is hardcoded.

**Why it matters**  
You cannot change verbosity without redeploying, which makes production troubleshooting slower and can force noisy logging in hot paths.

**Before**
```python
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
```

**After**
```python
import logging
import os

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
```

### MISSING_INVOCATION_LOG [LOW]

**What it means**  
The handler does not emit structured JSON at the start of execution.

**Why it matters**  
Without a consistent invocation record, CloudWatch queries and per-invocation troubleshooting are harder.

**Before**
```python
def lambda_handler(event, context):
    return {"ok": True}
```

**After**
```python
import json
import logging

logger = logging.getLogger(__name__)


def lambda_handler(event, context):
    logger.info(json.dumps({"event": "lambda_invoked", "function": context.function_name}))
    return {"ok": True}
```

### UNCACHED_PAGINATOR [HIGH]

**What it means**  
A paginator such as `list_users` or `list_queues` is created and used every invocation without a TTL cache.

**Why it matters**  
Repeated list APIs often take 100-500ms and do not change on every invocation. Re-fetching them on warm paths adds wasted latency.

**Before**
```python
def _queue_ids(client, instance_id):
    paginator = client.get_paginator("list_queues")
    return [queue["Id"] for page in paginator.paginate(InstanceId=instance_id) for queue in page["QueueSummaryList"]]
```

**After**
```python
import time

_CACHE = {}
_CACHE_TTL = 300


def _queue_ids(client, instance_id):
    key = f"queues:{instance_id}"
    cached = _CACHE.get(key)
    if cached is not None and (time.time() - cached["ts"]) < _CACHE_TTL:
        return cached["value"]
    paginator = client.get_paginator("list_queues")
    value = [queue["Id"] for page in paginator.paginate(InstanceId=instance_id) for queue in page["QueueSummaryList"]]
    _CACHE[key] = {"value": value, "ts": time.time()}
    return value
```

### API_CALL_IN_LOOP [HIGH]

**What it means**  
Code calls APIs like `describe_user()` inside a loop over many items.

**Why it matters**  
Latency becomes `N * API latency`, which is especially expensive in Lambda. Each additional item can add another remote call.

**Before**
```python
results = []
for user_id in user_ids:
    results.append(connect.describe_user(InstanceId=instance_id, UserId=user_id))
```

**After**
```python
user_cache = {}
results = []
for user_id in user_ids:
    if user_id not in user_cache:
        user_cache[user_id] = connect.describe_user(InstanceId=instance_id, UserId=user_id)
    results.append(user_cache[user_id])
```

### HARDCODED_REGION [MEDIUM]

**What it means**  
`region_name="us-east-1"` is set directly in a boto3 client/resource call.

**Why it matters**  
The code breaks or behaves incorrectly when the Lambda function is deployed in another region. Lambda already exposes `AWS_REGION`.

**Before**
```python
import boto3

_CONNECT = boto3.client("connect", region_name="us-east-1")
```

**After**
```python
import boto3
import os

_CONNECT = boto3.client("connect", region_name=os.environ.get("AWS_REGION"))
```

### BROAD_EXCEPT [LOW]

**What it means**  
The code uses `except Exception` or bare `except:` without catching boto3-specific errors first.

**Why it matters**  
Broad catches can swallow `ClientError` and `BotoCoreError`, making retries, metrics, and troubleshooting less precise.

**Before**
```python
try:
    return _CONNECT_CLIENT.list_users(InstanceId=instance_id)
except Exception as exc:
    logger.error("failed: %s", exc)
    raise
```

**After**
```python
from botocore.exceptions import BotoCoreError, ClientError

try:
    return _CONNECT_CLIENT.list_users(InstanceId=instance_id)
except (ClientError, BotoCoreError):
    logger.exception("AWS API failure")
    raise
except Exception:
    logger.exception("Unexpected failure")
    raise
```
