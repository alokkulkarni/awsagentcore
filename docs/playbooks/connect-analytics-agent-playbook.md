# Connect Analytics Agent Playbook

## Document Control

| Field | Value |
| --- | --- |
| Document ID | PLY-CAA-001 |
| Version | 1.0 |
| Owner | Platform Engineering |
| Effective Date | 2026-05-25 |
| Component | Connect Analytics Agent |

## 1. Purpose

This playbook defines the standard deployment and operational approach for the Amazon Connect Analytics Agent component.

The component provides:
- 9 Amazon Connect analytics Lambda tools: `realtime-metrics`, `historical-metrics`, `agent-states`, `search-contacts`, `contact-detail`, `transcript`, `keyword-search`, `recording-url`, and `contact-flow-events`
- A Strands-based agent exposed through AgentCore Gateway, with direct Lambda fallback when Gateway is unavailable
- A React 18 + Vite dashboard delivered through CloudFront for supervisors and operators

## 2. Architecture

### Logical flow
1. Amazon Connect analytics requests are served by 9 Lambda tool functions.
2. AgentCore Gateway registers each tool schema from `infrastructure/gateway/tool-schemas.json`.
3. The Strands agent Lambda calls tools through AgentCore Gateway when available.
4. If Gateway is unavailable, the agent uses direct Lambda invocation via `DIRECT_TOOL_LAMBDAS`.
5. API Gateway exposes `/api/query`, `/api/health`, and `/api/metrics`.
6. Cognito secures the cloud frontend path.
7. The React frontend is hosted in S3 and delivered by CloudFront.
8. Local development uses Docker with `MOCK_MODE=true` by default and an in-process FastAPI agent.

### Deployment topology
- Lambda tools × 9
- AgentCore Gateway
- Strands agent Lambda
- API Gateway + Cognito
- S3 website bucket + CloudFront
- React 18 + Vite frontend
- Optional EventBridge + SQS for live bot/contact events

## 3. Prerequisites

Required before cloud deployment:
- AWS CLI v2 with valid credentials
- Python 3.12+
- Node.js 20+
- Docker
- `jq` (required because `deploy.sh` writes and updates `.deploy-state.json`)
- Amazon Connect instance ID
- Bedrock access for Claude in the target AWS Region

Recommended access:
- IAM permissions for Lambda, IAM, API Gateway, Cognito, S3, CloudFront, EventBridge, SQS, and CloudWatch Logs
- Amazon Connect analytics and Contact Lens permissions for the tool Lambdas

## 4. Deployment Strategy

Standard deployment sequence executed by `connect-analytics-agent/deploy.sh`:
1. Create IAM roles
2. Create and attach IAM policies
3. Package and deploy the 9 Lambda tool functions
4. Create AgentCore Gateway and register tool schemas
5. Deploy the Strands agent Lambda
6. Deploy API Gateway resources and methods
7. Create Cognito user pool and frontend client
8. Create the S3 frontend bucket
9. Build the React frontend and sync assets
10. Create or update the CloudFront distribution
11. Optionally enable EventBridge + SQS with `./deploy.sh setup-eventbridge`

Operational notes:
- Expected cloud deployment duration: 10-20 minutes
- Local Docker mode is the preferred path for development and UI validation
- Gateway registration is best-effort; direct Lambda mode is the supported fallback path

## 5. Environment Matrix

| Environment | Primary Use | Runtime Mode | Required Variables | Notes |
| --- | --- | --- | --- | --- |
| Local | Developer workflow | Docker + FastAPI + mounted tools | `MOCK_MODE=true` by default; `AWS_REGION`, `CONNECT_INSTANCE_ID` only for live local mode | Frontend on `http://localhost:5274`, API on `http://localhost:8100` |
| Staging | Pre-production validation | Full AWS deployment | `AWS_REGION`, `CONNECT_INSTANCE_ID`, `STACK_SUFFIX`, optional `BEDROCK_MODEL_ID` | Use isolated Connect data and Cognito users |
| Production | Business operations | Full AWS deployment | `AWS_REGION`, `CONNECT_INSTANCE_ID`, `STACK_SUFFIX`, optional `BEDROCK_MODEL_ID` | Requires change approval and rollback readiness |

### Standard environment variables

| Variable | Requirement | Default |
| --- | --- | --- |
| `AWS_REGION` | Required for cloud; recommended for local | AWS CLI configured region, then `us-east-1` |
| `CONNECT_INSTANCE_ID` | Required for cloud | none |
| `BEDROCK_MODEL_ID` | Optional | `us.anthropic.claude-sonnet-4-5` |
| `STACK_SUFFIX` | Recommended | current date in `YYYYMMDD` |
| `MOCK_MODE` | Local only | `true` |

## 6. Change Management

- Tool schema changes in `infrastructure/gateway/tool-schemas.json` require AgentCore Gateway re-registration.
- Lambda code updates can be applied per function without a full stack teardown.
- Frontend-only changes require a rebuild, S3 sync, and CloudFront invalidation.
- Changes to Cognito, API Gateway, or CloudFront must follow standard environment promotion controls.
- `.deploy-state.json` is an operational state artifact and must be preserved during in-place updates.

## 7. Risk Register

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Amazon Connect instance inaccessible | Tool Lambdas return empty or failed responses | Validate `CONNECT_INSTANCE_ID`, IAM, and Connect permissions before deployment |
| Tool Lambda timeout due to Connect API latency | Agent answers fail or are delayed | Monitor CloudWatch duration/errors; retry with narrower filters or higher service-side quotas |
| AgentCore Gateway unavailable | Agent loses Gateway path | Use built-in direct Lambda fallback and verify `DIRECT_TOOL_LAMBDAS` population |
| Cognito auth failure | Dashboard login blocked | Validate user pool, app client, and frontend environment values after deployment |
| `search-contacts` pagination issues | Incomplete contact result sets | Validate `next_token` handling and cap result sizes during smoke testing |
| CloudFront propagation delay | Frontend appears stale | Wait for distribution deployment and invalidate cache after frontend changes |

## 8. Rollback Strategy

- Roll back individual Lambda tools by updating function code to the last known-good package or published version.
- Roll back the agent Lambda independently from the tool Lambdas.
- Revert frontend artifacts by re-syncing the prior build to S3 and issuing a CloudFront invalidation.
- Preserve and, if needed, restore `.deploy-state.json` before risky changes.
- If Gateway registration fails after a schema change, operate temporarily in direct Lambda mode and redeploy the gateway registration step.

## 9. Communication Plan

| Stage | Audience | Communication |
| --- | --- | --- |
| Pre-change | Platform Engineering, Contact Center Operations | Deployment window, expected impact, rollback plan |
| In-progress | On-call engineers, stakeholders | Status every major phase: tools, gateway, agent, API, frontend |
| Validation complete | Platform Engineering, product owner | Confirmation of 9-tool health, dashboard reachability, sample NLQ success |
| Incident or rollback | Incident commander, support teams | Failure symptom, mitigation, ETA, rollback status |

## 10. Success Criteria

A deployment is successful only when all of the following are true:
- All 9 deployed tool Lambdas exist and are invocable
- AgentCore Gateway is active or the direct Lambda fallback path is confirmed
- The Strands agent Lambda answers a natural-language Amazon Connect question successfully
- API Gateway health and query endpoints return success
- The React dashboard loads through CloudFront
- The dashboard returns live or mock Amazon Connect data as expected for the target environment

## 11. Post-Deployment Validation

Perform the following before handoff:
- Confirm `.deploy-state.json` contains Lambda names, API URL, Cognito IDs, and CloudFront URL
- Invoke `realtime-metrics` and `search-contacts` directly
- Invoke `connect-analytics-agent-${STACK_SUFFIX}` with a sample chat request
- Verify `GET /api/health` and `GET /api/metrics`
- Open the CloudFront URL and submit a natural-language query
- Review CloudWatch logs for the agent Lambda and at least one tool Lambda
- If enabled, confirm EventBridge and SQS are delivering bot/contact events

## 12. Contacts and Escalation

| Level | Role | Responsibility |
| --- | --- | --- |
| L1 | Platform Engineering on-call | Deployment execution, initial triage, rollback |
| L2 | Contact Center Operations | Validate Connect data quality and business behavior |
| L3 | AWS Platform Owner | IAM, networking, CloudFront, API Gateway, Cognito escalation |
| L4 | Security / Identity | Cognito, token, and access-control escalation |

Escalate immediately for production login failure, repeated Lambda timeouts, AgentCore Gateway registration failure, or widespread Connect API access errors.

## 13. Approvals

The following approvals are required for production rollout:
- Platform Engineering lead
- Service owner / product owner for Connect Analytics Agent
- Contact Center Operations representative
- Security review when Cognito, IAM, or public-edge behavior changes
