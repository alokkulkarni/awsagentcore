# Service Introduction Document — DTMF Secure Capture

This Service Introduction Document covers the ARIA DTMF Secure Capture service that enables Meridian Bank to collect sensitive keypad-entered information during voice interactions without exposing raw digits to agents, recordings or the wider conversational runtime. The document is written for service transition, operational acceptance and architecture governance within a UK retail banking context.

The document reflects the secure-capture guide in `docs/aria-dtmf-secure-capture-guide.md`, the focused deployment and runbook artefacts in `docs/playbooks/` and `docs/runbooks/`, the key artefacts held under `meridian-dtmf-keys/`, and the Lambda implementation in `scripts/lambdas/aria_dtmf_start_session.py`, `aria_dtmf_decrypt.py`, `aria_dtmf_validate.py` and `aria_dtmf_status_proxy.py`.

## Document Control

| Field | Value |
| --- | --- |
| SID ID | SID-DTC-001 |
| Version | 1.0.0 |
| Status | Draft |
| Classification | Internal |
| Owner | [OWNER_NAME] |
| Reviewers | [REVIEWER_NAME] |
| Service | DTMF Secure Capture |
| Business Unit | Security / Compliance / Contact Centre |
| Primary Region | eu-west-2 |
| Document Date | [DATE] |

This SID is a controlled transition document for a PCI-sensitive service. It is intended to support release readiness, support model definition, risk acceptance, training and formal service introduction into BAU operations. Because the service handles regulated cardholder interactions, document accuracy is itself a control requirement and should be reviewed whenever key management, flow logic or validation scope changes.

The owner is accountable for end-to-end service integrity, including key lifecycle, flow publication dependencies, Lambda deployment, API exposure, auditability and operational readiness. Reviewers should include security engineering, PCI governance, platform engineering and contact centre operations so that both technical design and frontline usability are represented.

| Revision | Date | Author | Summary |
| --- | --- | --- | --- |
| 1.0.0 | [DATE] | [OWNER_NAME] | Initial draft covering secure-capture design, PCI control model, operational support and transition approach. |

## Executive Summary

DTMF Secure Capture is the bank's controlled mechanism for collecting card PANs, PINs, dates of birth, account numbers and related keypad-entered values during a voice interaction without allowing those digits to be heard by an advisor, retained in call recordings or passed unprotected into the broader AI workflow. The service uses Amazon Connect secure input with RSA encryption, Lambda-based decryption and validation, DynamoDB-backed session tracking and a masked status path for agents and flows.

The service is Tier 1 because it underpins PCI-compliant handling of the most sensitive inputs in the contact centre. If it fails, the bank cannot simply continue with the same journey in an unprotected manner; it must either restore the secure path or reroute the customer to an alternative compliant process. The service is therefore both an operational feature and a regulatory control.

From an architectural standpoint, the solution is elegant precisely because it keeps the cleartext boundary as small as possible. Amazon Connect encrypts DTMF immediately using the registered public key, `aria_dtmf_decrypt.py` uses AWS Encryption SDK and a KMS-protected private key retrieved from Secrets Manager, `aria_dtmf_validate.py` performs Luhn, BIN and ownership checks, and only masked or derived results are propagated to contact attributes or user interfaces.

The transition priority is to operationalise the service like a bank control rather than a demo feature. That means strict key rotation, synthetic-only testing outside production, precise monitoring, explicit support routing, formal change control and closure of known design limitations such as the singleton active-session discovery pattern used by the launcher and human-agent status panel.

## Service Description

| Attribute | Value |
| --- | --- |
| Name | DTMF Secure Capture |
| Classification | Security and compliance control service for sensitive keypad capture |
| Service Tier | Tier 1 (Business Critical — required for PCI-DSS compliant collection) |
| Service Type | Security / Compliance Service |
| Category | Secure Data Capture / PCI-DSS / IVR Security |
| Business Unit | Security / Compliance / Contact Centre |
| Primary Consumers | Amazon Connect contact flows, ARIA AI path, human-agent assisted voice journeys and PCI governance stakeholders |

The service is implemented as a four-Lambda chain with supporting keys, API Gateway routes, DynamoDB state and a CloudFront-hosted agent status panel. The solution supports both AI-initiated capture, where ARIA requests `CollectCardDetails` via the fulfilment bridge, and human-agent-initiated capture, where the advisor triggers a Quick Connect and the customer completes secure input while the agent is held away from the audio path.

The working key artefacts in `meridian-dtmf-keys/` include `meridian-connect-pubkey-only.pem` and `meridian-connect-public.pem` for public-key registration workflows. Operational guidance in the repository expects the private key to be protected in a managed secret store and not used directly from source paths; this must remain the only permitted production operating pattern.

| Service Component | Role in Service |
| --- | --- |
| `aria_dtmf_start_session.py` | Creates an active secure-capture session and sets `dtmf_status=awaiting_trigger`. |
| `aria_dtmf_decrypt.py` | Decrypts Amazon Connect ciphertext and returns masked and derived values only. |
| `aria_dtmf_validate.py` | Performs Luhn, BIN and ownership checks, then pushes status back to the original contact. |
| `aria_dtmf_status_proxy.py` | Provides browser-facing JSON status for launcher and CCP panel use. |
| `dtmf_active_sessions` table | Tracks the active secure-capture session and recent terminal state. |
| Connect security key | Stores the public key used by the secure input block for encryption. |
| CloudFront / S3 panel assets | Delivers launcher and status panel to the agent desktop. |

## Business Context

In a UK retail bank, asking a customer to speak or key sensitive digits without technical controls creates unacceptable operational and regulatory exposure. Card numbers, PINs and related secrets must not be audible to advisors, captured in call recordings, surfaced to AI prompt context or written to general-purpose logs. DTMF Secure Capture exists to close that exposure while preserving a usable assisted-service experience.

The business driver is therefore twofold. First, the bank must satisfy PCI-DSS and internal control expectations for cardholder data handling. Secondly, it must do so without collapsing customer experience or forcing unnecessary channel switching. A secure capture journey that keeps the customer in the call, preserves automation continuity and returns only masked outcomes is materially better for both compliance and service quality.

The service also supports a broader ARIA operating model. For the AI path, ARIA can request secure capture and then resume the conversation with derived card context. For the human-agent path, the advisor can trigger secure collection without hearing the tones and can monitor progress in a purpose-built status panel. This allows the same controlled capability to serve both automation and assisted-service journeys.

| Stakeholder / Persona | Interest in Service | Transition Need |
| --- | --- | --- |
| Security Officer / PCI control owner | Assurance that cardholder data controls are enforced technically, not procedurally. | Evidence of key handling, logging discipline and auditability. |
| Contact Centre Operations | A workable secure process that does not confuse agents or customers. | Clear operational scripts, panel guidance and fallback process. |
| Platform Engineering | A repeatable deployment and support model for Lambda, API and key rotation. | Runbooks, alarms, release control and backlog for design hardening. |
| Service Management | Explicit support ownership and business-impact definition for incidents. | Incident classes, SLOs and go-live acceptance criteria. |
| Solution Architecture | Consistency with target-state voice security architecture. | Architecture baseline and risk treatment decisions. |
| PCI DSS QSA / compliance liaison | Confidence that production operation aligns to assessed control statements. | Change notifications, evidence trail and incident reporting path. |

| Business Value Metric | Intent | Target / Interpretation |
| --- | --- | --- |
| PCI-safe capture success rate | Collect sensitive data without control breach. | Near-100% for valid journeys; zero deliberate bypass. |
| Raw digit exposure incidents | Prevent audible, logged or agent-visible leakage. | Zero tolerated. |
| Secure-capture completion time | Maintain acceptable customer experience. | Terminal state visible to agent panel within six seconds of completion. |
| Retry efficiency | Catch simple mis-entry through Luhn/BIN checks without unnecessary escalation. | Most invalid entries resolved within guided retry path. |
| Ownership mismatch detection | Surface potential fraud or mis-key scenarios. | Mismatched authenticated cards flagged for escalation. |
| Change compliance | Ensure production changes follow security sign-off and controlled rollout. | 100% of production releases with recorded approval evidence. |

## Service Scope

The service boundary begins when an Amazon Connect flow enters the secure-capture path and ends when only masked or derived outcomes have been returned to the contact flow, agent panel or ARIA session context. Within that boundary the service manages session state, decryption, validation, status propagation, key access and agent feedback mechanisms.

The service is intentionally narrow in scope: it secures collection and validation of keypad-entered values. It does not perform card authorisation, payment execution, case creation or core-banking account mutation. Those are downstream business services that may consume derived outputs but are not part of the secure-capture control itself.

In scope:

- Amazon Connect secure input configuration and the registered public encryption key used for DTMF capture.
- Session initialisation via `aria_dtmf_start_session.py` and active-session state in DynamoDB.
- Server-side decryption using AWS Encryption SDK in `aria_dtmf_decrypt.py`.
- Validation logic in `aria_dtmf_validate.py`, including Luhn, BIN and ownership checks.
- Status propagation through Connect contact attributes and the API-backed human-agent panel.
- API Gateway routes `GET /dtmf-active` and `GET /dtmf-status` exposed by `aria_dtmf_status_proxy.py`.
- Human-agent wrapper flow and AI-initiated collection path dependencies where they invoke the secure-capture chain.
- Operational key lifecycle, synthetic test practice, monitoring, alerting and support runbooks.

Out of scope:

- Core-banking authorisation or payment processing after a card is validated.
- General ARIA conversation logic unrelated to secure keypad collection.
- Non-voice channels such as web forms or mobile-app card entry.
- Amazon Connect tenancy, telephony carrier services and enterprise network design.
- Customer identity proofing outside the specific ownership-check interactions used by the validation Lambda.
- Storage of full PAN or PIN values outside the ephemeral decrypt-memory boundary; that pattern is prohibited, not part of scope.

## Technical Architecture

The service uses Amazon Connect's secure DTMF capability as the ingress control. The contact flow captures keypad tones using a Connect security key, producing AWS Encryption SDK envelope ciphertext rather than plaintext digits. That ciphertext is then passed to `aria_dtmf_decrypt.py`, which retrieves the bank's private key from a managed secret store protected by KMS and decrypts the payload server-side inside Lambda memory only.

The decrypted result is not propagated as a raw value. Instead, the Lambda returns masked output, last four digits, BIN and Luhn-validity hints as appropriate to the collection purpose. `aria_dtmf_validate.py` then applies layered validation: optional Luhn confirmation when a full card number is provided, BIN validation against `aria-card-bins`, and customer ownership verification through either the primary customer Lambda or DynamoDB fallback. Status is pushed back to the original contact leg and mirrored into the active-session tracker so the human-agent UI can render progress safely.

```text
Customer on phone keypad
        |
        v
Amazon Connect secure input block
        |  (public RSA key / Connect security key)
        v
Encrypted DTMF payload
        |
        +--> aria_dtmf_start_session.py --> DynamoDB `dtmf_active_sessions`
        |
        +--> aria_dtmf_decrypt.py --> Secrets Manager private key --> KMS
        |                           --> AWS Encryption SDK decrypt
        |                           --> masked value / BIN / last four / Luhn flag
        |
        +--> aria_dtmf_validate.py --> BIN table (`aria-card-bins`)
        |                           --> customer ownership Lambda / DynamoDB fallback
        |                           --> Connect contact attributes (`dtmf_status`, `dtmf_masked`, ...)
        |
        +--> aria_dtmf_status_proxy.py --> API Gateway
                                        --> launcher iframe / CCP status panel
```

| Technology Element | Implementation Detail | Why It Matters |
| --- | --- | --- |
| Runtime | AWS Lambda on Python 3.12 | Managed scale and low-ops serverless execution. |
| Encryption ingress | Amazon Connect secure input with registered public RSA key | Digits are encrypted before application software reads them. |
| Key artefacts | `meridian-connect-pubkey-only.pem` / `meridian-connect-public.pem` in working key set | Provide the public material used for Connect registration and operational key workflows. |
| Key custody | Private key fetched from Secrets Manager and protected by KMS in the implemented Lambda path | Keeps secret material out of flow configuration and runtime environment variables. |
| Cryptography library | `aws_encryption_sdk` with RSA OAEP SHA-512 MGF1 wrapping | Matches Amazon Connect encrypted-input envelope requirements. |
| Validation data | DynamoDB `aria-card-bins` and `aria-customer-cards` plus customer verification Lambda | Supports layered validation without persisting full PAN. |
| Status store | DynamoDB `dtmf_active_sessions` | Supports launcher discovery and terminal-state visibility. |
| UI delivery | S3 + CloudFront panel assets with approved origins in Connect | Gives human agents masked, colour-coded feedback. |
| API façade | API Gateway + `aria_dtmf_status_proxy.py` | Provides browser-safe read-only status access. |
| Contact-state transport | Amazon Connect contact attributes | Moves masked outcomes and status between flow blocks and agent views. |

| Integration Point | Direction | Contract Summary |
| --- | --- | --- |
| Connect secure input → decrypt Lambda | Inbound synchronous | `encryptedValue`, `keyId`, `purpose` passed as flow parameters. |
| Start-session Lambda → DynamoDB | Outbound synchronous | Writes `session_id = ACTIVE`, `contact_id`, `status`, `updated_at`, `ttl`. |
| Decrypt Lambda → Secrets Manager / KMS | Outbound synchronous | Fetches PEM private key material and decrypts via AWS-managed controls. |
| Validate Lambda → BIN table | Outbound synchronous | Looks up `binPrefix` and card-type metadata. |
| Validate Lambda → customer verification Lambda | Outbound synchronous | Checks customer ownership using BIN + last four. |
| Validate Lambda → Connect | Outbound synchronous | Pushes `dtmf_status`, step and error attributes to original contact. |
| Status proxy → Connect | Outbound synchronous | Reads contact attributes for human-agent display. |
| Status proxy → browser panel | Outbound HTTP JSON | Returns masked state only; no raw digits. |
| CloudFront assets → Connect CCP | Inbound browser integration | Provides launcher and status panel to the advisor desktop. |

## Service Interfaces

The service contracts are small but sensitive. Any change to key IDs, flow parameter names, contact attribute names or API responses can break either the security posture or the agent experience. Interface discipline is therefore mandatory and must be version-controlled alongside flow publication changes.

| API / Contract | Caller | Key Inputs | Key Outputs |
| --- | --- | --- | --- |
| `aria_dtmf_start_session.py` | Amazon Connect flow | `ContactId` / `InitialContactId` from Connect event | `status=ok` plus side effects in DynamoDB and contact attributes. |
| `aria_dtmf_decrypt.py` | Amazon Connect flow | `encryptedValue`, `keyId`, `purpose` | `maskedValue`, `digitCount`, `lastFour`, `cardBin`, `luhnValid`, `errorMessage`. |
| `aria_dtmf_validate.py` | Amazon Connect flow | `cardLastFour`, `cardBin`, `digitCount`, optional `cardFull`, customer/auth attributes | `isValid`, `validationStatus`, `cardType`, `cardNickname`, `requiresEscalation`. |
| `GET /dtmf-active` | Launcher / status panel | No body | `contactId` and current session status if present. |
| `GET /dtmf-status?contactId=` | Launcher / status panel | Original contact ID | `dtmf_status`, masked card data, validation status and error fields. |
| Quick Connect / wrapper flow | Human agent path | Agent-triggered transfer into secure sub-flow | Customer returns to agent with masked outputs in contact attributes. |
| Lex `CollectCardDetails` intent | AI agent path | Returned by fulfilment bridge when DTMF capture requested | Transfers customer into secure sub-flow and then back to conversation. |

| Event / Message Interface | Purpose | Notes |
| --- | --- | --- |
| `dtmf_status` contact attribute | Primary state machine for flows and human-agent panel. | Observed statuses include `awaiting_trigger`, `validating`, `complete`, `ownership_mismatch` and `system_error`. |
| `dtmf_masked` contact attribute | Safe masked result display. | Should contain only masked output such as `****4821`. |
| `dtmf_card_type` and validation attributes | Supports agent context and AI session continuation. | Derived only; never sufficient to reconstruct full PAN. |
| DynamoDB active-session record | Lets browser assets discover the current contact to monitor. | Current implementation uses singleton active-session semantics. |
| Connect key ID | Binds secure input encryption to the expected RSA key pair. | Mismatch results in decryption failure or unusable capture. |

| UI Interface | Consumer | Operational Use |
| --- | --- | --- |
| Amazon Connect secure sub-flow | Customer / Connect runtime | Collects keypad digits and branches on decrypt/validate result. |
| Quick Connect “Collect Card — Secure” | Human agent | Starts secure capture without exposing tones to the agent. |
| CCP Contact Attributes view | Human agent | Displays masked final values and status. |
| Launcher iframe | Human agent desktop | Auto-discovers the active secure-capture session. |
| CCP status panel | Human agent desktop | Polls every two seconds and renders colour-coded progress. |

## Service Dependencies

The secure-capture service is deliberately dependent on a tightly controlled set of AWS services and contact-flow configurations. This keeps the cryptographic boundary narrow, but it also means dependency failure often has direct customer impact. Support teams must understand which dependencies are hard requirements and which have fail-open or fail-safe behaviours.

Internal dependencies are as follows:

- Amazon Connect flows with secure input blocks configured to use the correct encryption key.
- DTMF wrapper and sub-flow logic for AI and human-agent paths.
- Customer ownership Lambda and/or fallback card-reference table.
- Approved BIN table contents for bank-issued card ranges.
- CloudFront/S3 deployment of launcher and panel assets where human-agent monitoring is used.
- Contact attribute mappings that return masked outcomes to advisors or back into AI session context.

| External Dependency | Purpose | Criticality | Fallback / Behaviour on Failure |
| --- | --- | --- | --- |
| Amazon Connect | Primary capture and orchestration engine. | Critical | No secure-capture service without Connect invocation context. |
| Secrets Manager + KMS | Protects private key and optional API keys. | Critical | Decrypt path fails and flow should return customer safely to alternative path. |
| AWS Encryption SDK | Required to decrypt Connect ciphertext envelope. | Critical | No supported manual fallback inside application logic. |
| DynamoDB | Tracks active session, BIN metadata and fallback customer-card references. | Critical | Panel discovery and validation degrade or fail. |
| API Gateway | Browser access to masked status data. | High | Human-agent visibility degrades; AI path may still continue. |
| CloudFront / S3 | Hosts agent launcher and status panel. | Medium | Secure capture still possible, but human agents lose enhanced live feedback. |
| Customer verification Lambda | Primary ownership check. | High | Service fails open to DynamoDB fallback or validation-service-error path depending on overall availability. |
| Amazon Q in Connect / Lex session mapping | Needed only when ARIA must resume with secure-capture outcomes. | Medium | Human-agent capture still works without AI continuation. |

## Service Level Objectives

The SLOs below are framed for a control service rather than a generic API. The objective is not only low latency but also safe, deterministic behaviour under failure. For example, a decryption failure that safely returns the customer to a compliant fallback is operationally better than a hidden silent failure that leaves the customer stranded in the flow.

| Objective | Target | Measurement Basis |
| --- | --- | --- |
| Availability | 99.95% monthly for secure-capture initiation and validation path | Measured across start-session, decrypt, validate and status-proxy availability. |
| Session initialisation latency | p95 < 250 ms | Time for `aria_dtmf_start_session.py` to write active state and set initial contact attribute. |
| Decryption latency | p95 < 500 ms | Measured for `aria_dtmf_decrypt.py` including secret retrieval on warm path. |
| Validation latency | p95 < 700 ms | Measured for `aria_dtmf_validate.py` excluding customer input time. |
| Agent status visibility | Final state visible within 6 seconds of capture completion | Combines Lambda completion and two-second polling rhythm. |
| Throughput | Support low-hundreds concurrent secure-capture requests subject to table and concurrency redesign for launcher discovery | Measured through Lambda concurrency, API load and DynamoDB behaviour. |
| RTO | 60 minutes for full service restoration | Recovery objective for production incident response. |
| RPO | 15 minutes for operational state; no accepted loss for successfully written immutable audit evidence when enabled | Based on DynamoDB/session behaviour and downstream audit design. |

These targets assume that the current singleton discovery mechanism is not the sole source of truth for large-scale concurrency. If the service is expanded across many simultaneous human-agent sessions without redesigning the active-session model, the visibility SLO becomes difficult to uphold even if the underlying Lambda chain remains healthy.

## Operational Model

This service should be supported as a regulated control, not merely as a convenience feature. L1 teams must recognise symptoms and business impact quickly, but key-handling, decryption and compliance-significant incidents require escalation into platform engineering and security without delay. Production changes should only be executed in approved windows with Contact Centre Operations informed beforehand.

| Support Tier | Owner | Responsibilities | Hours |
| --- | --- | --- | --- |
| L1 | Service Desk / Contact Centre Operations | Initial symptom triage, agent support, incident logging and business-impact assessment. | Business hours with escalation path. |
| L2 | Platform Engineering | Lambda, API Gateway, DynamoDB, flow integration, deployment and rollback execution. | 24x7 on-call for Tier 1 incidents. |
| L3 | Security Engineering / PCI control owner | Key compromise, data exposure and control-failure investigation. | On demand, mandatory for security incidents. |
| L4 | Architecture / QSA liaison | Structural defect remediation and regulatory interpretation. | On demand via major incident process. |

The on-call model should treat any suspected PAN exposure, private-key issue, repeated decryption failure or insecure flow bypass as a priority security incident. For operational failures with no evidence of data exposure, the first goal remains restoring a compliant customer path, even if that means temporarily disabling AI-initiated capture or human-agent panel functionality until the root cause is corrected.

| Incident Class | Definition | Typical Examples |
| --- | --- | --- |
| P1 | PCI-sensitive control unavailable or data exposure suspected. | Possible PAN in logs, key mismatch causing broad decrypt failure, insecure fallback attempted. |
| P2 | Major degradation with compliant workaround available. | Status panel unavailable, ownership service degraded, repeated invalid-bin false negatives. |
| P3 | Localised defect with manageable workaround. | Single queue or Quick Connect mapping issue, non-production key-rotation problem. |
| P4 | Minor issue or enhancement request. | Documentation update, dashboard tuning, panel cosmetic change. |

## Security & Compliance

Security is the point of this service. The design intent is that no human agent, AI prompt, transcript store or general log path should ever receive raw keypad-entered cardholder data in the clear. The only place cleartext exists is transiently inside the decrypt Lambda memory boundary while the service derives masked or validation-ready outputs. Every other interface is supposed to carry ciphertext, masked values or safe metadata only.

Authentication and authorisation rely on AWS-native controls. Amazon Connect invokes the Lambdas through explicit resource permissions, execution roles are scoped to the necessary AWS APIs only, Secrets Manager access is tightly limited to the decrypt Lambda and optional validation secret retrieval, and KMS protects secret material at rest. The browser panel is read-only, consumes masked status JSON and depends on approved origins and CloudFront-backed delivery rather than direct privileged access.

| Security Topic | Current Position |
| --- | --- |
| Security Classification | Internal service implementing PCI-sensitive control path. |
| AuthN / AuthZ | IAM execution roles, Lambda invoke permissions from Connect, API Gateway read-only route handling and approved-origin browser integration. |
| Key Management | Public key registered in Amazon Connect; private key retrieved server-side from Secrets Manager protected by KMS in the implemented code path. |
| Data Minimisation | Only BIN, last four, card type, nickname and masked values may leave decrypt/validate flow. |
| Logging Control | PANs, PINs and CVVs must never be logged; post-deploy log scans are mandatory. |
| Operational Security Evidence | Repository playbook and runbook require Security Officer sign-off, synthetic-only testing and post-deploy PAN audit checks. |

| Data Classification | Examples | Handling Requirement |
| --- | --- | --- |
| Cardholder Data — Restricted | Full PAN, CVV, PIN, sensitive account numbers | Must remain encrypted or ephemeral only; never persist to contact attributes, logs or agent UI. |
| Derived PCI Data — Restricted | BIN, last four, masked card output, card type | May be used for validation and safe display under least-privilege access. |
| Customer Confidential | Customer ID, authentication state, ownership-check outcome | Need-to-know access and controlled retention. |
| Control Metadata — Internal | Status codes, session IDs, flow result flags | May be logged and monitored under standard internal controls. |
| Key Material — Secret | Private RSA key, secret ARNs, API keys | Managed secret stores only, rotation and access logging mandatory. |

- PCI-DSS 4.0 is the primary regulatory control driver for this service.
- FCA operational resilience and complaint reconstruction obligations apply where secure capture affects customer servicing outcomes.
- GDPR / UK DPA apply to customer identifiers and any linked personal data used during ownership validation.
- ISO/IEC 20000-1 service transition controls apply to release, support model, documentation and change governance.

## Capacity & Scalability

The core Lambda chain scales horizontally in the AWS sense, but the service has a more subtle scalability profile because human-agent visibility depends on polling and shared session-discovery state. The cryptographic operations themselves are well suited to Lambda execution, especially with module-level client caching and warm-container reuse, but the launcher and panel pattern needs deliberate concurrency design before broad expansion.

| Capacity Area | Current Position | Implication |
| --- | --- | --- |
| Lambda compute | Serverless scaling per function. | Good baseline elasticity for bursty voice traffic. |
| Cryptographic path | Private key cached at module scope after first retrieval. | Reduces repeat secret-fetch overhead on warm containers. |
| Polling rhythm | Agent panel polls every 2 seconds once contact discovered. | Creates predictable API load amplification during concurrent sessions. |
| Session retention | Active sessions use one-hour TTL in current Lambda code; terminal statuses retained briefly for discovery. | Good for queue-wait survivability, but must be understood by support teams. |
| Known limit | Active-session discovery currently uses a singleton `ACTIVE` row. | Not suitable for many simultaneous human-agent sessions without redesign. |
| Validation dependency | Ownership check may call another Lambda or table lookup. | Downstream latency directly affects overall completion time. |

Scaling approach should prioritise redesign of session discovery before wide operational rollout to many simultaneous advisors. A per-contact or per-agent discovery model, combined with measured API Gateway capacity and DynamoDB access patterns, would remove the current last-write-wins risk. Until then, service introduction should explicitly constrain rollout scope or agent concurrency expectations.

Other known limits include dependence on correct Connect key selection, approved BIN-table coverage, and human-agent UI dependency on CloudFront propagation and approved-origin configuration. These are not blockers to controlled production use, but they are not invisible operational details either; they must be planned, monitored and owned.

## Monitoring & Observability

The most important observation principle is that secure capture is only healthy when both security and usability outcomes are healthy. A green Lambda metric is insufficient if agents cannot see terminal states, if ownership mismatches are not surfaced, or if customers are trapped in a broken retry loop. Journey-aware telemetry is therefore required.

| Key Metric | Why It Matters |
| --- | --- |
| Start-session success / failure rate | Shows whether secure-capture initiation is working at flow entry. |
| Decrypt success / failure rate | Primary signal of encryption key correctness and secret accessibility. |
| Validate success / invalid_luhn / invalid_bin / ownership_mismatch counts | Distinguishes customer mis-entry from system fault. |
| System-error count in decrypt/validate | Indicates technical failure requiring immediate triage. |
| API Gateway latency and 5xx rate | Directly affects human-agent status visibility. |
| DynamoDB throttles and TTL behaviour | Required for reliable session discovery and status retention. |
| Secrets Manager access anomalies | May indicate key access issues or security concern. |
| Potential PAN pattern matches in logs | Critical control to detect data leakage. |
| CloudFront 4xx / 5xx for panel assets | Indicates agent UI delivery issues. |
| Ownership service fallback rate | Shows whether primary validation dependency is degrading. |

Logging strategy must be explicitly restrictive. Contact IDs, masked outputs, validation codes and high-level error reasons are useful; raw digits are forbidden. The repository runbook already mandates post-deploy CloudWatch scans for 13–19 digit patterns across all four Lambda log groups, and that control should be retained as a permanent release gate rather than an optional reassurance step.

| Alert Threshold | Suggested Trigger | Operational Response |
| --- | --- | --- |
| Decrypt system errors | Any repeated burst in 5 minutes | Treat as priority incident; verify key ID, secret access and recent changes. |
| Validation system errors | Any repeated burst in 5 minutes | Check downstream ownership services and Connect attributes. |
| API Gateway 5xx | > 1% over 5 minutes | Investigate status proxy and browser-facing dependency chain. |
| Panel asset failures | CloudFront 4xx/5xx sustained | Confirm distribution, origin access control and approved origins. |
| Potential PAN in logs | Any match | Immediate Sev-1 security triage until disproven. |
| DynamoDB throttles | Any non-zero on active-session table | Assess hot key / singleton contention and table mode. |
| Ownership fallback surge | Unexpected increase above baseline | Investigate primary ownership Lambda health. |
| Secrets Manager anomalies | Unexpected access pattern or denied calls | Security review and key-access validation. |

- Dashboards should separate customer-path states from platform states: initiation, decryption, validation, panel/API and key access.
- Hypercare reporting should include counts of invalid_luhn, invalid_bin and ownership_mismatch so operational teams can distinguish fraud indicators from UX issues.
- Security operations should receive visibility of PAN-audit checks, Secrets Manager anomalies and any decrypt failures caused by key mismatch.

## Disaster Recovery & Business Continuity

The service uses managed regional AWS services, so ordinary host failure is not the main DR threat. The meaningful DR scenarios are key loss, configuration drift, table rebuild, panel/API unavailability and regional service disruption. The service must be recoverable in a way that preserves PCI control integrity; a fast but insecure workaround is not an acceptable recovery option.

Because the current implementation is not an active-active cross-region design, DR should be treated as a rehearsed restore process. Recovery assets must include key references, Connect key IDs, deployment scripts, CloudFormation parameters, flow artefacts, approved-origin configuration and panel delivery settings.

| DR Topic | Current Approach |
| --- | --- |
| DR Strategy | Scripted rebuild / controlled restore of Lambdas, API, keys and flow associations. |
| Primary RTO Target | 60 minutes for service restoration in primary region. |
| Primary RPO Target | 15 minutes for operational session state; no intentional loss of immutable audit evidence once written. |
| Failover Approach | Manual decision to restore in secondary region with new key registration and redeployment of API/panel assets. |
| Business Continuity Measure | Route customer to alternative compliant servicing path if secure capture cannot be restored immediately. |
| Key Recovery Requirement | Validated access to private-key secret and Connect public-key registration process. |

- DR testing must include end-to-end decryption using synthetic data, not only infrastructure deployment success.
- If key compromise is suspected, recovery means rotation and re-registration, not simply reusing the same secret in a new region.
- Human-agent panel recovery must not outrank secure-capture core recovery; the cryptographic path comes first, the convenience UI second.

## Service Transition Plan

Secure capture should only move into live service through a tightly controlled transition sequence. This is not a feature that can be introduced incrementally in production without prior key, flow and support readiness. Each phase below is designed to produce evidence for CAB, service management and PCI stakeholders as well as technical confidence for engineering teams.

| Phase | Purpose | Key Activities | Exit Criteria |
| --- | --- | --- | --- |
| 1. Control and design review | Confirm approved secure design and scope. | Review architecture, key lifecycle, data handling, runbooks and risk register. | Security and architecture sign-off complete. |
| 2. Key and environment preparation | Establish trusted cryptographic materials. | Generate or rotate RSA key pair, store private key securely, register public key in Connect, record key ID. | Key references validated and documented. |
| 3. Non-production build and flow test | Validate technical path using synthetic data only. | Deploy Lambdas, API, panel assets and contact flows in staging. | All synthetic end-to-end scenarios pass. |
| 4. Operational readiness | Prepare support and change control. | Set alarms, brief support tiers, rehearse rollback, confirm approved origins and agent guidance. | Operational acceptance complete. |
| 5. Production go-live | Execute controlled release. | Deploy in approved window, publish flows, run smoke tests and confirm masked outcomes only. | Go-live checklist complete and service stable. |
| 6. Hypercare and closure | Stabilise and hand over. | Enhanced monitoring, daily review and final evidence pack publication. | Service owner and service management accept BAU handover. |

Acceptance Criteria:

- Public key is correctly registered in Amazon Connect and key ID matches deployed configuration.
- Private key is retrieved only from managed secret storage and is not embedded in source, environment variables or logs.
- Start-session, decrypt, validate and status-proxy functions are deployed to controlled aliases and return expected outputs.
- All testing outside production uses synthetic test numbers only; no live PANs used in rehearsal.
- Agent panel and launcher show masked values only and render terminal states correctly.
- Ownership mismatch produces escalation-safe outcomes and does not expose raw digits.
- Post-deploy PAN audit across Lambda logs returns no suspicious raw-digit patterns.
- Rollback procedure for code and key changes has been rehearsed successfully.

Go-Live Checklist:

- Security Officer approval recorded.
- Contact Centre Operations informed of window and agent-side changes.
- Production key ID, secret ARN and KMS controls validated.
- Connect flows published with correct Lambda aliases and secure input settings.
- BIN table reviewed and approved for production ranges.
- Ownership-check dependency validated.
- API Gateway routes return expected masked JSON.
- CloudFront panel and launcher assets reachable from approved origins.
- Synthetic smoke call completed successfully.
- CloudWatch alarms and dashboards enabled.
- Rollback versions and previous key references recorded.
- Hypercare bridge opened and staffed.

## Training & Knowledge Transfer

Training should emphasise both what the service does and what users must never do. Advisors need to know how to trigger secure capture, what the panel statuses mean and when to escalate rather than improvise. Engineers need to know the key lifecycle, runbook steps, panel/API dependencies and the difference between customer mis-entry and technical decryption failure.

Knowledge transfer should draw directly from the repository's secure-capture guide, playbook and runbook, but those artefacts should be summarised into role-specific operational notes before go-live. Security and PCI stakeholders should receive a separate control-focused briefing rather than being expected to infer controls from deployment scripts alone.

| Audience | Knowledge Required | Recommended Artefact |
| --- | --- | --- |
| Human agents / supervisors | How to trigger secure capture, interpret status colours and handle fallback. | Quick-reference guide derived from the secure-capture guide. |
| Service Desk / L1 | Symptom triage, incident severity and escalation path. | SID summary and operational KB article. |
| Platform Engineering / L2 | Deployment, rollback, key rotation and observability. | Runbook, playbook and deployment scripts. |
| Security / PCI governance | Key custody, log-audit process and incident model. | Security briefing and control evidence pack. |
| Architecture / CAB | Boundary, known limits, DR posture and risk treatment. | This SID and supporting architecture artefacts. |

## Risk Register

| ID | Risk | Category | Probability | Impact | Mitigation | Owner | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| DTC-R1 | Incorrect Connect key ID or mismatched RSA key pair causes decryption failure across live calls. | Security / Availability | Medium | High | Strict key-registration validation, synthetic smoke tests and controlled rotation procedure. | Platform Engineering | Open |
| DTC-R2 | Raw sensitive digits are exposed through logs, source artefacts or unsupported operating practice. | Compliance | Low | Critical | Managed-secret-only policy, post-deploy PAN log scans, code review and immediate rotation if breach suspected. | Security Officer | Open |
| DTC-R3 | Singleton `ACTIVE` session record causes last-write-wins collisions for simultaneous human-agent sessions. | Scalability | High | High | Redesign active-session discovery model before broad multi-agent rollout. | Platform Engineering | Open |
| DTC-R4 | Primary ownership-validation dependency is unavailable, increasing fail-open outcomes. | Operational Control | Medium | Medium | Monitor fallback rate, maintain DynamoDB fallback and review fraud controls for validation-service-error path. | Service Owner | Open |
| DTC-R5 | CloudFront / approved-origin misconfiguration leaves agents without live panel feedback. | Operations | Medium | Medium | Pre-go-live browser validation, approved-origin checklist and fallback to contact-attribute view. | Contact Centre Operations | Open |
| DTC-R6 | Local or working-copy key material persists outside approved secret-management controls. | Key Management | Medium | Critical | Immediate removal from non-approved locations, rotate affected keys and enforce secure generation/handling process. | Security Officer | Open |

## Approvals

| Role | Name | Signature | Date |
| --- | --- | --- | --- |
| Service Owner | [NAME] | [NAME] | [DATE] |
| Platform Engineering Lead | [NAME] | [NAME] | [DATE] |
| Security Officer | [NAME] | [NAME] | [DATE] |
| Contact Centre Operations Lead | [NAME] | [NAME] | [DATE] |
| Service Management Approver | [NAME] | [NAME] | [DATE] |
