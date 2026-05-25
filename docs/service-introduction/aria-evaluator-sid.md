# Service Introduction Document — ARIA Evaluator

This Service Introduction Document (SID) defines the managed-service introduction posture for ARIA Evaluator, the internal quality-assurance and automated evaluation platform used to test conversational AI agents across chat and voice providers.

## Document Control

| Field | Value |
|---|---|
| SID ID | SID-EVL-001 |
| Service | ARIA Evaluator |
| Version | 1.0.0 |
| Status | Draft |
| Classification | Internal |
| Owner | [OWNER_NAME] |
| Reviewers | [REVIEWER_NAME], [REVIEWER_NAME] |
| Business Unit | Engineering / AI Platform |
| Service Type | Internal Tooling / Quality Assurance Platform |
| Service Tier | Tier 2 (Business Important) |
| Category | AI Evaluation / Contact Centre QA |
| Effective Date | [DATE] |
| Next Review Date | [DATE] |

### Revision History

| Version | Date | Author | Change Summary |
|---|---|---|---|
| 0.1.0 | [DATE] | [NAME] | Initial evaluator service introduction draft for engineering review. |
| 0.9.0 | [DATE] | [NAME] | Added architecture, interfaces, operational model, scaling, and deployment content. |
| 1.0.0 | [DATE] | [NAME] | Baseline SID for internal production-style deployment and service transition. |

### Document Purpose

This SID provides a controlled description of how ARIA Evaluator should be introduced, supported, secured, and scaled as an internal quality platform used by engineers, QA teams, and AI governance stakeholders.

The document is intended to support architecture assurance, operational readiness, internal change review, and alignment between engineering teams operating conversational AI agents and the platform team providing evaluation capability.

## Executive Summary

ARIA Evaluator is a TypeScript and Node.js platform for repeatable testing of conversational AI agents, with a browser-based React UI, REST API, CLI execution modes, transcript persistence, report generation, and provider-specific adapters for both chat and voice channels. It exists to move AI contact-centre testing away from ad hoc manual spot checks and toward structured, evidential, and reusable evaluation workflows.

The platform's key differentiator is multi-provider support under a single run model. It can execute scenarios against Amazon Connect, Amazon Lex, Azure Bot, Strands-based services, Copilot SDK experiences, and custom endpoints. For voice evaluation it provides a native AWS path using `ConnectWebRTCAdapter` with `@roamhq/wrtc`, Chime signalling, Polly text-to-speech injection, and Transcribe Streaming capture. For chat and orchestration control it exposes both CLI and UI surfaces, allowing engineering teams to run individual scenarios, full packs, or replay saved transcripts through the evaluation pipeline.

The intended audience for this SID is engineering management, AI platform owners, QA leads, service operations, and architecture reviewers introducing the evaluator as a dependable internal tool rather than a developer-only utility. The service benefits include faster regression detection, standardised provider comparison, persistent run evidence, improved release confidence for AI agents, and a clearer operational boundary between test execution, report generation, and runtime settings management.

## Service Description

### Service Profile

| Attribute | Definition |
|---|---|
| Service Name | ARIA Evaluator |
| Package Description | ARIA Evaluator — TypeScript/Node.js with Playwright voice + React UI |
| Service Classification | Internal engineering quality platform |
| Service Tier | Tier 2 (Business Important) |
| Service Type | Internal Tooling / Quality Assurance Platform |
| Category | AI Evaluation / Contact Centre QA |
| Primary Interfaces | React UI, Express REST API, CLI entrypoints, SSE event streams |
| Primary Runtime | Node.js 20 |
| Persistence | Prisma ORM with SQLite in current repo baseline; PostgreSQL target for scaled shared environments |
| Deployment Options | Local workstation, Docker container, ECS Fargate with CloudFront / ALB |
| Main Business Unit | Engineering / AI Platform |

ARIA Evaluator is designed to orchestrate scenario-driven conversations against AI agents and then persist transcripts, reports, logs, and metadata that support engineering decisions. It is intentionally broader than a single test harness: the service includes scenario loading, live-run control, transcript capture, evaluation by LLM judge, report generation, settings administration, and artifact browsing through the UI.

The implementation currently centres on `aria-evaluator-ts/`. `src/api/server.ts` exposes the REST API and static assets, `src/api/routes/runs.ts` manages run creation and live log streaming, `src/conversation/runner.ts` drives individual scenarios, `src/adapters/*` implements provider integrations, and the React UI under `src/ui/` gives internal users a portal for runs, transcripts, reports, settings, and scenario selection.

## Business Context

### Business Drivers

- Reduce manual effort required to validate conversational AI changes across multiple providers and channels.
- Provide repeatable evidence of quality, safety, escalation, and compliance behaviours before releasing AI agents.
- Compare provider behaviour using the same scenario corpus and scoring model.
- Enable voice testing without human callers by automating WebRTC and browser-driven conversations.
- Surface live run logs, transcripts, and reports so teams can debug failures quickly.
- Create an operationally managed internal platform that supports continuous evaluation rather than one-off demonstrations.
- Support AI governance by preserving artifacts and scores for post-release review.

### Stakeholders & Personas

| Stakeholder / Persona | Interest | Required Outcome |
|---|---|---|
| AI platform engineer | Regression detection and rapid diagnosis | Reliable run execution, logs, and reproducible artifacts |
| QA / test automation lead | Coverage and repeatability | Multi-scenario execution with clear pass/fail evidence |
| Contact-centre solution architect | Provider comparison | Side-by-side behaviour across Connect, Lex, Azure, Strands, Copilot, and custom endpoints |
| Product engineer | Fast feedback before release | Easy UI/CLI workflow and reusable scenarios |
| AI governance / model risk | Evidence and traceability | Persistent transcripts, reports, and judge output |
| Operations / platform support | Manageable internal service | Health endpoint, logs, deployment model, and incident handling |
| Security reviewer | Safe use of secrets and test data | Controlled settings, internal-only deployment, and approved datasets |

### Business Value Metrics

| Metric | Target | Rationale |
|---|---|---|
| Regression test turnaround time | < 30 minutes for standard scenario packs | Keeps release validation aligned with sprint delivery tempo |
| Artifact availability | 99.9% for completed runs | Ensures reports, transcripts, and logs are available for diagnosis |
| Voice test automation coverage | ≥ 80% of supported Connect voice journeys | Reduces reliance on manual call testing |
| Failed-run diagnosis time | < 15 minutes to identify likely root cause | Enabled by SSE logs and persisted transcripts |
| Provider onboarding time | < 5 engineering days for new chat adapter pattern | Encourages platform reuse |
| Reproducibility | 100% of completed runs produce transcript and run metadata | Required for auditability of release decisions |

The evaluator is strategically important because it shortens the feedback loop on AI behaviour. As conversational agents become more deeply embedded in customer-service channels, the cost of releasing without repeatable evaluation rises sharply. ARIA Evaluator therefore operates as a guardrail for delivery teams, not merely as a convenience tool.

From a platform perspective, the service also standardises how artifacts are produced and consumed. Rather than each project inventing its own logs and spreadsheets, teams can rely on a common run object, transcript format, audio artifact pattern, and report output location.

## Service Scope

### In-Scope

- Scenario-based chat and voice execution against supported providers.
- React UI for initiating and reviewing runs, transcripts, reports, and runtime settings.
- Express API for runs, scenarios, transcripts, reports, settings, and health.
- CLI execution modes: `cli:connect`, `cli:lex`, `cli:azure`, `cli:strands`, `cli:copilot`, and `cli:custom`.
- Native Connect voice evaluation using `ConnectWebRTCAdapter` and Node-based WebRTC.
- Browser-automation voice evaluation paths where Playwright-based adapters are required.
- Transcript persistence to `transcripts/`, audio persistence to `transcripts/audio/`, and run logs under `reports/run-logs/`.
- LLM-based evaluation and report generation for completed transcripts.
- Runtime settings persistence through `data/runtime-settings.json` and environment overlays.
- Containerised and ECS-style deployment support.

### Out-of-Scope

- Production customer-contact routing or live customer servicing.
- Real-time intrusion detection or general SIEM replacement.
- Full-scale test management, defect management, or enterprise test planning workflows.
- Non-approved use of live customer data in evaluation packs.
- Voice support for providers explicitly marked chat-only in the current implementation.
- Continuous synthetic monitoring of external providers unless separately scheduled and governed.

### Service Boundaries

The service boundary begins when an internal user or automation process starts a run through the UI, API, or CLI. Within that boundary the platform selects scenarios, resolves runtime settings, spawns the appropriate CLI/provider adapter, collects live output, persists artifacts, computes evaluation results, and exposes them back through API and UI surfaces.

The boundary ends at the provider adapter edge and artifact consumers. ARIA Evaluator does not own the target provider's uptime, dialogue design, or security posture; it measures those systems. Likewise, it does not own enterprise test governance beyond the evidence it produces.

Where teams require enterprise scheduling, pipeline orchestration, or broader release workflow integration, ARIA Evaluator should be treated as a component within that chain rather than the complete SDLC control plane.

## Technical Architecture

### Architecture Overview

ARIA Evaluator uses a hub-and-spoke internal architecture. The hub is a Node.js service exposing a REST API, static UI, and run orchestration. The spokes are provider adapters that know how to talk to Connect, Lex, Azure Direct Line, Strands endpoints, Copilot-style chat, or custom HTTP/WebSocket services. A shared conversation runner and transcript model ensure that provider-specific variability is normalised into common artifacts.

The API layer is implemented in `src/api/server.ts` and routes under `src/api/routes/`. `runs.ts` is the most important operational route because it creates run records, persists line-oriented logs under `reports/run-logs`, streams live output via SSE, merges transcripts back into Prisma, and upserts final evaluation and report records. `runner.ts` handles scenario execution, collects turns, persists transcripts, and saves mixed voice audio for voice runs.

### Component Diagram in ASCII/text

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Internal Users / Automation                                                  │
│ - Browser users                                                              │
│ - Engineers running CLI                                                      │
│ - CI or scheduled internal jobs                                              │
└───────────────────────────────┬──────────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ ARIA Evaluator Service                                                       │
│                                                                              │
│  React UI (Runs, Scenarios, Reports, Settings, Transcripts)                 │
│                  │                                                           │
│                  ▼                                                           │
│  Express API                                                                  │
│  - /api/runs                                                                  │
│  - /api/scenarios                                                             │
│  - /api/transcripts                                                           │
│  - /api/reports                                                               │
│  - /api/settings                                                              │
│  - /health                                                                    │
│                  │                                                           │
│                  ▼                                                           │
│  Run Orchestration                                                            │
│  - Scenario loader                                                            │
│  - Scenario runner                                                            │
│  - Child-process CLI execution                                                │
│  - SSE log streaming                                                          │
│  - Transcript / report persistence                                            │
└───────────────┬───────────────────────────────┬──────────────────────────────┘
                │                               │
                ▼                               ▼
┌────────────────────────────┐     ┌──────────────────────────────────────────┐
│ Shared Data Layer          │     │ Provider Adapters                         │
│ - Prisma models            │     │ - Connect chat                            │
│ - SQLite / PostgreSQL path │     │ - Connect WebRTC voice                    │
│ - reports/, transcripts/   │     │ - Playwright voice                        │
│ - runtime-settings.json    │     │ - Lex chat                                │
└───────────────┬────────────┘     │ - Azure Direct Line chat                  │
                │                  │ - Strands chat                            │
                │                  │ - Copilot / custom chat and voice         │
                │                  └───────────────┬──────────────────────────┘
                │                                  │
                ▼                                  ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ External Services                                                             │
│ Amazon Connect | ConnectParticipant | Chime | Polly | Transcribe Streaming   │
│ Bedrock / Bedrock Agent Runtime | Lex | Azure Direct Line | Custom endpoints |
└──────────────────────────────────────────────────────────────────────────────┘
```

### Technology Stack

| Layer | Technology | Role in Service |
|---|---|---|
| Language | TypeScript / Node.js | Primary backend and CLI implementation |
| Front end | React 18 + Vite | Internal web portal for runs, reports, transcripts, and settings |
| API framework | Express | REST API and SSE event streaming |
| ORM | Prisma | Persistence abstraction for runs, turns, reports, and evaluation results |
| Default database | SQLite | Current repository baseline and local development data store |
| Scaled database target | PostgreSQL via Prisma-compatible deployment pattern | Recommended for shared multi-user environments |
| Browser automation | Playwright | Browser-driven voice/chat evaluation paths |
| Native voice stack | `@roamhq/wrtc` + `amazon-chime-sdk-js` | Node-side WebRTC and Chime signalling for Connect voice |
| Speech services | Amazon Polly + Transcribe Streaming | Inject customer audio and transcribe agent output during voice tests |
| Cloud SDKs | AWS SDK v3 | Connect, ConnectParticipant, Bedrock, Lex, Polly, Transcribe integrations |
| UI state / validation | Native React patterns + typed contracts | Keeps internal UI simple and strongly typed |
| Containerisation | Docker | Portable runtime packaging |
| Infrastructure | CloudFormation under `infra/cloudformation` | Low-cost ECS Fargate, CloudFront, ALB, S3 state storage |

### Integration Points

| Integration Point | Direction | Purpose | Notes |
|---|---|---|---|
| `/api/runs` | Inbound | Create, inspect, and soft-delete evaluation runs | Core operational API |
| `/api/runs/:id/logs` | Inbound | Retrieve persisted run logs | Reads from `reports/run-logs` |
| `/api/runs/:id/events` | Inbound SSE | Stream live run events and replay persisted logs on reconnect | Used by Runs page |
| `/api/transcripts` | Inbound | List and fetch transcript artifacts | JSON transcript browsing |
| `/api/reports` | Inbound | List generated HTML and JSON reports | Artifact discovery |
| `/api/settings` | Inbound | Manage editable runtime settings | Backed by `data/runtime-settings.json` |
| CLI provider scripts | Internal | Execute provider-specific run entrypoints | Spawned by `runs.ts` |
| Provider adapters | Outbound | Talk to Connect, Lex, Azure, Strands, Copilot, or custom endpoints | Channel-specific implementations |
| Static artifact serving | Outbound/internal | Serve `/reports`, `/transcripts`, and `/audio` | Used by UI for review |

## Service Interfaces

### APIs/Contracts

| Interface | Method / Protocol | Contract Summary | Consumer |
|---|---|---|---|
| Health endpoint | `GET /health` | Returns `{ ok, ts }` for liveness and timestamp | Load balancer, monitoring |
| Runs list | `GET /api/runs` | Returns most recent non-deleted runs and eval results | UI, automation |
| Run detail | `GET /api/runs/:id` | Returns run, ordered turns, eval result, and report metadata | UI |
| Run logs | `GET /api/runs/:id/logs` | Returns persisted log lines for a run | UI, troubleshooting tooling |
| Run events | `GET /api/runs/:id/events` (SSE) | Streams `start`, `log`, `complete`, and `failed` events | UI live panels |
| Run create | `POST /api/runs` | Accepts scenario file(s)/refs, channel, and provider | UI and future automation |
| Transcript list/read | `GET /api/transcripts`, `GET /api/transcripts/:filename` | Lists transcript JSONs and returns selected file | UI, artifact export |
| Reports list | `GET /api/reports` | Lists HTML and JSON report artifacts | UI |
| Settings read/update | `GET/PUT /api/settings` | Reads effective settings and updates editable overrides | Internal operators |

The API contracts are intentionally pragmatic. They are optimised for an internal engineering portal rather than for public partner consumption, which is why the service serves static assets and artifacts directly and keeps payloads close to internal object models.

A key interface pattern is the split between synchronous metadata calls and asynchronous run execution. `POST /api/runs` returns quickly with a `202` and `runId`, then the long-running work continues in a detached child process while logs and completion state are delivered via SSE and persisted storage.

### Event/Message Interfaces

| Event / Message | Producer | Consumer | Purpose |
|---|---|---|---|
| SSE `start` event | Runs API | React Runs page | Announces run start, provider, channel, and selected scenarios |
| SSE `log` event | Runs API | React Runs page | Streams terminal-style progress and replayable logs |
| SSE `complete` event | Runs API | React Runs page | Communicates final score, pass status, and report paths |
| SSE `failed` event | Runs API | React Runs page | Communicates run failure and error summary |
| Connect chat websocket frames | Amazon Connect / ConnectParticipant | Connect chat adapter | Customer/agent message flow |
| WebRTC / Chime media frames | Amazon Connect / Chime | Connect WebRTC adapter | Voice session establishment and audio streaming |
| Transcript JSON | Scenario runner | Report generator, UI, support tools | Normalised conversation artifact |
| WAV audio artifact | Voice adapters | UI and engineering review | Mixed 16 kHz mono voice recording |

### UI Interfaces

- Runs page with provider and channel selection, live transcript rendering, log replay, and artifact linking.
- Dashboard page showing recent run status and summaries.
- Scenarios page for selecting scenario packs and launching runs.
- Reports page for generated HTML/JSON evaluation outputs.
- Transcripts page for browsing stored transcript files and replay artifacts.
- Settings page for editing approved runtime configuration keys without code changes.

The UI also encodes operational rules. `RunsPage.tsx` explicitly marks `lex`, `azure`, `strands`, and `copilot` as chat-only providers, while `connect` and properly configured `custom` providers can expose both chat and voice. This prevents unsupported mode selection before a run ever starts.

## Service Dependencies

### Internal Dependencies

| Dependency | Type | Dependency Reason |
|---|---|---|
| `src/api/server.ts` | Core service | Hosts REST API, static assets, and health endpoint |
| `src/api/routes/runs.ts` | Core service | Manages run lifecycle, log persistence, SSE, and Prisma updates |
| `src/conversation/runner.ts` | Execution engine | Drives scenarios through adapters and writes transcripts/audio |
| `src/adapters/*` | Integration layer | Encapsulates provider-specific chat and voice behaviour |
| `src/report/generator.ts` | Reporting | Generates HTML/JSON reports from transcripts and judge results |
| `src/judge/*` | Evaluation | Calculates scores and recommendations |
| `prisma/schema.prisma` | Persistence contract | Defines run, turn, result, report, and scenario data model |
| `src/api/runtime-settings.ts` | Config management | Reads, persists, and merges editable settings |
| React UI under `src/ui` | Internal consumer surface | Main operator-facing portal |

### External Dependencies table

| External Service / Component | Criticality | Usage | Failure Impact |
|---|---|---|---|
| Amazon Connect | High | Chat and voice evaluation target, contact setup | Connect-based runs unavailable |
| ConnectParticipant API | High | Chat message transport | Connect chat tests fail |
| Chime signalling | High | WebRTC media setup for Connect voice | Native voice tests fail |
| Amazon Polly | Medium | Customer speech synthesis into voice path | Voice runs lose synthetic input path |
| Amazon Transcribe Streaming | Medium | Agent speech transcription during voice evaluation | Reduced transcript quality or no voice artifact text |
| Amazon Bedrock / Bedrock Agent Runtime | Medium to High | Target provider for some evaluated services | Provider-specific runs unavailable |
| Amazon Lex V2 | Medium | Chat-only provider target | Lex runs unavailable |
| Azure Direct Line | Medium | Azure Bot chat testing | Azure runs unavailable |
| Custom chat/voice endpoints | Variable | Partner or internal non-standard targets | Run failures for dependent scenarios |
| Docker / ECS / CloudFront stack | Medium | Shared internal deployment footprint | Internal hosted portal unavailable |

Because ARIA Evaluator is a measuring service, dependency failure rarely creates direct customer harm, but it does create delivery risk by removing evidence or delaying release validation. That is why the service is categorised as Tier 2 rather than a disposable engineering utility.

The most significant architectural dependency constraint is provider asymmetry. Voice is currently supported for `connect` and for `custom` voice adapters when configured; the other provider types are explicitly enforced as chat-only both in CLI validation and in the UI. That control is necessary to avoid false expectations and wasted run cycles.

## Service Level Objectives

### Target Service Levels

| Objective | Target | Measurement Approach |
|---|---|---|
| Monthly availability | 99.5% | Successful health checks and API responsiveness during business support hours |
| Run creation API latency | p95 ≤ 500 ms | Time to acknowledge `POST /api/runs` and return `202` |
| Log propagation delay | p95 ≤ 2 seconds | Delay between child-process output and SSE/log visibility |
| Artifact persistence | 99.9% for completed runs | Transcript, run log, and report availability after run completion |
| UI page availability | 99.5% | Static asset and API reachability |
| Report generation completion | ≥ 98% for successfully completed transcript sets | Judge and report pipeline reliability |

### Availability, Throughput, and Recovery Targets

| Dimension | Target | Notes |
|---|---|---|
| Concurrent run orchestration | 10 chat runs or 3 voice runs per shared service instance as initial operating guardrail | Voice runs are materially heavier due media and transcription load |
| Maximum single run duration | 60 minutes | Matches `RUN_HARD_TIMEOUT_MS` default of 3,600,000 ms |
| Persisted log retention per run | Up to 3,000 lines | Controlled by `MAX_PERSISTED_LOG_LINES` |
| RTO | 4 hours | Internal tooling recovery target |
| RPO | 1 hour for shared-service runtime settings and artifacts; near-zero where backed by durable object storage | Depends on deployment pattern |

These SLOs recognise that ARIA Evaluator is not customer-facing, but it is release-critical for teams using it as a gate before deploying conversational AI changes. Response expectations are therefore lower than for ARIA Banking Agent but still formal enough to support internal SLAs.

The most important quality measure is not only uptime; it is whether a completed run leaves behind usable artifacts. A run without logs, transcript, or report is operationally far less valuable than a run that fails fast with a clear error message.

## Operational Model

### Support Tiers table — L1/L2/L3

| Support Tier | Team | Responsibilities | Typical Triggers |
|---|---|---|---|
| L1 | Internal service desk / platform enablement | Confirm availability, collect run IDs, verify known issues, route tickets | Portal unavailable, users cannot view reports, basic settings issues |
| L2 | QA platform operations / AI platform support | Diagnose API, SSE, artifact, settings, and provider-integration failures | Stuck runs, missing logs, repeated provider auth/config errors |
| L3 | Service developers / specialist platform engineers | Code fixes, adapter changes, Prisma issues, deployment defects, deep provider troubleshooting | Persistent defects, failed upgrades, architecture changes |

### On-Call Model

- Business-hours primary support for routine incidents and enhancement requests.
- Extended-hours escalation available when the service is part of a release-critical path or shared cutover window.
- Named engineering owner for planned release weekends where evaluator evidence is required before promotion.
- Security consultation on demand if secrets, test-data handling, or artifact exposure is suspected to be unsafe.

### Incident Classification

| Severity | Definition | Example |
|---|---|---|
| Sev1 | Broad release-impacting outage during critical release window | Runs cannot start, artifacts unavailable, service entirely down for multiple teams |
| Sev2 | Major degradation with workaround | Voice runs fail but chat runs continue, SSE broken but logs retrievable later |
| Sev3 | Limited-impact bug | Single provider adapter defect, report list issue, settings update glitch |
| Sev4 | Minor issue or enhancement | UX refinement, non-blocking documentation gap, cosmetic defect |

Operational ownership should emphasise quick diagnosis. The platform already retains terminal-style output, run metadata, and transcript files, so support processes should require attachment of `runId`, provider, channel, and timestamp on every incident ticket.

For long-running or heavyweight voice tests, operators should differentiate between platform failure and target-system failure. The evaluator must expose enough evidence to make that distinction clear, especially when Connect, Lex, Azure, or a custom endpoint is the true cause of the failed run.

## Security & Compliance

### Security Classification

The service is an Internal engineering platform, but its artifacts can contain customer-like utterances, scenario data, voice recordings, runtime endpoints, and provider configuration. It must therefore be treated as an internal confidential system with controlled operator access and approved dataset usage.

### AuthN/AuthZ

- Runtime access should be restricted to authenticated internal users through enterprise ingress controls such as CloudFront, ALB, corporate network controls, or SSO-enabled reverse proxy patterns.
- Outbound provider access is controlled through AWS IAM, API keys, bearer tokens, or provider-specific secrets configured via environment or runtime settings.
- `runtime-settings.json` stores only approved editable keys; secrets should still be managed through secure deployment mechanisms wherever possible.
- The service itself does not implement fine-grained RBAC in the current codebase, so deployment architecture must provide tenancy and access restrictions externally.

### Data Classification

| Data Type | Classification | Handling Rule |
|---|---|---|
| Synthetic scenarios | Internal | Preferred data source for routine testing |
| Provider endpoints and configuration | Confidential internal configuration | Restrict editing to approved operators |
| Transcripts | Confidential | Review access limited to relevant engineering and QA teams |
| Voice recordings | Confidential | Store only where justified and purge by retention policy |
| Run logs | Internal / Confidential depending on content | Avoid secrets in log output and cap retention |
| Evaluation reports | Internal | Safe for engineering sharing when based on approved datasets |

### Regulatory Requirements

- Internal software engineering control requirements for change management and evidence retention.
- GDPR-aligned handling if any non-synthetic or personal-like data is introduced into scenarios or transcripts.
- Cloud security baseline for secret handling, logging, and least privilege.
- AI governance obligations for documented release evidence and model behaviour review.

Although ARIA Evaluator is not the production customer-service system, it can produce sensitive artifacts. Teams must therefore use masked or synthetic test data by default, segregate environments, and avoid using unrestricted personal data in scenario packs unless explicitly approved under a controlled test process.

The current code permits broad CORS and simple static serving because the service is intended for controlled internal networks and tooling environments. If introduced as a shared enterprise portal, the service must be fronted by hardened ingress, authenticated access, encrypted transport, and storage policies appropriate to the artifact sensitivity.

## Capacity & Scalability

### Current Capacity

The repository currently supports a practical low-cost operating model. `infra/cloudformation/ecs-cloudfront-lowcost.yaml` provisions a single desired-count ECS Fargate service behind an ALB and CloudFront, with S3-backed state synchronization patterns and conservative CPU/memory defaults. This is appropriate for small-to-medium shared engineering use but not for unrestricted horizontal burst.

At the application layer, the current Prisma schema is configured for SQLite, which is efficient for local and small shared deployments but imposes single-writer and scaling constraints under heavier concurrent use. For broader organisational rollout, the platform should migrate the Prisma datasource to PostgreSQL and separate artifact storage from the application container lifecycle.

### Scaling Approach

- Keep API and UI stateless where possible so they can scale horizontally behind the load balancer.
- Externalise persistence to PostgreSQL for shared multi-user environments.
- Store reports, transcripts, and audio in durable object storage rather than local container disk where persistence matters.
- Limit voice-run concurrency per worker because WebRTC, Chime, Polly, and Transcribe workloads are resource intensive.
- Separate run execution workers from API/UI service if sustained concurrent usage grows.
- Use per-provider concurrency controls to prevent external quota exhaustion.

### Known Limits

| Limit | Current Behaviour | Operational Consideration |
|---|---|---|
| Voice provider support | `connect` and configured `custom` only | UI and CLI explicitly block voice mode for chat-only providers |
| Run timeout | Hard stop after 60 minutes by default | Prevents zombie runs but may terminate long investigations |
| Persisted log volume | 3,000 lines retained per run | Very verbose runs may need artifact export beyond portal view |
| SQLite baseline | Single-node friendly, limited for shared concurrent writes | PostgreSQL recommended for scale |
| Fargate template desired count | Default 1, max 1 in low-cost template | Suitable for pilot/internal use, not burst-heavy scale |
| Voice artifact cost | Audio recording and transcription increase storage and runtime cost | Apply retention policies and concurrency guardrails |

Capacity management should be grounded in usage tiers. A small engineering pod can operate comfortably on the low-cost footprint, while enterprise-wide adoption should trigger a deliberate scale-up plan including Postgres, separated workers, and hardened artifact storage.

## Monitoring & Observability

### Key Metrics

| Metric Family | Example Metrics | Why It Matters |
|---|---|---|
| Service health | `/health` success, API latency, static asset availability | Confirms operator access |
| Run execution | run start rate, duration, completion rate, timeout count | Measures platform effectiveness |
| Provider quality | failures by provider/channel, auth/config failures, adapter error types | Identifies integration hotspots |
| Artifact integrity | transcript save success, report generation success, log availability, audio save success | Confirms evidence completeness |
| User operations | settings updates, concurrent run count, active SSE streams | Helps capacity planning |

### Logging Strategy

- Runs persist line-oriented logs under `reports/run-logs` using `run-<id>.log` naming.
- `runs.ts` appends stdout and stderr lines from spawned CLI processes and replays them over SSE.
- Transcript artifacts are written as prettified JSON under `transcripts/`, with voice WAV files under `transcripts/audio/`.
- Completion state is summarised into Prisma records so UI pages can load quickly even after runs end.
- In development, Prisma logs warnings and errors; in production, error-only logging reduces noise.

### Alerting Thresholds

| Alert | Threshold | Response |
|---|---|---|
| Run failure spike | > 30% failed runs for one provider in 15 minutes | Investigate target provider, credentials, or adapter regressions |
| Artifact gap | Any completed run missing transcript or report where expected | Treat as platform defect |
| SSE degradation | Event stream stalls or reconnect storms for active runs | Inspect API node health and reverse-proxy behaviour |
| Voice failure spike | > 20% Connect voice runs fail in 30 minutes | Check Connect, Chime, Polly, Transcribe, and runtime quotas |
| Storage growth | Audio/transcript/report storage exceeds retention forecast | Apply cleanup policy and capacity review |

### Dashboards

- Operations dashboard for run counts, failure rates, and active provider/channel mix.
- Quality dashboard for pass rates, average scores, and scenario pack outcomes.
- Artifact dashboard for transcript, report, and audio generation completeness.
- Platform dashboard for API latency, health checks, and deployment status.

Because the evaluator is often used during release cycles, observability must support both routine operations and fast triage under deadline pressure. The combination of persisted logs, transcript detail, and report linkage is the core support model and should be preserved even if the infrastructure topology evolves.

## Disaster Recovery & Business Continuity

### DR Strategy

The recommended DR model is rapid rebuild plus durable artifact retention. Application containers should be treated as replaceable, while run metadata, settings, reports, transcripts, and audio artifacts should be kept in durable backing stores appropriate to the deployment tier.

### RTO/RPO Targets

| Recovery Dimension | Target |
|---|---|
| Service RTO | 4 hours |
| Artifact RPO | 1 hour in shared deployment baseline |
| Runtime settings RPO | 1 hour unless backed by external state sync |
| Pilot/local deployment RPO | Best effort |

### Failover Approach

- Rebuild the API/UI container from Docker image and redeploy through ECS or equivalent runtime.
- Restore database and artifact storage from durable backups or synchronized object storage.
- If the shared portal is unavailable, fall back to CLI execution on approved engineer workstations.
- Preserve scenario repositories and runtime settings outside ephemeral container filesystems for shared deployments.
- Validate provider credentials and external reachability before reopening the service.

Business continuity for ARIA Evaluator is principally about keeping release evidence flowing. The fallback plan should therefore prioritise preserving the ability to run scenarios and capture artifacts, even if that means temporarily reverting to CLI-only operation while the portal is restored.

## Service Transition Plan

### Transition Phases table

| Phase | Objective | Key Activities | Exit Criteria |
|---|---|---|---|
| Foundation | Establish baseline service shape | Package build, local runtime validation, artifact paths, health endpoint verification | Stable local deployment with persisted outputs |
| Shared pilot | Introduce managed internal portal | ECS/CloudFront deployment, ingress hardening, secrets setup, user onboarding | Pilot users can run and review scenarios reliably |
| Operational readiness | Formalise support model | Dashboards, retention policy, support rota, runbook creation, backup validation | L1/L2/L3 sign-off |
| Controlled adoption | Expand to additional engineering teams | Provider onboarding, scenario governance, concurrency tuning | Stable usage with agreed SLAs |
| Standard platform service | Make evaluator the default QA path | Integrate with release processes and governance checkpoints | Platform owner approval and service review complete |

### Acceptance Criteria

- `npm run lint` and `npm run build` succeed in the evaluator package.
- API, UI, and static artifact routes work in the target deployment environment.
- Run creation, logs, transcripts, reports, and settings APIs behave as documented.
- Connect voice runs generate transcripts and 16 kHz mono WAV output.
- Chat-only provider restrictions are enforced in UI and CLI.
- Artifact retention, access controls, and backup expectations are documented and tested.
- Support teams can diagnose at least one failed run end-to-end using only stored artifacts and logs.

### Go-Live Checklist

- [ ] Build and lint pipeline green for `aria-evaluator-ts`.
- [ ] Runtime environment variables and editable settings keys reviewed.
- [ ] Secrets distribution method approved.
- [ ] SQLite/PostgreSQL deployment choice documented for target environment.
- [ ] Artifact storage, cleanup, and backup policy confirmed.
- [ ] Health endpoint and dashboard monitoring configured.
- [ ] Runbook published for stuck runs, missing logs, and failed provider sessions.
- [ ] Internal users trained on provider/channel limitations.
- [ ] Pilot sign-off captured from platform owner and QA lead.

## Training & Knowledge Transfer

### Training Requirements

| Audience | Training Focus |
|---|---|
| Platform support | Service architecture, health checks, log locations, artifact paths |
| QA engineers | Scenario selection, run interpretation, transcript/report usage |
| AI developers | Provider configuration, adapter behaviours, run reproduction |
| Security reviewers | Secrets handling, access model, artifact sensitivity |
| Service owners | Capacity model, deployment topology, and DR approach |

### Documentation Links

- `aria-evaluator-ts/package.json`
- `aria-evaluator-ts/src/api/server.ts`
- `aria-evaluator-ts/src/api/routes/runs.ts`
- `aria-evaluator-ts/src/conversation/runner.ts`
- `aria-evaluator-ts/src/adapters/connect-webrtc.ts`
- `aria-evaluator-ts/src/ui/pages/RunsPage.tsx`
- `aria-evaluator-ts/prisma/schema.prisma`
- `aria-evaluator-ts/Dockerfile`
- `aria-evaluator-ts/infra/cloudformation/ecs-cloudfront-lowcost.yaml`

### Knowledge Transfer Plan

- Walkthrough of provider model, including chat-only versus voice-capable adapters.
- Hands-on session for launching runs, reading live logs, and reviewing generated artifacts.
- Operational handover for deployment, settings management, and incident triage.
- Retrospective after pilot adoption to update runbooks, retention rules, and scaling assumptions.

Knowledge transfer is complete when support and QA teams can independently launch a representative run, interpret the transcript and report output, and identify the difference between platform failure and target-provider failure.

## Risk Register

| ID | Risk | Category | Probability | Impact | Mitigation | Owner | Status |
|---|---|---|---|---|---|---|---|
| EVL-R01 | SQLite persistence becomes a bottleneck as concurrent internal usage increases. | Scalability / Data | Medium | High | Move shared deployments to PostgreSQL, separate artifact storage, and load-test before wider adoption. | [OWNER_NAME] | Open |
| EVL-R02 | Secrets or provider tokens are handled unsafely through runtime settings or logs. | Security | Medium | High | Use secret stores where possible, redact logs, restrict settings access, and review deployment architecture. | [OWNER_NAME] | Open |
| EVL-R03 | Voice run reliability is affected by external service quotas or signalling instability in Connect/Chime/Transcribe. | Dependency / Reliability | Medium | Medium | Add quota monitoring, concurrency guardrails, retry logic, and clear runbook guidance for provider-side faults. | [OWNER_NAME] | Open |
| EVL-R04 | Teams treat evaluator scores as absolute truth despite scenario or judge-model limitations. | Governance | Medium | High | Publish scoring guidance, keep human review for critical releases, and version scenario packs and judge prompts. | [OWNER_NAME] | Open |
| EVL-R05 | Artifact growth from transcripts, logs, and WAV files increases storage cost and slows portal access. | Cost / Operations | Medium | Medium | Implement retention schedules, externalize storage, and monitor artifact volume trends. | [OWNER_NAME] | Open |
| EVL-R06 | Provider capability drift causes outdated assumptions about chat-only and voice-enabled modes. | Product / Integration | Medium | Medium | Review provider matrix quarterly and update UI/CLI enforcement logic with release notes. | [OWNER_NAME] | Open |

## Approvals

| Role | Name | Signature | Date |
|---|---|---|---|
| Service Owner | [NAME] | [NAME] | [DATE] |
| QA Platform Lead | [NAME] | [NAME] | [DATE] |
| Enterprise Architect | [NAME] | [NAME] | [DATE] |
| Information Security Reviewer | [NAME] | [NAME] | [DATE] |
| Engineering Manager | [NAME] | [NAME] | [DATE] |
