# Common Runbook Patterns

Use these patterns to turn raw deployment mechanics into clear, verifiable procedures.

## Blue-green deployment pattern

**When to use:** stateless services with two independently runnable environments and a traffic switch.

**Recommended flow**

1. Validate the green environment with the target artifact.
2. Run smoke tests directly against green.
3. Verify schema and feature-flag compatibility.
4. Shift traffic in a controlled way.
5. Verify traffic, latency, error rate, and health checks.
6. Keep blue intact until the observation window ends.

**Verify gates**

- green health endpoint returns 200
- target group healthy host count matches expected capacity
- error rate stays below the rollback threshold after the switch
- one high-value business transaction succeeds on green

## Canary deployment pattern

**When to use:** progressive delivery with percentage-based traffic shifting.

**Recommended flow**

1. Deploy the candidate version beside the stable version.
2. Shift 1–5% of traffic to the canary.
3. Verify the golden signals and business KPIs.
4. Promote gradually to 25%, 50%, and 100% only if each gate passes.
5. Roll back immediately if any promotion gate is violated.

**Common rollback gates**

- error rate > X% for Y minutes
- p99 latency exceeds 2x baseline
- health checks fail on more than N targets
- a business transaction fails during the canary window

## Database migration pattern

**When to use:** deployments that change schema, data shape, or migration state.

**Recommended flow**

1. confirm the migration is backward compatible when possible
2. take or verify a fresh backup
3. run the migration
4. verify schema objects, row counts, and application startup
5. keep an explicit restore or reverse-migration decision point

**Mandatory verify points**

- backup completed successfully
- migration tool reports success with zero pending statements
- application can read and write with the new schema
- restore point or reversal path is documented before proceeding

## Lambda deployment pattern

**When to use:** AWS Lambda functions with published versions and aliases.

**Recommended flow**

1. publish the new Lambda version
2. verify configuration, environment variables, and IAM role
3. point a test alias or weighted alias to the new version
4. verify CloudWatch logs and metrics
5. shift production traffic only after the verify gate passes

**Verify commands to include**

- `aws lambda get-function-configuration`
- `aws lambda get-alias`
- `aws cloudwatch get-metric-statistics` or alarm checks
- synthetic invocation or business-path smoke test

## CloudFormation stack update pattern

**When to use:** infrastructure or application changes managed by CloudFormation or SAM.

**Recommended flow**

1. validate the template locally
2. create a change set
3. review the diff for destructive operations
4. execute the change set in the approved window
5. wait for `UPDATE_COMPLETE` and verify downstream services

**Verify gates**

- template validation exits 0
- change set contains only approved resources
- stack reaches `UPDATE_COMPLETE`
- alarms remain healthy after execution

## Docker / ECS deployment pattern

**When to use:** containerized services on ECS, EKS, Kubernetes, or similar schedulers.

**Recommended flow**

1. build and tag the release image
2. push the image to the registry
3. register the new task definition or deployment spec
4. update the service
5. wait for the service to become steady
6. run smoke tests and verify metrics

**Verify gates**

- image digest exists in the registry
- task definition references the expected image tag
- scheduler reports rollout complete or service stable
- health checks and synthetic probes succeed

## Rollback trigger examples

Define objective rollback triggers before the change starts. Common triggers include:

- error rate > X% for Y minutes
- latency p99 > X ms for Y minutes
- health check failures on more than N targets
- new deployment fails to reach steady state inside the documented timeout
- queue backlog or retry depth grows above threshold
- data integrity or migration verification fails

Every runbook should pair each trigger with a metric, alarm name, CLI query, or log command.
