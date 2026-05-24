---
name: lambda-performance-audit
description: >
  Validates AWS Lambda handlers against official AWS performance best practices for all supported runtimes.
  Activate when writing, reviewing, creating, or optimising Lambda functions in Python, Node.js, TypeScript, Go, or Java (Spring / Spring Cloud Function).
  Covers: SDK client placement outside the handler, HTTP keepalive and connection pool config, retry/timeout settings,
  LOG_LEVEL environment variable, TTL caching for repeated AWS API calls, structured JSON invocation logging,
  N+1 loop patterns, hardcoded region names, SDK v1 vs v2 usage, and Spring Cloud Function patterns.
  Use to audit existing Lambda files, auto-fix common issues, or validate changes before deployment.
license: MIT
compatibility: >
  Python 3.9+ (python3 in PATH); Node.js 18+ (node in PATH); Go 1.21+ (go in PATH); Java 11+.
  uv optional (for PEP 723 script execution).
metadata:
  category: aws
  tags: [lambda, aws, boto3, performance, serverless, python, nodejs, typescript, go, java, spring]
  author: agentskills
allowed-tools: [Bash, Read, Edit, Glob, Grep]
---

## Activation

Activate whenever a Lambda handler file is written, modified, reviewed, or created. Detect the runtime from the file extension:

| Extension | Runtime |
|-----------|---------|
| `.py` | Python |
| `.js` `.mjs` `.cjs` `.ts` | Node.js / TypeScript |
| `.go` | Go |
| `.java` | Java / Spring |

## Rules by Runtime

### Python

| Rule ID | Severity | Auto-fix |
|---------|----------|---------|
| CLIENT_IN_HANDLER | CRITICAL | No |
| MISSING_BOTO_CONFIG | HIGH | Yes |
| MISSING_CONFIG_IMPORT | HIGH | Yes |
| UNCACHED_PAGINATOR | HIGH | No |
| API_CALL_IN_LOOP | HIGH | No |
| HARDCODED_LOG_LEVEL | MEDIUM | Yes |
| HARDCODED_REGION | MEDIUM | No |
| MISSING_INVOCATION_LOG | LOW | Yes |
| BROAD_EXCEPT | LOW | No |

### Node.js / TypeScript

| Rule ID | Severity | Auto-fix |
|---------|----------|---------|
| JS_CLIENT_IN_HANDLER | CRITICAL | No |
| JS_SDK_V2_USAGE | HIGH | No |
| JS_MISSING_HTTP_KEEPALIVE | HIGH | No |
| JS_MISSING_RETRY_CONFIG | HIGH | No |
| JS_FULL_SDK_IMPORT | MEDIUM | No |
| JS_HARDCODED_REGION | MEDIUM | No |
| JS_MISSING_INVOCATION_LOG | LOW | No |
| JS_UNHANDLED_ASYNC | HIGH | No |

### Go

| Rule ID | Severity | Auto-fix |
|---------|----------|---------|
| GO_CLIENT_IN_HANDLER | CRITICAL | No |
| GO_SDK_V1_USAGE | HIGH | No |
| GO_MISSING_HTTP_TRANSPORT | HIGH | No |
| GO_CLIENT_NOT_IN_VAR_BLOCK | HIGH | No |
| GO_MISSING_LOG_LEVEL | MEDIUM | No |
| GO_MISSING_INVOCATION_LOG | LOW | No |

### Java / Spring

| Rule ID | Severity | Auto-fix |
|---------|----------|---------|
| JAVA_CLIENT_IN_HANDLER | CRITICAL | No |
| JAVA_SDK_V1_USAGE | HIGH | No |
| JAVA_MISSING_HTTP_CLIENT_CONFIG | HIGH | No |
| JAVA_NO_STATIC_CLIENT | HIGH | No |
| JAVA_MISSING_RETRY_CONFIG | HIGH | No |
| JAVA_SNAPSTART_NOT_CONSIDERED | MEDIUM | No |
| JAVA_MISSING_INVOCATION_LOG | LOW | No |

## Workflow

1. Detect runtime from file extension
2. Run: `python3 .agents/skills/lambda-performance-audit/scripts/audit_lambda.py <file_path>`
3. Fix all CRITICAL and HIGH issues — manually for structural ones, auto-fix for flagged ones
4. Re-run audit until zero CRITICAL/HIGH issues remain
5. Validate syntax:
   - Python: `python3 -m py_compile <file>`
   - Node.js: `node --check <file>` (or `tsc --noEmit` for TypeScript)
   - Go: `go build ./...`
   - Java: `mvn compile` or `./gradlew classes`

## Python Auto-fix

```bash
python3 .agents/skills/lambda-performance-audit/scripts/fix_lambda.py <file.py>
```

Auto-fixes: `MISSING_BOTO_CONFIG`, `MISSING_CONFIG_IMPORT`, `HARDCODED_LOG_LEVEL`, `MISSING_INVOCATION_LOG`

## Standard Patterns

### Python
```python
import os, json, logging
import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_BOTO_CONFIG = Config(
    tcp_keepalive=True,
    max_pool_connections=10,
    retries={"mode": "standard", "max_attempts": 3},
    connect_timeout=5,
    read_timeout=15,
)
_CLIENT = boto3.client("connect", config=_BOTO_CONFIG)

def lambda_handler(event, context):
    logger.info(json.dumps({"event": "lambda_invoked", "function": context.function_name}))
```

### Node.js (ESM, SDK v3)
```javascript
import { NodeHttpHandler } from "@smithy/node-http-handler";
import { Agent } from "https";
import { ConnectClient } from "@aws-sdk/client-connect";

const httpAgent = new Agent({ keepAlive: true, maxSockets: 50 });
const client = new ConnectClient({
  requestHandler: new NodeHttpHandler({ httpsAgent: httpAgent }),
  maxAttempts: 3,
});

export const handler = async (event, context) => {
  console.log(JSON.stringify({ event: "lambda_invoked", function: context.functionName }));
};
```

### Go
```go
var (
    httpClient = &http.Client{
        Transport: &http.Transport{
            DialContext: (&net.Dialer{
                Timeout:   5 * time.Second,
                KeepAlive: 30 * time.Second,
            }).DialContext,
            MaxIdleConns:        100,
            IdleConnTimeout:     90 * time.Second,
            TLSHandshakeTimeout: 10 * time.Second,
        },
    }
    connectClient *connect.Client
)

func init() {
    cfg, _ := config.LoadDefaultConfig(context.Background(),
        config.WithHTTPClient(httpClient),
    )
    connectClient = connect.NewFromConfig(cfg)
}
```

### Java (SDK v2, static init)
```java
import software.amazon.awssdk.http.apache.ApacheHttpClient;
import software.amazon.awssdk.core.retry.RetryPolicy;
import software.amazon.awssdk.services.connect.ConnectClient;
import java.time.Duration;

public class MyHandler implements RequestHandler<Map<String,Object>, String> {
    private static final ConnectClient CONNECT_CLIENT = ConnectClient.builder()
        .httpClientBuilder(ApacheHttpClient.builder()
            .maxConnections(50)
            .connectionTimeout(Duration.ofSeconds(5))
            .socketTimeout(Duration.ofSeconds(15)))
        .overrideConfiguration(c -> c.retryPolicy(RetryPolicy.builder()
            .numRetries(3).build()))
        .build();

    @Override
    public String handleRequest(Map<String,Object> event, Context context) {
        context.getLogger().log("{\"event\":\"lambda_invoked\"}");
    }
}
```

## References

- For complete rules per language: read `references/rules.md` (index) or the per-language files
- For code patterns and before/after examples: read `references/fix-patterns.md`
- For machine-readable rule definitions: read `assets/rules.json`

