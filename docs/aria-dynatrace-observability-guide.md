# ARIA Meridian Bank — Dynatrace Observability & Monitoring Guide

**Version:** 1.0  
**Status:** Production Reference  
**Audience:** Service Introduction · Run Teams · Service Managers · Change Engineering

---

## Contents

- [M.1 Purpose and Scope](#m1-purpose-and-scope)
- [M.2 The ARIA Stack — Component Inventory](#m2-the-aria-stack--component-inventory)
- [M.3 Dynatrace Integration Architecture](#m3-dynatrace-integration-architecture)
- [M.4 AWS Connection Setup — Metric Streams](#m4-aws-connection-setup--metric-streams)
- [M.5 AWS Log Forwarding — Data Firehose](#m5-aws-log-forwarding--data-firehose)
- [M.6 Lambda Instrumentation — OpenTelemetry](#m6-lambda-instrumentation--opentelemetry)
- [M.7 Business Events (BizEvents) — Customer Journey Tracking](#m7-business-events-bizevents--customer-journey-tracking)
- [M.8 Configuration Item (CI) Mapping](#m8-configuration-item-ci-mapping)
- [M.9 Tag Taxonomy](#m9-tag-taxonomy)
- [M.10 CloudWatch Metrics Reference](#m10-cloudwatch-metrics-reference)
- [M.11 Distributed Tracing — End-to-End Customer Journey](#m11-distributed-tracing--end-to-end-customer-journey)
- [M.12 Alerting Strategy](#m12-alerting-strategy)
- [M.13 SLO / SLA Framework](#m13-slo--sla-framework)
- [M.14 Dashboard Specifications](#m14-dashboard-specifications)
- [M.15 Operational Testing — Synthetic Monitoring](#m15-operational-testing--synthetic-monitoring)
- [M.16 Change Engineering Integration](#m16-change-engineering-integration)
- [M.17 Runbooks for Run Teams](#m17-runbooks-for-run-teams)
- [M.18 Team Responsibilities & Onboarding](#m18-team-responsibilities--onboarding)

---

## M.1 Purpose and Scope

### What This Document Is

This guide explains how **all components of the ARIA Meridian Bank AI Banking Assistant** are monitored, alerted, and traced through **Dynatrace**. It is written assuming the reader may be new to Dynatrace but understands the basics of AWS and contact centre operations.

### Who Needs This Document

| Team | What They Use It For |
|------|---------------------|
| **Service Introduction** | Onboarding ARIA components into Dynatrace; setting up initial monitoring and CI mapping |
| **Run Teams** | Day-to-day operations; responding to alerts; using dashboards to monitor live traffic |
| **Service Managers** | Business journey dashboards; SLO compliance; reporting on AI agent performance |
| **Change Engineering** | Deployment markers; Davis AI problem correlation; rollback triggers; change tracking |

### What ARIA Is

ARIA (AI Retail & Institutional Assistant) is a conversational AI banking assistant deployed on **Amazon Connect** (the contact centre platform) that handles voice and chat interactions for Meridian Bank customers. When ARIA cannot help, it escalates to a human agent. The system uses:

- Amazon Connect for telephony and chat
- Amazon Lex V2 to understand what customers are saying
- AWS Bedrock AgentCore to power the AI reasoning and tool use
- Multiple AWS Lambda functions as the "glue" between services
- DynamoDB for routing configuration
- KMS for encrypting sensitive data (e.g. card numbers entered via phone keypad)
- Amazon Data Firehose + S3 for audit logs

---

## M.2 The ARIA Stack — Component Inventory

This is every AWS component that forms the ARIA system. All of these are monitored through Dynatrace.

### Core Customer-Facing Services

| Component | AWS Service | Resource Name | Role |
|-----------|------------|---------------|------|
| Contact Centre | Amazon Connect | `meridian-aria` instance | Receives phone calls and chats |
| AI Bot | Amazon Lex V2 | ARIA bot | Understands intent, routes to AI or human |
| AI Agent Runtime | AWS Bedrock AgentCore | `aria-meridian-bank-gateway` | Powers AI reasoning and tool calls |
| MCP Gateway | Bedrock AgentCore MCP | `aria-meridian-bank-gateway` | Exposes banking tools to the AI |
| Chat Widget | Amazon CloudFront + S3 | `meridian-aria-client-{deploy_id}` | Embeds chat on bank website |

### Lambda Functions

Every Lambda function listed below is deployed by the ARIA deploy scripts. Each has its own IAM role with least-privilege permissions.

| Function Name | Source File | Purpose |
|---------------|------------|---------|
| `aria-lex-fulfillment` | `aria_connect_fulfillment.py` | Bridge between Lex V2 and Bedrock AgentCore; handles chat + voice |
| `aria-session-injector` | `session_injector.py` | Pre-fetches customer ID by phone number before Lex; sets auth status |
| `aria-session-injector-qconnect` | `session_injector_qconnect.py` | Amazon Q Connect version of session injector |
| `aria-routing-lookup` | `aria_routing_lookup.py` | Resolves which Connect queue to route a call to based on topic |
| `aria-dtmf-decrypt` | `aria_dtmf_decrypt.py` | Decrypts card/account numbers collected via DTMF keypad tones |
| `aria-callback-scheduler` | `aria_callback_scheduler.py` | Resolves dedicated callback queue ID for each topic category |
| `aria-audit-cloudtrail-writer` | `audit_cloudtrail_writer.py` | Writes audit events to CloudTrail Lake |
| `aria-audit-dynamodb-writer` | `audit_dynamodb_writer.py` | Writes audit events to DynamoDB audit table |

### Data Stores

| Resource | AWS Service | Purpose |
|----------|------------|---------|
| `aria-routing-config` | DynamoDB | Queue routing and callback queue configuration |
| `aria-audit-events` | DynamoDB | Audit event ledger (TTL 90 days) |
| `meridian-aria-transcripts-{deploy_id}` | S3 | Call/chat transcript storage |
| `meridian-aria-audit-{deploy_id}` | S3 | Long-term audit archive |
| `meridian-aria-client-{deploy_id}` | S3 | Chat widget static assets |

### Security & Compliance

| Resource | AWS Service | Purpose |
|----------|------------|---------|
| DTMF RSA CMK | AWS KMS | Encrypts RSA private key used for DTMF data decryption |
| DTMF RSA private key | Secrets Manager | Stores RSA private key for `aria-dtmf-decrypt` |
| ARIA Cognito Identity Pool | Amazon Cognito | WebSocket authentication for chat widget |

### Integration Fabric

| Resource | AWS Service | Purpose |
|----------|------------|---------|
| `aria-audit` | EventBridge custom bus | Carries audit events between Lambdas |
| `aria-banking-audit` / `aria-banking-audit-{deploy_id}` | EventBridge rule | Routes events to audit writer Lambdas |
| `aria-audit-firehose` | Kinesis Data Firehose | Delivers audit events to S3 archive |
| Connect ↔ Lex integration | Amazon Connect | Native Lex V2 bot integration within Connect flows |
| Amazon Q Connect integration | Amazon Q Connect | Knowledge base surfaced to agents during calls |

---

## M.3 Dynatrace Integration Architecture

### Plain-English Explanation

Think of Dynatrace as a "control room" that watches everything happening inside AWS. To get data into this control room, you set up three "pipelines":

1. **Metric Streams** — AWS continuously pushes performance numbers (how fast, how many errors) to Dynatrace every 60 seconds. This is like a live dashboard feed.
2. **Log Streaming via Firehose** — Lambda and other AWS services write logs to CloudWatch; Firehose picks them up and delivers them to Dynatrace in near-real time.
3. **OpenTelemetry traces** — Lambda functions emit trace spans directly to Dynatrace's OTLP endpoint so you can see the exact journey of each customer call end-to-end.

### Architecture Diagram

```
┌─────────────────────────── AWS Account ───────────────────────────────┐
│                                                                          │
│  Amazon Connect ──► Lex V2 ──► aria-lex-fulfillment ──► Bedrock         │
│        │                              │                  AgentCore       │
│        │              aria-session-injector                │             │
│        │              aria-routing-lookup              MCP Gateway       │
│        │              aria-dtmf-decrypt                    │             │
│        │              aria-callback-scheduler              │             │
│        │              aria-audit-*                         │             │
│        │                                                                 │
│  ┌─────┴──────────────────────────────────────────────────┐             │
│  │               AWS Observability Layer                   │             │
│  │                                                          │             │
│  │   CloudWatch Metrics ──► CloudWatch Metric Streams ──►  │             │
│  │   CloudWatch Logs    ──► Kinesis Data Firehose      ──►  │──► Dynatrace
│  │   Lambda OTel Spans  ──────────────────────────────────►  │             │
│  └─────────────────────────────────────────────────────────┘             │
└──────────────────────────────────────────────────────────────────────────┘
                                                       │
                                          ┌────────────▼─────────────┐
                                          │  Dynatrace SaaS Tenant   │
                                          │  {your-environment-id}   │
                                          │  .live.dynatrace.com     │
                                          │                          │
                                          │  • Davis AI Engine       │
                                          │  • Dashboards            │
                                          │  • Alert Policies        │
                                          │  • SLOs                  │
                                          │  • BizEvents             │
                                          │  • Synthetic Monitors    │
                                          └──────────────────────────┘
```

### Dynatrace Tenant Details

Before starting setup, you will need to know:

| Item | Value |
|------|-------|
| Dynatrace Environment ID | `{your-environment-id}` ← fill in at setup |
| Dynatrace SaaS URL | `https://{your-environment-id}.live.dynatrace.com` |
| OTLP Endpoint | `https://{your-environment-id}.live.dynatrace.com/api/v2/otlp` |
| Metric Streams endpoint (EU) | `https://eu.aws.cloud.dynatrace.com/` |
| AWS Region | `eu-west-2` (London) |

---

## M.4 AWS Connection Setup — Metric Streams

### What This Does

CloudWatch Metric Streams pushes **all AWS performance metrics** from the ARIA-related services to Dynatrace every 60 seconds. This is the most comprehensive and low-latency method.

You need to do this **once** per AWS account/region pair.

### Step-by-Step Setup

#### Step M.4.1 — Create a Dynatrace API Token

1. In Dynatrace, open the left-hand menu and go to **Access tokens** (search for it or find it under **Settings → Integration → Dynatrace API**).
2. Click **Generate new token**.
3. Give it a name: `aria-aws-metric-streams`.
4. Enable these permissions (scroll through the list):
   - **Ingest metrics** (`metrics.ingest`)
   - **Read metrics** (`metrics.read`)
5. Click **Generate** and **copy the token immediately** — you won't see it again.
6. Store it in AWS Secrets Manager as `aria-dynatrace-api-token` for safe keeping.

#### Step M.4.2 — Deploy the Metric Streams Client

Open a terminal where you have the AWS CLI configured for the Meridian Bank AWS account.

```bash
# Set your values
DYNATRACE_ENV_URL="https://{your-environment-id}.live.dynatrace.com"
DYNATRACE_API_KEY="dt0c01.{your-token}"
STACK_NAME="dynatrace-aws-metric-streams-client"
# Use EU endpoint since the AWS region is eu-west-2
DELIVERY_ENDPOINT="https://eu.aws.cloud.dynatrace.com/"
REQUIRE_VALID_CERTIFICATE=true

# Download the CloudFormation template and deploy
wget -O dynatrace-aws-metric-streams-client.yaml \
  https://assets.cloud.dynatrace.com/awsmetricstreaming/dynatrace-aws-metric-streams-client.yaml

aws cloudformation deploy \
  --capabilities CAPABILITY_NAMED_IAM \
  --template-file ./dynatrace-aws-metric-streams-client.yaml \
  --stack-name $STACK_NAME \
  --region eu-west-2 \
  --parameter-overrides \
    DynatraceEnvironmentUrl=$DYNATRACE_ENV_URL \
    DynatraceApiKey=$DYNATRACE_API_KEY \
    RequireValidCertificate=$REQUIRE_VALID_CERTIFICATE \
    FirehoseHttpDeliveryEndpoint=$DELIVERY_ENDPOINT
```

**This takes about 5 minutes to deploy.**

#### Step M.4.3 — Verify the Deployment

1. Go to **AWS Console → CloudFormation**.
2. Find the stack `dynatrace-aws-metric-streams-client`.
3. Click the **Events** tab — all events should show `CREATE_COMPLETE`.
4. In Dynatrace, go to **Infrastructure → Technologies & Processes**. Within a few minutes you should see entries for `AWS/Lambda`, `AWS/DynamoDB`, etc.

#### Step M.4.4 — Restrict Metrics to ARIA Namespaces

By default, ALL CloudWatch namespaces are streamed (this includes RDS, EC2, etc. that are unrelated to ARIA). To reduce cost and noise:

1. Go to **AWS Console → CloudWatch → Metrics → Streams**.
2. Find the stream created by the CloudFormation stack (look for `dynatrace-` in the name).
3. Click **Edit**.
4. Under **Metrics to be streamed**, choose **Selected namespaces**.
5. Select exactly these namespaces:

| Namespace | What It Covers |
|-----------|---------------|
| `AWS/Connect` | Amazon Connect call centre |
| `AWS/Lambda` | All Lambda functions |
| `AWS/Lex` | Lex V2 AI bot |
| `AWS/DynamoDB` | Routing and audit tables |
| `AWS/ApiGateway` | API Gateway (WebSocket) |
| `AWS/CloudFront` | Chat widget CDN |
| `AWS/SecretsManager` | DTMF key access |
| `AWS/Firehose` | Audit Firehose delivery |
| `AWS/Events` | EventBridge audit bus |
| `AWS/Bedrock` | Bedrock AI agent |

6. Click **Save changes**.

### Metric Key Prefix in Dynatrace

Metrics ingested via Metric Streams are available in Dynatrace with the prefix `cloud.aws.<service>`. Examples:

- `cloud.aws.lambda.duration` — Lambda execution time
- `cloud.aws.connect.contactsinqueue` — contacts waiting in queue
- `cloud.aws.dynamodb.successfulrequestlatency` — DynamoDB response time

---

## M.5 AWS Log Forwarding — Data Firehose

### What This Does

Lambda functions write their output (including errors and trace information) to CloudWatch Logs. This step sets up a Kinesis Data Firehose delivery stream that continuously reads those logs and forwards them to Dynatrace's Logs & Events viewer.

> **Important:** AWS deprecated the older "Dynatrace Log Forwarder" Lambda in December 2024. **Always use the Firehose method** described here.

### Step M.5.1 — Create the Firehose Log Delivery Stream

```bash
# Set your values
DYNATRACE_API_URL="https://{your-environment-id}.live.dynatrace.com"
DYNATRACE_API_KEY="dt0c01.{your-logs-token}"    # needs 'Ingest logs' permission
LOG_STACK_NAME="dynatrace-log-delivery-stream"

# Download and deploy
wget -O dynatrace-firehose-log-stream.yaml \
  https://assets.cloud.dynatrace.com/awslogstreaming/dynatrace-firehose-log-stream.yaml

aws cloudformation deploy \
  --capabilities CAPABILITY_NAMED_IAM \
  --template-file ./dynatrace-firehose-log-stream.yaml \
  --stack-name $LOG_STACK_NAME \
  --region eu-west-2 \
  --parameter-overrides \
    DtApiUrl=$DYNATRACE_API_URL \
    DtApiToken=$DYNATRACE_API_KEY
```

### Step M.5.2 — Note the Stack Outputs

After deployment:

1. In **CloudFormation**, select the log stack.
2. Click the **Outputs** tab.
3. Note down:
   - `FirehoseArn` — the ARN of the Firehose stream (you'll need this later)
   - `CloudWatchSubscriptionFilterRoleArn` — IAM role for CloudWatch to push to Firehose

### Step M.5.3 — Subscribe Lambda Log Groups

Download the subscription script and subscribe all ARIA log groups:

```bash
# Download the helper script
wget -O dynatrace-firehose-logs.sh \
  https://assets.cloud.dynatrace.com/awslogstreaming/dynatrace-firehose-logs.sh
chmod +x dynatrace-firehose-logs.sh

# Subscribe all ARIA Lambda log groups in one command
./dynatrace-firehose-logs.sh subscribe \
  --stack-name $LOG_STACK_NAME \
  --log-groups \
    /aws/lambda/aria-lex-fulfillment \
    /aws/lambda/aria-session-injector \
    /aws/lambda/aria-session-injector-qconnect \
    /aws/lambda/aria-routing-lookup \
    /aws/lambda/aria-dtmf-decrypt \
    /aws/lambda/aria-callback-scheduler \
    /aws/lambda/aria-audit-cloudtrail-writer \
    /aws/lambda/aria-audit-dynamodb-writer
```

### Step M.5.4 — Subscribe CloudTrail and EventBridge Logs

```bash
# Subscribe CloudTrail logs (if sending to CloudWatch)
./dynatrace-firehose-logs.sh subscribe \
  --stack-name $LOG_STACK_NAME \
  --log-groups \
    /aws/cloudtrail/aria-audit \
    /aws/events/aria-audit
```

### Step M.5.5 — Verify Log Ingestion

1. In Dynatrace, go to **Logs & Events** (left menu).
2. In the filter bar, type `aws.region = eu-west-2`.
3. Within 5 minutes of the first Lambda invocation, you should see log entries.
4. To verify Lambda entity linking, filter for `aws.lambda.function_name = aria-lex-fulfillment`. Logs should automatically show the function name as an enrichment attribute.

### Log Attributes Added by Firehose

Dynatrace automatically enriches each log record with:

| Attribute | Example Value |
|-----------|--------------|
| `aws.data_firehose.arn` | ARN of the Firehose stream |
| `aws.lambda.function_name` | `aria-lex-fulfillment` |
| `aws.lambda.function_version` | `production` (alias) |
| `aws.region` | `eu-west-2` |
| `aws.account.id` | `{your-account-id}` |

---

## M.6 Lambda Instrumentation — OpenTelemetry

### What This Does

OpenTelemetry (OTel) instrumentation makes Lambda functions emit **distributed traces** to Dynatrace. A trace is like a timeline showing exactly what happened during one customer call — which Lambda was called, how long it took, what it called next, and whether it succeeded.

This is the most powerful observability feature: you can click on a failed customer interaction and see exactly which step failed and why.

### Why OpenTelemetry (Not OneAgent)

Dynatrace offers two methods to instrument Lambda:

| Method | Pros | Cons |
|--------|------|------|
| **OpenTelemetry (OTLP)** | AWS-native, vendor-neutral, works with ADOT Lambda layer | Manual instrumentation of business logic |
| **Dynatrace OneAgent Extension** | Automatic, deep | Requires Dynatrace Extension layer ARN per version; locked to Dynatrace |

**Recommendation: Use OpenTelemetry (ADOT)** — it is the AWS-recommended approach, uses an AWS-managed Lambda layer, and avoids vendor lock-in.

### Step M.6.1 — Create an API Token for OTel

In Dynatrace, create a second API token (or extend the existing one) with:
- **Ingest OpenTelemetry traces** (`openTelemetryTrace.ingest`)
- **Ingest metrics** (`metrics.ingest`)
- **Ingest logs** (`logs.ingest`)

Name it `aria-lambda-otel`.

### Step M.6.2 — Add the ADOT Lambda Layer

The **AWS Distro for OpenTelemetry (ADOT)** provides a Lambda layer that auto-instruments Python functions without code changes.

For each ARIA Lambda function, add the layer ARN. For Python 3.12 in eu-west-2:

```bash
# The ADOT layer for Python in eu-west-2
ADOT_LAYER_ARN="arn:aws:lambda:eu-west-2:901920570463:layer:aws-otel-python-amd64-ver-1-30-0:1"

# Add to a Lambda function
aws lambda update-function-configuration \
  --function-name aria-lex-fulfillment \
  --layers $ADOT_LAYER_ARN \
  --region eu-west-2
```

> **Note:** Check https://aws-otel.github.io/docs/getting-started/lambda for the latest ADOT layer version for Python/eu-west-2. The version number changes with releases.

### Step M.6.3 — Set Environment Variables on All Lambda Functions

Each Lambda function needs three environment variables to send traces to Dynatrace:

```bash
DT_ENV_ID="{your-environment-id}"
DT_OTEL_TOKEN="dt0c01.{your-otel-token}"

# Function to update OTel env vars on a Lambda
update_otel_env() {
    local fn=$1
    local service_name=$2
    
    aws lambda update-function-configuration \
      --function-name "$fn" \
      --region eu-west-2 \
      --environment "Variables={
        OTEL_SERVICE_NAME=${service_name},
        OTEL_EXPORTER_OTLP_ENDPOINT=https://${DT_ENV_ID}.live.dynatrace.com/api/v2/otlp,
        OTEL_EXPORTER_OTLP_HEADERS=Authorization=Api-Token ${DT_OTEL_TOKEN},
        OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf,
        OTEL_PROPAGATORS=tracecontext,
        AWS_LAMBDA_EXEC_WRAPPER=/opt/otel-instrument
      }"
}

# Apply to all ARIA Lambdas
update_otel_env "aria-lex-fulfillment"          "aria.lex.fulfillment"
update_otel_env "aria-session-injector"          "aria.session.injector"
update_otel_env "aria-session-injector-qconnect" "aria.session.injector.qconnect"
update_otel_env "aria-routing-lookup"            "aria.routing.lookup"
update_otel_env "aria-dtmf-decrypt"              "aria.dtmf.decrypt"
update_otel_env "aria-callback-scheduler"        "aria.callback.scheduler"
update_otel_env "aria-audit-cloudtrail-writer"   "aria.audit.cloudtrail"
update_otel_env "aria-audit-dynamodb-writer"     "aria.audit.dynamodb"
```

> **Important:** The `OTEL_EXPORTER_OTLP_HEADERS` variable contains your API token. Store the token in Secrets Manager and retrieve it dynamically in your deploy script — **do not hard-code it in source control**.

### Step M.6.4 — Add Custom Spans for Business Logic (Optional but Recommended)

For richer traces, add manual spans in the Lambda handler files. Here is the pattern used across ARIA Lambdas:

```python
# Add to requirements.txt:
# opentelemetry-api==1.27.0
# opentelemetry-sdk==1.27.0

from opentelemetry import trace

tracer = trace.get_tracer("aria.banking", "1.0.0")

def lambda_handler(event, context):
    contact_id = event.get("Details", {}).get("ContactData", {}).get("ContactId", "unknown")
    
    with tracer.start_as_current_span("handle-customer-request") as span:
        span.set_attribute("aria.contact.id", contact_id)
        span.set_attribute("aria.channel", "VOICE")
        span.set_attribute("aria.customer.auth_status", event.get("Details", {})
                           .get("ContactData", {}).get("Attributes", {})
                           .get("authStatus", "unauthenticated"))
        
        # --- your existing Lambda logic here ---
        result = process_request(event)
        
        span.set_attribute("aria.intent", result.get("intent", "unknown"))
        span.set_attribute("aria.routing.queue", result.get("queueName", "unknown"))
        
        return result
```

### Step M.6.5 — Propagate Trace Context via Contact ID

Amazon Connect does not propagate W3C `traceparent` headers natively. Use the **Contact ID** as a correlation key across services:

In each Lambda, extract and set the Contact ID as a span attribute:

```python
CONTACT_ID_KEY = "aria.contact.id"

def get_contact_id(event):
    return (event.get("Details", {})
                 .get("ContactData", {})
                 .get("ContactId", "unknown"))
```

Then in Dynatrace, you can search all traces/logs for a specific Contact ID to reconstruct the full journey of a single customer interaction.

---

## M.7 Business Events (BizEvents) — Customer Journey Tracking

### What Are Business Events?

A **BizEvent** in Dynatrace is a structured event that represents a significant business moment — not just "Lambda executed" but "customer escalated to human agent" or "callback was requested". These power the **Business Journey dashboards** used by Service Managers.

### Why BizEvents Matter for ARIA

BizEvents allow you to answer questions like:
- "How many customers asked about account balances today?"
- "What percentage of AI interactions needed human escalation this week?"
- "How long does the average callback take from request to answer?"
- "Are DTMF card-capture sessions succeeding?"

### M.7.1 — BizEvent Schema

All ARIA BizEvents follow this schema:

```json
{
  "event.type":          "com.meridianbank.aria.<category>.<action>",
  "event.provider":      "aria-banking",
  "event.timestamp":     "2025-01-15T14:30:00.000Z",
  "aria.contact.id":     "<connect-contact-id>",
  "aria.channel":        "VOICE | CHAT",
  "aria.customer.id":    "<hashed-customer-id>",
  "aria.auth.status":    "authenticated | unauthenticated",
  "aria.intent":         "<detected-intent>",
  "aria.queue.name":     "<routed-queue>",
  "aria.agent.id":       "<agent-id-if-escalated>"
}
```

> **Privacy note:** Never include actual card numbers, account numbers, or PII in BizEvents. Use Contact ID and hashed Customer ID only.

### M.7.2 — ARIA BizEvent Catalogue

| Event Type | When Emitted | Lambda | Key Extra Fields |
|-----------|--------------|--------|-----------------|
| `com.meridianbank.aria.contact.started` | Customer call/chat begins | `aria-session-injector` | `aria.channel` |
| `com.meridianbank.aria.contact.authenticated` | Customer ID resolved | `aria-session-injector` | `aria.auth.status=authenticated` |
| `com.meridianbank.aria.contact.unauthenticated` | No customer ID found | `aria-session-injector` | `aria.auth.status=unauthenticated` |
| `com.meridianbank.aria.intent.resolved` | AI understood the request | `aria-lex-fulfillment` | `aria.intent`, `aria.confidence` |
| `com.meridianbank.aria.tool.invoked` | AI called a banking tool | `aria-lex-fulfillment` | `aria.tool.name`, `aria.tool.duration_ms` |
| `com.meridianbank.aria.escalated.agent` | Escalated to human agent | `aria-lex-fulfillment` | `aria.escalation.reason`, `aria.queue.name` |
| `com.meridianbank.aria.escalated.failed` | Escalation failed | `aria-lex-fulfillment` | `aria.error.code` |
| `com.meridianbank.aria.dtmf.started` | DTMF card capture started | `aria-lex-fulfillment` | `aria.dtmf.field_name` |
| `com.meridianbank.aria.dtmf.completed` | DTMF capture succeeded | `aria-dtmf-decrypt` | `aria.dtmf.field_name` |
| `com.meridianbank.aria.dtmf.failed` | DTMF capture failed | `aria-dtmf-decrypt` | `aria.error.code` |
| `com.meridianbank.aria.callback.requested` | Customer requested callback | `aria-callback-scheduler` | `aria.callback.reason` |
| `com.meridianbank.aria.callback.created` | Callback enqueued in Connect | Contact flow | `aria.callback.queue` |
| `com.meridianbank.aria.callback.completed` | Outbound callback answered | Contact flow | `aria.callback.duration_ms` |
| `com.meridianbank.aria.contact.ended` | Call/chat completed | `aria-lex-fulfillment` | `aria.contact.duration_ms`, `aria.resolution` |

### M.7.3 — Emitting BizEvents from Lambda

Use the Dynatrace OTLP / OpenTelemetry API to emit BizEvents as custom spans with specific attributes. The ADOT collector will forward these to Dynatrace's BizEvents engine when the span contains `event.type` attribute:

```python
from opentelemetry import trace
from opentelemetry.trace import SpanKind
import time

tracer = trace.get_tracer("aria.banking.bizevents")

def emit_biz_event(event_type: str, contact_id: str, channel: str, extra: dict = None):
    """Emit a Dynatrace BizEvent as an OTel span."""
    attrs = {
        "event.type":       event_type,
        "event.provider":   "aria-banking",
        "aria.contact.id":  contact_id,
        "aria.channel":     channel,
    }
    if extra:
        attrs.update(extra)
    
    with tracer.start_as_current_span(
        name=event_type,
        kind=SpanKind.INTERNAL,
        attributes=attrs
    ):
        pass  # span ends immediately; the event is captured

# Example usage in aria-lex-fulfillment:
def lambda_handler(event, context):
    contact_id = get_contact_id(event)
    channel    = get_channel(event)
    
    # Emit contact.started when handling a new conversation turn
    emit_biz_event(
        "com.meridianbank.aria.contact.started",
        contact_id, channel,
        {"aria.auth.status": get_auth_status(event)}
    )
    
    # ... process the request ...
    
    # Emit intent resolved
    emit_biz_event(
        "com.meridianbank.aria.intent.resolved",
        contact_id, channel,
        {"aria.intent": intent, "aria.confidence": confidence_score}
    )
```

### M.7.4 — Viewing BizEvents in Dynatrace

1. Go to **Business Analytics → Business Events** in Dynatrace.
2. Filter by `event.provider = aria-banking`.
3. You will see a timeline of every significant event in every customer interaction.
4. Use **DQL (Dynatrace Query Language)** to query BizEvents:

```dql
// Count escalations in the last 24 hours by queue
fetch bizevents
| filter event.type == "com.meridianbank.aria.escalated.agent"
| summarize count = count(), by:{aria.queue.name}
| sort count desc
```

---

## M.8 Configuration Item (CI) Mapping

### What Is a CI?

A **Configuration Item (CI)** is a record in your IT service management (ITSM) tool (e.g. ServiceNow, Jira Service Management) that represents one component of your IT estate. CI mapping means connecting what Dynatrace sees to those ITSM records so that when an alert fires, the incident is automatically linked to the right component.

### ARIA CI Hierarchy

```
Application CI: ARIA-Banking-AI-Agent
│
├── Service CI: ARIA-Contact-Centre
│   └── Amazon Connect instance
│
├── Service CI: ARIA-AI-Engine
│   ├── Bedrock AgentCore runtime
│   └── MCP Gateway
│
├── Service CI: ARIA-NLP-Layer
│   └── Lex V2 bot
│
├── Service CI: ARIA-Fulfillment-Lambda
│   └── aria-lex-fulfillment
│
├── Service CI: ARIA-Session-Management
│   ├── aria-session-injector
│   └── aria-session-injector-qconnect
│
├── Service CI: ARIA-Routing-Engine
│   ├── aria-routing-lookup
│   └── DynamoDB: aria-routing-config
│
├── Service CI: ARIA-Secure-Data-Collection
│   ├── aria-dtmf-decrypt
│   ├── KMS CMK (DTMF)
│   └── Secrets Manager (RSA key)
│
├── Service CI: ARIA-Callback-Management
│   ├── aria-callback-scheduler
│   └── DynamoDB: aria-routing-config (callback fields)
│
├── Service CI: ARIA-Audit-System
│   ├── aria-audit-cloudtrail-writer
│   ├── aria-audit-dynamodb-writer
│   ├── EventBridge: aria-audit bus
│   ├── Firehose: aria-audit-firehose
│   └── DynamoDB: aria-audit-events
│
└── Service CI: ARIA-Chat-Widget
    ├── S3: meridian-aria-client-{deploy_id}
    └── CloudFront distribution
```

### CI Attributes Table

| CI Name | Dynatrace Entity Type | AWS Resource Type | ITSM Tier | Business Owner |
|---------|----------------------|-------------------|-----------|----------------|
| ARIA-Contact-Centre | Application (Custom) | Amazon Connect | Production | Contact Centre Manager |
| ARIA-AI-Engine | Service | Bedrock | Production | AI Engineering |
| ARIA-NLP-Layer | Service | Lambda / Lex | Production | AI Engineering |
| ARIA-Fulfillment-Lambda | Service (Lambda) | Lambda | Production | Banking Tech |
| ARIA-Session-Management | Service (Lambda) | Lambda | Production | Security/Identity |
| ARIA-Routing-Engine | Service (Lambda + DB) | Lambda + DynamoDB | Production | Contact Centre Ops |
| ARIA-Secure-Data-Collection | Service (Lambda) | Lambda + KMS | Production | Security |
| ARIA-Callback-Management | Service (Lambda) | Lambda + DynamoDB | Production | Contact Centre Ops |
| ARIA-Audit-System | Service | Lambda + DynamoDB + Firehose | Production | Compliance |
| ARIA-Chat-Widget | Application | CloudFront + S3 | Production | Digital |

---

## M.9 Tag Taxonomy

Tags in Dynatrace are key-value labels applied to entities (services, process groups, Lambda functions). They enable filtering, alert routing, and CMDB linkage.

### Mandatory Tags on All ARIA Entities

Apply these tags to every ARIA Dynatrace entity (via auto-tagging rules or manually):

| Tag Key | Example Value | Purpose |
|---------|--------------|---------|
| `application` | `aria-banking` | Groups all ARIA components |
| `environment` | `production` | Separates prod from dev/staging |
| `aws.region` | `eu-west-2` | Region filter |
| `team` | `banking-ai` | Alert routing to correct team |
| `tier` | `critical` / `high` / `medium` | Alert severity baseline |
| `ci.name` | `ARIA-Fulfillment-Lambda` | Links to CMDB CI |

### Service-Specific Tags

| Entity | Additional Tags |
|--------|----------------|
| All Lambda functions | `aws.service=lambda`, `runtime=python3.12` |
| aria-dtmf-decrypt | `security.sensitive=true`, `pci.in-scope=true` |
| aria-audit-* | `compliance.audit=true` |
| DynamoDB tables | `aws.service=dynamodb`, `data.classification=internal` |
| KMS CMK | `security.sensitive=true`, `pci.in-scope=true` |

### Setting Up Auto-Tagging Rules in Dynatrace

Instead of tagging each entity manually, set up one auto-tagging rule that applies to all Lambda functions matching the ARIA naming pattern:

1. Go to **Settings → Tags → Automatically applied tags**.
2. Click **Create auto-tag rule**.
3. Name: `ARIA Application Tag`.
4. Under **Optional tag value**, set value: `aria-banking`.
5. Add condition:
   - Entity type: `AWS Lambda function`
   - Property: `AWS Lambda function name`
   - Operator: `begins with`
   - Value: `aria-`
6. Click **Save changes**.

Repeat this process to create rules for each tag in the mandatory set, adjusting conditions appropriately.

---

## M.10 CloudWatch Metrics Reference

### What Dynatrace Sees for Each ARIA Component

These are the key metrics that flow from CloudWatch Metric Streams into Dynatrace. The Dynatrace metric name uses the prefix `cloud.aws.` followed by the service namespace in lowercase.

#### Amazon Connect Metrics (`AWS/Connect`)

| CloudWatch Metric | Dynatrace Metric Key | What It Means |
|-------------------|---------------------|---------------|
| `ContactsInQueue` | `cloud.aws.connect.contactsinqueue` | Customers waiting for an agent or AI |
| `LongestQueueWait` | `cloud.aws.connect.longestqueuewait` | Longest anyone has been waiting (seconds) |
| `ContactsHandled` | `cloud.aws.connect.contactshandled` | Successfully handled contacts |
| `ContactsAbandoned` | `cloud.aws.connect.contactsabandoned` | Customers who hung up before being helped |
| `ContactsTransferredIn` | `cloud.aws.connect.contactstransferredin` | Transferred contacts received |
| `ContactsTransferredOut` | `cloud.aws.connect.contactstransferredout` | Transferred contacts sent away |
| `CallBackContactsWaiting` | `cloud.aws.connect.callbackcontactswaiting` | Callbacks queued awaiting agent |
| `ServiceLevel` | `cloud.aws.connect.servicelevel` | % of calls answered within target time |

> **Note:** Amazon Connect metrics are per-queue. Set the `Queue` dimension filter in CloudWatch to `ARIA-Banking-General` (and each of your queues) for focused monitoring.

#### AWS Lambda Metrics (`AWS/Lambda`)

| CloudWatch Metric | Dynatrace Metric Key | What It Means |
|-------------------|---------------------|---------------|
| `Invocations` | `cloud.aws.lambda.invocations` | Number of times function was called |
| `Duration` | `cloud.aws.lambda.duration` | Execution time (milliseconds) |
| `Errors` | `cloud.aws.lambda.errors` | Calls that threw an exception |
| `Throttles` | `cloud.aws.lambda.throttles` | Calls blocked due to concurrency limit |
| `ConcurrentExecutions` | `cloud.aws.lambda.concurrentexecutions` | Simultaneous running instances |
| `DeadLetterErrors` | `cloud.aws.lambda.deadlettererrors` | Failed DLQ deliveries |
| `IteratorAge` | `cloud.aws.lambda.iteratorage` | Stream event processing lag |

All metrics are available per function by the `FunctionName` dimension.

#### Amazon Lex V2 (`AWS/Lex`)

| CloudWatch Metric | Dynatrace Metric Key | What It Means |
|-------------------|---------------------|---------------|
| `RuntimeInvalidLambdaResponses` | `cloud.aws.lex.runtimeinvalidlambdaresponses` | Invalid responses from fulfillment Lambda |
| `RuntimeLambdaErrors` | `cloud.aws.lex.runtimelambdaerrors` | Errors in Lambda integration |
| `RuntimeSuccessfulRequests` | `cloud.aws.lex.runtimesuccessfulrequests` | Successful bot conversations |
| `RuntimeThrottledEvents` | `cloud.aws.lex.runtimethrottledevents` | Throttling on bot requests |
| `RuntimeUserErrors` | `cloud.aws.lex.runtimeusererrors` | Misunderstood or failed interactions |

#### Amazon DynamoDB (`AWS/DynamoDB`)

| CloudWatch Metric | Dynatrace Metric Key | What It Means |
|-------------------|---------------------|---------------|
| `SuccessfulRequestLatency` | `cloud.aws.dynamodb.successfulrequestlatency` | Average query time (ms) |
| `ThrottledRequests` | `cloud.aws.dynamodb.throttledrequests` | Requests blocked by capacity limits |
| `SystemErrors` | `cloud.aws.dynamodb.systemerrors` | DynamoDB internal errors |
| `ConditionalCheckFailedRequests` | `cloud.aws.dynamodb.conditionalcheckfailedrequests` | Failed conditional writes |

#### API Gateway / WebSocket (`AWS/ApiGateway`)

| CloudWatch Metric | Dynatrace Metric Key | What It Means |
|-------------------|---------------------|---------------|
| `4XXError` | `cloud.aws.apigateway.4xxerror` | Client-side errors on WebSocket API |
| `5XXError` | `cloud.aws.apigateway.5xxerror` | Server-side errors |
| `ConnectionCount` | `cloud.aws.apigateway.connectioncount` | Active WebSocket connections (chat users) |
| `MessageCount` | `cloud.aws.apigateway.messagecount` | Messages sent/received |
| `IntegrationError` | `cloud.aws.apigateway.integrationerror` | Backend Lambda errors |

---

## M.11 Distributed Tracing — End-to-End Customer Journey

### The Customer Journey Trace

When a customer contacts Meridian Bank, the following sequence of Lambda invocations happens. Each one produces a trace span. Together, they form the complete trace for that customer interaction:

```
[Amazon Connect] — receives call/chat
       │
       ▼
[aria-session-injector]     ← Span: "resolve-customer-session"
  Look up customer ID         Attributes: contact.id, auth.status
       │
       ▼
[Amazon Lex V2]             ← Not a Lambda, but spans emitted by fulfillment
  NLU + intent detection
       │
       ▼
[aria-lex-fulfillment]      ← Span: "fulfillment-dispatch"
  Route to AI or human        Attributes: intent, channel, auth.status
       │
       ├──► [Bedrock AgentCore]   ← External call (timeout tracking via duration span)
       │          │
       │          └──► [MCP Tools / Banking APIs]  ← Spans: "tool-invoke-{name}"
       │
       └──► [aria-routing-lookup]  ← Span: "routing-lookup"
                   │                  Attributes: topicCategory, queueId
                   │
                   └──► [Amazon Connect Transfer]
                                │
                                └──► [aria-callback-scheduler]  ← If callback needed
                                           Span: "callback-queue-resolve"
```

### Trace Search in Dynatrace

To find the trace for a specific customer interaction:

1. Go to **Applications & Microservices → Distributed Traces**.
2. Filter by `aria.contact.id = {the-contact-id-from-connect}`.
3. Click on the trace to see the full waterfall — every span, every Lambda, every external call.

Alternatively, from **Logs & Events**, find a log line for that contact ID and click **View trace** to jump directly to the trace.

### Connecting Contact ID Across All Signals

The **Contact ID** (assigned by Amazon Connect, looks like `abc12345-6789-...`) is the correlation key across logs, traces, and BizEvents:

| Signal | Where Contact ID Appears |
|--------|------------------------|
| Logs | `aria.contact.id` log attribute (set in Lambda code) |
| Traces | `aria.contact.id` span attribute |
| BizEvents | `aria.contact.id` event attribute |
| CloudTrail | `requestParameters.ContactId` |

To add Contact ID to Lambda logs automatically:

```python
import logging
import json

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def log_with_context(level, message, contact_id, **kwargs):
    entry = {
        "message": message,
        "aria.contact.id": contact_id,
        "service": "aria.lex.fulfillment",
        **kwargs
    }
    getattr(logger, level)(json.dumps(entry))
```

---

## M.12 Alerting Strategy

### Alert Priority Levels

ARIA uses a four-tier alert priority system aligned to Meridian Bank's incident management:

| Priority | SLA Response | Examples |
|----------|-------------|---------|
| **P1 — Critical** | 5 minutes, page on-call | AI agent completely down; all Lambda errors; DTMF decrypt failure |
| **P2 — High** | 15 minutes, notification | Lambda error rate >5%; queue wait >10 min; routing failures |
| **P3 — Medium** | 1 hour | Lambda near timeout; increased abandons; chat widget slow |
| **P4 — Low** | Next business day | Capacity warnings; KMS key audit; cost anomalies |

### Alert Definitions

Create the following Dynatrace **Metric Events** (alerts based on metric thresholds):

#### P1 Alerts — Critical

| Alert Name | Metric | Condition | Duration | Action |
|------------|--------|-----------|----------|--------|
| ARIA-P1-LexFulfillmentDown | `cloud.aws.lambda.errors{FunctionName=aria-lex-fulfillment}` | error rate > 50% | 2 minutes | Page on-call + create P1 incident |
| ARIA-P1-DTMFDecryptFailing | `cloud.aws.lambda.errors{FunctionName=aria-dtmf-decrypt}` | error rate > 80% | 1 minute | Page security team + P1 incident |
| ARIA-P1-LexFulfillmentThrottle | `cloud.aws.lambda.throttles{FunctionName=aria-lex-fulfillment}` | > 10 throttles | 1 minute | Page on-call |
| ARIA-P1-RoutingDown | `cloud.aws.lambda.errors{FunctionName=aria-routing-lookup}` | error rate > 80% | 2 minutes | Page on-call |

#### P2 Alerts — High

| Alert Name | Metric | Condition | Duration | Action |
|------------|--------|-----------|----------|--------|
| ARIA-P2-HighErrorRate | `cloud.aws.lambda.errors` (all ARIA functions) | error rate > 5% | 5 minutes | Notify team channel |
| ARIA-P2-LongQueueWait | `cloud.aws.connect.longestqueuewait` | > 600 seconds (10 min) | 3 minutes | Notify Contact Centre Manager |
| ARIA-P2-DynamoThrottle | `cloud.aws.dynamodb.throttledrequests` | > 5 | 5 minutes | Notify team + auto-scale review |
| ARIA-P2-CallbackFailures | `cloud.aws.lambda.errors{FunctionName=aria-callback-scheduler}` | error rate > 10% | 5 minutes | Notify Contact Centre Ops |
| ARIA-P2-HighAbandons | `cloud.aws.connect.contactsabandoned` | > 20% above 7-day average | 5 minutes | Notify Contact Centre Manager |

#### P3 Alerts — Medium

| Alert Name | Metric | Condition | Duration | Action |
|------------|--------|-----------|----------|--------|
| ARIA-P3-LambdaSlowdown | `cloud.aws.lambda.duration` (all) | p95 duration > 8000ms | 5 minutes | Notify team channel |
| ARIA-P3-FirehoseBacklog | `cloud.aws.firehose.deliverytosplunk.datadelivered` | < expected baseline | 10 minutes | Notify Compliance team |
| ARIA-P3-ChatWidgetSlow | Synthetic monitor response time | > 5000ms | 3 minutes | Notify Digital team |
| ARIA-P3-LexUserErrors | `cloud.aws.lex.runtimeusererrors` | > 20% above baseline | 10 minutes | Notify AI Engineering |

#### P4 Alerts — Low

| Alert Name | Metric | Condition | Duration | Action |
|------------|--------|-----------|----------|--------|
| ARIA-P4-LambdaConcurrency | `cloud.aws.lambda.concurrentexecutions` | > 80% of reserved concurrency | 15 minutes | Notify team |
| ARIA-P4-DynamoCapacity | `cloud.aws.dynamodb.consumedreadcapacityunits` | > 80% of provisioned | 15 minutes | Notify team |

### Setting Up Alerts in Dynatrace

For each alert above:

1. Go to **Settings → Anomaly Detection → Custom metric events**.
2. Click **Create metric event**.
3. Fill in:
   - **Title:** e.g. `ARIA-P1-LexFulfillmentDown`
   - **Metric source:** select the metric from the dropdown
   - **Dimension filter:** add `FunctionName = aria-lex-fulfillment`
   - **Aggregation:** Sum (for counts) or Average (for durations)
   - **Alert condition:** Rising, threshold value
   - **Severity:** Critical / Error / Warning / Info (maps to P1/P2/P3/P4)
4. Save and enable.

### Alert Routing (Notification Integration)

Set up notification channels so alerts reach the right team:

1. Go to **Settings → Integration → Problem notifications**.
2. Add notification targets:

| Notification Type | Target | Filter |
|------------------|---------|----|
| Microsoft Teams webhook | `#aria-oncall` channel | All P1 |
| Microsoft Teams webhook | `#aria-alerts` channel | P2 and P3 |
| Email | banking-ai@meridianbank.com | All P1, P2 |
| Email | contact-centre-ops@meridianbank.com | Connect queue alerts |
| PagerDuty | On-call rotation | P1 only |

---

## M.13 SLO / SLA Framework

### Service Level Objectives

An SLO (Service Level Objective) defines how reliable a service must be. An SLA (Service Level Agreement) is the contractual version. Define these in Dynatrace so you can see at a glance whether ARIA is meeting its targets.

#### ARIA SLO Definitions

Create these SLOs under **Applications & Microservices → SLOs** in Dynatrace:

| SLO Name | Target | Measurement | Window |
|----------|--------|-------------|--------|
| ARIA-SLO-FulfillmentAvailability | 99.5% | % invocations without error for `aria-lex-fulfillment` | Rolling 30 days |
| ARIA-SLO-RoutingSuccessRate | 99.9% | % invocations without error for `aria-routing-lookup` | Rolling 30 days |
| ARIA-SLO-DTMFSuccessRate | 99.0% | % DTMF decrypt calls completing without error | Rolling 30 days |
| ARIA-SLO-CallbackDeliveryRate | 98.0% | % callback contacts successfully enqueued | Rolling 30 days |
| ARIA-SLO-QueueAnswerTime | 90% within 120s | % contacts answered within 2 minutes | Rolling 7 days |
| ARIA-SLO-ChatWidgetAvailability | 99.9% | HTTP synthetic monitor success rate | Rolling 30 days |
| ARIA-SLO-AuditIntegrity | 100% | % audit events successfully written to DynamoDB | Rolling 30 days |

#### How to Create an SLO in Dynatrace

1. Go to **Applications & Microservices → SLOs**.
2. Click **Add new SLO**.
3. Example for Fulfillment Availability:
   - **Name:** `ARIA-SLO-FulfillmentAvailability`
   - **Indicator type:** Metric
   - **SLI metric expression:**
     ```
     (100) * (1 - (
       (cloud.aws.lambda.errors:splitBy("aws.lambda.function_name")
         :filter(eq("aws.lambda.function_name","aria-lex-fulfillment"))
         :sum)
       /
       (cloud.aws.lambda.invocations:splitBy("aws.lambda.function_name")
         :filter(eq("aws.lambda.function_name","aria-lex-fulfillment"))
         :sum)
     ))
     ```
   - **Target:** 99.5
   - **Warning:** 99.8
   - **Timeframe:** Last 30 days

#### Error Budget

Dynatrace calculates the **error budget** automatically — the amount of downtime you can still afford before breaching the SLA. Service Managers should review this weekly. A shrinking error budget is an early warning to investigate.

---

## M.14 Dashboard Specifications

### Overview

Create four dashboards in Dynatrace tailored to each audience. All dashboards should use the `application = aria-banking` tag filter as the starting point.

---

### Dashboard 1: ARIA Operations Dashboard (Run Teams)

**Purpose:** Real-time view of ARIA health. Used by Run Team during live operations.

**Tiles to include:**

| Tile | Type | Content |
|------|------|---------|
| ARIA System Status | Single value + colour | Davis AI problem count (0=green, >0=red) |
| Lambda Error Rate (last 15 min) | Line chart | Errors per function, all ARIA Lambdas |
| Lambda Invocations (last 1h) | Bar chart | Invocations by function name |
| Lambda Duration P95 (last 1h) | Line chart | P95 duration per function |
| Contacts in Queue | Single value | `cloud.aws.connect.contactsinqueue` per queue |
| Longest Queue Wait | Single value | `cloud.aws.connect.longestqueuewait` |
| Contacts Handled (today) | Single value | `cloud.aws.connect.contactshandled` |
| Contacts Abandoned (today) | Single value | `cloud.aws.connect.contactsabandoned` with % |
| Callbacks Waiting | Single value | `cloud.aws.connect.callbackcontactswaiting` |
| DynamoDB Latency | Line chart | `cloud.aws.dynamodb.successfulrequestlatency` |
| Active SLO Compliance | SLO tile | All 7 ARIA SLOs, status at a glance |
| Open Problems | Problems tile | Davis AI detected problems tagged `application:aria-banking` |

---

### Dashboard 2: Business Journey Dashboard (Service Managers)

**Purpose:** Business-level view of customer journeys. Shows how effectively ARIA is serving customers.

**Tiles to include — all powered by BizEvents (DQL queries):**

| Tile | DQL Query | Metric |
|------|-----------|--------|
| Total Contacts Today | `fetch bizevents \| filter event.type=="com.meridianbank.aria.contact.started" \| summarize count()` | Count |
| Authenticated vs Unauthenticated | `fetch bizevents \| filter event.type=="com.meridianbank.aria.contact.*" \| summarize count(), by:{aria.auth.status}` | Pie chart |
| AI Containment Rate | Contacts resolved by AI / total contacts | KPI % |
| Escalation Rate | `fetch bizevents \| filter event.type=="com.meridianbank.aria.escalated.agent" \| summarize count()` / total contacts | KPI % |
| Top Intents (last 7 days) | `fetch bizevents \| filter event.type=="com.meridianbank.aria.intent.resolved" \| summarize count(), by:{aria.intent} \| sort count desc` | Bar chart |
| Escalation Reasons | `fetch bizevents \| filter event.type=="com.meridianbank.aria.escalated.agent" \| summarize count(), by:{aria.escalation.reason}` | Pie chart |
| DTMF Sessions (today) | Count started vs completed vs failed | 3 single-value tiles |
| Callback Funnel | Requested → Created → Completed | Funnel chart |
| SLO Compliance | All ARIA SLOs | SLO tile |
| Channel Split (Voice vs Chat) | `fetch bizevents \| filter event.type=="com.meridianbank.aria.contact.started" \| summarize count(), by:{aria.channel}` | Pie chart |

---

### Dashboard 3: Technical Deep-Dive (Change Engineering)

**Purpose:** Detailed infrastructure view during deployments and post-deployment validation.

**Tiles to include:**

| Tile | Type | Content |
|------|------|---------|
| Deployment Events (last 30 days) | Event list | Deployment markers from CI/CD |
| Error Rate Before vs After Deploy | Comparison chart | Lambda error rates with deployment marker overlay |
| Lambda Duration Before vs After | Comparison chart | P50, P95, P99 duration per function |
| DynamoDB Throttle Events | Count | Any throttles since last deploy |
| Lex Bot Success Rate | Metric | `cloud.aws.lex.runtimesuccessfulrequests` |
| CloudFront Cache Hit Rate | Metric | Chat widget CDN performance |
| Cognito Auth Success Rate | Metric | WebSocket auth for chat widget |
| OTel Trace Ingest Health | Count | Traces received per minute |
| Log Volume Trend | Line chart | Log events per hour per service |
| Recently Resolved Problems | Problem list | Davis AI problems closed in last 48h |

---

### Dashboard 4: Callback & Queue Health (Contact Centre Ops)

**Purpose:** Callback-specific view for the team managing queued callbacks.

**Tiles to include:**

| Tile | Content |
|------|---------|
| Callbacks Currently Waiting | Per queue, real-time |
| Callback Success Rate (today) | Completed / requested |
| Avg Callback Wait Duration | From request to answer |
| Callback Lambda Errors | `aria-callback-scheduler` error rate |
| Queue Occupancy per Topic | Contacts in each topic queue |
| Out-of-Hours Callback Volume | Count triggered by OOH flows |
| Queue-Full Callbacks vs Direct | Split by `aria.callback.reason` |
| Callback Completion Trend | 7-day rolling line chart |

---

## M.15 Operational Testing — Synthetic Monitoring

### What Is Synthetic Monitoring?

Dynatrace Synthetic Monitoring sends automated, scheduled requests to your services — like a robot that repeatedly calls your API every minute to verify it's working. This catches outages **before** real customers experience them.

For ARIA, we use **HTTP monitors** (testing specific endpoints) and **API-triggered monitors** (testing Lambda behaviour via test events).

### M.15.1 — Chat Widget Availability Monitor

**What it tests:** The chat widget hosted on CloudFront is loading successfully.

**Setup in Dynatrace:**

1. Go to **Digital Experience → Synthetic Monitoring → Create synthetic monitor**.
2. Select **HTTP monitor**.
3. Settings:
   - **Name:** `ARIA-ChatWidget-Availability`
   - **URL:** `https://{cloudfront-domain}/index.html`
   - **Method:** GET
   - **Frequency:** every 5 minutes
   - **Locations:** London, Frankfurt, Dublin (multiple for geo redundancy)
4. Response validation:
   - **HTTP status:** 200
   - **Response body contains:** `aria-chat-widget` (or whatever your HTML marker is)
5. Alert threshold:
   - Notify if unavailable from 2+ locations simultaneously

### M.15.2 — Lambda Health Check Monitors

Create HTTP monitors for Lambda function URLs. If your Lambdas are not exposed via Function URLs, use a lightweight API Gateway health endpoint or a separate health-check Lambda.

**Create a health check Lambda (one-time):**

```python
# scripts/lambdas/aria_health_check.py
# A simple Lambda that validates connectivity to DynamoDB and returns a health status

import boto3
import json

dynamodb = boto3.resource("dynamodb", region_name="eu-west-2")

def lambda_handler(event, context):
    try:
        table = dynamodb.Table("aria-routing-config")
        table.load()
        return {"statusCode": 200, "body": json.dumps({"status": "healthy"})}
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"status": "unhealthy", "error": str(e)})}
```

Deploy this with a Function URL (no auth, or use IAM auth with synthetic credentials), then monitor it:

- **Name:** `ARIA-RoutingConfig-Health`
- **URL:** `https://{function-url-id}.lambda-url.eu-west-2.on.aws/`
- **Method:** GET
- **Frequency:** every 1 minute
- **Expectation:** HTTP 200 + `"status": "healthy"` in body

### M.15.3 — Routing Lambda Functional Test

This monitor sends a realistic test event to verify the routing logic is working end-to-end:

```json
// Test payload for aria-routing-lookup
{
  "Details": {
    "ContactData": {
      "Attributes": {
        "topicCategory": "account_enquiry"
      }
    }
  }
}
```

Expected response: JSON containing `queueId` and `queueName` fields.

Use Dynatrace's **Script-mode HTTP monitor** with pre/post validation scripts to verify the response structure.

### M.15.4 — Callback Scheduler Functional Test

Test that the callback scheduler correctly resolves a callback queue:

```json
// Test payload for aria-callback-scheduler
{
  "Details": {
    "ContactData": {
      "Attributes": {
        "topicCategory": "account_enquiry"
      }
    }
  }
}
```

Expected response contains `callbackQueueId` that does not start with `PLACEHOLDER`.

### M.15.5 — Synthetic Monitor Alert Policy

1. In Dynatrace, each synthetic monitor has its own alert settings.
2. For all ARIA monitors, set:
   - Alert when: outage confirmed from 2+ locations
   - Recovery: when available from all locations
   - Severity: map Chat Widget → Error, Lambda health → Critical

---

## M.16 Change Engineering Integration

### Why This Matters

When you deploy a new version of ARIA (new Lambda code, updated prompts, flow changes), Davis AI in Dynatrace will **automatically correlate** any new problems with your deployment event. This means instead of hunting for the cause of a spike in Lambda errors after a release, Dynatrace will tell you: "Problem started at 14:32 — deployment `aria-lex-fulfillment v1.4.2` detected at 14:30".

### M.16.1 — Sending Deployment Events from Deploy Scripts

Add this function to each ARIA deploy script to mark deployments in Dynatrace:

```bash
# Add to any deploy script after successful deployment
send_dynatrace_deployment_event() {
    local function_name=$1
    local version=$2
    local deployer="${DEPLOYER:-CI/CD}"
    
    local DT_ENV_URL="https://${DT_ENVIRONMENT_ID}.live.dynatrace.com"
    local DT_TOKEN="${DT_API_TOKEN}"  # read from env or secrets manager
    
    curl -s -X POST "${DT_ENV_URL}/api/v2/events/ingest" \
      -H "Authorization: Api-Token ${DT_TOKEN}" \
      -H "Content-Type: application/json" \
      -d "{
        \"eventType\": \"CUSTOM_DEPLOYMENT\",
        \"title\": \"ARIA Lambda Deployed: ${function_name}\",
        \"entitySelector\": \"type(PROCESS_GROUP),tag(application:aria-banking),entityName.contains(${function_name})\",
        \"properties\": {
          \"dt.event.deployment.version\": \"${version}\",
          \"dt.event.deployment.release_stage\": \"production\",
          \"dt.event.deployment.name\": \"${function_name}\",
          \"deployer\": \"${deployer}\",
          \"aws.region\": \"eu-west-2\"
        }
      }"
    
    echo "Sent deployment event to Dynatrace for ${function_name} v${version}"
}

# Call after each Lambda deployment:
# send_dynatrace_deployment_event "aria-lex-fulfillment" "1.4.2"
```

### M.16.2 — Dynatrace API Token for Events

Create an API token for deployment events:

1. In Dynatrace → **Access tokens** → **Generate new token**.
2. Name: `aria-change-engineering`.
3. Enable: **Ingest events** (`events.ingest`).
4. Store in AWS Secrets Manager as `aria-dynatrace-events-token`.

### M.16.3 — Blocking Deployments on SLO Breach

Add a gate in your CI/CD pipeline that checks ARIA SLO status before deploying. If the current error budget is below 20%, the deployment is blocked until the issue is resolved:

```bash
check_dynatrace_slo_health() {
    local SLO_ID=$1  # Get from Dynatrace Settings → SLOs → copy SLO ID
    
    local response=$(curl -s \
      -H "Authorization: Api-Token ${DT_API_TOKEN}" \
      "https://${DT_ENVIRONMENT_ID}.live.dynatrace.com/api/v2/slo/${SLO_ID}?timeFrame=GTF&from=now-7d")
    
    local error_budget=$(echo $response | jq -r '.errorBudget')
    
    if (( $(echo "$error_budget < 20" | bc -l) )); then
        echo "ERROR: ARIA SLO error budget is ${error_budget}% — below 20% threshold"
        echo "Deployment blocked. Resolve active incidents before deploying."
        exit 1
    fi
    
    echo "SLO error budget: ${error_budget}% — deployment approved"
}
```

### M.16.4 — Release Validation Gates

After every deployment, run a **3-minute validation window**:

```bash
validate_deployment() {
    local FUNCTION_NAME=$1
    local WAIT_SECONDS=180  # 3 minutes
    
    echo "Waiting ${WAIT_SECONDS}s for post-deployment validation..."
    sleep $WAIT_SECONDS
    
    # Check Lambda error rate in the last 5 minutes via Dynatrace Metrics API
    local error_rate=$(curl -s \
      -H "Authorization: Api-Token ${DT_API_TOKEN}" \
      "https://${DT_ENVIRONMENT_ID}.live.dynatrace.com/api/v2/metrics/query?metricSelector=cloud.aws.lambda.errors:filter(eq(\"aws.lambda.function_name\",\"${FUNCTION_NAME}\")):sum&resolution=5m&from=now-5m" \
      | jq -r '.resolution.dataPoints[0][1] // 0')
    
    echo "Error count in last 5 min: ${error_rate}"
    
    if (( $(echo "$error_rate > 0" | bc -l) )); then
        echo "WARNING: Errors detected after deployment of ${FUNCTION_NAME}"
        echo "Investigate before proceeding: check Dynatrace → Lambda: ${FUNCTION_NAME}"
    else
        echo "Deployment validation passed for ${FUNCTION_NAME}"
    fi
}
```

### M.16.5 — Change Freeze Periods

To prevent deployments during critical business periods (e.g. end of month, bank holidays):

1. In Dynatrace, go to **Settings → Maintenance windows**.
2. Create a maintenance window:
   - **Name:** `ARIA Month-End Freeze`
   - **Type:** Planned maintenance
   - **Schedule:** recurring, last 2 business days of each month
   - During maintenance: suppress all P3/P4 alerts (not P1/P2)
3. In your deploy scripts, check for active maintenance windows before deploying:

```bash
check_maintenance_window() {
    local active=$(curl -s \
      -H "Authorization: Api-Token ${DT_API_TOKEN}" \
      "https://${DT_ENVIRONMENT_ID}.live.dynatrace.com/api/v2/maintenanceWindows?now=true" \
      | jq -r '.maintenanceWindows[] | select(.type=="PLANNED") | .name')
    
    if [[ -n "$active" ]]; then
        echo "BLOCK: Active maintenance window: $active"
        echo "Deployments are not permitted during change freeze."
        exit 1
    fi
}
```

---

## M.17 Runbooks for Run Teams

This section provides step-by-step response procedures for each alert type. These are the **first-line response actions** for the Run Team before escalating.

---

### Runbook M.17.1 — ARIA-P1-LexFulfillmentDown

**Alert:** `aria-lex-fulfillment` error rate exceeds 50% for 2 minutes.

**What This Means:** The main AI agent cannot process customer requests. Customers contacting the bank will receive error messages or fail to be connected.

**Immediate Actions (5 minutes):**

1. Go to Dynatrace → **Applications & Microservices → Lambda → aria-lex-fulfillment**.
2. Click **Logs** — look for the error message in the last 10 minutes. Common errors:
   - `BedrockAgentCoreError` — Bedrock AgentCore runtime is unavailable → escalate to AI Engineering
   - `DynamoDBConnectionError` — DynamoDB unreachable → check DynamoDB health
   - `ConfigurationError` — missing environment variable → check Lambda config in AWS console
3. Go to AWS Console → Lambda → `aria-lex-fulfillment` → **Test**. Send the test event `{"Details":{"ContactData":{"Attributes":{}}}}`. Check the response.
4. If the error is `BedrockAgentCoreError`, check the Bedrock service health at https://health.aws.amazon.com
5. If error rate drops below 5%, **acknowledge the alert** in Dynatrace.

**Escalation:** If not resolved in 10 minutes → page AI Engineering on-call.

---

### Runbook M.17.2 — ARIA-P1-DTMFDecryptFailing

**Alert:** `aria-dtmf-decrypt` error rate exceeds 80% for 1 minute.

**What This Means:** Customers who enter card numbers via keypad will receive errors. Secure data collection is not working.

**Immediate Actions:**

1. Go to Dynatrace → Lambda → `aria-dtmf-decrypt` → **Logs**.
2. Look for:
   - `KMSInvalidStateException` — KMS key is disabled or pending deletion → check AWS KMS Console
   - `SecretsManagerAccessDenied` — IAM permission problem → check Lambda role
   - `DecryptionError` — RSA key mismatch — may indicate key rotation issue
3. In AWS Console → KMS → find the ARIA DTMF key → verify status is **Enabled**.
4. In AWS Console → Secrets Manager → find `aria-dtmf-rsa-key` → check **Last accessed** date.
5. If KMS key is disabled: **do not re-enable without Change Management approval** — escalate to Security team immediately.

**Escalation:** Immediate → Security team + Contact Centre Manager (customers cannot do DTMF flow until resolved).

---

### Runbook M.17.3 — ARIA-P2-LongQueueWait

**Alert:** Connect queue wait time exceeds 10 minutes.

**What This Means:** Customers are waiting too long for either AI assistance or a human agent.

**Immediate Actions:**

1. Go to Dynatrace → Dashboard → **ARIA Operations Dashboard**.
2. Check `ContactsInQueue` per queue — which queue is backed up?
3. Go to Amazon Connect Console → **Real-Time Metrics → Queues**.
4. Check: are enough agents logged in and available? If agents are offline → Contact Centre Manager to bring agents online.
5. If the AI (ARIA) is routing all contacts to the same queue due to a routing logic error:
   - Check Dynatrace → Lambda → `aria-routing-lookup` → recent logs
   - Look for a specific `topicCategory` that is mapping to the wrong queue
6. If queue is backed up due to high volume: temporarily enable **overflow routing** in Amazon Connect (forward to partner queue or enable additional agents).

**Escalation:** If wait time exceeds 15 minutes → Contact Centre Manager.

---

### Runbook M.17.4 — ARIA-P2-CallbackFailures

**Alert:** `aria-callback-scheduler` error rate exceeds 10% for 5 minutes.

**What This Means:** Callback queue resolution is failing. Customers requesting callbacks may not receive them.

**Immediate Actions:**

1. Dynatrace → Lambda → `aria-callback-scheduler` → **Logs**.
2. Look for:
   - `ResourceNotFoundException` — DynamoDB table `aria-routing-config` not found → check table exists in AWS console
   - `ValidationError: callbackQueueId starts with PLACEHOLDER` — callback queues not configured → this is not an error, it's expected behaviour (falls back to main queue)
   - `AccessDenied` → IAM role `aria-callback-scheduler-role` missing DynamoDB permission
3. If PLACEHOLDER values are in production: run `./scripts/deploy_callback_lambda.sh update-queues` to configure real queue IDs.
4. If DynamoDB is throttling: check DynamoDB capacity for `aria-routing-config`.

---

### Runbook M.17.5 — ARIA-P3-LambdaSlowdown

**Alert:** P95 Lambda duration exceeds 8000ms (8 seconds, near the 15s timeout).

**What This Means:** Lambda is taking much longer than normal. Customers may experience delays.

**Immediate Actions:**

1. Dynatrace → Lambda → check which function is slow.
2. For `aria-lex-fulfillment`: if slow, likely Bedrock AgentCore is taking longer → check `cloud.aws.bedrock.modelInvocationLatency` metric.
3. For `aria-routing-lookup`: likely DynamoDB latency → check `cloud.aws.dynamodb.successfulrequestlatency`.
4. Check if a recent deployment coincides with the slowdown (see Deployment Events on dashboard).
5. If Bedrock is slow and no recent deployment: open AWS Service Health Dashboard for Bedrock in eu-west-2.
6. If Lambda duration approaches 14 seconds: **increase Lambda timeout** in AWS Console as emergency measure (Settings → Configuration → General → Timeout).

---

### Runbook M.17.6 — Davis AI Problem Card

**Alert:** Davis AI has detected an anomaly and opened a Problem.

**What This Means:** Davis AI has automatically correlated multiple signals (metrics, logs, traces, topology) and identified a systemic issue. This is more powerful than individual metric alerts.

**Immediate Actions:**

1. Dynatrace → **Problems** (left menu).
2. Click on the ARIA problem.
3. Read the **root cause** section — Davis AI will usually point to the specific Lambda, DynamoDB table, or external service causing the issue.
4. Check the **Impact** section — which services and SLOs are affected.
5. Click **Explore contributing events** to see the chain of events that led to the problem.
6. If a recent deployment is listed as a contributing event → consider rollback: `aws lambda update-alias --function-name {fn} --name production --function-version {previous-version}`.

---

## M.18 Team Responsibilities & Onboarding

### Responsibility Matrix (RACI)

| Activity | Service Introduction | Run Teams | Service Managers | Change Engineering |
|----------|---------------------|-----------|-----------------|-------------------|
| Initial Dynatrace setup | **R** | C | I | I |
| Metric Streams deployment | **R** | C | I | I |
| Log group subscriptions | **R** | C | I | I |
| OTel Lambda instrumentation | **R** | I | I | A |
| CI mapping in CMDB | **R** | I | A | I |
| Auto-tagging rule setup | **R** | C | I | I |
| Alert definition creation | **R** | A | I | I |
| SLO creation | **R** | C | A | I |
| Dashboard creation | **R** | I | A | C |
| Synthetic monitor setup | **R** | C | I | I |
| Day-to-day alert response | I | **R** | I | I |
| Runbook execution | I | **R** | I | I |
| Deployment event integration | C | I | I | **R** |
| Dynatrace → ITSM integration | **R** | C | A | I |
| SLO reporting | I | C | **R** | I |
| Monthly review | I | C | **R** | C |

R = Responsible, A = Accountable, C = Consulted, I = Informed

### Onboarding — Service Introduction Team

**Goal:** Get Dynatrace fully operational before ARIA goes live.

Checklist:
- [ ] Dynatrace environment created and tenant URL confirmed
- [ ] API tokens created and stored in Secrets Manager: metric-streams, log-ingest, otel, events
- [ ] CloudFormation stack `dynatrace-aws-metric-streams-client` deployed in eu-west-2
- [ ] CloudFormation stack `dynatrace-log-delivery-stream` deployed in eu-west-2
- [ ] All 8 ARIA Lambda log groups subscribed to Firehose
- [ ] CloudTrail log group subscribed to Firehose
- [ ] ADOT Lambda layer added to all 8 ARIA Lambdas
- [ ] OTel environment variables set on all 8 Lambdas
- [ ] Auto-tagging rules created for all ARIA entities
- [ ] All P1–P4 alerts created as Metric Events
- [ ] Notification integrations created (Teams, Email, PagerDuty)
- [ ] All 7 SLOs created
- [ ] All 4 dashboards created
- [ ] Synthetic monitors created for chat widget and Lambda health
- [ ] CI mapping table documented and shared with ITSM team
- [ ] ITSM integration configured (if ServiceNow/Jira)
- [ ] Deployment event function added to deploy.sh
- [ ] Runbooks reviewed and validated with Run Team

### Onboarding — Run Teams

**Goal:** Know how to use Dynatrace for daily operations.

Minimum knowledge required:
1. **Opening the Operations Dashboard** — bookmark it: `https://{your-env}.live.dynatrace.com/ui/dashboards`
2. **Responding to a Problem** — go to Problems → read root cause → follow the matching runbook
3. **Finding logs for a contact** — go to Logs & Events → filter `aria.contact.id = {contact-id}`
4. **Finding the trace for a call** — go to Distributed Traces → filter by contact ID
5. **Checking an SLO** — go to Applications & Microservices → SLOs → check error budget
6. **Acknowledging an alert** — in Problems → click Acknowledge → add comment

**First week:** shadow an experienced Dynatrace user through 3 live alert responses.

### Onboarding — Service Managers

**Goal:** Use the Business Journey Dashboard to report on ARIA effectiveness.

Key tasks:
1. Open Business Journey Dashboard daily — track AI containment rate, escalation rate, callback completion
2. Review SLO compliance weekly — log any breaches in the service review
3. Monthly report: export SLO data from Dynatrace API for management reporting
4. Raise a Change Request if containment rate drops below 70% — trigger AI Engineering review

### Onboarding — Change Engineering

**Goal:** Ensure all ARIA deployments are reflected in Dynatrace and Davis AI can correlate changes with problems.

Key tasks:
1. Add `send_dynatrace_deployment_event` call to every deploy script (see Section M.16.1)
2. Add `check_dynatrace_slo_health` gate to CI/CD pipeline before any production deploy
3. Create Dynatrace maintenance windows for planned freezes (month-end, bank holidays)
4. After every deployment, run `validate_deployment` function and review Dynatrace for 30 minutes
5. Tag all deployment API tokens with the application tag `aria-banking`

---

## Quick Reference — Dynatrace Environment Details

| Item | Value |
|------|-------|
| Environment URL | `https://{your-environment-id}.live.dynatrace.com` |
| OTLP Endpoint | `https://{your-environment-id}.live.dynatrace.com/api/v2/otlp` |
| Logs Ingest (Firehose) | `https://{your-environment-id}.live.dynatrace.com/api/v2/logs/ingest/aws_firehose` |
| Metric Streams endpoint | `https://eu.aws.cloud.dynatrace.com/` |
| Events API | `https://{your-environment-id}.live.dynatrace.com/api/v2/events/ingest` |
| AWS Region | `eu-west-2` |
| Lambda runtime | Python 3.12 |
| ADOT Layer (Python/eu-west-2) | `arn:aws:lambda:eu-west-2:901920570463:layer:aws-otel-python-amd64-ver-1-30-0:1` |

## Quick Reference — Secrets Manager Keys

| Secret Name | Contains |
|-------------|----------|
| `aria-dynatrace-api-token` | Metric Streams + Log ingest token |
| `aria-dynatrace-otel-token` | OTel traces + metrics + logs token |
| `aria-dynatrace-events-token` | Deployment events ingest token |

---

*This document covers the complete Dynatrace observability setup for the ARIA Meridian Bank AI Banking Assistant. For questions, contact the AI Engineering team. For Dynatrace platform issues, contact the Dynatrace SaaS support team at https://support.dynatrace.com.*
