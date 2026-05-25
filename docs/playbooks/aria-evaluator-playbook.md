# ARIA Evaluator TS Playbook

| Field | Value |
|---|---|
| **Document ID** | PLY-EVAL-001 |
| **Version** | 1.0 |
| **Status** | Active |
| **Owner** | Platform Engineering |
| **Date** | 2026-05-25 |
| **Classification** | Internal |

---

## Table of Contents

1. [Purpose](#1-purpose)
2. [Architecture](#2-architecture)
3. [Prerequisites](#3-prerequisites)
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

## 1. Purpose

ARIA Evaluator TS is the operational quality-evaluation platform for AI agents in the `awsagentcore` repository. It is a TypeScript/Node.js service with an Express API, a React/Vite UI, Prisma ORM, and Playwright-powered chat and voice evaluation flows that execute against supported providers such as Amazon Connect, Lex, Azure Direct Line, Strands, Copilot, and custom endpoints.

The platform is used to:
- execute automated evaluation runs from curated YAML scenarios;
- simulate customer conversations and capture transcripts;
- score runs with an LLM judge;
- store reports, transcripts, runtime settings, and run metadata for review;
- operate as a locally runnable developer tool and as a low-cost CloudFront + ECS Fargate deployment.

### 1.1 Service Scope

| Capability | Current implementation |
|---|---|
| **Backend** | Node.js 20+ with Express REST API in `src/api/server.ts` |
| **Frontend** | React 18 + Vite UI in `src/ui/` |
| **Evaluation engine** | Scenario runner + provider adapters + CLI launchers in `src/conversation/`, `src/adapters/`, `src/cli/` |
| **Persistence** | Prisma ORM with SQLite datasource in `prisma/schema.prisma` |
| **Artifacts** | Reports under `reports/`, transcripts under `transcripts/`, runtime overrides under `data/` |
| **Cloud target** | Docker container on ECS Fargate behind ALB and CloudFront, with S3-backed state sync |

### 1.2 Operational Objective

Provide a repeatable and supportable method to deploy, validate, operate, and recover the ARIA Evaluator TS service while minimizing downtime and preserving generated reports, transcripts, and scenario data.

---

## 2. Architecture

### 2.1 Logical Architecture Summary

```text
Users / Operators
        |
        v
CloudFront
        |
        v
Application Load Balancer
        |
        v
ECS Fargate task (single Docker container)
        |
        +--> Express API (/api/*, /health)
        +--> React UI (static assets served by API container)
        +--> Prisma + SQLite database file
        +--> Reports / transcripts / run logs / settings state
        |
        v
S3 state bucket sync via ECS entrypoint
```

### 2.2 Application Components

| Component | Description | Evidence |
|---|---|---|
| **Express API** | Serves REST routes for scenarios, runs, transcripts, reports, and settings; exposes `/health`; serves built UI assets | `src/api/server.ts` |
| **Run orchestration** | Creates runs, launches provider-specific CLI commands, streams logs over SSE, and persists results | `src/api/routes/runs.ts` |
| **Scenario management** | Loads YAML scenarios from disk and supports create/update of multi-document YAML files | `src/api/routes/scenarios.ts` |
| **React UI** | Dashboard plus Scenarios, Runs, Transcripts, Reports, and Settings views | `src/ui/App.tsx`, `src/ui/pages/*` |
| **Conversation engine** | Drives scripted or goal-based scenarios through chat or voice adapters | `src/conversation/runner.ts` |
| **Reporting** | Generates HTML and JSON evaluation reports | `src/report/generator.ts` |
| **Persistence layer** | Prisma client with `Scenario`, `Run`, `Turn`, `EvalResult`, and `Report` models | `src/db/client.ts`, `prisma/schema.prisma` |
| **State synchronization** | Restores state from S3, wires reports/transcripts/data directories, runs Prisma schema push, and starts API | `infra/docker/ecs-entrypoint.sh` |

### 2.3 Infrastructure Architecture

The reference cloud deployment is defined in `infra/cloudformation/ecs-cloudfront-lowcost.yaml` and creates:
- a VPC with two public subnets;
- an internet-facing ALB;
- an ECS Fargate cluster, task definition, and service;
- a CloudFront distribution with path-based behaviors for `/api/*`, `/reports/*`, `/transcripts/*`, `/audio/*`, and `/health`;
- an S3 bucket for state synchronization;
- an ECR repository for container images;
- CloudWatch Logs and IAM roles for ECS runtime and execution.

### 2.4 Data and State Model

| Data type | Storage location | Notes |
|---|---|---|
| **Run metadata** | Prisma database | Includes status, timing, audio path, linked evaluation and report records |
| **Turns / transcripts** | Prisma + `transcripts/*.json` | Conversation turns are persisted to DB and transcript JSON files |
| **Reports** | `reports/*.html` and `reports/*.json` | Also exposed through `/reports` |
| **Runtime settings** | `data/runtime-settings.json` | Overrides editable environment keys through UI/API |
| **Database** | SQLite file via `DATABASE_URL` | Default local path `file:./data/aria-evaluator.db`; ECS entrypoint rewires to `/app/state/data/aria-evaluator.db` |

### 2.5 Technology Baseline

| Layer | Standard |
|---|---|
| **Runtime** | Node.js 20+ |
| **Package manager** | npm |
| **Frontend build** | Vite |
| **Type safety / lint gate** | TypeScript (`npm run lint` = `tsc --noEmit`) |
| **ORM** | Prisma |
| **Container** | Docker on `node:20-bookworm-slim` |
| **Cloud platform** | AWS ECS Fargate + CloudFront + ALB + S3 + ECR |

---

## 3. Prerequisites

The following must be in place before any deployment or major change:

### 3.1 Tooling

- Node.js 20 or later
- npm
- Docker
- AWS CLI v2
- Access to an ECR repository
- Permissions to deploy CloudFormation stacks with IAM resources

### 3.2 Access and Service Dependencies

| Requirement | Why it is needed |
|---|---|
| **AWS credentials** | Required for ECR login, CloudFormation deploy, ECS verification, log access, and CloudFront inspection |
| **Bedrock access** | Required for LLM judging and optional customer simulation |
| **Provider credentials/config** | Connect, Lex, Azure, Copilot, Strands, or custom provider settings must be supplied for live runs |
| **Container registry access** | Required to push the application image used by ECS |
| **CloudFormation IAM capability** | Template creates IAM roles and policies; deploys require `CAPABILITY_NAMED_IAM` |

### 3.3 Repository Inputs

- `aria-evaluator-ts/package.json`
- `aria-evaluator-ts/prisma/schema.prisma`
- `aria-evaluator-ts/infra/cloudformation/ecs-cloudfront-lowcost.yaml`
- `aria-evaluator-ts/infra/docker/ecs-entrypoint.sh`
- `.env` or environment overrides prepared outside version control

---

## 4. Deployment Strategy

### 4.1 Local Deployment Path

Use local deployment for development, validation, or troubleshooting:

1. `cd aria-evaluator-ts`
2. `npm install`
3. `npm run dev` for split API + Vite UI development mode
4. or `docker build` and `docker run` for container validation

**Expected local ports**
- API/default app port: `3001`
- Vite UI dev port: `5173`

### 4.2 Cloud Deployment Path

The standard release path is:

```text
docker build
   -> push image to ECR
      -> deploy/update CloudFormation stack using ecs-cloudfront-lowcost.yaml
         -> ECS service pulls image
            -> entrypoint restores state, applies Prisma schema, starts API/UI container
               -> CloudFront serves UI and proxies API
```

### 4.3 Standard Cloud Parameters

| Parameter | Recommended value |
|---|---|
| **AppName** | `aria-evaluator-ts` |
| **AppImageUri** | `<account>.dkr.ecr.<region>.amazonaws.com/aria-evaluator-ts:<tag>` |
| **DesiredCount** | `1` |
| **ContainerPort** | `3001` |
| **Cpu** | `256` unless testing requires more |
| **Memory** | `512` unless browser/runtime pressure requires more |

### 4.4 Deployment Principles

- Treat the Docker image as the release artifact.
- Keep `DesiredCount=1` for the low-cost topology unless performing controlled maintenance.
- Preserve `/app/state` contents via S3 synchronization before replacing tasks.
- Validate `/health`, UI access, and a sample evaluation run after every deployment.
- If the frontend asset set changes materially, invalidate CloudFront cache to reduce stale content risk.

---

## 5. Environment Matrix

| Environment | Hosting model | Primary use | Key commands / controls |
|---|---|---|---|
| **Local** | `npm run dev` or local Docker container | Development, debugging, scenario authoring | `npm run dev`, `npm run lint`, `npm run build`, `docker build` |
| **Staging** | ECS Fargate + ALB + CloudFront | Release validation and smoke tests | ECR push + CloudFormation deploy with `DesiredCount=1` |
| **Production** | ECS Fargate + ALB + CloudFront | Operational evaluation service | Controlled image release, post-deploy validation, rollback readiness |

### 5.1 Configuration Expectations

- Local may use `.env` and local filesystem state.
- Staging and production should use environment variables, state bucket synchronization, and immutable container images.
- Production changes to provider secrets or runtime settings must be auditable and controlled.

---

## 6. Change Management

All changes to ARIA Evaluator TS must follow standard release governance.

### 6.1 Change Types

| Change type | Required control |
|---|---|
| **Application code** | Peer review, lint/build validation, deployment verification |
| **Prisma schema change** | Assess DB impact, test on non-production data, validate startup `prisma db push` behavior, confirm data backup/rollback path |
| **ECS task definition/image update** | Versioned image tag, deployment note, service verification |
| **CloudFormation template change** | IaC review, change-set or controlled deploy, rollback plan |
| **Frontend asset change** | UI smoke test and CloudFront cache invalidation where needed |

### 6.2 Mandatory Controls

- Document release scope, risk, and expected impact before deployment.
- Use versioned container tags; do not rely on floating tags alone.
- Confirm `npm run lint` and `npm run build` pass on the release candidate.
- For schema changes, confirm persistence compatibility with the active SQLite file.
- For static asset changes, be prepared to run CloudFront invalidation to remove stale edge caches.

---

## 7. Risk Register

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| **R1** | ECS task image pull failure due to ECR auth or missing image | Medium | High | Verify image exists in ECR, task execution role has ECR access, test pull before deploy |
| **R2** | ALB health check failure caused by port mismatch or broken startup | Medium | High | Keep container/API port aligned to `3001`, verify `/health`, inspect entrypoint and ECS logs |
| **R3** | Playwright/browser runtime bloat increases image size and startup latency | Medium | Medium | Monitor image size, test build duration, size CPU/memory conservatively |
| **R4** | Evaluation timeout caused by upstream Bedrock/provider latency | High | Medium | Tune timeout env vars, validate provider reachability, retry in staging first |
| **R5** | Report/transcript storage fills local state volume or S3 bucket lifecycle is unmanaged | Medium | Medium | Monitor state growth, define retention, clean aged reports and transcripts |
| **R6** | Runtime settings drift between environments | Medium | Medium | Track environment overrides, review `data/runtime-settings.json`, keep production changes controlled |
| **R7** | Schema push at startup introduces incompatible data change | Low | High | Review Prisma changes, test on staging/state backup, use controlled release window |

---

## 8. Rollback Strategy

### 8.1 Primary Rollback Method

Rollback is executed by restoring the ECS service to the previous known-good task definition revision or by redeploying the prior image tag through CloudFormation.

### 8.2 Standard Rollback Sequence

1. Identify the last known-good image tag/task definition revision.
2. Update the ECS service or stack to reference that revision.
3. Confirm the replacement task reaches `RUNNING` and passes `/health`.
4. Invalidate CloudFront cache if stale UI assets remain visible.
5. Confirm reports, transcripts, and settings are still available from synchronized state.

### 8.3 Infrastructure Rollback

If a stack update fails, use CloudFormation rollback events as the source of truth and either:
- allow automatic rollback to complete; or
- redeploy the last known-good parameters/template set.

---

## 9. Communication Plan

| Stage | Audience | Communication |
|---|---|---|
| **Pre-change** | Platform Engineering, service owner | Change scope, risk, deployment window, rollback plan |
| **Start of deployment** | On-call engineers / stakeholders | Notify deployment start and expected validation duration |
| **Validation complete** | Platform Engineering, service owner | Confirm status, health, CloudFront URL, and smoke-test result |
| **Issue / rollback** | Platform Engineering lead, incident manager if needed | Provide impact statement, symptoms, mitigation, ETA |
| **Post-change** | Stakeholders and operations | Record outcome, defects, follow-up actions |

### 9.1 Minimum Change Record Content

- release identifier / image tag;
- target environment;
- reason for change;
- approver;
- validation result;
- rollback decision if applicable.

---

## 10. Success Criteria

A deployment is successful only when all of the following are true:

- ECS task status is `RUNNING`.
- ECS service desired count equals running count.
- ALB target is healthy and `/health` returns HTTP 200.
- CloudFront URL returns HTTP 200.
- UI loads and the Runs / Reports / Transcripts pages are reachable.
- At least one evaluation run completes successfully.
- Generated report is viewable.
- Transcript artifacts are visible through the UI or API.

---

## 11. Post-Deployment Validation

### 11.1 Required Validation Steps

1. Check CloudFormation stack status is complete.
2. Check ECS service desired vs running task counts.
3. Check target health behind the ALB.
4. Check CloudFront base URL and `/health`.
5. Open the UI and verify dashboard navigation.
6. Run one representative chat or voice scenario.
7. Confirm transcript JSON and HTML/JSON report artifacts are created.
8. Review CloudWatch logs for startup, Prisma, and run-processing errors.

### 11.2 Operational Evidence to Retain

- image tag deployed;
- CloudFront URL;
- ECS service/task revision;
- validation timestamps;
- sample run identifier and outcome.

---

## 12. Contacts and Escalation

| Priority | Role | Responsibility |
|---|---|---|
| **L1** | Platform Engineering on-call | Deployment execution, first-line triage, ECS/CloudFormation checks |
| **L2** | ARIA Evaluator service owner | Application-level defects, scenario execution failures, report/transcript defects |
| **L3** | Cloud platform / AWS account administrator | IAM, ECR, networking, CloudFront, ECS infrastructure failures |
| **L4** | Security / governance reviewer | Approval for IAM, secret handling, and compliance-impacting changes |

### 12.1 Escalate Immediately When

- production deployment is unavailable for more than 15 minutes;
- rollback fails or state artifacts appear corrupted;
- Bedrock/provider access failures affect all runs;
- data exposure, secret leakage, or unauthorized access is suspected.

---

## 13. Approvals

The following approvals are required for production-impacting change:

| Approval area | Required approver |
|---|---|
| **Application release** | Platform Engineering lead or delegated release manager |
| **Infrastructure / IAM change** | Cloud platform owner |
| **Schema or data-impacting change** | Service owner + Platform Engineering |
| **Security-sensitive change** | Security reviewer |

**Approval rule:** no production deployment proceeds without documented approval and a confirmed rollback path.
