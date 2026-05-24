# AWS Lambda Performance Rules Reference

## Official AWS Documentation

### Python
- https://docs.aws.amazon.com/lambda/latest/dg/python-handler.html
- https://docs.aws.amazon.com/lambda/latest/dg/best-practices.html
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtime-environment.html
- https://boto3.amazonaws.com/v1/documentation/api/latest/guide/configuration.html
- https://botocore.amazonaws.com/v1/documentation/api/latest/reference/config.html

### Node.js / TypeScript
- https://docs.aws.amazon.com/lambda/latest/dg/nodejs-handler.html
- https://docs.aws.amazon.com/lambda/latest/dg/nodejs-best-practices.html
- https://docs.aws.amazon.com/sdk-for-javascript/v3/developer-guide/the-request-object.html
- https://docs.aws.amazon.com/AWSJavaScriptSDK/v3/latest/
- https://smithy.io/2.0/ts-ssdk/index.html
- https://docs.powertools.aws.dev/lambda/typescript/latest/

### Go
- https://docs.aws.amazon.com/lambda/latest/dg/golang-handler.html
- https://docs.aws.amazon.com/lambda/latest/dg/golang-best-practices.html
- https://aws.github.io/aws-sdk-go-v2/docs/
- https://pkg.go.dev/github.com/aws/aws-sdk-go-v2
- https://pkg.go.dev/github.com/aws/aws-lambda-go/lambda

### Java / Spring
- https://docs.aws.amazon.com/lambda/latest/dg/java-handler.html
- https://docs.aws.amazon.com/lambda/latest/dg/java-best-practices.html
- https://docs.aws.amazon.com/lambda/latest/dg/snapstart.html
- https://docs.aws.amazon.com/lambda/latest/dg/java-tracing.html
- https://sdk.amazonaws.com/java/api/latest/
- https://docs.spring.io/spring-cloud-function/docs/current/reference/html/
- https://github.com/awslabs/aws-lambda-powertools-java

---

## Quick Reference — All Rules

| Rule ID | Language | Severity | Auto-fix |
|---------|----------|----------|---------|
| CLIENT_IN_HANDLER | Python | CRITICAL | No |
| MISSING_BOTO_CONFIG | Python | HIGH | Yes |
| MISSING_CONFIG_IMPORT | Python | HIGH | Yes |
| UNCACHED_PAGINATOR | Python | HIGH | No |
| API_CALL_IN_LOOP | Python | HIGH | No |
| HARDCODED_LOG_LEVEL | Python | MEDIUM | Yes |
| HARDCODED_REGION | Python | MEDIUM | No |
| MISSING_INVOCATION_LOG | Python | LOW | Yes |
| BROAD_EXCEPT | Python | LOW | No |
| JS_CLIENT_IN_HANDLER | Node.js | CRITICAL | No |
| JS_SDK_V2_USAGE | Node.js | HIGH | No |
| JS_MISSING_HTTP_KEEPALIVE | Node.js | HIGH | No |
| JS_MISSING_RETRY_CONFIG | Node.js | HIGH | No |
| JS_UNHANDLED_ASYNC | Node.js | HIGH | No |
| JS_FULL_SDK_IMPORT | Node.js | MEDIUM | No |
| JS_HARDCODED_REGION | Node.js | MEDIUM | No |
| JS_MISSING_INVOCATION_LOG | Node.js | LOW | No |
| GO_CLIENT_IN_HANDLER | Go | CRITICAL | No |
| GO_SDK_V1_USAGE | Go | HIGH | No |
| GO_MISSING_HTTP_TRANSPORT | Go | HIGH | No |
| GO_CLIENT_NOT_IN_VAR_BLOCK | Go | HIGH | No |
| GO_MISSING_LOG_LEVEL | Go | MEDIUM | No |
| GO_MISSING_INVOCATION_LOG | Go | LOW | No |
| JAVA_CLIENT_IN_HANDLER | Java | CRITICAL | No |
| JAVA_SDK_V1_USAGE | Java | HIGH | No |
| JAVA_MISSING_HTTP_CLIENT_CONFIG | Java | HIGH | No |
| JAVA_NO_STATIC_CLIENT | Java | HIGH | No |
| JAVA_MISSING_RETRY_CONFIG | Java | HIGH | No |
| JAVA_SNAPSTART_NOT_CONSIDERED | Java | MEDIUM | No |
| JAVA_MISSING_INVOCATION_LOG | Java | LOW | No |

For detailed explanations and code examples, see the per-language files:
- [rules-python.md](./rules-python.md)
- [rules-nodejs.md](./rules-nodejs.md)
- [rules-go.md](./rules-go.md)
- [rules-java-spring.md](./rules-java-spring.md)

---

## Python Rules

(see [rules-python.md](./rules-python.md) for full detail)

### CLIENT_IN_HANDLER [CRITICAL]

**What it means:** `boto3.client()` or `boto3.resource()` is created inside `lambda_handler`.

**Why it matters:** Every invocation pays for a new SDK session, connection setup, and possible DNS work. On warm invocations this can add ~50–300ms of avoidable latency.

**Before**
```python
def lambda_handler(event, context):
    client = boto3.client("connect")
    return client.list_queues(InstanceId=event["instance_id"])
```

**After**
```python
from botocore.config import Config
_BOTO_CONFIG = Config(tcp_keepalive=True, max_pool_connections=10,
    retries={"mode": "standard", "max_attempts": 3}, connect_timeout=5, read_timeout=15)
_CONNECT_CLIENT = boto3.client("connect", config=_BOTO_CONFIG)

def lambda_handler(event, context):
    return _CONNECT_CLIENT.list_queues(InstanceId=event["instance_id"])
```

### MISSING_BOTO_CONFIG [HIGH]
Add `config=Config(tcp_keepalive=True, max_pool_connections=10, retries={"mode":"standard","max_attempts":3}, connect_timeout=5, read_timeout=15)` to every `boto3.client()` / `boto3.resource()` call.

### MISSING_CONFIG_IMPORT [HIGH]
Add `from botocore.config import Config` when boto3 is used.

### HARDCODED_LOG_LEVEL [MEDIUM]
Replace `logger.setLevel(logging.INFO)` → `logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))`

### UNCACHED_PAGINATOR [HIGH]
Cache paginator results at module level with TTL dict (300s). See rules-python.md for full pattern.

### API_CALL_IN_LOOP [HIGH]
N+1 API calls in loops. Collect IDs first; use batch APIs or per-item caching.

### HARDCODED_REGION [MEDIUM]
Replace `region_name="us-east-1"` → `region_name=os.environ.get("AWS_REGION")` or omit entirely.

### MISSING_INVOCATION_LOG [LOW]
Add `logger.info(json.dumps({"event": "lambda_invoked", "function": context.function_name}))` as first handler statement.

### BROAD_EXCEPT [LOW]
Catch `(ClientError, BotoCoreError)` before a final broad `except Exception`.

---

## Node.js / TypeScript Rules

(see [rules-nodejs.md](./rules-nodejs.md) for full detail)

### JS_CLIENT_IN_HANDLER [CRITICAL]
`new ConnectClient(...)` inside the handler recreates the client on every warm invocation. Move to module scope.

### JS_SDK_V2_USAGE [HIGH]
`require('aws-sdk')` signals SDK v2 which is in maintenance mode, has a larger bundle, and slower cold starts. Migrate to `@aws-sdk/client-*`.

### JS_MISSING_HTTP_KEEPALIVE [HIGH]
Without a custom `NodeHttpHandler` with `keepAlive: true`, connections are not reused. Add `@smithy/node-http-handler` with an `https.Agent`.

### JS_MISSING_RETRY_CONFIG [HIGH]
Always set `maxAttempts: 3` in client config for transient failure resilience.

### JS_UNHANDLED_ASYNC [HIGH]
Async handler without try/catch silently swallows rejections. Always wrap in try/catch and re-throw.

### JS_FULL_SDK_IMPORT [MEDIUM]
`import AWS from 'aws-sdk'` bundles the whole SDK. Use per-service imports for smaller packages.

### JS_HARDCODED_REGION [MEDIUM]
Replace `region: "us-east-1"` → `region: process.env.AWS_REGION`.

### JS_MISSING_INVOCATION_LOG [LOW]
Add `console.log(JSON.stringify({ event: "lambda_invoked", function: context.functionName }))`.

---

## Go Rules

(see [rules-go.md](./rules-go.md) for full detail)

### GO_CLIENT_IN_HANDLER [CRITICAL]
`config.LoadDefaultConfig(ctx)` or `NewXxxFromConfig(cfg)` inside the handler function means a new client per invocation. Use `var` block + `init()`.

### GO_SDK_V1_USAGE [HIGH]
`github.com/aws/aws-sdk-go` (v1) is in maintenance mode. Migrate to `github.com/aws/aws-sdk-go-v2`.

### GO_MISSING_HTTP_TRANSPORT [HIGH]
Go's default `http.Transport` has no keepalive tuning. Create a custom `http.Client` with `http.Transport{DialContext with KeepAlive: 30s, MaxIdleConns: 100}` and pass via `config.WithHTTPClient()`.

### GO_CLIENT_NOT_IN_VAR_BLOCK [HIGH]
Declare SDK clients as package-level `var` and initialise in `init()`. Lambda freezes the process between invocations, so package-level variables are preserved.

### GO_MISSING_LOG_LEVEL [MEDIUM]
Read `os.Getenv("LOG_LEVEL")` at startup and configure logging verbosity accordingly.

### GO_MISSING_INVOCATION_LOG [LOW]
Add a structured JSON log at the start of each handler invocation.

---

## Java / Spring Rules

(see [rules-java-spring.md](./rules-java-spring.md) for full detail)

### JAVA_CLIENT_IN_HANDLER [CRITICAL]
`XxxClient.builder().build()` inside `handleRequest()` recreates the client every invocation. Use `private static final`.

### JAVA_SDK_V1_USAGE [HIGH]
`com.amazonaws.*` classes are AWS SDK v1 (maintenance mode). Migrate to `software.amazon.awssdk.*`.

### JAVA_MISSING_HTTP_CLIENT_CONFIG [HIGH]
Without `ApacheHttpClient` or `UrlConnectionHttpClient` configuration, the SDK uses default settings with no connection pool tuning.

### JAVA_NO_STATIC_CLIENT [HIGH]
If no `private static final XxxClient` field exists, the client is likely recreated per invocation.

### JAVA_MISSING_RETRY_CONFIG [HIGH]
Add `.overrideConfiguration(c -> c.retryPolicy(RetryPolicy.builder().numRetries(3).build()))` to each client builder.

### JAVA_SNAPSTART_NOT_CONSIDERED [MEDIUM]
For Java 21 on Lambda, consider SnapStart with CRaC interface to eliminate cold start entirely.

### JAVA_MISSING_INVOCATION_LOG [LOW]
Add `context.getLogger().log("{\"event\":\"lambda_invoked\"}")` at the start of `handleRequest()`.

