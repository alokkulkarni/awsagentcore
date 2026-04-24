# Key Management Guide: Secure DTMF Capture for Amazon Connect

> **Product:** Secure DTMF Capture for Amazon Connect  
> **Version:** 1.0  
> **Audience:** Security engineers, platform engineers, compliance teams

---

## 1. RSA Key Pair Role

### Why RSA?

Amazon Connect's "Store customer input" block supports **RSA public-key encryption** for DTMF digits. This is the only encryption mechanism Connect provides for in-flow digit capture. RSA was chosen because:

1. **Asymmetric encryption** — the public key (held by Connect) can only encrypt; it cannot decrypt. Even if an attacker obtained the public key, they could not recover plaintext digits.
2. **No shared secret** — the private key never needs to be distributed to Connect, reducing the blast radius of a key compromise.
3. **AWS native support** — the AWS Encryption SDK's `RawMasterKey` provider supports the exact padding scheme Connect uses.

### Algorithm and Padding

Connect uses:
```
RSA/ECB/OAEPWithSHA-512AndMGF1Padding
```

This translates to:
- **RSA-OAEP** (Optimal Asymmetric Encryption Padding)
- **SHA-512** as the hash function for OAEP
- **MGF1** (Mask Generation Function 1) with SHA-512
- **2048-bit** key size (minimum required by Connect)

### Why 2048-bit?

- Amazon Connect requires a minimum of 2048-bit RSA keys.
- 2048-bit provides ~112 bits of security, sufficient for the intended purpose (short-lived per-call encryption of digit sequences).
- The digits are ephemeral — they exist in Lambda memory for milliseconds. Long-term key strength is less critical than key rotation cadence.
- 4096-bit keys are also supported if your security policy requires them; increase key size in the `openssl genrsa` command.

---

## 2. Initial Key Setup

### Prerequisite

OpenSSL 1.1.1 or later must be installed. Verify:
```bash
openssl version
# OpenSSL 3.x.x ...
```

### Run the Setup Script

```bash
cd /path/to/awsagentcore
bash scripts/setup_dtmf_keys.sh
```

### What the Script Does

1. Generates a 2048-bit RSA private key in PEM format:
   ```bash
   openssl genrsa -out dtmf_private.pem 2048
   ```
2. Extracts the public key:
   ```bash
   openssl rsa -in dtmf_private.pem -pubout -out dtmf_public.pem
   ```
3. Creates a KMS Customer Managed Key (CMK) with an alias.
4. Stores the private key PEM in AWS Secrets Manager, encrypted by the CMK:
   ```bash
   aws secretsmanager create-secret \
     --name aria/dtmf-private-key \
     --kms-key-id alias/aria-dtmf-cmk \
     --secret-string file://dtmf_private.pem
   ```
5. Deletes the local private key file.
6. Prints the public key PEM and the Secrets Manager ARN.

### Manual Steps (if not using the script)

```bash
# 1. Generate key pair
openssl genrsa -out dtmf_private.pem 2048
openssl rsa -in dtmf_private.pem -pubout -out dtmf_public.pem

# 2. Create KMS CMK
KMS_ARN=$(aws kms create-key \
  --description "DTMF Secure Capture CMK" \
  --key-usage ENCRYPT_DECRYPT \
  --query KeyMetadata.Arn --output text)

aws kms create-alias --alias-name alias/aria-dtmf-cmk --target-key-id "$KMS_ARN"

# 3. Store private key in Secrets Manager
SECRET_ARN=$(aws secretsmanager create-secret \
  --name aria/dtmf-private-key \
  --kms-key-id "$KMS_ARN" \
  --secret-string file://dtmf_private.pem \
  --query ARN --output text)

# 4. Delete local private key
rm dtmf_private.pem

echo "Secret ARN: $SECRET_ARN"
cat dtmf_public.pem
```

---

## 3. Private Key Storage

### Secrets Manager

The RSA private key is stored as a plaintext PEM string in AWS Secrets Manager. Secrets Manager applies envelope encryption:

```
Private Key PEM (plaintext)
        ↓
Encrypted by KMS CMK (AES-256 data key)
        ↓
Stored in Secrets Manager (ciphertext)
```

The KMS CMK is a Customer Managed Key — **you control the key policy**, the rotation schedule, and who can use it.

### Access Pattern

The `aria-dtmf-decrypt` Lambda fetches the secret via `secretsmanager:GetSecretValue`. Secrets Manager calls KMS to decrypt the data key, decrypts the secret, and returns the plaintext PEM to Lambda in memory over TLS.

```python
# Simplified internal pattern
client = boto3.client('secretsmanager')
response = client.get_secret_value(SecretId=PRIVATE_KEY_SECRET_ARN)
private_key_pem = response['SecretString'].encode()
# Private key now in Lambda memory — used immediately, not persisted
```

### In-Memory Caching

The Lambda caches the private key PEM in a module-level variable across warm invocations. This reduces Secrets Manager API calls and improves performance. The cache is cleared when the Lambda execution environment is recycled (typically after 15 minutes of inactivity, or after a code update).

If you need to force cache eviction immediately (e.g. after key rotation), update the Lambda function configuration (e.g. bump an environment variable) to force a new execution environment.

### Rotation Policy Recommendations

| Scenario | Recommended Rotation Cadence |
|---|---|
| Standard deployment | Annually |
| High-security / PCI scope | 90 days |
| Suspected key compromise | Immediately |
| Personnel change (key admin leaves) | Within 30 days |

---

## 4. Public Key in Amazon Connect

### Adding the Key

1. Navigate to Amazon Connect console → your instance → **Security keys**.
2. Click **Add key**.
3. Paste the full public key PEM (including `-----BEGIN PUBLIC KEY-----` / `-----END PUBLIC KEY-----` lines).
4. Amazon Connect validates the key format and returns a **Key ID** (UUID).

### Key ID Usage

The Key ID returned by Connect is used in two places:

1. **`CONNECT_KEY_ID` environment variable** on the `aria-dtmf-decrypt` Lambda — tells the decrypt Lambda which key was used for encryption (for validation).
2. **"Store customer input" block** in the contact flow — select the key by its ID from the dropdown.

### What Happens If You Delete the Key?

- Any call currently **mid-capture** (in the "Store customer input" block) will encrypt with the selected key. If that key is deleted before the decrypt Lambda runs, decryption will fail.
- Any calls that have **already completed capture** and are awaiting the decrypt Lambda invocation will fail decryption.
- Future calls will fail at the "Store customer input" block (Connect cannot encrypt without the key).

**Never delete a Connect Security Key without first verifying no calls are in progress that use it.** During key rotation, keep the old key active for at least 5 minutes after adding the new one.

---

## 5. Key Rotation Procedure

Key rotation replaces the RSA key pair without service interruption. The old key remains valid for in-flight calls during the transition window.

### Step-by-Step Rotation

**Phase 1: Generate New Key Pair**

```bash
bash scripts/setup_dtmf_keys.sh --rotate
```

The `--rotate` flag generates a new key pair and stores the new private key in Secrets Manager under a new secret name (e.g. `aria/dtmf-private-key-v2`). The old secret is not yet deleted.

Note the new:
- `NewPrivateKeySecretArn`
- New public key PEM

**Phase 2: Add New Public Key to Amazon Connect**

1. In Connect console → Security keys → **Add key**.
2. Paste the new public key PEM.
3. Note the new **Key ID** (UUID).

At this point, **both the old and new keys are active** in Connect. No service disruption.

**Phase 3: Update the Decrypt Lambda**

Update the Lambda environment variable to point to the new secret, and update the key ID:

```bash
aws lambda update-function-configuration \
  --function-name aria-dtmf-decrypt \
  --region eu-west-2 \
  --environment "Variables={
    PRIVATE_KEY_SECRET_ARN=arn:aws:secretsmanager:...:secret:aria/dtmf-private-key-v2-...,
    CONNECT_KEY_ID=<new-key-id>
  }"
```

Publish a new version and move the `prod` alias:

```bash
VERSION=$(aws lambda publish-version --function-name aria-dtmf-decrypt --query Version --output text)
aws lambda update-alias --function-name aria-dtmf-decrypt --name prod --function-version "$VERSION"
```

**Phase 4: Update Contact Flows**

In each contact flow's "Store customer input" block, change the selected Security Key to the new Key ID. Save and publish each flow.

**Phase 5: Transition Window**

Wait **at least 5 minutes** after publishing the updated contact flows. During this window:
- New calls use the new key (encrypted with new public key, decrypted with new private key).
- In-flight calls that started before the flow update use the old key.

The decrypt Lambda now uses the new private key. If an old in-flight call tries to decrypt with the old ciphertext, it will fail (because the Lambda now uses the new private key). This is an acceptable brief disruption; the contact flow should handle decrypt failures gracefully with a retry prompt.

For zero-disruption rotation, deploy a temporary Lambda version that tries the new key first and falls back to the old key for a 5-minute window. This is an advanced pattern — see `key-management-guide.md` advanced section for details.

**Phase 6: Verify**

```bash
# Place a test call and confirm decryption succeeds with new key
aws logs tail /aws/lambda/aria-dtmf-decrypt --follow --region eu-west-2
# Look for "status": "success" in recent logs
```

**Phase 7: Remove Old Key**

1. In Connect console → Security keys → select old key → **Remove**.
2. Delete the old Secrets Manager secret:
   ```bash
   aws secretsmanager delete-secret \
     --secret-id arn:aws:secretsmanager:...:secret:aria/dtmf-private-key-AbCdEf \
     --recovery-window-in-days 7
   ```
   Use `--recovery-window-in-days 7` to allow a 7-day recovery window in case you need to roll back.

---

## 6. Access Control

### Who Can Read the Private Key

**Only** the `aria-dtmf-decrypt` Lambda execution role (`aria-dtmf-decrypt-role`) should have `secretsmanager:GetSecretValue` on the private key secret.

Verify no other principals have access:

```bash
aws secretsmanager get-resource-policy \
  --secret-id arn:aws:secretsmanager:...:secret:aria/dtmf-private-key-AbCdEf
```

If no resource policy is returned, access is controlled entirely by IAM identity policies. Verify that no other roles or users have been granted access.

### KMS Key Policy

The KMS CMK key policy should follow the principle of least privilege:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "Enable IAM User Permissions",
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws:iam::123456789012:root"},
      "Action": "kms:*",
      "Resource": "*"
    },
    {
      "Sid": "Allow Decrypt Lambda to use key",
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws:iam::123456789012:role/aria-dtmf-decrypt-role"},
      "Action": ["kms:Decrypt", "kms:DescribeKey"],
      "Resource": "*"
    },
    {
      "Sid": "Allow DynamoDB SSE",
      "Effect": "Allow",
      "Principal": {"Service": "dynamodb.amazonaws.com"},
      "Action": ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"],
      "Resource": "*"
    },
    {
      "Sid": "Allow Secrets Manager",
      "Effect": "Allow",
      "Principal": {"Service": "secretsmanager.amazonaws.com"},
      "Action": ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"],
      "Resource": "*"
    }
  ]
}
```

**Explicitly deny** `kms:Decrypt` for all other principals using an explicit Deny statement if your security policy requires it.

### IAM Role Trust Boundary

The `aria-dtmf-decrypt-role` trust policy should only trust Lambda:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"Service": "lambda.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }
  ]
}
```

Do not add human IAM users or other service principals to this trust policy.

---

## 7. Audit and Compliance

### CloudTrail Events

All access to the private key generates CloudTrail events. Key events to monitor:

| Event | CloudTrail Event Name | Service | What it means |
|---|---|---|---|
| Secret accessed | `GetSecretValue` | `secretsmanager.amazonaws.com` | Lambda fetched the private key (expected during calls) |
| Secret access attempt denied | `GetSecretValue` (with `errorCode`) | `secretsmanager.amazonaws.com` | Unauthorised access attempt |
| KMS key used for decrypt | `Decrypt` | `kms.amazonaws.com` | Secrets Manager decrypted data key (expected) |
| KMS key policy modified | `PutKeyPolicy` | `kms.amazonaws.com` | Key policy change — should be rare; alert on this |
| Connect Security Key added | `CreateInstanceStorageConfig` | `connect.amazonaws.com` | New public key added |
| Connect Security Key removed | `DeleteInstanceStorageConfig` | `connect.amazonaws.com` | Public key removed — alert on unexpected removal |

### CloudTrail Log Insights Query — Monitor Secret Access

```sql
fields eventTime, userIdentity.arn, sourceIPAddress, errorCode
| filter eventSource = "secretsmanager.amazonaws.com"
| filter eventName = "GetSecretValue"
| filter requestParameters.secretId like /aria\/dtmf-private-key/
| sort eventTime desc
```

Expected callers: only the `aria-dtmf-decrypt` Lambda role. Any other caller is anomalous.

### KMS Key Usage Metrics

Monitor KMS `Decrypt` API call volume in CloudWatch:

```bash
aws cloudwatch get-metric-statistics \
  --namespace AWS/KMS \
  --metric-name NumberOfRequestsSucceeded \
  --dimensions Name=KeyId,Value=<CMK-ID> \
  --start-time 2025-01-01T00:00:00Z \
  --end-time 2025-01-02T00:00:00Z \
  --period 3600 \
  --statistics Sum
```

Baseline this against your expected call volume. A spike significantly above baseline may indicate an attack or misconfiguration.

### Connect Security Key Audit

Amazon Connect does not yet provide a dedicated audit log for Security Key usage per call. To audit which calls used DTMF encryption:
- Filter Connect contact records (Contact Trace Records) for calls where the contact flow included a "Store customer input" block.
- Cross-reference with CloudTrail `GetSecretValue` events by timestamp.

---

## 8. PCI DSS Considerations

This section describes how the solution supports PCI DSS compliance objectives. **This is not a complete PCI DSS compliance assessment.** Buyers are responsible for their own PCI DSS audit and must engage a Qualified Security Assessor (QSA).

### How This Solution Helps

| PCI DSS Requirement | How the Solution Addresses It |
|---|---|
| Req 3.3: Do not store sensitive authentication data after authorisation | Full card digits are never stored. Only `bin` and `lastFour` are retained. |
| Req 3.4: Render PAN unreadable | The only PAN-derived values stored are the masked value (`****4567`) and the BIN (not PAN). |
| Req 3.5: Protect keys used to secure stored cardholder data | RSA private key protected by KMS CMK; access restricted to single Lambda role. |
| Req 3.6: Key management procedures | Key rotation procedure documented; CloudTrail audit of all key access. |
| Req 4.1: Use strong cryptography for transmission | All data transmitted over TLS 1.2+. DTMF encrypted with RSA-OAEP-SHA512 before transmission. |
| Req 7: Restrict access to system components | IAM least-privilege; only decrypt Lambda can access private key; only validate Lambda writes contact attributes. |
| Req 10: Log all access to system components | CloudTrail captures all Secrets Manager, KMS, and Lambda API calls. |

### Scope Reduction

Because full card digits never enter any AWS storage service, database, or log in cleartext, the PCI DSS scope of this solution is significantly reduced compared to traditional IVR implementations. The components that handle encrypted or masked data only are generally outside PCI scope.

**Components that may be in scope** (depending on your QSA assessment):
- `aria-dtmf-decrypt` Lambda (transiently holds cleartext in memory)
- The Secrets Manager secret (holds the private key)
- The KMS CMK (controls access to the private key)
- Amazon Connect itself (handles encrypted DTMF audio)

**Components typically out of scope:**
- `aria-dtmf-validate` Lambda (never receives full card number)
- `aria-dtmf-status-proxy` Lambda (handles masked values only)
- DynamoDB tables (session metadata and BINs — no cardholder data)
- CloudFront / S3 panel (displays masked values only)
- API Gateway (proxies masked values only)

### Buyer Responsibilities

1. Ensure your Amazon Connect instance is operating in a PCI-compliant configuration.
2. Ensure your AWS account and VPC configurations meet PCI DSS network segmentation requirements.
3. Complete a PCI DSS assessment with a QSA for your full card processing environment.
4. This solution does **not** make your environment PCI-compliant by itself — it is a component that supports scope reduction.
5. Review the [AWS PCI DSS Compliance Package](https://aws.amazon.com/compliance/pci-dss-level-1-faqs/) for AWS-side compliance coverage.
