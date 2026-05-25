# Industry Standards Reference for Deployment Playbooks

This reference consolidates the external standards and operating models that inform the `deployment-playbook` skill. Use it when tailoring a playbook for regulated environments, production reliability reviews, or change governance processes.

## Core standards and references

| Standard / Reference | Why it matters | URL |
|----------------------|----------------|-----|
| ITIL v4 | Governs change enablement, approval paths, change scheduling, and service management alignment | https://www.axelos.com/best-practice-solutions/itil |
| DORA (DevOps Research & Assessment) | Connects deployment practices to delivery performance and operational outcomes | https://dora.dev/ |
| Google SRE Book | Provides service reliability, monitoring, incident response, and error budget guidance | https://sre.google/sre-book/table-of-contents/ |
| ISO/IEC 20000-1:2018 | Formal IT service management system standard, including change control expectations | https://www.iso.org/standard/70636.html |
| ISO 22301:2019 | Business continuity framework relevant to rollback, resilience, and recovery planning | https://www.iso.org/standard/75106.html |
| NIST SP 800-160 Vol 2 Rev 1 | Resilient systems engineering guidance for dependable operations and recovery planning | https://csrc.nist.gov/publications/detail/sp/800-160/vol-2-rev-1/final |
| CAB Best Practices | Practical guidance for operating a Change Advisory Board effectively | https://www.bmc.com/blogs/change-advisory-board/ |

## How these standards influence the playbook structure

### ITIL v4

ITIL v4 informs the Change Management, Approvals, Change Window, and governance-related sections. The playbook format captures the operational evidence typically reviewed during normal or emergency change authorization.

### DORA

DORA emphasizes delivery performance and learning loops. The playbook format aligns by requiring measurable success criteria, fast rollback planning, and post-deployment validation that supports improvement.

### Google SRE

SRE practices emphasize safe release engineering, observability, and failure recovery. The playbook format therefore requires validation steps, rollback triggers, escalation contacts, and SLO-aware success criteria.

### ISO/IEC 20000-1:2018

ISO 20000 expects controlled service management processes, especially around change, approval, and evidence. The Document Control, Approvals, and Change Management sections help create auditable artifacts.

### ISO 22301:2019

Business continuity and operational resilience depend on recoverability. The Rollback Strategy, RTO, and dependency-aware deployment phases support that outcome.

### NIST SP 800-160 Vol 2 Rev 1

NIST resilient systems guidance reinforces designing for degraded operation, recovery, and mission continuity. This is reflected in rollback triggers, phased rollout, risk logging, and escalation planning.

## RAID log guidance

A RAID log records:

- **Risk** — a potential event that could negatively affect the deployment
- **Assumption** — a condition accepted as true for planning purposes
- **Issue** — a current problem requiring action
- **Dependency** — an external prerequisite, handoff, or constraint

The deployment-playbook skill uses a practical RAID-style risk register in markdown table form so the document stays readable while still capturing probability, impact, and ownership.

## DORA Four Key Metrics

The DORA metrics most relevant to deployment playbooks are:

1. **Deployment frequency** — how often the team deploys to production.
2. **Lead time for changes** — the time from commit to successful production deployment.
3. **Change failure rate** — the proportion of deployments that cause degraded service or require remediation.
4. **Time to restore service** — how quickly the service is recovered after a failed deployment.

A high-quality playbook contributes to better DORA outcomes by reducing ambiguity, improving readiness, making rollback faster, and ensuring validation is repeatable.

## Practical implications for playbook authors

When authoring a deployment playbook in an enterprise environment:

- use explicit change type and approval language
- include measurable success criteria tied to service indicators
- make rollback triggers observable and objective
- define stakeholder communication timing up front
- record dependencies and risks in a structured register
- capture post-deployment validation and closeout steps

## Additional references

- DORA research hub: https://dora.dev/
- Google SRE workbook and companion guidance: https://sre.google/resources/
- CAB best-practice explainer: https://www.bmc.com/blogs/change-advisory-board/
