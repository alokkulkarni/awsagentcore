# Quick Start: Secure DTMF Capture for Amazon Connect

> **Estimated time:** 15 minutes (assumes AWS CLI configured and Connect instance exists)

---

## Before You Begin

Confirm you have:
- [ ] AWS CLI v2 configured with admin credentials (`aws sts get-caller-identity`)
- [ ] An Amazon Connect instance ID (UUID)
- [ ] Python 3.12+, OpenSSL, zip, and bash installed
- [ ] Chrome or Edge browser for agent testing

---

## Step 1 — Generate the RSA Key Pair

Run from the repository root:

```bash
bash scripts/setup_dtmf_keys.sh
```

When prompted, enter:
- **Region:** your AWS region (e.g. `eu-west-2`)
- **Secret name:** `aria/dtmf-private-key`
- **KMS alias:** `alias/aria-dtmf-cmk`

**Save the output.** You need:
```
PrivateKeySecretArn: arn:aws:secretsmanager:<region>:<account>:secret:aria/dtmf-private-key-XXXXXX
KmsKeyArn:           arn:aws:kms:<region>:<account>:key/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA...
-----END PUBLIC KEY-----
```

---

## Step 2 — Add Public Key to Amazon Connect

1. Open [Amazon Connect Console](https://console.aws.amazon.com/connect/) → your instance
2. Left nav → **Security keys**
3. Click **Add key**
4. Paste the full `-----BEGIN PUBLIC KEY-----` ... `-----END PUBLIC KEY-----` block
5. Click **Add**
6. **Copy the Key ID** shown (UUID format, e.g. `a1b2c3d4-e5f6-7890-abcd-ef1234567890`)

---

## Step 3 — Deploy the CloudFormation Stack

```bash
aws cloudformation deploy \
  --template-file marketplace/cloudformation/dtmf-secure-capture.yaml \
  --stack-name dtmf-secure-capture-prod \
  --region eu-west-2 \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    ConnectInstanceId=<your-connect-instance-id> \
    ConnectInstanceArn=arn:aws:connect:eu-west-2:<account-id>:instance/<your-connect-instance-id> \
    ConnectKeyId=<key-id-from-step-2> \
    PrivateKeySecretArn=<PrivateKeySecretArn-from-step-1> \
    KmsKeyArn=<KmsKeyArn-from-step-1> \
    Environment=prod
```

Wait ~5–8 minutes for `CREATE_COMPLETE`. Then **note the stack outputs:**

```bash
aws cloudformation describe-stacks \
  --stack-name dtmf-secure-capture-prod \
  --region eu-west-2 \
  --query 'Stacks[0].Outputs' \
  --output table
```

You need: `CloudFrontDomain`, `ApiGatewayUrl`, `SessionsTableName`, `BinsTableName`.

---

## Step 4 — Upload Lambda Code and Panel HTML

```bash
bash scripts/deploy_dtmf_lambda.sh deploy
```

Enter the values from Steps 1–3 when prompted. The script:
- Packages and deploys all 4 Lambda functions
- Builds the Python dependencies layer (`cryptography`, `aws-encryption-sdk`)
- Publishes a `prod` alias for each Lambda
- Uploads `dtmf-panel/index.html` and `dtmf-launcher/index.html` to S3

Deployment takes ~3–5 minutes.

---

## Step 5 — Import a Contact Flow

1. Open Amazon Connect console → your instance → **Contact flows**
2. Click **Create contact flow** → **Import flow (beta)**
3. Upload `marketplace/contact-flows/ARIA-DTMF-SecureCollection.json`
4. In each **Invoke AWS Lambda function** block, update the Lambda ARN:
   - Start session: `arn:aws:lambda:<region>:<account>:function:aria-dtmf-start-session:prod`
   - Decrypt: `arn:aws:lambda:<region>:<account>:function:aria-dtmf-decrypt:prod`
   - Validate: `arn:aws:lambda:<region>:<account>:function:aria-dtmf-validate:prod`
5. Click **Save** then **Publish**

> **Tip:** Also import `ARIA-DTMF-CardCapture-Example.json` for a ready-made card number trigger flow.

---

## Step 6 — Add Launcher to Agent Workspace

1. Amazon Connect console → your instance → **Agent workspace** → **Third-party applications**
2. Click **Add application**
3. Fill in:
   - **Name:** `Secure DTMF Launcher`
   - **URL:** `https://<CloudFrontDomain>/dtmf-launcher/index.html`
   - **Namespace:** `dtmf_launcher`
4. **Save**

Also guide agents to allow popup windows from `https://<CloudFrontDomain>` in their browser.

---

## Step 7 — Test

1. **Place a test call** to your Connect instance
2. **Accept the call** in the CCP
3. **Trigger** the DTMF collection flow (click the configured Quick Connect or flow block)
4. **Enter `4111111111111111`** on the test phone keypad when prompted (Luhn-valid test number)
5. **Verify** the agent panel popup appears and shows `✅ Card Validated — ****1111`

**Check DynamoDB session:**
```bash
aws dynamodb get-item \
  --table-name dtmf_active_sessions \
  --key '{"session_id":{"S":"ACTIVE"}}' \
  --region eu-west-2
```

**Check Lambda logs:**
```bash
aws logs tail /aws/lambda/aria-dtmf-decrypt --follow --region eu-west-2
aws logs tail /aws/lambda/aria-dtmf-validate --follow --region eu-west-2
```

---

## Done ✅

Your secure DTMF capture solution is live. For next steps, see:

- [Full Deployment Guide](docs/deployment-guide.md) — operations, monitoring, troubleshooting
- [Configuration Reference](docs/configuration-reference.md) — all parameters and API schemas
- [Customisation Guide](docs/customisation-guide.md) — add purposes, rebrand panel, integrate your data
- [Key Management Guide](docs/key-management-guide.md) — key rotation and PCI guidance
