# ARIA Evaluator TS Runbook

| Field | Value |
|---|---|
| **Document ID** | RNB-EVAL-001 |
| **Companion Playbook** | PLY-EVAL-001 |
| **Version** | 1.0 |
| **Status** | Active |
| **Owner** | Platform Engineering |
| **Last Updated** | 2026-05-25 |
| **Classification** | Internal |

> Execute steps in order. Do not skip verification checkpoints.

---

## Table of Contents

1. [Pre-deployment checklist](#1-pre-deployment-checklist)
2. [Local development](#2-local-development)
3. [Build and lint](#3-build-and-lint)
4. [Docker build](#4-docker-build)
5. [ECR push](#5-ecr-push)
6. [CloudFormation deploy](#6-cloudformation-deploy)
7. [Verify ECS task](#7-verify-ecs-task)
8. [Verify CloudFront](#8-verify-cloudfront)
9. [Run an evaluation](#9-run-an-evaluation)
10. [Scale ECS](#10-scale-ecs)
11. [Update deployment (new image)](#11-update-deployment-new-image)
12. [View ECS logs](#12-view-ecs-logs)
13. [Teardown](#13-teardown)
14. [Troubleshooting](#14-troubleshooting)

---

## 1. Pre-deployment checklist

### 1.1 Environment validation

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/aria-evaluator-ts

node --version
npm --version
docker --version
aws --version
aws sts get-caller-identity
```

**Expected:**
- Node.js 20+
- AWS CLI authenticated
- Docker engine available

### 1.2 Service and access validation

```bash
# Confirm Bedrock model access in your target region
aws bedrock list-foundation-models \
  --region eu-west-2 \
  --query "modelSummaries[?modelLifecycle.status=='ACTIVE'].modelId" \
  --output text

# Confirm or create the ECR repository later in Step 5
aws ecr describe-repositories \
  --repository-names aria-evaluator-ts \
  --region eu-west-2
```

### 1.3 Deployment prerequisites

- [ ] Docker available locally
- [ ] Node.js 20+ installed
- [ ] AWS credentials valid
- [ ] Bedrock model access confirmed
- [ ] Target ECR repository exists or can be created
- [ ] CloudFormation deployment permissions include `CAPABILITY_NAMED_IAM`
- [ ] Provider-specific runtime variables prepared (`CONNECT_*`, `LEX_*`, `AZURE_*`, `STRANDS_*`, `COPILOT_*`, or `CUSTOM_*`)

---

## 2. Local development

### 2.1 Install dependencies

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/aria-evaluator-ts
npm install
```

### 2.2 Start development mode

```bash
npm run dev
```

This launches:
- API dev server from `src/api/server.ts`
- Vite UI after `http://localhost:3001/health` becomes available

### 2.3 Access URLs

- UI dev server: `http://localhost:5173`
- API health check: `http://localhost:3001/health`

**✓ Verify**

```bash
curl -i http://localhost:3001/health
```

Expected: HTTP 200 with `{ "ok": true, ... }`

> If browser binaries are missing during local voice/chat execution, install them with `npx playwright install` before retrying a run.

---

## 3. Build and lint

### 3.1 Type-check / lint gate

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/aria-evaluator-ts
npm run lint
```

### 3.2 Production build

```bash
npm run build
```

### 3.3 Confirm build output

```bash
ls -la dist
ls -la dist/ui
```

**✓ Verify**
- `dist/api/` exists
- `dist/ui/` exists
- build exits with code 0

---

## 4. Docker build

### 4.1 Build image

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/aria-evaluator-ts
docker build -t aria-evaluator-ts .
```

### 4.2 Run container locally

The image exposes port `3001` by default.

```bash
docker run --rm -p 3001:3001 aria-evaluator-ts
```

If you require port 3000 externally, override the app port explicitly:

```bash
docker run --rm -e API_PORT=3000 -p 3000:3000 aria-evaluator-ts
```

**✓ Verify**

```bash
curl -i http://localhost:3001/health
```

Expected: HTTP 200

---

## 5. ECR push

### 5.1 Create repository if needed

```bash
export AWS_REGION=eu-west-2
aws ecr create-repository \
  --repository-name aria-evaluator-ts \
  --region "$AWS_REGION" \
  || true
```

### 5.2 Authenticate Docker to ECR

```bash
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export ECR_URI="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/aria-evaluator-ts"

aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"
```

### 5.3 Tag and push image

```bash
export IMAGE_TAG=$(git rev-parse --short HEAD)
docker tag aria-evaluator-ts:latest "$ECR_URI:$IMAGE_TAG"
docker push "$ECR_URI:$IMAGE_TAG"
```

**✓ Verify**

```bash
aws ecr describe-images \
  --repository-name aria-evaluator-ts \
  --region "$AWS_REGION" \
  --query "imageDetails[].imageTags" \
  --output json
```

---

## 6. CloudFormation deploy

### 6.1 Deploy the low-cost ECS + CloudFront stack

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/aria-evaluator-ts

export STACK_NAME=aria-evaluator-ts
export APP_IMAGE_URI="$ECR_URI:$IMAGE_TAG"

aws cloudformation deploy \
  --stack-name "$STACK_NAME" \
  --template-file infra/cloudformation/ecs-cloudfront-lowcost.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    AppName=aria-evaluator-ts \
    AppImageUri="$APP_IMAGE_URI" \
    DesiredCount=1
```

### 6.2 Optional overrides

Add overrides if required for performance or environment control:
- `Cpu=512`
- `Memory=1024`
- `ContainerPort=3001`
- `S3StatePrefix=aria-evaluator`
- `S3SyncIntervalSeconds=30`

**✓ Verify**

```bash
aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query "Stacks[0].StackStatus" \
  --output text
```

Expected: `CREATE_COMPLETE` or `UPDATE_COMPLETE`

---

## 7. Verify ECS task

### 7.1 Inspect service counts

```bash
aws ecs describe-services \
  --cluster aria-evaluator-ts-cluster \
  --services aria-evaluator-ts-svc \
  --query "services[0].[desiredCount,runningCount,pendingCount,status]" \
  --output table
```

### 7.2 Inspect task health/events

```bash
aws ecs describe-services \
  --cluster aria-evaluator-ts-cluster \
  --services aria-evaluator-ts-svc \
  --query "services[0].events[0:10].[createdAt,message]" \
  --output table
```

**✓ Verify**
- `desiredCount` equals `runningCount`
- no repeated task replacement or health-check failures

---

## 8. Verify CloudFront

### 8.1 Get output values

```bash
aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs[].[OutputKey,OutputValue]" \
  --output table
```

Capture:
- `CloudFrontUrl`
- `CloudFrontDistributionId`

### 8.2 Check endpoint health

```bash
export CLOUDFRONT_URL=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs[?OutputKey=='CloudFrontUrl'].OutputValue" \
  --output text)

curl -i "$CLOUDFRONT_URL/health"
curl -I "$CLOUDFRONT_URL/"
```

**✓ Verify**
- `/health` returns HTTP 200
- `/` returns HTTP 200 or expected redirect/HTML response

---

## 9. Run an evaluation

### 9.1 Through the UI

1. Open the CloudFront URL.
2. Go to **Scenarios**.
3. Select a scenario file or scenario reference.
4. Choose channel (`chat` or `voice`) and provider.
5. Start the run.
6. Watch progress on the **Runs** page.
7. Open **Reports** and **Transcripts** after completion.

### 9.2 Through the API

```bash
curl -X POST "$CLOUDFRONT_URL/api/runs" \
  -H 'Content-Type: application/json' \
  -d '{
    "scenarioFile": "sample.yaml",
    "channel": "chat",
    "provider": "connect"
  }'
```

### 9.3 Observe run state

```bash
curl "$CLOUDFRONT_URL/api/runs"
```

**✓ Verify**
- run status transitions from `pending` -> `running` -> `completed`
- report entries appear in `/api/reports`
- transcript entries appear in `/api/transcripts`

---

## 10. Scale ECS

The reference stack is intentionally low-cost and defaults to one task. Scale only when needed.

```bash
aws ecs update-service \
  --cluster aria-evaluator-ts-cluster \
  --service aria-evaluator-ts-svc \
  --desired-count 1
```

To pause the always-on service for cost control:

```bash
aws ecs update-service \
  --cluster aria-evaluator-ts-cluster \
  --service aria-evaluator-ts-svc \
  --desired-count 0
```

**✓ Verify**

```bash
aws ecs describe-services \
  --cluster aria-evaluator-ts-cluster \
  --services aria-evaluator-ts-svc \
  --query "services[0].[desiredCount,runningCount]" \
  --output table
```

---

## 11. Update deployment (new image)

### 11.1 Standard refresh flow

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/aria-evaluator-ts
npm run lint
npm run build
docker build -t aria-evaluator-ts .
docker tag aria-evaluator-ts:latest "$ECR_URI:$IMAGE_TAG"
docker push "$ECR_URI:$IMAGE_TAG"
```

### 11.2 Force ECS redeployment

If the task definition already references the target image tag and you need a restart:

```bash
aws ecs update-service \
  --cluster aria-evaluator-ts-cluster \
  --service aria-evaluator-ts-svc \
  --force-new-deployment
```

If you changed the image tag used by CloudFormation, redeploy the stack with the new `AppImageUri`.

**✓ Verify**
- new task starts successfully
- old task drains cleanly
- post-deployment checks in Sections 7-9 pass

---

## 12. View ECS logs

```bash
aws logs tail /ecs/aria-evaluator-ts --follow --since 30m
```

Look for:
- `Applying database schema`
- `Starting API server on port`
- Prisma errors
- provider connection errors
- run failure messages emitted by the run router

---

## 13. Teardown

Delete the stack only when the environment is no longer required.

```bash
aws cloudformation delete-stack --stack-name "$STACK_NAME"
```

### 13.1 Track deletion

```bash
aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query "Stacks[0].StackStatus" \
  --output text
```

**Note:** the template sets delete policies on created infrastructure, including the ECR repository and state bucket. Confirm no required reports, transcripts, or settings remain before teardown.

---

## 14. Troubleshooting

### 14.1 ECS task health check failing

**Symptoms**
- task repeatedly replaced
- ALB target unhealthy
- CloudFront `/health` fails

**Checks**
```bash
aws ecs describe-services \
  --cluster aria-evaluator-ts-cluster \
  --services aria-evaluator-ts-svc \
  --query "services[0].events[0:10].[createdAt,message]" \
  --output table

aws logs tail /ecs/aria-evaluator-ts --since 30m
```

**Actions**
- confirm container port and `API_PORT` are aligned (`3001` by default)
- confirm `infra/docker/ecs-entrypoint.sh` completed and started `node dist/api/server.js`
- confirm `/health` is reachable locally in the container image before redeploying

### 14.2 Playwright timeouts or slow runs

**Symptoms**
- runs remain `running` for too long
- provider interaction fails under voice/chat evaluation

**Actions**
- increase evaluation timeout environment values such as `EVAL_RESPONSE_TIMEOUT_SECONDS`, `VOICE_INITIAL_GREETING_TIMEOUT_MS`, or related voice timing keys
- confirm provider credentials and endpoint accessibility
- test the scenario locally before promoting the image

### 14.3 Database migration / Prisma errors

**Symptoms**
- startup fails during schema application
- runtime errors reference missing tables or Prisma client issues

**Actions**
```bash
npm run db:generate
npm run db:push
```
- confirm `DATABASE_URL` points to the expected SQLite path
- verify the ECS state directory is writable
- review schema changes against existing data before redeploying

### 14.4 CloudFront serving stale content

**Symptoms**
- old UI still visible after deploy
- asset references mismatch newly deployed build

**Action**
```bash
export DISTRIBUTION_ID=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs[?OutputKey=='CloudFrontDistributionId'].OutputValue" \
  --output text)

aws cloudfront create-invalidation \
  --distribution-id "$DISTRIBUTION_ID" \
  --paths '/*'
```

### 14.5 Image pull failure

**Actions**
- confirm the image tag exists in ECR
- confirm the stack/task definition points to the correct `AppImageUri`
- confirm the ECS task execution role can read from ECR

### 14.6 Missing reports or transcripts

**Actions**
- inspect `/api/reports` and `/api/transcripts`
- review run logs via `/api/runs/:id/logs`
- confirm `EVAL_REPORT_OUTPUT_DIR`, `SCENARIOS_DIR`, and state symlinks are correct
- confirm S3 state sync bucket/prefix values are correct in ECS task environment
