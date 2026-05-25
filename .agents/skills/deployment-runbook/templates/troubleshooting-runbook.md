# [PROJECT_NAME] Troubleshooting Runbook
Use this runbook to diagnose production issues systematically using symptoms, metrics, logs, traces, and low-risk recovery actions before escalating.
## 1. Document Control
| Field | Value |
|---|---|
| Title | [PROJECT_NAME] Troubleshooting Runbook |
| Runbook ID | RNB-TSH-001 |
| Version | 1.2 |
| Status | Approved |
| Owner | Operations Engineering |
| Created | 2024-04-08 |
| Last Reviewed | [DATE] |
| Last Tested | [DATE] |
| Audience | On-call Engineer, Service Owner |
| Approved Change Window | 24x7 operational use |
## 2. Overview
| Item | Details |
|---|---|
| Component | [PROJECT_NAME] production service and supporting AWS resources |
| Purpose | Provide a symptom-driven, low-to-high-risk diagnostic path for production issues |
| Critical Dependencies | CloudWatch metrics, logs, tracing, ECS/Lambda runtime, database, network ingress |
| SLA/SLO Targets | Keep availability above 99.9%, error rate below 1%, and p95 latency below 400 ms |
| On-call Contact | Slack: #prod-oncall; PagerDuty: [PROJECT_NAME] Primary |
| Diagnostic Strategy | Start broad with service health, narrow to logs / traces, then apply the lowest-risk remediation |
| Escalation Rule | Escalate whenever diagnosis exceeds the observation window or a stateful change is required |
This guide assumes the operator records every command, observation, and decision in a ticket or incident timeline.
## 3. Prerequisites
### Access and tooling checklist
| Check | Required State | Evidence |
|---|---|---|
| Production access | Approved read or break-glass access is active | `aws sts get-caller-identity` succeeds |
| Observability access | Dashboards, logs, and traces are reachable | Recent data is visible |
| Incident context | Open ticket or incident ID exists for active customer issues | Identifier recorded |
| Known symptom | At least one observed symptom is written down | User report, alert, or metric spike available |
| Rollback path | If a recent change is involved, rollback target is known | Previous artifact or version identified |
### Environment variable checklist
| VAR NAME | Purpose | Example value |
|---|---|---|
| PROJECT_NAME | Service identifier used in logs and dashboards | [PROJECT_NAME] |
| AWS_REGION | Region to query | [AWS_REGION] |
| HEALTHCHECK_URL | External health probe | https://[PROJECT_NAME].example.com/health |
| LOG_GROUP | Primary CloudWatch log group | /aws/ecs/[PROJECT_NAME] |
| TRACE_SERVICE | Tracing namespace or service name | [PROJECT_NAME]-prod |
| METRIC_NAMESPACE | CloudWatch namespace for application metrics | [PROJECT_NAME]/Application |
| DB_INSTANCE_ID | Primary database instance | [PROJECT_NAME]-prod-db |
| ROLLBACK_TARGET | Known-good deployment target if change regression is confirmed | 2025.04.2 |
### Pre-checks
- Do not make stateful changes before evidence is gathered unless customer impact is severe and immediate.
- Record every diagnostic command and output location in the ticket or incident timeline.
- Use the escalation criteria in the troubleshooting table when uncertainty remains.
## 4. Procedure Steps
### 1. Capture the reported symptom and timeframe
Purpose: create a precise problem statement before querying systems.
```bash
printf 'Record symptom, affected users, first seen time, and last known good time.\n'
```
✓ **Verify**
- The symptom, timeframe, and affected scope are documented in one place.
- The problem statement is specific enough to test whether later actions improve it.
⚠️ **If this fails**
- If the symptom is unclear, gather a concrete example request, user report, or alarm before continuing.
- Escalate to support or the incident commander if customer scope cannot be established quickly.
### 2. Check external health and active alarms
Purpose: determine whether the issue is visible from outside the system and whether alerting has already scoped it.
```bash
curl -fsS "$HEALTHCHECK_URL"
aws cloudwatch describe-alarms --region "$AWS_REGION" --output table
```
✓ **Verify**
- You know whether the service is fully down, partially degraded, or externally healthy.
- Any active alarms are recorded with names and states.
⚠️ **If this fails**
- If the health endpoint fails, keep the issue in high-severity mode until proven otherwise.
- If alarm data is unavailable, continue with logs and traces but note the monitoring gap.
### 3. Query application logs for recent errors
Purpose: find the fastest evidence of exceptions, bad config, auth failures, or dependency timeouts.
```bash
aws logs tail "$LOG_GROUP" --since 15m
```
✓ **Verify**
- You either find a relevant error pattern or confirm that logs are quiet during the symptom window.
- Key error messages are copied into the ticket with timestamps.
⚠️ **If this fails**
- If logs are missing or delayed, escalate the observability issue and continue with metrics and traces.
- Do not assume “no logs” means “no problem”.
### 4. Inspect service-level metrics and traces
Purpose: measure whether the failure is driven by latency, errors, traffic changes, or saturation.
```bash
printf 'Review latency, traffic, errors, and saturation for namespace %s.\n' "$METRIC_NAMESPACE"
printf 'Open tracing for service %s and inspect the slowest or failing spans.\n' "$TRACE_SERVICE"
```
✓ **Verify**
- At least one signal points toward a narrowed fault domain such as app code, database, network, or dependency.
- The ticket links to the relevant dashboard or trace evidence.
⚠️ **If this fails**
- If metrics and traces disagree, record both and continue comparing with deployment history rather than guessing.
- Escalate if core telemetry is missing during a customer-facing issue.
### 5. Check recent changes and deployment history
Purpose: quickly determine whether the issue correlates with a new release, config change, or infrastructure update.
```bash
printf 'Review the most recent deployment, config, secret, and infrastructure changes for %s.\n' "$PROJECT_NAME"
```
✓ **Verify**
- You know whether a recent change is a plausible trigger for the symptom.
- If a regression is suspected, a rollback target is identified.
⚠️ **If this fails**
- If change history is unclear, involve the release owner before taking risky recovery steps.
- Do not roll back blindly if the symptom predates the most recent change.
### 6. Diagnose infrastructure and dependency health
Purpose: determine whether the issue is caused by compute, storage, network, or a downstream dependency.
```bash
aws rds describe-db-instances --db-instance-identifier "$DB_INSTANCE_ID" --region "$AWS_REGION" --query 'DBInstances[0].DBInstanceStatus' --output text
printf 'Check dependency dashboards, quota status, and recent platform incidents.\n'
```
✓ **Verify**
- You can state whether the fault is application-local or dependency-driven.
- Any unhealthy dependency is recorded with owner and current status.
⚠️ **If this fails**
- If dependency ownership is external, escalate using the documented support path immediately.
- If infrastructure diagnostics require write access or risky actions, pause and get approval before continuing.
### 7. Apply the lowest-risk corrective action
Purpose: restore service with the smallest safe change supported by evidence.
```bash
printf 'Examples: restart unhealthy tasks, scale out, roll back the latest release, or rotate a bad secret.\n'
```
✓ **Verify**
- The corrective action is recorded and produces measurable improvement in the reported symptom.
- The action does not create new alarms or widen the blast radius.
⚠️ **If this fails**
- If the action fails, revert it if possible and escalate rather than stacking multiple risky changes.
- Use the rollback runbook when a recent deployment regression is strongly indicated.
### 8. Verify resolution and decide on escalation
Purpose: close the diagnostic loop by proving recovery or formally escalating with evidence.
```bash
curl -fsS "$HEALTHCHECK_URL"
aws cloudwatch describe-alarms --region "$AWS_REGION" --output table
```
✓ **Verify**
- Health checks and relevant alarms show recovery or clear improvement.
- If unresolved, the escalation package includes symptom, evidence, attempted actions, and a recommended next step.
⚠️ **If this fails**
- Escalate immediately if the issue remains unresolved after one full diagnostic cycle or if customer impact is worsening.
- Keep the incident active until a human owner accepts the next action.
## 5. Troubleshooting Table
| Symptom | Probable Cause | Diagnostic Command | Resolution | Escalate If |
|---|---|---|---|---|
| Health endpoint fails but logs are quiet | Ingress, load balancer, DNS, or container startup problem | `curl -fsS "$HEALTHCHECK_URL"` | Check load balancer target health, task status, and recent restarts | The service remains externally unavailable for more than one verify interval |
| High latency without obvious errors | Saturation, dependency slowness, or DB contention | `printf 'Review p95/p99 latency, CPU, memory, and DB load.\n'` | Scale capacity, examine slow traces, and check database performance | Latency breaches the SLO long enough to burn error budget |
| Spiking 5xx after deployment | Application regression or config drift | `aws logs tail "$LOG_GROUP" --since 15m` | Compare release history and execute rollback if regression is confirmed | Rollback target is unknown or rollback also fails |
| Authentication or secret errors in logs | Expired secret, IAM drift, or bad config | `printf 'Verify secret version, IAM role, and environment variables.\n'` | Restore the previous secret or config state and restart affected workloads | Multiple services or teams are impacted |
| Database healthy but writes are failing | Schema mismatch or transaction contention | `aws rds describe-db-instances --db-instance-identifier "$DB_INSTANCE_ID" --region "$AWS_REGION"` | Check migrations, lock contention, and app compatibility before changing state | Data integrity risk or restore decision is required |
## 6. Rollback Procedure
### 1. Identify the last known-good state
Purpose: prepare a safe recovery path if troubleshooting confirms a recent change regression.
```bash
printf 'Confirm rollback target %s and the change it will reverse.\n' "$ROLLBACK_TARGET"
```
✓ **Verify**
- The rollback target is documented and linked to the suspected regression.
- The change owner agrees that rollback is the lowest-risk recovery path.
⚠️ **If this fails**
- Escalate if the last known-good state cannot be identified confidently.
- Do not perform a blind rollback on incomplete change history.
### 2. Capture evidence before reversal
Purpose: preserve the failing state for later root-cause analysis.
```bash
aws logs tail "$LOG_GROUP" --since 15m
```
✓ **Verify**
- The error evidence is saved in the incident or ticket before rollback.
- The failing symptom and timestamp are captured clearly enough for postmortem analysis.
⚠️ **If this fails**
- If evidence capture is blocked, proceed only when customer impact justifies immediate rollback.
- Note the missing evidence gap in the incident timeline.
### 3. Execute the rollback path
Purpose: restore the prior healthy version or configuration.
```bash
printf 'Run the approved rollback command from the rollback runbook.\n'
```
✓ **Verify**
- The previous version or config becomes active without new critical errors.
- The rollback command and timestamp are captured in the ticket.
⚠️ **If this fails**
- Escalate to the service owner and incident commander if rollback fails.
- Do not keep repeating the same failed recovery action without new evidence.
### 4. Verify service health after rollback
Purpose: confirm the recovery solved the user-visible symptom.
```bash
curl -fsS "$HEALTHCHECK_URL"
```
✓ **Verify**
- Health checks succeed and the original symptom improves.
- Metrics and alarms move back toward baseline.
⚠️ **If this fails**
- Keep the incident active and continue diagnosis if symptoms remain.
- Escalate to dependency owners if rollback reveals a broader platform issue.
### 5. Record the diagnostic conclusion
Purpose: preserve the learned signal for future responders and automation.
```bash
printf 'Document the symptom, evidence, root-cause hypothesis, and final recovery path.\n'
```
✓ **Verify**
- The ticket contains the final troubleshooting conclusion and next-step owner.
- At least one preventive action is recorded for runbook, monitoring, or automation improvement.
⚠️ **If this fails**
- Leave the issue open until the documentation and owner assignment are complete.
- Escalate to engineering management if no owner accepts the follow-up work.
## 7. Quick Reference
```bash
curl -fsS "$HEALTHCHECK_URL"
aws cloudwatch describe-alarms --region "$AWS_REGION" --output table
aws logs tail "$LOG_GROUP" --since 15m
aws rds describe-db-instances --db-instance-identifier "$DB_INSTANCE_ID" --region "$AWS_REGION" --query 'DBInstances[0].DBInstanceStatus' --output text
printf 'Review recent deployments and rollback target %s\n' "$ROLLBACK_TARGET"
```
- Start with service health, then logs, then metrics / traces, then dependencies.
- Do not perform stateful remediation without evidence or approval.
- Escalate early when diagnosis exceeds the documented observation window.
## 8. Change Log
| Version | Date | Author | Change Summary |
|---|---|---|---|
| 1.2 | [DATE] | Operations Engineering | Expanded dependency diagnostics and escalation criteria |
| 1.1 | 2025-02-18 | Operations Engineering | Added metric and trace analysis guidance |
| 1.0 | 2024-04-08 | Operations Engineering | Initial troubleshooting runbook |
