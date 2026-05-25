# ARIA Platform Master Service Introduction Document

This master Service Introduction Document defines the service-transition baseline, architecture description, and operational governance for the ARIA platform as a whole. It covers the eight component services that collectively deliver Meridian Bank's AI-enabled banking, analytics, evaluation, white-label chat, secure DTMF capture, and contact-centre integration capability across Meridian Bank and Nationwide deployments.

The document is written at platform scope. It therefore emphasises shared control patterns such as Amazon Connect integration, Bedrock and AgentCore usage, the three-tier audit architecture, PII vaulting, white-label channel management, CI/CD, observability, and regulated financial-services resilience obligations.

## Document Control

| Field | Value |
| --- | --- |
| SID ID | SID-ARP-001 |
| Version | 1.0.0 |
| Status | Draft |
| Classification | Internal |
| Owner | [OWNER_NAME] |
| Reviewers | [REVIEWER_NAME], [REVIEWER_NAME] |
| Service Name | ARIA Platform |
| Organisation | Meridian Bank with white-labelled channel support for Nationwide |
| Primary Cloud | AWS |
| Primary Region | Europe (London) with multi-region disaster recovery pattern |

### Revision History

| Version | Date | Author | Summary |
| --- | --- | --- | --- |
| 0.1.0 | [DATE] | [NAME] | Initial platform service introduction draft assembled from repository architecture and component analysis. |
| 0.8.0 | [DATE] | [NAME] | Expanded services catalogue, dependency map, shared security posture, and operating model. |
| 0.9.0 | [DATE] | [NAME] | Added platform-level SLOs, DR targets, transition controls, and risk register. |
| 1.0.0 | [DATE] | [NAME] | Draft baseline issued for architecture, operations, security, and service-transition review. |


## Executive Summary

ARIA Platform is Meridian Bank's consolidated AI and conversational-services platform for retail banking and contact-centre transformation. The repository evidence shows a core ARIA Banking Agent built on Strands Agents and Amazon Bedrock, supporting voice and chat channels, backed by a shared audit architecture, transcript storage, Lambda-based Connect integrations, white-labelled web widgets, evaluation frameworks, secure DTMF capture, and adjacent internal productivity and analytics tools.

At platform level, the design is intentionally service-oriented. Customer-facing widgets such as Meridian Chat Widget and Nationwide Chat Widget do not contain privileged business logic; they feed Amazon Connect and ARIA orchestration services. Connect Lambda Platform provides channel mediation and integration glue. DTMF Secure Capture isolates PCI-sensitive keypad collection. Evaluator services provide quality assurance and regression capability. Connect Analytics Agent provides operational and analytical insight. Brainstorming Agent supports internal ideation and productivity workflows. Together these services form a coherent but modular estate.

The platform context supplied for this SID is AWS-centric and aligned to regulated UK banking expectations. Core services include Amazon Connect, Bedrock models such as Claude Sonnet 4.6 and Nova Sonic 2, AgentCore Runtime, Lambda, DynamoDB, S3, EventBridge, Cognito, CloudFront, and Systems Manager, with CI/CD via GitHub Actions and observability through CloudWatch and Dynatrace. The repository README and operational guides additionally evidence shared cross-cutting controls: a PII vault pipeline, a three-tier audit trail using EventBridge, DynamoDB, CloudTrail Lake, and S3 WORM, and deployment automation for Connect-adjacent workloads.

This SID positions ARIA Platform as a governed banking platform rather than a collection of experiments. It therefore defines a platform services catalogue, shared security posture, tiered service objectives, dependency governance, operational support model, business continuity expectations, and platform-wide transition criteria required for formal service introduction.


## Service Description

| Attribute | Definition |
| --- | --- |
| Name | ARIA Platform |
| Classification | Multi-service AI banking and contact-centre enablement platform |
| Service Tier | Mixed tier model with platform-wide governance across Tier 1, Tier 2, and Tier 3 services |
| Service Type | AI Banking Platform / Digital Channel and Contact-Centre Platform |
| Category | Customer Engagement, AI Servicing, Contact Centre Integration, Internal Productivity |
| Primary Consumers | Retail banking customers, contact-centre advisors, operations teams, platform engineers, analysts, and internal innovation users |
| Deployment Model | AWS-native managed services plus static front ends, Lambda functions, and AgentCore-hosted runtimes |
| Infrastructure Delivery | CDK + CloudFormation with script-driven deployments and GitHub Actions CI/CD |
| Observability Model | CloudWatch-native telemetry enriched by Dynatrace dashboards, traces, and alerts |

### Platform Services Catalogue

| Component Service | SID ID | Tier | Primary Purpose | Owner | Status |
| --- | --- | --- | --- | --- | --- |
| ARIA Banking Agent | SID-ARB-001 | Tier 1 | Core AI banking assistant for chat, voice, and AgentCore channels | [OWNER_NAME] | Operational baseline |
| ARIA Evaluator | SID-EVL-001 | Tier 2 | Quality evaluation, regression testing, and voice/WebRTC assessment | [OWNER_NAME] | Operational baseline |
| Brainstorming Agent | SID-BSA-001 | Tier 3 | Internal ideation and productivity workspace using Bedrock and SQLite memory | [OWNER_NAME] | Operational baseline |
| Connect Analytics Agent | SID-CAA-001 | Tier 2 | Natural-language analytics and dashboarding for Amazon Connect | [OWNER_NAME] | Operational baseline |
| Connect Lambda Platform | SID-CLP-001 | Tier 1 | Shared serverless integration layer for contact-centre workflows and MCP tools | [OWNER_NAME] | Operational baseline |
| DTMF Secure Capture | SID-DTC-001 | Tier 1 | PCI-sensitive secure keypad capture for payment and verification scenarios | [OWNER_NAME] | Operational baseline |
| Meridian Chat Widget | SID-MCW-001 | Tier 1 | Meridian customer-facing chat entry point | [OWNER_NAME] | Operational baseline |
| Nationwide Chat Widget | SID-NCW-001 | Tier 1 | Nationwide customer-facing chat entry point | [OWNER_NAME] | Operational baseline |

The platform should be understood as a federation of bounded services that share patterns, controls, and infrastructure but not necessarily identical runtime characteristics. This is important when assessing change risk: changes to shared audit or Connect Lambda services can affect multiple customer-facing channels at once, while changes to internal services such as Brainstorming Agent are operationally isolated.


## Business Context

### Business Drivers

- Accelerate digital banking adoption through AI-assisted chat and voice servicing.
- Reduce average handling time and cost-to-serve by increasing safe self-service containment.
- Improve service coverage outside standard contact-centre hours while maintaining regulated controls.
- Provide consistent AI-assisted customer journeys across Meridian's owned channels and white-labelled partner channels.
- Embed auditable, policy-governed AI into customer servicing rather than allowing uncontrolled shadow automation.
- Support regulated financial-services obligations through resilient architecture, strong auditability, and data minimisation.
- Enable rapid experimentation and quality control through evaluator frameworks, scenario testing, and analytics tooling.
- Create reusable platform components such as secure capture and Connect Lambda integrations that can be shared across channels.
- Improve advisor effectiveness through routing, transfer, analytics, and contextual handoff capabilities.
- Provide internal innovation capability through tools such as Brainstorming Agent without contaminating the production banking channel.

### Stakeholders & Personas

| Stakeholder / Persona | Primary Need | Platform Relevance |
| --- | --- | --- |
| Retail banking customer | Fast, trusted help with banking tasks | Consumes ARIA, widgets, voice, and secure capture indirectly |
| Contact-centre advisor | Reliable transfers, context, and secure data handling | Depends on Lambda integrations, DTMF, and routing |
| Contact Centre Operations Manager | Service stability and workforce efficiency | Uses analytics, routing, and platform status |
| Digital Banking Product Owner | Adoption, containment, and customer satisfaction | Owns customer-facing value realisation |
| Compliance and Risk Officer | Auditability and regulated control evidence | Depends on audit trail, PII vault, PCI and FCA controls |
| Security Architect | Secure-by-design patterns and identity propagation | Owns cross-cutting security posture |
| Platform Engineer | Repeatable deployment, observability, and incident response | Runs AWS-native platform services |
| QA / Model Risk / Evaluation Lead | Regression and behavioural assurance | Consumes ARIA Evaluator services |
| Business Analyst / Operations Analyst | Insight into Connect performance and conversational outcomes | Consumes Connect Analytics Agent |
| Internal innovation user | Structured ideation and memory recall | Consumes Brainstorming Agent under lower criticality |

### Business Value Metrics

| Metric | Business Intent | Platform Usage |
| --- | --- | --- |
| Containment rate | Reduce assisted-service cost while preserving quality | Tracked across chat and voice services |
| Average handling time reduction | Improve advisor productivity | Measured where AI containment and transfer are used |
| First-contact resolution | Improve customer outcome quality | Monitored for AI and transferred journeys |
| Digital adoption | Increase use of self-service over telephony or branch | Measured across widgets and voice experiences |
| Evaluation coverage | Ensure safe and repeatable releases | Measured through evaluator scenario runs |
| Audit completeness | Demonstrate regulated traceability | Measured across banking tool and escalation events |
| Secure capture success rate | Protect PCI-sensitive flows while completing journeys | Measured in DTMF Secure Capture service |
| Analytics query success | Improve operational insight for Connect teams | Measured in Connect Analytics Agent |
| Release lead time | Shorten safe delivery cycles | Measured across GitHub Actions and deployment scripts |
| Availability by tier | Demonstrate operational resilience | Measured platform-wide and per component |

The platform is strategically important because it allows Meridian to industrialise AI capability rather than treat it as a one-off chatbot. It combines customer channels, assurance tooling, operational analytics, and governance controls into a single manageable estate, which is essential in a UK retail banking environment where resilience, traceability, and customer trust are inseparable.


## Service Scope

### In-Scope

- The eight platform services listed in the Platform Services Catalogue.
- Shared AWS services and deployment patterns required for Amazon Connect, Bedrock, AgentCore Runtime, Lambda, DynamoDB, S3, EventBridge, Cognito, CloudFront, and Systems Manager usage.
- Shared control patterns including the PII vault pipeline, three-tier audit architecture, transcript storage, and white-label widget model.
- CI/CD controls implemented through GitHub Actions and script-driven deployment automation.
- Platform-wide observability through CloudWatch and Dynatrace.
- Disaster recovery planning, service-level governance, and service-transition controls for the platform estate.

### Out-of-Scope

- Meridian or Nationwide core banking back-office systems not represented in this repository.
- Third-party CRM or case-management solutions except where explicitly integrated by Connect Lambda Platform.
- Bank-wide enterprise IAM or network controls beyond those directly needed to consume the platform.
- Non-ARIA AI experiments or tooling not part of the eight defined services.
- Physical telephony networks and devices outside the logical service boundary of Amazon Connect and bank-managed endpoints.

### Service Boundaries

At platform boundary level, ARIA owns conversational orchestration, supporting channels, supporting Lambda-based integrations, secure capture, evaluation, and operational insight services. It does not replace the bank's source-of-truth systems, identity stores, compliance tooling, or enterprise service desk; instead it integrates with them through controlled interfaces and audit-trace patterns.

The service boundary is also intentionally tiered. Tier 1 services support real customer journeys and regulated operational flows. Tier 2 services support assurance and analytics needed to run the customer estate effectively. Tier 3 services support internal productivity and experimentation but are still governed under shared platform standards.


## Technical Architecture

### Overview

Repository evidence and supplied platform context indicate a hub-and-spoke architecture centred on Amazon Connect and the ARIA Banking Agent. Customer-facing widgets and voice paths enter through Connect and AgentCore-backed orchestration, while shared services such as Connect Lambda Platform, DTMF Secure Capture, audit pipelines, transcript stores, and observability form the cross-cutting backbone. Supporting services such as ARIA Evaluator and Connect Analytics Agent consume the same platform primitives to assess, analyse, and improve service quality.

The core ARIA service uses Strands Agents with Amazon Bedrock models, including Claude Sonnet 4.6 for chat and Nova Sonic 2 for speech-to-speech voice. The repository README explicitly documents a shared PII vault pipeline and three-tier audit architecture, showing a mature focus on regulated-bank controls rather than a purely experimental AI implementation.

### Component Diagram in text/ASCII

```text
                                  +--------------------------------+
                                  | Meridian / Nationwide Customers|
                                  +---------------+----------------+
                                                  |
                           +----------------------+----------------------+
                           |                                             |
                           v                                             v
           +------------------------------+              +------------------------------+
           | Meridian Chat Widget         |              | Nationwide Chat Widget       |
           | SID-MCW-001                  |              | SID-NCW-001                  |
           +---------------+--------------+              +---------------+--------------+
                           |                                             |
                           +----------------------+----------------------+
                                                  |
                                                  v
                                   +-------------------------------+
                                   | Amazon Connect                |
                                   | Chat, Voice, Contact Flows    |
                                   +---------------+---------------+
                                                   |
                     +-----------------------------+------------------------------+
                     |                                                            |
                     v                                                            v
      +-------------------------------+                             +-------------------------------+
      | ARIA Banking Agent            |                             | Connect Lambda Platform       |
      | SID-ARB-001                   |                             | SID-CLP-001                   |
      | Bedrock + AgentCore Runtime   |                             | Routing, fulfillment, MCP     |
      +---------------+---------------+                             +-----------+-------------------+
                      |                                                             |
          +-----------+------------+                                  +-------------+------------+
          |                        |                                  |                          |
          v                        v                                  v                          v
+--------------------+   +-----------------------+      +-----------------------+   +-----------------------+
| DTMF Secure Capture|   | Audit + Transcript    |      | Connect Analytics     |   | ARIA Evaluator        |
| SID-DTC-001        |   | EventBridge/DDB/S3    |      | Agent SID-CAA-001     |   | SID-EVL-001           |
+--------------------+   +-----------------------+      +-----------------------+   +-----------------------+
                                                                 |
                                                                 v
                                                      +-----------------------+
                                                      | Brainstorming Agent   |
                                                      | SID-BSA-001           |
                                                      +-----------------------+
```

### Technology Stack

| Domain | Technology | Platform Role | Notes |
| --- | --- | --- | --- |
| Conversational contact centre | Amazon Connect | Chat, voice, contact flows, routing, transcripts, and advisor handoff | Platform control plane for customer interactions |
| LLM runtime | Amazon Bedrock | Claude Sonnet 4.6 and Nova Sonic 2 inference | Supports both chat and voice patterns |
| AI orchestration | Strands Agents | Agent and tool orchestration framework | Used in ARIA Banking Agent and related services |
| Managed AI hosting | AgentCore Runtime | Hosted chat and WebSocket voice endpoints | Backs ARIA cloud-hosted runtime |
| Serverless compute | AWS Lambda | Connect integrations, MCP tools, routing, status, and support services | Foundation of Connect Lambda Platform and DTMF flows |
| Primary NoSQL store | DynamoDB | Audit index, routing data, transcript and session records, DTMF state | On-demand or quota-managed scaling |
| Object storage | S3 | Static front ends, transcript archives, audit archive, reports, and assets | Used with CloudFront and DR patterns |
| Event bus | EventBridge | Audit fan-out and decoupled event distribution | Key cross-cutting audit control |
| Identity | Amazon Cognito | User authentication and token handling for web-accessible platform surfaces | Aligned with supplied platform context |
| Identity propagation | OBO token pattern | Carries authenticated context into tool calls | Documented in platform OBO guide |
| Front-end delivery | CloudFront | Static site and CDN delivery for customer and internal front ends | Critical for widgets and dashboards |
| Configuration / secrets | Systems Manager and Secrets Manager patterns | Environment and secret distribution | Used across scripts and secure capture |
| IaC | CDK + CloudFormation | Provisioning and repeatable environments | Combined with scripted deployment workflows |
| CI/CD | GitHub Actions | Build, package, and release orchestration | Platform-wide release control plane |
| Observability | CloudWatch + Dynatrace | Metrics, logs, traces, dashboards, alerts | Unified operational and service reporting |
| Languages | Python, TypeScript, JavaScript | Service implementation languages across components | Reflects repo structure |
| Secure capture crypto | RSA + KMS + Secrets Manager | Protect DTMF keypad flows | Supports PCI-sensitive use cases |

### Integration Points

| Integration Point | Participants | Purpose | Governance Concern |
| --- | --- | --- | --- |
| Customer chat entry | Widgets -> Amazon Connect | Start customer chat journeys | Domain allowlist, UX quality, availability |
| Voice interaction | Connect / WebRTC -> ARIA Banking Agent | Speech-to-speech customer servicing | Latency, identity proofing, transcript accuracy |
| MCP tool execution | ARIA Banking Agent -> Connect Lambda Platform | Invoke domain tools and contact-centre support functions | AuthZ, audit, parameter integrity |
| Audit fan-out | ARIA -> EventBridge -> DynamoDB / CloudTrail Lake / S3 | Immutable and queryable tool-call audit trail | Regulatory completeness and retention |
| PII vaulting | ARIA -> PII tool chain | Prevent raw PII entering model context | Security and privacy assurance |
| Secure keypad capture | Connect flows -> DTMF Lambdas | Collect sensitive digits without exposing raw data | PCI-DSS scope and key management |
| Analytics | Connect Analytics Agent -> Connect APIs / Contact Lens | Natural-language operational reporting | Least privilege and data classification |
| Evaluation | ARIA Evaluator -> Connect / WebRTC / Bedrock | Scenario execution and scoring | Safe test isolation and result integrity |
| Internal ideation | Brainstorming Agent -> Bedrock + SQLite | Internal productivity support | Tier separation from customer estate |

### Dependency Map

The platform has several critical dependency chains:

1. Customer-facing widgets depend on CloudFront, S3, approved-origin governance, Amazon Connect, ARIA Banking Agent, and advisor transfer paths.
2. ARIA Banking Agent depends on Bedrock model availability, AgentCore Runtime, shared tools, the PII vault, transcript management, and the three-tier audit pattern.
3. Connect Lambda Platform depends on Lambda execution, DynamoDB, Connect permissions, and in some cases AgentCore endpoint discovery.
4. DTMF Secure Capture depends on Connect contact-flow encryption keys, Secrets Manager, KMS, Lambda, and secure UI components for advisors.
5. ARIA Evaluator depends on scenario libraries, Bedrock judge models, Connect chat or voice interfaces, and report generation stores.
6. Connect Analytics Agent depends on Connect analytics APIs, AgentCore Gateway or direct Lambda fallbacks, Cognito, API Gateway, and dashboard hosting.
7. Brainstorming Agent depends on Bedrock, FastAPI, SQLite memory, WebSockets, and React UI delivery.
8. All services depend on shared CI/CD, observability, security review, and incident-management processes to operate safely as one platform.


## Service Interfaces

### APIs/Contracts

| Interface | Scope | Purpose | Examples |
| --- | --- | --- | --- |
| ARIA AgentCore `/invocations` | Platform API | Chat invocation interface for ARIA Banking Agent | Documented in root README |
| ARIA AgentCore `/ws` | Platform API | Bidirectional voice session interface | WebSocket voice events and PCM streaming |
| Hosted widget `window.amazon_connect` contract | Channel API | Configure and operate browser-hosted chat widgets | Styles, snippet ID, event hooks, content types |
| Lex fulfillment bridge | Integration API | Connect AI / Lex integration with AgentCore | `aria-lex-fulfillment` Lambda path |
| MCP gateway contracts | Tooling API | Expose domain tool capabilities via gateway-managed Lambdas | Auth, customer, cards, products, escalation |
| Connect Analytics REST/UI API | Operational API | Serve dashboards, prompts, transcripts, and analytics views | Express + React dashboard |
| ARIA Evaluator REST API | Internal API | Expose runs, scenarios, reports, transcripts, and settings | Express API with static UI |
| DTMF start / decrypt / validate / status contracts | Secure capture API | Manage keypad-capture sessions and masked outcomes | Lambda invocations from flows and panels |

### Event/Message Interfaces

| Interface | Pattern | Producer | Consumer |
| --- | --- | --- | --- |
| Audit events | EventBridge event | ARIA Banking Agent tools | DynamoDB, CloudTrail Lake, S3 archive |
| Chat messages | Managed chat stream | Customer or ARIA / advisor | Amazon Connect widget and downstream channels |
| Voice audio | PCM / bidirectional stream | Customer and ARIA voice runtime | Nova Sonic / AgentCore / clients |
| Evaluator progress | REST + live progress pattern | ARIA Evaluator API | Evaluator UI |
| Analytics prompt and result payloads | HTTP JSON | Analytics dashboard | Analytics agent backend |
| DTMF session state | DynamoDB item + Lambda response | DTMF functions | Connect flows and advisor panels |
| Deployment and build events | CI/CD workflow events | GitHub Actions | Platform teams and release process |
| Observability telemetry | Metrics, logs, traces | All platform components | CloudWatch and Dynatrace |

### UI Interfaces

| UI Surface | Audience | Platform Role |
| --- | --- | --- |
| Meridian Chat Widget | Meridian customers | Primary public chat ingress |
| Nationwide Chat Widget | Nationwide customers | White-labelled public chat ingress |
| ARIA Evaluator UI | QA, model risk, engineers | Scenario, run, report, and transcript management |
| Connect Analytics dashboard | Operations analysts and supervisors | Natural-language analytics and visual reporting |
| Brainstorming Agent UI | Internal users | Ideation workspace and memory browser |
| CCP status and DTMF panels | Contact-centre advisors | Secure-capture control and session visibility |
| Operational runbooks and playbooks | Support teams | Human-readable operational interface for incidents and changes |

The interface landscape shows that ARIA Platform is not a single application but a governed ecosystem of user interfaces, runtime APIs, and event contracts. Change control must therefore consider interface compatibility, not just code build success.


## Service Dependencies

### Internal Dependencies

- ARIA Banking Agent provides the core customer-facing intelligence layer consumed by customer channels and contact-centre flows.
- Connect Lambda Platform provides shared routing, session injection, fulfillment, and MCP-mediated support services to other platform components.
- DTMF Secure Capture provides PCI-sensitive data collection support for both AI-led and advisor-led journeys.
- ARIA Evaluator provides structured regression and behavioural assurance before and after releases.
- Connect Analytics Agent provides operational insight into the health and effectiveness of the Connect estate.
- Widgets depend on the platform-wide customer-channel integration pattern rather than bespoke channel-specific backends.
- Shared audit, transcript, observability, and deployment patterns are cross-cutting dependencies for almost every service.

### External Dependencies

| Dependency | Type | Used By | Why It Matters |
| --- | --- | --- | --- |
| Amazon Connect | AWS managed service | Banking Agent, widgets, Lambda Platform, analytics, evaluator, DTMF | Primary customer-contact platform |
| Amazon Bedrock | AWS managed service | Banking Agent, evaluator, brainstorming, analytics | LLM and speech model execution |
| AgentCore Runtime | AWS managed service | Banking Agent, analytics gateway patterns, evaluator alignment | Managed hosting for agent endpoints |
| AWS Lambda | AWS managed service | Connect Lambda Platform, DTMF, analytics toolchain, audit writers | Core integration and serverless runtime |
| DynamoDB | AWS managed service | Audit, routing, transcripts, DTMF, analytics state | Low-latency platform persistence |
| S3 | AWS managed service | Widgets, transcripts, reports, audit archive, static content | Durable storage and content delivery origin |
| EventBridge | AWS managed service | Audit and decoupled eventing | Central event fan-out control |
| CloudTrail Lake | AWS managed service | Audit tiering | Immutable queryable compliance record |
| CloudFront | AWS managed service | Widgets and web front ends | Public edge delivery and TLS termination |
| Amazon Cognito | AWS managed service | Web-facing platform surfaces and token propagation | Authentication baseline in supplied platform context |
| Systems Manager / Secrets patterns | AWS managed service | Configuration, keys, and runtime parameters | Secure operational configuration |
| GitHub Actions | CI/CD service | All deployable components | Automated build, release, and change control |
| Dynatrace | Observability platform | All platform components | Unified dashboards, traces, SLOs, and alerting |
| Open-source frameworks | Third-party dependency | React, Vite, FastAPI, Strands, Prisma, Playwright, Chime SDK | Development productivity and runtime capability |

The dependency posture makes supplier and quota governance an important part of service management. Because several Tier 1 services converge on the same AWS-managed foundations, platform resilience must be assessed end-to-end rather than as isolated component uptime.


## Service Level Objectives

### Platform-level SLOs

| Tier | Availability | RTO | RPO | Intended Use |
| --- | --- | --- | --- | --- |
| Tier 1 | 99.9% | 4 hours | 1 hour | Customer-facing or regulated operational services |
| Tier 2 | 99.5% | 8 hours | 4 hours | Operational insight, evaluation, and supporting decision services |
| Tier 3 | 99.0% | 24 hours | 24 hours | Internal productivity or non-customer-critical services |

### Per-component SLO table

| Component | Tier | Availability Target | Latency Target | Throughput Characteristic | RTO | RPO |
| --- | --- | --- | --- | --- | --- | --- |
| ARIA Banking Agent | Tier 1 | 99.9% | Chat response <= 8s p95; voice interaction low-latency speech loop | Concurrent sessions governed by Bedrock, Connect, and AgentCore quotas | 4h | 1h |
| ARIA Evaluator | Tier 2 | 99.5% | Scenario start <= 30s p95; report generation <= 5 min typical | Batch and on-demand evaluation workloads | 8h | 4h |
| Brainstorming Agent | Tier 3 | 99.0% | Interactive response <= 10s p95 for normal prompts | Internal-user session scale | 24h | 24h |
| Connect Analytics Agent | Tier 2 | 99.5% | Query response <= 15s p95 for standard prompts | Analytical workloads with bursty daytime demand | 8h | 4h |
| Connect Lambda Platform | Tier 1 | 99.9% | Routing and Lambda-mediated actions <= 2s p95 typical | Quota-managed Lambda and Connect invocation scale | 4h | 1h |
| DTMF Secure Capture | Tier 1 | 99.9% | Masked result availability <= 6s after digit completion | Concurrent secure-capture sessions governed by Connect/Lambda | 4h | 1h |
| Meridian Chat Widget | Tier 1 | 99.9% | Widget readiness <= 2.5s p95 after page ready | CDN-scale asset delivery, Connect-governed session scale | 4h | 1h |
| Nationwide Chat Widget | Tier 1 | 99.9% | Widget readiness <= 2.5s p95 after page ready | CDN-scale asset delivery, Connect-governed session scale | 4h | 1h |

These SLOs should be reviewed alongside shared dependency health. For example, a Tier 1 widget outage may be caused by a Tier 1 Lambda Platform issue or a Connect origin misconfiguration rather than by the widget codebase. Platform SLO governance must therefore include dependency attribution and error-budget sharing, not just isolated component statistics.


## Operational Model

### Support Tiers L1/L2/L3

| Tier | Primary Team | Responsibilities | Typical Escalation Destinations |
| --- | --- | --- | --- |
| L1 | Service Desk / Operations Centre | Customer-impact triage, incident logging, status validation, comms initiation | Digital Channels, Connect Operations |
| L2 | Platform Engineering / Connect Operations / Application Owners | Component-specific diagnosis, restore service, assess rollback, validate dependencies | AWS Platform, Security, Product Owners |
| L3 | AWS Platform Engineering / Architecture / Security / Model Owners | Deep platform failure analysis, infrastructure remediation, security review, supplier engagement | AWS Support, executive incident management |

### On-Call Model

Platform on-call must be shared across digital channels, Connect operations, and AWS platform engineering because most significant incidents cross service boundaries. A customer may report a widget issue that is actually a Connect-Lambda permission problem, or a voice issue that is actually a Bedrock regional dependency problem. The on-call design must therefore support coordinated rather than siloed incident response.

Hypercare and enhanced change support are required for Tier 1 releases, changes to shared audit and identity controls, Connect-flow restructures, secure-capture changes, and model upgrades. Change windows must include rollback authority, business-owner awareness, and support briefings for affected channels.

### Incident Classification

| Severity | Definition | Typical Platform Example |
| --- | --- | --- |
| P1 | Widespread customer impact, regulatory exposure, or loss of Tier 1 service | Widgets unavailable, ARIA unavailable, DTMF secure capture unusable, or major transfer failure |
| P2 | Material degradation to one major service or important supporting capability | Connect Analytics unavailable during business hours or evaluator outage blocking release confidence |
| P3 | Limited degradation or workaround available | Single brand-shell defect, partial analytics data gap, non-critical dashboard issue |
| P4 | Minor issue or enhancement request | Low-impact UI refinement or documentation correction |


## Security & Compliance

### Security Classification

ARIA Platform is an internal banking platform supporting customer-facing, advisor-facing, and internal workloads. Several platform components process or influence regulated customer journeys, making the effective operational security classification equivalent to a high-assurance internal platform that fronts confidential and, in some services, PCI-sensitive processing.

### AuthN/AuthZ

The supplied platform context identifies Amazon Cognito as the primary authentication mechanism for web-accessible surfaces and OBO token propagation as the identity-propagation model into downstream tool execution. Repository evidence further shows a knowledge-based authentication flow inside the ARIA Banking Agent for customer identity verification, and the root README emphasises that authentication state is validated before privileged banking operations proceed.

- Customer-facing widgets do not hold privileged credentials; they initiate controlled conversations into downstream managed services.
- ARIA Banking Agent uses a shared authentication toolset and KBA flow to validate customers before sensitive actions.
- OBO token propagation ensures downstream tools act in the correct user context rather than as an unrestricted platform identity.
- Lambda execution roles and Connect invoke permissions must remain least-privilege and environment-scoped.
- Secrets, private keys, and sensitive runtime configuration are handled through AWS secret-management patterns, not stored in client code.

### Data Classification

| Data Domain | Classification | Cross-cutting Control |
| --- | --- | --- |
| Public static content | Public / controlled | Release management and integrity control |
| Customer conversational data | Confidential banking interaction data | Connect, transcript management, access control, and retention policies |
| Customer identity and account context | Highly confidential | KBA, OBO propagation, least privilege, audit trail |
| Raw PII | Highly confidential / restricted | PII vault pipeline so raw data never enters LLM context |
| Payment-card input | PCI-sensitive | DTMF secure capture with RSA encryption, KMS, and masked outputs only |
| Audit data | Regulated record | Three-tier storage with immutable and queryable retention paths |
| Evaluation and internal analytics outputs | Internal confidential | Controlled access and segregation from customer production data |

### Regulatory Requirements

| Requirement | Platform Interpretation | Control Response |
| --- | --- | --- |
| PCI-DSS | Applies to secure capture and any payment-adjacent flows | DTMF secure capture pattern, masked output only, strict key handling |
| FCA regulation | Operational resilience, customer communications, outsourcing, and governance | Tiered SLOs, change control, incident response, supplier oversight |
| GDPR | Data minimisation, lawful processing, residency and access control | PII vaulting, UK/EU-centric hosting choices, least data in browser and LLM context |
| DORA | Operational resilience for digital financial services | Platform-wide resilience, DR testing, dependency transparency, monitoring, and auditability |
| Internal audit / model risk | Traceability and controllable AI behaviour | Evaluation framework, prompt-injection testing, immutable audit paths |

A defining cross-cutting security feature is the PII vault pipeline documented in the root README. Raw PII is tokenised and stored out-of-band so the LLM sees only vault references. A second major control is the three-tier audit pattern using EventBridge fan-out to DynamoDB, CloudTrail Lake, and S3 WORM, giving hot, warm, and cold evidence paths for every banking tool call. Together these controls establish a strong regulated-platform posture.


## Capacity & Scalability

### Current Capacity

The platform uses a mixed scaling model. Customer-facing web channels scale through CloudFront and S3. Connect Lambda Platform and DTMF scale through Lambda concurrency and DynamoDB on-demand patterns. ARIA Banking Agent scale depends on AgentCore, Bedrock quotas, Connect chat concurrency, and voice-session capacity. Evaluation and analytics workloads are batch- and prompt-driven, while Brainstorming Agent is an internal-user service with lower concurrency expectations.

| Capacity Area | Current Characteristic | Planning Note |
| --- | --- | --- |
| Customer web entry | CDN and static-origin based | High elasticity for page delivery |
| Conversational concurrency | Governed by Connect, Bedrock, and AgentCore quotas | Quota review is a first-class scaling activity |
| Serverless integration | Lambda-based with per-function concurrency and execution limits | Shared services require quota and blast-radius management |
| State stores | DynamoDB-backed on-demand or quota-managed tables | Supports bursty operational traffic |
| Report and archive storage | S3-backed object storage | Scales well but requires lifecycle and retention control |
| Internal tools | Lower criticality and smaller concurrency profile | Can tolerate slower horizontal growth |

### Scaling Approach

- Scale static front ends through CloudFront and disciplined asset versioning.
- Scale conversational workloads through Connect and Bedrock quota governance, not just code optimisation.
- Use Lambda and DynamoDB elasticity for integration-heavy services while monitoring concurrency exhaustion and hot partitions.
- Treat voice and secure-capture journeys as quota-sensitive because they carry stricter latency expectations.
- Separate Tier 1 capacity dashboards from Tier 2 and Tier 3 services so customer-critical signals are not diluted.
- Rehearse white-label onboarding and cross-brand growth assumptions to prevent configuration bottlenecks from becoming capacity incidents.

### Known Limits

| Limit Area | Known Constraint | Mitigation |
| --- | --- | --- |
| Bedrock model quotas | Can affect chat or voice throughput during spikes | Quota management, regional planning, and graceful degradation |
| Connect approved origins and widget config | Small config errors can create full channel outage | Strict release controls and synthetic validation |
| Lambda concurrency and IAM propagation | Can affect contact-centre integrations | Reserved concurrency planning and deployment sequencing |
| DTMF key rotation complexity | Improper rotation can disrupt payment journeys | Runbook-driven controlled key management |
| Cross-region voice dependency | Nova Sonic availability is region-limited | Documented DR and cross-region access planning |
| Shared dependency blast radius | One common platform defect can hit multiple services | Component isolation, observability, and staged rollout |


## Monitoring & Observability

### Key Metrics

| Metric Family | Examples | Primary Audience |
| --- | --- | --- |
| Availability | Widget launch success, AgentCore endpoint health, Lambda health, API availability | Service Operations |
| Performance | Time to first response, Lambda duration, analytics query latency, evaluator turnaround time | Engineering and Product |
| Reliability | Transfer failure rate, DTMF decrypt errors, chat-start failures, API 5xx rate | Operations and Incident Management |
| Security | Auth failures, OBO mismatch, policy violations, secure-capture anomalies | Security and Risk |
| Compliance | Audit event completeness, transcript write success, key rotation success | Compliance and Internal Audit |
| Business outcomes | Containment, CSAT proxy metrics, evaluation scores, analytics usage | Product and Service Owners |

### Logging Strategy

- Use CloudWatch as the canonical AWS-native telemetry sink for Lambda, AgentCore-connected services, and supporting infrastructure.
- Stream or forward key logs, metrics, and traces into Dynatrace for cross-service dashboards, SLO tracking, and problem correlation.
- Emit structured audit events for banking tool use through EventBridge into the three-tier audit architecture.
- Retain transcript artefacts separately from infrastructure logs to support service review and regulated evidence handling.
- Tag platform components consistently so white-label and tier-specific dashboards can be segmented accurately.

### Alerting Thresholds

| Alert Class | Indicative Threshold | Typical Action |
| --- | --- | --- |
| Tier 1 availability incident | Any sustained failure affecting customer access or secure capture | Immediate incident bridge and coordinated response |
| Lambda error anomaly | Meaningful deviation from baseline or repeated function failure | L2 / L3 platform investigation |
| Audit pipeline failure | Dropped or delayed audit events | Treat as compliance-significant incident |
| DTMF decrypt or validation failure spike | Any sustained pattern beyond background noise | Immediate secure-capture review |
| Evaluation score regression | Release-to-release drop below accepted threshold | Block release progression or trigger remediation |
| Analytics API degradation | Sustained latency or 5xx breach | Operational and platform review |

### Dashboards

The platform should maintain at least four dashboard views: executive service health, Tier 1 operational control room, engineering deep-dive, and security/compliance oversight. The Dynatrace observability guide in the repository already describes a broad monitoring model, including metric streams, log streaming, OpenTelemetry, business events, dashboard segmentation, and SLO governance. That guide should be treated as the detailed observability implementation companion to this master SID.


## Disaster Recovery & Business Continuity

### DR Strategy

The supplied platform context states London as the primary AWS region with multi-region support for disaster recovery. Platform DR therefore combines infrastructure reproducibility, cross-region service activation, static-asset portability, configuration replication, and runbook-driven recovery for quota- and configuration-sensitive services such as Connect, AgentCore-linked runtimes, and DTMF key material.

The platform is not monolithic, so DR must be tier-aware. Customer-facing Tier 1 services require the fastest restoration path and the clearest customer communication plan. Tier 2 and Tier 3 services may recover more slowly, but their recovery sequences must not interfere with Tier 1 restoration.

### RTO/RPO Targets

| Tier | RTO | RPO | Application |
| --- | --- | --- | --- |
| Tier 1 | 4 hours | 1 hour | ARIA Banking Agent, Connect Lambda Platform, DTMF Secure Capture, Meridian Chat Widget, Nationwide Chat Widget |
| Tier 2 | 8 hours | 4 hours | ARIA Evaluator, Connect Analytics Agent |
| Tier 3 | 24 hours | 24 hours | Brainstorming Agent |

### Failover Approach

1. Restore or rehydrate critical infrastructure through CDK / CloudFormation and controlled deployment scripts in the designated recovery region or recovery environment.
2. Prioritise Tier 1 customer channels and their shared dependencies: Connect integrations, AgentCore-backed ARIA services, DTMF secure capture, and static web delivery.
3. Re-establish secrets, keys, and parameter state required for OBO, DTMF, and runtime configuration using approved secure stores.
4. Validate audit fan-out, transcript persistence, and monitoring before declaring recovery complete, because silent loss of control evidence is unacceptable in regulated banking.
5. Restore Tier 2 services once Tier 1 customer journeys are stable, then recover Tier 3 internal services.
6. Execute a business-continuity communication plan that informs customer-service teams, operations, and business owners of degraded or restored capability by service tier.

DR testing must include not only infrastructure rebuilds but also full end-to-end scenario validation: widget launch, AI conversation, live transfer, secure capture, audit evidence, and evaluation re-entry. In AI banking platforms, partial technical recovery without restored control evidence is not sufficient.


## Service Transition Plan

### Transition Phases

| Phase | Objective | Key Activities | Exit Criteria |
| --- | --- | --- | --- |
| Platform design baseline | Agree architecture and service catalogue | Review all eight services, shared controls, tiers, and ownership | Architecture governance approval |
| Component readiness | Validate each service independently | Build verification, config review, support-model confirmation, doc completion | Component owners sign off |
| Cross-cutting control validation | Validate platform-wide security and audit patterns | Test PII vault, audit fan-out, observability, identity propagation, and key management | Security and compliance sign-off |
| Integrated non-functional testing | Prove end-to-end resilience and performance | Run channel, routing, transfer, DTMF, analytics, and evaluation scenarios | Non-functional acceptance complete |
| Operational readiness | Prepare support and change organisations | Runbook completion, on-call activation, dashboard review, service-desk training | Operational acceptance achieved |
| Go-live and migration | Enable production usage under controlled conditions | Deploy release set, perform smoke tests, manage hypercare | Stable production operation observed |
| Post-transition review | Confirm service acceptance and lessons learned | Assess incidents, metrics, and follow-up improvements | Formal service introduction closure |

### Acceptance Criteria

- All Tier 1 services demonstrate successful smoke tests in production-like conditions.
- Three-tier audit trail and transcript persistence are proven for representative banking actions.
- PII vault pipeline and OBO identity propagation are validated for regulated customer journeys.
- DTMF secure capture demonstrates masked-only outcomes with no evidence of raw sensitive data leakage.
- Widgets launch successfully from production domains and complete end-to-end chat flows.
- Connect Lambda Platform functions have correct permissions, aliases, and dependency configuration.
- ARIA Evaluator is able to run regression scenarios against the live integration pattern.
- CloudWatch and Dynatrace dashboards are populated and alert routing is active.
- Runbooks, playbooks, training material, and escalation paths are published and reviewed.
- Business owners, operations, security, and architecture stakeholders approve the platform service introduction package.

### Go-Live Checklist

- Platform change record approved for all in-scope components.
- Component service catalogue reviewed and ownership confirmed.
- Tier 1 deployment sequence and rollback sequence rehearsed.
- CloudFront, S3, Connect, AgentCore, Lambda, and DynamoDB configurations confirmed in target environment.
- Audit, transcript, and observability pipelines validated with live smoke-test data.
- DTMF keys, secrets, and Connect security-key associations confirmed and not due for immediate rotation.
- Widget approved origins reviewed for Meridian and Nationwide production domains.
- Security review confirms no secrets are present in client bundles or public artifacts.
- On-call bridge, incident communications, and business-owner contacts confirmed.
- Hypercare war room and daily reporting cadence scheduled.
- Fallback customer communication and alternative servicing channels prepared.
- Post-go-live evaluation scenarios queued for early-life regression confidence.


## Training & Knowledge Transfer

Platform introduction requires knowledge transfer at both component and cross-cutting levels. Teams must understand not only how their individual service works, but also how platform patterns such as Connect integration, audit fan-out, PII vaulting, DTMF controls, and Dynatrace observability tie the estate together.

| Audience | Training Focus | Outcome |
| --- | --- | --- |
| Service Desk / Operations Centre | Tier model, symptom triage, customer-channel dependencies | Faster first-line response for customer incidents |
| Connect Operations | Lambda integration, widgets, routing, secure capture, transfer paths | Confident handling of contact-centre changes and faults |
| Platform Engineering | Shared controls, DR, CI/CD, observability, and AWS dependency governance | Consistent execution of platform operations |
| Security / Compliance / Audit | PII vault, OBO, audit tiers, PCI secure-capture design | Stronger control assurance and review readiness |
| Product and Service Owners | Tiered SLOs, value metrics, and hypercare governance | Clear business accountability |
| QA / Evaluation Teams | Using ARIA Evaluator, scenario libraries, and release quality gates | Repeatable release confidence process |

Knowledge transfer should include architecture walkthroughs, live incident simulations, secure-capture operational drills, and a platform dependency map review. This is essential because the hardest real-world incidents will involve interactions between services rather than failures inside a single codebase.


## Risk Register

| ID | Risk | Category | Probability | Impact | Mitigation | Owner | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ARP-R1 | Shared dependency failure in Amazon Connect or Bedrock causes simultaneous degradation across multiple Tier 1 services | Platform Dependency | Medium | High | Tier-aware dashboards, supplier escalation paths, graceful degradation, and DR runbooks | [OWNER_NAME] | Open |
| ARP-R2 | Audit fan-out failure leads to incomplete regulated evidence for banking tool calls | Compliance | Low | High | Continuous audit-pipeline monitoring, alerting, and reconciliation checks | [OWNER_NAME] | Open |
| ARP-R3 | OBO or authentication-context mismatch allows incorrect customer context in downstream tools | Security / Identity | Low | High | Strict token-validation controls, test coverage, and security review for identity propagation changes | [OWNER_NAME] | Open |
| ARP-R4 | DTMF key-management or rotation error disrupts PCI-sensitive customer journeys | PCI / Operational | Medium | High | Runbook-driven rotation, dual-key transition windows, and controlled change windows | [OWNER_NAME] | Open |
| ARP-R5 | White-label divergence between Meridian and Nationwide increases release and support complexity | Operating Model | Medium | Medium | Shared design pattern, release governance, and comparative channel dashboards | [OWNER_NAME] | Open |
| ARP-R6 | Lambda permission drift or stale configuration breaks Connect flows after deployment | Release / Integration | Medium | High | Post-deploy validation, alias discipline, and controlled script usage | [OWNER_NAME] | Open |
| ARP-R7 | Evaluation coverage is insufficient, allowing behaviour regressions into production | Quality / Model Risk | Medium | High | Mandatory evaluator gates for key releases and adversarial test coverage | [OWNER_NAME] | Open |
| ARP-R8 | Observability is fragmented, delaying root-cause analysis during major incidents | Operations | Medium | High | Unified tagging, CloudWatch + Dynatrace standardisation, and dashboard ownership | [OWNER_NAME] | Open |


## Approvals

| Role | Name | Signature | Date |
| --- | --- | --- | --- |
| Platform Service Owner | [NAME] |  | [DATE] |
| Chief / Lead Architect | [NAME] |  | [DATE] |
| Digital Banking Product Owner | [NAME] |  | [DATE] |
| Connect Operations Lead | [NAME] |  | [DATE] |
| Security and Compliance Reviewer | [NAME] |  | [DATE] |
| Operations Acceptance Manager | [NAME] |  | [DATE] |

