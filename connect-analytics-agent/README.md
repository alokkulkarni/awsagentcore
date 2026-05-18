# Amazon Connect Analytics Agent

Amazon Connect Analytics Agent is a full-stack reference project that combines Amazon Connect analytics APIs, AWS AgentCore Gateway, a Strands-based Bedrock agent, and a React 18 dashboard. It supports both local mock development and cloud deployment from a single `deploy.sh` entrypoint.

## Project overview

This project includes:

- 9 AWS Lambda analytics tools for Amazon Connect
- An AWS Strands agent that calls those tools through AgentCore Gateway (with direct Lambda fallback)
- A React 18 + Vite frontend for chat, dashboards, and transcript exploration
- Docker-based local development with realistic mock responses
- A single deployment script for deploy, teardown, and local operations

## Prerequisites

| Requirement | Version / Notes |
| --- | --- |
| AWS CLI | v2 with configured credentials |
| Docker | Docker Desktop or compatible engine |
| Node.js | 20+ |
| Python | 3.12+ |
| jq | Required by `deploy.sh` state tracking |
| Amazon Connect | Existing instance ID |
| Bedrock access | Claude model access in target region |

## Quick start: local development

```bash
git clone <your-repo-url>
cd connect-analytics-agent
./deploy.sh local
```

Then open `http://localhost:5274`.

Local mode defaults to `MOCK_MODE=true`, so no live AWS resources are required.

## Cloud deployment

1. Copy `.env.example` values into your shell or environment.
2. Export the minimum required variables:

```bash
export AWS_REGION=us-east-1
export CONNECT_INSTANCE_ID=your-connect-instance-id
export STACK_SUFFIX=prod
```

3. Deploy everything:

```bash
./deploy.sh deploy
```

The script provisions IAM roles and policies, Lambda functions, AgentCore Gateway or direct fallback configuration, API Gateway, Cognito, S3, and CloudFront.

## Architecture overview

```text
┌─────────────────────┐     HTTPS      ┌──────────────────────────┐
│   React Frontend    │ ─────────────▶ │ API Gateway + Cognito    │
│ CloudFront / Docker │                └────────────┬─────────────┘
└──────────┬──────────┘                             │
           │                                        ▼
           │                                ┌──────────────┐
           │                                │ Agent Lambda │
           │                                │   Strands    │
           │                                └──────┬───────┘
           │                                       │
           │                         AgentCore MCP │  Direct fallback
           │                                       ▼
           │                              ┌─────────────────┐
           │                              │ AgentCore GW    │
           │                              └──────┬──────────┘
           │                                     │
           ▼                                     ▼
┌─────────────────────┐                ┌───────────────────────┐
│ Local FastAPI Agent │                │ Lambda Connect Tools  │
│   (mock or live)    │                └──────────┬────────────┘
└─────────────────────┘                           │
                                                  ▼
                                        ┌───────────────────────┐
                                        │ Amazon Connect APIs   │
                                        │ Contact Lens + S3     │
                                        └───────────────────────┘
```

See `docs/architecture.md` for detailed design notes.

## Example prompts

- How many agents are busy right now?
- Who is my busiest agent today?
- Show me abandoned calls from the last hour.
- Find calls mentioning “escalation”.
- What is the average handle time for Technical Support today?
- Show agents currently in after contact work.
- Get transcript for contact `<contact-id>`.
- Generate a recording link for the latest support call.

## Teardown

To remove cloud resources created by the deploy script:

```bash
./deploy.sh teardown
```

To stop local containers:

```bash
./deploy.sh local-stop
```

## Troubleshooting

- **`CONNECT_INSTANCE_ID is required`**: export `CONNECT_INSTANCE_ID` before cloud deploy.
- **`bedrock-agentcore-control not available`**: the script automatically falls back to direct Lambda invocation mode and records that in state.
- **Frontend cannot reach backend locally**: confirm Docker is running and `http://localhost:8100/health` returns healthy.
- **Contact Lens transcript errors**: ensure Contact Lens is enabled for the Connect instance and the queried contact has analysis data.
- **CloudFront not updated yet**: initial distributions can take several minutes to deploy.
- **Bedrock access denied**: request model access for the configured Claude model in the deployment region.

## Environment variables

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `AWS_REGION` | Yes (cloud) | `us-east-1` | Deployment region, with AWS CLI config fallback |
| `CONNECT_INSTANCE_ID` | Yes (cloud/live local) | none | Amazon Connect instance ID |
| `BEDROCK_MODEL_ID` | No | `us.anthropic.claude-sonnet-4-5` | Bedrock model for the Strands agent |
| `STACK_SUFFIX` | No | current date | Unique suffix for resource naming |
| `MOCK_MODE` | No | `true` locally | Enables local mocked responses |
| `AGENTCORE_GATEWAY_ENDPOINT` | No | empty | Injected after gateway creation |
| `AWS_ACCESS_KEY_ID` | No | empty | Optional for live local Docker |
| `AWS_SECRET_ACCESS_KEY` | No | empty | Optional for live local Docker |
| `AWS_SESSION_TOKEN` | No | empty | Optional for live local Docker |

## Repository structure

The project follows the exact structure requested in the task prompt, including dedicated directories for tools, agent runtime, frontend, infrastructure definitions, Docker assets, and documentation.
