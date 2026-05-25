---
name: service-introduction
description: >
  Generate and validate industry-standard Service Introduction Documents (SID) for any software project.
  Activate when a user asks to create a Service Introduction Document, SID, Service Design Package,
  or service onboarding document. Scans the project repository to auto-collect technical details,
  interactively prompts for business context, integrates with GitHub/GitLab MCP servers for remote repos,
  and generates a complete ITIL v4 / ISO 20000-1 compliant document.
  Use to create new SIDs from scratch, validate existing ones, or audit service onboarding completeness.
license: MIT
compatibility: >
  Python 3.9+ (python3 in PATH). Works with any project — language/framework agnostic.
  Optional: GitHub MCP server (github-mcp-server), GitLab MCP server, filesystem MCP server.
metadata:
  category: documentation
  tags: [sid, service-introduction, itil, iso-20000, togaf, service-transition, service-design, documentation, onboarding]
  author: agentskills
allowed-tools: [Bash, Read, Edit, Glob, Grep, Write, mcp__github-mcp-server__get_file_contents, mcp__github-mcp-server__search_code, mcp__filesystem__read_file, mcp__filesystem__list_directory]
---

## Activation

Activate this skill when the user asks for any of the following:

- Create a service introduction document
- Generate a SID
- Write a service onboarding doc
- Produce a service design package
- Document this service
- Create a service transition document
- Audit service onboarding completeness
- Validate an existing SID or service introduction record
- Describe what services a project runs and how they should be introduced into operations

Typical trigger phrases include: `create a service introduction document`, `generate a SID`, `write a service onboarding doc`, `service design package`, `what services do we run`, `document this service`, `SID for [project]`, and `create service transition document`.

## Industry Standard Format (Required Sections)

Every Service Introduction Document produced or validated by this skill must include the eighteen canonical sections below.

### 1. Document Control
Required fields:
- SID ID in `SID-[A-Z]{3}-NNN` format
- Version (semantic version)
- Status (`Draft`, `In Review`, `Approved`, `Active`, `Retired`)
- Classification (`Public`, `Internal`, `Confidential`, `Restricted`)
- Owner
- Reviewers
- Revision History table

### 2. Executive Summary
Required content:
- Minimum two paragraphs
- Service value proposition
- Key benefits
- Intended audience

### 3. Service Description
Required fields:
- Service Name
- Classification
- Service Tier (`1`, `2`, or `3`)
- Service Type (`New`, `Enhanced`, `Deprecated`)
- Category
- Business Unit

### 4. Business Context
Required content:
- Business Drivers list with at least three drivers
- Stakeholders & Personas table
- Business Value Metrics

### 5. Service Scope
Required content:
- In-Scope list
- Out-of-Scope list
- Service Boundaries description

### 6. Technical Architecture
Required content:
- Architecture Overview
- Technology Stack table
- Integration Points table

### 7. Service Interfaces
Required content:
- APIs / Contracts endpoint table
- Event / Message interfaces
- UI interfaces

### 8. Service Dependencies
Required content:
- Internal Dependencies table
- External Dependencies table with version, owner, and criticality columns

### 9. Service Level Objectives
Required content:
- Availability target as a numeric percentage
- Latency targets for p50, p95, and p99
- Throughput target
- RTO
- RPO

### 10. Operational Model
Required content:
- Support Tiers table covering L1 / L2 / L3
- On-Call Model
- Incident Classification table

### 11. Security & Compliance
Required content:
- Security classification
- Authentication and authorization mechanisms
- Data classification
- Regulatory requirements such as PCI-DSS, GDPR, FCA, HIPAA, SOC 2, or ISO 27001

### 12. Capacity & Scalability
Required content:
- Current capacity metrics
- Scaling approach
- Known limits table

### 13. Monitoring & Observability
Required content:
- Key Metrics table
- Logging strategy
- Alerting thresholds table
- Dashboard links

### 14. Disaster Recovery & Business Continuity
Required content:
- DR strategy
- RTO / RPO targets
- Failover approach

### 15. Service Transition Plan
Required content:
- Transition Phases table
- Acceptance Criteria checklist
- Go-Live Checklist

### 16. Training & Knowledge Transfer
Required content:
- Training requirements
- Documentation links
- Knowledge transfer plan

### 17. Risk Register
Required content:
- Markdown table with columns `ID`, `Risk/Issue`, `Category`, `Probability`, `Impact`, `Mitigation`, `Owner`, `Status`
- Minimum four populated rows

### 18. Approvals
Required content:
- Markdown table with `Role`, `Name`, `Signature`, `Date`
- Minimum three approvers for production-ready drafts

## Workflow

Follow this workflow exactly.

### Step 1: Trigger & Mode Selection
- Detect whether the user wants to **create**, **validate**, or **update** a Service Introduction Document.
- Ask or infer the operating mode: `generate` for a new SID, `validate` to check an existing SID, or `update` to enrich an existing SID with newly discovered information.
- When the request is ambiguous, prefer `generate` for greenfield documentation and `validate` for existing markdown files that already resemble a SID.

### Step 2: Repository Scanning (Automatic)
Run:
```bash
python3 .agents/skills/service-introduction/scripts/generate_sid.py --project-root <project_dir> --scan-only --output-json
```
Collect at least the following automatically:
- Project name from `package.json`, `pyproject.toml`, `go.mod`, or directory name
- Description from `README.md` first paragraph or package metadata
- Language and framework stack
- Runtime environments from `Dockerfile`, `docker-compose.yml`, `.env.example`, `infra/`, `cdk.json`, or `serverless.yml`
- APIs detected from OpenAPI / Swagger files or route definitions
- External services such as AWS managed services, databases, and third-party SDKs
- Existing documentation from `docs/`, `README.md`, `CHANGELOG.md`, or `CONTRIBUTING.md`
- CI/CD pipeline signals from `.github/workflows/`, `.gitlab-ci.yml`, `Jenkinsfile`, or CircleCI config
- Security configuration signals such as auth middleware, JWT libraries, encryption, or CSP headers

### Step 3: MCP-Enhanced Scanning (If Available)
When MCP servers are available:
- Use `mcp__github-mcp-server__get_file_contents` to read `README.md`, package manifests, and architecture docs from remote repositories.
- Use `mcp__github-mcp-server__search_code` to locate API routes, service clients, data models, and infrastructure definitions.
- Use `mcp__filesystem__list_directory` or `mcp__filesystem__read_file` to inspect documentation directories and remote workspaces.
- Merge MCP-derived context into the same generation context used by the local scanner.

### Step 4: Interactive Collection
Run `collect_info.py` for the fields that cannot be inferred safely.

Questions to ask in this exact order:
1. `What is the intended service tier? [1=Business Critical / 2=Business Important / 3=Supporting]`
2. `Who is the service owner? (name and team)`
3. `What is the primary business purpose of this service? (1-2 sentences)`
4. `What are the key business drivers for introducing this service? (list 3)`
5. `What regulatory or compliance frameworks apply? (PCI-DSS, GDPR, FCA, HIPAA, SOC2, ISO27001, none)`
6. `What is the target availability SLO? [99.9% / 99.5% / 99.0% / custom]`
7. `What is the RTO target? [1h / 4h / 8h / 24h / custom]`
8. `What is the RPO target? [1h / 4h / 8h / 24h / custom]`
9. `Who are the L1/L2/L3 support contacts?`
10. `Is there a go-live date planned? (YYYY-MM-DD or TBD)`
11. `What template type? [generic / api-service / ai-service / platform-service]`

All questions should present sensible defaults. In non-interactive mode (`--no-interactive`), load defaults from environment variables or context JSON.

### Step 5: Generate + Validate
- Merge automatic scan results with answers from `collect_info.py` into a single context dictionary.
- Select the correct template based on `template_type`.
- Substitute all `{{TOKEN}}` values while leaving user-fill placeholders such as `[NAME]`, `[OWNER_NAME]`, `[DATE]`, and `[REVIEWER_NAME]` intact.
- Write the output file to `docs/service-introduction/<project-name>-sid.md` unless `--output` overrides it.
- Immediately validate the generated document with `validate_sid.py`.
- Report results using the validator summary format: `Found N issues (X critical, Y high, Z medium, W low)`.
- If any critical or high findings remain, provide a short remediation guide and iterate until the document is production-ready.

## Standard Patterns

### SID identifier format
- Canonical format: `SID-XXX-NNN`
- Examples: `SID-API-001`, `SID-AIM-001`, `SID-PLT-001`
- `XXX` should be derived from significant project words or the operating domain.

### Canonical heading format
Use canonical `##` headings for the eighteen required sections. Numbering prefixes are permitted, but the normalized heading text must remain the same. Examples:

- `## 1. Document Control`
- `## 2. Executive Summary`
- `## 6. Technical Architecture`
- `## 11. Security & Compliance`

### Canonical heading normalisation rule
The validator uses the following normalisation function exactly:

```python
def canonical_heading(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"^\d+(?:\.\d+)*[.)-]?\s*", "", value)
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return value.strip()
```

## References

- `references/rules.md` — complete SID validation rule index with severity, examples, and remediation cues
- `references/itil-reference.md` — ITIL v4 Service Transition and Service Design Package alignment
- `references/iso-20000-reference.md` — ISO/IEC 20000-1:2018 clause mapping for service introduction
- `references/industry-standards.md` — ITIL, ISO 20000, TOGAF, COBIT, FCA, DORA, NIST, GDPR, PCI-DSS, SOC 2, ISO 27001, agentskills.io, and MCP references
- `assets/schema.json` — machine-readable rule metadata for all twenty SID rules
- `templates/service-introduction.md` — default generic SID template
- `templates/api-service-sid.md` — API and microservice oriented SID template
- `templates/ai-service-sid.md` — AI / ML service SID template with AI governance section
- `templates/platform-service-sid.md` — shared platform and infrastructure service SID template
- ITIL v4 Foundation (ISBN 978-0-11-331607-7)
- ISO/IEC 20000-1:2018 Service management systems requirements
- TOGAF ADM, COBIT 2019, FCA SYSC, DORA, and NIST CSF reference material
