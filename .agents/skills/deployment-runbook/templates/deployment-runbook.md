# [PROJECT_NAME] Production Deployment Runbook
Use this runbook to deploy the [PROJECT_NAME] web application into production with explicit verification and rollback gates after every change.
## 1. Document Control
| Field | Value |
| --- | --- |
| Title | [PROJECT_NAME] Production Deployment Runbook |
| Runbook ID | RNB-WEB-001 |
| Version | 1.4 |
| Status | Approved |
| Owner | Platform Engineering |
| Created | 2024-01-15 |
| Last Reviewed | [DATE] |
| Last Tested | [DATE] |
| Audience | On-call SRE, Release Engineer |
## 2. Overview
| Item | Details |
| --- | --- |
| Component | [PROJECT_NAME] public web application on ECS Fargate behind an Application Load Balancer |
| Purpose | Deploy a new release without breaching customer-facing availability or latency objectives |
| Critical Dependencies | Amazon ECR, Amazon ECS, AWS CloudFormation, Amazon RDS, AWS Secrets Manager, Route 53 |
| SLA/SLO Targets | 99.9% monthly availability, p95 latency < 400 ms, error rate < 1% |
| On-call Contact | PagerDuty: Web Platform Primary; Slack: #prod-oncall |
| Deployment Strategy | Rolling ECS deployment with CloudFormation-managed infrastructure and manual promotion gates |
## 3. Prerequisites
### Access and tooling checklist
| Check | Required State | Evidence |
| --- | --- | --- |
| Production AWS access | Approved production IAM role assumed | `aws sts get-caller-identity` shows prod account |
| Git access | Read access to the release tag and deployment repository | Tag checkout succeeds locally |
| Docker tooling | Docker CLI installed and usable for image builds | `docker version` succeeds |
| Change approval | Approved deployment window and change ticket present | Change record linked in release notes |
### Environment variable checklist
| VAR NAME | Purpose | Example value |
| --- | --- | --- |
| PROJECT_NAME | Application identifier used across AWS resources | [PROJECT_NAME] |
| STACK_NAME | CloudFormation stack name for the production service | [STACK_NAME] |
| AWS_REGION | Deployment region for all AWS CLI commands | [AWS_REGION] |
| RELEASE_TAG | Approved Git tag or immutable release label | 2025.04.3 |
| AWS_ACCOUNT_ID | Target AWS account that owns the ECR repository | 123456789012 |
| ECS_CLUSTER | Production ECS cluster name | [PROJECT_NAME]-prod-cluster |
| ECS_SERVICE | Production ECS service name | [PROJECT_NAME]-web |
| ECR_REPOSITORY | Repository that stores the web image | [PROJECT_NAME]-web |
| HEALTHCHECK_URL | External health endpoint used for smoke tests | https://[PROJECT_NAME].example.com/health |
| PREVIOUS_TASK_DEFINITION | Last known-good task definition for rollback | [PROJECT_NAME]-web:142 |
### Pre-checks
- Confirm there is no overlapping database maintenance or freeze window.
- Ensure the previous task definition or image digest is known before starting the deployment.
## 4. Procedure Steps
### 1. Verify operator context and export deployment variables
Purpose: Confirm the engineer is authenticated to the correct production account and working with the approved release metadata.
```bash
export PROJECT_NAME="[PROJECT_NAME]"
export STACK_NAME="[STACK_NAME]"
export AWS_REGION="[AWS_REGION]"
export RELEASE_TAG="2025.04.3"
export AWS_ACCOUNT_ID="123456789012"
export ECS_CLUSTER="${PROJECT_NAME}-prod-cluster"
export ECS_SERVICE="${PROJECT_NAME}-web"
export ECR_REPOSITORY="${PROJECT_NAME}-web"
export HEALTHCHECK_URL="https://${PROJECT_NAME}.example.com/health"
export PREVIOUS_TASK_DEFINITION="${PROJECT_NAME}-web:142"
aws sts get-caller-identity --output table
aws configure get region
printf 'Deploying %s to %s in %s
' "$RELEASE_TAG" "$STACK_NAME" "$AWS_REGION"
```
✓ **Verify**
- The AWS account, region, release tag, and rollback target are correct and recorded in the change ticket.
⚠️ **If this fails**
- Stop immediately if the AWS account, role, region, or release tag is wrong; re-authenticate and restart from step 1.
### 2. Confirm deployment window and baseline service health
Purpose: Ensure the rollout starts from a known-good state and that no live incident is already active.
```bash
printf 'Starting deployment window for %s at %s
' "$PROJECT_NAME" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
curl -fsS "$HEALTHCHECK_URL"
aws cloudwatch describe-alarms   --alarm-names "${PROJECT_NAME}-High5xx" "${PROJECT_NAME}-HighLatency" "${PROJECT_NAME}-TargetResponseTime"   --region "$AWS_REGION"   --query 'MetricAlarms[].{Alarm:AlarmName,State:StateValue}'   --output table
```
✓ **Verify**
- The health endpoint returns 200 and the listed alarms are `OK` or explicitly approved for the change window.
⚠️ **If this fails**
- Pause the deployment if health checks fail or alarms are already firing; investigate the live issue before introducing new change.
### 3. Check out the approved release and run pre-deployment validation
Purpose: Create a deterministic workspace and prove the application and infrastructure definitions meet the quality gate before packaging.
```bash
git fetch origin --tags
git checkout "$RELEASE_TAG"
git status --short
npm ci
<!-- PRECHECK_COMMAND_START -->
aws cloudformation validate-template   --template-body file://infra/app.yaml   --region "$AWS_REGION"
npm run lint
npm test
<!-- PRECHECK_COMMAND_END -->
```
✓ **Verify**
- The workspace is clean and every validation command exits 0 with no unresolved test, lint, or template errors.
⚠️ **If this fails**
- Do not continue if checkout, dependency install, or validation fails; fix the release outside production and restart from step 1.
### 4. Build and publish the release artifact
Purpose: Produce the immutable image or package that production will deploy.
```bash
<!-- BUILD_COMMAND_START -->
docker build --platform linux/amd64 -t "$PROJECT_NAME:$RELEASE_TAG" .
<!-- BUILD_COMMAND_END -->
<!-- ARTIFACT_COMMAND_START -->
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
docker tag "$PROJECT_NAME:$RELEASE_TAG" "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}:$RELEASE_TAG"
docker push "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}:$RELEASE_TAG"
<!-- ARTIFACT_COMMAND_END -->
```
✓ **Verify**
- The build completes successfully and the artifact registry returns the expected immutable tag or digest for the release.
⚠️ **If this fails**
- If the build or push fails, fix the artifact pipeline first; never deploy an unverified or stale image tag.
### 5. Create and review the infrastructure change set
Purpose: Inspect the exact diff before live execution.
```bash
<!-- CHANGE_SET_COMMAND_START -->
aws cloudformation deploy   --template-file infra/app.yaml   --stack-name "$STACK_NAME"   --capabilities CAPABILITY_NAMED_IAM   --parameter-overrides ImageTag="$RELEASE_TAG"   --region "$AWS_REGION"   --no-execute-changeset
aws cloudformation describe-change-set   --change-set-name "${STACK_NAME}-changeset"   --stack-name "$STACK_NAME"   --region "$AWS_REGION"   --output table
<!-- CHANGE_SET_COMMAND_END -->
```
✓ **Verify**
- The change set contains only approved changes and no unexpected replacement of stateful resources.
⚠️ **If this fails**
- If the change set contains unapproved or destructive operations, stop and review with the platform owner before proceeding.
### 6. Execute the production deployment
Purpose: Apply the approved infrastructure and service update using the verified artifact.
```bash
<!-- DEPLOY_COMMAND_START -->
aws cloudformation deploy   --template-file infra/app.yaml   --stack-name "$STACK_NAME"   --capabilities CAPABILITY_NAMED_IAM   --parameter-overrides ImageTag="$RELEASE_TAG"   --region "$AWS_REGION"
<!-- DEPLOY_COMMAND_END -->
```
✓ **Verify**
- The deploy command exits 0 and the stack moves toward `UPDATE_COMPLETE` without entering a rollback state.
⚠️ **If this fails**
- If the stack enters `UPDATE_ROLLBACK_*` or a stateful replacement begins unexpectedly, stop and move to the rollback section.
### 7. Monitor the rollout and run smoke tests
Purpose: Confirm the new version is stable before the change is declared complete.
```bash
<!-- MONITOR_COMMAND_START -->
aws ecs wait services-stable --cluster "$ECS_CLUSTER" --services "$ECS_SERVICE" --region "$AWS_REGION"
aws ecs describe-services   --cluster "$ECS_CLUSTER"   --services "$ECS_SERVICE"   --region "$AWS_REGION"   --query 'services[0].deployments[].{Status:status,TaskDefinition:taskDefinition,Running:runningCount,Desired:desiredCount}'   --output table
<!-- MONITOR_COMMAND_END -->
<!-- SMOKE_TEST_COMMAND_START -->
curl -fsS "$HEALTHCHECK_URL"
curl -fsS "${HEALTHCHECK_URL%/health}/ready"
<!-- SMOKE_TEST_COMMAND_END -->
```
✓ **Verify**
- The scheduler reports the service as stable, smoke tests pass, and latency and error rate stay inside the documented SLA/SLO envelope.
⚠️ **If this fails**
- If the service does not stabilize or smoke tests fail, begin rollback immediately and notify the application owner.
### 8. Close the deployment and record the observation window
Purpose: Finish the change cleanly and leave a traceable operational record.
```bash
printf 'Deployment complete for %s release %s at %s
' "$PROJECT_NAME" "$RELEASE_TAG" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
printf 'Record release tag, task definition, start time, end time, and dashboard links in the change record.
'
```
✓ **Verify**
- The change record contains final timestamps, deployed artifact identifiers, and links to the dashboards used for verification.
⚠️ **If this fails**
- Do not close the change if the observation window has not completed or customer-facing metrics are still unstable.
## 5. Troubleshooting Table
| Symptom | Probable Cause | Diagnostic Command | Resolution | Escalate If |
| --- | --- | --- | --- | --- |
| CloudFormation stack enters `UPDATE_ROLLBACK_FAILED` | Nested resource failure or blocked rollback | `aws cloudformation describe-stack-events --stack-name "$STACK_NAME" --region "$AWS_REGION" --max-items 20` | Identify the failing logical resource, remediate it, and continue rollback only after review | A stateful resource is stuck or replacement would cause data loss |
| ECS service never reaches steady state | Task definition error, failing health check, or insufficient capacity | `aws ecs describe-services --cluster "$ECS_CLUSTER" --services "$ECS_SERVICE" --region "$AWS_REGION" --output json` | Review service events, fix the task definition or health check, then retry or roll back | The service remains unstable for more than 15 minutes |
| Image push fails with access denied | ECR permissions or wrong account / region context | `aws ecr describe-repositories --repository-names "$ECR_REPOSITORY" --region "$AWS_REGION"` | Re-authenticate, confirm repository existence, and retry the login / push flow | Multiple engineers cannot push to the same repository |
| Smoke test returns 5xx after deployment | Application boot failure, bad config, or downstream dependency issue | `aws logs tail "/aws/ecs/${PROJECT_NAME}" --since 10m --follow` | Inspect logs, compare config, and roll back if the issue is user-impacting | Customer traffic is failing or error-budget burn accelerates |
| Database migration blocks startup | Schema change incompatible with new or old application version | `aws rds describe-db-instances --db-instance-identifier "${PROJECT_NAME}-prod" --region "$AWS_REGION"` | Pause rollout, validate migration status, and execute the documented database recovery plan | Writes are failing or rollback requires restore-from-backup |
## 6. Rollback Procedure
### 1. Freeze further changes and select the rollback target
Purpose: Prevent additional drift while restoring the last known-good version.
```bash
printf 'Rollback initiated for %s at %s
' "$PROJECT_NAME" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
aws ecs describe-services --cluster "$ECS_CLUSTER" --services "$ECS_SERVICE" --region "$AWS_REGION" --query 'services[0].taskDefinition' --output text
printf 'Using rollback target %s
' "$PREVIOUS_TASK_DEFINITION"
```
✓ **Verify**
- The current task definition and intended rollback target are both identified and recorded in the incident or change log.
⚠️ **If this fails**
- If you cannot determine the last known-good version, stop and escalate to the application owner before changing production again.
### 2. Capture current state and recent events
Purpose: Preserve diagnostic evidence before the bad deployment is replaced.
```bash
aws ecs describe-services --cluster "$ECS_CLUSTER" --services "$ECS_SERVICE" --region "$AWS_REGION" --output json
aws cloudformation describe-stack-events --stack-name "$STACK_NAME" --region "$AWS_REGION" --max-items 20
aws logs tail "/aws/ecs/${PROJECT_NAME}" --since 15m
```
✓ **Verify**
- Recent stack events, service events, and logs are captured in the incident record or ticket before the environment changes again.
⚠️ **If this fails**
- If evidence capture is blocked, continue with rollback only when customer impact is ongoing and record the missing-evidence gap in the incident timeline.
### 3. Redeploy the last known-good task definition
Purpose: Restore service capacity using the previously healthy application version.
```bash
<!-- ROLLBACK_COMMAND_START -->
aws ecs update-service   --cluster "$ECS_CLUSTER"   --service "$ECS_SERVICE"   --task-definition "$PREVIOUS_TASK_DEFINITION"   --region "$AWS_REGION"
<!-- ROLLBACK_COMMAND_END -->
```
✓ **Verify**
- The update-service call succeeds and ECS starts replacing tasks with the previous task definition.
⚠️ **If this fails**
- If rollback launch fails, escalate immediately to the platform owner and prepare the broader incident response path.
### 4. Verify recovery and data integrity
Purpose: Confirm the rollback restored customer-facing functionality without introducing data inconsistencies.
```bash
aws ecs wait services-stable --cluster "$ECS_CLUSTER" --services "$ECS_SERVICE" --region "$AWS_REGION"
curl -fsS "$HEALTHCHECK_URL"
curl -fsS "${HEALTHCHECK_URL%/health}/ready"
```
✓ **Verify**
- The service becomes stable, health checks pass, and latency and error rate return to an acceptable baseline.
⚠️ **If this fails**
- If rollback does not restore service health, escalate to a P1 incident and involve database and platform owners immediately.
### 5. Communicate rollback completion and open follow-up work
Purpose: Close the loop, document impact, and ensure the failure becomes engineering learning.
```bash
printf 'Rollback complete for %s using %s
' "$PROJECT_NAME" "$PREVIOUS_TASK_DEFINITION"
printf 'Post-incident actions: capture root cause, update runbook, and schedule re-test.
'
```
✓ **Verify**
- Stakeholders are notified that rollback is complete and a defect, incident, or postmortem item is opened with the captured evidence.
⚠️ **If this fails**
- Keep the incident open and continue monitoring if communication channels are degraded or service health is still uncertain.
## 7. Quick Reference
```bash
aws sts get-caller-identity --output table
aws cloudformation validate-template --template-body file://infra/app.yaml --region "$AWS_REGION"
docker build --platform linux/amd64 -t "$PROJECT_NAME:$RELEASE_TAG" .
docker push "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}:$RELEASE_TAG"
aws cloudformation deploy --template-file infra/app.yaml --stack-name "$STACK_NAME" --capabilities CAPABILITY_NAMED_IAM --parameter-overrides ImageTag="$RELEASE_TAG" --region "$AWS_REGION"
aws ecs wait services-stable --cluster "$ECS_CLUSTER" --services "$ECS_SERVICE" --region "$AWS_REGION"
aws ecs update-service --cluster "$ECS_CLUSTER" --service "$ECS_SERVICE" --task-definition "$PREVIOUS_TASK_DEFINITION" --region "$AWS_REGION"
```
- Stop at the first failed verify block; do not continue optimistically.
- Roll back immediately if error rate or latency breaches the documented threshold.
## 8. Change Log
| Version | Date | Author | Change Summary |
| --- | --- | --- | --- |
| 1.4 | [DATE] | Platform Engineering | Refreshed rollout verification and rollback evidence capture steps |
| 1.0 | 2024-01-15 | Platform Engineering | Initial approved production deployment runbook |
