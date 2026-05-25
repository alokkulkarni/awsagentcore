# ARIA Banking Agent Operational Runbook

| Field | Value |
|---|---|
| **Document ID** | RNB-ARIA-BANKING-001 |
| **Companion Playbook** | PLY-ARIA-BANKING-001 |
| **Version** | 1.0 |
| **Owner** | Platform Engineering |
| **Date** | 2026-05-25 |
| **Status** | Active |

> Execute steps in order. Every step includes a **✓ Verify** block.
> Repository root used throughout: `/Users/alokkulkarni/Documents/Development/awsagentcore`

---

## 1. Pre-deployment checklist

### 1.1 Confirm AWS identity and repository state

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
aws sts get-caller-identity
git status
```

**✓ Verify**

```bash
aws sts get-caller-identity --query 'Account' --output text && git status --short
```

**Expected output:** first command returns the AWS account ID; second command returns no lines for a clean tree.

### 1.2 Confirm Bedrock model availability

```bash
aws bedrock list-foundation-models \
  --region eu-west-2 \
  --query "modelSummaries[?contains(modelId, 'claude-sonnet-4-6')].[modelId]" \
  --output table

aws bedrock list-foundation-models \
  --region eu-north-1 \
  --query "modelSummaries[?contains(modelId, 'nova-2-sonic')].[modelId]" \
  --output table
```

**✓ Verify**

```bash
aws bedrock list-foundation-models --region eu-west-2 --query "length(modelSummaries[?contains(modelId, 'claude-sonnet-4-6')])" --output text && \
aws bedrock list-foundation-models --region eu-north-1 --query "length(modelSummaries[?contains(modelId, 'nova-2-sonic')])" --output text
```

**Expected output:** both commands return a value greater than `0`.

### 1.3 Confirm Amazon Connect instance ID

```bash
export CONNECT_INSTANCE_ID="<connect-instance-uuid>"
aws connect describe-instance \
  --instance-id "$CONNECT_INSTANCE_ID" \
  --region eu-west-2 \
  --query 'Instance.[Id,InstanceStatus]' \
  --output table
```

**✓ Verify**

```bash
aws connect describe-instance --instance-id "$CONNECT_INSTANCE_ID" --region eu-west-2 --query 'Instance.InstanceStatus' --output text
```

**Expected output:** `ACTIVE`.

### 1.4 Confirm tooling versions

```bash
aws --version
agentcore --version
python3 --version
docker --version
uv --version
```

**✓ Verify**

```bash
command -v aws && command -v agentcore && command -v python3 && command -v docker && command -v uv
```

**Expected output:** all five commands print executable paths with no errors.

### 1.5 Back up deployment state

```bash
[ -f scripts/.deploy-state.json ] && \
  cp scripts/.deploy-state.json "scripts/.deploy-state.json.bak-$(date +%Y%m%d%H%M%S)"
```

**✓ Verify**

```bash
ls -1 scripts/.deploy-state.json* 2>/dev/null | tail -5
```

**Expected output:** existing state file and/or a timestamped backup file is listed.

---

## 2. Cloud deployment (agentcore mode)

### 2.1 Start the full deployment

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
./scripts/deploy.sh deploy agentcore
```

**Expected duration:** **15–25 minutes**.

The script prompts for:

- AgentCore runtime region (`eu-west-2`)
- Claude region (`eu-west-2`)
- Nova Sonic region (`eu-north-1`)
- S3 bucket names (`meridian-aria-transcripts-<id>`, `meridian-aria-audit-<id>`, `meridian-aria-client-<id>`)
- Agent name (`aria_banking_agent`)
- Connect instance ID
- Build mode (`1=CodeBuild`, `2=Local Docker build`)

### 2.2 What `deploy agentcore` creates, in order

1. S3 transcript bucket: `meridian-aria-transcripts-<id>`
2. S3 audit WORM bucket: `meridian-aria-audit-<id>`
3. DynamoDB table: `aria-audit-events`
4. EventBridge bus: `aria-audit`
5. CloudTrail Lake data store and channel: `aria-banking-audit`, `aria-audit-channel`
6. IAM roles: `aria-lambda-audit-role`, `aria-lambda-fulfillment-role`, `aria-lambda-session-injector-role`, `aria-firehose-audit-role`
7. Audit Lambdas: `aria-audit-cloudtrail-writer`, `aria-audit-dynamodb-writer`
8. Kinesis Firehose: `aria-audit-firehose`
9. EventBridge rules: `aria-audit-to-cloudtrail`, `aria-audit-to-dynamodb`, `aria-audit-to-firehose`
10. AgentCore container build and push to ECR repository `bedrock-agentcore-aria-banking-agent`
11. AgentCore runtime launch for `aria_banking_agent`
12. Lex fulfillment Lambda: `aria-lex-fulfillment`
13. Connect session injector Lambda: `aria-session-injector`
14. Cognito Identity Pool and unauth role
15. React client bucket: `meridian-aria-client-<id>`
16. CloudFront distribution
17. `npm run build` and S3 sync of the React `dist/`

### 2.3 Manual recovery reference: exact core commands used by `scripts/deploy.sh`

```bash
# Foundation infrastructure
aws s3api create-bucket --bucket "$TRANSCRIPT_BUCKET" --region "$AGENTCORE_REGION" --create-bucket-configuration LocationConstraint="${AGENTCORE_REGION}"
aws s3api put-bucket-versioning --bucket "$TRANSCRIPT_BUCKET" --versioning-configuration Status=Enabled
aws s3api create-bucket --bucket "$AUDIT_BUCKET" --region "$AGENTCORE_REGION" --create-bucket-configuration LocationConstraint="${AGENTCORE_REGION}" --object-lock-enabled-for-bucket
aws s3api put-object-lock-configuration --bucket "$AUDIT_BUCKET" --object-lock-configuration '{"ObjectLockEnabled":"Enabled","Rule":{"DefaultRetention":{"Mode":"COMPLIANCE","Days":2557}}}'
aws dynamodb create-table --table-name aria-audit-events --attribute-definitions AttributeName=customer_id,AttributeType=S AttributeName=timestamp,AttributeType=S --key-schema AttributeName=customer_id,KeyType=HASH AttributeName=timestamp,KeyType=RANGE --billing-mode PAY_PER_REQUEST --region "$AGENTCORE_REGION" --output text --query "TableDescription.TableName"
aws dynamodb wait table-exists --table-name aria-audit-events --region "$AGENTCORE_REGION"
aws dynamodb update-time-to-live --table-name aria-audit-events --time-to-live-specification "Enabled=true,AttributeName=ttl" --region "$AGENTCORE_REGION"
aws events create-event-bus --name aria-audit --region "$AGENTCORE_REGION" --query "EventBusArn" --output text
aws cloudtrail create-event-data-store --name aria-banking-audit --retention-period 2557 --no-multi-region-enabled --advanced-event-selectors '[{"Name":"ARIA custom audit events","FieldSelectors":[{"Field":"eventCategory","Equals":["ActivityAuditLog"]}]}]' --region "$AGENTCORE_REGION" --query "EventDataStoreArn" --output text
aws cloudtrail create-channel --name aria-audit-channel --source Custom --destinations "[{\"Type\":\"EVENT_DATA_STORE\",\"Location\":\"${CLOUDTRAIL_EDS_ARN}\"}]" --region "$AGENTCORE_REGION" --query "ChannelArn" --output text

# Audit fan-out
aws iam create-role --role-name aria-lambda-audit-role --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' --query "Role.RoleName" --output text
aws iam attach-role-policy --role-name aria-lambda-audit-role --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
aws firehose create-delivery-stream --delivery-stream-name aria-audit-firehose --delivery-stream-type DirectPut --extended-s3-destination-configuration "RoleARN=${FIREHOSE_ROLE_ARN},BucketARN=arn:aws:s3:::${AUDIT_BUCKET},Prefix=audit-events/,ErrorOutputPrefix=error/,CompressionFormat=GZIP,BufferingHints={SizeInMBs=5,IntervalInSeconds=300}" --region "$AGENTCORE_REGION" --query "DeliveryStreamARN" --output text
aws events put-rule --name "aria-audit-to-cloudtrail" --event-bus-name aria-audit --event-pattern '{"source":["com.meridianbank.aria"],"detail-type":["BankingAuditEvent"]}' --state ENABLED --region "$AGENTCORE_REGION" --query "RuleArn" --output text
aws events put-rule --name "aria-audit-to-dynamodb" --event-bus-name aria-audit --event-pattern '{"source":["com.meridianbank.aria"],"detail-type":["BankingAuditEvent"]}' --state ENABLED --region "$AGENTCORE_REGION" --query "RuleArn" --output text
aws events put-rule --name "aria-audit-to-firehose" --event-bus-name aria-audit --event-pattern '{"source":["com.meridianbank.aria"],"detail-type":["BankingAuditEvent"]}' --state ENABLED --region "$AGENTCORE_REGION" --query "RuleArn" --output text

# AgentCore runtime
agentcore launch --agent "$AGENT_NAME" --env "NOVA_SONIC_REGION=${NOVA_SONIC_REGION}" --env "TRANSCRIPT_S3_BUCKET=${TRANSCRIPT_BUCKET}" --env "TRANSCRIPT_S3_PREFIX=transcripts" --env "TRANSCRIPT_STORE=s3" --env "AUDIT_STORE=eventbridge" --env "AUDIT_EVENTBRIDGE_BUS=aria-audit" --env "AUDIT_REGION=${AGENTCORE_REGION}" --env "BANK_API_BASE_URL=${BANK_API_BASE_URL}" --env "BANK_API_KEY=${BANK_API_KEY}" --env "LOG_LEVEL=INFO"

# Integration + client delivery
aws cognito-identity create-identity-pool --identity-pool-name "$POOL_NAME" --allow-unauthenticated-identities --region "$AGENTCORE_REGION" --no-cli-pager --query 'IdentityPoolId' --output text
aws cloudfront create-origin-access-control --origin-access-control-config "{\"Name\":\"${OAC_NAME}\",\"Description\":\"ARIA React OAC\",\"SigningProtocol\":\"sigv4\",\"SigningBehavior\":\"always\",\"OriginAccessControlOriginType\":\"s3\"}" --query 'OriginAccessControl.Id' --output text --no-cli-pager
npm run build --prefix client
aws s3 sync client/dist/ "s3://${CLIENT_BUCKET}/" --delete --region "$AGENTCORE_REGION" --cache-control "max-age=31536000,immutable" --exclude "index.html" --no-cli-pager
aws s3 cp client/dist/index.html "s3://${CLIENT_BUCKET}/index.html" --region "$AGENTCORE_REGION" --cache-control "no-cache,no-store,must-revalidate" --content-type "text/html" --no-cli-pager
aws cloudfront create-invalidation --distribution-id "$CF_DISTRIBUTION_ID" --paths "/*" --query 'Invalidation.Id' --output text --no-cli-pager
```

**✓ Verify**

```bash
./scripts/deploy.sh status
```

**Expected output:** populated values for `Runtime ARN`, `Transcript bucket`, `Audit WORM bucket`, `CloudFront distribution`, `CloudFront domain`, `Firehose stream`, `Cognito Identity Pool`, and React `VITE_*` values.

---

## 3. Local development mode

### 3.1 Prepare local mode

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
./scripts/deploy.sh deploy local
```

The script creates `.venv` if required, installs Python dependencies, and writes `client/.env.local` with localhost endpoints.

### 3.2 Start the local backend and client

```bash
source .venv/bin/activate
uvicorn aria.agentcore_app:app --host 0.0.0.0 --port 8080 --workers 1
```

In a second terminal:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/client
npm install
npm run dev
```

**✓ Verify**

```bash
curl -i http://localhost:8080/ping | head -5
```

**Expected output:** HTTP `200` response headers from the AgentCore app.

---

## 4. Status check and cost check

### 4.1 Status

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
./scripts/deploy.sh status
```

**✓ Verify**

```bash
./scripts/deploy.sh status | grep -E 'Runtime ARN|CloudFront domain|Cognito Identity Pool|Firehose stream'
```

**Expected output:** matching lines for all four labels.

### 4.2 Costs

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
./scripts/deploy.sh costs
```

**✓ Verify**

```bash
./scripts/deploy.sh costs | grep -E 'TOTAL|Forecasted month-end total|Spend looks normal|Spend exceeds'
```

**Expected output:** one cost total line and one forecast/status line.

---

## 5. Updating a Lambda without full teardown

Use the same packaging/update sequence as `deploy_lambda()` in `scripts/deploy.sh`. Example below redeploys **`aria-session-injector`** only.

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
export AGENTCORE_REGION="$(python3 -c "import json; print(json.load(open('scripts/.deploy-state.json')).get('agentcore_region','eu-west-2'))")"
export ZIP_PATH="scripts/aria-session-injector.zip"
(cd scripts/lambdas && zip -q "../aria-session-injector.zip" "session_injector.py")
aws lambda update-function-code \
  --function-name "aria-session-injector" \
  --zip-file "fileb://${ZIP_PATH}" \
  --region "$AGENTCORE_REGION" \
  --query "FunctionName" --output text
aws lambda wait function-updated \
  --function-name "aria-session-injector" \
  --region "$AGENTCORE_REGION"
aws lambda update-function-configuration \
  --function-name "aria-session-injector" \
  --environment "Variables={AWS_REGION=${AGENTCORE_REGION},MEMORY_TABLE_NAME=aria-audit-events}" \
  --region "$AGENTCORE_REGION" \
  --query "FunctionName" --output text
rm -f "$ZIP_PATH"
```

**Other source/function mappings**

- `scripts/lambdas/aria_connect_fulfillment.py` → `aria-lex-fulfillment`
- `scripts/lambdas/audit_cloudtrail_writer.py` → `aria-audit-cloudtrail-writer`
- `scripts/lambdas/audit_dynamodb_writer.py` → `aria-audit-dynamodb-writer`

**✓ Verify**

```bash
aws lambda get-function --function-name aria-session-injector --region "$AGENTCORE_REGION" --query 'Configuration.[FunctionName,LastUpdateStatus,State]' --output table
```

**Expected output:** `aria-session-injector`, `Successful`, `Active`.

---

## 6. Updating the React client

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
export AGENTCORE_REGION="$(python3 -c "import json; print(json.load(open('scripts/.deploy-state.json')).get('agentcore_region','eu-west-2'))")"
export CLIENT_BUCKET="$(python3 -c "import json; print(json.load(open('scripts/.deploy-state.json')).get('client_bucket',''))")"
export CF_DISTRIBUTION_ID="$(python3 -c "import json; print(json.load(open('scripts/.deploy-state.json')).get('cloudfront_distribution_id',''))")"
cd client && npm run build
aws s3 sync dist/ "s3://${CLIENT_BUCKET}/" \
  --delete \
  --region "$AGENTCORE_REGION" \
  --cache-control "max-age=31536000,immutable" \
  --exclude "index.html" \
  --no-cli-pager
aws s3 cp dist/index.html "s3://${CLIENT_BUCKET}/index.html" \
  --region "$AGENTCORE_REGION" \
  --cache-control "no-cache,no-store,must-revalidate" \
  --content-type "text/html" \
  --no-cli-pager
aws cloudfront create-invalidation \
  --distribution-id "$CF_DISTRIBUTION_ID" \
  --paths '/*' \
  --query 'Invalidation.Id' --output text --no-cli-pager
```

**✓ Verify**

```bash
aws s3 ls "s3://${CLIENT_BUCKET}/index.html" && aws cloudfront get-distribution --id "$CF_DISTRIBUTION_ID" --query 'Distribution.Status' --output text --no-cli-pager
```

**Expected output:** `index.html` is listed in S3 and CloudFront status is `InProgress` or `Deployed`.

---

## 7. Smoke tests

### 7.1 Confirm deployment status

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
./scripts/deploy.sh status
```

**✓ Verify**

```bash
./scripts/deploy.sh status | grep 'Runtime ARN'
```

**Expected output:** one `Runtime ARN` line with an `arn:aws:bedrock-agentcore:` value.

### 7.2 Test ARIA chat invoke

Use the exact quick test printed by `scripts/deploy.sh`:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
agentcore invoke '{"message": "Hello Aria", "authenticated": true, "customer_id": "CUST-001"}'
```

If the generated smoke script exists, run it as well:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
python3 scripts/test_invoke.py
```

**✓ Verify**

```bash
python3 scripts/test_invoke.py | tail -5
```

**Expected output:** ARIA returns a readable banking-agent response rather than an exception.

### 7.3 Check CloudWatch for Lambda errors

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
export AGENTCORE_REGION="$(python3 -c "import json; print(json.load(open('scripts/.deploy-state.json')).get('agentcore_region','eu-west-2'))")"
for fn in aria-audit-cloudtrail-writer aria-audit-dynamodb-writer aria-lex-fulfillment aria-session-injector; do
  echo "=== ${fn} ==="
  aws logs tail "/aws/lambda/${fn}" --since 15m --format short --region "$AGENTCORE_REGION" | grep -iE 'error|exception' || true
done
```

**✓ Verify**

```bash
for fn in aria-audit-cloudtrail-writer aria-audit-dynamodb-writer aria-lex-fulfillment aria-session-injector; do
  aws logs tail "/aws/lambda/${fn}" --since 15m --format short --region "$AGENTCORE_REGION" | grep -qiE 'error|exception' && echo "FAIL:${fn}" || echo "OK:${fn}"
done
```

**Expected output:** `OK:` for all four functions.

### 7.4 Check DynamoDB audit events

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
export AGENTCORE_REGION="$(python3 -c "import json; print(json.load(open('scripts/.deploy-state.json')).get('agentcore_region','eu-west-2'))")"
aws dynamodb scan \
  --table-name aria-audit-events \
  --region "$AGENTCORE_REGION" \
  --max-items 5 \
  --query 'Items[].{customer_id:customer_id.S,timestamp:timestamp.S}'
```

**✓ Verify**

```bash
aws dynamodb scan --table-name aria-audit-events --region "$AGENTCORE_REGION" --max-items 1 --query 'length(Items)' --output text
```

**Expected output:** `1` or another value greater than `0` after smoke traffic has been generated.

---

## 8. Rollback procedure

### 8.1 Preserve current state first

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
cp scripts/.deploy-state.json "scripts/.deploy-state.json.rollback-$(date +%Y%m%d%H%M%S)"
```

**✓ Verify**

```bash
ls -1 scripts/.deploy-state.json.rollback-* | tail -1
```

**Expected output:** one rollback snapshot path.

### 8.2 Runtime rollback using a previous ECR image tag

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
export AGENTCORE_REGION="$(python3 -c "import json; print(json.load(open('scripts/.deploy-state.json')).get('agentcore_region','eu-west-2'))")"
aws ecr list-images --repository-name bedrock-agentcore-aria-banking-agent --region "$AGENTCORE_REGION" --output table
# Re-deploy the previously approved image by restoring the known-good code or image workflow, then rerun:
./scripts/deploy.sh deploy agentcore
```

**✓ Verify**

```bash
./scripts/deploy.sh status | grep 'Runtime ARN'
```

**Expected output:** a fresh runtime ARN is present and smoke tests pass on the rolled-back build.

### 8.3 Lambda rollback using the previous ZIP/package

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
export AGENTCORE_REGION="$(python3 -c "import json; print(json.load(open('scripts/.deploy-state.json')).get('agentcore_region','eu-west-2'))")"
aws lambda update-function-code \
  --function-name "aria-lex-fulfillment" \
  --zip-file "fileb://<previous-known-good-zip>" \
  --region "$AGENTCORE_REGION" \
  --query "FunctionName" --output text
aws lambda wait function-updated \
  --function-name "aria-lex-fulfillment" \
  --region "$AGENTCORE_REGION"
```

**✓ Verify**

```bash
aws lambda get-function --function-name aria-lex-fulfillment --region "$AGENTCORE_REGION" --query 'Configuration.[LastUpdateStatus,State]' --output text
```

**Expected output:** `Successful` and `Active`.

---

## 9. Teardown

### 9.1 Execute teardown

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
./scripts/deploy.sh teardown
```

**Warning:** this is irreversible for runtime, EventBridge, Firehose, Lambda, Cognito, CloudFront, and DynamoDB resources. The audit WORM bucket may remain because Object Lock COMPLIANCE retention blocks deletion.

The script removes:

- AgentCore runtime and session
- EventBridge rules and `aria-audit` bus
- Lambdas and IAM roles
- Firehose
- CloudTrail channels and `aria-banking-audit*` stores (queued for deletion)
- DynamoDB table `aria-audit-events`
- CloudFront distribution and OAC
- Cognito Identity Pool and unauth role
- Optional transcript bucket and client bucket
- `scripts/.deploy-state.json`

**✓ Verify**

```bash
./scripts/deploy.sh status 2>&1 | grep 'No deployment state found'
```

**Expected output:** `No deployment state found. Run: ./scripts/deploy.sh deploy`.

---

## 10. Troubleshooting

### 10.1 AgentCore will not start

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
aws logs tail /aws/bedrock-agentcore/runtimes --follow
```

Also rerun the exact status command:

```bash
./scripts/deploy.sh status
```

**✓ Verify**

```bash
./scripts/deploy.sh status | grep -E 'Runtime ARN|Execution role'
```

**Expected output:** runtime and execution role are present. If not, review the runtime logs for IAM / CodeBuild / container errors.

### 10.2 Lambda errors

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
export AGENTCORE_REGION="$(python3 -c "import json; print(json.load(open('scripts/.deploy-state.json')).get('agentcore_region','eu-west-2'))")"
aws logs tail /aws/lambda/aria-lex-fulfillment --since 30m --format short --region "$AGENTCORE_REGION"
aws logs tail /aws/lambda/aria-session-injector --since 30m --format short --region "$AGENTCORE_REGION"
```

**✓ Verify**

```bash
aws lambda get-function --function-name aria-lex-fulfillment --region "$AGENTCORE_REGION" --query 'Configuration.State' --output text && \
aws lambda get-function --function-name aria-session-injector --region "$AGENTCORE_REGION" --query 'Configuration.State' --output text
```

**Expected output:** both commands return `Active`.

### 10.3 CloudFront 403

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
export CLIENT_BUCKET="$(python3 -c "import json; print(json.load(open('scripts/.deploy-state.json')).get('client_bucket',''))")"
export CF_DISTRIBUTION_ID="$(python3 -c "import json; print(json.load(open('scripts/.deploy-state.json')).get('cloudfront_distribution_id',''))")"
export CF_DOMAIN="$(python3 -c "import json; print(json.load(open('scripts/.deploy-state.json')).get('cloudfront_domain',''))")"
curl -I "https://${CF_DOMAIN}"
aws cloudfront get-distribution --id "$CF_DISTRIBUTION_ID" --query 'Distribution.Status' --output text --no-cli-pager
aws s3api get-bucket-policy --bucket "$CLIENT_BUCKET"
```

**✓ Verify**

```bash
aws cloudfront get-distribution --id "$CF_DISTRIBUTION_ID" --query 'Distribution.DomainName' --output text --no-cli-pager
```

**Expected output:** the CloudFront domain matches the stored `cloudfront_domain`; if `curl -I` still returns `403`, re-check OAC bucket policy and propagation.

### 10.4 Cognito 403 / browser invoke denied

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
export AGENTCORE_REGION="$(python3 -c "import json; print(json.load(open('scripts/.deploy-state.json')).get('agentcore_region','eu-west-2'))")"
export POOL_ID="$(python3 -c "import json; print(json.load(open('scripts/.deploy-state.json')).get('cognito_identity_pool_id',''))")"
export UNAUTH_ROLE_ARN="$(python3 -c "import json; print(json.load(open('scripts/.deploy-state.json')).get('cognito_unauth_role_arn',''))")"
aws cognito-identity describe-identity-pool --identity-pool-id "$POOL_ID" --region "$AGENTCORE_REGION" --no-cli-pager
aws iam get-role-policy --role-name "${UNAUTH_ROLE_ARN##*/}" --policy-name aria-cognito-unauth-policy
```

**✓ Verify**

```bash
aws iam get-role-policy --role-name "${UNAUTH_ROLE_ARN##*/}" --policy-name aria-cognito-unauth-policy --query 'PolicyDocument.Statement[0].Action' --output text
```

**Expected output:** includes `bedrock-agentcore:InvokeAgentRuntime`, `bedrock-agentcore:InvokeAgentRuntimeForUser`, and `bedrock-agentcore:InvokeAgentRuntimeWithWebSocketStream`.

### 10.5 Voice not connecting / Nova Sonic issue

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
aws bedrock list-foundation-models \
  --region eu-north-1 \
  --query "modelSummaries[?contains(modelId, 'nova-2-sonic')].[modelId]" \
  --output table
aws logs tail /aws/bedrock-agentcore/runtimes --since 30m | grep -iE 'nova|sonic|bidirectional|InvokeModelWithBidirectionalStream' || true
```

**✓ Verify**

```bash
aws bedrock list-foundation-models --region eu-north-1 --query "length(modelSummaries[?contains(modelId, 'nova-2-sonic')])" --output text
```

**Expected output:** value greater than `0`. If runtime logs show bidirectional stream or permission errors, verify the runtime execution role includes Bedrock cross-region invoke permissions.
