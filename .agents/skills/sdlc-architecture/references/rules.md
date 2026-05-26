# SDLC Architecture Validation Rules

This reference defines the ten `ARC-NNN` validation rules enforced by `validate_architecture.py`. The rules align to TOGAF ADM, ISO/IEC/IEEE 42010, the C4 model, and arc42-style architecture documentation practices.

## Severity Model

- **CRITICAL** — mandatory architecture artefact missing; the phase output is not reviewable.
- **HIGH** — major design completeness gap; fix before downstream engineering work proceeds.
- **MEDIUM** — important documentation quality issue; address before formal sign-off.
- **LOW** — advisory improvement needed for production-grade architecture packs.

## Rule Index

| Rule ID | Severity | Section | Summary |
|---------|----------|---------|---------|
| ARC-001 | CRITICAL | HLD | HLD document exists at architecture/hld.md |
| ARC-002 | CRITICAL | Component Breakdown | At least one component defined in HLD |
| ARC-003 | HIGH | Component Diagram | Component diagram (.mmd) exists |
| ARC-004 | HIGH | ADRs | At least one ADR exists in architecture/adrs/ |
| ARC-005 | HIGH | Technology Stack | Technology stack document exists |
| ARC-006 | MEDIUM | Component Breakdown | Each component has a defined responsibility |
| ARC-007 | MEDIUM | Integration Points | Integration points/interfaces documented |
| ARC-008 | MEDIUM | Non-Functional Requirements | Performance, scalability, and security addressed |
| ARC-009 | LOW | Deployment Architecture | Deployment model described |
| ARC-010 | LOW | Known Risks & Trade-offs | Architecture risk assessment present |

## ARC-001 — HLD document exists at architecture/hld.md

**Severity:** CRITICAL

### ✅ Pass example
```text
architecture/hld.md exists and contains structured design content.
```

### ❌ Fail example
```text
No HLD file was generated.
```

## ARC-002 — At least one component defined in HLD

**Severity:** CRITICAL

### ✅ Pass example
```md
## Component Breakdown
| Component | Responsibility | Technology | Interfaces |
| --- | --- | --- | --- |
| API Layer | Handle requests | Python | HTTP |
```

### ❌ Fail example
```md
## Component Breakdown
TBD
```

## ARC-003 — Component diagram (.mmd) exists

**Severity:** HIGH

### ✅ Pass example
```text
architecture/component-diagram.mmd
```

### ❌ Fail example
```text
Diagram was mentioned in prose only; no Mermaid source exists.
```

## ARC-004 — At least one ADR exists in architecture/adrs/

**Severity:** HIGH

### ✅ Pass example
```text
architecture/adrs/001-initial-architecture-baseline.md
```

### ❌ Fail example
```text
No ADR files were created.
```

## ARC-005 — Technology stack document exists

**Severity:** HIGH

### ✅ Pass example
```text
architecture/tech-stack.md exists and explains recommended technologies.
```

### ❌ Fail example
```text
The HLD references technologies casually but there is no dedicated stack document.
```

## ARC-006 — Each component has a defined responsibility

**Severity:** MEDIUM

### ✅ Pass example
```md
| API Layer | Expose authenticated request/response endpoints | Python | HTTP |
```

### ❌ Fail example
```md
| API Layer | TBD | Python | HTTP |
```

## ARC-007 — Integration points/interfaces documented

**Severity:** MEDIUM

### ✅ Pass example
```md
## Integration Points
| Integration Point | Direction | Protocol / Interface | Notes |
| --- | --- | --- | --- |
| Payments Service | Outbound | REST API | Transaction settlement |
```

### ❌ Fail example
```md
Integrations will be defined later.
```

## ARC-008 — Non-functional requirements addressed (performance, scalability, security)

**Severity:** MEDIUM

### ✅ Pass example
```md
## Non-Functional Requirements
- Performance: p95 latency under 300ms.
- Scalability: stateless services scale horizontally.
- Security: least privilege and audited secrets.
```

### ❌ Fail example
```md
## Non-Functional Requirements
- Reliability TBD.
```

## ARC-009 — Deployment model described

**Severity:** LOW

### ✅ Pass example
```md
## Deployment Architecture
The service is deployed through CI/CD into isolated environments with environment-specific configuration.
```

### ❌ Fail example
```md
## Deployment Architecture
TBD
```

## ARC-010 — Architecture risk assessment present

**Severity:** LOW

### ✅ Pass example
```md
## Known Risks & Trade-offs
| Risk | Impact | Trade-off / Mitigation |
| --- | --- | --- |
| Monolith coupling | Slower change | Plan decomposition ADRs |
```

### ❌ Fail example
```md
No risk assessment was recorded.
```
