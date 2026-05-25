# Service Introduction Document — Connect Lambda Platform

This Service Introduction Document describes the shared serverless Lambda platform that underpins the ARIA contact centre capability for Meridian Bank. It is written as a service transition artefact for platform engineering, contact centre operations, information security, architecture governance and service management.

The document reflects the implementation present under `scripts/lambdas/`, the associated release and security records in `docs/`, and the operational deployment conventions used for Amazon Connect, AgentCore support services and audit fan-out in `eu-west-2`.

## Document Control

| Field | Value |
| --- | --- |
| SID ID | SID-CLP-001 |
| Version | 1.0.0 |
| Status | Draft |
| Classification | Internal |
| Owner | [OWNER_NAME] |
| Reviewers | [REVIEWER_NAME] |
| Service | Connect Lambda Platform |
| Business Unit | Platform Engineering |
| Primary Region | eu-west-2 |
| Document Date | [DATE] |

The Connect Lambda Platform is governed as a Tier 1 shared platform service because it mediates customer interactions, PCI-sensitive flows, queue routing, transcript carry-over and audit emission across the ARIA operating model. Change control is therefore aligned to Meridian Bank production change governance, Amazon Connect publication windows and security review checkpoints.

The owner is accountable for design integrity, operational readiness, release traceability and service transition evidence. Reviewers are expected to cover platform engineering, service management, information security, contact centre operations and solution architecture before the document moves from draft into controlled publication.

| Revision | Date | Author | Summary |
| --- | --- | --- | --- |
| 1.0.0 | [DATE] | [OWNER_NAME] | Initial draft covering shared Lambda service boundaries, dependencies, transition controls and operational model. |

## Executive Summary

The Connect Lambda Platform is the shared serverless execution layer for ARIA within Amazon Connect. It provides the control-plane functions that make voice and chat journeys operable in production: conversation fulfilment, dynamic routing, secure DTMF orchestration, session context injection, cross-channel transfer and compliance event delivery. In practical terms, every materially significant contact-centre interaction depends on one or more of these Lambda functions succeeding inside a low-latency Amazon Connect workflow.

From a service management perspective, the platform is business critical because it backs all core contact-centre paths rather than a single feature. The `aria_connect_fulfillment.py` bridge carries every Lex turn into AgentCore, while routing, callback and transfer functions preserve continuity when automation must escalate, defer or move a customer across channels. The DTMF functions enforce safe handling of sensitive keypad input and the audit writers anchor the bank's regulatory evidence chain.

The platform is deliberately engineered as a warm-container-optimised, Python 3.12 Lambda estate. Across the functions inspected, AWS SDK clients are initialised outside the handler and use `tcp_keepalive=True`, `max_pool_connections=10`, standard retries, `connect_timeout=5` and `read_timeout=15`, following AWS Lambda performance guidance for connection reuse and controlled dependency initialisation. This is complemented by documented security review evidence showing SAST, transitive dependency CVE scanning and manual review completion for the Lambda estate.

The service therefore enters transition as a mature shared platform with clear technical interfaces, known constraints and well-defined ownership boundaries. The remaining transition focus is disciplined operationalisation: monitoring, concurrency governance, DR rehearsal, approval evidence and removal of implementation constraints that are acceptable in pilot-scale flows but not in full production scale-out.

## Service Description

| Attribute | Value |
| --- | --- |
| Name | Connect Lambda Platform |
| Classification | Shared internal platform service supporting customer-facing journeys |
| Service Tier | Tier 1 (Business Critical — backs all contact centre interactions) |
| Service Type | Shared Platform Service / Serverless Functions |
| Category | Serverless / Contact Centre Integration |
| Business Unit | Platform Engineering |
| Primary Consumers | Amazon Connect contact flows, Lex V2 integration, AgentCore support stack, audit pipeline and Contact Centre Operations |

The service is not a single Lambda function; it is a curated platform of Python 3.12 handlers operating as a common serverless substrate for ARIA. Each function is small by design, but together they provide the service behaviours that Amazon Connect cannot deliver natively: external fulfilment, high-assurance status propagation, session enrichment, contact-attribute manipulation, asynchronous audit fan-out and controlled cross-channel context transfer.

The platform is consumed synchronously by Amazon Connect contact flows and related AI support paths, and asynchronously by EventBridge for audit fan-out. It is also deployed together with the AgentCore support estate via `scripts/deploy_mcp_gateway.sh`, which provisions session injection and transfer handlers as support functions adjacent to the ARIA runtime and MCP gateway footprint.

| Lambda Component | Primary Purpose | Primary Trigger |
| --- | --- | --- |
| `aria_callback_scheduler.py` | Resolves callback queues dynamically from `aria-routing-config` and carries conversation context into outbound and agent whisper flows. | Amazon Connect callback offer flow |
| `aria_connect_fulfillment.py` | Bridges Lex V2 turns to the ARIA AgentCore `/invocations` endpoint, handles retry logic, and diverts to `CollectCardDetails` when DTMF collection is requested. | Lex V2 / Amazon Connect |
| `aria_dtmf_decrypt.py` | Decrypts RSA-OAEP protected DTMF ciphertext using AWS Encryption SDK and returns masked outputs, BIN and last-four derivations. | Amazon Connect secure input block |
| `aria_dtmf_start_session.py` | Creates the active DTMF session record in DynamoDB and pushes `dtmf_status=awaiting_trigger` to the original contact. | Amazon Connect flow block |
| `aria_dtmf_status_proxy.py` | Exposes `GET /dtmf-active` and `GET /dtmf-status` over API Gateway for launcher and CCP status panel polling. | API Gateway / browser panel |
| `aria_dtmf_validate.py` | Performs Luhn, BIN and ownership checks, updates contact attributes in real time, and synchronises the active-session table. | Amazon Connect flow block |
| `aria_meeting_id_capture.py` | Extracts and normalises 6-digit meeting identifiers from Connect event payloads for callback workflows. | Amazon Connect customer input flow |
| `aria_routing_lookup.py` | Returns queue routing and proficiency metadata as a Connect-compatible flat string map. | Amazon Connect escalation flow |
| `audit_cloudtrail_writer.py` | Writes immutable audit events to CloudTrail Lake custom channels for seven-year compliance retention. | EventBridge audit bus |
| `audit_dynamodb_writer.py` | Writes operational audit events to DynamoDB with ninety-day TTL for hot-path complaint and fraud queries. | EventBridge audit bus |
| `chat_to_voice_transfer.py` | Pulls Contact Lens chat transcript segments, stores them in DynamoDB and starts outbound voice callbacks. | Amazon Connect chat flow |
| `session_injector_qconnect.py` | Populates Amazon Q in Connect session variables after the Connect assistant block. | Amazon Connect / Q Connect |
| `session_injector.py` | Injects customer, vulnerability and prior-interaction context into contact flows and downstream AI prompts. | Amazon Connect flow |
| `voice_to_chat_transfer.py` | Creates chat contacts from voice calls, stores transcripts and issues SMS deep links. | Amazon Connect voice flow |

## Business Context

Meridian Bank's ARIA programme exists to provide consistent, compliant and low-friction servicing across voice and chat channels. The Connect Lambda Platform is the enabling layer that turns that ambition into an operable banking service by binding Amazon Connect, Lex, AgentCore, Amazon Q in Connect, audit storage and specialist routing logic into a coherent production path. Without it, the contact centre would revert to fragmented point solutions, duplicated flow logic and manual workarounds.

The business drivers are explicit. First, the bank needs lower average handling time and better first-contact resolution through AI-assisted and automated journeys. Secondly, it must preserve regulatory and evidential integrity when sensitive actions occur, particularly around card data, customer authentication and vulnerable-customer handling. Thirdly, it must avoid brittle flow duplication by establishing a reusable shared serverless layer that multiple journeys can consume.

From a transition standpoint, the platform is also a cost-and-change accelerator. Lambda-based shared services reduce permanent infrastructure overhead, allow versioned rollouts aligned to flow publication windows, and permit specialist capabilities such as DTMF decryption or CloudTrail Lake audit writing to be improved once for the whole contact centre rather than reimplemented per flow.

| Stakeholder / Persona | Interest in Service | Transition Need |
| --- | --- | --- |
| Contact Centre Operations | Stable customer journeys, predictable agent experience and low disruption during change windows. | Operational readiness, go-live comms and rollback playbooks. |
| Platform Engineering | Reusable integration layer with controlled deployment, monitoring and supportability. | Versioning, observability, IaC alignment and hypercare ownership. |
| Information Security | Least privilege, secure key handling, no raw PCI data leakage and evidential audit trails. | Security review evidence, access model sign-off and log validation. |
| Service Management | Clear service ownership, SLOs, incident routing and transition acceptance criteria. | Support model, knowledge articles and service catalogue entry. |
| Solution Architecture | Conformance to target operating model and reduction of bespoke contact-flow logic. | Architecture baseline, interface catalogue and risk disposition. |
| Risk / Compliance / QSA Liaison | PCI-DSS, FCA and GDPR alignment for customer-affecting flows. | Control mapping, risk register review and DR expectations. |

| Business Value Metric | Intent | Target / Interpretation |
| --- | --- | --- |
| Automation continuity | Maintain successful fulfilment of AI-assisted turns through the shared bridge. | No material increase in abandoned or error-routed contact-flow invocations after transition. |
| Average handling time | Reduce manual hand-off friction through routing lookup, context injection and cross-channel transfer. | Measured reduction versus equivalent non-platform paths once stable in production. |
| PCI-safe handling | Avoid raw card data exposure to agents, recordings and logs. | Zero confirmed leakage incidents. |
| Operational auditability | Record consequential actions to hot and immutable stores. | Audit event completeness for in-scope actions. |
| Reuse of shared capability | Minimise duplicated contact-flow logic across channels. | New flows consume shared Lambdas rather than bespoke clones. |
| Change velocity | Permit independent Lambda upgrades within controlled release practice. | Reduced time to deliver routing, transfer or validation changes. |

## Service Scope

The service scope includes the shared Lambda handlers under `scripts/lambdas/` that are invoked directly by Amazon Connect, API Gateway or EventBridge as part of the ARIA operating model. It also includes the shared runtime conventions, packaging approach, IAM execution model, CloudWatch logging, deployment scripts, support runbooks and service-management controls that make those handlers operable as a platform rather than a loose collection of scripts.

The service boundary starts when a supported upstream platform invokes a Lambda entry point and ends when that invocation returns a Connect-compatible response, updates a downstream AWS system of record, or emits an audit event into the bank's compliance pipeline. Business logic that resides entirely inside the ARIA runtime container or in external banking systems is outside the platform boundary, even when the platform mediates the call.

For service transition purposes, the following items are in scope:

- Shared fulfilment path between Lex V2 and AgentCore, including SigV4-signed invocation of the AgentCore runtime endpoint.
- DTMF session start, decrypt, validate and status-proxy capabilities.
- Queue and callback routing lookup against DynamoDB configuration.
- Session injection into Connect and Amazon Q in Connect prompts.
- Voice↔chat transfer support functions, including transcript carry-over via DynamoDB and Contact Lens retrieval.
- Audit fan-out writers for DynamoDB hot storage and CloudTrail Lake immutable storage.
- Meeting ID capture for callback and scheduled-contact scenarios.
- Runtime conventions for Python 3.12, boto3 client reuse, retry policy and logging baseline.
- Deployment scripts, release tracking and operational documentation directly related to the Lambda estate.

The following items are explicitly out of scope for this SID:

- Core banking systems and APIs that the runtime tools ultimately call.
- The ARIA runtime container itself, its in-process banking tools and prompt engineering.
- Amazon Connect flow authoring beyond the dependencies and contracts required by these Lambdas.
- Customer-facing product design, speech copy, Lex intent design and knowledge content governance.
- Enterprise network, landing zone and IAM federation controls not specific to this platform.
- Static web asset ownership for non-platform front ends, except where the CCP DTMF panel depends on the status-proxy API.
- Downstream analytics or MI use cases that consume audit or transcript data after the platform has written them.

## Technical Architecture

At a high level, the Connect Lambda Platform acts as a serverless orchestration layer between Amazon Connect and a set of AWS-managed services. The platform is intentionally decomposed so that low-latency synchronous handlers remain narrow in responsibility: routing lookup returns flat string maps for Connect, session injectors enrich prompt variables, transfer handlers preserve transcript context, and DTMF handlers isolate sensitive-card workflows from the rest of the estate.

The technical pattern is event-driven and stateless at the compute tier, with state externalised into Amazon Connect contact attributes, Lex session attributes, DynamoDB tables, EventBridge and S3. The handlers rely on AWS managed elasticity rather than provisioned host capacity, and the code inspected consistently uses connection reuse, module-level client initialisation and bounded retry settings to minimise cold-start and network overhead.

```text
Customer / Agent
      |
      v
Amazon Connect contact flow / Lex V2 / Q Connect
      |
      +--> aria_connect_fulfillment.py --> AgentCore runtime /invocations --> ARIA response
      |
      +--> aria_routing_lookup.py / aria_callback_scheduler.py --> DynamoDB routing config
      |
      +--> session_injector.py / session_injector_qconnect.py --> Connect / Q Connect session data
      |
      +--> voice_to_chat_transfer.py / chat_to_voice_transfer.py --> Contact Lens + DynamoDB + SMS / outbound voice
      |
      +--> aria_dtmf_start_session.py --> DynamoDB active session
      |        |
      |        +--> aria_dtmf_decrypt.py --> AWS Encryption SDK + Secrets Manager + KMS
      |        |
      |        +--> aria_dtmf_validate.py --> BIN table + customer lookup Lambda + contact attributes
      |        |
      |        +--> aria_dtmf_status_proxy.py --> API Gateway --> launcher / CCP status panel
      |
      +--> EventBridge audit bus --> audit_dynamodb_writer.py + audit_cloudtrail_writer.py
```

| Technology Element | Implementation Detail | Why It Matters |
| --- | --- | --- |
| Runtime | AWS Lambda on Python 3.12 | Common managed compute substrate for all shared handlers. |
| SDK baseline | `boto3` / `botocore` with module-level client reuse | Reduces connection churn and improves warm-path latency. |
| HTTP integration | `urllib.request` plus SigV4 signing in `aria_connect_fulfillment.py` | Allows secure invocation of AgentCore runtime `/invocations`. |
| Cryptography | `aws_encryption_sdk` and `cryptography`-backed dependencies in DTMF path | Supports RSA-OAEP decryption of Connect secure input payloads. |
| State store | Amazon DynamoDB tables including `dtmf_active_sessions`, `aria-routing-config`, `aria-transcript-store`, `aria-card-bins`, `aria-customer-cards` | Provides low-latency state externalisation. |
| Audit transport | Amazon EventBridge custom audit bus | Decouples synchronous tool execution from compliance storage fan-out. |
| Immutable audit store | CloudTrail Lake custom channel | Supports cryptographically verifiable long-retention audit events. |
| Operational audit store | Amazon DynamoDB `aria-audit-events` design target | Supports hot complaint and fraud queries. |
| Transcript archive | Amazon S3 and DynamoDB transcript storage | Preserves context during channel transfer. |
| Contact-centre integration | Amazon Connect, Lex V2, Amazon Q in Connect and Contact Lens | Primary upstream systems and session context sources. |
| Messaging | Pinpoint SMS Voice V2 in `voice_to_chat_transfer.py` | Supports voice-to-chat deflection messaging. |
| Observability | CloudWatch Logs with Dynatrace guidance available in repository | Supports operational telemetry and incident triage. |

| Integration Point | Direction | Contract Summary |
| --- | --- | --- |
| Amazon Connect → Lambda | Inbound synchronous | Standard Connect event payloads with `Details.ContactData` and `Details.Parameters`. |
| Lex V2 → `aria_connect_fulfillment.py` | Inbound synchronous | Lex turn event with session state, request attributes and utterance text. |
| `aria_connect_fulfillment.py` → AgentCore runtime | Outbound synchronous | SigV4-signed HTTPS POST to `/invocations` endpoint. |
| Connect session injectors → Q Connect | Outbound synchronous | `UpdateSessionData` after session creation. |
| Routing / callback handlers → DynamoDB | Outbound synchronous | Point lookup against routing configuration. |
| DTMF decrypt → Secrets Manager / KMS | Outbound synchronous | Fetches private key material protected by KMS. |
| DTMF validate → customer verification Lambda | Outbound synchronous | Ownership check via Lambda-to-Lambda invocation. |
| Status proxy → API Gateway → browser assets | Bidirectional HTTP | Provides JSON status for launcher and agent panel polling. |
| Transfer handlers → Contact Lens / Connect / Pinpoint | Outbound synchronous | Retrieves transcript and initiates chat or voice actions. |
| Audit bus → audit writers | Asynchronous event | Non-blocking compliance event delivery. |
| Audit writer → CloudTrail Lake | Outbound synchronous | Writes immutable custom audit events. |
| Audit writer → DynamoDB | Outbound synchronous | Writes hot operational audit records with TTL. |

## Service Interfaces

The platform exposes no public customer API. Its interfaces are operational integration contracts between Amazon Connect, Lex, API Gateway, EventBridge and adjacent AWS services. Contract stability matters because Amazon Connect contact flows and Lex session mappings are configuration-driven; a seemingly small schema change can silently break downstream attributes or routing logic.

| API / Contract | Caller | Key Inputs | Key Outputs |
| --- | --- | --- | --- |
| Connect Lambda event | Amazon Connect | `ContactId`, `InitialContactId`, contact attributes and flow parameters | Flat string maps or JSON structures consumed by flow blocks. |
| Lex fulfilment event | Lex V2 / Amazon Connect | `sessionState`, `requestAttributes`, `inputTranscript` | Lex dialog actions such as `ElicitIntent` or `CollectCardDetails`. |
| AgentCore invocation | `aria_connect_fulfillment.py` | Signed HTTP request containing session, utterance and contextual attributes | ARIA text response and bridge metadata. |
| Q Connect `UpdateSessionData` | Session injectors | Resolved assistant session, customer context and vulnerability metadata | Enriched prompt variables for subsequent AI steps. |
| Routing lookup response | Amazon Connect | `topicCategory` and echoed context attributes | `queueId`, `queueName`, proficiency metadata and routing error flag. |
| Callback scheduler response | Amazon Connect | `topicCategory`, callback reason and context attributes | `callbackQueueId`, queue name and scheduling error flag. |
| DTMF decrypt response | Amazon Connect flow | `encryptedValue`, `keyId`, `purpose` | Masked value, digit count, BIN, last four and validation hints. |
| DTMF validate response | Amazon Connect flow | Derived card metadata, authentication state and customer ID | `isValid`, `validationStatus`, `cardType`, `requiresEscalation`. |
| Status proxy HTTP API | Launcher / agent panel | GET `/dtmf-active`; GET `/dtmf-status?contactId=` | JSON status payloads for human-agent UI. |
| Transfer Lambda response | Amazon Connect flow | Contact IDs, phone numbers, widget URL and transfer mode | Chat or callback outcome attributes under `$.External.*`. |
| EventBridge audit event | Runtime / tools / flows | Structured audit envelope with actor, action, outcome and customer context | Fan-out to writer Lambdas. |
| Meeting ID response | Amazon Connect flow | Customer-input payload containing 6-digit token | `success`, `meetingId`, `meetingIdSource`, message. |

| Event / Message Interface | Purpose | Notes |
| --- | --- | --- |
| Amazon Connect contact attributes | Real-time state propagation between flow blocks, Lambda handlers, agent CCP and Lex session mapping. | Examples include `dtmf_status`, `aria_status`, `topicCategory` and escalation metadata. |
| Lex session attributes | Conversation continuity into `aria_connect_fulfillment.py` and ARIA prompt context. | Must be explicitly mapped by flow configuration. |
| EventBridge `detail` payload | Audit event fan-out. | Writer Lambdas derive customer, timestamp and event identifiers from `detail`. |
| DynamoDB singleton active session row | DTMF session discovery for launcher and panel. | Current implementation uses `session_id = "ACTIVE"` with last-write-wins semantics. |
| SMS / callback payloads | Channel-transfer continuation. | Used only in voice↔chat transfer functions. |

| UI Interface | Consumer | Operational Use |
| --- | --- | --- |
| Amazon Connect contact flows | Flow designers / Connect runtime | Primary orchestration surface consuming Lambda responses. |
| CCP Contact Attributes panel | Human agents | Displays routing, transfer and DTMF status information when mapped into the contact. |
| DTMF launcher iframe | Human agents | Auto-discovers the currently active secure-entry session via `/dtmf-active`. |
| DTMF status panel | Human agents | Polls `/dtmf-status` every two seconds and renders colour-coded progress. |
| CloudWatch / Dynatrace dashboards | Operations and engineering | Consumption interface for runtime telemetry rather than customer interaction. |

## Service Dependencies

The platform has strong internal coupling to the ARIA contact-centre operating model. In particular, Connect flows must set and map attributes consistently, Lex must preserve session identifiers, and the AgentCore runtime must honour the bridge actions expected by `aria_connect_fulfillment.py`. These are designed dependencies rather than incidental ones and must be version-managed as part of transition planning.

Internal dependencies are summarised below:

- Amazon Connect contact flows published with correct Lambda associations, attribute mappings and branch logic.
- Lex V2 bot configuration aligned to the `CollectCardDetails` intent and normal `ElicitIntent` loop.
- ARIA runtime availability at the configured AgentCore `/invocations` endpoint.
- Q Connect assistant configuration for prompt-variable injection where session injectors are used.
- DynamoDB tables seeded with valid routing, BIN and card-reference data.
- Transcript storage table available for voice↔chat transfer journeys.
- EventBridge audit bus and downstream writer deployment for full compliance fan-out.
- CloudFront/S3-hosted DTMF panel assets where human-agent secure capture is enabled.

| External Dependency | Purpose | Criticality | Fallback / Behaviour on Failure |
| --- | --- | --- | --- |
| Amazon Connect | Primary caller and contact-attribute source. | Critical | No service without Connect invocation context. |
| Lex V2 | Conversation turn orchestration for fulfilment path. | Critical | Customer journey degrades to flow-level fallbacks. |
| Bedrock AgentCore Runtime | Executes ARIA runtime for conversational fulfilment. | Critical | Retry in fulfilment bridge, then controlled error path. |
| Amazon Q in Connect / Wisdom | Prompt-variable injection target for assisted flows. | High | Session injection returns partial failure or skipped enrichment. |
| DynamoDB | Routing, DTMF session, BIN, card-reference and transcript state. | Critical | Handlers return controlled errors or reduced behaviour. |
| Secrets Manager + KMS | Protects DTMF private key and optional ownership API keys. | Critical for DTMF | DTMF decrypt path fails closed or returns system error. |
| EventBridge | Audit-event decoupling. | High | Synchronous customer path continues, but compliance gap is created. |
| CloudTrail Lake | Immutable long-retention audit store. | High | Operational hot store may continue, but immutable audit objective is degraded. |
| Contact Lens | Transcript extraction for channel transfer. | Medium | Transfers may proceed with reduced transcript context. |
| Pinpoint SMS Voice V2 | Voice-to-chat deflection notifications. | Medium | Fallback to voice-only handling or agent comms. |

## Service Level Objectives

Because this is a shared platform rather than a single endpoint, SLOs are defined around customer-impacting platform outcomes and the most latency-sensitive transaction classes. The objectives below are designed for service management and transition acceptance; they should be refined into CloudWatch alarms and operational reports once steady-state baselines are available.

| Objective | Target | Measurement Basis |
| --- | --- | --- |
| Availability | 99.95% monthly for Tier 1 synchronous invocation paths | Successful Lambda completions and API availability during agreed service window. |
| Routing / callback lookup latency | p95 < 300 ms | Measured from Lambda invocation start to response return. |
| Session injection latency | p95 < 500 ms | Measured for `session_injector.py` and `session_injector_qconnect.py`. |
| DTMF status API latency | p95 < 250 ms | Measured on API Gateway for `GET /dtmf-active` and `GET /dtmf-status`. |
| DTMF decrypt + validate latency | p95 < 1.0 s end-to-end | Measured across sequential flow invocation steps excluding customer input time. |
| Fulfilment bridge latency | p95 < 2.5 s before first response token/intent decision | Measured from Lex event receipt to AgentCore response parsing. |
| Throughput | Support concurrent Lambda scaling for peak contact-centre demand without manual host provisioning | Observed via Lambda concurrency and throttling metrics. |
| RTO | 60 minutes for platform restoration in-region; 4 hours for regional failover exercise target | Recovery objective for production incident management. |
| RPO | 15 minutes for operational state; 0 minutes for immutable audit events once accepted by downstream store | Based on DynamoDB / audit-pipeline recovery design. |

These objectives assume agreed AWS service quotas, pre-provisioned IAM roles, current deployment scripts and tested rollback aliases. They do not assume active-active multi-region operations today; the current architecture is resilient in-region but not yet engineered as a full cross-region hot/hot service.

## Operational Model

Operational ownership follows a standard three-tier model with specialist escalation into platform engineering and security when PCI-sensitive or cross-channel issues are involved. Because the Lambdas are embedded in live customer journeys, detection and restoration speed matter more than pure infrastructure repair; incident handling must therefore focus on restoring the customer path, even if full feature fidelity is temporarily reduced.

| Support Tier | Owner | Responsibilities | Hours |
| --- | --- | --- | --- |
| L1 | Service Desk / Contact Centre Operations | Initial triage, user-impact assessment, change freeze decision support and comms to supervisors. | Business hours with on-call escalation path. |
| L2 | Platform Engineering | Lambda, API Gateway, DynamoDB, Connect integration and deployment triage; rollback execution. | 24x7 on-call for Tier 1 incidents. |
| L3 | Solution Architecture / Senior Engineering | Design-level fault isolation, code defect analysis, structural remediation and release approval. | On demand via major incident process. |
| Specialist | Information Security / PCI liaison | Key-handling, audit-trail, data-exposure and control-break investigation. | On demand for security-significant incidents. |

The on-call model should align to the ARIA production rota, with platform engineering owning the first technical response and liaising directly with Contact Centre Operations. For P1 incidents, a single incident lead should coordinate Lambda rollback, contact-flow fallback decisions and customer communication so that technical teams are not simultaneously making conflicting changes in Connect and Lambda.

Operational readiness also requires agreed runbooks for DTMF failure, routing failure, AgentCore fulfilment degradation, transcript transfer failure and audit-pipeline interruption. Knowledge articles must explain which failures are customer-path blocking, which are fail-open, and which create compliance debt that can be remediated after service restoration.

| Incident Class | Definition | Typical Examples |
| --- | --- | --- |
| P1 | Customer service materially unavailable or compliance-critical path broken. | Fulfilment bridge outage, DTMF secure capture unavailable, widespread routing failure. |
| P2 | Major degradation with workaround or limited scope. | Voice↔chat transfer failing, Q Connect injection degraded, audit immutable store unavailable but hot path live. |
| P3 | Non-critical defect with manageable workaround. | Single queue mapping issue, delayed transcript carry-over, non-critical dashboard gap. |
| P4 | Minor issue or enhancement request. | Documentation gap, tuning change, cosmetic attribute-mapping issue. |

## Security & Compliance

The Connect Lambda Platform is classified as Internal but it processes and transports higher-classification data elements on behalf of upstream channels. The platform therefore inherits strong obligations around access control, logging discipline, segregation of duties and secure handling of derived card artefacts, customer identifiers, vulnerability indicators and audit data. Control design must reflect the service's position inside a UK retail bank contact-centre environment rather than a generic chatbot integration.

Authentication and authorisation are AWS-native. Amazon Connect invokes the Lambdas through explicit resource permissions, execution roles are granted least-privilege access to downstream AWS APIs, and `aria_connect_fulfillment.py` signs AgentCore requests using SigV4. Sensitive DTMF operations require additional access to Secrets Manager and KMS-protected key material, while Q Connect enrichment requires `UpdateSessionData` access scoped to the configured assistant.

| Security Topic | Current Position |
| --- | --- |
| Security Classification | Internal service with regulated-data handling responsibilities. |
| AuthN / AuthZ | IAM execution roles, Lambda resource policies, Connect association controls and SigV4-signed outbound runtime invocation. |
| Key Management | DTMF private key protected by Secrets Manager and KMS in the inspected implementation; public key registered in Amazon Connect security keys. |
| Secure Coding Evidence | Repository security audit records SAST, dependency CVE scan and manual review with zero residual actionable findings as of 2026-05-24. |
| Logging Control | No intentional raw PCI digit logging; handlers use masked or derived values for card data paths. |

| Data Classification | Examples | Handling Requirement |
| --- | --- | --- |
| Operational Internal | Queue IDs, topic categories, routing metadata, Lambda status codes | May be logged and retained under standard internal controls. |
| Confidential Customer | Customer IDs, prior-summary context, vulnerability markers, transcript references | Need-to-know access, limited log exposure, controlled retention. |
| PCI-derived Restricted | BIN, last four digits, masked card identifiers | Only derived outputs permitted; never reconstruct full PAN. |
| Secret / Key Material | DTMF private key, API secrets, signing credentials | Managed secret stores only, encrypted at rest and access-logged. |
| Immutable Compliance Data | CloudTrail Lake audit events | Seven-year retention objective, append-only handling. |

- PCI-DSS 4.0 obligations apply where the platform participates in secure DTMF collection and derived card-data handling.
- FCA recordkeeping and complaint reconstruction obligations apply to routing, escalation and consequential customer actions.
- GDPR and UK Data Protection Act obligations apply to customer identifiers, vulnerability context and transcript-linked personal data.
- ISO/IEC 20000-1 and internal service transition controls apply to release, knowledge transfer and operational acceptance.

## Capacity & Scalability

The platform inherits AWS Lambda horizontal scaling characteristics and therefore avoids fixed server capacity planning. In steady state, the principal capacity concern is not CPU estate but concurrency coordination across Lambda, API Gateway, DynamoDB and Amazon Connect limits. This makes the service operationally attractive, but it also means design constraints hidden in application logic can become the true scale bottleneck if not resolved before wider rollout.

| Capacity Area | Current Position | Implication |
| --- | --- | --- |
| Compute scale | Serverless Lambda scaling per function with no permanent host fleet. | Good elasticity for bursty contact-centre demand. |
| SDK connection pools | Most handlers configure `max_pool_connections=10` and keepalive on warm containers. | Improves burst handling inside each container. |
| DynamoDB state | Point lookups and keyed writes for routing, session and transcript state. | Low-latency access pattern, but table design must match concurrency expectations. |
| Audit fan-out | EventBridge decouples synchronous path from downstream audit writes. | Prevents compliance writes from lengthening customer-path latency. |
| AgentCore bridge | Fulfilment path relies on remote runtime availability and retry budget. | Upstream scaling is only useful if AgentCore endpoint scales with it. |
| Human-agent DTMF discovery | Current `dtmf_active_sessions` discovery path stores a singleton `session_id = ACTIVE` row. | Known concurrency limitation: simultaneous sessions are last-write-wins for launcher discovery. |

Scaling approach for transition is to keep Lambda concurrency unreserved initially, monitor real-world peaks, and then introduce reserved concurrency or provisioned concurrency only where p95 customer impact justifies it. DynamoDB autoscaling or on-demand mode should be used for routing and session tables, and API Gateway plus CloudFront should be monitored for browser-panel polling amplification during busy periods.

Known limits at the time of writing are: the singleton active-session discovery pattern in DTMF flows; dependence on correct Connect attribute mapping for state propagation; single-region operational posture; and the latency sensitivity of the fulfilment bridge when external runtime or customer lookup services degrade. These limits are manageable for controlled production use but must be tracked explicitly in the risk register and transition backlog.

## Monitoring & Observability

Observability for the platform must distinguish customer-path health from supporting control health. A Lambda can be “green” at infrastructure level while the customer journey is functionally broken because a contact attribute is missing, a routing table entry is absent, or an immutable audit target is unavailable. Transition success therefore depends on combining technical metrics with journey-centric operational views.

| Key Metric | Why It Matters |
| --- | --- |
| Lambda invocation success / error rate by function | Primary signal for synchronous customer-path health. |
| Lambda duration p50 / p95 / p99 | Detects cold-start pressure, downstream dependency slowness and regression after release. |
| Lambda throttles and concurrency | Shows whether AWS quotas or burst patterns are constraining the platform. |
| API Gateway 2xx / 4xx / 5xx for DTMF status proxy | Directly affects human-agent secure-capture visibility. |
| DynamoDB consumed capacity and throttles | Required for routing, session and transcript tables. |
| AgentCore invocation failure / retry count | Indicates conversational fulfilment risk before customer abandonment rises. |
| Connect attribute update failures | Breaks state propagation to flows, agents and Lex. |
| CloudTrail writer failures | Creates immutable audit gaps with regulatory significance. |
| EventBridge delivery failures | Signals audit fan-out degradation. |
| Contact Lens transcript retrieval failures | Degrades voice↔chat continuity. |

Logging strategy should remain structured, masked and correlation-friendly. Contact IDs, initial contact IDs, session IDs and request IDs should be present to support incident reconstruction, but raw customer secrets and full PAN-equivalent values must never be written. The security audit evidence in the repository should be treated as the minimum standard for future changes, not a one-off compliance exercise.

| Alert Threshold | Suggested Trigger | Operational Response |
| --- | --- | --- |
| Fulfilment bridge error rate | > 2% over 5 minutes | L2 triage, validate AgentCore availability and consider rollback. |
| Routing / callback Lambda failures | > 1% over 10 minutes | Check DynamoDB config integrity and recent releases. |
| DTMF decrypt / validate system errors | Any sustained burst or repeat contact-impacting errors | Treat as high-priority due to PCI-sensitive path. |
| API Gateway 5xx on status proxy | > 1% over 5 minutes | Investigate Lambda, CORS and Connect attribute retrieval. |
| DynamoDB throttles | Any non-zero for in-scope tables | Increase capacity mode or investigate hot keys. |
| Audit writer failures | Any repeated failure in 15 minutes | Raise compliance-impacting incident and assess compensating controls. |
| Transfer Lambda failures | > 2% over 15 minutes | Notify Contact Centre Operations of degraded transfer capability. |
| CloudWatch log pattern detection | Possible 13–19 digit sequences or key-handling anomalies | Immediate security review. |

- Operational dashboards should be provided in CloudWatch and, where adopted, Dynatrace as described in `docs/aria-dynatrace-observability-guide.md`.
- Dashboards must be separated by customer-path domain: fulfilment, routing, DTMF, transfer and audit.
- Hypercare reporting for transition should include hourly incident summary, error-rate trend and rollback readiness status during the initial go-live window.

## Disaster Recovery & Business Continuity

The current platform is resilient within an AWS region because Lambda, API Gateway, DynamoDB, EventBridge and CloudTrail Lake are managed multi-AZ services. Business continuity risk arises primarily from configuration loss, deployment drift, secret unavailability or a full regional dependency event rather than from host failure. DR planning must therefore prioritise reproducible deployment, secret recovery, table configuration rebuild and contact-flow republishing.

The service is not yet presented as an active-active multi-region estate. Consequently, regional DR remains a controlled restore pattern rather than a transparent failover. This is acceptable for the present maturity stage provided RTO/RPO expectations are explicit, tested and supported by current deployment scripts and documented procedures.

| DR Topic | Current Approach |
| --- | --- |
| DR Strategy | Pilot-light / scripted rebuild using repository deployment assets and stored configuration values. |
| Primary RTO Target | 60 minutes for in-region restoration of Tier 1 paths; 4 hours for exercised secondary-region restore objective. |
| Primary RPO Target | 15 minutes for operational state; immutable audit records depend on downstream acceptance. |
| Failover Approach | Manual failover decision, redeploy Lambdas and APIs, restore secrets and republish Connect integrations. |
| Data Protection | DynamoDB managed durability, S3 durability and CloudTrail Lake retention. |
| Business Continuity Measure | Customer journeys fall back to agent-led servicing where compliant and operationally acceptable. |

- A DR rehearsal must include validation of Lambda deployment, API availability, DynamoDB table readiness, secret accessibility and Connect flow rebinding.
- PCI-sensitive DTMF paths must fail safely; if secure capture cannot be guaranteed, the bank must route customers to an alternative compliant servicing pattern rather than bypassing controls.
- Audit-pipeline restoration order should prioritise immutable trail availability for consequential actions, even if hot-query convenience storage is restored second.

## Service Transition Plan

Transition to controlled live service should be phased rather than executed as a single technical deploy. The platform touches customer journeys, agent workflows and regulated evidence paths, so acceptance needs to combine technical validation, flow publication control, operational readiness and hypercare monitoring.

| Phase | Purpose | Key Activities | Exit Criteria |
| --- | --- | --- | --- |
| 1. Design & control review | Confirm target-state design and control scope. | Architecture review, security review, service-model sign-off, dependency inventory. | Approved design baseline and accepted risk register. |
| 2. Build & packaging validation | Validate artefacts and deployment mechanics. | Package Lambdas, validate Python 3.12 runtime assumptions, review IAM and environment settings. | Repeatable build with deployment evidence. |
| 3. Non-production integration test | Prove end-to-end contact-flow behaviour. | Run routing, fulfilment, DTMF, transfer and audit scenarios in staging using synthetic data. | All critical scenarios pass with no unresolved Sev-1/2 defects. |
| 4. Operational readiness | Prepare teams and tooling. | Dashboards, alerts, runbooks, support-tier briefings and rollback rehearsals. | Support teams trained and on-call model confirmed. |
| 5. Production go-live | Execute controlled release. | Change window, Lambda deploy, flow publication, smoke tests, approvals and communications. | Go-live checklist complete and service stable. |
| 6. Hypercare & handover | Stabilise and transfer to BAU. | Enhanced monitoring, daily review, defect triage and final service acceptance. | Hypercare exit signed off by owner and service management. |

Acceptance Criteria:

- All in-scope Lambda functions deployed from controlled artefacts and associated to the correct Connect flows or API routes.
- Fulfilment bridge successfully invokes AgentCore with SigV4 signing and returns valid Lex responses.
- Routing and callback handlers resolve expected queues for seeded topic categories.
- DTMF path validates that only masked or derived values are exposed outside decrypt memory scope.
- Session injectors populate required prompt variables in test journeys using Amazon Q in Connect and standard flow contexts.
- Audit events are visible in the hot-path store and, where enabled, immutable store.
- Operational dashboards, alarms and runbooks are published and exercised.
- Rollback to last known-good Lambda alias and flow publication state has been rehearsed.

Go-Live Checklist:

- Approved production change record in place.
- Owner, reviewers and on-call contacts briefed.
- Environment variables, secrets and IAM roles validated.
- Connect flow associations and Lex mappings confirmed.
- DynamoDB tables present and seeded with production routing / BIN data where applicable.
- Audit destinations reachable and tested.
- CloudWatch alarms enabled and routed to the correct support channel.
- Synthetic smoke tests executed for fulfilment, routing, transfer and DTMF paths.
- Rollback alias versions recorded before deployment.
- Contact Centre Operations informed of release window and expected agent-side effects.
- Hypercare bridge opened for the agreed monitoring period.
- Post-go-live review scheduled within five business days.

## Training & Knowledge Transfer

Training must be role-based. Flow administrators need to understand Lambda contracts and attribute mappings; platform engineers need deployment, rollback and observability knowledge; service desk teams need symptom-based triage guidance; and information security needs clarity on the key-handling and audit-control boundaries. A single technical walk-through is insufficient for a Tier 1 platform service.

Knowledge transfer should be completed before production go-live and refreshed at the end of hypercare. The repository already contains strong supporting artefacts, including the security audit report, release configuration tracker, DTMF guide, channel-transfer guide and deployment runbooks; these should be indexed into the service knowledge base rather than left as engineering-only documents.

| Audience | Knowledge Required | Recommended Artefact |
| --- | --- | --- |
| Service Desk / L1 | Symptom triage, service ownership, escalation path and business impact language. | SID summary, incident matrix and operational KB article. |
| Platform Engineering / L2 | Deployment, rollback, alarm interpretation and dependency troubleshooting. | Deployment scripts, release config tracker and runbooks. |
| Contact Centre Operations | Go-live effects, agent experience and fallback handling. | Go-live briefing deck and DTMF/channel-transfer guides. |
| Security / Compliance | Key handling, audit fan-out and logging controls. | Security audit report and audit-event architecture document. |
| Architecture / CAB | Boundaries, interfaces, DR position and known risks. | This SID plus architecture diagrams and release tracker. |

## Risk Register

| ID | Risk | Category | Probability | Impact | Mitigation | Owner | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CLP-R1 | AgentCore fulfilment endpoint latency or outage causes widespread conversational degradation. | Availability | Medium | High | Retry budget, monitoring, rollback of recent changes and agreed customer-path fallback in Connect. | Platform Engineering | Open |
| CLP-R2 | DTMF active-session discovery uses a singleton `ACTIVE` row, creating concurrency collision risk for human-agent status discovery. | Scalability | High | High | Redesign active-session table for per-contact or per-agent discovery before large-scale rollout. | Platform Engineering | Open |
| CLP-R3 | Audit fan-out partially fails, leaving hot or immutable compliance records incomplete. | Compliance | Medium | High | Alert on EventBridge and writer failures, reconcile from source events, and document compensating controls. | Service Owner | Open |
| CLP-R4 | Connect flow attribute mapping drift breaks routing, DTMF or session-enrichment logic without infrastructure alarms. | Configuration | Medium | High | Version control exported flows, enforce release checklists and execute end-to-end smoke tests on every publish. | Contact Centre Operations | Open |
| CLP-R5 | Single-region deployment posture extends recovery time during regional AWS disruption. | DR | Low | High | Maintain scripted rebuild, rehearsed DR runbook and backlog for secondary-region readiness. | Architecture | Open |
| CLP-R6 | Documentation and implementation drift around DTMF key management or deployment scripts leads to unsafe change activity. | Operational Governance | Medium | Medium | Maintain controlled service docs, update runbooks per release and require security review for key-handling changes. | Service Management | Open |

## Approvals

| Role | Name | Signature | Date |
| --- | --- | --- | --- |
| Service Owner | [NAME] | [NAME] | [DATE] |
| Platform Engineering Lead | [NAME] | [NAME] | [DATE] |
| Contact Centre Operations Lead | [NAME] | [NAME] | [DATE] |
| Information Security Reviewer | [NAME] | [NAME] | [DATE] |
| Service Management Approver | [NAME] | [NAME] | [DATE] |
