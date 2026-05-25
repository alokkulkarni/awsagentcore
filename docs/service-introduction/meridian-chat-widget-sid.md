# Meridian Chat Widget Service Introduction Document

This Service Introduction Document defines the production service baseline, transition controls, and operational expectations for the Meridian Bank customer chat widget deployed from the `connect-chat-widget/` component in this repository. The document is written to support service transition, architecture governance, operational acceptance, and audit readiness for a customer-facing digital banking channel.

## Document Control

| Field | Value |
| --- | --- |
| SID ID | SID-MCW-001 |
| Version | 1.0.0 |
| Status | Draft |
| Classification | Internal |
| Owner | [OWNER_NAME] |
| Reviewers | [REVIEWER_NAME], [REVIEWER_NAME] |
| Service Name | Meridian Chat Widget |
| Repository Component | `connect-chat-widget/` |
| Business Unit | Digital Banking / Customer Experience |
| Primary Region | AWS Europe (London) with platform DR alignment |

### Revision History

| Version | Date | Author | Summary |
| --- | --- | --- | --- |
| 0.1.0 | [DATE] | [NAME] | Initial architecture and service transition draft created from repository analysis. |
| 0.9.0 | [DATE] | [NAME] | Expanded operating model, security controls, SLOs, and transition requirements for service introduction review. |
| 1.0.0 | [DATE] | [NAME] | Draft baseline issued for stakeholder review and formal service transition planning. |


## Executive Summary

Meridian Chat Widget is the customer-facing web channel that embeds the Amazon Connect hosted chat experience into Meridian Bank's digital estate. The service provides an entry point for customers who need help with accounts, payments, cards, product queries, and general servicing, while presenting the interaction in a branded Meridian user experience rather than a generic third-party frame.

From a technical perspective, the service is a lightweight React and Vite application that serves a branded shell page, loads the hosted Amazon Connect widget client in the browser, and applies client-side presentation controls such as participant display-name normalisation, responsive styling, and bank-specific visual identity. The repository implementation shows a simple React root, a branded `App.jsx`, and a `ConnectChatWidget.jsx` component that watches widget DOM updates and harmonises transcript labels from `BOT` and `SYSTEM` into Meridian-friendly names.

Operationally, the service is Tier 1 because it is part of the primary self-service and assisted-service path for Meridian's digital channels. It depends on high availability of CloudFront, static asset hosting, Amazon Connect chat services, approved origin management, and downstream contact flows that route customers to ARIA or to a live human advisor when containment thresholds or customer intent require human intervention.

This SID introduces the widget as a controlled production service, not merely a front-end artefact. It establishes scope boundaries, service levels, support ownership, security expectations, monitoring obligations, and go-live controls needed before the channel can be treated as a formally onboarded banking service.


## Service Description

| Attribute | Definition |
| --- | --- |
| Name | Meridian Chat Widget |
| Classification | Customer-facing web application delivering hosted chat initiation and interaction controls |
| Service Tier | Tier 1 (Business Critical — primary digital chat channel) |
| Service Type | Customer-Facing Web Channel |
| Category | Customer Engagement / Digital Banking Channel |
| Primary Users | Meridian Bank customers visiting Meridian web properties on desktop or mobile browsers |
| Deployment Model | Static front-end build produced by Vite and published to S3 + CloudFront |
| Runtime Pattern | Browser-rendered React shell plus hosted Amazon Connect widget script and iframe |
| Source Evidence | `connect-chat-widget/README.md`, `connect-chat-widget/package.json`, `connect-chat-widget/index.html`, `connect-chat-widget/src/App.jsx`, `connect-chat-widget/src/components/ConnectChatWidget.jsx` |

The service presents Meridian branding, navigation, hero content, and feature tiles while delegating the chat session runtime to Amazon Connect. The widget itself is not reimplemented locally; instead, the application bootstraps the hosted Connect client using the `window.amazon_connect` contract and snippet configuration declared in `index.html`.

The service exists to reduce customer effort for routine service journeys, improve 24x7 availability of conversational support, and create a consistent front door into ARIA or a live human agent. It is therefore classified as a front-end channel service with downstream reliance on managed conversational infrastructure rather than as an independently stateful business application.


## Business Context

### Business Drivers

- Provide Meridian customers with an always-available digital assistance entry point on the bank home page.
- Increase self-service containment for common enquiries before expensive live-agent handling is needed.
- Support ARIA adoption as the bank's primary AI-led conversational channel for digital banking journeys.
- Preserve brand trust by presenting chat in a Meridian-native experience instead of a visually generic external widget.
- Improve mobile engagement by delivering a responsive, fixed-position chat entry point that remains accessible during browsing.
- Maintain a simple deployment footprint so channel updates can be promoted through static hosting and CDN controls rather than server rebuilds.
- Ensure channel controls such as approved origins, CSP posture, and TLS enforcement align with financial-services expectations.
- Create a reusable white-label pattern that can also be adapted for partner brands such as Nationwide without changing the underlying chat service model.

### Stakeholders & Personas

| Stakeholder / Persona | Interest in Service | Success Measure |
| --- | --- | --- |
| Retail customer | Needs quick answers or transfer to a human without leaving the website | Fast session start, clear messaging, reliable chat continuity |
| Digital Banking Product Owner | Owns customer adoption and service outcomes | High engagement, containment, and customer satisfaction |
| Customer Experience team | Owns look-and-feel and journey consistency | Meridian branding and frictionless responsive experience |
| Contact Centre Operations | Depends on correct routing into Amazon Connect | Stable handoff, clean transfers, predictable queue behaviour |
| ARIA platform team | Consumes chat sessions in downstream flows | Consistent metadata and reliable session initiation |
| Security and Risk | Requires strong browser security posture | No client secrets, known-origin restriction, compliant TLS delivery |
| Service Desk | Supports incidents raised by customers or internal users | Actionable monitoring, runbooks, and known-failure patterns |
| Accessibility and Brand governance | Needs inclusive, on-brand channel delivery | Responsive layout, readable styling, and consistent bank identity |

### Business Value Metrics

| Metric | Intent | Target Use in Governance |
| --- | --- | --- |
| Chat initiation success rate | Demonstrates that the widget is available and permitted by approved origin controls | Daily channel health review and release acceptance |
| Containment rate | Measures how many journeys stay within ARIA without human transfer | Monthly digital servicing value tracking |
| Transfer completion rate | Measures successful escalation from AI to live advisor | Operational stability and workforce planning |
| Time to first response | Measures perceived responsiveness after customer opens chat | Customer experience reporting |
| Mobile engagement share | Measures use of the chat entry point on responsive layouts | Channel adoption planning |
| CloudFront availability | Measures static asset delivery stability | Infrastructure service review |
| CSP / approved-origin failure count | Detects preventable deployment misconfiguration | Change quality and release hardening |
| Customer satisfaction delta for chat journeys | Shows channel impact on digital experience | Quarterly service value review |

The service is also strategically important because it is a visible manifestation of Meridian's digital transformation programme. A failed widget or visibly off-brand experience damages customer confidence immediately; a reliable and well-governed widget increases trust in both ARIA and the bank's broader self-service operating model.


## Service Scope

### In-Scope

- The React and Vite application in `connect-chat-widget/` including `App.jsx`, `main.jsx`, styling, and public assets.
- Loading and configuring the hosted Amazon Connect widget client in `index.html`.
- Client-side display-name normalisation and widget DOM observation in `src/components/ConnectChatWidget.jsx`.
- Meridian branding, responsive layout, hero content, footer content, and interaction affordances around the chat entry point.
- Static build generation into `dist/` and publication to S3 with CloudFront delivery.
- Approved origin management required for the hosted widget to initialise in development and production.
- Customer chat initiation, message send and receive, human transfer, and chat termination as surfaced through the hosted widget experience.

### Out-of-Scope

- Amazon Connect instance administration beyond the widget's dependency on approved origins and snippet configuration.
- ARIA prompt design, banking tool logic, KBA journey logic, or backend contact-flow orchestration.
- Live-agent queue configuration, workforce management, or advisor desktop tooling.
- Core banking APIs, customer profile stores, and any data persistence beyond browser-rendered front-end assets.
- Regulatory policy ownership; the widget consumes policy outcomes but does not define them.
- Browser analytics products, tag managers, or consent platforms unless explicitly integrated by Meridian's digital estate standards.

### Service Boundaries

The widget boundary starts when a customer loads the Meridian web page containing the front-end assets and ends when control passes to the hosted Amazon Connect service. The browser hosts the shell, styling, and light DOM-manipulation behaviour; chat transport, transcript rendering, participant state, and session lifecycle are managed by Amazon Connect once the widget client is initialised.

The service boundary also excludes customer identity proofing and account servicing logic. If the session requires authentication, verification, or privileged banking actions, those controls occur downstream within ARIA, Connect flows, and bank-owned services. The widget must therefore be treated as a Tier 1 ingress channel with strict browser security controls but minimal domain-state retention.


## Technical Architecture

### Overview

The implemented architecture is intentionally thin. `main.jsx` mounts a React application into the root DOM node, `App.jsx` renders Meridian's marketing shell, and `ConnectChatWidget.jsx` attaches client-side behaviour that keeps the hosted widget aligned with Meridian naming conventions. The actual chat session runtime is provided by the hosted Amazon Connect script loaded from the Connect domain inside `index.html`.

This split keeps browser code simple and lowers operational risk. Meridian owns the brand shell, CDN deployment, and client security headers, while Amazon Connect owns chat transport, widget frame rendering, and backend messaging. The browser therefore becomes an orchestrated presentation layer rather than a custom chat client.

### Component Diagram in text/ASCII

```text
+-------------------+        HTTPS         +-----------------------+
| Customer Browser  | ------------------> | CloudFront            |
| Meridian website  |                     | CDN for static assets |
+---------+---------+                     +-----------+-----------+
          |                                             |
          | fetch index.html, JS, CSS                   |
          v                                             v
+-------------------+                     +-----------------------+
| React + Vite App  |                     | S3 origin             |
| App.jsx shell     |                     | versioned static site |
| ConnectChatWidget |                     +-----------------------+
+---------+---------+
          |
          | loads hosted widget client via window.amazon_connect()
          v
+-------------------+        Managed chat / iframe     +------------------------+
| Amazon Connect    | --------------------------------> | Contact Flows / ARIA   |
| Hosted Widget     |                                   | AI + live-agent paths  |
+---------+---------+                                   +-----------+------------+
          |                                                         |
          | transcript, events, transfer state                      |
          v                                                         v
+-------------------+                                   +------------------------+
| Customer-visible  |                                   | Human advisors / queues|
| chat panel        |                                   | and transcript outputs |
+-------------------+                                   +------------------------+
```

### Technology Stack

| Layer | Technology | Observed Usage | Operational Notes |
| --- | --- | --- | --- |
| Front-end framework | React 18 | Application root and branded Meridian page shell | Lightweight SPA pattern; no server rendering dependency |
| Build tool | Vite 5 | `npm run dev`, `npm run build`, `npm run preview` | Fast static build, low operational overhead |
| Language | JavaScript / JSX | `App.jsx`, `main.jsx`, `ConnectChatWidget.jsx` | Simple component model eases change control |
| Hosted chat runtime | Amazon Connect hosted widget client | Loaded from Connect domain in `index.html` | Managed script and iframe runtime outside local bundle |
| Styling | CSS | `App.css` and `index.css` define Meridian palette and layout | Supports responsive shell and feature cards |
| Static hosting | S3 | Target production artefact store for `dist/` output | Immutable object storage plus deployment versioning |
| Content delivery | CloudFront | Target edge delivery layer | TLS termination, cache control, header enforcement |
| Browser API | MutationObserver | Used to rename participant labels as widget DOM updates | Protects presentation consistency during bot and agent transitions |
| Messaging contract | `window.amazon_connect` | Used for styles, display names, snippet selection, contact attributes, and event hooks | Acts as the core runtime integration boundary |
| Delivery artefact | `dist/` folder | Vite production build output | Promoted to CDN and origin under release governance |

### Integration Points

| Integration | Direction | Purpose | Key Control |
| --- | --- | --- | --- |
| Browser -> CloudFront | Inbound customer traffic | Deliver Meridian page shell and static assets | HTTPS, caching, WAF or edge security policies |
| CloudFront -> S3 | Origin fetch | Retrieve versioned static build artifacts | Bucket policy and origin access controls |
| Browser -> Amazon Connect hosted script | Outbound browser dependency | Load chat widget runtime | Approved origins and CSP / response-header allow rules |
| Browser -> Amazon Connect chat service | Session runtime | Initiate and maintain customer chat | TLS, origin allowlist, Connect snippet governance |
| Amazon Connect -> Contact flows | Backend processing | Route chat to ARIA or a live advisor | Flow version control and operational testing |
| Contact flows -> ARIA / advisor queues | Downstream orchestration | Resolve customer intent and escalation paths | Service dependency and routing governance |
| Browser -> responsive UI layer | Local rendering | Surface Meridian navigation, hero, features, and footer | Brand design assurance and accessibility review |

The architecture is intentionally opinionated around separation of concerns. Meridian owns experience composition and deployment, Amazon Connect owns the conversational session runtime, and the ARIA platform owns banking capability execution. This boundary clarity simplifies incident triage: widget shell issues are front-end or CDN concerns, while conversation failures are routed into Connect and downstream platform support processes.


## Service Interfaces

### APIs/Contracts

| Interface | Type | Observed Use | Notes |
| --- | --- | --- | --- |
| `window.amazon_connect('styles', ...)` | Hosted widget configuration | Sets open/close button colours and icon type | Controls visible chat-launch affordance |
| `window.amazon_connect('customDisplayNames', ...)` | Hosted widget configuration | Maps transcript labels such as bot and system display names | Used with MutationObserver as a defence-in-depth presentation control |
| `window.amazon_connect('snippetId', ...)` | Hosted widget bootstrap | Associates the page with a specific Connect widget configuration | Snippet governance must be tied to release management |
| `window.amazon_connect('supportedMessagingContentTypes', ...)` | Messaging contract | Allows text, markdown, and interactive content types | Determines what content the widget is expected to render |
| `window.amazon_connect('contactAttributes', ...)` | Session metadata injection | Provides routing metadata such as locale or auth hinting | Must never contain secrets or unnecessary regulated data |
| `window.amazon_connect('onChatConnected', ...)` | Event hook | Triggers post-connect label harmonisation | Useful for quality and UI consistency checks |
| `window.amazon_connect('onAgentConnect', ...)` | Event hook | Re-runs display normalisation when live agent joins | Supports clean transfer presentation |
| `window.amazon_connect('onChatDisconnected', ...)` | Event hook | End-of-session clean-up extension point | Used lightly in current implementation |

### Event/Message Interfaces

| Event / Message | Producer | Consumer | Operational Meaning |
| --- | --- | --- | --- |
| Initial widget script load | Browser | Hosted widget runtime | Bootstraps the chat control on page load |
| Chat session connected | Amazon Connect widget | Client-side event hook | Confirms session establishment and label refresh |
| Human agent connected | Amazon Connect widget | Client-side event hook | Indicates transfer from AI-only interaction to advisor participation |
| Dynamic transcript DOM insertion | Hosted widget iframe / DOM updates | MutationObserver | Triggers participant-name reconciliation |
| Customer text message | Customer browser | Amazon Connect chat service | Primary business interaction payload |
| Bot or advisor response | ARIA or advisor via Connect | Customer browser | Visible service outcome requiring latency monitoring |
| Session disconnected | Amazon Connect widget | Client-side event hook | Terminal event for support troubleshooting and journey completion |

### UI Interfaces

| UI Surface | Purpose | Design Notes |
| --- | --- | --- |
| Header and navigation | Orient customer on Meridian site | Uses bank colours, wordmark, and anchor links |
| Hero section | Advertise digital banking proposition and prompt engagement | Keeps chat as contextual support rather than the only call to action |
| Feature cards | Reassure customers about transfers, insights, security, and ARIA support | Supports trust-building before chat entry |
| Hosted chat button overlay | Primary chat initiation control | Rendered by hosted widget, styled to Meridian palette |
| Hosted chat panel | Conversation surface for AI and advisor interactions | Managed by Connect, not locally rendered |
| Responsive layout | Support mobile and smaller browsers | Breakpoints in CSS reduce risk of overlay collision and layout compression |
| Footer | Display regulated banking text and identity | Important for trust and legal presentation |

The interface model is deliberately minimalistic: Meridian supplies experience framing and configuration, while Connect supplies the secure and operationally mature conversation frame. This is appropriate for a banking environment because it limits bespoke client complexity while still preserving brand control.


## Service Dependencies

### Internal Dependencies

- `src/App.jsx` for Meridian-branded presentation and customer page context.
- `src/components/ConnectChatWidget.jsx` for display-name normalisation and event-hook attachment.
- `index.html` for hosted widget bootstrap, snippet configuration, and initial contract registration.
- `package.json` scripts for build and preview lifecycle management.
- Release pipeline that publishes `dist/` output into the approved static-hosting path.

### External Dependencies

| Dependency | Type | Why Required | Dependency Risk |
| --- | --- | --- | --- |
| Amazon Connect hosted widget endpoint | Managed AWS service | Supplies the chat widget client and runtime frame | High — widget cannot launch if unavailable or misconfigured |
| Amazon Connect Chat service | Managed AWS service | Provides session initiation, message transport, and participant state | High — core transactional dependency |
| Connect contact flows | Platform service | Route chats to ARIA or advisor queues | High — incorrect flow versioning breaks service journeys |
| ARIA Banking Agent | Internal downstream service | Delivers AI conversation capability | High — affects containment and first-response quality |
| Human advisor queues | Operational dependency | Provide assisted-service fallback when escalation is required | Medium to High — impacts transfer completion |
| S3 static origin | AWS infrastructure | Stores production build artifacts | Medium — mitigated by durable object storage and release controls |
| CloudFront | AWS infrastructure | Provides edge delivery, TLS, and cache management | High for customer reachability |
| Customer browser | Execution environment | Runs React shell and hosted widget script | Medium — subject to device, privacy, and extension variability |
| Approved origins configuration | Connect governance setting | Allows widget initialisation from Meridian domains | High — frequent source of avoidable launch failures |
| Security header policy | Edge control | Restricts script, frame, and connect destinations | High — misalignment causes CSP or load failures |

The most important dependency characteristic is that the service is only as reliable as the end-to-end chain from static asset delivery to Connect configuration. A front-end-only green build is insufficient evidence of readiness; production confidence depends equally on correct approved origins, snippet governance, contact-flow versioning, and downstream agent availability.


## Service Level Objectives

| Objective | Target | Measurement Scope | Comment |
| --- | --- | --- | --- |
| Availability | 99.9% monthly | Customer-visible Meridian chat entry point in production | Aligned to Tier 1 digital channel expectations |
| Widget bootstrap latency | <= 2.5 seconds p95 after page ready on standard broadband | Browser load of hosted widget control | Measures readiness of the chat-launch surface |
| Time to chat session creation | <= 5 seconds p95 | Customer click to active session state | Dependent on Connect and origin allowlist correctness |
| Time to first bot response | <= 8 seconds p95 | Start of chat to first AI greeting | Downstream dependency on ARIA and contact flows |
| Transfer completion | >= 98% of initiated transfer attempts | AI-to-human handoff workflow | Protects assisted-service continuity |
| Throughput | Designed for CDN-scale page delivery and contact-centre quota-managed chat concurrency | Static shell plus managed chat sessions | Capacity governed more by Connect quotas than web-server limits |
| RTO | 4 hours | Channel restoration after Priority 1 outage | Aligned to Tier 1 platform objective |
| RPO | 1 hour | Recoverable configuration or deploy-state loss | Static site is largely reproducible; RPO applies to deployment metadata and config |

These objectives intentionally distinguish static delivery from conversational delivery. The page shell may load successfully while the hosted widget still fails due to approved-origin or contact-flow issues. Service reviews therefore need separate indicators for page reachability, widget initialisation, session creation, and downstream conversational responsiveness.

Error-budget consumption should be reviewed jointly by Digital Banking, Connect Operations, and the ARIA platform owner because no single team controls the full customer journey. This shared-governance approach is necessary for a channel that is thin at the edge but highly dependent on managed downstream services.


## Operational Model

### Support Tiers L1/L2/L3

| Tier | Team | Responsibilities | Typical Tools |
| --- | --- | --- | --- |
| L1 | Service Desk / Digital Operations | Triage customer reports, validate reachability, check known incidents, perform first-line comms | Status pages, synthetic checks, runbooks, browser reproduction |
| L2 | Digital Channel Engineering / Connect Operations | Investigate widget load, approved origins, deployment, and contact-flow issues | CloudFront logs, S3 release records, Connect console, browser diagnostics |
| L3 | ARIA Platform / AWS Platform Engineering | Resolve deep platform failures, Connect service issues, ARIA routing, or security-header problems | AWS consoles, CI/CD records, observability stack, code repo |

### On-Call Model

The service follows the Meridian digital-channel on-call rota for customer-facing incidents, with explicit dependency escalation into Connect Operations and the ARIA platform. L1 records the incident, L2 owns technical triage for page and widget behaviour, and L3 is engaged whenever the symptom crosses into Connect session handling, ARIA execution, or edge-security policy defects.

Changes to approved origins, snippet configuration, CloudFront response headers, or contact-flow targets must be treated as controlled changes because they are common outage drivers. Hypercare coverage is required for initial go-live and for any brand-wide redesign that changes the shell around the widget.

### Incident Classification

| Severity | Definition | Example |
| --- | --- | --- |
| P1 | Channel unavailable for most customers or major bank domain | Widget cannot launch in production due to origin or runtime failure |
| P2 | Material feature degradation with workaround | Chat launches but transfer to a live advisor consistently fails |
| P3 | Partial or low-impact degradation | Brand label formatting or responsive layout issue on a non-core viewport |
| P4 | Informational or planned enhancement | Minor content or styling refinement without service-impacting behaviour |


## Security & Compliance

### Security Classification

The document classification is Internal, while the service itself is a customer-facing digital channel that must be engineered to handle regulated banking interactions safely. The widget must therefore be treated as a public ingress surface with confidential operational configuration and tightly controlled browser integration policies.

### AuthN/AuthZ

- Customer access to the page is unauthenticated at channel-entry level unless Meridian wraps the page inside an authenticated web journey.
- The widget must never contain embedded AWS credentials, API keys, or bank secrets in shipped JavaScript or HTML.
- Session-level authentication and authorisation for banking actions occur downstream in ARIA, Connect flows, and customer-auth journeys rather than in the widget shell.
- Any contact attributes injected from the browser must be limited to non-secret metadata such as locale or experience context.
- Approved origins in Amazon Connect act as a critical browser-side authorisation control for where the hosted widget may initialise.

### Data Classification

| Data Type | Classification | Handling Expectation |
| --- | --- | --- |
| Static site assets | Internal / public-facing content | May be publicly served but must be integrity controlled through release management |
| Branding and marketing copy | Public | No special protection beyond normal content governance |
| Session metadata in browser | Confidential operational metadata | Minimise payload; never include secrets or unnecessary personal data |
| Customer conversation content | Confidential banking interaction data | Handled by Connect and downstream platform controls, not persisted by the widget itself |
| Authentication outcomes and routing context | Confidential regulated data | Consumed downstream under platform security controls |

### Regulatory Requirements

- HTTPS-only delivery with modern TLS policy for all production customer access.
- Content security policy or equivalent edge header controls aligned to hosted widget and frame dependencies.
- CORS and origin restrictions limited to approved Meridian web properties and controlled test domains.
- Alignment with FCA expectations for resilience, customer communications, and outsourcing governance where managed services are used.
- Alignment with GDPR data-minimisation principles by keeping sensitive data processing out of the browser wherever possible.
- Alignment with Meridian's secure-by-design standards for third-party script governance and release assurance.

A key security design principle is that the widget should never become a shadow backend. All privileged banking logic, PII processing, and transcript retention live in downstream controlled services. The browser front end remains intentionally simple so the attack surface is constrained to presentation, delivery, and configuration.


## Capacity & Scalability

### Current Capacity

The current component is a static front-end workload with modest asset size and no dedicated application servers. Capacity is therefore dominated by CloudFront edge throughput for page loads and by Amazon Connect chat concurrency for actual conversation sessions. The service can scale web delivery horizontally through CDN behaviour, while chat concurrency remains governed by Connect instance quotas and downstream ARIA capacity.

| Capacity Dimension | Current Characteristic | Planning Implication |
| --- | --- | --- |
| Static asset serving | CDN-delivered and origin-backed by S3 | Scales elastically with edge distribution |
| Front-end runtime | Runs entirely in browser | No server pool sizing required for page rendering |
| Chat session concurrency | Managed by Amazon Connect quotas and routing capacity | Requires operational quota review rather than web-tier autoscaling |
| Build output | Vite-generated `dist/` bundle | Release packaging and cache invalidation must be controlled |
| Responsive design | Single codebase for desktop and mobile | Functional testing must cover multiple viewport classes |

### Scaling Approach

- Use CloudFront edge caching and origin versioning for burst traffic during campaigns or incident-driven support spikes.
- Treat Connect chat concurrency and downstream agent / ARIA capacity as the primary scaling control points.
- Keep the front-end bundle lean so session initiation is not dominated by customer-side download cost.
- Separate static-delivery scaling from conversational scaling in capacity reviews and operational dashboards.
- Validate that approved origins, snippet configuration, and contact-flow targets are replicated correctly when onboarding new domains or brands.

### Known Limits

| Limit Area | Known Constraint | Mitigation |
| --- | --- | --- |
| Approved origins | Widget fails to initialise if domain not allowlisted in Connect | Change control and pre-production validation |
| Hosted widget dependency | Front-end cannot compensate for upstream hosted widget outage | Operational dependency monitoring and communication plan |
| Browser extensions / privacy controls | Third-party blocking can affect hosted script load | User messaging, fallback contact options, synthetic testing |
| Viewport collisions | Fixed-position overlays can conflict with other page elements | Responsive UX testing across templates |
| Contact attributes | Excessive or sensitive metadata should not be injected from client | Schema governance and security review |


## Monitoring & Observability

### Key Metrics

| Metric | Source | Why It Matters |
| --- | --- | --- |
| CloudFront availability and error rate | CloudFront metrics | Detects customer reachability issues for the page shell |
| Static origin errors | S3 / CloudFront origin metrics | Highlights bad deploys or missing assets |
| Widget script load success | Browser telemetry / synthetic checks | Detects hosted widget dependency failures |
| Chat initiation success | Connect channel analytics | Validates end-to-end session bootstrap |
| Time to first response | Connect / ARIA telemetry | Measures conversational responsiveness |
| Transfer rate and transfer failures | Connect analytics | Shows whether human fallback is functioning |
| Browser JavaScript errors | Client-side logging / RUM | Identifies release regressions in shell code |
| CSP or origin-policy violations | Browser console telemetry and synthetic scripts | Catches configuration drift rapidly |

### Logging Strategy

- Use CloudFront access logs or equivalent CDN telemetry for edge-delivery visibility.
- Capture structured browser-side error events for widget bootstrap and DOM-observer failures.
- Correlate chat start failures with Connect approved-origin and contact-flow change records.
- Rely on downstream Connect and ARIA telemetry for transcript, latency, and transfer observability.
- Preserve enough deployment metadata to associate customer-impacting defects with release versions and cache invalidations.

### Alerting Thresholds

| Alert | Threshold | Response Expectation |
| --- | --- | --- |
| CDN availability degradation | Error budget burn or 5xx spike above normal baseline | L2 digital channel triage within operational target |
| Widget launch failure | Synthetic check cannot open widget from production URL | Treat as high-priority customer-channel incident |
| Chat start success drop | Meaningful deviation from daily baseline | Joint Connect / ARIA investigation |
| Transfer failure spike | Sustained increase in failed AI-to-human handoffs | Contact-centre operational review and rollback check |
| Browser exception spike after release | Release-correlated error burst | Pause rollout and assess rollback |

### Dashboards

Operational dashboards should present page reachability, widget readiness, chat initiation, transfer outcomes, and release version status on a single view. Separate engineering dashboards should expose deeper CDN, browser, and Connect signals so support teams can quickly determine whether a fault is at the edge, in Connect configuration, or downstream in ARIA.


## Disaster Recovery & Business Continuity

### DR Strategy

The widget service supports business continuity through its low-complexity static architecture. Front-end assets can be rebuilt rapidly from source, republished to a clean S3 origin, and redistributed through CloudFront. Because customer conversation state is not owned by the widget shell, recovery focuses on restoring access and correct configuration rather than replaying application databases.

### RTO/RPO Targets

| Measure | Target | Rationale |
| --- | --- | --- |
| RTO | 4 hours | Tier 1 digital channel restoration target |
| RPO | 1 hour | Protects release metadata, config state, and deployment artefacts |

### Failover Approach

1. Rebuild or promote the last known-good static bundle and publish to the production S3 origin or standby origin.
2. Invalidate CloudFront caches or switch origin configuration to the verified recovery build.
3. Reconfirm approved origins and widget snippet configuration in Amazon Connect before reopening service.
4. Run synthetic chat-start checks from desktop and mobile footprints to validate true service recovery.
5. If Connect or downstream ARIA is unavailable, publish a customer-facing fallback contact route rather than exposing a broken chat entry point.

Business continuity for this service is tightly coupled to Meridian's ability to provide alternative assisted-service channels. In a prolonged outage, the bank must prioritise clear customer messaging and redirect users to secure phone or authenticated digital alternatives.


## Service Transition Plan

### Transition Phases

| Phase | Objective | Key Activities | Exit Criteria |
| --- | --- | --- | --- |
| Design assurance | Confirm architecture and controls | Review repo implementation, branding, widget configuration, and boundary assumptions | Architecture sign-off completed |
| Build verification | Validate deployable artefact | Run `npm run build`, inspect `dist/`, verify hosted widget contract registration | Build passes and artefacts are reproducible |
| Integration testing | Validate end-to-end channel flow | Test approved origins, chat launch, AI response, live-agent transfer, and disconnect journeys | Core user journeys pass |
| Operational readiness | Prepare support organisation | Publish runbook, monitoring, alert routing, and incident ownership | Support sign-off completed |
| Go-live | Introduce service into production | Deploy static assets, validate CDN and Connect config, monitor hypercare | Go-live checklist fully complete |
| Hypercare | Stabilise after launch | Daily metric review and rapid rollback capability | Stable trend over agreed observation period |

### Acceptance Criteria

- Production build completes successfully and produces deterministic `dist/` artifacts.
- Meridian branding, footer text, and responsive layout are approved by customer-experience stakeholders.
- Approved origins are configured for each production domain and validated with live browser tests.
- Hosted widget loads successfully and starts chat sessions with expected content types enabled.
- Transfer from ARIA to a human advisor is demonstrated in a controlled test.
- Monitoring, alerting, and support ownership are active before customer traffic is enabled.
- Rollback path to previous static bundle is rehearsed and documented.

### Go-Live Checklist

- Change record approved by Digital Banking, Connect Operations, and Security.
- Release candidate build tagged and stored in controlled artifact location.
- S3 origin updated with versioned bundle and integrity check completed.
- CloudFront distribution updated or invalidated with expected TTL behaviour.
- Approved origins in Connect include all live Meridian domains and no unnecessary domains.
- Snippet configuration aligned to the intended production Connect widget instance.
- Synthetic monitoring enabled for page load and chat launch.
- Support teams briefed on P1 and P2 failure patterns.
- Fallback customer contact route prepared in case rollback is needed.
- Hypercare bridge and reporting cadence agreed for the first production window.


## Training & Knowledge Transfer

Operational introduction of the service requires structured knowledge transfer to Service Desk, Digital Operations, Connect Operations, and the ARIA platform team. Training should focus on the boundary between the static channel shell and the hosted chat runtime so support teams know where to triage CDN, browser, Connect, and downstream agent issues.

| Audience | Training Topic | Outcome |
| --- | --- | --- |
| L1 Service Desk | Recognising widget launch failures and customer symptom capture | Accurate first-line triage and user guidance |
| Digital Channel Engineering | Build, deploy, cache invalidation, and browser diagnostics | Independent support for shell and release issues |
| Connect Operations | Approved origins, snippet governance, and transfer-path validation | Reduced config-driven outages |
| ARIA Platform Team | Channel-specific customer symptom interpretation | Faster cross-team incident resolution |
| Product / CX | Brand review checkpoints and go-live reporting | Confidence in customer-facing quality |

Knowledge transfer should include a walkthrough of `App.jsx`, `ConnectChatWidget.jsx`, and `index.html`, plus a live demonstration of a successful chat journey and a deliberately misconfigured approved-origin failure. This creates operational literacy around the most likely real-world defect patterns.


## Risk Register

| ID | Risk | Category | Probability | Impact | Mitigation | Owner | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| MCW-R1 | Production origin not added to Amazon Connect approved origins, preventing widget launch | Configuration | Medium | High | Treat approved-origin changes as release gates and validate with synthetic and browser tests | [OWNER_NAME] | Open |
| MCW-R2 | Hosted widget script or frame blocked by security headers after CDN change | Security / Availability | Medium | High | Control CSP and response-header changes through security review and regression testing | [OWNER_NAME] | Open |
| MCW-R3 | Downstream ARIA or transfer path failure is perceived by customers as a widget outage | Dependency | Medium | High | Provide layered observability and clear incident-routing playbooks | [OWNER_NAME] | Open |
| MCW-R4 | Responsive overlay conflicts with other page elements on smaller devices | UX | Low | Medium | Run viewport regression tests across supported templates and breakpoints | [OWNER_NAME] | Open |
| MCW-R5 | Non-essential metadata added to contact attributes from browser side | Security / Privacy | Low | High | Enforce attribute schema review and prohibit sensitive data in front-end config | [OWNER_NAME] | Open |
| MCW-R6 | CloudFront cache serves stale widget configuration after urgent change | Release | Medium | Medium | Use versioned assets, explicit invalidation, and release rollback discipline | [OWNER_NAME] | Open |


## Approvals

| Role | Name | Signature | Date |
| --- | --- | --- | --- |
| Service Owner | [NAME] |  | [DATE] |
| Digital Banking Product Owner | [NAME] |  | [DATE] |
| Connect Operations Lead | [NAME] |  | [DATE] |
| Security Reviewer | [NAME] |  | [DATE] |
| Architecture Review Authority | [NAME] |  | [DATE] |

