# Python Lambda Security Rules

## Official AWS References
- https://docs.aws.amazon.com/lambda/latest/dg/python-handler.html — Handler programming model
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html — Lambda security best practices
- https://docs.aws.amazon.com/lambda/latest/dg/configuration-envvars.html#configuration-envvars-encryption — Environment variable encryption
- https://docs.aws.amazon.com/secretsmanager/latest/userguide/intro.html — Secrets Manager
- https://docs.aws.amazon.com/lambda/latest/dg/python-logging.html — Python logging
- https://owasp.org/www-project-top-ten/ — OWASP Top 10 2021
- https://owasp.org/www-project-serverless-top-10/ — OWASP Serverless Top 10

## Rule: PY_PII_IN_LOG [CRITICAL]

**CWE**  CWE-532 — Insertion of Sensitive Information into Log File

**Description**  Full event or sensitive object serialised directly into log statement

**AWS Lambda context**  Lambda event payloads often contain customer identifiers, tokens, or contact details; anything logged is durable in CloudWatch by default.

**Before**
```python
import json
logger.info("event=%s", json.dumps(event))
```

**After**
```python
safe_event = _redact_event(event)
logger.info("event=%s", json.dumps(safe_event))
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html

## Rule: PY_HARDCODED_SECRET [CRITICAL]

**CWE**  CWE-798 — Use of Hard-coded Credentials

**Description**  Possible hardcoded secret — sensitive variable name assigned a string literal

**AWS Lambda context**  Lambda zip archives and container images are frequently shared across environments; embedded secrets spread to every copy.

**Before**
```python
client_secret = "super-secret-value"
```

**After**
```python
client_secret = secrets_client.get_secret_value(SecretId=os.environ["API_SECRET_ID"])["SecretString"]
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html

## Rule: PY_EVAL_EXEC [CRITICAL]

**CWE**  CWE-95 — Improper Neutralization of Directives in Dynamically Evaluated Code ('Eval Injection')

**Description**  eval() or exec() called — code injection risk if argument contains user input

**AWS Lambda context**  Many Lambda handlers transform event data directly; evaluating request content gives the caller code execution inside the function role.

**Before**
```python
result = eval(event["expression"])
```

**After**
```python
result = ast.literal_eval(event["expression"])
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Injection_Prevention_Cheat_Sheet.html

## Rule: PY_SSRF_URLOPEN [HIGH]

**CWE**  CWE-918 — Server-Side Request Forgery (SSRF)

**Description**  urllib.request.urlopen() or requests call without HTTPS scheme validation

**AWS Lambda context**  Functions frequently call third-party APIs using URLs from event payloads or environment variables; validate before any outbound call.

**Before**
```python
response = urllib.request.urlopen(event["endpoint"]).read()
```

**After**
```python
parsed = urllib.parse.urlparse(event["endpoint"])
if parsed.scheme != "https" or not parsed.netloc:
    raise ValueError("HTTPS required")
response = urllib.request.urlopen(event["endpoint"]).read()
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html

## Rule: PY_INSECURE_DESERIALISE [HIGH]

**CWE**  CWE-502 — Deserialization of Untrusted Data

**Description**  Insecure deserialization: pickle.load/loads or yaml.load() without safe Loader

**AWS Lambda context**  SQS, EventBridge, and API Gateway payloads are untrusted inputs even if they originate from internal publishers.

**Before**
```python
obj = pickle.loads(event.get("blob", b""))
```

**After**
```python
obj = json.loads(event["blob"])
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Deserialization_Cheat_Sheet.html

## Rule: PY_CMD_INJECTION [HIGH]

**CWE**  CWE-78 — OS Command Injection

**Description**  Command injection risk: os.system/os.popen/subprocess with shell=True

**AWS Lambda context**  Even short-lived Lambda containers can access environment variables, IAM credentials, and mounted files once commands execute.

**Before**
```python
os.system(f"ls {event.get('path')}")
```

**After**
```python
subprocess.run(["ls", safe_path], check=True, shell=False)
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Injection_Prevention_Cheat_Sheet.html

## Rule: PY_WEAK_CRYPTO [HIGH]

**CWE**  CWE-327 — Use of a Broken or Risky Cryptographic Algorithm

**Description**  Weak cryptographic algorithm: MD5 or SHA-1 used — not suitable for security purposes

**AWS Lambda context**  Many Lambda handlers generate tokens or hashes for downstream systems; choose primitives that meet current security guidance.

**Before**
```python
digest = hashlib.md5(payload).hexdigest()
```

**After**
```python
digest = hashlib.sha256(payload).hexdigest()
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html

## Rule: PY_MISSING_TLS_VERIFY [HIGH]

**CWE**  CWE-295 — Improper Certificate Validation

**Description**  TLS certificate verification disabled: requests called with verify=False

**AWS Lambda context**  Lambda commonly calls public HTTPS endpoints; trust validation is a primary control against traffic interception.

**Before**
```python
requests.get(url, timeout=3, verify=False)
```

**After**
```python
requests.get(url, timeout=3)
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html

## Rule: PY_XXE_RISK [HIGH]

**CWE**  CWE-611 — Improper Restriction of XML External Entity Reference

**Description**  XML parsing without XXE protection — xml.etree.ElementTree is vulnerable to XXE attacks

**AWS Lambda context**  Lambda handlers consuming XML from S3, SQS, or partner integrations should assume XML is attacker-influenced.

**Before**
```python
from xml.etree.ElementTree import fromstring
root = fromstring(xml_body)
```

**After**
```python
from defusedxml.ElementTree import fromstring
root = fromstring(xml_body)
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/XML_External_Entity_Prevention_Cheat_Sheet.html

## Rule: PY_SQL_INJECTION [HIGH]

**CWE**  CWE-89 — SQL Injection

**Description**  Possible SQL injection — string formatting used to build a SQL query

**AWS Lambda context**  API Gateway and SQS events often flow directly to persistence logic; parameterisation is essential when handlers talk to RDS or Aurora.

**Before**
```python
cursor.execute(f"SELECT * FROM users WHERE id = {event["user_id"]}")
```

**After**
```python
cursor.execute("SELECT * FROM users WHERE id = %s", (event["user_id"],))
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html

## Rule: PY_LOG_INJECTION [MEDIUM]

**CWE**  CWE-117 — Improper Output Neutralization for Logs

**Description**  User-controlled value logged without sanitization — potential log injection

**AWS Lambda context**  Security teams often query CloudWatch Logs directly; malformed lines make investigations and alerting unreliable.

**Before**
```python
logger.info("customer=%s", event.get("customer_name"))
```

**After**
```python
logger.info("customer=%s", sanitize_for_log(event.get("customer_name")))
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html

## Rule: PY_SILENT_EXCEPT [MEDIUM]

**CWE**  CWE-390 — Detection of Error Condition Without Action

**Description**  Silent exception swallowing: except block with only 'pass' — errors are hidden

**AWS Lambda context**  Lambda retries and DLQs depend on correct error handling; swallowing exceptions can also hide partial failures.

**Before**
```python
try:
    cache.warm()
except Exception:
    pass
```

**After**
```python
try:
    cache.warm()
except Exception:
    logger.debug("Suppressed exception", exc_info=True)
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html

## Rule: PY_SENSITIVE_IN_RESPONSE [MEDIUM]

**CWE**  CWE-200 — Exposure of Sensitive Information to an Unauthorized Actor

**Description**  Sensitive key name in function return value — may expose secrets to caller

**AWS Lambda context**  Lambda outputs can be surfaced through API Gateway, Step Functions, SQS, or EventBridge and may be widely visible.

**Before**
```python
return {"password": password, "status": "ok"}
```

**After**
```python
return {"status": "ok"}
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/User_Privacy_Protection_Cheat_Sheet.html

## Rule: PY_MISSING_INPUT_VALIDATION [MEDIUM]

**CWE**  CWE-20 — Improper Input Validation

**Description**  Event parameter used in AWS API call without format validation

**AWS Lambda context**  Handlers often proxy request parameters into AWS APIs such as Connect or S3; validate format and shape first.

**Before**
```python
return _CONNECT_CLIENT.describe_contact(ContactId=event.get("contact_id"))
```

**After**
```python
contact_id = validate_contact_id(event.get("contact_id"))
return _CONNECT_CLIENT.describe_contact(ContactId=contact_id)
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html
