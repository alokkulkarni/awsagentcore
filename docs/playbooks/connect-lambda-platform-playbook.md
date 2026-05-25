# Connect Lambda Platform Playbook

## Document Control

| Field | Value |
| --- | --- |
| Document ID | PLY-CLP-001 |
| Version | 1.0 |
| Owner | Platform Engineering |
| Date | 2026-05-25 |
| Component | Connect Lambda Platform |

## 1. Purpose and Scope

This playbook defines the deployment and operational control model for the **Connect Lambda Platform** in `awsagentcore`: the supporting Lambda functions, AgentCore MCP gateway resources, and script-driven integrations that sit around Amazon Connect contact flows, Lex V2, and ARIA AgentCore.

### In scope

- `aria-routing-lookup`
- `aria-callback-scheduler`
- `aria-meeting-id-capture`
- `aria-webrtc-api`
- `aria-session-injector-qconnect`
- `aria-lex-fulfillment` (deployed from `aria_connect_fulfillment.py`)
- `aria-banking-mcp-gateway-${ENV}`
- `aria-banking-session-injector-${ENV}`
- `aria-banking-chat-to-voice-transfer-${ENV}`
- `aria-banking-voice-to-chat-transfer-${ENV}`
- MCP domain Lambdas created by `scripts/deploy_mcp_gateway.sh` for `account`, `auth`, `customer`, `escalation`, `knowledge`, `pii`, `mortgage`, `debit-card`, `credit-card`, and `products`

### Out of scope

- DTMF operational procedures and the `aria-banking-mcp-dtmf-${ENV}` contact-flow bridge
- Full ARIA AgentCore platform deployment outside the `deploy_fulfillment_lambda` and `deploy_session_injector_lambda` functions in `scripts/deploy.sh`
- Amazon Connect instance creation, Lex bot authoring, and contact-flow design beyond Lambda integration points

## 2. Architecture

### 2.1 Invocation model

| Resource | Actual deployed name | Primary invoker | Notes |
| --- | --- | --- | --- |
| MCP gateway | `aria-banking-mcp-gateway-${ENV}` | Amazon Connect AI Agent / AgentCore control plane | Gateway resource, not a Lambda |
| Routing lookup | `aria-routing-lookup` | Amazon Connect contact flow | Dynamic queue selection from DynamoDB |
| Callback scheduler | `aria-callback-scheduler` | Amazon Connect callback flow | Reads shared routing table and callback fields |
| Meeting ID capture | `aria-meeting-id-capture` | Amazon Connect IVR | Reads 6-digit input from Lambda event |
| Standalone Q in Connect injector | `aria-session-injector-qconnect` | Amazon Connect after Connect assistant block | Publishes versioned `prod` alias |
| Env-scoped session injector | `aria-banking-session-injector-${ENV}` | Amazon Connect after Connect assistant block | Deployed by `deploy_mcp_gateway.sh` from the same source family |
| Lex fulfillment bridge | `aria-lex-fulfillment` | Amazon Lex V2 | Calls AgentCore `/invocations` over SigV4 HTTPS |
| WebRTC API | `aria-webrtc-api` | Browser/mobile client via Lambda Function URL | `AWS_IAM` auth; no alias/versioning |
| Chat to voice transfer | `aria-banking-chat-to-voice-transfer-${ENV}` | Amazon Connect chat flow | Stores transcript then starts outbound voice contact |
| Voice to chat transfer | `aria-banking-voice-to-chat-transfer-${ENV}` | Amazon Connect voice flow | Creates chat contact and sends SMS/chat link |

### 2.2 Platform characteristics

- Contact-flow Lambdas are stateless at execution time.
- `aria-session-injector-qconnect` and `aria-banking-session-injector-${ENV}` write Q in Connect session data and can also read prior summaries / cross-channel transcripts from DynamoDB.
- `aria-routing-lookup` and `aria-callback-scheduler` both read `aria-routing-config`.
- `aria-banking-chat-to-voice-transfer-${ENV}` and `aria-banking-voice-to-chat-transfer-${ENV}` depend on `aria-transcript-store`.
- `aria-lex-fulfillment` depends on `AGENTCORE_ENDPOINT`, derived from the AgentCore runtime ARN in `scripts/.deploy-state.json`.

### 2.3 Identity, trust, and permissions

- Lambda execution roles are scoped per function family.
- Amazon Connect is the trusted invoker for routing, callback, meeting ID, and session-injector flows.
- Amazon Lex V2 is the trusted invoker for `aria-lex-fulfillment`.
- `aria-webrtc-api` uses a Function URL with `AWS_IAM`; clients assume `aria-webrtc-client-role` and invoke with SigV4.
- Most standalone scripts scope Connect invoke permission to the Connect instance ARN. `deploy_session_injector_qconnect.sh` is broader and uses `--source-account` without `--source-arn`.

### 2.4 MCP tools package

`scripts/lambdas/mcp_tools/` contains:

- `__init__.py`
- `aria_account_handler.py`
- `aria_auth_handler.py`
- `aria_credit_card_handler.py`
- `aria_customer_handler.py`
- `aria_debit_card_handler.py`
- `aria_dtmf_handler.py` *(operationally excluded here)*
- `aria_escalation_handler.py`
- `aria_knowledge_handler.py`
- `aria_mortgage_handler.py`
- `aria_pii_handler.py`
- `aria_products_handler.py`

Operational note: `deploy_mcp_gateway.sh` generates and packages handler code inline for the deployed domain Lambdas; the `mcp_tools/*.py` files are the reference implementations, not the exact packaged artifacts used by that script.

## 3. Prerequisites

Required before deployment:

- ARIA Banking Agent already deployed; `scripts/.deploy-state.json` must contain `agentcore_chat_url` / runtime state for `aria-lex-fulfillment`
- Amazon Connect instance ID confirmed
- Amazon Q in Connect enabled for any session-injector deployment placed after the Connect assistant block
- Python `3.12+`
- AWS CLI v2
- `zip` on `PATH`

Additional script-specific prerequisites:

- `deploy_mcp_gateway.sh`: `python3`, `pip3`, `jq`, and `boto3`
- `deploy_webrtc_api.sh`: valid Connect instance and contact flow IDs, plus Cognito/OIDC trust-policy follow-up for `aria-webrtc-client-role`
- `deploy_callback_lambda.sh`: `deploy_routing_lambda.sh` must already have created `aria-routing-config`

## 4. Deployment Strategy

### 4.1 Recommended sequence

1. **Deploy MCP gateway and env-scoped support Lambdas** with `deploy_mcp_gateway.sh`.
   - Creates `aria-transcript-store`
   - Creates `aria-banking-session-injector-${ENV}`
   - Creates `aria-banking-chat-to-voice-transfer-${ENV}`
   - Creates `aria-banking-voice-to-chat-transfer-${ENV}`
   - Creates `aria-banking-mcp-gateway-${ENV}` and domain Lambdas
2. **Deploy routing** with `deploy_routing_lambda.sh`.
3. **Deploy callback scheduler** with `deploy_callback_lambda.sh`.
   - Immediately update placeholder callback queue IDs with `update-queues` before production use
4. **Deploy WebRTC API** with `deploy_webrtc_api.sh lambda`.
5. **Deploy meeting ID capture** with `deploy_meeting_id_lambda.sh deploy`.
6. **Deploy standalone Q in Connect injector** with `deploy_session_injector_qconnect.sh` when you need the separately named, alias-managed function `aria-session-injector-qconnect`.
7. **Deploy fulfillment bridge** only after AgentCore runtime exists.
   - `aria-lex-fulfillment` is created inside `./scripts/deploy.sh deploy`
8. **Channel transfer Lambdas** are refreshed by rerunning `deploy_mcp_gateway.sh deploy` or `deploy_mcp_gateway.sh update-lambdas`.

### 4.2 Deployment rules

- Standalone routing, callback, meeting-ID, and standalone Q in Connect injector scripts are idempotent and create or update the target Lambda.
- `deploy_mcp_gateway.sh` is also idempotent, but it manages multiple resources and includes hardcoded account/runtime assumptions that must match the target environment.
- Connect permission must be verified after every deployment.
- Contact-flow changes must be coordinated with Connect Operations before production cutover.

## 5. Environment Matrix

| Resource | Deploy path | Region | Required environment/config | Optional environment/config |
| --- | --- | --- | --- | --- |
| `aria-banking-mcp-gateway-${ENV}` | `deploy_mcp_gateway.sh` | Connect region, default `eu-west-2` | `ENV`, `CONNECT_INSTANCE_ID` strongly recommended | `CONNECT_INSTANCE_URL`, `CONNECT_ASSISTANT_ID`, `CONNECT_CONTACT_FLOW_ID`, `CONNECT_QUEUE_ID`, `CHAT_WIDGET_URL`, `SMS_ORIGINATION_NUMBER`, `SOURCE_PHONE_NUMBER`, `CRM_API_ENDPOINT` |
| `aria-routing-lookup` | `deploy_routing_lambda.sh` | Connect region | `ROUTING_TABLE=aria-routing-config` | `CONNECT_INSTANCE_ID` for invoke permission |
| `aria-callback-scheduler` | `deploy_callback_lambda.sh` | Connect region | `ROUTING_TABLE=aria-routing-config` | `CONNECT_INSTANCE_ID` for invoke permission |
| `aria-webrtc-api` | `deploy_webrtc_api.sh lambda` | Connect region | `CONNECT_INSTANCE_ID`, `CONNECT_CONTACT_FLOW_ID` | `ALLOWED_ORIGINS`, `ALLOWED_PRINCIPAL_ARNS`, `LOG_LEVEL`, `AWS_REGION_OVERRIDE`, `DEV_MODE=false` |
| `aria-meeting-id-capture` | `deploy_meeting_id_lambda.sh` | Connect region | none | `CONNECT_INSTANCE_ID` for invoke permission |
| `aria-session-injector-qconnect` | `deploy_session_injector_qconnect.sh` | Connect region | `ASSISTANT_ID` | `INSTANCE_ID`, `MEMORY_TABLE_NAME`, `CRM_API_ENDPOINT` |
| `aria-lex-fulfillment` | `deploy.sh` | AgentCore region | `AGENTCORE_ENDPOINT`, `AWS_REGION` | `CONNECT_INSTANCE_ID` |
| `aria-banking-session-injector-${ENV}` | `deploy_mcp_gateway.sh` | Connect region | `ASSISTANT_ID`, `INSTANCE_ID` | `CRM_API_ENDPOINT`, `TRANSCRIPT_TABLE_NAME=aria-transcript-store` |
| `aria-banking-chat-to-voice-transfer-${ENV}` | `deploy_mcp_gateway.sh` | Connect region | `INSTANCE_ID`, `CONTACT_FLOW_ID`, `QUEUE_ID`, `SOURCE_PHONE_NUMBER`, `DYNAMODB_TABLE=aria-transcript-store` | none |
| `aria-banking-voice-to-chat-transfer-${ENV}` | `deploy_mcp_gateway.sh` | Connect region | `INSTANCE_ID`, `CONTACT_FLOW_ID`, `CHAT_WIDGET_URL`, `SMS_ORIGINATION_NUMBER`, `DYNAMODB_TABLE=aria-transcript-store` | `MOBILE_APP_SCHEME` is not set by the script |

## 6. Change Management

| Change type | Examples | Control |
| --- | --- | --- |
| Standard | Zip + `update-function-code` for an existing standalone Lambda; rerun `deploy_mcp_gateway.sh update-lambdas` | Platform Engineering approval |
| Normal | New Lambda, IAM policy change, MCP gateway target/schema change, Function URL trust change, DynamoDB schema change | Platform Engineering + service owner |
| Emergency | Restore Connect invoke permission, revert broken alias, update stale `AGENTCORE_ENDPOINT` after AgentCore redeploy | Incident-led change control |

Additional controls:

- Contact-flow edits require Connect Operations coordination.
- Alias-managed Lambdas (`aria-routing-lookup`, `aria-callback-scheduler`, `aria-meeting-id-capture`, `aria-session-injector-qconnect`) should be invoked via `:prod` only.
- `.deploy-state.json` and the per-script state files are operational artifacts and must not be removed during in-place updates.

## 7. Risk Register

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Missing Connect invoke permission | Contact flow cannot invoke Lambda; failures appear as broken branches or silent drop-offs | Validate `aws lambda get-policy` after every deploy and reapply the correct permission statement |
| Stale `AGENTCORE_ENDPOINT` | `aria-lex-fulfillment` returns 5xx after AgentCore redeploy | Pull fresh value from `scripts/.deploy-state.json` and update Lambda configuration |
| Q in Connect disabled or injector placed before Connect assistant block | Session enrichment fails; `{{$.Custom.*}}` variables remain empty | Enable Q in Connect, place injector after Connect assistant, verify `ASSISTANT_ID` |
| Callback queue placeholders left in place | Callback flow falls back to main queue or routes incorrectly | Run `./scripts/deploy_callback_lambda.sh update-queues` before production use |
| `aria-routing-config` missing | Routing and callback Lambdas fail | Always deploy routing before callback and verify the table exists |
| `aria-transcript-store` missing | Chat/voice transfer and session-injector transcript lookup fail | Deploy MCP gateway stack first or create the table separately |
| WebRTC client-role trust policy still contains placeholder identity-pool ID | Clients cannot invoke `aria-webrtc-api` Function URL | Replace `REPLACE_WITH_IDENTITY_POOL_ID` and re-run the script |
| Hardcoded account/runtime in `deploy_mcp_gateway.sh` | MCP gateway deployment targets wrong account/runtime | Validate script assumptions before production use |
| Standalone Q in Connect injector lacks scoped `source-arn` | Broader-than-necessary Connect invoke permission | Compensate with stricter IAM/process controls and audit regularly |
| Meeting ID value collision or invalid capture | Rare IVR error or wrong lookup path | Validate 6-digit format and branch on `$.External.success` |

## 8. Rollback Strategy

- For alias-managed standalone Lambdas, roll back by repointing `prod` to the previous published version with `aws lambda update-alias`.
- `aria-webrtc-api`, `aria-lex-fulfillment`, `aria-session-injector`, and MCP gateway-managed Lambdas do not use aliases; roll back by redeploying the last known-good package or rerunning the relevant deploy script from the prior revision.
- Roll back contact-flow changes by restoring the prior flow version/import in Amazon Connect.
- If callback routing is wrong, revert the callback queue fields in `aria-routing-config` to the prior known-good values.

## 9. Communication Plan

| Stage | Audience | Communication |
| --- | --- | --- |
| Pre-change | Platform Engineering, Connect Operations | Window, scope, expected contact-flow impact, rollback owner |
| In progress | On-call engineers, service owner | Status at each major deployment step |
| Validation complete | Platform Engineering, Connect Operations | Confirm Lambda health, flow validation, and remaining actions |
| Incident / rollback | Incident manager, support teams | Symptom, mitigation, ETA, rollback state |

Any Lambda that touches active contact flows requires prior notification to Connect Operations.

## 10. Success Criteria

The platform change is successful only when all applicable checks pass:

- Each deployed Lambda returns `Active` from `aws lambda get-function`
- `aria-banking-mcp-gateway-${ENV}` exists and its targets are present
- Amazon Connect or Lex can invoke the correct function/alias
- `aria-session-injector-qconnect` or `aria-banking-session-injector-${ENV}` populates session/contact attributes as expected
- `aria-lex-fulfillment` returns a valid Lex response against a realistic event
- Channel transfer flows create the downstream contact successfully
- WebRTC health and signed start-contact requests succeed

## 11. Post-Deployment Validation

Perform all relevant checks before handoff:

- Invoke each standalone Lambda with a realistic payload
- Verify Connect or Lex resource policies with `aws lambda get-policy`
- Confirm `aria-routing-config` and `aria-transcript-store` exist and contain expected records
- Review CloudWatch Logs for each updated function
- Validate end-to-end routing, callback, meeting-ID, and transfer paths in Connect
- Re-add or refresh the MCP gateway integration in Connect AI Agent Designer after gateway target changes

## 12. Contacts and Escalation

| Level | Role | Responsibility |
| --- | --- | --- |
| L1 | Platform Engineering on-call | Deployment execution, Lambda/IAM triage, rollback |
| L2 | Connect Operations | Contact-flow validation, queue routing, callback behaviour |
| L3 | AWS Platform Owner | IAM, Function URL, DynamoDB, AgentCore gateway, regional issues |
| L4 | AI Platform / ARIA owner | AgentCore runtime, Lex integration, MCP gateway behaviour |

Escalate immediately for repeated Connect invoke failures, broken callback routing, WebRTC client-auth failures, or stale AgentCore runtime configuration.

## 13. Approvals

Production rollout requires approval from:

- Platform Engineering lead
- Service owner for the Connect Lambda Platform
- Connect Operations representative
- Security review when IAM scope, Function URL access, or Q in Connect permissions change
