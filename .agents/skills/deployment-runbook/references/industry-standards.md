# Industry Standards and Reference Material

Use these references to justify structure, verification style, escalation guidance, and operational quality when writing production runbooks.

| Standard / Source | URL | Why it matters in a runbook |
|-------------------|-----|-----------------------------|
| Google SRE Book | https://sre.google/sre-book/table-of-contents/ | Canonical SRE guidance for safe operations, automation, and on-call excellence |
| Google SRE Workbook | https://sre.google/workbook/table-of-contents/ | Practical guidance for alerting, on-call response, and operational maturity |
| ITIL v4 Service Operations | https://www.axelos.com/best-practice-solutions/itil | Aligns runbooks with incident, change, and service operation disciplines |
| DevOps Handbook | https://itrevolution.com/product/the-devops-handbook/ | Supports fast feedback, safer change, and learning loops in operational procedures |
| AWS Well-Architected Operational Excellence Pillar | https://docs.aws.amazon.com/wellarchitected/latest/operational-excellence-pillar/welcome.html | AWS-native expectations for operations as code, observability, and event response |
| AWS Runbook Automation | https://docs.aws.amazon.com/systems-manager/latest/userguide/automation-documents.html | Useful for converting manual runbook steps into executable automation |
| DORA State of DevOps | https://dora.dev/research/ | Frames deployment frequency, MTTR, and change failure rate as operational outcomes |
| PagerDuty Runbook Best Practices | https://www.pagerduty.com/resources/learn/incident-response-runbook/ | Strong guidance for escalation, urgency, and communications |
| Atlassian Runbooks | https://www.atlassian.com/incident-management/runbooks | Helpful examples of incident-oriented and troubleshooting-oriented runbooks |
| Microsoft Azure Runbook standard | https://learn.microsoft.com/en-us/azure/automation/automation-runbook-types | Cross-cloud reference for executable operational procedures |

## How to use these references

### Google SRE Book

Use it to justify:

- verification after every step
- SLO-aware promotion and rollback gates
- clear ownership and escalation paths
- toil reduction and automation follow-up notes

### Google SRE Workbook

Use it to strengthen:

- on-call readiness
- alert interpretation
- incident response flow
- post-change observation windows

### ITIL v4 Service Operations

Use it for:

- change approval context
- incident categorization
- role clarity and handoffs
- service continuity and knowledge management

### DevOps Handbook

Use it for:

- fast, low-risk deployment patterns
- build-test-deploy feedback loops
- learning-oriented change logs
- shared ownership across development and operations

### AWS Well-Architected Operational Excellence

Use it for:

- cloud-native readiness checks
- metrics, alarms, and event response expectations
- immutable artifact handling and automation-first design
- clear rollback and recovery pathways

### DORA guidance

Use DORA metrics to make runbooks measurable:

- deployment frequency: how often the runbook is exercised
- lead time for changes: how fast safe releases move through the procedure
- change failure rate: whether the runbook catches risk before customer impact
- mean time to restore: how effective the rollback and troubleshooting sections are

## Recommended authoring stance

A production-quality runbook should be:

- **deterministic** — the operator knows exactly what to run next
- **observable** — success and failure are measurable
- **auditable** — version history and ownership are clear
- **trainable** — a new engineer can execute it with minimal context
- **automatable** — repeated manual work is clearly visible as future automation backlog
