# [PROJECT_NAME] Change Management Playbook

## 1. Document Control

| Field | Value |
|-------|-------|
| Title | [PROJECT_NAME] Normal Change Deployment Playbook |
| Playbook ID | PLY-CHG-001 |
| Version | 1.0.0 |
| Status | In Review |
| Owner | [OWNER] |
| Created | [DATE] |
| Last Reviewed | [DATE] |
| Approvers | Change Manager; Service Owner; Platform Lead |

## 2. Purpose & Scope

### Objective

This playbook governs a **Normal Change** for [PROJECT_NAME]. It is designed for organizations that require formal risk assessment, CAB review, implementation evidence, and a post-implementation review.

### In-Scope

- Application code and infrastructure changes approved for this change record
- CAB governance activities, implementation evidence, and PIR tasks
- Stakeholder communications tied to this change

### Out-of-Scope

- Emergency changes not pre-approved through the Normal Change process
- Unrelated maintenance or platform upgrades outside this change record

## 3. Change Management

- **Change Type:** Normal
- **Change Window:** [DAY], [TIME_UTC] – [TIME_UTC] UTC
- **CAB Approval Path:** Standard CAB review; service owner and change manager sign-off required.
- **Freeze Periods:** Confirm no quarterly-end or holiday blackout conflicts before scheduling.
- **Implementation Owner:** [OWNER]

## 4. Change Request Summary

| Item | Detail |
|------|--------|
| Change Type | Normal |
| Business Reason | Deliver approved release scope while maintaining service continuity |
| Requested By | [OWNER] |
| Planned Window | [CHANGE_WINDOW] |
| Customer Impact | Low to moderate; brief transient degradation may occur during cutover |
| Rollback Window | Available throughout implementation |
| Related Ticket | <!-- PLACEHOLDER: insert change request or service management record --> |

## 4. Scope and Impact Assessment

### In-Scope

- Application code deployment
- Infrastructure-as-code updates tied to the approved release
- Observability dashboard review and post-change smoke tests

### Out-of-Scope

- Broad platform upgrades
- DR failover testing
- Manual data remediation unrelated to the release

### Impacted Services

- Customer-facing APIs and associated background services
- Internal support tools dependent on [PROJECT_NAME]
- Monitoring, alerting, and support workflows tied to service health

## 5. CAB Review Inputs

Provide the following before CAB review:

- risk register with named owners
- deployment and rollback steps with timing estimates
- validation evidence from non-production environments
- communication plan for customers, support, and internal stakeholders
- evidence that freeze periods and conflicting changes have been checked

## 6. CAB Approval Workflow

1. Submit the change request and attach this playbook.
2. Confirm service owner review is complete.
3. Review risk, impact, and implementation timing with CAB.
4. Record CAB decision, conditions, and required follow-up actions.
5. Confirm implementation owner accepts the final execution conditions.

### CAB Decision Record

| Field | Detail |
|-------|--------|
| CAB Decision | <!-- PLACEHOLDER: approved / approved with conditions / deferred --> |
| Conditions | <!-- PLACEHOLDER: mandatory pre-conditions from CAB --> |
| Decision Date | [DATE] |
| Decision Owner | Change Manager |

## 7. Implementation Readiness Checklist

- [ ] Release artifact signed off by engineering
- [ ] Runbook and rollback artifact reviewed by on-call engineer
- [ ] Monitoring dashboards and alert routes verified
- [ ] Support team briefed on expected service behavior
- [ ] Freeze-calendar conflict check completed
- [ ] Required approvals captured in the Approvals section

## 7. Environment Matrix

| Environment | Region | Tier | Purpose | Deployment Order |
|-------------|--------|------|---------|------------------|
| Staging | [AWS_REGION] | Non-prod | Change validation before production | 1 |
| Production | [AWS_REGION] | Production | Live customer traffic — authorized change window only | 2 |

## 8. Deployment Strategy

### Phase 1 — Pre-Window Confirmation

**Objective:** Confirm all governance and technical prerequisites before the change window opens.

**Steps**
1. Confirm CAB conditions are satisfied.
2. Confirm support coverage and escalation contacts are online.
3. Verify the prior stable release remains deployable.
4. Reconfirm health baseline for critical service indicators.

**Dependencies:** CAB approval, approved artifact, operator coverage.

**Duration Estimate:** 15 minutes.

**Rollback Trigger:** If any mandatory CAB condition is unmet, abort before execution.

### Phase 2 — Controlled Implementation

**Objective:** Execute the approved change within the authorized window.

**Steps**
1. Start the deployment using the approved automation path.
2. Validate step completion at each checkpoint.
3. Hold the rollout if critical alerts, failed smoke tests, or abnormal latency occur.
4. Continue only after checkpoint owner confirmation.

**Dependencies:** CI/CD platform availability, healthy downstream dependencies.

**Duration Estimate:** 30 minutes.

**Rollback Trigger:** Roll back if error rate exceeds threshold, user transactions fail, or dependency health becomes unstable.

### Phase 3 — Validation and Closure

**Objective:** Confirm service stability and close the change record with evidence.

**Steps**
1. Run smoke tests and review dashboards.
2. Obtain business or service-owner sign-off.
3. Publish completion update.
4. Record evidence for PIR.

**Dependencies:** Stable service telemetry and validator results.

**Duration Estimate:** 20 minutes.

**Rollback Trigger:** Initiate rollback if validation fails or if business-critical workflows are impaired.

## Rollback Strategy

### Rollback Time Objective (RTO)

Restore the last known good state within **30 minutes** of a rollback decision.

### Rollback Trigger Conditions

- authentication or payment critical paths fail
- Sev1 or Sev2 alerts trigger and persist for more than five minutes
- data integrity checks fail
- synthetic tests fail across more than one production availability zone

## Success Criteria

- Zero Sev1 or Sev2 incidents caused by this change
- All smoke tests pass in production within the observation window
- Key customer journeys verified by service owner
- CAB post-implementation review evidence captured

## Post-Deployment Validation

- [ ] All service health endpoints return HTTP 200
- [ ] Error rates and latency p99 within pre-change baselines
- [ ] Business-critical workflows validated by service owner
- [ ] Change record updated with deployment evidence and closed

## Contacts & Escalation

| Role | Name | Contact | Escalation Level |
|------|------|---------|------------------|
| Implementation Owner | [NAME] | [CONTACT] | L1 — change execution |
| Service Owner | [NAME] | [CONTACT] | L1 — business decisions |
| Change Manager | [NAME] | [CONTACT] | L2 — governance escalation |
| On-Call Engineer | [NAME] | [PAGERDUTY] | L2 — technical incidents |
| Incident Manager | [NAME] | [CONTACT] | L3 — P1/P2 escalation |

## 10. Risk Register

| ID | Risk/Issue | Category | Probability | Impact | Mitigation | Owner | Status |
|----|------------|----------|-------------|--------|------------|-------|--------|
| R-001 | Dependency latency increase during cutover | Technical | Medium | High | Pause rollout, validate downstream service health, and use rollback if threshold breach persists | Platform Lead | Open |
| R-002 | Support teams unaware of rollout timing | Operational | Low | Medium | Send pre-window and in-flight updates to support and incident channels | Release Manager | Open |
| R-003 | CAB condition missed before implementation | Governance | Low | High | Use pre-window readiness checklist and explicit CAB condition review | Change Manager | Open |

## 11. Communication Plan

| Phase | Audience | Channel | Owner | Timing |
|-------|----------|---------|-------|--------|
| Pre-CAB | Service Owner, Platform Lead | Change record comments | Release Manager | 2 business days before CAB |
| CAB Outcome | Engineering leadership, support | Email and change system update | Change Manager | Within 2 hours of CAB decision |
| Deployment Start | Operations, support, stakeholders | Slack / Teams release channel | Release Manager | At change window start |
| Validation Complete | CAB watchers, service owner | Change record and chat channel | Implementation Owner | After smoke tests pass |
| PIR Scheduled | Engineering and service management | Calendar invite and ticket update | Change Manager | Within 1 business day |

## 12. Post-Implementation Review (PIR) Checklist

- [ ] Did the change start and finish within the approved window?
- [ ] Were there any incidents, alerts, or service desk contacts caused by the change?
- [ ] Did rollback criteria trigger at any point?
- [ ] Were success criteria fully met?
- [ ] Are follow-up improvements required to tooling, testing, or documentation?
- [ ] Was the change record closed with complete evidence?

## 13. Approvals

| Role | Name | Signature | Date |
|------|------|-----------|------|
| Service Owner | <!-- PLACEHOLDER: name --> | __________________ | [DATE] |
| Change Manager | <!-- PLACEHOLDER: name --> | __________________ | [DATE] |
| Platform Engineering Lead | <!-- PLACEHOLDER: name --> | __________________ | [DATE] |
