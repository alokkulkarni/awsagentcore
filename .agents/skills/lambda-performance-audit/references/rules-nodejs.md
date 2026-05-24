# Node.js / TypeScript Lambda Performance Rules

## Official AWS References
- https://docs.aws.amazon.com/lambda/latest/dg/nodejs-handler.html — Node.js handler programming model
- https://docs.aws.amazon.com/lambda/latest/dg/nodejs-best-practices.html — Node.js best practices
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtime-environment.html — Execution environment lifecycle
- https://docs.aws.amazon.com/sdk-for-javascript/v3/developer-guide/the-request-object.html — AWS SDK v3 request handling
- https://docs.aws.amazon.com/AWSJavaScriptSDK/v3/latest/ — AWS SDK for JavaScript v3 API reference
- https://docs.aws.amazon.com/sdk-for-javascript/v3/developer-guide/migrating-to-v3.html — SDK v2 to v3 migration guide
- https://aws.amazon.com/blogs/compute/using-node-js-es-modules-and-top-level-await-in-aws-lambda/ — ES modules and top-level await
- https://docs.powertools.aws.dev/lambda/typescript/latest/ — AWS Lambda Powertools for TypeScript
- https://smithy.io/2.0/ts-ssdk/ — Smithy TypeScript SDK (NodeHttpHandler)

## Runtime Requirements
- Node.js 18.x or later (Lambda managed runtime)
- AWS SDK for JavaScript v3 (`@aws-sdk/client-*`)
- `@smithy/node-http-handler` for HTTP keepAlive configuration

## Key Concepts

### Execution Environment Reuse
Lambda re-uses the same execution environment across warm invocations. Code at module scope (outside the handler function) runs only during the cold start / init phase and is preserved for subsequent invocations. This is the Node.js equivalent of Python's module-level code.

Lambda recommends using **ES modules with top-level `await`** so async initialization completes during the init phase, not on first invoke.

### SDK v3 Architecture
AWS SDK v3 uses a modular, tree-shakable design. Each service is a separate npm package (`@aws-sdk/client-connect`, etc.). The old monolithic `aws-sdk` (v2) is in maintenance mode and should not be used in new functions.

---

## Rule: JS_CLIENT_IN_HANDLER [CRITICAL]

**What it means:** An AWS SDK client is instantiated inside the handler function body.

**Why it matters:** The client is recreated on every warm invocation — new TLS handshake, connection setup, credential refresh. Adds 50–300ms of avoidable latency.

**Before (bad)**
```javascript
// CommonJS, SDK v2 style
exports.handler = async (event, context) => {
    const AWS = require('aws-sdk');
    const connect = new AWS.Connect({ region: 'us-east-1' }); // ← BAD
    return connect.listQueues({ InstanceId: event.instanceId }).promise();
};
```

**Before (bad, SDK v3)**
```javascript
import { ConnectClient, ListQueuesCommand } from "@aws-sdk/client-connect";

export const handler = async (event, context) => {
    const client = new ConnectClient({}); // ← BAD: inside handler
    return client.send(new ListQueuesCommand({ InstanceId: event.instanceId }));
};
```

**After (correct)**
```javascript
import { NodeHttpHandler } from "@smithy/node-http-handler";
import { Agent } from "https";
import { ConnectClient, ListQueuesCommand } from "@aws-sdk/client-connect";

// Module scope — initialised once, reused on warm invocations
const httpAgent = new Agent({ keepAlive: true, maxSockets: 50 });
const client = new ConnectClient({
    requestHandler: new NodeHttpHandler({ httpsAgent: httpAgent }),
    maxAttempts: 3,
});

export const handler = async (event, context) => {
    console.log(JSON.stringify({ event: "lambda_invoked", function: context.functionName }));
    return client.send(new ListQueuesCommand({ InstanceId: event.instanceId }));
};
```

**Lazy-init alternative (when config depends on env vars)**
```javascript
let client;
function getClient() {
    if (!client) {
        client = new ConnectClient({
            region: process.env.AWS_REGION,
            requestHandler: new NodeHttpHandler({ httpsAgent: new Agent({ keepAlive: true }) }),
            maxAttempts: 3,
        });
    }
    return client;
}

export const handler = async (event) => {
    return getClient().send(new ListQueuesCommand({ InstanceId: event.instanceId }));
};
```

---

## Rule: JS_SDK_V2_USAGE [HIGH]

**What it means:** The file uses AWS SDK for JavaScript v2 (`require('aws-sdk')` or `import AWS from 'aws-sdk'`).

**Why it matters:**
- SDK v2 entered maintenance mode in September 2024 and will reach end-of-life in 2025
- SDK v2 includes all services in one bundle — larger deployment package and slower cold starts
- SDK v3 is modular (per-service packages), tree-shakable, and actively maintained

**Before**
```javascript
const AWS = require('aws-sdk');
const connect = new AWS.Connect();
```

**After (SDK v3)**
```javascript
import { ConnectClient, ListQueuesCommand } from "@aws-sdk/client-connect";

const client = new ConnectClient({});
await client.send(new ListQueuesCommand({ InstanceId: instanceId }));
```

**Reference:** https://docs.aws.amazon.com/sdk-for-javascript/v3/developer-guide/migrating-to-v3.html

---

## Rule: JS_MISSING_HTTP_KEEPALIVE [HIGH]

**What it means:** No `NodeHttpHandler` with a custom `https.Agent` is configured on the SDK client.

**Why it matters:** Without keepAlive, each SDK call opens a new TLS connection. With keepAlive, connections are pooled and reused, reducing per-call overhead by 50–150ms.

**Before**
```javascript
import { S3Client } from "@aws-sdk/client-s3";

const client = new S3Client({}); // no keepAlive
```

**After**
```javascript
import { NodeHttpHandler } from "@smithy/node-http-handler";
import { Agent } from "https";
import { S3Client } from "@aws-sdk/client-s3";

const agent = new Agent({ keepAlive: true, maxSockets: 50 });
const client = new S3Client({
    requestHandler: new NodeHttpHandler({ httpsAgent: agent }),
    maxAttempts: 3,
});
```

**Install:** `npm install @smithy/node-http-handler`

---

## Rule: JS_MISSING_RETRY_CONFIG [HIGH]

**What it means:** AWS SDK client is created without an explicit `maxAttempts` setting.

**Why it matters:** Transient AWS API failures (throttling, 5xx) will not be retried reliably without an explicit retry config.

**After**
```javascript
const client = new ConnectClient({ maxAttempts: 3 });
```

---

## Rule: JS_UNHANDLED_ASYNC [HIGH]

**What it means:** An async handler has no top-level `try/catch`, meaning any rejected promise silently fails.

**Before**
```javascript
export const handler = async (event) => {
    const result = await client.send(new GetContactCommand({ ContactId: event.id }));
    return result;
    // ← no try/catch: unhandled rejection silently swallowed
};
```

**After**
```javascript
export const handler = async (event, context) => {
    console.log(JSON.stringify({ event: "lambda_invoked", function: context.functionName }));
    try {
        const result = await client.send(new GetContactCommand({ ContactId: event.id }));
        return result;
    } catch (err) {
        console.error(JSON.stringify({ event: "handler_error", error: err.message }));
        throw err;
    }
};
```

---

## Rule: JS_FULL_SDK_IMPORT [MEDIUM]

Importing the full SDK v2 (`require('aws-sdk')`) bundles 80MB+ of code. Use per-service SDK v3 imports.

---

## Rule: JS_HARDCODED_REGION [MEDIUM]

**Before:** `const client = new ConnectClient({ region: "us-east-1" });`
**After:** `const client = new ConnectClient({ region: process.env.AWS_REGION });`

Lambda automatically sets `AWS_REGION`.

---

## Rule: JS_MISSING_INVOCATION_LOG [LOW]

```javascript
export const handler = async (event, context) => {
    console.log(JSON.stringify({ event: "lambda_invoked", function: context.functionName, requestId: context.awsRequestId }));
    // ...
};
```

