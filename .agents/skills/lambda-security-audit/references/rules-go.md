# Go Lambda Security Rules

## Official AWS References
- https://docs.aws.amazon.com/lambda/latest/dg/golang-handler.html — Handler programming model
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html — Lambda security best practices
- https://docs.aws.amazon.com/lambda/latest/dg/configuration-envvars.html#configuration-envvars-encryption — Environment variable encryption
- https://docs.aws.amazon.com/secretsmanager/latest/userguide/intro.html — Secrets Manager
- https://pkg.go.dev/github.com/aws/aws-lambda-go/lambda — aws-lambda-go runtime
- https://owasp.org/www-project-top-ten/ — OWASP Top 10 2021
- https://owasp.org/www-project-serverless-top-10/ — OWASP Serverless Top 10

## Rule: GO_PII_IN_LOG [CRITICAL]

**CWE**  CWE-532 — Insertion of Sensitive Information into Log File

**Description**  Full request/event struct logged with %v or %+v — PII/sensitive data exposure

**AWS Lambda context**  Go handlers often use fmt or log directly; %+v dumps everything inside an event struct into CloudWatch.

**Before**
```go
log.Printf("event=%+v", event)
```

**After**
```go
log.Printf("event=%q request_id=%s", event.Type, requestID)
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html

## Rule: GO_HARDCODED_SECRET [CRITICAL]

**CWE**  CWE-798 — Use of Hard-coded Credentials

**Description**  Possible hardcoded secret — sensitive variable assigned a string literal

**AWS Lambda context**  Statically linked Go Lambdas are distributed as a single binary, so any embedded credential is present everywhere that binary is copied.

**Before**
```go
password := "super-secret-password"
```

**After**
```go
password := mustGetSecret(ctx, os.Getenv("DB_SECRET_ID"))
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html

## Rule: GO_MISSING_TLS_VERIFY [HIGH]

**CWE**  CWE-295 — Improper Certificate Validation

**Description**  TLS verification disabled: InsecureSkipVerify: true

**AWS Lambda context**  Go Lambda functions often build custom transports; do not disable the most important TLS integrity control.

**Before**
```go
TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
```

**After**
```go
TLSClientConfig: &tls.Config{RootCAs: certPool},
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html

## Rule: GO_CMD_INJECTION [HIGH]

**CWE**  CWE-78 — OS Command Injection

**Description**  Command injection risk: exec.Command with user-controlled string

**AWS Lambda context**  Go Lambdas sometimes wrap system utilities for data processing; never hand request data straight to those helpers.

**Before**
```go
exec.Command(event.Command).Run()
```

**After**
```go
exec.Command("convert", safeFile).Run()
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Injection_Prevention_Cheat_Sheet.html

## Rule: GO_WEAK_CRYPTO [HIGH]

**CWE**  CWE-327 — Use of a Broken or Risky Cryptographic Algorithm

**Description**  Weak cryptographic algorithm: crypto/md5 or crypto/sha1 used

**AWS Lambda context**  Go handlers frequently compute hashes for signed URLs or cache keys; weak algorithms should be avoided for security uses.

**Before**
```go
sum := md5.New()
```

**After**
```go
sum := sha256.New()
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html

## Rule: GO_SQL_INJECTION [HIGH]

**CWE**  CWE-89 — SQL Injection

**Description**  Possible SQL injection — fmt.Sprintf used to build SQL query string

**AWS Lambda context**  Serverless backends routinely bridge API requests to Aurora or RDS; parameter binding is essential.

**Before**
```go
query := fmt.Sprintf("SELECT * FROM users WHERE id = %s", userID)
```

**After**
```go
rows, err := db.QueryContext(ctx, "SELECT * FROM users WHERE id = $1", userID)
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html

## Rule: GO_SILENT_ERROR [MEDIUM]

**CWE**  CWE-390 — Detection of Error Condition Without Action

**Description**  Error silently discarded with blank identifier: _ = err

**AWS Lambda context**  Lambda invocations are short; if you discard an error there may be no other chance to see the failure.

**Before**
```go
_ = err
```

**After**
```go
if err != nil {
    log.Printf("operation failed: %v", err)
}
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html

## Rule: GO_LOG_INJECTION [MEDIUM]

**CWE**  CWE-117 — Improper Output Neutralization for Logs

**Description**  User-controlled value passed to log.Printf — potential log injection

**AWS Lambda context**  Printf-style logs are common in Go Lambdas; quote untrusted strings to keep log structure intact.

**Before**
```go
log.Printf("user=%s", event.UserInput)
```

**After**
```go
log.Printf("user=%q", sanitizeForLog(event.UserInput))
```

**References**
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
