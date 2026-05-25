# [PROJECT_NAME] Rollback Runbook
Use this runbook when a production release must be reversed quickly and safely after a failed deployment, regression, or customer-impacting incident.
## 1. Document Control
| Field | Value |
|---|---|
| Title | [PROJECT_NAME] Rollback Runbook |
| Runbook ID | RNB-RBK-001 |
| Version | 1.2 |
| Status | Approved |
| Owner | Platform Engineering |
| Created | 2024-03-04 |
| Last Reviewed | [DATE] |
| Last Tested | [DATE] |
| Audience | On-call SRE, Incident Commander |
| Approved Change Window | Any time rollback criteria are met |
## 2. Overview
| Item | Details |
|---|---|
| Component | [PROJECT_NAME] production web and API stack |
| Purpose | Restore the last known-good version while preserving evidence and protecting data integrity |
| Critical Dependencies | CloudFormation stack history, ECS service history, database backups, status page tooling |
| SLA/SLO Targets | Restore service to baseline availability within 15 minutes and keep error rate below 1% |
| On-call Contact | PagerDuty: Service Operations Primary; Slack: #incident-bridge |
| Rollback Triggers | 5xx > 2% for 5 minutes, p99 latency > 800 ms, failed health checks, or failed smoke tests |
| Primary Evidence Sources | CloudWatch alarms, ECS service events, application logs, deployment change record |
Rollback is a production change. Treat it with the same precision as the original deployment and do not improvise if evidence is incomplete.
## 3. Prerequisites
### Access and tooling checklist
| Check | Required State | Evidence |
|---|---|---|
| Incident ownership | Incident commander or change owner identified | Owner acknowledged in Slack or PagerDuty |
| Rollback target | Last known-good release, image digest, or task definition known | Target recorded before action |
| Database readiness | Backup or restore point confirmed for any schema-changing release | Backup job status available |
| Communications | Status page and stakeholder channels ready | Templates copied before publishing |
| Production access | Correct AWS role is active | `aws sts get-caller-identity` output reviewed |
### Environment variable checklist
| VAR NAME | Purpose | Example value |
|---|---|---|
| PROJECT_NAME | Service name used in dashboards and AWS resources | [PROJECT_NAME] |
| STACK_NAME | Production infrastructure stack name | [STACK_NAME] |
| AWS_REGION | Region hosting the live service | [AWS_REGION] |
| ROLLBACK_TARGET | Known-good release identifier | 2025.04.2 |
| ECS_CLUSTER | Cluster hosting the live tasks | [PROJECT_NAME]-prod-cluster |
| ECS_SERVICE | Service being restored | [PROJECT_NAME]-web |
| DB_INSTANCE_ID | Primary database instance identifier | [PROJECT_NAME]-prod-db |
| HEALTHCHECK_URL | External health endpoint | https://[PROJECT_NAME].example.com/health |
### Pre-checks
- Confirm rollback criteria have been met and documented.
- Pause automated deploy pipelines so they do not reintroduce the bad version.
- Notify stakeholders that rollback is starting and customer impact is being evaluated.
## 4. Procedure Steps
### 1. Classify the rollback and freeze additional changes
Purpose: ensure all responders agree that the system is in rollback mode and no further production drift is introduced.
```bash
printf 'Rollback mode enabled for %s at %s\n' "$PROJECT_NAME" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
aws sts get-caller-identity --output table
printf 'Rollback target: %s\n' "$ROLLBACK_TARGET"
```
✓ **Verify**
- The rollback target is written in the incident log and all operators are aligned on the version being restored.
- No active deployment job continues to push the failed release.
⚠️ **If this fails**
- If multiple rollback targets are being discussed, stop and get the incident commander to choose one authoritative target.
- If automation cannot be paused, disable the pipeline or revoke deploy permissions until rollback is complete.
### 2. Capture current state and preserve evidence
Purpose: preserve logs, metrics, and deployment metadata before the environment changes again.
```bash
aws cloudformation describe-stack-events --stack-name "$STACK_NAME" --region "$AWS_REGION" --max-items 25
aws ecs describe-services --cluster "$ECS_CLUSTER" --services "$ECS_SERVICE" --region "$AWS_REGION" --output json
aws logs tail "/aws/ecs/${PROJECT_NAME}" --since 30m
```
✓ **Verify**
- Recent stack events, ECS events, and logs are saved in the incident ticket or timeline.
- You can identify the failed release, timestamp, and first observable symptom after this step.
⚠️ **If this fails**
- If evidence capture is blocked and customer impact is ongoing, prioritize rollback but record the missing evidence gap.
- Escalate to the incident commander if observability systems are unavailable.
### 3. Verify backup or state restore readiness
Purpose: confirm that any data-affecting change can be reversed safely before the application version is moved.
```bash
aws rds describe-db-instances --db-instance-identifier "$DB_INSTANCE_ID" --region "$AWS_REGION" --query 'DBInstances[0].DBInstanceStatus' --output text
printf 'Confirm restore point or backup for rollback target %s\n' "$ROLLBACK_TARGET"
```
✓ **Verify**
- The database is available and a recent backup or restore point is confirmed for the affected release window.
- Any irreversible schema or data migration risk is explicitly reviewed before proceeding.
⚠️ **If this fails**
- If no safe restore option exists for a schema-changing release, escalate to the database owner before touching production.
- Do not assume rollback is application-only when migrations are involved.
### 4. Restore the last known-good application version
Purpose: replace the failed production version with the previously healthy release artifact.
```bash
aws ecs update-service \
  --cluster "$ECS_CLUSTER" \
  --service "$ECS_SERVICE" \
  --task-definition "$ROLLBACK_TARGET" \
  --region "$AWS_REGION"
aws ecs wait services-stable --cluster "$ECS_CLUSTER" --services "$ECS_SERVICE" --region "$AWS_REGION"
```
✓ **Verify**
- The service returns to a stable state and the active deployment references `$ROLLBACK_TARGET`.
- No additional failed tasks or restart storms appear during stabilization.
⚠️ **If this fails**
- If rollback launch fails, escalate immediately to the platform owner and prepare a broader incident response.
- If the rollback target itself is unhealthy, select the previous healthy version rather than retrying the same bad target.
### 5. Run smoke tests and validate customer journeys
Purpose: confirm that the rollback actually restored service function, not just scheduler status.
```bash
curl -fsS "$HEALTHCHECK_URL"
curl -fsS "${HEALTHCHECK_URL%/health}/ready"
printf 'Execute one high-value business transaction test for %s\n' "$PROJECT_NAME"
```
✓ **Verify**
- Health and readiness endpoints succeed and the priority customer journey passes.
- Error rate, latency, and saturation begin trending back toward baseline.
⚠️ **If this fails**
- If smoke tests still fail, keep the incident open and escalate to the application and database owners immediately.
- Do not declare rollback successful until customer-observable behaviour is healthy.
### 6. Communicate recovery status and schedule follow-up work
Purpose: close the loop with stakeholders and ensure the failed release cannot quietly recur.
```bash
printf 'Rollback complete for %s using target %s\n' "$PROJECT_NAME" "$ROLLBACK_TARGET"
printf 'Create follow-up items: root cause analysis, automation backlog, and runbook updates.\n'
```
✓ **Verify**
- Status page, chat channels, and stakeholders are updated with the recovery state and next steps.
- A defect, RCA, or postmortem task exists for the failed deployment.
⚠️ **If this fails**
- If communications tooling is unavailable, use the backup process defined by the incident commander.
- If recovery is partial, keep monitoring and do not close the incident.
## 5. Troubleshooting Table
| Symptom | Probable Cause | Diagnostic Command | Resolution | Escalate If |
|---|---|---|---|---|
| Rollback target does not exist | Artifact retention gap or wrong identifier | `aws ecs list-task-definitions --family-prefix "$PROJECT_NAME" --sort DESC` | Select the most recent known-good revision from service history and registry metadata | No known-good target can be proven safe |
| Database schema mismatch after rollback | Forward migration was not backward compatible | `aws rds describe-db-instances --db-instance-identifier "$DB_INSTANCE_ID" --region "$AWS_REGION"` | Engage the database owner and execute the documented restore or reverse migration plan | Data writes are failing or corruption is suspected |
| Service stabilizes but smoke tests still fail | Downstream dependency, bad secret, or partial rollback | `aws logs tail "/aws/ecs/${PROJECT_NAME}" --since 15m` | Review logs, verify secrets/config, and continue incident response until user journeys pass | Customer-facing impact persists for more than one verify interval |
| Rollback blocked by IAM access error | Operator using wrong role or expired session | `aws sts get-caller-identity --output table` | Re-authenticate with the approved role and retry the command | Multiple approved operators also fail |
| Rollback causes new alarm storm | Previous version depends on drifted infra or config | `aws cloudwatch describe-alarms --region "$AWS_REGION" --output table` | Review config drift and restore the matching infrastructure or secrets state | Sustained customer impact continues after rollback |
## 6. Rollback Procedure
### 1. Re-verify rollback target after initial recovery
Purpose: double-check that the environment is still pinned to the restored version.
```bash
aws ecs describe-services --cluster "$ECS_CLUSTER" --services "$ECS_SERVICE" --region "$AWS_REGION" --query 'services[0].taskDefinition' --output text
```
✓ **Verify**
- The command returns the same target documented in the incident record.
- No drift or new rollout appears during the recovery window.
⚠️ **If this fails**
- If the service drifted again, re-freeze the pipeline and repeat the restore step.
- Escalate if an automated process is reintroducing the failed version.
### 2. Verify alarms remain healthy during the observation window
Purpose: ensure recovery is sustained long enough to close the rollback event.
```bash
aws cloudwatch describe-alarms --alarm-names "${PROJECT_NAME}-High5xx" "${PROJECT_NAME}-HighLatency" --region "$AWS_REGION" --output table
```
✓ **Verify**
- All alarms are `OK` or trending back to normal inside the defined observation window.
- No fresh customer-impacting alerts are triggered by the restored version.
⚠️ **If this fails**
- Keep the incident active and continue investigation if alarms re-fire during observation.
- Escalate to the service owner if a dependency outside the application is now driving the incident.
### 3. Capture final post-rollback evidence
Purpose: preserve the final healthy state for postmortem analysis and future automation.
```bash
aws logs tail "/aws/ecs/${PROJECT_NAME}" --since 10m
```
✓ **Verify**
- Logs show healthy startup and no new critical errors after rollback.
- The incident record contains final evidence of the recovered state.
⚠️ **If this fails**
- Escalate if errors continue despite apparent health-check recovery.
- Keep the rollback event open until evidence matches the healthy state.
### 4. Hand off to follow-up owners
Purpose: assign ownership for corrective and preventive action.
```bash
printf 'Assign RCA owner and remediation due date before closing the change.\n'
```
✓ **Verify**
- An owner and due date are recorded for the failed release follow-up.
- The runbook, automation, or monitoring backlog contains at least one preventive task.
⚠️ **If this fails**
- Keep the operational ticket open until a named owner accepts the action items.
- Escalate to engineering management if no owner is available for follow-up work.
### 5. Close rollback event when stable
Purpose: formally close the operational event only after recovery is sustained.
```bash
printf 'Close rollback event after agreed observation window completes with stable metrics.\n'
```
✓ **Verify**
- The observation window completes with healthy metrics and stakeholder acknowledgement.
- The incident or change record has a clear final state and next-step summary.
⚠️ **If this fails**
- Extend monitoring or reopen the incident if any regression appears.
- Do not close the event if customer impact is still uncertain.
## 7. Quick Reference
```bash
aws ecs describe-services --cluster "$ECS_CLUSTER" --services "$ECS_SERVICE" --region "$AWS_REGION" --query 'services[0].taskDefinition' --output text
aws cloudformation describe-stack-events --stack-name "$STACK_NAME" --region "$AWS_REGION" --max-items 25
aws ecs update-service --cluster "$ECS_CLUSTER" --service "$ECS_SERVICE" --task-definition "$ROLLBACK_TARGET" --region "$AWS_REGION"
aws ecs wait services-stable --cluster "$ECS_CLUSTER" --services "$ECS_SERVICE" --region "$AWS_REGION"
curl -fsS "$HEALTHCHECK_URL"
```
- Use the rollback target recorded before the first recovery action.
- Always preserve evidence before destroying the failed state when customer impact allows.
- Keep the incident open until customer-facing behaviour is healthy again.
## 8. Change Log
| Version | Date | Author | Change Summary |
|---|---|---|---|
| 1.2 | [DATE] | Platform Engineering | Expanded backup readiness and communications guidance |
| 1.1 | 2025-02-14 | Platform Engineering | Added explicit smoke-test verification after rollback |
| 1.0 | 2024-03-04 | Platform Engineering | Initial rollback-only runbook |
