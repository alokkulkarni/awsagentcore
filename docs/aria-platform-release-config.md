# ARIA Platform — Release Configuration & Deployment Tracker

> **Document type:** Living configuration management + release tracking document  
> **Region:** `eu-west-2`  
> **Account:** `395402194296`  
> **Last audited:** 2026-04-25  
> **Audience:** Engineering, DevOps, Security

---

## How to read this document

| Symbol | Meaning |
|---|---|
| ✅ **Deployed** | Resource exists in AWS and is operational |
| ⚠️ **Deployed — update pending** | Exists in AWS but code changes are required |
| 🔴 **Code exists — never deployed** | Source file is in the repo but no AWS resource exists |
| 🆕 **Not yet built** | Neither source nor AWS resource exists; required for upcoming feature |
| ⚪ **Out of scope** | Code exists but belongs to a separate feature not in current scope |

---

## 1. Lambda Functions

| # | Function Name | Source File | Deploy Status | Connect Associated | Teardown Script | Notes |
|---|---|---|---|---|---|---|
| 1 | `aria-dtmf-decrypt` | `scripts/lambdas/aria_dtmf_decrypt.py` | ✅ Deployed (2026-04-24) | ✅ Yes | `deploy_dtmf_lambda.sh teardown` | Decrypts DTMF payload via RSA key from Secrets Manager |
| 2 | `aria-dtmf-start-session` | `scripts/lambdas/aria_dtmf_start_session.py` | ⚠️ Deployed — update pending | ✅ Yes | `deploy_dtmf_lambda.sh teardown` | Needs to write `status=awaiting_config` for configurable validation feature |
| 3 | `aria-dtmf-validate` | `scripts/lambdas/aria_dtmf_validate.py` | ⚠️ Deployed — update pending | ✅ Yes | `deploy_dtmf_lambda.sh teardown` | Needs to read `dtmf_skip_ownership` contact attr and honour it |
| 4 | `aria-dtmf-status-proxy` | `scripts/lambdas/aria_dtmf_status_proxy.py` | ⚠️ Deployed — update pending | ❌ No (API GW) | `deploy_dtmf_lambda.sh teardown` | Needs `POST /dtmf-configure` route handler added |
| 5 | `aria-routing-lookup` | `scripts/lambdas/aria_routing_lookup.py` | ✅ Deployed (2026-04-09) | ✅ Yes | `deploy_routing_lambda.sh teardown` | Proficiency-based queue routing |
| 6 | `aria-session-injector-qconnect` | `scripts/lambdas/session_injector_qconnect.py` | ✅ Deployed (2026-04-07) | ✅ Yes | `deploy_session_injector_qconnect.sh` (no teardown cmd) | Q Connect session context injector |
| 7 | `aria-banking-session-injector-prod` | `scripts/lambdas/session_injector.py` | ✅ Deployed (2026-04-10) | ❌ No | `deploy_mcp_gateway.sh teardown` | Injects customer context into Q Connect sessions |
| 8 | `aria-banking-mcp-account-prod` | `scripts/lambdas/mcp_tools/` | ✅ Deployed (2026-04-10) | ❌ No | `deploy_mcp_gateway.sh teardown` | MCP domain tool — accounts |
| 9 | `aria-banking-mcp-auth-prod` | `scripts/lambdas/mcp_tools/` | ✅ Deployed (2026-04-10) | ❌ No | `deploy_mcp_gateway.sh teardown` | MCP domain tool — authentication |
| 10 | `aria-banking-mcp-credit-card-prod` | `scripts/lambdas/mcp_tools/` | ✅ Deployed (2026-04-10) | ❌ No | `deploy_mcp_gateway.sh teardown` | MCP domain tool — credit cards |
| 11 | `aria-banking-mcp-customer-prod` | `scripts/lambdas/mcp_tools/` | ✅ Deployed (2026-04-10) | ❌ No | `deploy_mcp_gateway.sh teardown` | MCP domain tool — customers |
| 12 | `aria-banking-mcp-debit-card-prod` | `scripts/lambdas/mcp_tools/` | ✅ Deployed (2026-04-10) | ❌ No | `deploy_mcp_gateway.sh teardown` | MCP domain tool — debit cards |
| 13 | `aria-banking-mcp-escalation-prod` | `scripts/lambdas/mcp_tools/` | ✅ Deployed (2026-04-10) | ❌ No | `deploy_mcp_gateway.sh teardown` | MCP domain tool — escalation |
| 14 | `aria-banking-mcp-knowledge-prod` | `scripts/lambdas/mcp_tools/` | ✅ Deployed (2026-04-10) | ❌ No | `deploy_mcp_gateway.sh teardown` | MCP domain tool — knowledge base |
| 15 | `aria-banking-mcp-mortgage-prod` | `scripts/lambdas/mcp_tools/` | ✅ Deployed (2026-04-10) | ❌ No | `deploy_mcp_gateway.sh teardown` | MCP domain tool — mortgages |
| 16 | `aria-banking-mcp-pii-prod` | `scripts/lambdas/mcp_tools/` | ✅ Deployed (2026-04-10) | ❌ No | `deploy_mcp_gateway.sh teardown` | MCP domain tool — PII vault |
| 17 | `aria-banking-mcp-products-prod` | `scripts/lambdas/mcp_tools/` | ✅ Deployed (2026-04-10) | ❌ No | `deploy_mcp_gateway.sh teardown` | MCP domain tool — products |
| 18 | `aria-banking-voice-to-chat-transfer-prod` | `scripts/lambdas/voice_to_chat_transfer.py` | ✅ Deployed (2026-04-10) | ❌ No | `deploy_mcp_gateway.sh teardown` | Voice→chat SMS deflection handler |
| 19 | `aria-banking-chat-to-voice-transfer-prod` | `scripts/lambdas/chat_to_voice_transfer.py` | ✅ Deployed (2026-04-10) | ❌ No | `deploy_mcp_gateway.sh teardown` | Chat→voice callback handler |
| 20 | `aria-audit-dynamodb-writer` | `scripts/lambdas/audit_dynamodb_writer.py` | 🔴 Never deployed | ❌ — | `deploy.sh teardown` | Writes to `aria-audit-events` DynamoDB; EventBridge wiring missing |
| 21 | `aria-audit-cloudtrail-writer` | `scripts/lambdas/audit_cloudtrail_writer.py` | 🔴 Never deployed | ❌ — | `deploy.sh teardown` | Writes to CloudTrail Lake; channel + data store not yet created |
| 22 | `aria-callback-scheduler` | `scripts/lambdas/aria_callback_scheduler.py` | ⚪ Out of scope | ❌ — | Not scripted | Callback scheduling feature — not in current release |
| 23 | `aria-connect-fulfillment` | `scripts/lambdas/aria_connect_fulfillment.py` | ⚪ Out of scope | ❌ — | `deploy.sh teardown` | Lex/AgentCore fulfilment — separate feature |
| 24 | `aria-dtmf-config` | ❌ Not yet written | 🆕 Not yet built | ❌ — | TBD | **New:** validates agent token, writes config attrs, fires audit event |
| 25 | `aria-dtmf-config-check` | ❌ Not yet written | 🆕 Not yet built | ❌ Needs Connect assoc | TBD | **New:** wait-loop poller for Connect flow; returns `dtmf_config_ready` flag |

---

## 2. DynamoDB Tables

| # | Table Name | Deploy Status | Items | TTL | Teardown Script | Notes |
|---|---|---|---|---|---|---|
| 1 | `dtmf_active_sessions` | ✅ Deployed | 0 (live, empties rapidly) | ✅ attr: `ttl` | `deploy_dtmf_lambda.sh teardown` | Active DTMF session tracking; session records self-expire |
| 2 | `aria-customer-cards` | ✅ Deployed | 4 | ❌ Disabled | `deploy_dtmf_lambda.sh teardown` | Customer → card BIN/last-four reference data |
| 3 | `aria-card-bins` | ✅ Deployed | 5 | ❌ Disabled | `deploy_dtmf_lambda.sh teardown` | BIN prefix → card type mapping |
| 4 | `aria-routing-config` | ✅ Deployed | 8 | ❌ Disabled | `deploy_routing_lambda.sh teardown` | Proficiency routing rules; update UUIDs after deploy |
| 5 | `aria-transcript-store` | ✅ Deployed | 0 | ✅ attr: `ttl` | Manual `aws dynamodb delete-table` | Chat/voice transcript storage |
| 6 | `VoiceTestState` | ✅ Deployed | 3 | ❌ Disabled | Manual `aws dynamodb delete-table` | Voice test session state; test/dev use |
| 7 | `aria-audit-events` | 🔴 Never created | — | — | `deploy.sh teardown` | Required by `audit_dynamodb_writer`; 90-day TTL operational audit store |
| 8 | `dtmf_audit_events` | 🆕 Not yet built | — | — | TBD | **New:** DTMF config audit; append-only; IAM DENY on DeleteItem/UpdateItem; 7-year TTL |

---

## 3. API Gateway

### `aria-dtmf-status-proxy-api` (ID: `bz8frqf9f9`)
Endpoint: `https://bz8frqf9f9.execute-api.eu-west-2.amazonaws.com`

| # | Route | Deploy Status | Target Lambda | Teardown Script | Notes |
|---|---|---|---|---|---|
| 1 | `GET /dtmf-active` | ✅ Deployed | `aria-dtmf-status-proxy` | `deploy_dtmf_lambda.sh teardown` | Returns active session `contactId` from DynamoDB |
| 2 | `GET /dtmf-status` | ✅ Deployed | `aria-dtmf-status-proxy` | `deploy_dtmf_lambda.sh teardown` | Returns current `dtmf_status` contact attribute |
| 3 | `POST /dtmf-configure` | 🆕 Not yet built | `aria-dtmf-config` (new) | TBD | **New:** agent submits validation config options before capture starts |

### `aws-tf-elements-api` (ID: `9kmyip1cq7`)
Endpoint: `https://9kmyip1cq7.execute-api.eu-west-2.amazonaws.com`

| # | Route | Deploy Status | Notes |
|---|---|---|---|
| — | Various | ✅ Deployed | Separate API — not part of DTMF stack |

---

## 4. S3 Buckets & Frontend Assets

| # | Bucket / Asset | Deploy Status | Last Modified | Teardown Script | Notes |
|---|---|---|---|---|---|
| 1 | `aria-dtmf-panel-395402194296/dtmf-panel/index.html` | ⚠️ Deployed — update pending | 2026-04-24 | `deploy_dtmf_lambda.sh teardown` | Needs `awaiting_config` in STATUS_MAP + config form UI |
| 2 | `aria-dtmf-panel-395402194296/dtmf-launcher/index.html` | ✅ Deployed | 2026-04-24 | `deploy_dtmf_lambda.sh teardown` | Detects active session, opens panel popup |
| 3 | `meridian-connect-widget-prod` | ✅ Deployed | 2026-04-23 | `deploy_connect_widget.sh` (manual bucket delete) | Meridian Bank Connect chat widget |
| 4 | `nationwide-connect-widget-prod` | ✅ Deployed | 2026-04-24 | `deploy_nationwide_chat_widget.sh` (manual bucket delete) | Nationwide Connect chat widget |
| 5 | `meridian-bank-knowledgebase` | ✅ Deployed | 2026-04-23 | Manual `aws s3 rb --force` | Bedrock knowledge base source documents |
| 6 | `amazon-connect-*` (multiple) | ✅ Deployed | 2026-04-23/24 | Managed by Connect — do not delete manually | Connect call recordings, chat transcripts, access logs |

---

## 5. Amazon Connect

### Connect Instance: `f969d4b4-f716-4974-a325-bb7899f2f293`

#### Contact Flows

| # | Flow Name | Type | Deploy Status | Teardown | Notes |
|---|---|---|---|---|---|
| 1 | `ARIA-DTMF-SecureCollection` | Contact Flow | ⚠️ Deployed — 2 bugs + update pending | Manual (Connect console) | Bug 1: Luhn-fail branch missing `dtmf_status` set. Bug 2: No `isValid` branch after validate Lambda. Pending: add wait loop for configurable validation |
| 2 | `ARIA-DTMF-HumanAgentWrapper` | Queue Transfer | ✅ Deployed | Manual (Connect console) | Wraps DTMF flow to return customer to agent queue |
| 3 | `ARIA-Agent-Screen-Pop-Flow` | Contact Flow | ✅ Deployed | Manual (Connect console) | Screen pop to agent desktop on contact arrival |
| 4 | `Sample secure input with no agent` | Contact Flow | ✅ Deployed (AWS sample) | Manual (Connect console) | AWS-provided sample — reference only |
| 5 | `Sample secure input with agent` | Queue Transfer | ✅ Deployed (AWS sample) | Manual (Connect console) | AWS-provided sample — reference only |

#### Lambda Associations (Connect → Lambda)

| # | Lambda ARN | Associated | Notes |
|---|---|---|---|
| 1 | `aria-dtmf-decrypt` | ✅ Yes | |
| 2 | `aria-dtmf-start-session` | ✅ Yes | |
| 3 | `aria-dtmf-validate` | ✅ Yes | |
| 4 | `aria-routing-lookup` | ✅ Yes | |
| 5 | `aria-session-injector-qconnect` | ✅ Yes | |
| 6 | `aria-dtmf-config-check` | 🆕 Not yet built | Required when Lambda is created for wait-loop |

#### KMS & Secrets Manager (DTMF Encryption Keys)

| # | Resource | Deploy Status | Teardown Script | Notes |
|---|---|---|---|---|
| 1 | KMS key `alias/meridian-connect-dtmf` | ✅ Deployed | `setup_dtmf_keys.sh teardown` | Protects RSA private key in Secrets Manager |
| 2 | Secret `meridian/connect/dtmf-private-key` | ✅ Deployed | `setup_dtmf_keys.sh teardown` | RSA private key for DTMF decryption |
| 3 | Connect security key (public key uploaded) | ✅ Deployed | Manual (Connect console → Security keys) | Public key registered in Connect for DTMF encryption |

---

## 6. EventBridge & Audit Pipeline

| # | Component | Deploy Status | Teardown Script | Notes |
|---|---|---|---|---|
| 1 | EventBridge bus `aria-audit` | 🔴 Never created | `deploy.sh teardown` | Custom audit event bus; deploy.sh creates it but script has never been run |
| 2 | EventBridge rule `aria-audit-to-dynamodb` | 🔴 Never created | `deploy.sh teardown` | Routes audit events → `aria-audit-dynamodb-writer` Lambda |
| 3 | EventBridge rule `aria-audit-to-cloudtrail` | 🔴 Never created | `deploy.sh teardown` | Routes audit events → `aria-audit-cloudtrail-writer` Lambda |
| 4 | EventBridge rule `aria-audit-to-firehose` | 🔴 Never created | `deploy.sh teardown` | Routes audit events → Firehose → S3 WORM |
| 5 | EventBridge rule `dtmf-config-to-audit` | 🆕 Not yet built | TBD | **New:** routes `dtmf.validation.config.set` events to audit Lambdas |
| 6 | CloudTrail Lake event data store | 🔴 Never created | `deploy.sh teardown` | 7-year immutable retention; deploy.sh provisions it but never run |
| 7 | CloudTrail Lake custom channel `aria-banking-audit` | 🔴 Never created | `deploy.sh teardown` | Custom channel for application-emitted audit events |
| 8 | Kinesis Firehose `aria-audit-firehose` | 🔴 Never created | `deploy.sh teardown` | S3 WORM delivery stream for audit events |

---

## 7. CloudFormation

| # | Template | Exists in Repo | Stack Deployed | Notes |
|---|---|---|---|---|
| 1 | `marketplace/cloudformation/dtmf-secure-capture.yaml` | ✅ Yes | ❌ No deployed stack | Marketplace/installer artefact only. All DTMF resources deployed manually via `deploy_dtmf_lambda.sh`. Template needs updating when configurable validation feature is built. |

---

## 8. Teardown Scripts Reference

This table shows which script tears down which AWS resources. Run scripts in the order shown to avoid dependency failures.

| Order | Script | Command | What it removes |
|---|---|---|---|
| 1 | `scripts/setup_dtmf_keys.sh` | `./scripts/setup_dtmf_keys.sh teardown` | KMS key `alias/meridian-connect-dtmf`, Secrets Manager secret `meridian/connect/dtmf-private-key`, local private key file |
| 2 | `scripts/deploy_dtmf_lambda.sh` | `./scripts/deploy_dtmf_lambda.sh teardown` | Lambdas: `aria-dtmf-decrypt`, `aria-dtmf-validate`, `aria-dtmf-start-session`, `aria-dtmf-status-proxy`; Lambda Layer `aria-dtmf-dependencies`; DynamoDB: `aria-card-bins`, `aria-customer-cards`, `dtmf_active_sessions`; API Gateway `aria-dtmf-status-proxy-api`; IAM roles: `aria-dtmf-decrypt-role`, `aria-lambda-dtmf-validate-role`, `aria-lambda-dtmf-start-session-role`, `aria-lambda-dtmf-status-proxy-role`; CloudWatch log groups |
| 3 | `scripts/deploy_routing_lambda.sh` | `./scripts/deploy_routing_lambda.sh teardown` | Lambda: `aria-routing-lookup`; DynamoDB: `aria-routing-config`; IAM role: `aria-routing-lookup-role`; CloudWatch log group |
| 4 | `scripts/deploy_mcp_gateway.sh` | `./scripts/deploy_mcp_gateway.sh teardown` | All 10 `aria-banking-mcp-*-prod` Lambdas; `aria-banking-session-injector-prod`; `aria-banking-voice-to-chat-transfer-prod`; `aria-banking-chat-to-voice-transfer-prod`; MCP Gateway targets; IAM role `aria-mcp-lambda-role` |
| 5 | `scripts/deploy.sh` | `./scripts/deploy.sh teardown` | AgentCore Runtime endpoint; ECR repo; EventBridge bus `aria-audit` + rules; Lambdas: `aria-audit-cloudtrail-writer`, `aria-audit-dynamodb-writer`; Kinesis Firehose `aria-audit-firehose`; IAM roles: `aria-lambda-audit-role`, `aria-lambda-fulfillment-role`; S3 buckets: transcript, audit; CloudFront distribution; DynamoDB `aria-audit-events`; CloudTrail Lake channel + data store |
| 6 | `scripts/deploy_session_injector_qconnect.sh` | No teardown command — manual | Lambda: `aria-session-injector-qconnect`; IAM role (manual `aws lambda delete-function`) |
| 7 | `scripts/deploy_connect_widget.sh` | No teardown command — manual | CloudFront distribution; S3 bucket `meridian-connect-widget-prod` (manual) |
| 8 | `scripts/deploy_nationwide_chat_widget.sh` | No teardown command — manual | S3 bucket `nationwide-connect-widget-prod` (manual) |
| 9 | **Connect console** (manual) | N/A | Contact flows: `ARIA-DTMF-SecureCollection`, `ARIA-DTMF-HumanAgentWrapper`, `ARIA-Agent-Screen-Pop-Flow`; Lambda associations; Security key |

> ⚠️ **Note:** `deploy_session_injector_qconnect.sh`, `deploy_connect_widget.sh`, and `deploy_nationwide_chat_widget.sh` do not have a `teardown` command. Resources must be deleted manually via AWS CLI or console.

---

## 9. Upcoming Work — Configurable Validation Feature (Approach B)

These components are required for the agent-configurable validation feature (agent can optionally disable ownership check before triggering DTMF capture, with immutable audit trail).

| # | Component | Type | Action | Priority |
|---|---|---|---|---|
| 1 | `aria-dtmf-config` Lambda | New Lambda | Build + deploy; add API GW integration | High |
| 2 | `aria-dtmf-config-check` Lambda | New Lambda | Build + deploy; add Connect association | High |
| 3 | `POST /dtmf-configure` API route | New API GW route | Add to `aria-dtmf-status-proxy-api` | High |
| 4 | `dtmf_audit_events` DynamoDB table | New Table | Create with append-only IAM policy + 7-year TTL | High |
| 5 | `aria-dtmf-start-session` Lambda | Update existing | Change initial status to `awaiting_config` | High |
| 6 | `aria-dtmf-validate` Lambda | Update existing | Read + honour `dtmf_skip_ownership` contact attr | High |
| 7 | `aria-dtmf-status-proxy` Lambda | Update existing | Add `POST /dtmf-configure` handler | High |
| 8 | `dtmf-status-panel/index.html` | Update existing | Add `awaiting_config` to STATUS_MAP; render config form UI | High |
| 9 | `ARIA-DTMF-SecureCollection` Connect flow | Update existing | Add wait-loop block after start-session (manual in console) | High |
| 10 | EventBridge rule `dtmf-config-to-audit` | New rule | Route `dtmf.validation.config.set` → audit Lambdas | Medium |
| 11 | `aria-audit-dynamodb-writer` Lambda | Deploy existing code | First-time deploy of existing `audit_dynamodb_writer.py` | Medium |
| 12 | `aria-audit-cloudtrail-writer` Lambda | Deploy existing code | First-time deploy; requires CloudTrail Lake channel first | Medium |
| 13 | `aria-audit-events` DynamoDB table | Create missing | Required by audit_dynamodb_writer | Medium |
| 14 | CloudTrail Lake channel + data store | Create missing | 7-year immutable audit; required by audit_cloudtrail_writer | Medium |

---

## 10. Known Bugs — Outstanding (Manual Connect Console Fixes Required)

| # | Bug | Location | Impact | Fix Required |
|---|---|---|---|---|
| 1 | Luhn-fail branch does not set `dtmf_status` | `ARIA-DTMF-SecureCollection` flow | Panel stays stuck at `validating_card` indefinitely | Add `Set contact attributes` block on Luhn-fail branch: `dtmf_status=validation_failed` |
| 2 | Success prompt plays unconditionally after validate Lambda | `ARIA-DTMF-SecureCollection` flow | Customer hears "card captured" even on ownership mismatch | Add `Check contact attributes` block on `$.External.isValid`; route No Match to escalation prompt + set `dtmf_requires_escalation=true` |

---

## 11. Deployment Status Summary

| Category | ✅ Deployed & OK | ⚠️ Deployed, needs update | 🔴 Code exists, never deployed | 🆕 Not yet built |
|---|---|---|---|---|
| Lambda functions | 19 | 3 | 2 | 2 |
| DynamoDB tables | 6 | 0 | 1 (`aria-audit-events`) | 1 (`dtmf_audit_events`) |
| API Gateway routes | 2 | 0 | 0 | 1 |
| Frontend (S3) | 2 | 1 (status panel) | 0 | 0 |
| Connect flows | 4 | 1 (`ARIA-DTMF-SecureCollection`) | 0 | 0 |
| EventBridge / CloudTrail / Firehose | 0 | 0 | 4 | 1 |
| **Total** | **33** | **5** | **7** | **5** |
