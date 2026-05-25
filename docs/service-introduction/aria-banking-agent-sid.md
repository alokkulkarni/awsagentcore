# Service Introduction Document — ARIA Banking Agent

This Service Introduction Document (SID) describes the production introduction posture for ARIA Banking Agent, Meridian Bank's AI-native conversational banking service running across chat, voice, and Amazon Bedrock AgentCore hosted channels.

## Document Control

| Field | Value |
|---|---|
| SID ID | SID-ARB-001 |
| Service | ARIA Banking Agent |
| Version | 1.0.0 |
| Status | Draft |
| Classification | Internal |
| Owner | [OWNER_NAME] |
| Reviewers | [REVIEWER_NAME], [REVIEWER_NAME] |
| Business Unit | Digital Banking / Customer Experience |
| Service Type | New AI-Native Service |
| Service Tier | Tier 1 (Business Critical) |
| Category | Conversational AI / Customer Service Automation |
| Effective Date | [DATE] |
| Next Review Date | [DATE] |

### Revision History

| Version | Date | Author | Change Summary |
|---|---|---|---|
| 0.1.0 | [DATE] | [NAME] | Initial service introduction draft aligned to current ARIA architecture and operating model. |
| 0.9.0 | [DATE] | [NAME] | Expanded architecture, security, operational readiness, transition, and risk content for design authority review. |
| 1.0.0 | [DATE] | [NAME] | Baseline SID issued for service transition, CAB review, and controlled production onboarding. |

### Document Purpose

This document is the formal transition artifact for moving ARIA Banking Agent from engineering delivery into managed service operation within a regulated UK retail banking environment.

It consolidates business intent, architecture, service management controls, resilience targets, operational responsibilities, and approval checkpoints so that platform engineering, Amazon Connect operations, security, compliance, and contact-centre leadership can assess the service consistently.

## Executive Summary

ARIA Banking Agent is Meridian Bank's automated conversational banking service built to provide safe, empathetic, and auditable customer support across digital chat, telephony, and cloud-hosted assistant channels. The service combines Strands Agents orchestration, Amazon Bedrock foundation models, Amazon Nova Sonic 2 speech-to-speech, Amazon Connect routing, and Amazon Bedrock AgentCore Runtime to deliver self-service banking journeys that feel natural to customers while remaining tightly governed for security and compliance.

The service proposition is deliberately enterprise-grade rather than experimental. ARIA uses a mandatory PII redaction and vaulting pipeline so raw personal data never enters model reasoning context, injects customer and vulnerability context at session start when available, persists only redacted conversation history to AgentCore Memory, and emits a three-tier audit trail through EventBridge to CloudTrail Lake, DynamoDB, and S3-compatible archival patterns. The same core banking toolset is shared across chat, voice, and AgentCore deployment modes, giving Meridian Bank one controlled reasoning layer instead of separate channel-specific bots.

The intended audience for this SID is service transition managers, architecture review boards, contact-centre operations, security and compliance teams, incident response leads, and engineering owners accountable for live support. For those audiences, the key benefits are faster customer containment, improved 24x7 self-service coverage, consistent treatment of vulnerable customers, reduced variation across channels, and a materially stronger evidential trail than a conventional black-box generative AI deployment.

## Service Description

### Service Profile

| Attribute | Definition |
|---|---|
| Service Name | ARIA Banking Agent |
| Expanded Name | Automated Responsive Intelligence Agent |
| Service Classification | Internal managed platform capability delivering external customer outcomes |
| Service Tier | Tier 1 (Business Critical) |
| Service Type | New AI-Native Service |
| Category | Conversational AI / Customer Service Automation |
| Primary Channels | Amazon Connect chat, Amazon Connect voice, direct AgentCore HTTPS chat, direct AgentCore WSS voice |
| Primary Models | Claude Sonnet 4.6 for chat reasoning, Nova Sonic 2 for voice speech-to-speech |
| Primary Runtime | Amazon Bedrock AgentCore Runtime |
| Business Unit | Digital Banking / Customer Experience |
| Geographic Scope | UK retail banking operations, English language first |

ARIA Banking Agent presents a single business capability: secure conversational handling of common retail-banking service requests. In the current implementation it supports balance and statement enquiries, debit and credit card enquiries, lost or stolen card blocking, mortgage enquiries, spending analysis, product information retrieval, knowledge-base lookups, and controlled escalation to human agents.

The service is not a stand-alone chatbot widget; it is a multi-channel orchestration layer. `aria/agent.py` creates the Strands agent used for reasoning, `aria/agentcore_app.py` exposes the Bedrock AgentCore HTTP entrypoint for chat, and `aria/agentcore_voice.py` exposes the WebSocket voice path for Nova Sonic audio streaming. These channels share the same tool contracts and banking policy framework so that customer treatment remains consistent regardless of entry point.

## Business Context

### Business Drivers

- Increase first-contact containment for routine retail-banking queries without expanding human-agent headcount.
- Provide a modern self-service experience across voice and chat using a consistent Meridian Bank persona.
- Reduce average handling time for low-complexity service contacts by resolving them before queue transfer.
- Improve after-hours and surge-period coverage for card, account, and mortgage enquiries.
- Create a compliant automation layer that evidences every sensitive action for fraud, complaint, and regulatory review.
- Support vulnerability-aware communication aligned to FCA Consumer Duty and fair customer treatment obligations.
- Decouple channel front ends from banking logic by exposing a reusable tool-driven agent core.

### Stakeholders & Personas

| Stakeholder / Persona | Interest | Required Outcome |
|---|---|---|
| Retail banking customer | Fast, accurate support on voice or chat | Natural conversation, short wait times, secure handling of personal data |
| Contact-centre operations manager | Queue reduction and service consistency | Higher containment, lower transfer rate, stable escalation behaviour |
| Human banking adviser | Clean handoff when ARIA cannot resolve | Structured transcript summary, context preservation, known escalation reason |
| Digital banking product owner | Customer-experience uplift | Measurable NPS and adoption improvement across digital and telephony channels |
| AI platform engineering | Operability and reuse | One set of tools, one policy model, reusable runtime interfaces |
| Security and fraud operations | Strong controls | No raw PII in prompts, immutable audit trail, IAM least privilege, rapid evidence retrieval |
| Compliance / risk / legal | Regulatory defensibility | Traceable decision path, vulnerability-aware treatment, policy conformance |
| Service transition and support teams | Sustainable live operations | Clear runbooks, support boundaries, SLOs, and DR approach |

### Business Value Metrics

| Metric | Target | Rationale |
|---|---|---|
| Self-service containment for in-scope intents | ≥ 45% within 6 months of go-live | Material queue deflection without over-automating sensitive journeys |
| Average handling time reduction for routine enquiries | 20–30% | Shared tooling and faster retrieval of account/product information |
| Authentication-to-resolution cycle time | < 3 minutes for standard balance/card requests | Directly tied to customer effort and telephony cost |
| Human transfer quality score | ≥ 90% handoff package completeness | Ensures L2/L3 advisers receive usable context |
| Audit event completeness | 100% of Tier 1 and Tier 2 tool invocations recorded | Required for compliance and dispute investigations |
| PII prompt leakage incidents | 0 tolerated | Foundational control for AI risk management |
| Vulnerable customer escalation accuracy | ≥ 95% for flagged sessions | Supports Consumer Duty outcomes and specialist routing |

The business case assumes ARIA is introduced as an augmentation and containment capability, not as a full replacement for human advisers. The value is highest where the request is information retrieval or controlled action execution and where channel volume is high enough that reducing routine workload materially improves queue performance.

The design also creates strategic value for Meridian Bank's wider AI roadmap. Because the same reasoning and tool layer can be invoked by Amazon Connect, direct web clients, or Bedrock AgentCore clients, the bank can expand channels without rewriting the core service logic or weakening operational governance.

## Service Scope

### In-Scope

- Retail banking self-service conversations for account, card, mortgage, spending, product, and FAQ queries.
- Amazon Connect voice and chat routing into ARIA experiences.
- Direct AgentCore chat over `POST /invocations` and direct AgentCore voice over `WS /ws`.
- Session-scoped customer authentication and KBA handling using the ARIA toolchain.
- PII detection, redaction, vaulting, retrieval, and purge within session boundaries.
- Retrieval of customer profile and product context for personalised greeting and resolution logic.
- Bedrock Knowledge Base lookups for policies, products, and service guidance.
- Three-tier auditing of sensitive tool actions.
- Human-agent escalation with transcript summary generation and session closure handling.
- AgentCore Memory persistence of redacted conversation history only.

### Out-of-Scope

- Payments initiation, funds transfer, standing-order amendments, and direct debit creation.
- Regulated financial advice, suitability recommendations, investment guidance, or collections negotiation.
- Loan origination, underwriting, or policy decisions.
- Branch servicing, teller workflows, or non-retail-bank brands.
- Back-office case management after transfer to human agents.
- Bulk outbound campaigns, debt collection automation, or complaint adjudication.
- Storage of raw PII, full PAN, PIN, CVV, or security secrets in model context or long-term memory.

### Service Boundaries

The service boundary starts at the conversational ingress point: Amazon Connect for telephony/chat or Bedrock AgentCore for direct cloud-hosted traffic. Within the boundary, ARIA owns session initiation, tool orchestration, voice or chat response generation, transcript persistence, session memory, and audit emission.

The service boundary ends at the interface to downstream banking systems, knowledge repositories, audit sinks, and human-agent transfer workflows. ARIA invokes those systems but does not own their data quality, upstream entitlement logic, or downstream human case resolution.

Where Amazon Connect is the front door, contact-flow logic, queue management, phone numbers, and live agent staffing remain controlled by the contact-centre platform team. ARIA is therefore a dependent service within the broader customer-contact value stream rather than the sole operational system.

## Technical Architecture

### Architecture Overview

ARIA Banking Agent is implemented as a layered conversational service. The front layer handles omni-channel ingress and session establishment. The middle layer runs the Strands agent and model interfaces inside Bedrock AgentCore Runtime. The control layer enforces prompt policy, PII vaulting, session memory, and audit generation. The integration layer connects to banking tools, knowledge sources, and operational telemetry sinks.

`aria/agent.py` resolves the Bedrock model for the current AWS region and creates the Strands `Agent` object with the shared tool list. `aria/agentcore_app.py` manages session affinity, HTTP chat requests, transcript managers, response cleaning, and asynchronous memory persistence. `aria/agentcore_voice.py` manages WebSocket audio, Nova Sonic streaming, stream renewal before the 600-second hard limit, transcript emission, and voice-side tool execution. The architecture is channel-aware but code-shared by design.

### Component Diagram in ASCII/text

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Customer Channels                                                            │
│  1) Amazon Connect Chat                                                      │
│  2) Amazon Connect Voice / PSTN                                              │
│  3) Direct AgentCore HTTPS Chat + WSS Voice                                  │
└───────────────┬───────────────────────────────┬──────────────────────────────┘
                │                               │
                ▼                               ▼
┌────────────────────────────┐     ┌──────────────────────────────────────────┐
│ Amazon Connect Flows       │     │ Bedrock AgentCore Runtime                │
│ - Contact routing          │     │ - POST /invocations                      │
│ - Connect assistant block  │     │ - WS /ws                                 │
│ - Session injector Lambda  │     │ - Per-session microVM affinity           │
│ - Queue / transfer control │     └────────────────┬─────────────────────────┘
└───────────────┬────────────┘                      │
                │                                   ▼
                │                     ┌────────────────────────────────────────┐
                │                     │ ARIA Orchestration Layer              │
                │                     │ - Strands Agent                       │
                │                     │ - Claude Sonnet 4.6 (chat)            │
                │                     │ - Nova Sonic 2 (voice)                │
                │                     │ - 20 core banking tools               │
                │                     └───────────────┬────────────────────────┘
                │                                     │
                ▼                                     ▼
┌────────────────────────────┐     ┌──────────────────────────────────────────┐
│ Control & Safety Services  │     │ Banking / Knowledge Integrations         │
│ - PII detect + redact      │     │ - Customer/profile/account tools         │
│ - Vault refs: vault://...  │     │ - Card, mortgage, spending tools         │
│ - AgentCore Memory         │     │ - Bedrock Knowledge Base                 │
│ - Transcript manager       │     │ - Escalation to human agent              │
│ - Audit manager            │     │ - Session/context injection              │
└───────────────┬────────────┘     └───────────────┬──────────────────────────┘
                │                                  │
                ▼                                  ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Observability and Evidence                                                   │
│ - EventBridge custom bus                                                     │
│ - CloudTrail Lake                                                            │
│ - DynamoDB audit/event stores                                                │
│ - S3 transcripts and immutable archives                                      │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Technology Stack

| Layer | Technology | Role in Service |
|---|---|---|
| Language | Python | Primary implementation language for the banking agent and Lambda support components |
| Orchestration | Strands Agents | Tool-aware reasoning and channel-independent agent behaviour |
| Chat model | Anthropic Claude Sonnet 4.6 on Bedrock | High-quality text reasoning for chat sessions and tool selection |
| Voice model | Amazon Nova Sonic 2 | Low-latency speech-to-speech generation for live voice conversations |
| Runtime | Amazon Bedrock AgentCore Runtime | Cloud-hosted execution surface for chat and voice channels |
| Telephony / chat routing | Amazon Connect | PSTN connectivity, queueing, chat sessions, and human transfer control |
| Memory | Bedrock AgentCore Memory | Retrieval of recent redacted turns for contextual continuity |
| Session state | AgentCore per-session microVM memory + DynamoDB-backed context injectors | Session affinity and contextual enrichment |
| Knowledge | Amazon Bedrock Knowledge Base | Retrieval of FAQ, product, and process content |
| Persistent transcripts | Amazon S3 | Transcript storage and controlled retrieval |
| Audit bus | Amazon EventBridge | Fan-out of structured audit events |
| Audit query store | Amazon DynamoDB | Hot-path operational and investigation queries |
| Immutable audit evidence | CloudTrail Lake and S3 WORM pattern | Long-term evidential retention |
| Identity | Amazon Cognito + IAM + OBO propagation pattern | Channel authentication and downstream authorisation context |
| API / transport | HTTPS, WebSocket, SigV4 | Client-to-runtime transport for chat and voice |

### Integration Points

| Integration Point | Direction | Purpose | Notes |
|---|---|---|---|
| Amazon Connect contact flows | Inbound | Voice/chat routing into ARIA | Provides queue control, assistant invocation, and escalation exit paths |
| Session injector Lambda | Inbound control | Injects `sessionId`, `customerId`, auth, vulnerability, and prior-summary context | Executed after Connect assistant block for prompt variable population |
| `POST /invocations` | Inbound API | Direct chat invocation | Managed by `aria/agentcore_app.py` |
| `WS /ws` | Inbound API | Direct voice session with PCM audio | Managed by `aria/agentcore_voice.py` |
| Bedrock model APIs | Outbound | Text and voice generation | Claude Sonnet for chat; Nova Sonic 2 for streaming voice |
| Bedrock Knowledge Base | Outbound | Policy and FAQ retrieval | Used by `search_knowledge_base` |
| Customer/product tools | Outbound | Banking data retrieval and controlled actions | Shared across channels |
| AgentCore Memory | Outbound | Retrieve/save recent redacted turns | Explicitly excludes vault-stored PII |
| EventBridge audit bus | Outbound | Publish structured tool audit events | Downstream rules route to evidence stores |
| S3 transcript store | Outbound | Persist transcripts after turns and on close | Supports customer-service evidence and transfer context |

## Service Interfaces

### APIs/Contracts

| Interface | Method / Protocol | Contract Summary | Consumer |
|---|---|---|---|
| Chat invocation | `POST /invocations` | Accepts `message`, optional `authenticated`, optional `customer_id`, and optional channel/context metadata | Direct clients, integration proxies, Connect-linked services |
| Health check | `GET /ping` | Runtime liveness probe handled by framework | Load balancer, deployment automation |
| Voice session | `WS /ws` | Accepts `session.config` then binary PCM audio; returns transcript events and binary audio | Browser/mobile voice clients or proxy services |
| Session injector | Lambda invocation | Receives Connect contact event and updates Q Connect session data | Amazon Connect contact flow |
| Tool contract | JSON schema per Strands tool | Validated argument schema per banking tool | Internal model/tool runtime only |
| Audit event contract | EventBridge event detail JSON | Structured tool invocation record including tier, severity, session, customer, and masked parameters | Evidence pipeline consumers |

The chat API returns plain text responses after markdown cleanup so that upstream clients and Connect prompts receive presentation-ready content. The first chat turn can include pre-auth context, after which session metadata is cached per session inside the AgentCore microVM to avoid repeated caller-side injection.

The voice API uses a strict WebSocket protocol. The client sends a `session.config` frame first, then streams raw 16 kHz 16-bit mono PCM audio. The server returns text control messages such as `session.started`, `transcript.user`, `transcript.aria`, `session.ended`, and binary 24 kHz mono PCM for ARIA's spoken output. This contract keeps the transport simple while allowing barge-in, transcript fan-out, and stream renewal behind the scenes.

### Event/Message Interfaces

| Event / Message | Producer | Consumer | Purpose |
|---|---|---|---|
| `SESSION_START` injection | Chat handler or Connect injector | ARIA agent prompt context | Tells ARIA whether the customer is authenticated and what context to load |
| `vault://session_id/TOKEN_KEY` references | PII vault tools | Other tools inside ARIA | Keeps raw PII out of model context and reasoning traces |
| `BankingAuditEvent` | Audit manager | EventBridge downstream rules | Immutable record of data access, auth, escalation, and card actions |
| Transcript save operations | Transcript manager | S3 and operations tooling | Preserve conversation evidence and support transfer summaries |
| AgentCore Memory save/retrieve | Memory wrapper | AgentCore Memory | Maintain recent redacted conversation continuity |
| Escalation metadata | `escalate_to_human_agent` tool | Amazon Connect / adviser flow | Provides handoff reference, wait time, and context package |

### UI Interfaces

- Amazon Connect agent and customer experiences use Connect-managed voice and chat surfaces, with ARIA acting as the AI assistant invoked by the flow.
- Direct digital consumers use HTTPS chat clients or WebSocket voice clients that integrate with AgentCore runtime endpoints.
- Human advisers receive the transferred interaction downstream in their standard contact-centre tooling, enriched by structured summaries rather than raw model conversation only.
- There is no independent public ARIA administration console in the current service boundary; platform observability is handled through AWS and support tooling.

## Service Dependencies

### Internal Dependencies

| Dependency | Type | Dependency Reason |
|---|---|---|
| `aria/agent.py` | Core runtime | Creates the Strands agent and resolves Claude Sonnet model selection per region |
| `aria/agentcore_app.py` | Core runtime | Handles HTTP chat sessions, transcript save, session cache, and memory persistence |
| `aria/agentcore_voice.py` | Core runtime | Handles Nova Sonic bidirectional voice sessions and tool execution over WebSocket |
| `aria/system_prompt.py` | Policy control | Encodes banking, vulnerability, and PII handling instructions |
| `aria/tools/*` | Domain integration | Implements the banking toolset used across every channel |
| `aria/audit_manager.py` | Compliance control | Builds and dispatches structured audit events |
| `aria/memory_client.py` | Continuity control | Saves and retrieves recent redacted turns from AgentCore Memory |
| Session injector Lambdas | Contact-centre integration | Populate Connect/Q Connect session variables prior to agent response |
| Transcript manager | Operational evidence | Persists session transcripts for support and investigation |

### External Dependencies table

| External Service / Component | Criticality | Usage | Failure Impact |
|---|---|---|---|
| Amazon Bedrock AgentCore Runtime | Critical | Hosts chat and voice entrypoints | Service unavailable for direct invocation channels |
| Amazon Bedrock model endpoints | Critical | Claude Sonnet and Nova Sonic inference | Customer response generation unavailable or degraded |
| Amazon Connect | Critical | Telephony, chat routing, queueing, transfer | No contact ingress or live transfer capability |
| Amazon Bedrock Knowledge Base | High | FAQ/product retrieval | Reduced answer quality for informational queries |
| DynamoDB | High | Session context, memory summaries, audit hot store | Loss of context enrichment and slower investigations |
| Amazon S3 | High | Transcript storage and audit/archive patterns | Reduced evidential retention and post-incident review capability |
| Amazon EventBridge | High | Audit event fan-out | Audit gap risk if not buffered or recovered |
| CloudTrail Lake | High | Immutable audit evidence | Reduced regulatory evidencing quality |
| Amazon Cognito / IAM | Critical | Authentication and authorisation context | Direct-channel auth failures and invocation denial |
| Core banking / CRM services | Critical | Customer profile and product lookups via tools | In-scope journeys cannot be completed safely |

ARIA is intentionally dependent on managed AWS services with strong availability characteristics. The dependency posture is acceptable for a Tier 1 service because each dependency is explicit, observable, and either recoverable or triggers a safe degrade mode such as transfer to human support.

The architecture avoids hidden dependencies by keeping tool execution and audit emission inside the service boundary. Where third-party or legacy core-banking dependencies are introduced later, they must inherit the same control requirements documented here, especially around latency, evidencing, and customer-data handling.

## Service Level Objectives

### Target Service Levels

| Objective | Target | Measurement Approach |
|---|---|---|
| Monthly availability | 99.95% | Successful invocation rate across AgentCore and Connect-integrated service windows |
| Chat first meaningful response | p95 ≤ 4 seconds | Measured from accepted request to first customer-visible response |
| Tool-backed routine resolution | p95 ≤ 8 seconds | Account/card/mortgage read flows without human transfer |
| Voice post-endpoint response latency | p95 ≤ 1.8 seconds | Time from customer end-of-speech to first ARIA speech frame |
| Authentication completion success | ≥ 98% for valid customer journeys | Valid sessions passing KBA or pre-auth entry without platform fault |
| Audit publication success | 100% of Tier 1/Tier 2 actions | Successful local write or EventBridge publish with downstream reconciliation |
| Transcript persistence success | 99.9% | Transcript save completion per session |

### Availability, Throughput, and Recovery Targets

| Dimension | Target | Notes |
|---|---|---|
| Concurrent chat sessions | Scale horizontally by AgentCore session allocation; initial production capacity 200 concurrent sessions per environment | Session affinity handled by AgentCore microVM routing |
| Concurrent voice sessions | Initial production planning baseline of 60 active voice sessions per environment | Voice sessions consume streaming model and Connect capacity |
| RTO | 60 minutes | Includes runtime recovery, environment redeploy, and contact-flow failover actions |
| RPO | 15 minutes for operational context, near-zero for immutable audit events | Audit should be event-driven; session context may be rebuilt from recent transcripts |
| Planned maintenance | Zero customer-visible downtime target | Use blue/green or staged rollout with Connect entrypoint control |

These SLOs are designed for a banking service where graceful failure matters as much as raw speed. ARIA is permitted to trade a small amount of latency for safe authentication, safe data retrieval, and reliable audit emission, but it is not permitted to fail open or silently skip evidence generation.

Any breach of the availability, audit-completeness, or PII-protection objectives is treated as a material service event. For that reason, observability and operational response are defined as first-class service requirements rather than post-deployment enhancements.

## Operational Model

### Support Tiers table — L1/L2/L3

| Support Tier | Team | Responsibilities | Typical Triggers |
|---|---|---|---|
| L1 | Service desk / contact-centre operations | Initial triage, dashboard review, confirm customer impact, invoke known workarounds, communicate incidents | Customer complaints, chat/voice unavailable, elevated transfer rate |
| L2 | AI platform operations + Amazon Connect operations | Diagnose runtime health, Connect flow issues, session injection failures, memory/audit degradations, scaling actions | Persistent latency, EventBridge publish failures, failed greetings, auth anomalies |
| L3 | ARIA engineering / platform engineering / security engineering | Code-level defects, prompt-policy changes, tool bugs, IAM or model integration failures, DR decisions | Sev1/Sev2 incidents, repeated regressions, control failures |

### On-Call Model

- 24x7 primary on-call for Tier 1 production incidents affecting customer access, authentication, escalation, or audit evidencing.
- Secondary on-call shared between AI platform engineering and Amazon Connect operations for integration incidents.
- Security on-call engaged immediately for suspected PII leakage, anomalous audit gaps, identity mismatch spikes, or abusive access patterns.
- Business-hours service owner coverage for change approvals, KPI review, and problem-management follow-through.

### Incident Classification

| Severity | Definition | Example |
|---|---|---|
| Sev1 | Customer-critical outage or control failure | Voice and chat unavailable, raw PII entering prompts, audit trail missing for sensitive actions |
| Sev2 | Major degradation with workaround | Elevated latency, KB unavailable but transfers functioning, repeated session injector failure |
| Sev3 | Limited-impact defect | Incorrect greeting behaviour, isolated transcript save issue, non-critical dashboard problem |
| Sev4 | Minor enhancement or observation | Tuning request, non-production issue, cosmetic logging improvement |

Operationally, ARIA must default to safe handling. If a downstream dependency cannot confirm customer context or complete a sensitive tool action, the correct service behaviour is controlled transfer or polite deferral rather than speculative answer generation.

The support model assumes that ARIA incidents may span application, model, contact-centre, and cloud-platform domains. Joint triage is therefore mandatory for Sev1 and Sev2 events, with one incident commander appointed per event regardless of which team first detects the issue.

## Security & Compliance

### Security Classification

The service processes customer identity data, account metadata, card information in masked form, vulnerability indicators, and operational audit evidence. The service itself is therefore classified as Internal, while the data it handles is treated as Confidential Banking Data with additional controls for PCI-adjacent and vulnerable-customer information.

### AuthN/AuthZ

- Direct digital channels use Amazon Cognito-backed authentication with IAM/SigV4 invocation control and on-behalf-of context propagation for downstream services.
- Connect-routed sessions use contact attributes and session-injection patterns to convey authentication state, customer ID, locale, and vulnerability context.
- The system prompt enforces a hard authentication gate: no customer data access before identity verification or confirmed pre-auth context.
- IAM roles are used for Bedrock, EventBridge, DynamoDB, S3, Connect, and CloudTrail interactions; least privilege is mandatory for production roles.
- Session identifiers are used as correlation keys, not as proof of identity.

### Data Classification

| Data Type | Classification | Handling Rule |
|---|---|---|
| Product FAQs and public policy content | Internal/Public | May be retrieved into model context |
| Customer identifiers and profile references | Confidential | Use only after auth; minimise exposure in responses |
| Full PII such as account number, mobile, DOB | Restricted | Must be redacted and vaulted; never reason over raw values |
| Card data | Restricted / PCI-adjacent | Last four only in conversation; full PAN/CVV/PIN prohibited |
| Vulnerability flags | Highly sensitive operational data | Silent context only; never disclosed back to the customer |
| Audit events | Confidential evidential records | Immutable retention and controlled access |
| Conversation history in memory | Confidential, redacted | AgentCore Memory stores redacted turns only |

### Regulatory Requirements

- UK GDPR and data-minimisation obligations for customer data handling.
- FCA Consumer Duty and fair treatment requirements, especially for vulnerable customers.
- PCI-DSS-aligned controls for payment-card-related information.
- Internal records-retention requirements for financial-service interactions and complaint investigations.
- Auditability standards compatible with enterprise service management and security operations.

The primary security design choice is that raw PII never becomes prompt context. The system prompt and tool chain require `pii_detect_and_redact`, optional `pii_vault_store`, just-in-time `pii_vault_retrieve`, and `pii_vault_purge`, using `vault://session_id/TOKEN_KEY` references rather than raw values. This is stronger than simple prompt redaction because it constrains the model's working set by design.

The second material control is evidential completeness. `aria/audit_manager.py` classifies tools into critical, significant, and informational tiers and emits structured events with masked parameters. In cloud deployment those events are sent through EventBridge to CloudTrail Lake and DynamoDB so that every sensitive access or action can be reconstructed without relying solely on model traces or application logs.

## Capacity & Scalability

### Current Capacity

The current architecture is suitable for phased production rollout to Meridian Bank's retail support channels. AgentCore provides per-session microVM affinity for conversational isolation, Amazon Connect scales independently for telephony and chat ingress, DynamoDB can operate in on-demand mode for context and audit access, and EventBridge and S3 provide effectively elastic downstream handling.

Voice capacity is governed primarily by streaming model concurrency, Connect concurrency, and the ability to maintain low post-endpoint response latency during peak traffic. Chat capacity is governed more by model throughput and downstream banking-tool latency. Because the service is stateless between persisted checkpoints other than active session state, horizontal scale is the preferred mechanism for growth.

### Scaling Approach

- Scale AgentCore runtime capacity horizontally by environment and traffic class.
- Separate chat and voice concurrency planning because voice sessions are longer-lived and latency-sensitive.
- Use DynamoDB on-demand or provisioned auto scaling for session-injector and audit query stores.
- Keep transcript and audit sinks decoupled via EventBridge and S3 so write spikes do not block customer responses.
- Pre-warm or stage region-specific model access for Claude Sonnet and Nova Sonic to avoid cold-path delays.
- Use Amazon Connect queue management and overflow routing to maintain customer-service continuity under saturation.

### Known Limits

| Limit | Current Behaviour | Operational Consideration |
|---|---|---|
| Nova Sonic streaming session hard limit | 600 seconds cumulative input audio | `aria/agentcore_voice.py` renews streams around 560 seconds to hide expiry |
| Voice transport assumptions | 16 kHz mono input, 24 kHz mono output | Client integrations must match codec expectations |
| Session memory contents | Redacted turns only | Prior context quality depends on earlier redaction quality and memory availability |
| Tool latency | Bounded by downstream banking and KB systems | High-latency tools may force transfer if service target cannot be met |
| Connect dependency | Required for PSTN and managed chat routing | Direct AgentCore channels can continue even if Connect is degraded |
| Audit sink dependency | EventBridge preferred in cloud mode | Local JSONL write may provide fallback in constrained environments |

Capacity planning should assume material growth after successful introduction because good containment drives adoption. The service should therefore be treated as a reusable platform capability with quarterly capacity review rather than a one-off channel integration.

## Monitoring & Observability

### Key Metrics

| Metric Family | Example Metrics | Why It Matters |
|---|---|---|
| Availability | successful invocations, WS connect success, Connect contact success | Detects customer-visible outages |
| Experience | response latency, greeting latency, transfer rate, abandonment rate | Measures service quality and containment |
| Safety | PII-vault usage rate, auth failures, mismatch rate, vulnerability escalation count | Detects control drift or unsafe behaviour |
| Model | Claude/Nova invocation errors, stream renewals, token usage, model throttling | Highlights inference or quota issues |
| Tooling | per-tool error rate, KB lookup latency, banking data access latency | Isolates integration bottlenecks |
| Evidence | audit publish success, transcript save success, memory save/retrieve failures | Confirms regulatory and support readiness |

### Logging Strategy

- Structured application logging is configured in `aria/agentcore_app.py` with rotating file handlers and console output.
- Voice sessions log lifecycle events, stream renewals, transcript milestones, and audio/session exceptions.
- Audit events are emitted separately from application logs so security evidence is not dependent on log parsing.
- Session IDs, customer IDs, contact IDs, and handoff references are the primary correlation keys across logs, traces, transcripts, and audits.
- Third-party library noise is intentionally reduced for `strands`, `boto3`, `botocore`, and related libraries to preserve signal quality.

### Alerting Thresholds

| Alert | Threshold | Response |
|---|---|---|
| Availability breach | > 2% failed invocations in 5 minutes | L2 investigation, incident bridge if sustained |
| Voice greeting failure | > 5 consecutive sessions without opening greeting | Check Nova Sonic, session injector, and flow configuration |
| Audit publication failure | Any Tier 1/Tier 2 audit event not persisted within 1 minute | Treat as Sev1 control incident |
| PII vault anomaly | Sudden drop in redaction/vault calls for PII-heavy journeys | Security review for control bypass |
| Auth mismatch spike | 3x normal baseline in 15 minutes | Fraud/security investigation |
| Transcript save failure | > 1% in 15 minutes | Storage and runtime investigation |

### Dashboards

- Executive dashboard for containment, transfer rate, and customer experience trends.
- Operations dashboard for live session counts, latency, and dependency health.
- Security dashboard for auth anomalies, PII control metrics, and audit completeness.
- Engineering dashboard for tool error rates, model failures, and runtime saturation.

Observability for ARIA is not limited to runtime health. Because the service operates in a regulated domain, the platform must prove that controls fired when they should, not merely that requests completed. Dashboards and alerts therefore combine customer metrics with control-evidence metrics.

## Disaster Recovery & Business Continuity

### DR Strategy

The service uses a managed-cloud DR posture centred on rapid redeployment and durable evidence storage. Amazon Connect and Bedrock managed services provide multi-AZ resilience within region, while S3 and DynamoDB provide durable storage for transcripts, context, and audit events. AgentCore workloads are treated as disposable compute and must be redeployable from version-controlled artefacts and configuration.

### RTO/RPO Targets

| Recovery Dimension | Target |
|---|---|
| Service RTO | 60 minutes |
| Audit evidence RPO | Near-zero for EventBridge-driven events |
| Transcript / operational context RPO | 15 minutes |
| Contact-flow recovery | 30 minutes for fail-forward or rollback |

### Failover Approach

- Prefer in-region fail-forward using blue/green runtime replacement and contact-flow switchback.
- Retain the ability to route customers directly to human queues if ARIA is unavailable or unsafe.
- Preserve phone-number and queue continuity in Amazon Connect even during ARIA runtime rollback.
- Maintain backup deployment artefacts, IAM roles, and environment configuration for secondary-region recovery if a regional event occurs.
- Test transcript and audit recovery independently from runtime recovery because regulatory continuity matters even after service failback.

The business-continuity posture assumes that the bank can continue serving customers manually even if ARIA is withdrawn. Accordingly, the most important DR requirement is a clean and rapid path to safe disablement and human-only routing, followed by controlled restoration once the issue is understood.

## Service Transition Plan

### Transition Phases table

| Phase | Objective | Key Activities | Exit Criteria |
|---|---|---|---|
| Design assurance | Confirm target-state service design | Architecture review, threat modelling, data classification, control mapping | Signed-off design and risk treatment plan |
| Non-production validation | Prove functional and control behaviour | Channel testing, KBA tests, vulnerability scenarios, audit reconciliation, load tests | Test evidence approved by engineering and security |
| Operational readiness | Prepare support and monitoring | Runbooks, dashboards, on-call rota, incident drills, access reviews | Support sign-off and CAB readiness |
| Pilot go-live | Limited exposure with close oversight | Controlled queue/channel release, hypercare, KPI review | Stable performance and no material control breaches |
| General availability | Broaden rollout | Expand queues/hours/channels, formal KPI acceptance | Service owner and CAB approval |

### Acceptance Criteria

- All in-scope journeys pass functional validation across chat and voice.
- PII vaulting and purge behaviour is demonstrated on representative banking scenarios.
- Tier 1 and Tier 2 audit events are visible in CloudTrail Lake and DynamoDB with correct masking.
- Vulnerable-customer prompts and escalation flows behave as designed in simulation and UAT.
- Connect session injection provides correct customer/auth context without greeting regressions.
- Transcript persistence, memory retrieval, and handoff summary generation are verified.
- Support teams have approved runbooks, dashboards, contact points, and incident procedures.

### Go-Live Checklist

- [ ] Production IAM roles reviewed and least privilege confirmed.
- [ ] Bedrock model access confirmed in target region(s).
- [ ] Amazon Connect flows, queues, phone numbers, and assistant bindings published.
- [ ] Session injector Lambda deployed and permissions validated.
- [ ] EventBridge rules, DynamoDB tables, and CloudTrail Lake channels active.
- [ ] S3 transcript bucket retention and encryption policies confirmed.
- [ ] Alerting, dashboards, and pager integration tested.
- [ ] Known-risk sign-offs recorded and CAB approval obtained.
- [ ] Hypercare rota published for first production window.

## Training & Knowledge Transfer

### Training Requirements

| Audience | Training Focus |
|---|---|
| L1 service desk | Service overview, known issues, ticket triage, escalation paths |
| L2 operations | Connect flows, AgentCore runtime behaviours, audit and transcript validation |
| L3 engineering | Tool contracts, prompt policy, model troubleshooting, DR procedures |
| Security / compliance | Audit evidence retrieval, PII control model, vulnerability handling review |
| Contact-centre leadership | KPI interpretation, containment strategy, fallback model |

### Documentation Links

- `docs/aria-amazon-connect-architecture.md`
- `docs/aria-connect-voice-chat-novice-guide.md`
- `aria/agent.py`
- `aria/agentcore_app.py`
- `aria/agentcore_voice.py`
- `aria/audit_manager.py`
- `aria/memory_client.py`
- `scripts/lambdas/session_injector.py`
- `scripts/lambdas/audit_cloudtrail_writer.py`
- `scripts/lambdas/audit_dynamodb_writer.py`

### Knowledge Transfer Plan

- Engineering walkthrough covering channel entrypoints, tool architecture, and control layers.
- Operational walkthrough covering dashboards, common incident signatures, and safe fallbacks.
- Security/compliance walkthrough demonstrating end-to-end evidence for authentication, data access, and escalation.
- Hypercare shadowing for the first production release window, followed by retrospective and documentation updates.

Knowledge transfer is considered complete only when receiving teams can execute a simulated incident, locate audit evidence, and explain the safe-disable process without engineering prompting.

## Risk Register

| ID | Risk | Category | Probability | Impact | Mitigation | Owner | Status |
|---|---|---|---|---|---|---|---|
| ARB-R01 | Downstream banking-tool latency causes poor customer experience or forced transfers during peak demand. | Performance / Dependency | Medium | High | Set tool latency budgets, alert on breach, cache low-risk knowledge content, and route to human support when SLA cannot be met safely. | [OWNER_NAME] | Open |
| ARB-R02 | PII control bypass or incorrect vault usage exposes raw personal data to model context. | Security / Compliance | Low | Critical | Enforce prompt-level mandatory pipeline, add regression tests, monitor vault-call patterns, and treat any breach as Sev1. | [OWNER_NAME] | Open |
| ARB-R03 | Session injector failure leads to wrong greeting, missing auth state, or missing vulnerability context in Connect journeys. | Operations / Integration | Medium | High | Health-check Lambda placement and permissions, add synthetic tests, and fail safe to human routing if context is incomplete. | [OWNER_NAME] | Open |
| ARB-R04 | Audit events fail to reach immutable storage, weakening evidential posture for sensitive actions. | Compliance / Resilience | Low | Critical | EventBridge monitoring, reconciliation jobs, fallback local write where applicable, and release gate requiring audit-path validation. | [OWNER_NAME] | Open |
| ARB-R05 | Model or prompt drift produces inconsistent vulnerable-customer handling or escalation quality. | AI Governance | Medium | High | Version prompts, run scenario regression packs, review escalations with compliance, and maintain controlled release approvals. | [OWNER_NAME] | Open |
| ARB-R06 | Voice-session scale or Nova Sonic quota constraints create queue backlogs during demand spikes. | Capacity | Medium | High | Pre-plan concurrency, reserve quotas, maintain transfer fallback, and scale release exposure gradually. | [OWNER_NAME] | Open |

## Approvals

| Role | Name | Signature | Date |
|---|---|---|---|
| Service Owner | [NAME] | [NAME] | [DATE] |
| Enterprise Architect | [NAME] | [NAME] | [DATE] |
| Information Security Reviewer | [NAME] | [NAME] | [DATE] |
| Operations Lead | [NAME] | [NAME] | [DATE] |
| Change Advisory Board Chair | [NAME] | [NAME] | [DATE] |
