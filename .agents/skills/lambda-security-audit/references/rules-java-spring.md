# Java / Spring Lambda Security Rules

## Official AWS References
- https://docs.aws.amazon.com/lambda/latest/dg/java-handler.html — Handler programming model
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html — Lambda security best practices
- https://docs.aws.amazon.com/lambda/latest/dg/security-iam.html — Least-privilege IAM guidance
- https://docs.aws.amazon.com/lambda/latest/dg/configuration-envvars.html#configuration-envvars-encryption — Environment variable encryption
- https://docs.aws.amazon.com/secretsmanager/latest/userguide/intro.html — Secrets Manager
- https://owasp.org/www-project-top-ten/ — OWASP Top 10 2021
- https://owasp.org/www-project-serverless-top-10/ — OWASP Serverless Top 10

## Rule: JAVA_PII_IN_LOG [CRITICAL]

**CWE**  CWE-532 — Insertion of Sensitive Information into Log File

**Description**  Full request/event object logged with toString() or directly — PII/sensitive data exposure

**AWS Lambda context**  Java event objects frequently include nested request metadata; toString() often serializes all of it.

**Before**
```java
log.info("request={}", request.toString());
```

**After**
```java
log.info("requestId={} status={}", request.getRequestId(), request.getStatus());
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html

## Rule: JAVA_HARDCODED_SECRET [CRITICAL]

**CWE**  CWE-798 — Use of Hard-coded Credentials

**Description**  Possible hardcoded secret — sensitive field assigned a string literal

**AWS Lambda context**  Java Lambda artifacts are commonly reused across stages; one leaked literal can compromise every deployment.

**Before**
```java
private static final String password = "super-secret-password";
```

**After**
```java
@Value("${app.db.password}")
private String password;
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html

## Rule: JAVA_CMD_INJECTION [HIGH]

**CWE**  CWE-78 — OS Command Injection

**Description**  Command injection risk: Runtime.exec() or ProcessBuilder with user input

**AWS Lambda context**  Java Lambdas often invoke helper binaries for document conversion or image processing; validate every argument.

**Before**
```java
Runtime.getRuntime().exec(input);
```

**After**
```java
new ProcessBuilder("convert", safeFile).start();
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Injection_Prevention_Cheat_Sheet.html

## Rule: JAVA_MISSING_TLS_VERIFY [HIGH]

**CWE**  CWE-295 — Improper Certificate Validation

**Description**  TLS verification disabled: TrustAllCerts or NoopHostnameVerifier in use

**AWS Lambda context**  Java HTTP clients are commonly shared across invocations; insecure TLS settings then affect every outbound call.

**Before**
```java
builder.setSSLHostnameVerifier(NoopHostnameVerifier.INSTANCE);
```

**After**
```java
builder.setSSLContext(sslContextFromTrustStore());
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html

## Rule: JAVA_WEAK_CRYPTO [HIGH]

**CWE**  CWE-327 — Use of a Broken or Risky Cryptographic Algorithm

**Description**  Weak cryptographic algorithm: MD5 or SHA-1 MessageDigest in use

**AWS Lambda context**  Java Lambdas frequently hash identifiers or credentials before calling downstream services; use current algorithms.

**Before**
```java
MessageDigest md = MessageDigest.getInstance("MD5");
```

**After**
```java
MessageDigest md = MessageDigest.getInstance("SHA-256");
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html

## Rule: JAVA_XXE_RISK [HIGH]

**CWE**  CWE-611 — Improper Restriction of XML External Entity Reference

**Description**  XXE risk: DocumentBuilderFactory or SAXParserFactory without XXE protection features disabled

**AWS Lambda context**  Spring and Java Lambdas often process SOAP, XML feeds, or uploaded files; secure parser configuration is mandatory.

**Before**
```java
DocumentBuilderFactory dbf = DocumentBuilderFactory.newInstance();
```

**After**
```java
DocumentBuilderFactory dbf = DocumentBuilderFactory.newInstance();
dbf.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/XML_External_Entity_Prevention_Cheat_Sheet.html

## Rule: JAVA_SQL_INJECTION [HIGH]

**CWE**  CWE-89 — SQL Injection

**Description**  Possible SQL injection — string concatenation used to build SQL query

**AWS Lambda context**  Java/Spring Lambdas often expose HTTP APIs backed by relational stores; prepared statements maintain the trust boundary.

**Before**
```java
String sql = "SELECT * FROM users WHERE id = " + userId;
```

**After**
```java
PreparedStatement ps = conn.prepareStatement("SELECT * FROM users WHERE id = ?");
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html

## Rule: JAVA_SILENT_CATCH [MEDIUM]

**CWE**  CWE-390 — Detection of Error Condition Without Action

**Description**  Empty catch block — exception silently swallowed

**AWS Lambda context**  Java Lambdas integrate with retries, DLQs, and alarms; silent catches break those safety mechanisms.

**Before**
```java
try {
    refresh();
} catch (Exception e) {}
```

**After**
```java
try {
    refresh();
} catch (Exception e) {
    log.debug("Suppressed exception", e);
}
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html

## Rule: JAVA_LOG_INJECTION [MEDIUM]

**CWE**  CWE-117 — Improper Output Neutralization for Logs

**Description**  User-controlled value concatenated directly into log statement

**AWS Lambda context**  Structured Java logging is common in Lambda; preserve safe formatting so CloudWatch parsing stays reliable.

**Before**
```java
log.info("user=" + request.getUserInput());
```

**After**
```java
log.info("user={}", sanitize(request.getUserInput()));
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
