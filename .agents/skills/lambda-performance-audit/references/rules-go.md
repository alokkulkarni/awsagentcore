# Go Lambda Performance Rules

## Official AWS References
- https://docs.aws.amazon.com/lambda/latest/dg/golang-handler.html — Go handler programming model
- https://docs.aws.amazon.com/lambda/latest/dg/golang-best-practices.html — Go best practices
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtime-environment.html — Execution environment lifecycle
- https://aws.github.io/aws-sdk-go-v2/docs/ — AWS SDK for Go v2 documentation
- https://aws.github.io/aws-sdk-go-v2/docs/configuring-sdk/ — SDK v2 configuration
- https://aws.github.io/aws-sdk-go-v2/docs/configuring-sdk/retries-timeouts/ — Retries and timeouts
- https://pkg.go.dev/github.com/aws/aws-sdk-go-v2 — SDK v2 package reference
- https://pkg.go.dev/github.com/aws/aws-lambda-go/lambda — Lambda Go runtime package

## Runtime Requirements
- Go 1.21+ (compiled to `bootstrap` binary for `provided.al2023` runtime, or use the `go1.x` managed runtime)
- `github.com/aws/aws-sdk-go-v2` (not v1)
- `github.com/aws/aws-lambda-go`

## Key Concepts

### Execution Environment Reuse
Lambda freezes the process between invocations. Package-level variables declared with `var` survive across warm invocations. The `init()` function runs once during cold start. This means SDK clients should be created in `init()` and stored in package-level variables.

### AWS SDK for Go v2
SDK v2 is the current, actively maintained version. It has a different API from v1 — service clients are created with `service.NewFromConfig(cfg)` rather than `session.New()`.

---

## Rule: GO_CLIENT_IN_HANDLER [CRITICAL]

**What it means:** An AWS SDK client is created inside the handler function, not in `init()` or the `var` block.

**Why it matters:** Every warm invocation creates a new client with new TLS connections. Package-level variables survive the freeze/thaw cycle.

**Before (bad)**
```go
func handleRequest(ctx context.Context, event json.RawMessage) error {
    cfg, _ := config.LoadDefaultConfig(ctx)     // ← BAD: runs every invocation
    s3Client := s3.NewFromConfig(cfg)            // ← BAD
    _, err := s3Client.PutObject(ctx, &s3.PutObjectInput{...})
    return err
}
```

**After (correct)**
```go
import (
    "context"
    "net"
    "net/http"
    "time"

    "github.com/aws/aws-sdk-go-v2/config"
    "github.com/aws/aws-sdk-go-v2/service/s3"
)

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
    s3Client *s3.Client
)

func init() {
    cfg, err := config.LoadDefaultConfig(context.Background(),
        config.WithHTTPClient(httpClient),
        config.WithRetryer(func() aws.Retryer {
            return retry.AddWithMaxAttempts(retry.NewStandard(), 3)
        }),
    )
    if err != nil {
        log.Fatalf("unable to load SDK config: %v", err)
    }
    s3Client = s3.NewFromConfig(cfg)
}

func handleRequest(ctx context.Context, event json.RawMessage) error {
    log.Printf(`{"event":"lambda_invoked","function":"%s"}`, os.Getenv("AWS_LAMBDA_FUNCTION_NAME"))
    _, err := s3Client.PutObject(ctx, &s3.PutObjectInput{...})
    return err
}
```

---

## Rule: GO_SDK_V1_USAGE [HIGH]

**What it means:** The file imports `github.com/aws/aws-sdk-go` (v1).

**Why it matters:** SDK v1 is in maintenance mode. SDK v2 has a better API, context support, and middleware model.

**Migration guide:** https://aws.github.io/aws-sdk-go-v2/docs/migrating/

**Before (v1)**
```go
import (
    "github.com/aws/aws-sdk-go/aws"
    "github.com/aws/aws-sdk-go/aws/session"
    "github.com/aws/aws-sdk-go/service/s3"
)

sess := session.Must(session.NewSession())
svc := s3.New(sess)
```

**After (v2)**
```go
import (
    "github.com/aws/aws-sdk-go-v2/config"
    "github.com/aws/aws-sdk-go-v2/service/s3"
)

cfg, _ := config.LoadDefaultConfig(ctx)
svc := s3.NewFromConfig(cfg)
```

---

## Rule: GO_MISSING_HTTP_TRANSPORT [HIGH]

**What it means:** No custom `http.Transport` is configured for the SDK HTTP client.

**Why it matters:** Go's default `http.Transport` has conservative settings — only 2 idle connections per host, short keepalive. For high-concurrency Lambda functions, this limits throughput.

**Recommended settings:**
```go
httpClient = &http.Client{
    Transport: &http.Transport{
        DialContext: (&net.Dialer{
            Timeout:   5 * time.Second,
            KeepAlive: 30 * time.Second,
        }).DialContext,
        MaxIdleConns:          100,
        MaxIdleConnsPerHost:   10,
        IdleConnTimeout:       90 * time.Second,
        TLSHandshakeTimeout:   10 * time.Second,
        ExpectContinueTimeout: 1 * time.Second,
    },
    Timeout: 30 * time.Second,
}
```

---

## Rule: GO_CLIENT_NOT_IN_VAR_BLOCK [HIGH]

Declare all SDK clients in a package-level `var()` block:
```go
var (
    connectClient *connect.Client
    dynamoClient  *dynamodb.Client
)
```
Initialise them in `init()`. The Lambda runtime preserves the process between invocations, so the clients are reused.

---

## Rule: GO_MISSING_LOG_LEVEL [MEDIUM]

```go
func init() {
    lvl := os.Getenv("LOG_LEVEL")
    if lvl == "" {
        lvl = "INFO"
    }
    // configure slog/zerolog/zap with lvl
    slog.SetLogLoggerLevel(slog.LevelInfo) // example with slog
}
```

---

## Rule: GO_MISSING_INVOCATION_LOG [LOW]

```go
func handleRequest(ctx context.Context, event json.RawMessage) error {
    log.Printf(`{"event":"lambda_invoked","function":"%s","requestId":"%s"}`,
        os.Getenv("AWS_LAMBDA_FUNCTION_NAME"),
        lambdacontext.FromContext(ctx).AwsRequestID)
    // ...
}
```

