# ISO 20000 / ITSM Change Management Reference

This reference summarizes practical change-management expectations commonly seen in ISO/IEC 20000-aligned service organizations and modern ITSM operating models.

## Change types and approval gates

### Standard change

- Pre-approved, repeatable, low-risk change
- Uses a documented implementation procedure
- Usually approved by policy rather than by case-by-case CAB review
- Requires periodic review to confirm the change remains low risk and repeatable

### Normal change

- Assessed for business impact, risk, and scheduling before implementation
- Requires approval from designated approvers and, where applicable, CAB review
- Should include implementation plan, rollback plan, validation steps, and communication plan

### Emergency change

- Used for urgent service restoration, critical security remediation, or regulatory response
- Approved via an expedited path, often involving an ECAB or on-call authority
- Must be reviewed after implementation and captured in the formal record

## Standard change pre-approval process

Organizations typically expect the following before a change is categorized as standard:

1. The implementation steps are documented and repeatable.
2. Risks are known and consistently low.
3. Rollback is proven and quick.
4. Required approvals are embedded in policy or service governance.
5. Evidence exists that the activity has succeeded previously without causing instability.

## Normal change CAB process

For normal changes, the usual governance path includes:

1. Change record created with scope, rationale, and implementation details.
2. Impact, risk, and dependency assessment completed.
3. Deployment playbook reviewed for sequencing, rollback, and validation completeness.
4. CAB or designated approvers review timing, customer impact, and support readiness.
5. Approved window is scheduled on the change calendar.
6. Post-implementation evidence is collected and the change is formally closed.

## Emergency change ECAB process

Typical emergency-change expectations:

- define why the emergency path is required
- record the specific risk of delaying the change
- identify the emergency approver or ECAB participants
- capture the implementation and rollback steps even if the document is brief
- perform a post-implementation review as soon as the incident stabilizes

## Post-implementation review (PIR) requirements

A production-grade playbook should support PIR by making it easy to record:

- what was deployed and when
- whether the deployment met the success criteria
- whether any rollback or workaround was required
- customer or business impact observed
- monitoring anomalies, incidents, or support tickets created
- follow-up actions for automation, documentation, or risk reduction

## Change freeze windows

Examples of common freeze windows include:

- quarterly earnings or board reporting periods
- peak holiday retail or travel dates
- payroll processing windows
- critical customer migrations
- major marketing campaign launches
- year-end financial close or fiscal cutover periods

A playbook should note the relevant freeze periods and confirm the change window does not conflict.

## Change success metrics

Useful change-management metrics include:

- on-time change start and finish rate
- deployment success rate
- change failure rate
- incidents caused by change
- rollback frequency
- mean time to restore service (MTRS)
- percentage of changes executed with complete evidence and approvals

## Guidance for authors

To keep a playbook ISO- and ITSM-friendly:

- clearly state the change type
- capture approval gates and owners
- define rollback conditions and RTO
- include evidence of readiness and post-change validation
- maintain version control and review dates in Document Control
