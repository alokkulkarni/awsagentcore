# Contact Flow Templates — Secure DTMF Capture for Amazon Connect

This guide covers everything you need to import, configure, and test the included contact flow templates for the Secure DTMF Capture product.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Importing Contact Flows](#2-importing-contact-flows)
   - [Via the Connect Console (recommended)](#21-via-the-connect-console)
   - [Via the AWS CLI](#22-via-the-aws-cli)
3. [Flow Templates — What Each One Does](#3-flow-templates)
4. [Post-Import Configuration](#4-post-import-configuration)
   - [Lambda Function ARNs](#41-lambda-function-arns)
   - [Prompt text blocks](#42-prompt-text-blocks)
   - [Set contact attributes block](#43-set-contact-attributes-block)
   - [Success branch destination](#44-success-branch-destination)
   - [Failure and timeout branch destinations](#45-failure-and-timeout-branch-destinations)
5. [Testing the Flow After Import](#5-testing-after-import)
6. [Reference — Lambda ARNs from CloudFormation Outputs](#6-lambda-arns-from-cloudformation-outputs)

---

## 1. Prerequisites

Before importing any flow template, confirm the following are complete:

| Step | What to verify |
|------|----------------|
| ✅ RSA key pair generated | `./scripts/generate-rsa-keypair.sh` ran successfully |
| ✅ Public key uploaded to Connect | Connect Console → Security Profiles → Security Keys → key appears with a Key ID |
| ✅ CloudFormation stack deployed | Stack status is `CREATE_COMPLETE` in CloudFormation |
| ✅ Lambda code deployed | `./scripts/deploy_dtmf_lambda.sh deploy` completed without errors |
| ✅ Lambda functions approved in Connect | All three Lambda ARNs added to Connect instance (see §6) |

To approve Lambda functions in Connect:
```
Connect Console → Your instance → Flows → AWS Lambda → Add function
```
Add all three ARNs: `DecryptLambdaArn`, `ValidateLambdaArn`, `StartSessionLambdaArn`.

---

## 2. Importing Contact Flows

### 2.1 Via the Connect Console

This is the simplest method and suitable for all environments.

1. Open the [Amazon Connect console](https://console.aws.amazon.com/connect/) and select your instance.
2. Click **Contact flows** in the left navigation, then **Create contact flow**.
3. In the flow designer, click the **dropdown arrow** next to the Save button (top right) and select **Import flow (beta)**.
4. Choose the `.json` file from `marketplace/contact-flows/` and click **Import**.
5. The flow is imported in a **draft** state — do not publish until you have completed post-import configuration (§4).
6. After configuration, click **Save** then **Publish**.

> **Important:** Each flow template must be imported and published individually. Do not attempt to bulk-import.

### 2.2 Via the AWS CLI

Use this method for CI/CD pipelines or scripted deployments.

```bash
# Set your instance ID (from CloudFormation parameter or Connect console)
INSTANCE_ID="your-connect-instance-uuid"
REGION="eu-west-2"

# Import a flow (replace FLOW_FILE with the target .json)
FLOW_FILE="marketplace/contact-flows/dtmf-full-card-number.json"
FLOW_NAME="DTMF Secure Card Capture"

aws connect create-contact-flow \
  --instance-id "${INSTANCE_ID}" \
  --name "${FLOW_NAME}" \
  --type CONTACT_FLOW \
  --content "$(cat "${FLOW_FILE}")" \
  --region "${REGION}"
```

The CLI returns a `ContactFlowId` and `ContactFlowArn`. Store these — you will need to reference flows from queue routing or other flows.

To update an existing flow (after editing):
```bash
aws connect update-contact-flow-content \
  --instance-id "${INSTANCE_ID}" \
  --contact-flow-id "${CONTACT_FLOW_ID}" \
  --content "$(cat "${FLOW_FILE}")" \
  --region "${REGION}"
```

---

## 3. Flow Templates

Each template handles a specific `collection_purpose`. They share a common structure: start session → play prompt → invoke Secure Input (DTMF) → invoke decrypt Lambda → invoke validate Lambda → branch on result.

### 3.1 `dtmf-full-card-number.json` — Full Payment Card Number

Captures a 13–19 digit PAN (Primary Account Number) using the Connect Secure Input block. After decryption, the `ValidateFunction` performs a Luhn algorithm check and, when `EnableBINValidation=true`, a BIN prefix lookup to identify card network and issuer. If a `CustomerDataLambdaArn` is configured, an ownership check verifies the card belongs to the authenticated customer. This flow is appropriate for payment journeys where the agent must confirm card identity without seeing the digits.

### 3.2 `dtmf-card-last-four.json` — Last Four Digits of Card

Captures exactly four digits representing the last four digits of a payment card. Used for card verification scenarios where the full PAN is already stored in the customer's record. The validate Lambda checks that the captured value is exactly four digits and, if a customer Lambda is configured, confirms they match the card on file. Luhn and BIN checks are skipped for this purpose since four digits alone are not sufficient for either check.

### 3.3 `dtmf-ssn.json` — Social Security Number (SSN)

Captures a 9-digit Social Security Number. The validate Lambda enforces exactly 9 digits and applies US SSN format checks (rejects all-zero area, group, or serial segments; rejects 078-05-1120 and similar known test SSNs). The collection purpose is passed as `ssn` in the contact attribute. This flow is intended for US identity verification journeys and should only be used in flows that already have an authenticated caller context.

### 3.4 `dtmf-account-number.json` — Bank Account Number

Captures a bank account number of 6–18 digits. The validate Lambda applies configurable length checks based on country context set in the contact attribute `accountNumberCountry` (defaults to GB if not set). For UK accounts, the expected length is 8 digits; for IBAN-style, up to 18. No checksum algorithm is applied by default. A customer Lambda can be used to verify the account number against a CRM record.

### 3.5 `dtmf-sort-code.json` — UK Sort Code

Captures exactly 6 digits representing a UK bank sort code, typically entered without hyphens. The validate Lambda checks the digit count is exactly 6 and validates the format against the UK Modulus Checking standard (if the BIN table has been extended with sort code ranges). The flow presents a prompt advising the caller to enter 6 digits without spaces or hyphens.

### 3.6 `dtmf-generic.json` — Generic / Custom Capture

A flexible template for capturing any sequence of digits that does not fall into a specific category — account PINs, reference numbers, loyalty card numbers, date of birth, etc. The validate Lambda applies only length constraints (configurable via the `minLength` and `maxLength` contact attributes). No checksum, BIN, or SSN format checks are performed. Use this template as a starting point for custom capture scenarios.

---

## 4. Post-Import Configuration

After importing a flow, you must configure the following blocks before publishing. Each configurable block is marked with a comment `# CONFIGURE HERE` in the flow JSON.

### 4.1 Lambda Function ARNs

Every flow invokes three Lambda functions. After import, the ARNs are set to placeholder values (`arn:aws:lambda:REGION:ACCOUNT:function:PLACEHOLDER`). Replace them with the actual ARNs from your CloudFormation stack outputs.

In the flow designer, click each **Invoke AWS Lambda function** block and update:

| Block label in flow | Lambda to use | CFN Output key |
|---------------------|---------------|----------------|
| Start DTMF Session | `aria-dtmf-start-session-<env>` | `StartSessionLambdaArn` |
| Decrypt DTMF Input | `aria-dtmf-decrypt-<env>` | `DecryptLambdaArn` |
| Validate DTMF Input | `aria-dtmf-validate-<env>` | `ValidateLambdaArn` |

To retrieve ARNs from the stack:
```bash
aws cloudformation describe-stacks \
  --stack-name your-stack-name \
  --query "Stacks[0].Outputs" \
  --output table \
  --region your-region
```

### 4.2 Prompt Text Blocks

Each flow contains **Play prompt** blocks that read text to the caller. The default text is a placeholder — update it to match your IVR tone, language, and compliance requirements.

Blocks to configure (identified by their label in the designer):

| Block label | Default placeholder text | What to change |
|-------------|--------------------------|----------------|
| `Intro Prompt` | "Please enter your [data type] using your keypad, followed by the hash key." | Rewrite to match your brand voice and add any required consent statement. |
| `Retry Prompt` | "We didn't receive a valid entry. Please try again." | Adjust retry wording; consider adding agent transfer option. |
| `Error Prompt` | "We were unable to capture your information. Please hold while we transfer you." | Update transfer language and ensure it matches the failure branch destination. |
| `Success Prompt` | "Thank you. Your information has been captured securely." | Optional — remove this block if you prefer silent continuation. |

> **Compliance note:** For card data (PCI-DSS) and SSN (US regulations), your legal team should review the consent language in the Intro Prompt before going live.

### 4.3 Set Contact Attributes Block

Near the top of each flow, a **Set contact attributes** block sets the `collectionPurpose` attribute. This drives validation logic in `aria-dtmf-validate`. Verify the value matches the intended purpose:

| Flow template | Expected `collectionPurpose` value |
|---------------|------------------------------------|
| `dtmf-full-card-number.json` | `full_card_number` |
| `dtmf-card-last-four.json` | `card_last_four` |
| `dtmf-ssn.json` | `ssn` |
| `dtmf-account-number.json` | `account_number` |
| `dtmf-sort-code.json` | `sort_code` |
| `dtmf-generic.json` | `generic` |

You may also set optional attributes in this block:

```
customerId          — populated from CRM lookup upstream in your main flow
accountNumberCountry — ISO 3166-1 alpha-2 (e.g. GB, US) — used by account_number validation
minLength           — minimum digits (generic purpose only)
maxLength           — maximum digits (generic purpose only)
```

### 4.4 Success Branch Destination

The **Validate DTMF Input** Lambda block has two branches: **Success** (validation passed) and **Error** (validation failed or Lambda error). The Success branch connects to a **Transfer to queue** or **Transfer to agent** block by default — the destination is a placeholder.

Update the Success branch to point to:
- The queue you want the contact routed to after capture, **or**
- A **Set working queue** block followed by a transfer if you need to set queue dynamically.

In the flow designer: click the **Success** branch line → click the target block → use the block selector to choose your queue or next flow block.

### 4.5 Failure and Timeout Branch Destinations

Configure what happens when capture fails. The following branches must all lead to a defined destination:

| Branch | Trigger condition | Recommended destination |
|--------|-------------------|--------------------------|
| **Timeout** | Caller did not enter digits within the timeout window | Retry block (up to 2 retries), then agent transfer |
| **Error** | Lambda error (decrypt or validate returned error) | Agent transfer with error flag contact attribute set |
| **Validation Failed** | Digits captured but failed validation (Luhn, length, etc.) | Retry block (up to 2 retries), then agent transfer |
| **Max Retries** | Exceeded retry limit | Queue transfer with `dtmfCaptureFailed=true` attribute |

Set the `dtmfCaptureFailed` contact attribute on failure branches so that agent desktops can surface a warning to the handling agent.

---

## 5. Testing After Import

After publishing the flow, test it thoroughly before routing live traffic through it.

### 5.1 Functional Test via Test Chat / Softphone

1. In the Connect console, go to **Phone numbers** and assign the imported flow to a test number.
2. Call the test number from a soft phone or physical phone.
3. When prompted, enter test digits on the keypad.
4. Verify the flow reaches the success branch and the contact attribute `dtmfCaptureStatus` is set to `success`.

Check contact attributes after the call:
```bash
aws connect get-contact-attributes \
  --instance-id "${INSTANCE_ID}" \
  --initial-contact-id "${CONTACT_ID}" \
  --region "${REGION}"
```

### 5.2 Agent Panel Verification

1. Open the agent panel URL (from CloudFormation Output `PanelURL`).
2. Enter the `session_id` contact attribute value from the active call.
3. Confirm the panel shows the session as **ACTIVE** while digits are being collected, then transitions to **COMPLETE** or **FAILED** after validation.

### 5.3 CloudWatch Logs Verification

Each Lambda writes structured JSON logs to CloudWatch. Check the following log groups:

| Log group | What to look for |
|-----------|-----------------|
| `/aws/lambda/aria-dtmf-start-session-<env>` | `session_created` event with `session_id` |
| `/aws/lambda/aria-dtmf-decrypt-<env>` | `decryption_success` and digit count |
| `/aws/lambda/aria-dtmf-validate-<env>` | `validation_result` with `purpose`, `valid`, and any check details |
| `/aws/lambda/aria-dtmf-status-proxy-<env>` | Polling requests from the agent panel |

### 5.4 Test Values by Purpose

Use these values to test validation logic end-to-end:

| Purpose | Valid test input | Expected result |
|---------|-----------------|-----------------|
| `full_card_number` | `4532015112830366` (Visa, passes Luhn) | success |
| `full_card_number` | `1234567890123456` (fails Luhn) | validation_failed |
| `card_last_four` | `1234` | success |
| `card_last_four` | `12345` | validation_failed (5 digits) |
| `ssn` | `123456789` | success (format ok) |
| `ssn` | `000123456` | validation_failed (area 000) |
| `account_number` | `12345678` | success (8-digit UK) |
| `sort_code` | `123456` | success |
| `sort_code` | `12345` | validation_failed (5 digits) |
| `generic` | Any digit sequence within min/max length | success |

---

## 6. Lambda ARNs from CloudFormation Outputs

After your stack is deployed, retrieve all ARNs with a single command:

```bash
aws cloudformation describe-stacks \
  --stack-name <your-stack-name> \
  --query 'Stacks[0].Outputs[?OutputKey==`DecryptLambdaArn` || OutputKey==`ValidateLambdaArn` || OutputKey==`StartSessionLambdaArn`].[OutputKey,OutputValue]' \
  --output table \
  --region <your-region>
```

**Output reference:**

| CloudFormation Output Key | Used in |
|--------------------------|---------|
| `DecryptLambdaArn` | All flows → "Decrypt DTMF Input" block |
| `ValidateLambdaArn` | All flows → "Validate DTMF Input" block |
| `StartSessionLambdaArn` | All flows → "Start DTMF Session" block |
| `StatusProxyApiUrl` | Agent panel → `STATUS_API_URL` config |
| `ActiveApiUrl` | Agent panel → `ACTIVE_API_URL` config |
| `PanelURL` | Share with contact centre supervisors |
| `LauncherURL` | Embed in agent desktop iframe |

> **Tip:** All Lambda ARNs must be added to your Connect instance's approved Lambda list **before** publishing any contact flow that invokes them, or the flow will fail at the invoke block.

```bash
# Approve a Lambda for use in Connect flows
aws connect associate-lambda-function \
  --instance-id "${INSTANCE_ID}" \
  --function-arn "${LAMBDA_ARN}" \
  --region "${REGION}"
```

Run this command once for each of the three Lambda ARNs.

---

*For support, see the product documentation in `marketplace/docs/` or contact support via the AWS Marketplace listing.*
