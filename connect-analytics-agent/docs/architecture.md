# Architecture

## 1. Architecture overview

Amazon Connect Analytics Agent is a layered system that exposes Amazon Connect operational analytics through MCP-compatible Lambda tools and a Strands orchestration layer.

```text
┌───────────────────────────────────────────────────────────────────────────┐
│                            User Browser                                  │
│  React 18 SPA: Chat, Dashboard, Agent States, Contact Search, Transcript │
└───────────────────────────────┬───────────────────────────────────────────┘
                                │ HTTPS
                                ▼
                    ┌───────────────────────────────┐
                    │ CloudFront + S3 Static Site  │
                    │ or Vite Docker Dev Server    │
                    └──────────────┬────────────────┘
                                   │ /api
                                   ▼
                    ┌───────────────────────────────┐
                    │ API Gateway / FastAPI Local   │
                    │ CORS + JSON + SSE streaming   │
                    └──────────────┬────────────────┘
                                   │
                                   ▼
                    ┌───────────────────────────────┐
                    │ Strands Agent Runtime         │
                    │ Bedrock Claude model          │
                    │ MCP tool selection            │
                    └──────────────┬────────────────┘
                        AgentCore  │  Direct fallback
                        Gateway    │  invocation mode
                                   ▼
                  ┌─────────────────────────────────────┐
                  │ 8 Lambda Analytics Tool Functions   │
                  │ Shared Connect utility module       │
                  └─────────────────┬───────────────────┘
                                    │ boto3
                                    ▼
          ┌─────────────────────────────────────────────────────────────┐
          │ Amazon Connect APIs: metrics, users, contacts, transcripts │
          │ Contact Lens analysis, S3 recordings, CloudWatch Logs      │
          └─────────────────────────────────────────────────────────────┘
```

## 2. Data sources and APIs used

The project uses live Amazon Connect APIs through `boto3`:

- `get_current_metric_data` for queue and routing performance snapshots
- `get_metric_data_v2` for historical aggregates
- `get_current_user_data` and `describe_user` for real-time agent state enrichment
- `search_contacts` for CTR discovery and transcript keyword search
- `describe_contact` and `get_contact_attributes` for detailed contact inspection
- `list_contact_analysis_segments` for Contact Lens transcript retrieval
- `s3.generate_presigned_url` for secure recording playback URLs

All tools accept AgentCore-style parameter lists and normalize them through `tools/shared/connect_utils.py`.

## 3. AgentCore Gateway integration details

The intended deployment path uses `aws bedrock-agentcore-control create-gateway` to provision an AgentCore Gateway, then registers all 8 Lambda-backed tools using `infrastructure/gateway/tool-schemas.json`.

Gateway integration flow:

1. `deploy.sh` creates the gateway IAM role and policy.
2. Tool Lambda ARNs are created or updated.
3. Tool schemas are read from JSON and attached to gateway targets.
4. The gateway endpoint is injected into the Strands agent Lambda via environment variables.
5. The Strands MCP client connects to the gateway SSE endpoint using signed AWS headers.

If the installed AWS CLI lacks `bedrock-agentcore-control`, the deployment script switches to a documented fallback mode where the agent invokes Lambda tool functions directly. This keeps the project deployable even in environments with older CLI support.

## 4. Strands agent design

The Strands layer lives under `agent/` and provides:

- Sync and async agent execution helpers
- MCP gateway connectivity through SSE transport
- Bedrock model initialization with region awareness
- Direct Lambda invocation fallback when no gateway endpoint exists
- A domain-specific system prompt focused on contact-center supervision tasks

Tool selection guidance is embedded in the system prompt. The prompt instructs the model to:

- prefer real-time tools for “right now” questions
- prefer historical metrics for busiest agent and trend analysis
- explain Contact Lens prerequisites clearly
- format durations and operational summaries for supervisors

## 5. Frontend architecture

The frontend is a React 18 SPA built with Vite and Tailwind CSS.

Core layers:

- `src/services/api.js`: shared HTTP client and auth behavior
- `src/hooks/useAgentChat.js`: session-aware chat state
- `src/components/ChatInterface.jsx`: conversational UI and markdown rendering
- `src/components/MetricsDashboard.jsx`: summary cards and AI-assisted drill-down
- `src/components/AgentStateTable.jsx`: sortable current-state view with CSV export
- `src/components/ContactSearch.jsx`: search workflow for CTRs and transcript pivots
- `src/components/TranscriptViewer.jsx`: transcript reader with recording access

The SPA is intentionally designed to work in:

- local mode, where relative `/api` requests are proxied to FastAPI
- cloud mode, where CloudFront serves the static app and the app uses the deployed API URL

## 6. Security model

Security controls are split by runtime boundary:

- **Tool Lambda role**: minimum Connect + S3 + CloudWatch access for analytics functions
- **Agent Lambda role**: Bedrock invoke, AgentCore invoke, optional Lambda fallback, CloudWatch logs
- **AgentCore gateway role**: trusted by `bedrock-agentcore.amazonaws.com`
- **Frontend auth**: Cognito user pool and app client for cloud mode
- **Transport security**: HTTPS via CloudFront and API Gateway; local mode is confined to localhost

The sample IAM policy uses `Resource: "*"` for Connect and S3 simplicity, but comments note where operators should scope access to specific Connect instances, Lambda ARNs, and recording buckets.

## 7. Local development setup

Local development uses Docker Compose with two services:

- `agent`: FastAPI app on port 8000
- `frontend`: Vite dev server on port 5173

Default local behavior sets `MOCK_MODE=true`, which returns realistic canned responses and avoids AWS calls. Developers can switch to live local mode by setting `MOCK_MODE=false`, `CONNECT_INSTANCE_ID`, and AWS credentials in the shell or `.env`.

## 8. Deployment pipeline

`deploy.sh` is intentionally monolithic so operators only need one command surface.

Deployment stages:

1. validate prerequisites
2. create IAM roles and policies
3. package and deploy tool Lambdas
4. create AgentCore gateway or fallback configuration
5. deploy Strands agent Lambda
6. create API Gateway and CORS wiring
7. provision Cognito user pool and client
8. build frontend and publish to S3 + CloudFront
9. write `.deploy-state.json`
10. print operational summary

Teardown reverses the order and tolerates partial state to simplify recovery from failed deployments.

## 9. Extension guide

To add a new analytics tool:

1. Create `tools/<new_tool>/handler.py` and `requirements.txt`.
2. Reuse `tools/shared/connect_utils.py` for event parsing and response formatting.
3. Add a schema entry to `infrastructure/gateway/tool-schemas.json`.
4. Extend `TOOL_NAMES` and packaging logic in `deploy.sh`.
5. Update the system prompt in `agent/agent_core.py` if the tool adds new capabilities.
6. Optionally add frontend affordances or suggested chat prompts.

## 10. Operational notes

- All timestamps are handled in ISO 8601 and rendered in the browser’s local timezone.
- Contact Lens and recordings can be absent per contact; tools return clear, user-friendly messages.
- The local server exposes `/health` and `/metrics` for lightweight verification and integration testing.
