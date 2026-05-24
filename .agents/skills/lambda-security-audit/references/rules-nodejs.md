# Node.js / TypeScript Lambda Security Rules

## Official AWS References
- https://docs.aws.amazon.com/lambda/latest/dg/nodejs-handler.html — Handler programming model
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html — Lambda security best practices
- https://docs.aws.amazon.com/lambda/latest/dg/configuration-envvars.html#configuration-envvars-encryption — Environment variable encryption
- https://docs.aws.amazon.com/secretsmanager/latest/userguide/intro.html — Secrets Manager
- https://docs.aws.amazon.com/lambda/latest/dg/nodejs-logging.html — Node.js logging
- https://owasp.org/www-project-top-ten/ — OWASP Top 10 2021
- https://owasp.org/www-project-serverless-top-10/ — OWASP Serverless Top 10

## Rule: JS_PII_IN_LOG [CRITICAL]

**CWE**  CWE-532 — Insertion of Sensitive Information into Log File

**Description**  Full event or request body serialised directly to console.log — PII/sensitive data exposure

**AWS Lambda context**  Node.js handlers often log full request objects during debugging; those logs persist beyond the invocation lifetime.

**Before**
```javascript
console.log(JSON.stringify(event));
```

**After**
```javascript
console.log(JSON.stringify({ event: "lambda_invoked", params: redactEvent(event) }));
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html

## Rule: JS_HARDCODED_SECRET [CRITICAL]

**CWE**  CWE-798 — Use of Hard-coded Credentials

**Description**  Possible hardcoded secret — sensitive variable assigned a string literal

**AWS Lambda context**  Lambda deployment packages are often copied across stages and accounts; embedded secrets fan out rapidly.

**Before**
```javascript
const clientSecret = "hardcoded-super-secret";
```

**After**
```javascript
const clientSecret = await secretsClient.send(new GetSecretValueCommand({ SecretId: process.env.CLIENT_SECRET_ID }));
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html

## Rule: JS_EVAL_RISK [CRITICAL]

**CWE**  CWE-95 — Improper Neutralization of Directives in Dynamically Evaluated Code ('Eval Injection')

**Description**  eval() called — code injection risk

**AWS Lambda context**  JSON event payloads are data, not code; Lambda should never dynamically execute caller-provided expressions.

**Before**
```javascript
const result = eval(event.expression);
```

**After**
```javascript
const result = JSON.parse(event.expression);
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Injection_Prevention_Cheat_Sheet.html

## Rule: JS_SSRF_RISK [HIGH]

**CWE**  CWE-918 — Server-Side Request Forgery (SSRF)

**Description**  HTTP request made with URL from event/environment without scheme validation

**AWS Lambda context**  Outbound calls from Lambda may traverse VPC routes or NAT gateways and can reach sensitive internal addresses.

**Before**
```javascript
await fetch(event.endpoint);
```

**After**
```javascript
const u = new URL(event.endpoint);
if (u.protocol !== "https:") throw new Error("HTTPS required");
await fetch(u);
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html

## Rule: JS_MISSING_TLS_VERIFY [HIGH]

**CWE**  CWE-295 — Improper Certificate Validation

**Description**  TLS verification disabled: rejectUnauthorized: false

**AWS Lambda context**  Lambda functions usually run over public internet egress; certificate validation is non-negotiable for production traffic.

**Before**
```javascript
https.request({ host, rejectUnauthorized: false });
```

**After**
```javascript
https.request({ host });
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html

## Rule: JS_CMD_INJECTION [HIGH]

**CWE**  CWE-78 — OS Command Injection

**Description**  Command injection risk: child_process.exec/execSync with shell interpolation

**AWS Lambda context**  Even helper invocations like ffmpeg, unzip, or ls can be weaponised when event data is concatenated into shell strings.

**Before**
```javascript
exec(`ls ${event.path}`);
```

**After**
```javascript
spawn("ls", [safePath], { stdio: "inherit" });
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Injection_Prevention_Cheat_Sheet.html

## Rule: JS_SQL_INJECTION [HIGH]

**CWE**  CWE-89 — SQL Injection

**Description**  Possible SQL injection — template literal or string concatenation used to build SQL

**AWS Lambda context**  Serverless APIs often bind request data directly into storage queries; parameterisation keeps that boundary safe.

**Before**
```javascript
const sql = `SELECT * FROM users WHERE id = ${event.userId}`;
```

**After**
```javascript
const sql = "SELECT * FROM users WHERE id = $1";
await db.query(sql, [event.userId]);
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html

## Rule: JS_LOG_INJECTION [MEDIUM]

**CWE**  CWE-117 — Improper Output Neutralization for Logs

**Description**  User-controlled event field interpolated directly into log string

**AWS Lambda context**  CloudWatch Insights and SIEM tooling assume sane log boundaries; injected line breaks undermine alerting.

**Before**
```javascript
console.info(`user=${event.user}`);
```

**After**
```javascript
console.info(`user=${sanitizeForLog(event.user)}`);
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html

## Rule: JS_SILENT_CATCH [MEDIUM]

**CWE**  CWE-390 — Detection of Error Condition Without Action

**Description**  Empty catch block — errors are silently discarded

**AWS Lambda context**  Async Lambda workflows depend on explicit failure signaling; silent catch blocks can make poison messages loop indefinitely.

**Before**
```javascript
try {
  await sync();
} catch (err) {}
```

**After**
```javascript
try {
  await sync();
} catch (err) {
  console.error("Suppressed error:", err);
}
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html

## Rule: JS_SENSITIVE_IN_RESPONSE [MEDIUM]

**CWE**  CWE-200 — Exposure of Sensitive Information to an Unauthorized Actor

**Description**  Sensitive field name in returned object — may expose secrets to caller

**AWS Lambda context**  API Gateway and Step Functions surface Lambda return payloads widely; never include secrets in those objects.

**Before**
```javascript
return { token: sessionToken, status: "ok" };
```

**After**
```javascript
return { status: "ok" };
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/User_Privacy_Protection_Cheat_Sheet.html
