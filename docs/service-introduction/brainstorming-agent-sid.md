# Brainstorming Agent Service Introduction Document

## Document Control

| Field | Value |
| --- | --- |
| SID ID | SID-BSA-001 |
| Version | 1.0.0 |
| Status | Draft |
| Classification | Internal |
| Owner | ARIA Engineering Product Enablement Lead — [OWNER_NAME] |
| Reviewers | Enterprise Architecture — [REVIEWER_NAME]; Security Architecture — [REVIEWER_NAME]; Service Operations — [REVIEWER_NAME] |
| Service Name | Brainstorming Agent |
| Business Unit | Engineering / Product |
| Service Tier | Tier 3 (Supporting) |
| Service Type | Internal Productivity Tool |
| Category | AI-Assisted Productivity / Knowledge Management |
| Initial Publication Date | [DATE] |
| Next Review Date | [DATE] |

| Revision | Date | Author | Summary |
| --- | --- | --- | --- |
| 0.1 | [DATE] | [OWNER_NAME] | Initial service introduction draft prepared for ARIA platform governance. |
| 0.9 | [DATE] | [OWNER_NAME] | Updated with technical architecture, operational model, and service transition controls. |
| 1.0.0 | [DATE] | [OWNER_NAME] | First controlled draft issued for architecture, security, and service management review. |

## Executive Summary

Brainstorming Agent is an internal ARIA platform capability designed to support structured ideation, solution shaping, and problem framing for engineering and product teams. The service combines a React and Vite user interface, a FastAPI application layer, a Strands-based Bedrock agent, SQLite persistence, and WebSocket streaming to create a continuous digital workspace for workshop-style thinking.

The service is optimised for high-context internal collaboration rather than external customer interaction. It preserves the thread of a brainstorming session, stores notable ideas and decisions, supports retrieval through SQLite FTS5 search, and presents a transparent audit trail of user messages, tool calls, safety analysis, and generated responses.

From a service management perspective, Brainstorming Agent is a Tier 3 supporting service because it improves delivery productivity but is not itself a customer-facing banking channel. The recommended production stance is controlled internal rollout, measured adoption, and governance focused on information classification, prompt safety, and operational transparency rather than high-volume transactional scale.

## Service Description

| Attribute | Definition |
| --- | --- |
| Name | Brainstorming Agent |
| Classification | Internal ARIA platform application supporting facilitated ideation and knowledge capture |
| Service Tier | Tier 3 (Supporting) |
| Service Type | Internal Productivity Tool |
| Category | AI-Assisted Productivity / Knowledge Management |
| Primary Consumers | Engineering teams, product managers, architects, delivery leads, innovation workshops |
| Primary Outcome | Persistent, searchable brainstorming sessions with real-time AI assistance |

Brainstorming Agent provides a browser-based workspace in which a user can create a session, maintain conversational context, and progressively capture high-value ideas. The service uses a FastAPI backend located under `brainstorming-agent/agent/`, and a React, Vite, and Tailwind frontend located under `brainstorming-agent/frontend/`.

The service does more than a simple chat interface. It binds each conversation to a session identifier, streams tokens and tool activity over `/ws/{session_id}`, stores sessions, memories, links between ideas, and audit events in SQLite, and allows users to return to prior lines of thinking without losing narrative continuity.

The backend agent is implemented with the Strands framework and is configured to use Amazon Bedrock, defaulting to the `eu.anthropic.claude-sonnet-4-6` model. Runtime tools include memory save, memory search, retrieval by topic, linking of related ideas, listing of previous sessions, and retrieval of prior session insights, allowing the service to behave as an accumulating knowledge workspace rather than a stateless prompt interface.

## Business Context

### Business Drivers

| Driver | Detail |
| --- | --- |
| Reduce ideation loss | Engineering and product teams regularly lose workshop outputs when whiteboards, notes, and follow-up actions are fragmented across tools. |
| Improve decision traceability | Strategic discussions benefit from being searchable later, especially where architectural choices evolve over several sessions. |
| Accelerate discovery cycles | A session-aware assistant reduces the time required to frame a problem, challenge assumptions, and identify non-obvious options. |
| Create reusable internal knowledge | Repeated thinking about similar propositions, delivery constraints, or regulatory themes can be linked and reused. |
| Standardise facilitation quality | The Strands system prompt enforces a structured answer pattern: substance first, insight second, one forward question last. |

### Stakeholders & Personas

| Persona | Need | Service Interaction |
| --- | --- | --- |
| Product Manager | Shape propositions, prioritise outcomes, and retain rationale | Creates topic-led sessions and saves insights as reusable decision artefacts |
| Solutions Architect | Explore option sets and record trade-offs | Uses linked memories and audit events to build design narratives |
| Engineering Lead | Run technical brainstorming and discovery workshops | Uses real-time streaming and session summaries during working sessions |
| Innovation Team | Compare ideas across multiple internal initiatives | Searches prior memories and reuses themes across sessions |
| Platform Operations | Support availability and health of the tool | Monitors health endpoint, logs, Docker health checks, and SQLite integrity |

### Business Value Metrics

| Metric | Measurement Intent | Indicative Target |
| --- | --- | --- |
| Session reuse rate | Percentage of sessions revisited after initial creation | Greater than 35 percent after pilot |
| Memory capture density | Average memories saved per active workshop session | At least 3 useful memories per session |
| Discovery cycle reduction | Reduction in time to produce a workshop summary or design direction | 20 to 30 percent improvement versus manual note collation |
| Search retrieval usefulness | Percentage of search results judged relevant by pilot users | Greater than 75 percent |
| User adoption | Monthly active internal users across engineering and product | Growth trend rather than fixed threshold during initial rollout |

The business case rests on productivity, continuity, and institutional memory rather than direct revenue generation. In a UK retail bank environment, this is valuable because engineering and product teams frequently revisit the same themes: customer journeys, architecture guardrails, controls, operational resilience, and AI-enabled propositions.

The service also supports governance by preserving auditable interaction records in the `audit_log` table. This enables retrospective review of prompts, output safety checks, and tool invocations, which is materially stronger than ad hoc note-taking in consumer collaboration tools.

## Service Scope

### In-Scope

- Browser-based brainstorming workspace for internal engineering and product users.
- Session creation, switching, and summary update through FastAPI REST endpoints.
- Real-time agent response streaming and tool activity updates through WebSockets.
- Persistent storage of sessions, memories, memory links, and audit events in SQLite.
- Memory search, topic filtering, and related-idea expansion through the frontend memory browser.
- Browser-native speech-to-text and text-to-speech through the Web Speech API.
- Docker-based local or controlled internal deployment using the supplied Dockerfiles and compose file.
- Bedrock-backed Strands agent with session runtime binding and memory-aware tools.

### Out-of-Scope

- External customer usage or internet-exposed anonymous access.
- Formal workflow management, task tracking, or action ownership beyond captured ideas.
- Regulated production processing of customer personal data, payment data, or live transactional banking records.
- Enterprise identity federation, role-based entitlements, or record management integration not present in the current codebase.
- Long-term analytical reporting, MI dashboards, or enterprise search across other ARIA components.

### Service Boundaries

The frontend is responsible for user interaction, session selection, voice controls, audit log display, and rendering of streamed assistant output. The backend is responsible for persistence, safety checks, Bedrock invocation, runtime tool binding, and tokenised streaming over the WebSocket channel.

The SQLite database is a service-owned persistence layer and should be treated as the authoritative store for session content and memory state within this component. Amazon Bedrock is the external inference dependency, while the linked AgentCore gateway is treated as an integration dependency where Lambda-accessible tools are required by the broader ARIA platform landscape.

The service boundary ends at the application and its persistence store. Any onward distribution of generated content into Jira, Confluence, SharePoint, or formal design repositories must be handled by adjacent services or manual operational processes.

## Technical Architecture

### Overview

Brainstorming Agent follows a compact full-stack pattern suited to internal tooling. The browser UI is delivered by a React application, proxied by Vite or a Docker front-end container, and communicates with the backend using relative `/api` calls plus `/ws` WebSocket traffic.

The backend initialises a FastAPI application with a lifespan hook that creates the SQLite schema, sets the active database path, and exposes endpoints for session and memory management. The WebSocket handler accepts a session identifier, records audit events, invokes the Strands agent in a thread, streams tool events while work is in progress, performs output safety analysis, then returns token chunks followed by a `done` event.

Persistence is implemented in `memory_store.py` using tables for `sessions`, `memories`, `memory_links`, and `audit_log`, plus an FTS5 virtual table and triggers to keep search content in sync. This gives the service a lightweight but useful knowledge graph and searchable memory layer without introducing separate database infrastructure.

### Component Diagram in text/ASCII

```text
+------------------------------+
| Internal User Browser        |
| React UI, Tailwind, Voice UI |
+--------------+---------------+
               |
               | HTTPS / WebSocket
               v
+------------------------------+
| Frontend Container or Vite   |
| /api proxy and /ws proxy     |
+--------------+---------------+
               |
               | HTTP on 8200 and WS on 8200
               v
+------------------------------+
| FastAPI Application          |
| sessions, memories, audit    |
| websocket orchestration      |
+------+-------------+---------+
       |             |
       |             |
       v             v
+-------------+   +----------------------+
| SQLite DB   |   | Strands Agent        |
| sessions    |   | runtime-bound tools  |
| memories    |   | Bedrock model        |
| audit log   |   | response generation  |
+------+------+   +----------+-----------+
       |                        |
       | FTS5 search            | HTTPS AWS SDK
       v                        v
+-------------+        +-------------------------+
| Memory      |        | Amazon Bedrock          |
| retrieval   |        | Claude Sonnet 4.6       |
+-------------+        +-------------------------+
                                |
                                | platform linkage
                                v
                     +----------------------------+
                     | AgentCore Gateway          |
                     | Lambda tool access         |
                     +----------------------------+
```

### Technology Stack

| Layer | Technology | Detail |
| --- | --- | --- |
| Frontend framework | React 18 | User workspace, chat panel, memory browser, audit log, session manager |
| Frontend build | Vite 6 | Local dev server on port 5175, proxy to backend and WebSocket routes |
| UI styling | Tailwind CSS 3 | Dark-slate internal workspace styling |
| Icons | lucide-react | Lightweight iconography for voice, memory, audit, and session panels |
| Backend framework | FastAPI | REST endpoints and WebSocket orchestration |
| Validation | Pydantic 2 | Session and summary request models |
| Agent runtime | Strands | Tool-enabled Bedrock agent runtime |
| Model provider | Amazon Bedrock | Default model `eu.anthropic.claude-sonnet-4-6` |
| Persistence | SQLite | File-based store at `agent/data/brainstorm.db` by default |
| Search | SQLite FTS5 | Full-text search across memory title, content, topics, and tags |
| Containerisation | Docker Compose | Frontend and backend containers with health checks and persistent volume |

### Integration Points

| Integration | Protocol | Purpose |
| --- | --- | --- |
| Frontend to backend REST | HTTP | Create sessions, list sessions, fetch memories, fetch audit, update summaries |
| Frontend to backend streaming | WebSocket | Stream assistant tokens, tool status, safety events, and keepalives |
| Backend to SQLite | Local file I/O | Persist sessions, memories, links, FTS index, and audit records |
| Backend to Amazon Bedrock | AWS SDK over HTTPS | Generate brainstorming responses and format agent output |
| Browser to Web Speech API | Native browser API | Local speech recognition and text-to-speech without separate speech service |
| Brainstorming Agent to AgentCore gateway | AWS internal integration | Optional extended tool access for ARIA Lambda usage |

The architecture is intentionally simple, which is appropriate for a supporting internal service. The main technical constraint is that SQLite remains a single-file database, so scale and high-availability expectations must be aligned to internal workshop usage rather than enterprise-grade multi-writer throughput.

## Service Interfaces

### APIs/Contracts

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Returns service status, active model identifier, and database connectivity state |
| POST | `/sessions` | Creates a new brainstorming session with title and optional topics |
| GET | `/sessions` | Lists recent sessions from SQLite |
| GET | `/sessions/{session_id}/memories` | Returns memories attached to a given session |
| GET | `/sessions/{session_id}/audit` | Returns audit entries for a session, up to a configurable limit |
| GET | `/memories/search` | Executes FTS-backed memory search by query string |
| GET | `/memories/{memory_id}/links` | Returns linked or related ideas for a memory |
| POST | `/sessions/{session_id}/summary` | Persists an updated session summary |

### Event/Message Interfaces

| Channel | Event Type | Meaning |
| --- | --- | --- |
| WebSocket | `ping` | Keepalive message every 30 seconds to prevent proxy timeout |
| WebSocket | `token` | Incremental response chunk sent to the browser during final rendering |
| WebSocket | `done` | Final assembled response sent at end of processing |
| WebSocket | `tool` | Tool lifecycle update such as running, done, or error |
| WebSocket | `memory_saved` | Notification that a new memory record has been created |
| WebSocket | `safety_analysis` | Drift and bias scores computed after the final response |
| WebSocket | `safety_blocked` | Input rejection notice where harmful or prompt-injection content is detected |
| WebSocket | `error` | Runtime or application error returned to the client |

### UI Interfaces

The user interface is organised into a left-hand session manager, a central chat panel, and a right-hand tabbed pane for memories and audit. The chat panel keeps recent messages in browser local storage keyed by session, reconnects WebSockets with backoff, renders markdown-like content, and shows live tool labels such as saving memory or searching memories.

The memory browser provides search, topic filtering, and expansion of linked ideas, while the audit log provides a transparent chronology of user input, assistant output, safety analysis, tool calls, tool results, and blocked content. This is particularly useful for service management because it allows support teams to diagnose user experience, model behaviour, and safety rule hits without replaying the full session.

Voice functionality is implemented purely in the browser using `SpeechRecognition` or `webkitSpeechRecognition` and `speechSynthesis`. The browser must therefore support the Web Speech API, with Chrome and Edge explicitly recommended in the README, and microphone consent is managed by the browser rather than the backend service.

## Service Dependencies

### Internal Dependencies

- `brainstorming-agent/agent/main.py` for FastAPI lifecycle, API routes, and WebSocket orchestration.
- `brainstorming-agent/agent/strands_agent.py` for system prompt definition, tool registration, and Bedrock model binding.
- `brainstorming-agent/agent/memory_store.py` for SQLite schema, FTS5 triggers, and audit persistence.
- `brainstorming-agent/agent/safety.py` for regex-based harmful-content blocking, bias analysis, and topic drift scoring.
- `brainstorming-agent/frontend/src` components for session management, chat, memory browsing, audit display, and voice control.
- `brainstorming-agent/docker` assets for container build, proxying, and volume-backed persistence.

### External Dependencies

| Dependency | Type | Dependency Nature | Operational Note |
| --- | --- | --- | --- |
| Amazon Bedrock | AWS managed service | Mandatory for agent response generation | Requires valid AWS credentials and permitted model access |
| Claude Sonnet model | Foundation model | Mandatory inference dependency | Default model is `eu.anthropic.claude-sonnet-4-6` |
| SQLite runtime | Embedded data store | Mandatory local persistence component | Single-writer characteristics limit horizontal scale |
| Browser Web Speech API | Browser capability | Optional UX enhancement | Service degrades gracefully if unsupported |
| AgentCore gateway | ARIA platform integration | Optional extended tool access | Must be controlled through approved internal gateway configuration |
| Docker engine | Local platform dependency | Optional deployment convenience | Required for documented Docker startup path |

The dependency profile is deliberately light, which improves service portability. The most material operational dependency remains Bedrock availability and AWS credential correctness; without these, the service can start but cannot deliver meaningful agent responses.

## Service Level Objectives

| SLO Dimension | Target | Notes |
| --- | --- | --- |
| Availability | 99.5 percent monthly during agreed support hours | Appropriate for a Tier 3 internal productivity service |
| Session and memory API latency | 95th percentile below 750 ms | Applies to SQLite-backed read and write endpoints excluding model inference |
| First visible response after user submit | 95th percentile below 4 seconds | Includes Bedrock invocation plus orchestration overhead |
| Streaming completion for standard prompts | 95th percentile below 20 seconds | Assumes normal prompt size and available Bedrock capacity |
| Concurrent active workshop sessions | 25 concurrent sessions per single backend instance | Practical target based on SQLite and WebSocket design |
| Recovery Time Objective | 8 hours | For controlled internal production deployment |
| Recovery Point Objective | 24 hours | Assumes scheduled backup of SQLite volume |

These objectives are design targets rather than observed production metrics at this draft stage. Formal service reporting should commence only once the component has been deployed into a managed environment with central logging, synthetic checks, and backup procedures.

## Operational Model

### Support Tiers L1/L2/L3

| Tier | Team | Responsibility | Typical Activities |
| --- | --- | --- | --- |
| L1 | Internal service desk or enablement support | First-line triage and user communication | Confirm service reachability, browser compatibility, and known issue patterns |
| L2 | ARIA platform operations | Application support and environment remediation | Review logs, restart containers, validate health endpoint, check AWS credentials and Bedrock access |
| L3 | Product engineering and architecture | Code-level diagnosis and fixes | Resolve defects in safety logic, memory persistence, streaming orchestration, and frontend behaviour |

### On-Call Model

As a Tier 3 supporting service, the recommended operating model is business-hours support with best-efforts out-of-hours response for planned innovation events or senior stakeholder workshops. A 24x7 rota is not justified unless the service becomes embedded in a wider mandatory delivery process.

Operational ownership should sit with the ARIA platform team, with a named product owner for roadmap and usage governance, and a named technical owner for runtime, dependencies, and release management. Escalation to AWS platform support is only required where Bedrock access, credential propagation, or wider AWS service health is implicated.

### Incident Classification

| Severity | Definition | Example |
| --- | --- | --- |
| Sev 1 | Service unavailable for all users during a critical internal event | Backend down, WebSocket unavailable, or corrupted SQLite file preventing startup |
| Sev 2 | Major degradation affecting core user journeys | Session creation works but agent responses fail because Bedrock access is broken |
| Sev 3 | Partial feature loss with workaround available | Voice support unavailable in browser, or memory link retrieval failing |
| Sev 4 | Cosmetic or low-impact issue | Styling defect, wording issue, or minor audit display inconsistency |

## Security & Compliance

### Security Classification

| Control Area | Position |
| --- | --- |
| Security Classification | Internal |
| Intended Data Profile | Internal ideation material, product concepts, engineering notes, architecture options |
| Prohibited Data Profile | Unredacted customer data, cardholder data, secrets, credentials, and special category personal data |
| Recommended Hosting Zone | Internal trusted network segment or managed corporate cloud account |

### AuthN/AuthZ

The current codebase does not implement application-layer user authentication or role-based access control. FastAPI CORS is configured with `allow_origins="*"`, which is acceptable only for tightly controlled internal deployment patterns and should not be carried into wider enterprise exposure without front-door identity controls.

Authentication to Bedrock is performed through AWS credentials present in the runtime environment or mounted profile configuration. This secures access to the model provider, but it does not identify end users inside the application itself; accordingly, access management should be enforced upstream through corporate reverse proxy, private network routing, or platform entry controls.

### Data Classification

Session data, memory content, and summaries should be treated as internal working material that may include commercially sensitive delivery thinking, target-state architecture, product hypotheses, and control discussions. Because workshop participants may type or dictate incidental personal data, the service should be operated on the principle of data minimisation and should not be approved for storage of production customer information.

The audit trail improves accountability but also means that prompts, blocked content snippets, and model responses persist in SQLite. Retention and purge standards should therefore be defined before production onboarding, including expectations for backup retention, deletion on request, and controlled access to the database file.

### Regulatory Requirements

| Requirement Area | Applicability | Service Position |
| --- | --- | --- |
| UK GDPR and Data Protection Act 2018 | Applicable where personal data is entered | Operate with internal-only usage policy and avoid customer data capture |
| FCA and PRA operational resilience | Applicable for managed internal services | Document ownership, recovery targets, and change control before broad adoption |
| ISO 27001 control alignment | Applicable through enterprise policy | Requires access control, logging, backup, vulnerability management, and secure deployment |
| AI governance and model risk | Applicable to AI-assisted internal decision support | Maintain transparent prompts, audit logs, and known limitations in training material |

## Capacity & Scalability

### Current Capacity

| Capacity Area | Current Design Position |
| --- | --- |
| Frontend sessions | Stateless browser clients, scalable through standard web hosting patterns |
| Backend workers | Single FastAPI process unless container scaling is introduced |
| Persistence | Single SQLite database file with WAL and file-locking constraints |
| Search | SQLite FTS5 suitable for modest internal datasets |
| Streaming | WebSocket per active session with token-chunk emission |
| Voice processing | Per-browser local capability, not server-scaled |

The current service is well suited to tens of active users and moderate data growth. It is not yet engineered for heavy concurrent writes, geographically distributed access, or strict high-availability operation because SQLite remains the persistence anchor and the WebSocket flow is held in a single application instance.

### Scaling Approach

If usage expands materially, the preferred scaling path is to keep the frontend stateless, separate the backend from file-based storage, and replace SQLite with a managed data service capable of concurrent writes and durable backup. Memory search could then be migrated either to a managed relational service with full-text capability or to a platform search component if cross-service knowledge retrieval becomes a requirement.

A second scaling step would be to externalise audit telemetry into central observability tooling and to manage WebSocket fan-out through a load-balancing or event-driven pattern. That work is not required for pilot or early internal production, but it should be a planned roadmap item if the service moves from workshop support into broad enterprise usage.

### Known Limits

- SQLite remains a practical upper bound for concurrent write throughput.
- Browser voice depends on Web Speech API availability and microphone permission.
- The service currently relies on upstream controls for user authentication.
- Bedrock model latency directly affects perceived responsiveness.
- Docker-compose deployment is convenient but not a substitute for managed production operations.

## Monitoring & Observability

### Key Metrics

| Metric | Source | Operational Use |
| --- | --- | --- |
| Health status | `/health` endpoint | Confirms app startup, Bedrock model identifier, and DB connectivity |
| WebSocket connection state | Frontend chat panel | Shows connection quality and reconnection behaviour |
| Memory save count | Audit events and memory tables | Indicates whether sessions are producing reusable knowledge |
| Search result volume | Memory search endpoint | Highlights relevance and growth of stored knowledge |
| Safety block frequency | `content_blocked` audit entries | Detects misuse, prompt injection attempts, or policy false positives |
| Drift and bias scores | `safety_analysis` audit entries | Reveals response quality patterns and prompt tuning needs |
| Latency per agent call | Audit event latency field | Provides a simple performance baseline for Bedrock-backed responses |

### Logging Strategy

The service already contains a useful local observability baseline because every user message, assistant response, tool call, tool result, blocked content event, safety analysis event, and runtime error is written into the SQLite `audit_log` table. This is stronger than relying solely on process logs because it preserves session context and user-visible impact.

Container-level health checks are defined in Docker Compose for the backend, and the frontend can surface service degradation through WebSocket state and audit refresh behaviour. For production deployment, these local signals should be supplemented by central log forwarding, synthetic health probes, backup monitoring, and periodic database integrity checks.

### Alerting Thresholds

| Alert | Threshold | Response |
| --- | --- | --- |
| Health endpoint failure | Two consecutive failures | Restart container and investigate DB path or AWS credentials |
| Bedrock response latency | Sustained p95 above 10 seconds | Review AWS region, credential path, and model availability |
| SQLite write failure | Any occurrence | Escalate to L2 immediately, check file system and volume state |
| Safety block spike | More than 10 blocked requests in one hour | Review misuse patterns or over-sensitive regex rules |
| WebSocket disconnect rate | More than 5 percent of active sessions | Review proxy, keepalive behaviour, and browser compatibility |

### Dashboards

Operational dashboards should at minimum cover health status, request volume, average response latency, safety events, and database backup status. The in-product audit panel is useful for user-level diagnostics, but it is not sufficient on its own for enterprise service operations.

## Disaster Recovery & Business Continuity

### DR Strategy

The minimum viable DR approach is image-based redeployment plus restoration of the SQLite database from the most recent controlled backup. Because the frontend is stateless and the backend schema is recreated automatically on startup, the main recovery concern is preservation of session and memory content stored in `brainstorm.db`.

Where the service is hosted in Docker, the persistent volume `brainstorm_data` must be included in the backup regime. Recovery procedures should include container rebuild, environment variable restoration, database integrity validation, and smoke testing of `/health`, session creation, memory retrieval, and WebSocket streaming.

### RTO/RPO Targets

| Measure | Target |
| --- | --- |
| RTO | 8 hours |
| RPO | 24 hours |
| Backup Frequency | Daily minimum, with pre-release backup before planned change |
| Recovery Validation | Quarterly restore test or after any material platform change |

### Failover Approach

There is no native multi-region or active-active failover in the current component design. Service continuity is therefore procedural: rebuild the containerised application, restore the SQLite volume, validate Bedrock access, and return the service to operation.

If business dependency increases, continuity should be strengthened by moving persistence to a managed multi-AZ platform service and deploying the application behind resilient internal ingress. Until then, the declared DR posture should remain proportionate to Tier 3 supporting service expectations.

## Service Transition Plan

### Transition Phases

| Phase | Objective | Key Activities | Exit Criteria |
| --- | --- | --- | --- |
| Design finalisation | Confirm service model and controls | Review this SID, confirm owner, support model, and data handling policy | Architecture, security, and operations sign-off complete |
| Build verification | Validate component readiness | Run frontend build and backend compile checks, inspect Docker health checks | `npm run build` passes in frontend and `python3 -m compileall .` passes in backend |
| Controlled pilot | Introduce to limited users | Onboard a small engineering and product cohort, collect UX and safety feedback | Pilot users confirm usefulness and no material security concerns are raised |
| Production onboarding | Move into managed internal service operation | Implement backup, monitoring, support rota, and release control | Support documentation and runbooks are in place |
| Continuous improvement | Tune quality and controls | Refine prompt, safety rules, memory strategy, and observability | Monthly governance review established |

### Acceptance Criteria

- Frontend build completes successfully using the documented `npm run build` command.
- Backend source compiles successfully using `python3 -m compileall .` from the backend directory.
- `/health` returns status `ok`, model identifier, and database state.
- Session creation, memory retrieval, and summary update flows succeed end to end.
- WebSocket streaming delivers `token`, `done`, and safety events without proxy interruption.
- Safety blocking and audit event capture are demonstrated in a non-production test scenario.
- Backup and restore procedure for the SQLite volume is documented and rehearsed.

### Go-Live Checklist

- Confirm named owner, support team, and escalation route.
- Confirm AWS credentials and Bedrock model access in the target account and region.
- Confirm database backup schedule for the persistent volume.
- Confirm reverse proxy or internal access control pattern for user authentication.
- Confirm browser support guidance for voice usage.
- Confirm release notes and rollback approach for the initial managed deployment.
- Confirm monitoring, alert routing, and incident logging destination.

## Training & Knowledge Transfer

Training should focus on two audiences. End users need concise guidance on when to use the service, how to create high-quality prompts, how to treat saved memories, and what information must not be entered. Support teams need technical runbooks covering health checks, SQLite location, Bedrock dependency checks, WebSocket behaviour, and known browser limitations.

A short enablement pack should include a live demonstration, a one-page internal user guide, a troubleshooting note for voice support, and an explanation of the audit log. This is especially important in a banking environment because transparency and appropriate use are as important as feature capability.

| Knowledge Transfer Item | Audience | Outcome |
| --- | --- | --- |
| User quick-start session | Engineers and product managers | Users can create sessions, use memory search, and understand voice limitations |
| Operational handover | L1 and L2 support | Support teams can diagnose health, DB, and connectivity issues |
| Architecture walkthrough | L3 engineering and architects | Technical owners understand runtime binding, safety logic, and persistence model |
| Governance briefing | Security and data governance | Control owners understand intended usage boundaries and retention expectations |

## Risk Register

| ID | Risk | Category | Probability | Impact | Mitigation | Owner | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BSA-01 | SQLite file contention or corruption under higher-than-expected concurrent usage causes session write failures. | Technology | Medium | Medium | Limit initial rollout, back up the volume, and plan migration to managed persistence if concurrency grows. | [OWNER_NAME] | Open |
| BSA-02 | Lack of native application authentication allows inappropriate access if deployed beyond an internal trusted boundary. | Security | Medium | High | Enforce upstream identity, restrict network exposure, and harden CORS before broader rollout. | [OWNER_NAME] | Open |
| BSA-03 | Users may enter customer or sensitive regulated information into a workspace intended for internal ideation. | Compliance | Medium | High | Publish clear acceptable-use guidance, add training, and review retention and deletion controls. | [OWNER_NAME] | Open |
| BSA-04 | Regex-based safety rules may over-block benign prompts or miss edge-case harmful content. | AI Risk | Medium | Medium | Monitor `content_blocked` and safety-analysis trends, tune rules, and retain manual review path. | [OWNER_NAME] | Open |
| BSA-05 | Bedrock latency or access issues degrade the workshop experience during important design sessions. | Supplier / Cloud | Medium | Medium | Validate AWS credentials pre-session, monitor latency, and keep a manual facilitation fallback. | [OWNER_NAME] | Open |

## Approvals

| Role | Name | Signature | Date |
| --- | --- | --- | --- |
| Service Owner | [NAME] | Pending | [DATE] |
| Enterprise Architect | [NAME] | Pending | [DATE] |
| Security Architect | [NAME] | Pending | [DATE] |
| Service Operations Manager | [NAME] | Pending | [DATE] |
| Product Sponsor | [NAME] | Pending | [DATE] |
