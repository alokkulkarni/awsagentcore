# DTMF Secure Capture (Marketplace) Runbook

This runbook covers secure deployment, verification, rotation, monitoring, incident response, teardown, and troubleshooting for the DTMF Secure Capture marketplace component.

## 1. Pre-deployment security checklist

Confirm all items before touching production:
- [ ] Security Officer approval confirmed
- [ ] PCI DSS scope document referenced for this environment
- [ ] No real PANs or live customer data will be used in test or staging
- [ ] Secrets Manager read permissions verified for the decrypt Lambda role only
- [ ] KMS key policy reviewed for least privilege
- [ ] CloudWatch log retention configured and reviewed to avoid retaining any 13-19 digit raw values
- [ ] Change window approved with Contact Centre Ops
- [ ] Rollback owner assigned

Recommended pre-check commands:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
aws sts get-caller-identity
aws configure list
printf 'AWS_REGION=%s\nCONNECT_INSTANCE_ID=%s\nSTACK_SUFFIX=%s\n' "$AWS_REGION" "$CONNECT_INSTANCE_ID" "$STACK_SUFFIX"
```

## 2. Step 1 — Generate RSA key pair

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
bash scripts/setup_dtmf_keys.sh
# Prompts: Region (eu-west-2), Secret name (aria/dtmf-private-key), KMS alias (alias/aria-dtmf-cmk)
# Save to secure vault: PrivateKeySecretArn, KmsKeyArn, Public Key PEM
export DTMF_PRIVATE_KEY_SECRET_ARN="arn:aws:secretsmanager:..."
export DTMF_KMS_KEY_ARN="arn:aws:kms:..."
```

Repository note: the checked-in script currently expects an explicit subcommand. If invoking the repository version directly, use:

```bash
bash scripts/setup_dtmf_keys.sh setup
```

Operator notes:
- Record the public key PEM in an approved secure vault or change record.
- Do not store the private key outside Secrets Manager after script completion.
- If the script reports a Connect key association, still independently verify the visible key in the console.

## 3. Step 2 — Add public key to Amazon Connect console

Exact UI path:
1. Sign in to **Amazon Connect Console**.
2. Open **Amazon Connect → Instances → _your instance_**.
3. In the instance navigation, open **Security keys**.
4. Select **Add key**.
5. Paste the full public key PEM block generated in Step 1.
6. Save the key.
7. Copy the displayed **Key ID**.
8. Update the shell environment:

```bash
export DTMF_CONNECT_KEY_ID="<key-id-from-console>"
```

## 4. Step 3 — Deploy CloudFormation

Export the required deployment variables first:

```bash
export AWS_REGION="eu-west-2"
export CONNECT_INSTANCE_ID="<connect-instance-id>"
export STACK_SUFFIX="prod"
```

Deploy the stack:

```bash
aws cloudformation deploy \
  --template-file marketplace/cloudformation/dtmf-secure-capture.yaml \
  --stack-name dtmf-secure-capture-${STACK_SUFFIX} \
  --region "$AWS_REGION" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    PrivateKeySecretArn="$DTMF_PRIVATE_KEY_SECRET_ARN" \
    KmsKeyArn="$DTMF_KMS_KEY_ARN" \
    ConnectInstanceId="$CONNECT_INSTANCE_ID" \
    ConnectEncryptionKeyId="$DTMF_CONNECT_KEY_ID"
```

Repository alignment check for the current template revision:
- Verify parameter names with `aws cloudformation validate-template --template-body file://marketplace/cloudformation/dtmf-secure-capture.yaml`.
- The checked-in template may also require `ConnectInstanceArn` and may emit `KMSKeyArn` as an output instead of accepting it as an input parameter. If so, add the missing parameter before deployment.

Verification commands:

```bash
aws cloudformation wait stack-create-complete \
  --stack-name dtmf-secure-capture-${STACK_SUFFIX} \
  --region "$AWS_REGION"

aws cloudformation describe-stacks \
  --stack-name dtmf-secure-capture-${STACK_SUFFIX} \
  --region "$AWS_REGION" \
  --query 'Stacks[0].StackStatus'

aws cloudformation describe-stacks \
  --stack-name dtmf-secure-capture-${STACK_SUFFIX} \
  --region "$AWS_REGION" \
  --query 'Stacks[0].Outputs' \
  --output table
```

Expected result: stack status `CREATE_COMPLETE` and outputs captured in the change record.

## 5. Step 4 — Deploy Lambda functions

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
bash scripts/deploy_dtmf_lambda.sh
```

Repository note: the checked-in script currently expects an explicit subcommand. If invoking the repository version directly, use:

```bash
bash scripts/deploy_dtmf_lambda.sh deploy
```

Verify all four Lambda functions:

```bash
for fn in aria-dtmf-start-session aria-dtmf-decrypt aria-dtmf-validate aria-dtmf-status-proxy; do
  aws lambda get-function \
    --function-name "$fn" \
    --region "$AWS_REGION" \
    --query 'Configuration.[FunctionName,Runtime,State,LastModified]' \
    --output table
  aws lambda list-aliases \
    --function-name "$fn" \
    --region "$AWS_REGION" \
    --query 'Aliases[].{Name:Name,Version:FunctionVersion}' \
    --output table
done
```

Expected result: all 4 functions report `State=Active` and the required alias exists.

## 6. Step 5 — Import contact flow

1. Open **Amazon Connect Console → your instance → Contact flows**.
2. Select **Create contact flow → Import flow (beta)**.
3. Import the required flow from `marketplace/contact-flows/`.
4. Update each Lambda block to the correct deployed alias ARN.
5. In every **Store customer input** block, confirm encryption is enabled and the new Connect key ID is selected.
6. Save and publish the flow.

## 7. End-to-end test

```bash
# Test session creation
aws lambda invoke --function-name aria-dtmf-start-session \
  --payload '{"contactId":"test-001","purpose":"card_last_four"}' \
  --cli-binary-format raw-in-base64-out /tmp/dtmf-session.json
cat /tmp/dtmf-session.json   # Expected: {"sessionId":"...","status":"pending"}

# Poll status
SESSION_ID=$(cat /tmp/dtmf-session.json | python3 -c "import json,sys; print(json.load(sys.stdin)['sessionId'])")
aws lambda invoke --function-name aria-dtmf-status-proxy \
  --payload "{\"sessionId\":\"$SESSION_ID\"}" \
  --cli-binary-format raw-in-base64-out /tmp/dtmf-status.json
cat /tmp/dtmf-status.json
```

Manual agent/browser validation:
1. Place a test call.
2. Accept the call in the CCP.
3. Trigger the secure capture flow.
4. Enter a synthetic test number such as `4111111111111111`.
5. Confirm the launcher opens/focuses the panel.
6. Confirm the panel shows masked output only.
7. Confirm terminal status appears within 6 seconds.

## 8. PAN audit check (MANDATORY post-deploy)

```bash
# Confirm no PANs in Lambda logs — check last 30 min
aws logs filter-log-events \
  --log-group-name /aws/lambda/aria-dtmf-decrypt \
  --start-time $(date -u +%s000 -d '30 minutes ago' 2>/dev/null || date -u -v-30M +%s000) \
  --filter-pattern "[0-9]{13,19}" 2>/dev/null | python3 -c "
import json,sys
events = json.load(sys.stdin).get('events',[])
if events:
    print('WARNING: Possible PAN in logs — investigate immediately')
else:
    print('PASS: No PAN patterns found in logs')
"
```

Repeat the same check for:
- `/aws/lambda/aria-dtmf-validate`
- `/aws/lambda/aria-dtmf-start-session`
- `/aws/lambda/aria-dtmf-status-proxy`

## 9. RSA key rotation procedure

Zero-downtime target procedure:
1. Confirm no uncontrolled change is in flight.
2. Check active sessions before rotation.
3. Generate a new key pair and new secret.
4. Add the new public key to Amazon Connect while keeping the old key active.
5. Update the decrypt Lambda to the new secret/key ID.
6. Publish a new version and move the alias.
7. Update contact flows to the new Connect key.
8. Monitor live decryption success.
9. Remove the old key only after the validation window is complete.

Commands:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
bash scripts/setup_dtmf_keys.sh rotate

aws lambda update-function-configuration \
  --function-name aria-dtmf-decrypt \
  --region "$AWS_REGION" \
  --environment "Variables={PRIVATE_KEY_SECRET_ARN=$DTMF_PRIVATE_KEY_SECRET_ARN,CONNECT_KEY_ID=$DTMF_CONNECT_KEY_ID}"

NEW_VERSION=$(aws lambda publish-version \
  --function-name aria-dtmf-decrypt \
  --region "$AWS_REGION" \
  --query 'Version' \
  --output text)

aws lambda update-alias \
  --function-name aria-dtmf-decrypt \
  --name prod \
  --function-version "$NEW_VERSION" \
  --region "$AWS_REGION"
```

Rotation guardrails:
- Do not rotate during active calls.
- Keep both Connect keys active during the transition window.
- Keep the previous secret recoverable until production testing passes.
- Do not remove the old Connect key until both Lambda and contact flow changes are verified.

## 10. Monitor active sessions

Check active-session state:

```bash
aws dynamodb scan \
  --table-name dtmf_active_sessions \
  --region "$AWS_REGION" \
  --filter-expression "#s = :active OR #s = :awaiting OR #s = :collecting OR #s = :validating" \
  --expression-attribute-names '{"#s":"status"}' \
  --expression-attribute-values '{":active":{"S":"active"},":awaiting":{"S":"awaiting_trigger"},":collecting":{"S":"collecting"},":validating":{"S":"validating"}}'
```

Create a basic CloudWatch alarm for decrypt errors:

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name dtmf-decrypt-errors \
  --namespace AWS/Lambda \
  --metric-name Errors \
  --dimensions Name=FunctionName,Value=aria-dtmf-decrypt \
  --statistic Sum \
  --period 300 \
  --evaluation-periods 1 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold
```

Recommended monitors:
- Lambda `Errors`, `Duration`, and throttles for all 4 functions
- API Gateway 4xx/5xx for the status proxy
- DynamoDB throttles on the sessions table
- CloudFront 4xx/5xx for panel assets
- Secrets Manager `GetSecretValue` anomalies via CloudTrail

## 11. SECURITY INCIDENT — private key suspected compromised

Immediate response steps:
1. Declare a Sev-1 security incident.
2. Notify Security Officer immediately.
3. Freeze all non-essential DTMF changes.
4. Disable new production DTMF capture paths if required by policy.
5. Generate a replacement RSA key pair immediately.
6. Register the new public key in Amazon Connect.
7. Repoint the decrypt Lambda to the new secret/key.
8. Review CloudTrail for `GetSecretValue`, `Decrypt`, `PutKeyPolicy`, and Connect key-management events.
9. Run a PAN exposure audit across all Lambda log groups.
10. Preserve evidence and incident timeline for PCI/QSA review.

Rapid audit commands:

```bash
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=GetSecretValue \
  --max-results 50

aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=Decrypt \
  --max-results 50
```

## 12. Teardown

```bash
aws cloudformation delete-stack --stack-name dtmf-secure-capture-${STACK_SUFFIX}
aws cloudformation wait stack-delete-complete --stack-name dtmf-secure-capture-${STACK_SUFFIX}
aws secretsmanager delete-secret --secret-id aria/dtmf-private-key --recovery-window-in-days 7
# Remove Connect Security Profile key from console (UI steps)
```

Console teardown steps:
1. Open **Amazon Connect Console → your instance → Security keys**.
2. Select the DTMF key.
3. Remove the key only after confirming stack deletion and no rollback need.
4. Remove any agent workspace app integrations that pointed at the CloudFront launcher/panel.

## 13. Troubleshooting

| Symptom | Likely Cause | Resolution |
| --- | --- | --- |
| Decrypt returns error | Connect key ID mismatch or wrong private key secret | Verify `DTMF_CONNECT_KEY_ID`, Connect key selection in the flow, and `PRIVATE_KEY_SECRET_ARN` on `aria-dtmf-decrypt` |
| Session not found | Session TTL expired or ACTIVE record was cleared | Inspect `dtmf_active_sessions`, verify TTL, and check whether the start-session Lambda wrote the ACTIVE row |
| Agent panel not polling | API Gateway CORS or asset URL issue | Check `/dtmf-active` and `/dtmf-status`, confirm CORS, confirm CloudFront URLs patched into panel/launcher assets |
| Luhn validation failing | Wrong collection purpose or invalid test card | Verify the purpose passed to the flow and use a Luhn-valid synthetic card number |
| Status proxy 403 | IAM or Connect permission issue | Verify `connect:GetContactAttributes` on the status-proxy role and confirm the correct Connect instance ID |
