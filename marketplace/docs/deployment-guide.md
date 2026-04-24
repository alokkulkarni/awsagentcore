# Deployment Guide: Secure DTMF Capture for Amazon Connect

> **Product:** Secure DTMF Capture for Amazon Connect  
> **Version:** 1.0  
> **Estimated deployment time:** 30–45 minutes (first time), ~10 minutes for updates

---

## Prerequisites

Before you begin, ensure the following are in place.

### AWS Account Requirements

| Service | Required Permissions |
|---|---|
| AWS Lambda | Create, update, and invoke functions; publish versions; manage aliases |
| Amazon DynamoDB | Create tables, read/write items, manage TTL |
| Amazon Connect | Access to an existing instance; permission to add Security Keys and Lambda integrations |
| AWS Secrets Manager | Create and read secrets |
| AWS KMS | Create CMKs; grant key usage to IAM roles |
| Amazon CloudFront | Create distributions and OAC configurations |
| Amazon S3 | Create buckets; upload objects; manage bucket policies |
| Amazon API Gateway | Create HTTP APIs; manage routes and integrations |
| AWS IAM | Create roles and attach policies |
| AWS CloudFormation | Full stack management |

> **Note:** An IAM user or role with `AdministratorAccess` is sufficient for deployment. For production, use a least-privilege role that covers the services above.

### Amazon Connect Instance

You need an existing Amazon Connect instance. Note:
- **Instance ID** (UUID format, e.g. `f969d4b4-f716-4974-a325-bb7899f2f293`)
- **Instance ARN** (`arn:aws:connect:<region>:<account>:instance/<instanceId>`)
- The instance must have **Lambda integrations enabled** (this is the default for all instances)

If you need to create a new instance, see the [Amazon Connect Getting Started Guide](https://docs.aws.amazon.com/connect/latest/adminguide/amazon-connect-get-started.html).

### Local Tooling

| Tool | Version | Check |
|---|---|---|
| AWS CLI | v2.x | `aws --version` |
| Python | 3.12+ | `python3 --version` |
| pip | 23+ | `pip3 --version` |
| OpenSSL | 1.1.1+ | `openssl version` |
| zip | any | `zip --version` |
| bash | 4+ (macOS: use Homebrew bash) | `bash --version` |

Configure AWS CLI credentials with sufficient permissions:

```bash
aws configure
# or
export AWS_PROFILE=my-admin-profile
```

Verify access:

```bash
aws sts get-caller-identity
```

### Agent Browser Requirements

- Google Chrome 110+ or Microsoft Edge 110+
- Popup windows must be **allowed** for the CloudFront domain (agents should whitelist `https://<CloudFrontDomain>`)
- No strict Content Security Policy blocking cross-origin iframes

---

## Step 1: Generate the RSA Key Pair

The RSA key pair is the cryptographic foundation of the solution. The public key goes into Amazon Connect (to encrypt digits). The private key goes into Secrets Manager (to decrypt them).

Run the setup script from the repository root:

```bash
cd /path/to/awsagentcore
bash scripts/setup_dtmf_keys.sh
```

The script will prompt for:
- AWS region (e.g. `eu-west-2`)
- Secret name (e.g. `aria/dtmf-private-key`)
- KMS CMK alias (e.g. `alias/aria-dtmf-cmk`)

The script will:
1. Generate a 2048-bit RSA key pair using OpenSSL.
2. Store the private key PEM in AWS Secrets Manager, encrypted by a new KMS CMK.
3. Print the public key PEM to stdout.
4. Output the Secrets Manager ARN.

**Save the output:**

```
=== OUTPUT ===
PrivateKeySecretArn: arn:aws:secretsmanager:eu-west-2:123456789012:secret:aria/dtmf-private-key-AbCdEf
KmsKeyArn:           arn:aws:kms:eu-west-2:123456789012:key/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

Public key PEM (add this to Amazon Connect Security Keys):
-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA...
-----END PUBLIC KEY-----
```

You will need both the `PrivateKeySecretArn` and the public key PEM in the next step.

> **Security note:** The private key PEM file is written to disk momentarily during generation and then deleted. Verify it is gone with `ls -la *.pem`. Never commit a private key to source control.

---

## Step 2: Add the Public Key to Amazon Connect

Amazon Connect must hold your RSA public key so it can encrypt DTMF digits at capture time.

### Console Steps

1. Open the [Amazon Connect Console](https://console.aws.amazon.com/connect/).
2. Select your Connect instance.
3. In the left navigation, choose **Security keys** (under the *Security* section).
4. Click **Add key**.
5. Paste the entire public key PEM block (including `-----BEGIN PUBLIC KEY-----` and `-----END PUBLIC KEY-----` lines).
6. Click **Add**.

Amazon Connect will display a **Key ID** in UUID format (e.g. `a1b2c3d4-e5f6-7890-abcd-ef1234567890`). **Copy this Key ID** — you will use it as the `ConnectKeyId` CloudFormation parameter and the `CONNECT_KEY_ID` Lambda environment variable.

### Verification

After adding the key, it should appear in the Security Keys list with status **Active**. The key is now used for all "Store customer input" blocks in your instance where encryption is enabled.

---

## Step 3: Deploy the CloudFormation Stack

The CloudFormation template provisions all AWS resources: DynamoDB tables, API Gateway, IAM roles, CloudFront distribution, and S3 bucket.

### Template Location

```
marketplace/cloudformation/dtmf-secure-capture.yaml
```

### Parameters

| Parameter | Type | Default | Description | Example |
|---|---|---|---|---|
| `ConnectInstanceId` | String | *(required)* | Your Connect instance UUID | `f969d4b4-f716-4974-a325-bb7899f2f293` |
| `ConnectInstanceArn` | String | *(required)* | Full Connect instance ARN | `arn:aws:connect:eu-west-2:123456789012:instance/f969d4b4-...` |
| `ConnectKeyId` | String | *(required)* | Key ID from Step 2 | `a1b2c3d4-e5f6-7890-abcd-ef1234567890` |
| `PrivateKeySecretArn` | String | *(required)* | Secrets Manager ARN from Step 1 | `arn:aws:secretsmanager:eu-west-2:...` |
| `KmsKeyArn` | String | *(required)* | KMS CMK ARN from Step 1 | `arn:aws:kms:eu-west-2:...:key/...` |
| `CustomerDataLambdaArn` | String | *(optional)* | ARN of your ownership-check Lambda | `arn:aws:lambda:eu-west-2:...` |
| `SessionTTLHours` | Number | `2` | DynamoDB session TTL in hours | `2` |
| `EnableBinCheck` | String | `true` | Whether to check BIN table | `true` |
| `StackName` | String | `dtmf-secure-capture` | CloudFormation stack name | `dtmf-secure-capture-prod` |
| `Environment` | String | `prod` | Deployment environment tag | `prod` |

### Deploy via AWS Console

1. Open [CloudFormation](https://console.aws.amazon.com/cloudformation/) → **Create stack** → **With new resources**.
2. Upload `marketplace/cloudformation/dtmf-secure-capture.yaml`.
3. Fill in all required parameters.
4. Accept IAM capabilities (the stack creates IAM roles).
5. Click **Create stack**.

Estimated time: **5–8 minutes**.

### Deploy via AWS CLI (one-liner)

```bash
aws cloudformation deploy \
  --template-file marketplace/cloudformation/dtmf-secure-capture.yaml \
  --stack-name dtmf-secure-capture-prod \
  --region eu-west-2 \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    ConnectInstanceId=f969d4b4-f716-4974-a325-bb7899f2f293 \
    ConnectInstanceArn=arn:aws:connect:eu-west-2:123456789012:instance/f969d4b4-f716-4974-a325-bb7899f2f293 \
    ConnectKeyId=a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
    PrivateKeySecretArn=arn:aws:secretsmanager:eu-west-2:123456789012:secret:aria/dtmf-private-key-AbCdEf \
    KmsKeyArn=arn:aws:kms:eu-west-2:123456789012:key/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx \
    Environment=prod
```

### Stack Outputs

Once the stack completes, note these outputs from the **Outputs** tab. You will need them in later steps.

| Output Key | Description | Example |
|---|---|---|
| `CloudFrontDomain` | Agent panel URL base | `d1bkzzc74letv0.cloudfront.net` |
| `ApiGatewayUrl` | API Gateway base URL | `https://bz8frqf9f9.execute-api.eu-west-2.amazonaws.com` |
| `SessionsTableName` | DynamoDB sessions table | `dtmf_active_sessions` |
| `BinsTableName` | DynamoDB BIN table | `aria-card-bins` |
| `LauncherUrl` | Full launcher URL for Agent Workspace | `https://d1bkzzc74letv0.cloudfront.net/dtmf-launcher/index.html` |
| `PanelUrl` | Full panel URL | `https://d1bkzzc74letv0.cloudfront.net/dtmf-panel/index.html` |

---

## Step 4: Upload Lambda Code and Panel HTML

The deploy script packages, uploads, and configures all four Lambda functions and the S3-hosted panel files.

```bash
bash scripts/deploy_dtmf_lambda.sh deploy
```

The script is interactive and will prompt for:
- AWS region
- Connect instance ID
- Connect Key ID
- Secrets Manager ARN
- KMS CMK ARN
- DynamoDB table names (from stack outputs)
- API Gateway URL (from stack outputs)
- CloudFront domain (from stack outputs)
- Customer Data Lambda ARN (optional, press Enter to skip)

The script performs the following:
1. Packages each Lambda function into a zip file.
2. Builds the `aria-dtmf-dependencies` Lambda Layer (Python 3.12, `cryptography` and `aws-encryption-sdk` libraries compiled for `manylinux2014_x86_64`).
3. Creates or updates each Lambda function with the layer attached.
4. Publishes a new immutable version and moves the `prod` alias to it.
5. Attaches a Connect resource-based policy to the `:prod` alias of the decrypt and validate Lambdas so only your Connect instance can invoke them.
6. Uploads `dtmf-panel/index.html` and `dtmf-launcher/index.html` to the S3 bucket.

> **Contact flows should always reference the `:prod` alias ARN**, never `$LATEST`:
> ```
> arn:aws:lambda:eu-west-2:123456789012:function:aria-dtmf-decrypt:prod
> ```

For non-interactive deployments (CI/CD), all values can be passed as flags:

```bash
bash scripts/deploy_dtmf_lambda.sh deploy \
  --region eu-west-2 \
  --connect-instance-id f969d4b4-... \
  --connect-key-id a1b2c3d4-... \
  --secret-arn arn:aws:secretsmanager:... \
  --kms-key-arn arn:aws:kms:... \
  --sessions-table dtmf_active_sessions \
  --bins-table aria-card-bins \
  --api-url https://bz8frqf9f9.execute-api.eu-west-2.amazonaws.com \
  --cf-domain d1bkzzc74letv0.cloudfront.net
```

---

## Step 5: Populate the BIN Table (Card Capture Only)

If you intend to capture full card numbers (`full_card_number` or `card_last_four` purposes) and want BIN-level card type identification, populate the `aria-card-bins` DynamoDB table.

### BIN Record Format

Each item in the table represents a BIN prefix range:

| Attribute | Type | Example |
|---|---|---|
| `bin_prefix` | String (PK) | `"414900"` |
| `card_type` | String | `"VISA"` |
| `card_subtype` | String | `"DEBIT"` |
| `issuer` | String | `"Barclays UK"` |
| `country` | String | `"GB"` |

### Loading BIN Records

The deploy script seeds a small example set of BIN records for testing. For production, load records from a commercial BIN database provider (e.g. BINlist, Mastercard BIN lookup API, or your card processor's BIN file).

Load a single record:

```bash
aws dynamodb put-item \
  --table-name aria-card-bins \
  --region eu-west-2 \
  --item '{
    "bin_prefix":   {"S": "414900"},
    "card_type":    {"S": "VISA"},
    "card_subtype": {"S": "DEBIT"},
    "issuer":       {"S": "Barclays UK"},
    "country":      {"S": "GB"}
  }'
```

For bulk loading, use `aws dynamodb batch-write-item` or the AWS SDK with batch writes. BIN records change infrequently; a monthly refresh cadence is typical.

---

## Step 6: Import Contact Flows

The solution includes ready-to-import Amazon Connect contact flow JSON files.

### Available Flows

| Flow File | Description | Import When |
|---|---|---|
| `ARIA-DTMF-SecureCollection.json` | Main collection sub-flow; handles all purposes | Always — required |
| `ARIA-DTMF-CardCapture-Example.json` | Example trigger flow for card number capture | Card number use cases |
| `ARIA-DTMF-SSN-Example.json` | Example trigger flow for SSN capture | SSN use cases |
| `ARIA-DTMF-GenericCapture-Example.json` | Example trigger flow for generic digit capture | Generic use cases |

For detailed import instructions, see [`contact-flows/README.md`](../contact-flows/README.md).

### Import Steps (Console)

1. Open Amazon Connect console → your instance → **Contact flows**.
2. Click **Create contact flow** → **Import flow (beta)**.
3. Upload the JSON file.
4. Review the imported flow — Lambda ARNs will need updating to your deployed ARNs.
5. Update each **Invoke AWS Lambda function** block:
   - **Start session:** `arn:aws:lambda:<region>:<account>:function:aria-dtmf-start-session:prod`
   - **Decrypt:** `arn:aws:lambda:<region>:<account>:function:aria-dtmf-decrypt:prod`
   - **Validate:** `arn:aws:lambda:<region>:<account>:function:aria-dtmf-validate:prod`
6. Save and **Publish** the flow.

> **Lambda ARN references:** Always use the `:prod` alias ARN in contact flows. If you redeploy the Lambda code, the alias moves to the new version automatically.

---

## Step 7: Configure Agent Workspace

Agents access the DTMF launcher via a third-party application integration in the Amazon Connect Agent Workspace.

### Add Launcher as Third-Party App

1. Open Amazon Connect console → your instance → **Agent workspace** → **Third-party applications**.
2. Click **Add application**.
3. Fill in:
   - **Name:** `Secure DTMF Launcher`
   - **URL:** `https://<CloudFrontDomain>/dtmf-launcher/index.html`
   - **Namespace:** `dtmf_launcher`
4. Save.

### Set Permissions

Ensure agents have the `BasicAgentAccess` security profile (or equivalent) that allows them to:
- Access the Contact Control Panel
- Use third-party applications

No additional Connect permissions are required for agents to use the DTMF panel — all AWS API calls are made by Lambda functions with their own IAM roles.

### Allow Popups in Agent Browsers

Agents must allow popup windows from the CloudFront domain. Guide your agents to:

1. Visit `https://<CloudFrontDomain>/dtmf-launcher/index.html` in their browser.
2. When prompted, click **Always allow popups** from this site.
3. Refresh the page.

Alternatively, configure this via browser policy in your device management system (Intune, Jamf, etc.).

---

## Step 8: Test the Deployment

### Manual Test Procedure

1. **Place a test call** to your Connect instance from a PSTN number.
2. **Accept the call** in the Contact Control Panel (CCP).
3. **Note the Contact ID** from the CCP or CloudWatch Logs.
4. **Trigger the DTMF flow** by clicking the configured button in the CCP.
5. **Enter 16 test digits** on the test phone keypad when prompted. Use a valid Luhn number, e.g. `4111111111111111`.
6. **Check the DynamoDB session:**

```bash
aws dynamodb get-item \
  --table-name dtmf_active_sessions \
  --key '{"session_id":{"S":"ACTIVE"}}' \
  --region eu-west-2
```

Expected output: item with `contactId`, `collectionPurpose`, `status`, `ttl`.

7. **Check the contact attributes:**

```bash
aws connect get-contact-attributes \
  --instance-id f969d4b4-f716-4974-a325-bb7899f2f293 \
  --initial-contact-id <ContactId> \
  --region eu-west-2
```

Expected: `dtmf_status = "complete"`, `dtmf_masked_value = "****1111"`.

8. **Check CloudWatch Logs:**

```bash
aws logs tail /aws/lambda/aria-dtmf-decrypt --follow --region eu-west-2
aws logs tail /aws/lambda/aria-dtmf-validate --follow --region eu-west-2
```

Look for `"status": "success"` and `"isValid": "true"` in the log output.

9. **Verify the agent panel** appeared in the browser and shows the correct status.

### Test Card Numbers

Use these Luhn-valid test numbers (not real card numbers):

| Number | Expected Result |
|---|---|
| `4111111111111111` | Valid (Luhn passes, 16 digits) |
| `4111111111111112` | Luhn fail |
| `1234` | Format fail (card_last_four: passes; full_card_number: Luhn fail) |

---

## Post-Deployment Verification Checklist

- [ ] RSA key pair generated and private key stored in Secrets Manager
- [ ] Public key added to Amazon Connect Security Keys; Key ID noted
- [ ] CloudFormation stack status is `CREATE_COMPLETE`
- [ ] All four Lambda functions exist and have a `prod` alias
- [ ] Lambda Layer `aria-dtmf-dependencies` is attached to decrypt and validate Lambdas
- [ ] Connect resource-based policies on `:prod` alias of decrypt and validate Lambdas
- [ ] `dtmf_active_sessions` and `aria-card-bins` DynamoDB tables exist
- [ ] API Gateway endpoints `/dtmf-status` and `/dtmf-active` return HTTP 200 (or 404 with JSON body if no active session)
- [ ] S3 bucket exists with `dtmf-panel/index.html` and `dtmf-launcher/index.html`
- [ ] CloudFront distribution status is `Deployed`
- [ ] Launcher URL loads without errors in Chrome
- [ ] Test call successfully triggers DTMF capture and validates
- [ ] Agent panel appears and shows correct status
- [ ] Panel auto-resets to idle after 15 seconds
- [ ] CloudWatch Log Groups exist for all four Lambdas
- [ ] DynamoDB session record TTL is set correctly (check `ttl` attribute is a Unix timestamp ~2 hours in future)
- [ ] No full card digits appear anywhere in logs (verify with CloudWatch Logs Insights query)

### CloudWatch Logs Insights — Verify No Card Digits in Logs

```
fields @timestamp, @message
| filter @logStream like /aria-dtmf-decrypt/
| filter @message like /\d{13,19}/
| sort @timestamp desc
| limit 20
```

This query should return **zero results**. Any result indicates a logging configuration error.

---

## Operations

### DynamoDB Stale Session Cleanup

DynamoDB TTL automatically removes sessions after `SessionTTLHours`. For immediate cleanup (e.g. after testing or a stuck session):

```bash
aws dynamodb delete-item \
  --table-name dtmf_active_sessions \
  --key '{"session_id":{"S":"ACTIVE"}}' \
  --region eu-west-2
```

### Lambda Log Groups

| Lambda | Log Group |
|---|---|
| `aria-dtmf-decrypt` | `/aws/lambda/aria-dtmf-decrypt` |
| `aria-dtmf-validate` | `/aws/lambda/aria-dtmf-validate` |
| `aria-dtmf-start-session` | `/aws/lambda/aria-dtmf-start-session` |
| `aria-dtmf-status-proxy` | `/aws/lambda/aria-dtmf-status-proxy` |

### Key Metrics to Monitor

| Metric | Service | Alarm Threshold |
|---|---|---|
| Lambda errors | CloudWatch | > 0 errors in 5 min window |
| Lambda duration | CloudWatch | p95 > 5000ms |
| DynamoDB throttled requests | CloudWatch | > 0 in 5 min window |
| Secrets Manager API calls | CloudWatch | Spike > baseline × 3 |
| CloudFront 4xx/5xx rate | CloudWatch | > 1% of requests |
| API Gateway 5xx | CloudWatch | > 0 in 5 min window |

### Recommended CloudWatch Alarms

```bash
# Lambda decrypt errors
aws cloudwatch put-metric-alarm \
  --alarm-name dtmf-decrypt-errors \
  --metric-name Errors \
  --namespace AWS/Lambda \
  --dimensions Name=FunctionName,Value=aria-dtmf-decrypt \
  --statistic Sum --period 300 --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --evaluation-periods 1 \
  --alarm-actions arn:aws:sns:eu-west-2:123456789012:dtmf-alerts
```

Repeat for each Lambda function.

### Key Rotation Procedure

Rotate the RSA key pair periodically (recommended: annually, or on suspicion of compromise). See [`key-management-guide.md`](key-management-guide.md) for the full procedure.

Quick summary:
1. Generate a new key pair: `bash scripts/setup_dtmf_keys.sh --rotate`
2. Add the new public key to Amazon Connect Security Keys (keep the old key active).
3. Update the `PRIVATE_KEY_SECRET_ARN` environment variable on the decrypt Lambda.
4. Wait for all in-flight calls using the old key to complete (typically < 5 minutes).
5. Remove the old key from Amazon Connect Security Keys.
6. Delete the old Secrets Manager secret.

---

## Troubleshooting

| Symptom | Likely Cause | Resolution |
|---|---|---|
| Agent panel does not appear | Popup blocked by browser | Guide agent to allow popups from the CloudFront domain; refresh launcher |
| Panel shows "Awaiting trigger..." indefinitely | `aria-dtmf-start-session` Lambda error, or DynamoDB PutItem failed | Check `/aws/lambda/aria-dtmf-start-session` CloudWatch Logs; verify DynamoDB table name in Lambda env vars |
| `ImportModuleError: No module named 'aws_encryption_sdk'` | Lambda Layer not attached or wrong architecture | Re-run `deploy_dtmf_lambda.sh deploy`; ensure layer is built for `manylinux2014_x86_64` |
| `404 Not Found` from `/dtmf-status` or `/dtmf-active` | API Gateway route not configured or Lambda integration missing | Check API Gateway console; verify `aria-dtmf-status-proxy` Lambda integration is attached to both routes |
| Status stuck at `decrypting` | `aria-dtmf-decrypt` Lambda failed or timed out | Check decrypt Lambda logs; verify `PRIVATE_KEY_SECRET_ARN` and `CONNECT_KEY_ID` env vars match |
| Status stuck at `validating` | `aria-dtmf-validate` Lambda error | Check validate Lambda logs; verify Connect instance ARN in `CONNECT_INSTANCE_ARN` env var |
| Stale `ACTIVE` session visible | Previous test session not cleaned up | Run the manual DynamoDB delete command above, or wait for TTL expiry |
| Panel does not reset after validation | Panel JS `autoReset` timer not firing | Clear browser cache; ensure panel HTML was uploaded to the correct S3 path |
| `ResourceNotFoundException` on DynamoDB GetItem | Table name mismatch between Lambda env var and actual table | Check Lambda environment variables vs. CloudFormation stack outputs |
| `AccessDeniedException` on Secrets Manager | Lambda IAM role missing `secretsmanager:GetSecretValue` | Check `aria-dtmf-decrypt-role` IAM policy; verify the secret ARN matches |
| `AccessDeniedException` on KMS | KMS key policy does not allow Lambda role | Add `aria-dtmf-decrypt-role` to the KMS key policy's `kms:Decrypt` statement |
| `AccessDeniedException` from Connect on UpdateContactAttributes | Validate Lambda role missing permission or wrong instance ARN | Verify `connect:UpdateContactAttributes` in `aria-lambda-dtmf-validate-role` policy |
| BIN check always passes even for unknown BINs | `aria-card-bins` table is empty | Populate with BIN records per Step 5; if BIN check is intentionally skipped, set `EnableBinCheck=false` |
| Panel shows garbled masked value | Contact attribute `dtmf_masked_value` contains unexpected characters | Check validate Lambda output; verify `maskedValue` is set correctly for the collection purpose |
| Connect flow fails at Lambda block | Lambda not added to Connect instance allowed Lambda list | In Connect console → Your instance → Flows → AWS Lambda → add each Lambda ARN |
