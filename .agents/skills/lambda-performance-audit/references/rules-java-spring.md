# Java / Spring Lambda Performance Rules

## Official AWS References
- https://docs.aws.amazon.com/lambda/latest/dg/java-handler.html — Java handler programming model
- https://docs.aws.amazon.com/lambda/latest/dg/java-best-practices.html — Java best practices
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtime-environment.html — Execution environment lifecycle
- https://docs.aws.amazon.com/lambda/latest/dg/snapstart.html — Lambda SnapStart for Java
- https://docs.aws.amazon.com/lambda/latest/dg/java-tracing.html — X-Ray tracing for Java
- https://sdk.amazonaws.com/java/api/latest/ — AWS SDK for Java v2 API reference
- https://docs.aws.amazon.com/sdk-for-java/latest/developer-guide/http-configuration.html — SDK HTTP client configuration
- https://docs.aws.amazon.com/sdk-for-java/latest/developer-guide/retry-strategy.html — Retry strategies
- https://docs.spring.io/spring-cloud-function/docs/current/reference/html/ — Spring Cloud Function reference
- https://github.com/awslabs/aws-lambda-powertools-java — AWS Lambda Powertools for Java
- https://docs.aws.amazon.com/sdk-for-java/latest/developer-guide/migrate.html — SDK v1 to v2 migration

## Runtime Requirements
- Java 11, 17, or 21 (Lambda managed runtime)
- AWS SDK for Java v2 (`software.amazon.awssdk.*`)
- `aws-lambda-java-core` for the RequestHandler interface
- `aws-lambda-java-events` for typed event objects

## Key Concepts

### Static Initialization
Java class static members are initialised once when the class is first loaded — during the cold start. `private static final` clients survive across warm invocations. Never create clients inside `handleRequest()`.

### Spring Cloud Function
If using Spring Boot with Lambda, use `spring-cloud-function-adapter-aws`. The `FunctionInvoker` class handles the Lambda integration and allows Spring DI to manage clients as beans.

### SnapStart (Java 21)
AWS Lambda SnapStart takes a snapshot of the initialized execution environment and restores it for subsequent invocations, drastically reducing cold starts. Requires the function to implement `org.crac.Resource` to handle the checkpoint lifecycle correctly.

---

## Rule: JAVA_CLIENT_IN_HANDLER [CRITICAL]

**What it means:** An AWS SDK client is instantiated inside `handleRequest()`.

**Why it matters:** Every invocation creates a new client, new connection pool, and possibly refreshes credentials. Static initialization runs once at cold start and is reused.

**Before (bad)**
```java
public String handleRequest(Map<String,Object> event, Context context) {
    ConnectClient client = ConnectClient.builder().build(); // ← BAD
    return client.listQueues(r -> r.instanceId(instanceId)).toString();
}
```

**After (correct)**
```java
import software.amazon.awssdk.http.apache.ApacheHttpClient;
import software.amazon.awssdk.core.retry.RetryPolicy;
import software.amazon.awssdk.services.connect.ConnectClient;
import java.time.Duration;

public class MyHandler implements RequestHandler<Map<String,Object>, String> {

    // Static final — initialised once at cold start, reused on warm invocations
    private static final ConnectClient CONNECT_CLIENT = ConnectClient.builder()
        .httpClientBuilder(ApacheHttpClient.builder()
            .maxConnections(50)
            .connectionTimeout(Duration.ofSeconds(5))
            .socketTimeout(Duration.ofSeconds(15)))
        .overrideConfiguration(c -> c
            .retryPolicy(RetryPolicy.builder().numRetries(3).build()))
        .build();

    @Override
    public String handleRequest(Map<String,Object> event, Context context) {
        context.getLogger().log("{\"event\":\"lambda_invoked\",\"function\":\"" + context.getFunctionName() + "\"}");
        return CONNECT_CLIENT.listQueues(r -> r.instanceId((String) event.get("instanceId"))).toString();
    }
}
```

---

## Rule: JAVA_SDK_V1_USAGE [HIGH]

**What it means:** The file imports `com.amazonaws.*` (AWS SDK for Java v1).

**Why it matters:** SDK v1 is in maintenance mode. SDK v2 has a fluent builder API, better async support, and is actively maintained.

**Before (v1)**
```java
import com.amazonaws.services.connect.AmazonConnect;
import com.amazonaws.services.connect.AmazonConnectClientBuilder;

AmazonConnect client = AmazonConnectClientBuilder.defaultClient();
```

**After (v2)**
```java
import software.amazon.awssdk.services.connect.ConnectClient;

ConnectClient client = ConnectClient.builder().build();
```

**Migration guide:** https://docs.aws.amazon.com/sdk-for-java/latest/developer-guide/migrate.html

---

## Rule: JAVA_MISSING_HTTP_CLIENT_CONFIG [HIGH]

**What it means:** SDK client built without explicit HTTP client configuration.

**Why it matters:** Default settings may not be optimised for Lambda's concurrency model. Explicit configuration ensures proper connection pool sizing and timeout values.

**After (ApacheHttpClient — sync)**
```java
import software.amazon.awssdk.http.apache.ApacheHttpClient;
import java.time.Duration;

private static final S3Client S3_CLIENT = S3Client.builder()
    .httpClientBuilder(ApacheHttpClient.builder()
        .maxConnections(50)
        .connectionTimeout(Duration.ofSeconds(5))
        .socketTimeout(Duration.ofSeconds(15))
        .connectionTimeToLive(Duration.ofSeconds(60)))
    .build();
```

**After (UrlConnectionHttpClient — lighter, no Apache dependency)**
```java
import software.amazon.awssdk.http.urlconnection.UrlConnectionHttpClient;

private static final S3Client S3_CLIENT = S3Client.builder()
    .httpClientBuilder(UrlConnectionHttpClient.builder()
        .connectionTimeout(Duration.ofSeconds(5))
        .socketTimeout(Duration.ofSeconds(15)))
    .build();
```

---

## Rule: JAVA_NO_STATIC_CLIENT [HIGH]

All AWS SDK clients must be `private static final` class members:

```java
public class OrderHandler implements RequestHandler<Order, String> {
    private static final S3Client        S3_CLIENT  = S3Client.builder()...build();
    private static final DynamoDbClient  DDB_CLIENT = DynamoDbClient.builder()...build();
    private static final ConnectClient   CON_CLIENT = ConnectClient.builder()...build();
}
```

---

## Rule: JAVA_MISSING_RETRY_CONFIG [HIGH]

```java
import software.amazon.awssdk.core.retry.RetryPolicy;
import software.amazon.awssdk.core.retry.backoff.FullJitterBackoffStrategy;
import java.time.Duration;

private static final ConnectClient CLIENT = ConnectClient.builder()
    .overrideConfiguration(c -> c.retryPolicy(RetryPolicy.builder()
        .numRetries(3)
        .backoffStrategy(FullJitterBackoffStrategy.builder()
            .baseDelay(Duration.ofMillis(100))
            .maxBackoffTime(Duration.ofSeconds(5))
            .build())
        .build()))
    .build();
```

---

## Rule: JAVA_SNAPSTART_NOT_CONSIDERED [MEDIUM]

SnapStart takes a snapshot after class initialization. To safely use it, implement `org.crac.Resource`:

```xml
<!-- pom.xml -->
<dependency>
    <groupId>org.crac</groupId>
    <artifactId>crac</artifactId>
    <version>1.4.0</version>
</dependency>
```

```java
import org.crac.Context;
import org.crac.Core;
import org.crac.Resource;

public class MyHandler implements RequestHandler<Order, String>, Resource {

    static {
        Core.getGlobalContext().register(new MyHandler());
    }

    @Override
    public void beforeCheckpoint(Context<? extends Resource> context) throws Exception {
        // Warm up connections, pre-load config, etc.
    }

    @Override
    public void afterRestore(Context<? extends Resource> context) throws Exception {
        // Re-open any closed resources if needed
    }
}
```

**Reference:** https://docs.aws.amazon.com/lambda/latest/dg/snapstart.html

---

## Rule: JAVA_MISSING_INVOCATION_LOG [LOW]

```java
@Override
public String handleRequest(Map<String,Object> event, Context context) {
    context.getLogger().log(String.format(
        "{\"event\":\"lambda_invoked\",\"function\":\"%s\",\"requestId\":\"%s\"}",
        context.getFunctionName(), context.getAwsRequestId()
    ));
    // ...
}
```

**With AWS Lambda Powertools for Java:**
```java
@Logging(logEvent = true)
public String handleRequest(Map<String,Object> event, Context context) {
    // Powertools automatically logs structured invocation data
}
```

