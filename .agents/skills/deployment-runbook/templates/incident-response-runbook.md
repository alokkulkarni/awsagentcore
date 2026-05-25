# [PROJECT_NAME] Incident Response Runbook
Use this runbook to coordinate live incident response for [PROJECT_NAME], classify severity, contain customer impact, communicate clearly, and verify resolution before closing the incident.
## 1. Document Control
| Field | Value |
| --- | --- |
| Title | [PROJECT_NAME] Incident Response Runbook |
| Runbook ID | RNB-INC-001 |
| Version | 1.3 |
| Status | Approved |
| Owner | Site Reliability Engineering |
| Created | 2024-02-12 |
| Last Reviewed | [DATE] |
| Last Tested | [DATE] |
| Audience | On-call Engineer, Incident Commander, Communications Lead |
| Approved Change Window | 24x7 emergency use |
## 2. Overview
| Item | Details |
| --- | --- |
| Component | [PROJECT_NAME] production application, APIs, and supporting cloud infrastructure |
| Purpose | Provide a repeatable incident handling path from triage through recovery and handoff |
| Critical Dependencies | CloudWatch alarms, logs, tracing, deployment history, status page tooling, Slack, email |
| SLA/SLO Targets | Restore service before the monthly error budget is exhausted; MTTR target < 30 minutes for Sev1 / Sev2 |
| On-call Contact | PagerDuty: [PROJECT_NAME] Primary; Slack: #incident-bridge; Email: ops@example.com |
| Severity Model | P1 = widespread outage, P2 = major degradation, P3 = limited degradation, P4 = low urgency / workaround available |
| Primary Objective | Protect customers first, then capture evidence, then drive learning and prevention |
If customer impact is active, prefer the lowest-risk mitigation that is reversible and observable.
## 3. Prerequisites
### Access and tooling checklist
| Check | Required State | Evidence |
| --- | --- | --- |
| Incident channel | Slack bridge and ticket created or ready to create | Channel link posted in status updates |
| Pager access | Primary on-call can page secondary owners | PagerDuty access confirmed |
| Cloud access | Correct production role assumed | `aws sts get-caller-identity` succeeds |
| Status communications | Status page and customer comms templates available | Templates copied before publishing |
| Diagnostics access | Logs, metrics, traces, and dashboards accessible | Recent data visible in tooling |
### Environment variable checklist
| VAR NAME | Purpose | Example value |
| --- | --- | --- |
| PROJECT_NAME | Service identifier used in alerts and status communications | [PROJECT_NAME] |
| AWS_REGION | Primary production region | [AWS_REGION] |
| INCIDENT_ID | Tracking identifier for the live response | INC-2025-0412 |
| SEVERITY | Incident priority level | P1 |
| STATUS_PAGE_COMPONENT | Public-facing component name | [PROJECT_NAME] API |
| HEALTHCHECK_URL | Primary health endpoint | https://[PROJECT_NAME].example.com/health |
| LOG_GROUP | Main application log group | /aws/ecs/[PROJECT_NAME] |
| TRACE_SERVICE | Tracing service name or namespace | [PROJECT_NAME]-prod |
### Pre-checks
- Classify severity within the first five minutes of a confirmed incident.
- Open a shared timeline and record every material action with a timestamp.
- If customer impact is ongoing, favor mitigation over root-cause perfection.
## 4. Procedure Steps
### 1. Acknowledge the alert and classify severity
Purpose: Establish ownership and urgency before responders begin parallel work.
```bash
printf 'Incident %s acknowledged at %s
' "$INCIDENT_ID" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
printf 'Severity classification: %s
' "$SEVERITY"
aws sts get-caller-identity --output table
```
✓ **Verify**
- The incident has a named owner, a severity level, and a communication channel visible to responders.
⚠️ **If this fails**
- If severity is uncertain, classify at the higher level and downgrade later when evidence supports it.
### 2. Establish baseline health and scope of impact
Purpose: Understand which user journeys, regions, or dependencies are failing before making changes.
```bash
curl -fsS "$HEALTHCHECK_URL"
aws cloudwatch describe-alarms --region "$AWS_REGION" --output table
```
✓ **Verify**
- The impacted scope and known healthy paths are documented in the timeline from at least one reliable source of truth.
⚠️ **If this fails**
- If customer impact cannot be scoped quickly, broaden diagnostics immediately and escalate to the incident commander.
### 3. Collect primary diagnostics
Purpose: Gather the minimum evidence needed to choose a containment path.
```bash
aws logs tail "$LOG_GROUP" --since 15m
printf 'Open tracing view for service %s and inspect failing requests.
' "$TRACE_SERVICE"
```
✓ **Verify**
- The timeline contains logs, traces, or alarm evidence that points toward a probable fault domain.
⚠️ **If this fails**
- If diagnostics are unavailable, prioritize containment and note the observability outage as a parallel problem.
### 4. Apply the lowest-risk containment action
Purpose: Reduce customer impact quickly while preserving the ability to continue diagnosis.
```bash
printf 'Containment options: rollback deployment, disable feature flag, drain bad nodes, or reroute traffic.
'
printf 'Select one action and record it in the incident timeline before execution.
'
```
✓ **Verify**
- A specific containment action is chosen, owned, and measurably reduces active customer harm.
⚠️ **If this fails**
- If containment is unclear, choose the safest reversible action and escalate rather than improvising multiple changes.
### 5. Publish the initial communication update
Purpose: Keep stakeholders aligned and reduce duplicate diagnostic work.
```bash
cat <<'EOF'
Status page update: Investigating elevated errors for [PROJECT_NAME]. Engineers are actively mitigating impact. Next update in 15 minutes.
EOF
cat <<'EOF'
Slack update: [INCIDENT_ID] [SEVERITY] Investigating elevated errors for [PROJECT_NAME]. Current customer impact: <describe>. Next update in 15 minutes.
EOF
```
✓ **Verify**
- Stakeholders receive the first update with known impact, current action, and next update time.
⚠️ **If this fails**
- If the primary communications tooling is unavailable, use the backup process defined by the incident commander.
### 6. Drive diagnosis to a likely root cause
Purpose: Move from symptom collection to a specific fault domain that can be fixed or mitigated.
```bash
printf 'Compare current deployment, config, dependency status, and recent infrastructure changes.
'
aws cloudformation describe-stack-events --stack-name "[STACK_NAME]" --region "$AWS_REGION" --max-items 20
```
✓ **Verify**
- A likely root cause or fault domain is identified and conflicting hypotheses are explicitly tracked or eliminated.
⚠️ **If this fails**
- If the cause remains unknown after one full diagnostic cycle, request additional subject-matter experts.
### 7. Execute the corrective action
Purpose: Apply the smallest safe fix that resolves customer impact.
```bash
printf 'Examples: rollback the last release, rotate a bad secret, increase capacity, or fail over a dependency.
'
printf 'Record the exact corrective command in the live timeline before and after execution.
'
```
✓ **Verify**
- The corrective action is attributable, timestamped, and measurably improves the affected service.
⚠️ **If this fails**
- If the corrective action fails, revert it if safe and escalate to the incident commander for the next option.
### 8. Verify resolution and hand off follow-up work
Purpose: Ensure the fix solved the customer problem and leave a clear operational record.
```bash
curl -fsS "$HEALTHCHECK_URL"
aws cloudwatch describe-alarms --region "$AWS_REGION" --output table
cat <<'EOF'
Final update: Monitoring has completed and service has recovered for [PROJECT_NAME]. We will complete a follow-up review and share preventive actions.
EOF
```
✓ **Verify**
- Health checks pass, alarms clear or trend normal, and a post-incident review owner and due date exist before closure.
⚠️ **If this fails**
- If symptoms reappear during the observation window or follow-up ownership is unclear, keep the incident open and continue monitoring.
## 5. Troubleshooting Table
| Symptom | Probable Cause | Diagnostic Command | Resolution | Escalate If |
| --- | --- | --- | --- | --- |
| Alert fired but service looks healthy | False positive or stale alarm threshold | `aws cloudwatch describe-alarms --region "$AWS_REGION" --output table` | Validate alarm logic, suppress if approved, and create follow-up tuning work | Multiple false positives are masking a real issue |
| Logs show timeouts to dependency | Upstream degradation or network issue | `aws logs tail "$LOG_GROUP" --since 15m` | Route around the dependency, fail over, or engage the owning team | Dependency team is unresponsive and customer impact is rising |
| Customer impact is unclear | Monitoring gap or partial regional failure | `curl -fsS "$HEALTHCHECK_URL"` | Use synthetic checks, support tickets, and analytics to refine scope | No clear blast-radius estimate after first update |
| Containment action reduces some errors but not all | Multiple root causes or incomplete mitigation | `aws cloudwatch describe-alarms --region "$AWS_REGION" --output table` | Continue diagnostics and apply the next lowest-risk mitigation step | Customer impact remains severe after one mitigation cycle |
| Incident communications become inconsistent | No single source of truth or unclear incident roles | `printf "Review incident timeline ownership and last update timestamp.\n"` | Re-establish the incident commander and communications lead immediately | Stakeholders are acting on conflicting information |
## 6. Rollback Procedure
### 1. Select the fastest safe mitigation rollback
Purpose: Reverse the specific change that contributed to the incident when that is the safest path.
```bash
printf 'Mitigation rollback candidates: deployment rollback, feature flag disable, config revert, or traffic re-route.\n'
```
✓ **Verify**
- One rollback path is selected and does not conflict with the active containment action.
⚠️ **If this fails**
- Escalate if no safe rollback exists and an alternative mitigation path is required.
### 2. Execute the mitigation rollback
Purpose: Remove the faulty change while the incident bridge remains active.
```bash
printf 'Record the exact rollback command in the timeline before running it.\n'
```
✓ **Verify**
- The rollback action completes and the expected system version or config is restored.
⚠️ **If this fails**
- If rollback fails, continue full incident response and engage the owning team immediately.
### 3. Verify service recovery after rollback
Purpose: Confirm the rollback improved customer experience rather than just reverting state.
```bash
curl -fsS "$HEALTHCHECK_URL"
```
✓ **Verify**
- The primary symptom improves and health checks succeed without new high-severity alarms.
⚠️ **If this fails**
- Keep the incident active and continue diagnosis if customer symptoms remain.
### 4. Update communications with rollback outcome
Purpose: Ensure stakeholders understand the current system state after the rollback.
```bash
printf 'Publish rollback outcome and revised next update time.\n'
```
✓ **Verify**
- Stakeholders receive a clear update on rollback status and current service health.
⚠️ **If this fails**
- Use the backup notification path if the primary channel fails or communication becomes fragmented.
### 5. Record rollback learnings for future automation
Purpose: Capture the operational knowledge discovered during the incident.
```bash
printf 'Document which manual steps should become automated before the next incident.\n'
```
✓ **Verify**
- At least one automation or monitoring improvement is logged in the follow-up work.
⚠️ **If this fails**
- Keep follow-up open until a named owner accepts the preventive action items.
## 7. Quick Reference
```bash
aws sts get-caller-identity --output table
curl -fsS "$HEALTHCHECK_URL"
aws cloudwatch describe-alarms --region "$AWS_REGION" --output table
aws logs tail "$LOG_GROUP" --since 15m
printf "Publish next update time in every incident communication.\n"
```
- Classify severity within the first five minutes.
- Always publish the next update time in every stakeholder communication.
- Prefer mitigation over perfect diagnosis while customer impact is active.
## 8. Change Log
| Version | Date | Author | Change Summary |
| --- | --- | --- | --- |
| 1.3 | [DATE] | Site Reliability Engineering | Expanded communication templates and follow-up ownership guidance |
| 1.2 | 2025-01-22 | Site Reliability Engineering | Added explicit severity and observation-window checkpoints |
| 1.0 | 2024-02-12 | Site Reliability Engineering | Initial incident response runbook |
