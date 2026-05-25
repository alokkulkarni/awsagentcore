# ARIA Banking Agent Deployment Playbook

| Field | Value |
|---|---|
| **Document ID** | PLY-ARIA-BANKING-001 |
| **Version** | 1.0 |
| **Owner** | Platform Engineering |
| **Date** | 2026-05-25 |
| **Status** | Active |
| **Classification** | Internal |

---

## 1. Purpose and Scope

This playbook defines the controlled deployment approach for the **ARIA Banking Agent** component in the `awsagentcore` repository. ARIA is **Meridian Bank's AI banking assistant for chat and voice via Amazon Bedrock AgentCore**, exposing HTTP chat through `POST /invocations` and voice through `WS /ws`.

### In scope

- Amazon Bedrock AgentCore runtime deployment in `eu-west-2`
- Claude Sonnet 4.6 chat path and Nova Sonic 2 voice path
- Transcript, audit, and session state infrastructure
- Audit Lambdas, Lex fulfillment Lambda, and Connect session injector Lambda
- Cognito unauthenticated browser access for the React client
- S3 + CloudFront delivery of the React frontend
- Deployment state tracking in `scripts/.deploy-state.json`

### Out of scope

- Amazon Connect instance creation
- Lex bot and Connect contact-flow authoring beyond Lambda attachment points
- Core banking API implementation behind `BANK_API_BASE_URL`
- Enterprise landing-zone, SCP, or organization-wide IAM setup
- Custom DNS/TLS beyond the default CloudFront domain

---

## 2. Component Overview

### 2.1 Architecture summary

ARIA runs as a containerized Bedrock AgentCore application with two entry paths:

- **Chat:** React client or API caller → AgentCore `POST /invocations` → Strands agent → Claude Sonnet 4.6
- **Voice:** browser or telephony bridge → AgentCore `WS /ws` → Nova Sonic 2 bidirectional stream → shared banking tools

At runtime the component:

1. Creates or resumes a session-scoped Strands agent.
2. Injects `SESSION_START` context on first turn.
3. Executes the shared 20-tool banking toolset.
4. Emits audit events to EventBridge.
5. Fans audit events to CloudTrail Lake, DynamoDB, and Firehose→S3 WORM.
6. Saves transcripts to S3 and recent turn memory to AgentCore Memory / DynamoDB-backed context flows.

### 2.2 Primary data flow

**Chat flow**

1. Customer opens the React client from CloudFront.
2. Browser obtains temporary AWS credentials from Cognito Identity Pool.
3. Browser invokes AgentCore over SigV4-signed HTTPS.
4. `aria/agentcore_app.py` routes the request to the Strands ARIA agent.
5. The agent uses Claude Sonnet 4.6 and registered banking tools.
6. Tool activity is audited to EventBridge and persisted to compliance stores.
7. Response returns to the browser; transcript is written to S3.

**Voice / Amazon Connect flow**

1. Customer connects over WebSocket or through Amazon Connect integration.
2. `aria-session-injector` can preload customer and session context.
3. AgentCore voice handler opens Nova Sonic 2 bidirectional streaming in `eu-north-1`.
4. ARIA uses the same banking tools, policies, vulnerability handling, and audit path.
5. `aria-lex-fulfillment` bridges Lex / Connect text turns back to AgentCore where required.
6. Escalation and transfer metadata flows back to Connect.

### 2.3 AWS services used

| Service | Region | Purpose |
|---|---|---|
| Amazon Bedrock AgentCore Runtime | `eu-west-2` | Hosts `aria_banking_agent` chat + voice runtime |
| Amazon Bedrock Claude Sonnet 4.6 | `eu-west-2` | Primary chat reasoning model |
| Amazon Bedrock Nova Sonic 2 | `eu-north-1` | Real-time speech-to-speech voice model |
| S3 transcript bucket | `eu-west-2` | `meridian-aria-transcripts-<id>` transcript storage |
| S3 audit bucket | `eu-west-2` | `meridian-aria-audit-<id>` immutable WORM archive |
| S3 client bucket | `eu-west-2` | `meridian-aria-client-<id>` React static hosting origin |
| DynamoDB | `eu-west-2` | `aria-audit-events` hot audit query store / TTL-backed records |
| EventBridge | `eu-west-2` | `aria-audit` custom audit event bus |
| CloudTrail Lake | `eu-west-2` | `aria-banking-audit` immutable 7-year audit store |
| Lambda | `eu-west-2` | `aria-audit-cloudtrail-writer`, `aria-audit-dynamodb-writer`, `aria-lex-fulfillment`, `aria-session-injector` |
| Kinesis Firehose | `eu-west-2` | `aria-audit-firehose` delivery to audit S3 WORM bucket |
| Cognito Identity Pool | `eu-west-2` | Browser identity for SigV4 chat/voice invoke |
| CloudFront | Global | HTTPS delivery of the React client |
| ECR | `eu-west-2` | `bedrock-agentcore-aria-banking-agent` container image repository |
| AgentCore Memory | `eu-west-2` | `aria_bank_mem` long-term memory when provisioned |

### 2.4 Bedrock models

| Path | Model | Runtime behavior |
|---|---|---|
| Chat | `anthropic.claude-sonnet-4-6` / `eu.anthropic.claude-sonnet-4-6` | Text reasoning for banking workflows |
| Voice | `amazon.nova-2-sonic-v1:0` | Bidirectional audio streaming for live voice conversations |

---

## 3. Prerequisites

| Requirement | Detail |
|---|---|
| AWS CLI v2 | Installed and authenticated |
| AgentCore CLI | `pip install bedrock-agentcore-starter-toolkit` |
| Python | `3.12+` |
| Docker | Required if using local container build mode |
| uv | Recommended Python workflow tool |
| Bedrock access | Claude Sonnet in `eu-west-2`; Nova Sonic 2 in `eu-north-1` |
| Amazon Connect | Existing Connect instance ID available |
| Node / npm | Required to build and deploy the React client |
| Repository state | Clean checkout of `awsagentcore` |

**Operational note:** `.bedrock_agentcore.yaml` is regenerated by `scripts/deploy.sh` during cloud deployment if missing or stale.

---

## 4. Deployment Strategy

### 4.1 Deployment phases

| Phase | Objective | Notes |
|---|---|---|
| 1. Foundation infrastructure | Create S3 buckets, DynamoDB, EventBridge, CloudTrail Lake | Establishes storage, retention, and audit baselines |
| 2. AgentCore container build/push | Regenerate `.bedrock_agentcore.yaml`, create memory, and build/push the runtime container | Uses CodeBuild by default; local Docker build is optional |
| 3. Audit Lambdas and fan-out | Create IAM roles, audit Lambdas, Firehose, and EventBridge rules | In the current script this is completed before live traffic is allowed |
| 4. Fulfillment Lambda | Deploy `aria-lex-fulfillment` | Enables Lex / Connect request bridging into AgentCore |
| 5. Session Injector | Deploy `aria-session-injector` | Preloads customer and contact context before the Lex block |
| 6. Cognito | Create Identity Pool and unauthenticated invoke role | Enables browser-based SigV4 access |
| 7. React client (CloudFront) | Create client S3 bucket, CloudFront distribution, and upload `dist/` | Completes end-user web delivery |
| 8. Validation and handover | Run status, smoke, audit, and client checks | Must pass before declaring success |

### 4.2 Deployment modes

| Mode | Command | Use case |
|---|---|---|
| Local development | `./scripts/deploy.sh deploy local` | Developer setup with `.venv`, localhost endpoints, local `uvicorn` |
| AgentCore cloud | `./scripts/deploy.sh deploy agentcore` | Staging and production cloud deployment |
| Status | `./scripts/deploy.sh status` | Current runtime and resource state |
| Costs | `./scripts/deploy.sh costs` | Current month spend check |
| Teardown | `./scripts/deploy.sh teardown` | Full resource removal with confirmation |

### 4.3 Release sequencing rule

Promote in order: **local-dev → staging → production**. No production deployment may proceed until staging smoke tests, audit checks, and CloudFront delivery checks pass.

---

## 5. Environment Matrix

| Environment | Region | Deployment mode | Purpose | Notes |
|---|---|---|---|---|
| `local-dev` | Workstation / localhost | `deploy local` | Developer integration and prompt/tool validation | Local `uvicorn`, React dev server, optional Docker/local-build testing, mock/stub bank API |
| `staging` | `eu-west-2` | `deploy agentcore` | Pre-production validation | Use isolated deploy ID / suffix and test Connect instance |
| `production` | `eu-west-2` | `deploy agentcore` | Customer-facing runtime | Controlled window only; audit path mandatory |

### Key environment variables

| Variable | Standard value | Purpose |
|---|---|---|
| `AWS_REGION` | `eu-west-2` | Default AWS CLI / AgentCore region |
| `AGENTCORE_REGION` | `eu-west-2` | AgentCore runtime, Lambda, EventBridge, DynamoDB region |
| `BEDROCK_MODEL_ID` | `eu.anthropic.claude-sonnet-4-6` | Preferred explicit Claude model/inference profile override |
| `NOVA_SONIC_REGION` | `eu-north-1` | Voice model region |
| `STACK_SUFFIX` | environment-specific | Operational naming suffix when wrapping the deploy script |
| `BANK_API_BASE_URL` | environment-specific | Banking API endpoint |
| `CONNECT_INSTANCE_ID` | environment-specific | Amazon Connect instance UUID |

**Important:** the script persists a generated `deploy_id` in `scripts/.deploy-state.json` and uses that for bucket and pool names. If an external release wrapper uses `STACK_SUFFIX`, map it to the retained deployment identifier for traceability.

---

## 6. Change Management

### 6.1 Change types

| Change type | Examples | Approval path |
|---|---|---|
| Standard | React-only update, non-breaking Lambda patch, config correction | Platform Engineering lead + service owner |
| Major | Model change, IAM policy change, AgentCore runtime change, Cognito/CloudFront change | Platform Engineering + Security + Product owner |
| Emergency | Sev1 outage fix, rollback, runtime disablement | Incident commander approval; retrospective required |

### 6.2 Freeze periods

Production changes are prohibited during:

- Declared bank-wide change freezes
- Last business day of the month and first business day of the next month
- Quarter-end and year-end close windows
- Active Sev1/Sev2 customer-impacting incidents unless the change is the approved emergency fix

### 6.3 Production deployment window

- **Approved window:** **Tuesday / Thursday, 19:00–23:00 UTC**
- Deploy outside this window only under emergency change control.

---

## 7. Risk Register

| ID | Risk | Probability | Impact | Mitigation | Owner |
|---|---|---:|---:|---|---|
| R-01 | Bedrock model not enabled in target region | Medium | High | Validate Claude and Nova access before deployment; block release if missing | AI Platform |
| R-02 | ECR push failure during AgentCore build/push | Medium | High | Use CodeBuild default path, verify repo permissions, retain prior image digest | Platform Engineering |
| R-03 | AgentCore container OOM or unstable runtime | Medium | High | Smoke test after launch, tail runtime logs, rollback to prior image if latency/errors spike | Platform Engineering |
| R-04 | Nova Sonic unavailable in `eu-north-1` | Low | High | Validate model availability pre-change; hold voice release or fail over to approved alternate voice region if authorized | AI Platform |
| R-05 | CloudFront propagation delay | High | Medium | Announce 5–15 minute propagation window; invalidate after upload; do not cut over instantly | Frontend Engineering |
| R-06 | Cognito misconfiguration causes browser 403s | Medium | High | Validate identity pool ID, unauth role policy, and SigV4 permissions before sign-off | Identity / Platform Engineering |
| R-07 | WORM audit bucket deletion blocked | High | Medium | Treat as expected compliance behavior; do not make teardown dependent on audit bucket deletion | Security / Compliance |
| R-08 | Connect flow routing failure after Lambda or Lex change | Medium | High | Keep prior Lambda package and flow version, run Connect smoke path immediately after deploy | Contact Centre Engineering |

---

## 8. Rollback Strategy

### 8.1 Mandatory rollback prerequisites

- Back up `scripts/.deploy-state.json` before every production deployment.
- Retain the last known-good ECR image tag/digest.
- Retain the previous Lambda ZIP or Git commit for each Lambda.
- Retain the previous React `dist/` bundle or Git commit for the client.

### 8.2 Rollback by resource

| Resource | Rollback method | Evidence required |
|---|---|---|
| AgentCore runtime | Re-deploy the previously approved ECR image/tag and confirm runtime health | `./scripts/deploy.sh status`, runtime logs, successful invoke |
| Audit / integration Lambdas | Re-publish previous ZIP using `aws lambda update-function-code` and confirm function state `Active` | Lambda configuration shows `Successful`; smoke path clears |
| React client | Rebuild or restore prior `dist/`, sync to S3, invalidate CloudFront | Client loads prior known-good UI |
| Cognito / CloudFront config | Re-apply previous role policy / distribution state from change record | Browser invoke succeeds without 403 |

### 8.3 Rollback order

1. **Client-only incident:** rollback React client first.
2. **Lambda integration incident:** rollback the affected Lambda before touching the runtime.
3. **Runtime incident:** rollback AgentCore image/runtime after preserving state file.
4. **Compliance / audit incident:** keep customer path stable, but restore EventBridge/Lambda/Firehose pipeline immediately.

---

## 9. Communication Plan

### 9.1 Stakeholder matrix

| Stakeholder | Interest | When to notify |
|---|---|---|
| Platform Engineering | Deployment execution and rollback ownership | Start, completion, rollback, blocker |
| AI Platform | Bedrock / AgentCore / model health | Pre-check failure, runtime issue, voice issue |
| Contact Centre Engineering | Connect / Lex / session injector readiness | Before production deploy and after voice validation |
| Security / Compliance | Audit storage, CloudTrail, WORM posture | Any audit-path degradation or teardown request |
| Product / Service Owner | Business readiness and customer impact | Start, completion, failed release |
| Service Desk / Operations | Customer-facing awareness | Production start/end and incident activation |

### 9.2 Announcement templates

**Deployment start**

> ARIA Banking Agent production deployment is starting now. Window: Tuesday/Thursday 19:00–23:00 UTC. Scope: AgentCore runtime, integration Lambdas, Cognito/CloudFront delivery, audit path validation. Expected customer impact: none / brief UI propagation delay only. Rollback plan and state backup confirmed.

**Deployment complete**

> ARIA Banking Agent deployment completed successfully. AgentCore runtime is healthy, chat response latency is within target, voice path validated, CloudWatch errors are zero, and audit events are flowing to DynamoDB / Firehose / CloudTrail Lake. CloudFront propagation may continue for up to 15 minutes.

**Rollback notice**

> ARIA Banking Agent rollback has been initiated due to failed validation. Customer-impacting changes are being reversed in this order: client / Lambda / runtime as applicable. Further update in 15 minutes or earlier on stabilization.

---

## 10. Success Criteria

| Gate | Acceptance criteria |
|---|---|
| Foundation | Buckets, `aria-audit-events`, `aria-audit`, CloudTrail Lake, Firehose, and audit Lambdas exist |
| Runtime | `aria_banking_agent` runtime ARN present and invokable |
| Chat | ARIA answers a representative banking query in **< 10 seconds** |
| Voice | Voice session connects / starts in **< 5 seconds** |
| Frontend | CloudFront URL serves the React app and SigV4 invokes succeed |
| Operations | CloudWatch reports **0 errors** for the post-deploy validation window |
| Compliance | Audit events visible in DynamoDB and delivered to immutable storage path |

---

## 11. Post-Deployment Validation

Complete the companion runbook checks before closing the change:

- `./scripts/deploy.sh status`
- `agentcore invoke '{"message": "Hello Aria", "authenticated": true, "customer_id": "CUST-001"}'`
- `python3 scripts/test_invoke.py`
- CloudWatch log review for runtime and Lambdas
- DynamoDB scan/query confirming audit events
- CloudFront URL load and Cognito-backed browser invoke test
- Connect / voice path check if the change touched Lambda or voice functionality

---

## 12. Contacts and Escalation

| Role | Responsibility | Escalate when |
|---|---|---|
| Platform Engineering on-call | Primary deploy / rollback execution | Script failure, runtime failure, client delivery issue |
| AI Platform on-call | Model availability, AgentCore, Nova Sonic | Model access denied, bidirectional stream failure, AgentCore instability |
| Contact Centre Engineering | Amazon Connect / Lex / routing | Session injector, fulfillment, routing, or transfer issue |
| Security / Compliance | Audit retention and compliance exceptions | CloudTrail / WORM / audit loss concern |
| Product owner | Customer impact decisions | Release delay, rollback decision, degraded feature acceptance |

**Escalation path:** Platform Engineering → AI Platform / Contact Centre Engineering → Security / Compliance → Product owner / incident commander.

---

## 13. Approvals

| Role | Approval required | Status |
|---|---|---|
| Platform Engineering Lead | Yes | Pending |
| AI Platform Owner | Yes | Pending |
| Contact Centre Engineering Lead | For voice / Connect changes | Pending |
| Security / Compliance | For audit / IAM / retention changes | Pending |
| Product Owner | For production release | Pending |
