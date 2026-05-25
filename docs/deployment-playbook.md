# Deployment Playbook — ARIA Platform

| Field | Value |
|---|---|
| **Document ID** | PLY-ARIA-001 |
| **Version** | 1.0 |
| **Status** | Active |
| **Owner** | Platform Engineering |
| **Review Cycle** | Quarterly |
| **Last Updated** | 2026-05-25 |
| **Classification** | Internal |

---

## Table of Contents

1. [Purpose and Scope](#1-purpose-and-scope)
2. [Platform Overview](#2-platform-overview)
3. [Prerequisites and Dependencies](#3-prerequisites-and-dependencies)
4. [Deployment Strategy](#4-deployment-strategy)
5. [Environment Matrix](#5-environment-matrix)
6. [Change Management](#6-change-management)
7. [Risk Register](#7-risk-register)
8. [Rollback Strategy](#8-rollback-strategy)
9. [Communication Plan](#9-communication-plan)
10. [Success Criteria](#10-success-criteria)
11. [Post-Deployment Validation](#11-post-deployment-validation)
12. [Contacts and Escalation](#12-contacts-and-escalation)
13. [Approvals](#13-approvals)

---

## 1. Purpose and Scope

This playbook defines the authoritative strategy, sequencing, risk controls, and stakeholder communication for deploying the ARIA platform — Meridian Bank's AI-powered contact centre intelligence suite.

### 1.1 In Scope

| Component | Description |
|---|---|
| **ARIA Banking Agent** | Core Bedrock AgentCore runtime — Meridian's AI banking assistant (chat + voice) |
| **Connect Analytics Agent** | Strands-based analytics agent with 9 Lambda tools and React dashboard |
| **Brainstorming Agent** | Internal AI brainstorming workspace (FastAPI + React) |
| **Marketplace — DTMF Secure Capture** | PCI DSS RSA-encrypted keypad capture for Amazon Connect |
| **ARIA Evaluator TS** | Automated quality evaluation platform for AI agents |
| **Meridian Chat Widget** | Amazon Connect chat widget for Meridian Bank website |
| **Nationwide Chat Widget** | Amazon Connect chat widget for Nationwide integration |
| **Connect Lambda Platform** | All supporting Lambda functions: routing, callback, MCP gateway, WebRTC API, DTMF, session injector, meeting ID |
| **Knowledgebase** | Meridian Bank S3-backed knowledge store for Q in Connect |

### 1.2 Out of Scope

- Amazon Connect instance provisioning (pre-existing)
- AWS account creation or organisation-level setup
- DNS and certificate management beyond CloudFront defaults
- Third-party CRM integrations (documented separately)

---

## 2. Platform Overview

### 2.1 Architecture Summary

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         ARIA Platform                                   │
│                                                                         │
│  ┌───────────────────┐    ┌──────────────────────┐                     │
│  │  Meridian Chat    │    │  Nationwide Chat     │                     │
│  │  Widget (CFront)  │    │  Widget (CFront)     │                     │
│  └─────────┬─────────┘    └──────────┬───────────┘                     │
│            │                         │                                 │
│            ▼                         ▼                                 │
│  ┌─────────────────────────────────────────────────────────────┐       │
│  │               Amazon Connect Instance                       │       │
│  │  Contact Flows  │  Session Injector  │  Lex V2 + ARIA       │       │
│  └──────────────────────────┬──────────────────────────────────┘       │
│                             │                                          │
│            ┌────────────────┼────────────────────┐                    │
│            ▼                ▼                    ▼                    │
│  ┌──────────────┐  ┌─────────────────┐  ┌──────────────────────┐      │
│  │ ARIA Banking │  │ Connect Analytics│  │  DTMF Secure Capture │      │
│  │ Agent        │  │ Agent           │  │  (Marketplace)       │      │
│  │ AgentCore    │  │ Lambda × 9      │  │  Lambda × 4          │      │
│  │ eu-west-2    │  │ AgentCore GW    │  │  DynamoDB            │      │
│  └──────────────┘  └─────────────────┘  └──────────────────────┘      │
│            │                │                                          │
│            ▼                ▼                                          │
│  ┌──────────────────────────────────────────────────────────────┐      │
│  │                Supporting Infrastructure                     │      │
│  │  S3 × 5  │  DynamoDB × 2  │  EventBridge  │  CloudTrail     │      │
│  │  Firehose │  Cognito       │  ECR           │  CloudFront × N │      │
│  └──────────────────────────────────────────────────────────────┘      │
│                                                                         │
│  ┌────────────────────────────┐   ┌──────────────────────────────┐     │
│  │ ARIA Evaluator TS          │   │  Brainstorming Agent         │     │
│  │ ECS Fargate + CloudFront   │   │  Docker / Cloud (FastAPI)    │     │
│  └────────────────────────────┘   └──────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 AWS Regions

| Service | Region | Rationale |
|---|---|---|
| ARIA AgentCore + most services | `eu-west-2` (London) | Data residency — UK customers |
| Nova Sonic 2 voice model | `eu-north-1` (Stockholm) | Nova Sonic 2 availability |
| Connect Analytics Agent | `us-east-1` (default, configurable) | Connect API availability |
| Amazon Connect instance | Customer-defined | Pre-existing |

### 2.3 Repository Structure

```
awsagentcore/
├── aria/                          # ARIA banking agent source
├── scripts/                       # ARIA + platform deploy scripts
│   ├── deploy.sh                  # Main ARIA deploy (AgentCore + CloudFront)
│   ├── lambdas/                   # All Lambda source files
│   ├── deploy_dtmf_lambda.sh
│   ├── deploy_routing_lambda.sh
│   ├── deploy_callback_lambda.sh
│   ├── deploy_mcp_gateway.sh
│   ├── deploy_webrtc_api.sh
│   ├── deploy_meeting_id_lambda.sh
│   ├── deploy_session_injector_qconnect.sh
│   ├── deploy_connect_widget.sh
│   ├── deploy_nationwide_chat_widget.sh
│   └── upload_knowledgebase_to_s3.sh
├── connect-analytics-agent/       # Analytics agent + frontend
│   └── deploy.sh
├── brainstorming-agent/           # Brainstorming agent + frontend
│   └── docker/
├── marketplace/                   # DTMF Secure Capture product
│   └── cloudformation/
├── aria-evaluator-ts/             # Evaluation platform
│   └── infra/
├── connect-chat-widget/           # Meridian chat widget
├── nationwide_chat_widget/        # Nationwide chat widget
└── knowledgebase/                 # Q in Connect knowledge sources
```

---

## 3. Prerequisites and Dependencies

### 3.1 Access Requirements

| Requirement | Detail | Validated By |
|---|---|---|
| AWS CLI v2 | Configured with IAM credentials | `aws sts get-caller-identity` |
| IAM permissions | `AdministratorAccess` or scoped policy (see §3.2) | Pre-deployment IAM review |
| Amazon Connect instance | Existing instance ID (UUID) | Connect console |
| Bedrock model access | Claude Sonnet 4.6 (eu-west-2), Nova Sonic 2 (eu-north-1) | Bedrock console → Model Access |
| AgentCore CLI | `pip install bedrock-agentcore-starter-toolkit` | `agentcore --version` |
| Docker | Desktop 4.x+ or compatible engine | `docker --version` |
| Node.js | v20+ | `node --version` |
| Python | 3.12+ | `python3 --version` |
| jq | Required by analytics deploy.sh | `jq --version` |
| uv | Python package manager (recommended) | `uv --version` |
| OpenSSL | RSA key generation for DTMF | `openssl version` |

### 3.2 Minimum IAM Permissions

The deploying principal requires access to:
- `iam:CreateRole`, `iam:AttachRolePolicy`, `iam:PutRolePolicy`, `iam:PassRole`
- `lambda:CreateFunction`, `lambda:UpdateFunctionCode`, `lambda:AddPermission`
- `s3:CreateBucket`, `s3:PutObject`, `s3:PutBucketPolicy`
- `cloudfront:CreateDistribution`, `cloudfront:CreateOriginAccessControl`
- `cognito-identity:CreateIdentityPool`
- `bedrock-agentcore:CreateAgentRuntime` (custom service role)
- `apigateway:*`
- `dynamodb:CreateTable`
- `events:PutRule`, `events:PutTargets`
- `firehose:CreateDeliveryStream`
- `cloudtrail:CreateEventDataStore`
- `ecr:CreateRepository`, `ecr:GetAuthorizationToken`
- `secretsmanager:CreateSecret` (DTMF)
- `kms:CreateKey`, `kms:CreateAlias` (DTMF)
- `ecs:RegisterTaskDefinition`, `ecs:CreateService` (evaluator)
- `cloudformation:*` (marketplace DTMF)

### 3.3 Pre-Deployment Checklist

- [ ] AWS credentials confirmed with `aws sts get-caller-identity`
- [ ] Bedrock model access confirmed in both `eu-west-2` and `eu-north-1`
- [ ] Amazon Connect instance ID available
- [ ] All tooling versions verified (Node 20+, Python 3.12+, Docker)
- [ ] Repository cloned and on the correct branch/tag
- [ ] Environment-specific `.env` files prepared (do not commit)
- [ ] DTMF RSA key pair generated (for marketplace deployment)
- [ ] Connect Security Profile RSA public key loaded
- [ ] Knowledgebase documents uploaded or available locally
- [ ] Peer review completed for any IaC changes

---

## 4. Deployment Strategy

### 4.1 Deployment Phases

Deployment is sequenced to satisfy hard dependencies. Each phase must complete and pass its verification gate before the next begins.

```
Phase 1: Foundation                 (IAM, S3, DynamoDB, EventBridge)
    │
    ▼
Phase 2: Core Platform              (ARIA AgentCore, Audit Lambdas, CloudTrail)
    │
    ▼
Phase 3: Connect Integration        (Lambda platform tools, session injector, Lex)
    │
    ▼
Phase 4: Analytics Agent            (9 Lambda tools, AgentCore Gateway, API GW)
    │
    ▼
Phase 5: Marketplace & DTMF         (CloudFormation stack, DTMF Lambdas, panels)
    │
    ▼
Phase 6: Frontends & Widgets        (Chat widgets, React clients, CloudFront)
    │
    ▼
Phase 7: Supporting Applications    (Brainstorming agent, ARIA Evaluator)
    │
    ▼
Phase 8: Post-Deployment            (Smoke tests, monitoring, knowledgebase sync)
```

### 4.2 Deployment Modes

| Mode | When to Use | Command Pattern |
|---|---|---|
| **Local (Docker)** | Feature development, integration testing before cloud | `./deploy.sh local` |
| **Cloud (agentcore)** | Staging and production deployments | `./deploy.sh deploy agentcore` |
| **Update** | Redeploy code changes to existing resources | `./deploy.sh update` |
| **Teardown** | Complete resource cleanup | `./deploy.sh teardown` |

### 4.3 Environment Promotion

```
Developer Local (Docker)
        │  Manual validation
        ▼
     Staging
        │  Integration tests pass
        │  Security scan clean
        ▼
   Production
        │  Change approval
        │  Deployment window
        ▼
   Post-deploy verification
```

---

## 5. Environment Matrix

| Environment | Region | AgentCore Mode | CloudFront | Purpose |
|---|---|---|---|---|
| **local-dev** | N/A | Mock (Docker) | No | Developer iteration |
| **staging** | `eu-west-2` | Live AgentCore | Yes | Integration + QA |
| **production** | `eu-west-2` | Live AgentCore | Yes | Live customer traffic |

### 5.1 Environment-Specific Variables

| Variable | Local | Staging | Production |
|---|---|---|---|
| `AWS_REGION` | N/A | `eu-west-2` | `eu-west-2` |
| `AGENTCORE_REGION` | N/A | `eu-west-2` | `eu-west-2` |
| `BEDROCK_MODEL_ID` | `mock` | `eu.anthropic.claude-sonnet-4-6` | `eu.anthropic.claude-sonnet-4-6` |
| `STACK_SUFFIX` | N/A | `staging` | `prod` |
| `CONNECT_INSTANCE_ID` | N/A | Staging Connect UUID | Production Connect UUID |
| `MOCK_MODE` | `true` | `false` | `false` |

---

## 6. Change Management

### 6.1 Change Classification

| Type | Definition | Approval Required | Deployment Window |
|---|---|---|---|
| **Standard** | Routine code update, no schema changes | Team lead | Business hours |
| **Normal** | Infrastructure change, new resource, config update | Change board | Scheduled maintenance |
| **Emergency** | Critical security fix or production outage | Senior engineer (verbal) | Any time |

### 6.2 Change Freeze Periods

- Last business day of each month (financial reporting)
- Major Amazon Connect platform updates (communicated by AWS)
- DTMF/PCI DSS audit periods

### 6.3 Deployment Window

| Environment | Window |
|---|---|
| Staging | Weekdays 09:00–17:00 local time |
| Production | Tuesday/Thursday 19:00–23:00 local time |
| Emergency | 24/7 with senior approval |

---

## 7. Risk Register

| ID | Risk | Probability | Impact | Mitigation | Owner |
|---|---|---|---|---|---|
| R-01 | Bedrock model access not enabled in target region | Medium | High | Verify in Bedrock console before deploy; add to pre-deploy checklist | Platform Eng |
| R-02 | AgentCore container image build failure | Low | High | Test Dockerfile locally; pin base image versions | DevOps |
| R-03 | IAM permission boundary blocks resource creation | Medium | High | Run IAM dry-run; use least-privilege scoped policy | Security |
| R-04 | Amazon Connect instance ID misconfigured | Low | High | Validate UUID with `aws connect describe-instance` before deploy | Platform Eng |
| R-05 | CloudFront distribution propagation delay (15–30 min) | High | Low | Expect delay; warn in communication plan; do not mark complete until URLs resolve | Platform Eng |
| R-06 | DTMF RSA private key rotation mid-deployment | Low | Critical | Generate keys in a single step; rotate only during maintenance windows | Security |
| R-07 | Lambda cold start causes first-call timeout | High | Low | Provision concurrency for latency-sensitive functions; set appropriate timeouts | Platform Eng |
| R-08 | ECS task fails to pull ECR image | Low | Medium | Ensure ECR repository exists; verify task execution role has `ecr:GetAuthorizationToken` | DevOps |
| R-09 | S3 bucket name collision (global namespace) | Low | Medium | Use `STACK_SUFFIX` timestamp or UUID; check bucket existence before create | Platform Eng |
| R-10 | Cognito identity pool misconfiguration causes 403 | Medium | High | Test unauthenticated Cognito credentials before React deploy; verify trust policy | Platform Eng |
| R-11 | Nova Sonic 2 not available in eu-north-1 | Low | Medium | Check regional availability; fall back to eu-west-2 if needed | Platform Eng |
| R-12 | Connect contact flow import breaks active calls | Medium | Critical | Deploy outside call centre hours; test on staging first | Ops |

---

## 8. Rollback Strategy

### 8.1 Rollback Decision Criteria

Initiate rollback if any of the following occur within 30 minutes of deployment:

- ARIA agent fails to respond to test query
- Error rate on API Gateway > 5% for 5 consecutive minutes
- Connect integration test fails (call not answered by AI)
- DTMF session creation returns non-200 response
- CloudFront returns 5xx on more than 3 consecutive health checks

### 8.2 Rollback Procedures by Component

| Component | Rollback Mechanism | Time to Restore |
|---|---|---|
| ARIA AgentCore | Re-deploy previous container tag from ECR | 5–10 min |
| Lambda functions | `aws lambda update-function-code` with previous zip/version | 2–3 min |
| React frontends (CloudFront) | Re-deploy previous `dist/` build to S3; invalidate cache | 5–10 min + propagation |
| DTMF CloudFormation | `aws cloudformation rollback-stack` | 5–15 min |
| ARIA Evaluator ECS | Update ECS service to previous task definition revision | 5–10 min |
| Connect contact flows | Re-import previous flow JSON from source control | 5 min |
| IAM roles/policies | Revert to previous policy document version (if versioned) | 2 min |

### 8.3 State Management

All deploy scripts maintain a `.deploy-state.json` file that records all created resource ARNs. This file must be preserved to enable teardown and rollback. Back up this file to S3 or a secure store before deployment.

```bash
# Back up deploy state before proceeding
cp scripts/.deploy-state.json scripts/.deploy-state.json.backup-$(date +%Y%m%d%H%M%S)
cp connect-analytics-agent/.deploy-state.json connect-analytics-agent/.deploy-state.json.backup-$(date +%Y%m%d%H%M%S)
```

---

## 9. Communication Plan

### 9.1 Stakeholder Notification Matrix

| Stakeholder | Notify When | Channel | Lead Time |
|---|---|---|---|
| Contact Centre Operations | Production deployment scheduled | Email + Slack | 48 hours |
| Contact Centre Operations | Deployment begins | Slack | 30 minutes before |
| Security / Compliance | DTMF/PCI DSS component changes | Email | 72 hours |
| Customer Success | Outward-facing widget or flow change | Email | 24 hours |
| Engineering Team | All deployments | Slack #deployments | At start |
| Senior Management | Emergency deployments only | Phone / Slack DM | Immediate |

### 9.2 Deployment Announcements

**Start of deployment:**
```
[DEPLOY START] ARIA Platform — <environment> — <date> <time>
Engineer: <name>
Components: <list of components being deployed>
Expected duration: <N> minutes
Rollback plan: Yes — see PLY-ARIA-001 §8
Escalation: <name> <phone>
```

**Completion:**
```
[DEPLOY COMPLETE] ARIA Platform — <environment> — <date> <time>
Status: SUCCESS / FAILED
Components deployed: <list>
CloudFront URLs: <list>
Smoke test: PASS / FAIL
Next steps: <if any>
```

---

## 10. Success Criteria

### 10.1 Phase-Level Gates

| Phase | Success Criterion |
|---|---|
| Phase 1 – Foundation | All S3 buckets, DynamoDB tables, and IAM roles created without error |
| Phase 2 – ARIA Core | AgentCore runtime status = `ACTIVE`; audit Lambda test invocation returns 200 |
| Phase 3 – Connect Integration | Session injector invoked successfully; Lex fulfillment Lambda returns valid response |
| Phase 4 – Analytics Agent | All 9 tool Lambdas invocable; AgentCore Gateway status = `ACTIVE`; React dashboard loads |
| Phase 5 – DTMF Marketplace | CloudFormation stack status = `CREATE_COMPLETE`; DTMF session creation test passes |
| Phase 6 – Frontends | All CloudFront distributions return 200; widgets load in browser |
| Phase 7 – Supporting Apps | Brainstorming agent API returns 200; evaluator UI accessible |
| Phase 8 – Post-Deploy | End-to-end smoke test completes; no errors in CloudWatch for 10 minutes |

### 10.2 Acceptance Criteria

- [ ] ARIA responds to a banking query via chat within 10 seconds
- [ ] ARIA voice call connects and AI responds within 5 seconds
- [ ] Analytics dashboard displays real-time metrics from Connect
- [ ] DTMF capture completes and agent panel shows validation status
- [ ] Chat widgets load on Meridian and Nationwide pages
- [ ] All CloudWatch alarm states are GREEN (not ALARM)
- [ ] Cost estimate for first 24 hours within 20% of baseline

---

## 11. Post-Deployment Validation

### 11.1 Smoke Test Matrix

| Test | Tool/Command | Expected Result |
|---|---|---|
| ARIA chat | POST to AgentCore HTTPS endpoint | 200 + AI response |
| ARIA voice | WebSocket connect to voice endpoint | Successful handshake |
| Analytics agent | Query via React dashboard | Metrics returned |
| DTMF capture | Simulated Connect contact flow | Session created, status returns |
| Chat widget | Browser open Meridian widget page | Widget loads, initiates chat |
| Knowledgebase | Q in Connect query | Returns answer from Meridian KB |
| Evaluator | Navigate to evaluator URL | Dashboard loads, runs listed |

### 11.2 Monitoring Checkpoints

After deployment, monitor the following for a minimum of 30 minutes:

- CloudWatch dashboard: Lambda error rates, duration p99, throttles
- AgentCore runtime health console
- API Gateway 4xx and 5xx metrics
- ECS task health (evaluator)
- CloudFront cache hit ratio and 5xx rate

### 11.3 Cost Baseline Check

Run the cost estimator within 24 hours of deployment:

```bash
./scripts/deploy.sh costs
```

Compare against the pre-deployment cost estimate. Escalate if spend is >50% above estimate.

---

## 12. Contacts and Escalation

| Role | Responsibility | Escalation Path |
|---|---|---|
| **Deployment Engineer** | Executes deployment, monitors progress | Direct contact |
| **Platform Lead** | Technical authority, rollback decisions | Escalation level 1 |
| **Security Officer** | Approves DTMF/PCI DSS changes | Required for DTMF deployments |
| **Contact Centre Ops Manager** | Signs off on Connect flow changes | Required for flow changes |
| **AWS Enterprise Support** | AWS infrastructure issues | Support case (Severity A/B) |
| **On-call Engineer** | Out-of-hours incidents | PagerDuty / on-call schedule |

### 12.1 Escalation Triggers

| Trigger | Response Time | Escalation To |
|---|---|---|
| AgentCore runtime fails to start | 15 minutes | Platform Lead |
| DTMF key compromise suspected | Immediate | Security Officer + Platform Lead |
| Production contact centre impacted | Immediate | Ops Manager + Platform Lead |
| Deployment stalled > 30 min over estimate | 5 minutes | Platform Lead |

---

## 13. Approvals

| Role | Name | Signature | Date |
|---|---|---|---|
| **Deployment Engineer** | | | |
| **Platform Lead** | | | |
| **Security Officer** (DTMF only) | | | |
| **Change Board Representative** (Normal/Major changes) | | | |

---

*This playbook is reviewed quarterly. To propose changes, submit a pull request to `docs/deployment-playbook.md` with the `change-management` label.*
