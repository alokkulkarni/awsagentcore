# Connect Analytics Agent Service Introduction Document

## Document Control

| Field | Value |
| --- | --- |
| SID ID | SID-CAA-001 |
| Version | 1.0.0 |
| Status | Draft |
| Classification | Internal |
| Owner | ARIA Contact Centre Analytics Product Lead — [OWNER_NAME] |
| Reviewers | Enterprise Architecture — [REVIEWER_NAME]; Contact Centre Technology — [REVIEWER_NAME]; Security Architecture — [REVIEWER_NAME]; Service Operations — [REVIEWER_NAME] |
| Service Name | Connect Analytics Agent |
| Business Unit | Operations / Contact Centre Management |
| Service Tier | Tier 2 (Business Important) |
| Service Type | Analytics & Reporting Platform |
| Category | Contact Centre Analytics / AI-Assisted Reporting |
| Initial Publication Date | [DATE] |
| Next Review Date | [DATE] |

| Revision | Date | Author | Summary |
| --- | --- | --- | --- |
| 0.1 | [DATE] | [OWNER_NAME] | Initial draft based on reference architecture, deployment scripts, and source code inspection. |
| 0.9 | [DATE] | [OWNER_NAME] | Added cloud deployment, security posture, and operational support model. |
| 1.0.0 | [DATE] | [OWNER_NAME] | Issued for architecture, operations, and security review. |

## Executive Summary

Connect Analytics Agent is an ARIA platform service that combines Amazon Connect analytics APIs, AWS AgentCore Gateway, Strands-based Bedrock reasoning, and a React 18 dashboard to deliver conversational and visual insight into contact-centre operations. It enables supervisors and operations managers to ask natural-language questions such as how many agents are busy, who is most occupied, or which contacts mention a specific issue, while also navigating purpose-built dashboard views for real-time operations, historical analytics, contact search, transcript review, and flow-funnel analysis.

The component is more than a demonstration chatbot. It provides operational APIs for metrics, session persistence, transcript access, live-contact monitoring, startup resource discovery, proactive alerting, and supervisor monitoring or barge-in workflows. It integrates with nine gateway-registered Lambda tools, maintains chat session history in SQLite locally or DynamoDB and S3 in cloud mode, and exposes the user interface through CloudFront in cloud deployment.

For a UK retail bank, the service is categorised as Tier 2 business-important capability because it informs operational decision-making in the contact centre, improves supervisory response times, and can materially reduce manual reporting effort. It does not replace core telephony or CRM systems, but it becomes operationally significant wherever supervisors use it to manage queues, investigate contact journeys, or assess conversational AI and human-agent performance.

## Service Description

| Attribute | Definition |
| --- | --- |
| Name | Connect Analytics Agent |
| Classification | Full-stack analytics service for Amazon Connect operational insight and supervisory decision support |
| Service Tier | Tier 2 (Business Important) |
| Service Type | Analytics & Reporting Platform |
| Category | Contact Centre Analytics / AI-Assisted Reporting |
| Primary Consumers | Contact centre supervisors, operations managers, MI analysts, contact-centre product owners |
| Primary Outcome | Real-time and historical visibility with AI-assisted query capability |

The service is implemented as a full-stack reference project under `connect-analytics-agent/`. The frontend delivers a multi-screen dashboard with real-time command centre, historical analytics, contact search, flow-funnel analysis, transcript viewer, floating assistant, startup scan visualisation, and supervisor barge-in controls. The backend layer is a FastAPI service for local and Docker operation, with a Lambda-compatible handler available for cloud deployment.

The AI capability is provided by a Strands agent that can either call tools through AgentCore Gateway or fall back to direct Lambda invocation and local tool execution. This approach reduces dependency risk because the analytics experience can continue in several modes: mock mode, local direct tool mode, AgentCore Gateway mode, or a cloud path via API Gateway and Lambda.

The service design also recognises that supervisors need more than a single interaction mode. As well as conversational questions, the product surfaces live alerting, dashboard KPIs, contact journey exploration, transcript summarisation, live bot and callback visibility, and session persistence so that operational teams can move between broad monitoring and case-level drill-down without changing tools.

## Business Context

### Business Drivers

| Driver | Detail |
| --- | --- |
| Faster operational insight | Supervisors need immediate answers on queue depth, wait times, agent states, and contact anomalies without manual report building. |
| Unified telemetry view | Amazon Connect generates data across metrics APIs, CTRs, Contact Lens transcripts, EventBridge events, and recordings; this service unifies them. |
| Better oversight of conversational AI | The service exposes bot-session behaviour, escalation patterns, contact-flow events, and transcript views for quality review. |
| Reduced swivel-chair operations | A single interface replaces repeated movement between Connect console, reports, recordings, and bespoke analyst extracts. |
| Natural-language accessibility | Non-technical supervisors can query operational data using natural language while still retaining structured dashboards. |

### Stakeholders & Personas

| Persona | Need | Service Interaction |
| --- | --- | --- |
| Real-Time Supervisor | Monitor queues, active calls, alerts, and intervention options | Uses the Real-Time Command Centre, proactive alerts, and monitor or barge workflow |
| Operations Manager | Assess staffing, occupancy, and service-level trends | Uses historical dashboards and natural-language analytics queries |
| MI Analyst | Investigate contact outcomes and drill into transcripts | Uses contact search, transcript viewer, and bot metrics views |
| Contact Centre Platform Engineer | Support deployment and tool integration | Uses deploy script, startup scan, gateway configuration, and tool registration flow |
| Security and Governance | Review data handling and access controls | Reviews CloudFront, Cognito, API posture, transcript access, and logging controls |

### Business Value Metrics

| Metric | Measurement Intent | Indicative Target |
| --- | --- | --- |
| Time to operational answer | Time from question to actionable insight for supervisors | Less than 2 minutes for standard queries |
| Queue anomaly response time | Time between critical condition and supervisory action | 30 percent faster than current manual detection |
| Manual report reduction | Reduction in ad hoc analyst report requests | 20 percent reduction after stabilisation |
| Search effectiveness | Percentage of contact searches resolved without separate system lookup | Greater than 80 percent |
| AI recommendation uptake | Frequency with which proactive alert recommendations are used | Monitor trend during pilot and governance review |
| Contact investigation efficiency | Time to retrieve transcript, recording, and flow context for a live issue | Less than 5 minutes end to end |

The strategic value is especially strong in a banking contact centre where queue pressure, call duration, abandoned contacts, and bot escalation rates can affect customer outcomes, colleague productivity, and reputational risk. The service provides a modern supervisory layer over operational data without requiring each user to understand the underlying API landscape.

Because the service can expose transcript and recording artefacts, it sits closer to regulated operational data than a generic internal productivity tool. That is why the operating model, controls, and transition planning in this SID are framed to Tier 2 business-important expectations rather than a lightweight experiment posture.

## Service Scope

### In-Scope

- React 18 dashboard for real-time, historical, contact-search, and flow-funnel analytics.
- Natural-language querying through a Strands Bedrock agent.
- Nine gateway-defined Lambda analytics tools registered in `tool-schemas.json`.
- Local mock mode and local direct-tool mode for development and demonstration.
- Cloud deployment via `deploy.sh` including Lambda, AgentCore, API Gateway, Cognito, S3, and CloudFront.
- Session persistence via SQLite locally or DynamoDB and optional S3 in cloud mode.
- Contact transcript retrieval, recording link generation, keyword search, and contact-flow journey inspection.
- EventBridge and SQS-backed live contact listener for inbound, outbound, callback, transfer, and bot-session visibility.
- Supervisor monitoring and barge-in support through Connect Streams and MonitorContact APIs.
- Startup resource discovery with SSE progress streaming and cached discovery state.

### Out-of-Scope

- Replacement of Amazon Connect CCP as the primary agent desktop.
- Core telephony routing, IVR design, or CRM case-management functions.
- Customer identity verification or decisioning beyond operational analytics.
- Formal regulatory record management for transcripts and recordings beyond underlying platform controls.
- Enterprise data warehouse or board-level MI production.
- Automatic remediation of operational incidents without supervisor review.

### Service Boundaries

The service boundary includes the browser dashboard, the analytics API layer, the Bedrock agent, session persistence, live-contact listener, deployment automation, and Lambda tool invocation mechanisms. It also includes the controlled user journey from CloudFront to API endpoints in cloud deployment and from Vite to FastAPI in local deployment.

The boundary does not extend into Amazon Connect itself, the underlying Lambda tool implementation logic outside the documented contracts, or enterprise identity and network controls beyond what the deployment scripts provision. Recordings, transcripts, and contact traces remain source-system artefacts owned by Amazon Connect and associated AWS storage services.

Any new Lambda tool added to the service must be registered in three places to remain in scope: `agent/agent_core.py`, `deploy.sh` tool maps, and `infrastructure/gateway/tool-schemas.json`. This registration discipline is an explicit architectural boundary and should be treated as a release-governance control.

## Technical Architecture

### Overview

Connect Analytics Agent uses a layered architecture with a static web front end, an analytics API and AI orchestration layer, and several AWS data and integration services. In local mode, the frontend runs on Vite port 5274 and proxies `/api` requests to a FastAPI service on port 8100. In cloud mode, the frontend is built and published to S3 behind CloudFront, while analytics requests are routed through API Gateway into Lambda.

The agent layer is implemented in `agent_core.py`. It maintains session history in memory for conversational continuity, signs requests to AgentCore Gateway using SigV4 when a gateway endpoint is configured, and can invoke tool Lambdas directly or execute local tool handlers from the mounted `tools/` directory. The Strands agent is created with Bedrock model support and a system prompt focused on operational contact-centre analytics.

The operational analytics plane is broader than the conversational plane. `local_server.py` exposes APIs for health, configuration, realtime metrics, historical metrics, contact search, transcripts, recordings, sessions, startup scan status, live contact views, and supervisor workflows. `eventbridge_listener.py` maintains an in-memory model of live contacts from an SQS queue fed by EventBridge, while `startup_scan.py` performs leader-elected AWS resource discovery and streams progress via server-sent events.

### Component Diagram in text/ASCII

```text
+------------------------------+
| Supervisor or Ops Browser    |
| React dashboard and AI chat  |
+--------------+---------------+
               |
               | HTTPS
               v
+------------------------------+
| CloudFront and S3 Frontend   |
| or local Vite proxy          |
+--------------+---------------+
               |
               | /api requests
               v
+------------------------------+
| API Gateway or FastAPI API   |
| health, metrics, search      |
| sessions, transcripts        |
+--------+-------------+-------+
         |             |
         |             |
         v             v
+----------------+   +----------------------+
| Strands Agent  |   | Operational API      |
| Bedrock model  |   | FastAPI and Lambda   |
| query routing  |   | metrics and sessions |
+--------+-------+   +-----------+----------+
         |                       |
         | SigV4 or direct       | reads and writes
         v                       v
+----------------------+   +----------------------+
| AgentCore Gateway    |   | Session Store        |
| tool invocation      |   | SQLite or DynamoDB   |
+----------+-----------+   | and optional S3      |
           |               +----------------------+
           |
           v
+------------------------------+
| Analytics Tool Lambdas       |
| metrics, search, transcript  |
| recording, flow events       |
+----------+-------------------+
           |
           v
+------------------------------------------------+
| Amazon Connect APIs, Contact Lens, S3,         |
| EventBridge, SQS, recordings, transcript data  |
+------------------------------------------------+
```

### Technology Stack

| Layer | Technology | Detail |
| --- | --- | --- |
| Frontend framework | React 18 | Dashboard screens, transcript viewer, floating assistant, startup scan, supervisor controls |
| Frontend build | Vite 7 | Dev server on port 5274 with `/api` proxy support |
| Frontend libraries | axios, recharts, react-markdown, xyflow, amazon-connect-streams | API access, charting, markdown rendering, flow visualisation, Connect CCP integration |
| Styling | Tailwind CSS 3 | Enterprise dashboard styling |
| Backend framework | FastAPI | Local operational API and SSE endpoints |
| Cloud entrypoint | Lambda handler | API Gateway-compatible runtime for cloud deployment |
| Agent runtime | Strands | Bedrock-backed reasoning with tool orchestration |
| Model provider | Amazon Bedrock | Deploy-time default `us.anthropic.claude-sonnet-4-5`; runtime includes additional candidate fallbacks |
| Tool integration | AgentCore Gateway and direct Lambda | SigV4-signed gateway access with direct fallback patterns |
| Session persistence | SQLite or DynamoDB and S3 | SQLite locally, DynamoDB in cloud, S3 for large session payloads over 300 KB |
| Real-time event ingestion | EventBridge and SQS | Live contact updates consumed into an in-memory registry |
| Frontend delivery | S3 and CloudFront | Static hosting and secure edge delivery for cloud mode |

### Integration Points

| Integration | Protocol | Purpose |
| --- | --- | --- |
| Frontend to analytics API | HTTPS | Retrieves metrics, contacts, sessions, transcripts, startup-scan state, and alerts |
| Frontend to startup scan | Server-sent events | Streams discovery progress from `/startup-scan/stream` |
| Frontend to Connect Streams | Browser JavaScript SDK | Receives CCP state, live contact events, monitoring and barge controls |
| Agent to AgentCore Gateway | HTTPS with SigV4 | Invokes tool contracts through AWS AgentCore Gateway |
| Agent to tool Lambdas | Lambda invoke API | Direct fallback where gateway is absent or not available |
| Tool Lambdas to Amazon Connect | AWS SDK | Fetch real-time metrics, historical metrics, contact records, transcripts, and recordings |
| EventBridge to SQS to listener | AWS event delivery | Maintains live contact state for dashboards and alerts |
| Session store to DynamoDB and S3 | AWS SDK | Durable conversation history in cloud mode |

The most important architectural decision is the availability of multiple operational modes. Mock mode supports demonstrations, local direct-tool mode supports development against mounted handler code, and gateway mode supports a more platform-aligned production architecture. This flexibility improves resilience but introduces configuration complexity that must be controlled in release and support processes.

## Service Interfaces

### APIs/Contracts

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Reports service mode, mock state, local tool availability, gateway configuration, and Connect configuration state |
| GET | `/config` | Returns resolved runtime configuration and discovered storage information |
| GET | `/metrics` | Returns queue and agent totals including online, available, on-call, ACW, and contacts in queue |
| GET | `/historical-metrics` | Returns time-based performance analytics |
| GET | `/historical-breakdown` | Returns grouped historical analytics by queue, routing profile, or agent |
| GET | `/agent-states` | Returns current agent roster and state details |
| GET | `/contacts` | Search endpoint for CTR-style contact filtering including custom attributes |
| GET | `/transcript/{contact_id}` | Retrieves transcript content for a specific contact |
| GET | `/recording/{contact_id}` | Returns recording information or link generation details |
| GET | `/contact-flow-events` | Retrieves contact flow journey data for a specific contact |
| POST | `/query` | Natural-language question endpoint for the AI assistant |
| GET | `/sessions` | Lists persisted chat sessions |
| GET | `/sessions/{session_id}` | Retrieves full session with messages |
| PUT | `/sessions/{session_id}` | Upserts a session to the configured session store |
| GET | `/startup-scan/stream` | Streams startup discovery progress via SSE |
| GET | `/live-contacts` | Returns currently active and recently-ended contacts from the listener |
| POST | `/contacts/{contact_id}/monitor` | Initiates supervisor monitoring with optional barge capability |
| DELETE | `/contacts/{contact_id}/monitor` | Stops the active monitoring path, usually via Streams-based disconnect |
| GET | `/config/streams` | Returns CCP alias and listener readiness for Connect Streams integration |

### Event/Message Interfaces

| Channel | Event or Message | Meaning |
| --- | --- | --- |
| SSE | `phase_start` | Startup scan begins a discovery phase |
| SSE | `phase_complete` | Startup scan completes a phase and updates totals |
| SSE | `scan_complete` | Discovery finished and cached resources are ready |
| EventBridge | `Amazon Connect Contact Event` | Source event for live contact tracking |
| SQS queue | Contact event payload | Buffered transport to the listener thread |
| Connect Streams | Contact refresh and monitoring state events | Real-time browser-side operational state without server polling |
| AgentCore request | Tool schema contract | Request containing action group, function, and parameters |
| AI chat response | Session id and markdown text | Conversational answer returned by `/query` |

### UI Interfaces

The dashboard is organised into four primary navigation screens: Real-Time Command Centre, Historical Analytics, Contact Search, and Flow Funnel. A floating AI assistant remains available across screens and can be prefilled by proactive alerts or dashboard actions so that a supervisor can pivot immediately from a metric anomaly into guided reasoning.

The Real-Time Command Centre combines live queue conditions, contact activity, proactive alerting, and supervisor intervention actions. Historical views surface occupancy, handle time, abandonment, and other metrics. Contact Search supports rich filters for time ranges, statuses, channels, initiation methods, queues, agents, phone numbers, and custom attributes encoded as searchable key-value filters.

The UI also includes a transcript modal, bot metrics dashboard, contact-flow visualisation, startup-scan overlay, and the `useConnectStreams` integration that opens a hidden CCP iframe for Amazon Connect event observation. This is a significant differentiator because it gives browser-side awareness of contact and monitoring state without relying purely on server polling.

## Service Dependencies

### Internal Dependencies

- `connect-analytics-agent/agent/agent_core.py` for Strands agent creation, tool-routing logic, Bedrock formatting, and SigV4 support.
- `connect-analytics-agent/agent/local_server.py` for operational APIs, security headers, rate limiting, session endpoints, and local runtime behaviour.
- `connect-analytics-agent/agent/session_store.py` for SQLite or DynamoDB and S3-backed conversation persistence.
- `connect-analytics-agent/agent/startup_scan.py` for leader-elected AWS resource discovery and SSE publishing.
- `connect-analytics-agent/agent/eventbridge_listener.py` for live contact state maintenance from SQS.
- `connect-analytics-agent/frontend/src` components, hooks, and services for dashboards, proactive alerts, AI chat, and CCP integration.
- `connect-analytics-agent/deploy.sh` for environment creation, tool registration, static site deployment, and teardown.
- `connect-analytics-agent/infrastructure/gateway/tool-schemas.json` as the controlled schema source for gateway tool contracts.

### External Dependencies

| Dependency | Type | Dependency Nature | Operational Note |
| --- | --- | --- | --- |
| Amazon Connect APIs | AWS managed service | Mandatory operational data source | Requires valid instance id and permitted IAM access |
| Amazon Connect Contact Lens | AWS managed service | Required for transcript and conversational insight features | Must be enabled on the Connect instance |
| AgentCore Gateway | AWS managed service | Preferred tool orchestration path | Supports SigV4-authenticated gateway invocation |
| AWS Lambda | AWS managed service | Mandatory execution layer for analytics tools in cloud mode | Tool mappings must stay aligned with schema and deploy script |
| Amazon Bedrock | AWS managed service | Mandatory for conversational reasoning and response formatting | Region and model-access alignment are critical |
| DynamoDB | AWS managed service | Cloud session storage option | Used when `SESSION_BACKEND=dynamodb` |
| Amazon S3 | AWS managed service | Frontend hosting, large session payload storage, transcript and recording artefacts | CloudFront and tool features depend on bucket configuration |
| CloudFront | AWS edge service | Secure frontend delivery in cloud mode | Initial propagation can take several minutes |
| Cognito | AWS managed identity | Frontend sign-in metadata in cloud deployment | Frontend stores JWT and forwards Bearer header |
| EventBridge and SQS | AWS eventing | Live contact event transport | Required for realtime contact activity beyond polling |
| Connect Streams SDK | Browser library | Required for CCP monitoring and barge user experience | Approved origins and alias configuration are mandatory |

The dependency model is richer than that of the Brainstorming Agent because this service sits close to live contact-centre operations. Operational support therefore needs explicit ownership of AWS permissions, Connect configuration, CloudFront publication, and tool-registration hygiene.

## Service Level Objectives

| SLO Dimension | Target | Notes |
| --- | --- | --- |
| Availability | 99.9 percent monthly for cloud deployment | Tier 2 target, excluding planned maintenance |
| Dashboard read API latency | 95th percentile below 2 seconds | Applies to health, config, metrics, queues, agents, and live-contact views |
| Natural-language query response | 95th percentile below 5 seconds for first answer | Subject to Bedrock and tool latency |
| Startup scan cold-start completion | 10 minutes or less | Aligns with current leader timeout and discovery design |
| Proactive alert polling interval | 30 seconds | Implemented in `useProactiveAlerts` |
| API rate limit | 30 calls per 60 seconds per client IP on query endpoint | Implemented in local server memory store |
| Recovery Time Objective | 4 hours | For managed cloud deployment with automation and backup in place |
| Recovery Point Objective | 15 minutes | Assumes cloud session storage and infrastructure state persistence |

These targets apply to the intended managed service form rather than local demo mode. Local mock and Docker modes are useful for development and testing but should not be represented as the production resilience posture.

## Operational Model

### Support Tiers L1/L2/L3

| Tier | Team | Responsibility | Typical Activities |
| --- | --- | --- | --- |
| L1 | Contact centre service desk | First-line user triage and basic issue logging | Confirm dashboard reachability, check login behaviour, collect affected query and screen details |
| L2 | ARIA platform and contact-centre operations support | Application and environment support | Review API health, restart services, inspect listener state, validate AWS credentials, review startup-scan state |
| L3 | Engineering and cloud platform specialists | Deep diagnostics and code change | Fix tool registration issues, Bedrock failures, Connect Streams defects, and deployment automation problems |

### On-Call Model

Because the service informs business-important operations, an on-call model is recommended for core contact-centre support hours, with out-of-hours best-efforts tied to operational dependency on the dashboard. Where the service is used directly by real-time supervisors, on-call cover should include both ARIA platform capability and contact-centre platform knowledge.

Operational responsibilities must be separated clearly. Contact-centre teams own interpretation of metrics and escalation decisions; platform teams own service availability, tool configuration, and cloud runtime; AWS platform teams own cross-account roles, security baselines, and foundational infrastructure. This division avoids ambiguity during live incidents.

### Incident Classification

| Severity | Definition | Example |
| --- | --- | --- |
| Sev 1 | Total loss of supervisory analytics capability during operating hours | CloudFront unavailable, API down, or `/query` and dashboard APIs both failing for all users |
| Sev 2 | Major operational degradation affecting key workflows | Live metrics unavailable, EventBridge listener stopped, or transcript access broadly failing |
| Sev 3 | Feature-specific degradation with workaround available | Startup scan not updating, proactive alerts failing, or monitoring and barge workflow unavailable |
| Sev 4 | Low-impact issue | Styling defect, non-critical chart label error, or minor markdown rendering issue |

## Security & Compliance

### Security Classification

| Control Area | Position |
| --- | --- |
| Security Classification | Internal |
| Data Sensitivity | Operational MI plus potentially sensitive transcript and recording references |
| Intended User Base | Authorised supervisors, operations managers, analysts, and platform teams |
| Hosting Expectation | Managed corporate AWS account with controlled network and identity perimeter |

### AuthN/AuthZ

The frontend API client reads a token from browser local storage under `connect.analytics.jwt`, adds it as a Bearer token, and redirects non-local users to `/login` on HTTP 401 responses. Cloud deployment also provisions Cognito user-pool metadata and publishes frontend configuration values for user pool and client identifiers, which establishes an identity path for the web experience.

Transport security is provided by HTTPS through CloudFront and API Gateway in cloud deployment, while agent-to-gateway calls are signed with SigV4. The local FastAPI service adds security headers including `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, CSP, and conditional HSTS, and restricts allowed origins through environment configuration.

A material control gap remains: the deployment script creates API Gateway methods with `authorization-type NONE`. This means production go-live should be contingent on explicit enforcement of JWT or equivalent authorisation at the API boundary, not merely token forwarding by the frontend. The SID therefore records secure transport as present but authorisation hardening as a mandatory transition action.

### Data Classification

Contact traces, transcripts, customer names in custom attributes, recording references, and queue or agent operational data may all contain personal data or commercially sensitive operational information. The service should therefore be treated as handling internal confidential operational data even though its document classification remains Internal.

Session history is persisted server-side, locally in SQLite or in cloud mode through DynamoDB and optional S3. Because large sessions can be written to S3 when exceeding 300 KB, retention, encryption, access review, and deletion procedures must extend across all configured persistence layers rather than focusing only on the web application.

### Regulatory Requirements

| Requirement Area | Applicability | Service Position |
| --- | --- | --- |
| UK GDPR and Data Protection Act 2018 | Applicable | Contact metadata, transcripts, and custom attributes may contain personal data |
| FCA and PRA operational resilience | Applicable | Service should have named owners, documented recovery targets, and clear support escalation |
| PCI DSS and payment-data controls | Potentially applicable | If transcripts or recordings include payment interactions, downstream masking and exclusion controls are required |
| Call recording and customer transparency requirements | Applicable | Underlying Connect and Contact Lens controls must remain aligned with legal and policy requirements |
| ISO 27001 and enterprise security policy | Applicable | Enforce logging, access control, encryption, vulnerability management, and release control |
| AI governance and model risk | Applicable | Natural-language answers should remain transparent and support human decision-making rather than replace it |

## Capacity & Scalability

### Current Capacity

| Capacity Area | Current Design Position |
| --- | --- |
| Frontend delivery | CloudFront and S3 scale well for static content distribution |
| Query API | Local FastAPI or Lambda-based cloud path depending deployment mode |
| Session store | SQLite locally, DynamoDB in cloud, S3 for large session payloads |
| Query throttling | In-memory rate limit of 30 calls in 60 seconds per client IP on `/query` |
| Session retention | `MAX_SESSIONS` set to 100 in the store abstraction |
| Large-message handling | S3 offload when DynamoDB payload exceeds 300 KB |
| Live contact memory | In-memory active-contact registry with 15-second terminal grace window |

The cloud architecture can scale materially better than the local architecture because CloudFront, API Gateway, Lambda, DynamoDB, S3, EventBridge, and SQS are all managed services. The principal scaling pressure points are Bedrock inference latency, Amazon Connect API throttling, and alignment of tool-invocation capacity with peak supervisory usage.

### Scaling Approach

The preferred production pattern is to run the user interface as a static site behind CloudFront, to host API and agent logic in Lambda or other horizontally scalable compute, and to use DynamoDB and S3 for session durability. This separates web scale from query scale and removes single-host storage constraints present in local Docker mode.

As usage grows, further scaling should focus on caching of low-volatility reference data, back-pressure and retry logic for Connect APIs, and richer central observability. The startup-scan model already uses a leader-lock pattern and cached discovery file, which is a useful mechanism for avoiding redundant API storms during startup, but its current lock-file implementation is still oriented to local shared storage rather than distributed coordination.

### Known Limits

- New tools must be registered consistently in `agent_core.py`, `deploy.sh`, and `tool-schemas.json`, creating drift risk during rapid delivery.
- Connect Streams requires approved origins and a valid `VITE_CONNECT_ALIAS`, otherwise CCP-driven monitoring workflows will fail.
- API query throttling is in-memory in the local server and is not distributed across multiple instances.
- Startup scan is single-region and depends on the permissions available to the running role.
- The production deployment script currently lacks enforced API authorisation despite Cognito provisioning.
- Bedrock model defaults differ between runtime code and deploy-time environment values and must be standardised operationally.

## Monitoring & Observability

### Key Metrics

| Metric | Source | Operational Use |
| --- | --- | --- |
| `agents_online`, `agents_available`, `agents_on_call`, `agents_in_acw` | `/metrics` | Core operational health for staffing and queue recovery |
| `contacts_in_queue`, `oldest_contact_age` | `/metrics` | Queue pressure detection and proactive alerting |
| Live inbound, bot, callback, and outbound counts | `eventbridge_listener` snapshots | Real-time view of contact-state distribution |
| Startup scan progress and discovery totals | `startup_scan` state and SSE | Detects configuration or discovery delays at service boot |
| Query volume and rate-limit hits | `/query` logging and HTTP 429s | Identifies misuse or scaling pressure |
| Session-store errors | Session API exceptions | Indicates persistence failure in SQLite, DynamoDB, or S3 |
| Monitor and barge workflow success | Supervisor panel and monitor endpoint outcomes | Measures supervisory intervention reliability |

### Logging Strategy

The backend uses Python logging and intentionally avoids logging raw query text, logging only query length and session identifier on the `/query` endpoint to reduce exposure of potentially sensitive content. Startup scan and listener components write operational logs, while deploy-time state is captured in `.deploy-state.json` for environment tracking.

Observability is partially embedded in the user experience. The startup scan overlay surfaces discovery progress from SSE, proactive alerts poll metrics every 30 seconds, and the frontend health badge reflects service connectivity. Even so, a managed production service should forward logs to a central platform, capture API response metrics, and raise alerts from infrastructure and application telemetry rather than relying on user-visible cues.

### Alerting Thresholds

| Alert | Threshold | Current Source |
| --- | --- | --- |
| Queue high warning | More than 5 contacts waiting | `useProactiveAlerts` threshold `QUEUE_HIGH_WARN` |
| Queue high critical | 10 or more contacts waiting | `useProactiveAlerts` threshold `QUEUE_HIGH_CRIT` |
| Long wait warning | Oldest wait at least 300 seconds | `useProactiveAlerts` threshold `LONG_WAIT_WARN` |
| Long wait critical | Oldest wait at least 600 seconds | `useProactiveAlerts` threshold `LONG_WAIT_CRIT` |
| Long live call warning | Active inbound call at least 900 seconds | `useProactiveAlerts` threshold `LONG_CALL_WARN` |
| Bot-stuck warning | Bot session at least 600 seconds without escalation | `useProactiveAlerts` threshold `BOT_STUCK_WARN` |
| EventBridge listener not started | Queue URL absent or listener inactive | `local_server.py` config and logs |
| Query rate-limit breach | More than 30 requests in 60 seconds per IP | Local in-memory rate limiter |

### Dashboards

The primary user-facing dashboards are the Real-Time Command Centre, Historical Analytics, Contact Search, Flow Funnel, Bot Metrics, and the Floating Assistant. Support teams should additionally maintain operational dashboards for API health, Lambda errors, SQS age, CloudFront availability, Cognito login errors, and Bedrock invocation latency.

## Disaster Recovery & Business Continuity

### DR Strategy

The production DR strategy relies on redeployability of cloud infrastructure, recoverable configuration state, and durable storage of sessions and artefacts in managed AWS services. `deploy.sh` provisions or updates roles, policies, Lambda functions, API Gateway, Cognito, S3, and CloudFront, which means a controlled rebuild path already exists for most of the stack.

For session continuity, the preferred production posture is `SESSION_BACKEND=dynamodb` with S3 enabled for larger payloads. In that model, frontend content is recoverable from source control and the build pipeline, API and agent logic from deployment automation, and sessions from managed storage. Local SQLite mode should be considered a development convenience only and not part of formal business continuity objectives.

### RTO/RPO Targets

| Measure | Target |
| --- | --- |
| RTO | 4 hours |
| RPO | 15 minutes |
| Recovery Validation | At least quarterly for cloud deployment |
| Minimum Backup Control | Session-store durability plus deploy-state preservation |

### Failover Approach

The current design is single-region and does not implement active-active failover. Nevertheless, several underlying services are multi-AZ by design, including DynamoDB, S3, API Gateway, CloudFront edge delivery, and Lambda execution. Failover at the service level is therefore primarily regional rebuild rather than application-native cross-region switch-over.

If the component becomes operationally relied upon by multiple contact centres or materially impacts customer outcomes, the next resilience step should be codified region-pair recovery, replicated session data, and explicit runbooks for tool Lambda redeployment and Connect integration validation. Until then, a single-region Tier 2 posture with documented rebuild procedures is proportionate.

## Service Transition Plan

### Transition Phases

| Phase | Objective | Key Activities | Exit Criteria |
| --- | --- | --- | --- |
| Design and control review | Confirm target operating model | Review service scope, ownership, transcript-data handling, and API security posture | Architecture and security reviews completed |
| Build verification | Confirm technical readiness | Run frontend build, validate local health, confirm tool schemas and deploy mappings | `cd connect-analytics-agent/frontend && npm run build` succeeds and smoke tests pass |
| Integration and pilot | Validate with target supervisor cohort | Test live metrics, queries, startup scan, sessions, contact search, and monitoring flow | Pilot users confirm workflow usefulness and support model works |
| Production hardening | Close control gaps | Enforce API authorisation, centralise logging, confirm retention and backup, standardise Bedrock model selection | Security and operations sign-off granted |
| Managed go-live | Launch as supported internal service | Publish runbooks, alert routes, release control, and contact-centre communications | Go-live checklist complete |

### Acceptance Criteria

- Frontend build succeeds using the documented command in the frontend directory.
- Local or cloud `/health` returns `status: ok` and correctly identifies mode.
- `/query` returns valid session id and usable markdown answer for standard prompts.
- Nine tool schemas are present and aligned with deploy-time mappings.
- Contact search supports native Connect filters plus custom attribute filtering.
- Startup scan stream, status, and cached resources operate as expected.
- Session persistence works end to end in the intended target backend.
- Supervisor monitoring flow is validated with approved origins and Connect permissions.
- API authorisation design is implemented or formally risk-accepted before production release.

### Go-Live Checklist

- Confirm named service owner, support rota, and escalation path.
- Confirm Connect instance id, alias, Bedrock access, and IAM roles in target region.
- Confirm Cognito configuration, login flow, and API authorisation enforcement.
- Confirm CloudFront URL, TLS, and browser compatibility for approved origins.
- Confirm EventBridge to SQS configuration for live-contact ingestion.
- Confirm session-store backend, retention settings, and backup controls.
- Confirm deployment rollback steps and last-known-good artefact version.
- Confirm operational dashboards, alerts, and runbooks are published.

## Training & Knowledge Transfer

Training should be split by role. Supervisors require practical instruction on navigation, proactive alerts, safe interpretation of AI-generated advice, contact search, transcript handling, and the monitoring or barge workflow. Platform and support teams require deeper understanding of deployment modes, tool registration discipline, listener operation, startup scan behaviour, and session storage backends.

A short operational knowledge pack should include example natural-language prompts, known limitations of transcript and recording retrieval, explanation of rate limits, and clear guidance that the AI assistant provides decision support rather than an authoritative operational mandate. This distinction is important in regulated banking environments where accountability for customer-impacting action must remain with human staff.

| Knowledge Transfer Item | Audience | Outcome |
| --- | --- | --- |
| Supervisor enablement workshop | Contact-centre leaders and supervisors | Users can interpret dashboards, trigger AI queries, and use monitoring responsibly |
| Operational handover | L1 and L2 teams | Support can diagnose health, mode, queue listener, and session-store issues |
| Engineering runbook review | L3 and platform engineers | Technical owners can manage deployment, tool drift, and Bedrock integration |
| Data and security briefing | Governance, legal, and security stakeholders | Control owners understand transcript, recording, and JWT handling responsibilities |

## Risk Register

| ID | Risk | Category | Probability | Impact | Mitigation | Owner | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CAA-01 | API Gateway methods are currently created without enforced authorisation, creating a production access-control gap. | Security | Medium | High | Implement JWT or equivalent authoriser before go-live and test failure paths. | [OWNER_NAME] | Open |
| CAA-02 | Tool registration drift across `agent_core.py`, `deploy.sh`, and `tool-schemas.json` causes incomplete or inconsistent tool availability. | Release Management | High | Medium | Add release checklist and automated validation for tool-map parity. | [OWNER_NAME] | Open |
| CAA-03 | Amazon Connect API throttling or missing Contact Lens data degrades query accuracy and transcript features. | Supplier / Integration | Medium | Medium | Monitor API errors, document feature prerequisites, and provide user guidance on limitations. | [OWNER_NAME] | Open |
| CAA-04 | Connect Streams origin or CCP configuration issues break supervisor monitor and barge workflows. | Operations | Medium | Medium | Validate approved origins, alias configuration, and security-profile permissions during deployment. | [OWNER_NAME] | Open |
| CAA-05 | Session persistence misconfiguration between SQLite and DynamoDB backends leads to data loss or inconsistent recovery posture. | Data / Continuity | Medium | High | Standardise production backend, document environment settings, and test restore procedures. | [OWNER_NAME] | Open |
| CAA-06 | Divergent Bedrock default model values between deployment configuration and runtime fallback logic create unpredictable response behaviour. | AI / Configuration | Medium | Medium | Standardise approved model id by environment and include it in configuration governance. | [OWNER_NAME] | Open |

## Approvals

| Role | Name | Signature | Date |
| --- | --- | --- | --- |
| Service Owner | [NAME] | Pending | [DATE] |
| Enterprise Architect | [NAME] | Pending | [DATE] |
| Security Architect | [NAME] | Pending | [DATE] |
| Contact Centre Technology Lead | [NAME] | Pending | [DATE] |
| Service Operations Manager | [NAME] | Pending | [DATE] |
