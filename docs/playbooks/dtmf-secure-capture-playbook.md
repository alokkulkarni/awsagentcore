# DTMF Secure Capture (Marketplace) Playbook

## Document Control

| Field | Value |
| --- | --- |
| Document ID | PLY-DTMF-001 |
| Version | 1.0 |
| Owner | Platform Engineering + Security Officer |
| Date | 2026-05-25 |
| Classification | CONFIDENTIAL |
| Component | DTMF Secure Capture (Marketplace) |

## 1. Purpose and Scope

This playbook defines the standard deployment, governance, and operational control model for the DTMF Secure Capture marketplace component in `awsagentcore`.

The component provides PCI DSS-aligned, RSA-encrypted DTMF keypad capture for Amazon Connect. Digits are encrypted at the moment of DTMF capture before any application software reads them. The solution includes:
- 4 Lambda functions: `aria-dtmf-start-session`, `aria-dtmf-decrypt`, `aria-dtmf-validate`, and `aria-dtmf-status-proxy`
- A DynamoDB active sessions table for contact/session state
- An agent browser panel and launcher delivered through CloudFront-backed static assets
- 8 built-in collection purposes: `full_card_number`, `card_last_four`, `ssn`, `account_number`, `sort_code`, `cvv`, `pin`, `generic`
- Luhn and optional BIN validation for card-related capture
- A pluggable ownership-verification Lambda integration for customer/card matching

This playbook applies to staging and production deployments, operational changes, key rotation, incident handling, rollback, and post-deployment validation.

## 2. Component Overview

Amazon Connect uses the **Store customer input** block with RSA encryption enabled and a public key stored in the Connect security-key slot to encrypt digits before they leave the contact flow. The application then processes only encrypted or masked values except for transient cleartext handling inside the decrypt Lambda.

### Runtime roles
1. **`aria-dtmf-start-session`** initialises the session, writes the active record to DynamoDB, and sets `dtmf_status=awaiting_trigger` on the contact.
2. **`aria-dtmf-decrypt`** decrypts ciphertext using the RSA private key from AWS Secrets Manager.
3. **`aria-dtmf-validate`** performs Luhn checks, optional BIN validation, and optional ownership verification.
4. **`aria-dtmf-status-proxy`** is polled by the agent panel every 2 seconds and returns masked status data.

### Security model
- Full PAN must never be stored.
- Only BIN (first 6) and `lastFour` may be retained for card workflows.
- The private key lives only in Secrets Manager and is KMS-encrypted at rest.
- Cleartext digits exist only transiently in Lambda memory during decryption.
- The browser panel receives masked values and status only.

## 3. Prerequisites

Required before deployment:
- OpenSSL
- AWS Secrets Manager
- AWS KMS
- Amazon Connect security-key slot / security key registration capability
- Python 3.12+
- AWS CLI v2
- CloudFormation capability `CAPABILITY_NAMED_IAM`

Recommended access:
- IAM permissions for Lambda, DynamoDB, CloudFormation, API Gateway, S3, CloudFront, KMS, Secrets Manager, CloudWatch Logs, and Amazon Connect
- Change approval from the Security Officer before any production rollout

## 4. Deployment Strategy

Deployment sequence is **strict** and cannot be reordered.

1. **Generate RSA key pair** using `setup_dtmf_keys.sh` (`setup` for first-time deployment, `rotate` for planned rotation).
2. **Add the public key to Amazon Connect** and copy the Connect Key ID.
3. **Deploy the CloudFormation stack** from `marketplace/cloudformation/dtmf-secure-capture.yaml` with all required parameters.
4. **Deploy the Lambda functions and panel assets** using `deploy_dtmf_lambda.sh` (`deploy` for the standard path).
5. **Import the contact flow** from `marketplace/contact-flows/` and bind Lambda aliases.
6. **Run end-to-end testing** with simulated DTMF input only.

### Deployment rules
- Never deploy production changes out of sequence.
- Never use real PANs in non-production testing.
- Contact flows must reference Lambda aliases, not `$LATEST`.
- Do not remove the old RSA key until the new path is verified.

## 5. Environment Matrix

| Environment | Purpose | Data Policy | PCI DSS Scope | Notes |
| --- | --- | --- | --- | --- |
| staging | Validation, rehearsals, integration testing | Synthetic test cards only, **never** real PANs | Reduced / pre-production | Use isolated Connect flows and isolated Secrets Manager secret |
| production | Live customer DTMF capture | Live DTMF data | In scope for PCI DSS controls | Requires approved change window and Security Officer sign-off |

### Standard environment variables

| Variable | Purpose |
| --- | --- |
| `AWS_REGION` | Target AWS region |
| `CONNECT_INSTANCE_ID` | Amazon Connect instance UUID |
| `DTMF_PRIVATE_KEY_SECRET_ARN` | Secrets Manager ARN for RSA private key |
| `DTMF_KMS_KEY_ARN` | KMS key ARN protecting the private key secret |
| `DTMF_CONNECT_KEY_ID` | Amazon Connect key ID used by encrypted DTMF capture |
| `STACK_SUFFIX` | Stack/environment suffix such as `staging` or `prod` |

## 6. Change Management

| Change Type | Classification | Requirements |
| --- | --- | --- |
| RSA key rotation | Major | Security Officer sign-off, planned maintenance window, no active calls, rollback plan required |
| CloudFormation parameter changes | Normal | Standard review, stack change review, pre-prod validation |
| Lambda code changes | Standard | Code review, deployment validation, log audit after release |

### Mandatory change controls
- RSA key rotation must not occur during active calls.
- Contact Centre Operations must be informed before Connect flow updates.
- Any scope-affecting security change must trigger PCI DSS review.

## 7. Risk Register

| ID | Risk | Probability | Impact | Mitigation | Owner |
| --- | --- | --- | --- | --- | --- |
| R-01 | Private key leaked to logs | Low | CRITICAL | Never print `SecretString`; use structured logging; Lambda environment variables must never contain key material | Security Officer |
| R-02 | RSA key rotation mid-active-call | Low | CRITICAL | Rotate only in a maintenance window; confirm no active sessions in DynamoDB before rotation | Platform Engineering |
| R-03 | Connect security key ID mismatch | Medium | HIGH | Validate the Connect key ID before deploy and before flow publish | Platform Engineering |
| R-04 | Full PAN persisted accidentally | Low | CRITICAL | Code review gate; validate Lambda contracts; only BIN and `lastFour` may be retained | Security Officer |
| R-05 | DynamoDB session TTL too short | Medium | MEDIUM | Review `SessionTTLHours` during deployment and confirm terminal-state visibility during testing | Platform Engineering |
| R-06 | Status proxy polling causes throttle | Low | LOW | Apply Lambda concurrency limits and add buffering/queueing if scale demands it | Platform Engineering |
| R-07 | BIN table empty | Medium | LOW | `EnableBINValidation=false` by default; populate BIN table before card-validation go-live | Product / Platform |

## 8. Rollback Strategy

### Lambda rollback
- Roll back Lambda aliases with `aws lambda update-alias` to the last known-good version.
- Rebind contact flows only to stable alias ARNs.

### CloudFormation rollback
- Use standard CloudFormation rollback or stack update rollback.
- Capture stack outputs before changes so panel/API URLs can be restored.

### RSA key rollback
- Keep the previous Secrets Manager version and/or prior secret active until the new key is proven.
- Repoint the decrypt Lambda environment to the previous secret/key reference.
- Repoint the decrypt alias to the last known-good version if needed.
- In Amazon Connect, do **not** delete the old key until the new key is confirmed working.

## 9. Communication Plan

| Trigger | Audience | Requirement |
| --- | --- | --- |
| Any DTMF deployment | Security Officer | **Mandatory notification** before execution |
| PCI DSS scope change | PCI DSS QSA | **Mandatory notification** and assessment alignment |
| Connect flow changes | Contact Centre Ops | Notify at least 48 hours before production change |
| Rollback or incident | Platform Engineering, Security Officer, Contact Centre Ops | Immediate update with impact and ETA |

## 10. Success Criteria

A deployment is successful only when all of the following are true:
- Session creation returns a valid `sessionId`
- `aria-dtmf-decrypt` returns only safe derived fields such as `{bin, lastFour, digitCount}` and never a full PAN
- The agent panel shows validation status within 6 seconds of capture completion
- CloudWatch logs contain zero instances of raw digit strings
- Contact flows use the intended Connect key ID and Lambda aliases

## 11. Post-Deployment Validation

Perform all checks before handoff:
- Confirm stack status is healthy and outputs are recorded
- Confirm all 4 Lambda functions are deployed and reachable
- Confirm `/dtmf-active` and `/dtmf-status` return expected JSON
- Confirm the launcher and panel load via CloudFront
- Run an end-to-end test using only simulated/test DTMF values
- Confirm status transitions complete in the agent panel
- Confirm only masked values are visible to the browser and contact attributes

### Mandatory PAN audit

After every deployment, search CloudWatch logs for possible 13-19 digit strings to confirm PANs are not logged. The audit must cover, at minimum:
- `/aws/lambda/aria-dtmf-decrypt`
- `/aws/lambda/aria-dtmf-validate`
- `/aws/lambda/aria-dtmf-start-session`
- `/aws/lambda/aria-dtmf-status-proxy`

Any match is a Sev-1 security incident until disproven.

## 12. Contacts and Escalation

| Level | Role | Responsibility |
| --- | --- | --- |
| L1 | Security Officer | Primary security approver, incident owner for key/PAN exposure concerns |
| L2 | Platform Engineering | Deployment execution, rollback, Lambda/API/DynamoDB triage |
| L3 | Contact Centre Ops | Flow validation, agent workspace readiness, operational communications |
| L4 | PCI DSS QSA contact | PCI scope review, compliance interpretation, post-incident consultation |

Escalate immediately for suspected key compromise, PAN exposure, Connect encryption-key mismatch, or repeated decrypt failures.

## 13. Approvals

Production deployment requires the following explicit approvals:
- [ ] Platform Engineering lead
- [ ] Contact Centre Operations representative
- [ ] **Security Officer sign-off REQUIRED**
- [ ] PCI DSS QSA notified if scope or control posture changes
