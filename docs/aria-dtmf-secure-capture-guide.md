# ARIA — Secure Card Capture (DTMF) Complete Novice Guide

**System:** Meridian Bank · ARIA AI Agent · Amazon Connect  
**Purpose:** Securely collect card numbers, PINs, and account numbers without any agent — human or AI — ever seeing or hearing the raw digits.

> **This guide is completely self-contained.**  
> Read it front to back in one sitting. Every step tells you exactly what to click, type, or run. No experience with AWS, Amazon Connect, or Lambda is assumed.

---

## How This Guide Is Organised

| Phase | What you do | Who needs it |
|---|---|---|
| Phases 1–3 | One-time shared setup | Everyone — do this first |
| Phase 4 | AI Agent (ARIA) path — end to end | If you want ARIA to trigger card capture |
| Phase 5 | Human Agent path — end to end | If you want human advisors to trigger card capture |
| Phase 6 | CCP Status Panel — S3 + CloudFront deployment | Human agent path only |
| Phases 7–10 | Reference, key rotation, testing, troubleshooting | Everyone |

Phases 4 and 5 are **independent**. You can deploy both or just one. Both paths use the **same shared sub-flow** you build in Phase 3 — the difference is only in how they trigger it and how they receive the results.

---

## What We Are Building

When a customer needs to provide sensitive card details over the phone, you must not:

- Ask them to say the number out loud (it is in the call recording)
- Let the agent hear the keypad tones (still a PCI-DSS violation)
- Store the raw digits anywhere in logs, databases, or contact records

The solution is **DTMF masking with RSA encryption**. The customer presses digits on their keypad. Amazon Connect encrypts those digits the instant they are pressed — before any software reads them. A Lambda function decrypts them privately, validates the card, and returns only a safe masked result: *"Card ending 4821 — Visa Debit — verified."*

### The Two Paths

| Path | Triggered by | How |
|---|---|---|
| **AI Agent (ARIA)** | ARIA decides it needs card details | Calls an MCP tool → signals the contact flow → sub-flow runs → results returned as session attributes |
| **Human Agent** | Advisor needs the customer's card number | Clicks "Collect Card — Secure" Quick Connect button → agent muted → sub-flow runs → results shown in CCP panel |

Both paths use the same **shared collection sub-flow** (Phase 3). You build it once.

---

## Glossary

| Term | Plain English |
|---|---|
| **DTMF** | The tones your phone makes when you press a digit key. Amazon Connect can read these silently. |
| **PCI-DSS** | The international security standard for handling card data. Violation = fines and loss of card processing rights. |
| **RSA** | A type of public-key encryption. You lock data with a public key; only the matching private key can unlock it. |
| **KMS** | AWS Key Management Service. A vault that protects your encryption keys. |
| **Secrets Manager** | An AWS service that stores sensitive strings (such as private keys) securely, encrypted by KMS. |
| **Lambda** | A function that runs in the cloud without you managing a server. |
| **Contact Flow** | A visual programme in Amazon Connect that controls what happens during a call. Like a flowchart you can draw. |
| **Contact Attribute** | A variable that lives on a specific call. Lambdas and agents can read and write it during the call. |
| **Session Attribute** | A variable passed to the Lex bot (ARIA). ARIA can read it in its system prompt context. |
| **CCP** | Contact Control Panel. The softphone interface that agents use in their browser to answer calls. |
| **Quick Connect** | A button visible in the CCP that agents can click to trigger a specific action with one click. |
| **Lex V2** | AWS's conversational AI service. Amazon Connect uses a Lex bot to route conversations to ARIA. |
| **Sub-flow** | A contact flow that another flow can transfer into. When it finishes, control returns to the original flow. Like a reusable function. |
| **Module flow** | Amazon Connect's name for a sub-flow you transfer into and get returned from. |
| **BIN** | Bank Identification Number. The first 6 digits of any card number. Publicly available — identifies the issuing bank and card type. Not sensitive. |
| **Luhn check** | A maths check that every valid card number must pass. Catches most digit-entry mistakes. |
| **MCP tool** | A function that ARIA (the AI agent) can call to perform an action, like looking up a balance or starting a collection flow. |
| **AgentCore** | The AWS service that hosts the ARIA AI agent. The fulfillment Lambda sends conversations to AgentCore. |
| **OAC** | Origin Access Control. A CloudFront setting that lets it securely fetch files from a private S3 bucket. |

---

## Architecture — The Full Picture

Read this before you start building. Every box is explained in the relevant phase.

```
 +-------------------------------------------------------------------------+
 |  ONE-TIME SETUP (Phases 1-3 — do once per environment)                  |
 |                                                                         |
 |  1. RSA key pair generated on your laptop                               |
 |     +-- Private key (.pem) -> AWS Secrets Manager (protected by KMS)    |
 |     +-- Public key (.pem)  -> Amazon Connect -> Security Keys           |
 |                                                                         |
 |  2. aria-dtmf-decrypt Lambda   — decrypts ciphertext                   |
 |  3. aria-dtmf-validate Lambda  — Luhn + BIN + ownership checks         |
 |  4. ARIA-DTMF-SecureCollection — the shared sub-flow (built once)       |
 +-------------------------------------------------------------------------+

 +-------------------------------------------------------------------------+
 |  AI AGENT PATH (Phase 4)                                                |
 |                                                                         |
 |  ARIA calls MCP tool: initiate_dtmf_card_capture                        |
 |    +-- sets contact attribute: dtmf_collection_requested = "true"       |
 |    +-- returns { bridge_action: "DTMF_COLLECT", message: "..." }        |
 |  fulfillment Lambda detects flag -> clears flag                         |
 |    +-- returns CollectCardDetails intent to Amazon Connect              |
 |  Main contact flow sees CollectCardDetails intent                       |
 |    +-- Transfer to flow: ARIA-DTMF-SecureCollection ------+             |
 |                                                           |             |
 |    +------------------------------------------------------+             |
 |    |                                                                    |
 |    v  ARIA-DTMF-SecureCollection runs (shared with human path)         |
 |       Customer presses digits -> encrypted -> decrypted -> validated    |
 |       Results written to contact attributes                             |
 |       End flow -> returns to main contact flow                          |
 |    |                                                                    |
 |    v  Main flow: dtmf_* contact attrs -> Lex session attributes         |
 |       Get customer input (Lex) -> ARIA resumes with results             |
 +-------------------------------------------------------------------------+

 +-------------------------------------------------------------------------+
 |  HUMAN AGENT PATH (Phases 5-6)                                          |
 |                                                                         |
 |  Agent clicks "Collect Card - Secure" Quick Connect                     |
 |    +-- Triggers ARIA-DTMF-HumanAgentWrapper (wrapper flow)              |
 |         +-- Agent placed on hold (cannot hear DTMF tones)               |
 |         +-- Transfer to flow: ARIA-DTMF-SecureCollection -----+         |
 |                                                               |         |
 |         +-----------------------------------------------------+         |
 |         |                                                               |
 |         v  ARIA-DTMF-SecureCollection runs (same shared sub-flow)      |
 |            Results written to contact attributes                        |
 |            End flow -> returns to wrapper flow                          |
 |         |                                                               |
 |         v  Wrapper: Conference all (agent rejoined)                     |
 |            CCP Status Panel shows live status to agent                  |
 |            Agent sees: dtmf_masked = "****4821"                         |
 +-------------------------------------------------------------------------+
```

---

# Phase 1 — One-Time Setup

> Do this once per environment. If someone else has already done this for your environment, skip to Phase 2.

---

## Step 1.1 — Generate the RSA Key Pair

> WARNING: Do this on your own laptop, not a shared server, not in a CI/CD pipeline.

Open Terminal and run:

```bash
# Create a secure directory outside any git repository
mkdir ~/meridian-dtmf-keys && cd ~/meridian-dtmf-keys

# Generate the RSA private key (4096-bit)
openssl genrsa -out meridian-connect-private.pem 4096

# Generate the public key as a self-signed X.509 certificate
# Amazon Connect requires a certificate, not a raw public key
openssl req -new -x509 \
  -key meridian-connect-private.pem \
  -out meridian-connect-public.pem \
  -days 1825 \
  -subj "/CN=meridian-connect-dtmf/O=Meridian Bank/C=GB"

# Confirm both files exist
ls -la ~/meridian-dtmf-keys/
```

You now have two files:
- `meridian-connect-private.pem` — **NEVER share. Never put in git. Never email.**
- `meridian-connect-public.pem` — safe to share; goes into Amazon Connect

---

## Step 1.2 — Create the KMS Key

The KMS key protects the private key when stored in Secrets Manager.

```bash
export AWS_REGION=eu-west-2
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Create the KMS key
KMS_OUTPUT=$(aws kms create-key \
  --description "Meridian Bank DTMF private key protection" \
  --key-usage ENCRYPT_DECRYPT \
  --region eu-west-2 \
  --output json)

# Extract and save the key ID and ARN
KMS_KEY_ID=$(echo "$KMS_OUTPUT" | python3 -c \
  "import sys,json; print(json.load(sys.stdin)['KeyMetadata']['KeyId'])")
KMS_KEY_ARN=$(echo "$KMS_OUTPUT" | python3 -c \
  "import sys,json; print(json.load(sys.stdin)['KeyMetadata']['Arn'])")

echo "KMS Key ID:  $KMS_KEY_ID"
echo "KMS Key ARN: $KMS_KEY_ARN"
echo "Save both values — needed in Step 1.3 and Phase 2."

# Create a readable alias
aws kms create-alias \
  --alias-name alias/meridian-connect-dtmf \
  --target-key-id "$KMS_KEY_ID" \
  --region eu-west-2
```

---

## Step 1.3 — Store the Private Key in Secrets Manager

```bash
SECRET_OUTPUT=$(aws secretsmanager create-secret \
  --name "meridian/connect/dtmf-private-key" \
  --description "RSA private key for Connect DTMF decryption — Meridian Bank" \
  --secret-string file://~/meridian-dtmf-keys/meridian-connect-private.pem \
  --kms-key-id alias/meridian-connect-dtmf \
  --region eu-west-2 \
  --output json)

SECRET_ARN=$(echo "$SECRET_OUTPUT" | python3 -c \
  "import sys,json; print(json.load(sys.stdin)['ARN'])")

echo "Secret ARN: $SECRET_ARN"
echo "Save this ARN — needed when deploying the Lambda in Phase 2."
```

> After this succeeds, delete the private key from your laptop:
> ```bash
> rm -P ~/meridian-dtmf-keys/meridian-connect-private.pem
> ```
> The private key now lives **only** in Secrets Manager. A copy on your laptop is a security risk.

---

## Step 1.4 — Upload the Public Key to Amazon Connect

1. Go to **AWS Console > Amazon Connect > Your instance**
2. In the left navigation, choose **Security keys**
3. Click **Add key**
4. Click **Choose file** and select `meridian-connect-public.pem` from `~/meridian-dtmf-keys/`
5. Click **Add**
6. Amazon Connect shows you a **Key ID** — like: `a1b2c3d4-e5f6-7890-abcd-ef1234567890`

> Write this Key ID down. You need it in Phase 3 (Store customer input block) and Phase 2 (Lambda deploy).

You can delete the public key from your laptop — it is safely stored in Connect.

---

## Step 1.5 — Create the DynamoDB Tables

**Table 1: `aria-card-bins`** — maps card BIN (first 6 digits) to card type

```bash
aws dynamodb create-table \
  --table-name aria-card-bins \
  --attribute-definitions AttributeName=binPrefix,AttributeType=S \
  --key-schema AttributeName=binPrefix,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region eu-west-2

echo "Table aria-card-bins created."
```

Seed with example BINs (replace with your real BIN ranges from card operations):

```bash
# Visa Debit
aws dynamodb put-item --table-name aria-card-bins --region eu-west-2 --item \
  '{"binPrefix":{"S":"414900"},"cardType":{"S":"VISA_DEBIT"},"isActive":{"BOOL":true}}'

# Mastercard Credit
aws dynamodb put-item --table-name aria-card-bins --region eu-west-2 --item \
  '{"binPrefix":{"S":"532188"},"cardType":{"S":"MC_CREDIT"},"isActive":{"BOOL":true}}'
```

**Table 2: `aria-customer-cards`** — maps customer IDs to their card last four (legacy fallback)

```bash
aws dynamodb create-table \
  --table-name aria-customer-cards \
  --attribute-definitions \
    AttributeName=customerId,AttributeType=S \
    AttributeName=cardLastFour,AttributeType=S \
  --key-schema \
    AttributeName=customerId,KeyType=HASH \
    AttributeName=cardLastFour,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --region eu-west-2

echo "Table aria-customer-cards created."
```

Seed with test data:

```bash
aws dynamodb put-item --table-name aria-customer-cards --region eu-west-2 --item \
  '{"customerId":{"S":"CUST-001"},"cardLastFour":{"S":"8901"},"isActive":{"BOOL":true},"cardType":{"S":"VISA_DEBIT"}}'
```

> Production: run a nightly sync from your core banking system. The primary ownership check uses the customer Lambda; this table is a fallback.

---

# Phase 2 — Deploy the Lambda Functions

Both Lambdas are deployed using the script at `scripts/deploy_dtmf_lambda.sh`.

---

## Step 2.1 — Run the Deploy Script

```bash
cd /path/to/awsagentcore

./scripts/deploy_dtmf_lambda.sh deploy \
  --instance-id      YOUR_CONNECT_INSTANCE_ID \
  --secret-arn       arn:aws:secretsmanager:eu-west-2:ACCOUNT:secret:meridian/connect/dtmf-private-key-XXXXXX \
  --connect-key-id   a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
  --kms-key-arn      arn:aws:kms:eu-west-2:ACCOUNT:key/YOUR_KMS_KEY_ID \
  --region eu-west-2
```

**Where to find each value:**

| Argument | Where to find it |
|---|---|
| `--instance-id` | Amazon Connect console > Your instance > Overview > Instance ARN (last UUID after `instance/`) |
| `--secret-arn` | The ARN saved at the end of Step 1.3 |
| `--connect-key-id` | The Key ID written down in Step 1.4 |
| `--kms-key-arn` | The ARN saved in Step 1.2 |

The script creates IAM roles, a Lambda Layer with the encryption library, both Lambda functions, and grants Amazon Connect permission to invoke them. It prints a success summary at the end.

---

## Step 2.2 — What Each Lambda Does

### `aria-dtmf-decrypt`

Source: `scripts/lambdas/aria_dtmf_decrypt.py`

Called by the contact flow immediately after the customer presses digits. Receives the encrypted ciphertext. The Lambda:

1. Retrieves the RSA private key from Secrets Manager (KMS decrypts the secret transparently)
2. Decrypts the ciphertext using the private key
3. Produces a masked display value (`****4821`)
4. Extracts the last 4 digits for card lookup (`4821`)
5. Extracts the BIN for validation (`414900`)
6. Returns these to the contact flow — **the raw digits are discarded after masking**

Returns:

| Key | Example | Meaning |
|---|---|---|
| `status` | `success` | Decryption worked |
| `maskedValue` | `****4821` | Safe to show agents and ARIA |
| `digitCount` | `4` | How many digits were collected |
| `lastFour` | `4821` | Last 4 — for tool calls only, not speech |
| `cardBin` | `414900` | First 6 digits for BIN validation |
| `errorMessage` | _(blank on success)_ | Populated on failure |

---

### `aria-dtmf-validate`

Source: `scripts/lambdas/aria_dtmf_validate.py`

Called after decryption succeeds. Receives `lastFour` and `cardBin`. Performs three checks:

**Check 1 — Luhn algorithm:** Every valid card number passes this maths check. Failure = likely miskey → allow retry.

**Check 2 — BIN lookup:** Queries `aria-card-bins` DynamoDB. If the BIN is not found, the bank does not issue this card type → allow retry.

**Check 3 — Ownership check (authenticated customers only):** Invokes the customer Lambda to verify the card belongs to the authenticated customer. If it does not match → immediate fraud escalation. This check is **skipped for unauthenticated customers**.

Returns:

| Key | Example | Meaning |
|---|---|---|
| `isValid` | `"true"` | All checks passed |
| `validationStatus` | `"valid"` | Detailed result code |
| `cardType` | `"VISA_DEBIT"` | Card type from BIN table |
| `cardNickname` | `"Everyday Debit"` | Human-readable name from customer profile |
| `requiresEscalation` | `"false"` | `"true"` = escalate to fraud team |

---

# Phase 3 — Build the Shared DTMF Collection Sub-Flow

> Build this flow once. Both the AI agent path (Phase 4) and the human agent path (Phase 5) transfer into it.

**Flow name:** `ARIA-DTMF-SecureCollection`  
**Flow type:** Standard (click **Create flow** — do not change the type dropdown)

---

## Opening the Flow Designer

1. Go to **AWS Console > Amazon Connect > Your instance**
2. Click **Routing > Flows** in the left navigation
3. Click the blue **Create flow** button (top right)
4. A blank canvas opens with a single **Entry point** block already on it
5. Click "Untitled" at the top left and type: `ARIA-DTMF-SecureCollection`

> How the canvas works: Drag blocks from the left panel onto the canvas. Connect them by clicking the small dot on the output of one block and dragging to the input of the next. Double-click a block to open its settings. Always click **Save** inside the block before moving on.

---

## Block 1 — Check the Channel (Voice Only)

DTMF encryption only works on voice. Chat customers must be told to call instead.

1. Search for `Check contact attributes` in the left panel — drag onto canvas
2. Connect **Entry point** to this block
3. Double-click and configure:
   - **Namespace:** System
   - **Attribute:** Channel
   - Click **Add condition**: Equals / `VOICE`
4. Click **Save**

**Outputs:** `= VOICE` arrow (continues) and `No match` arrow (chat/other).

---

## Block 2 — Tell Chat Customers to Call

1. Drag **Play prompt** onto canvas
2. Connect **No match** from Block 1 to it
3. Configure:
   - Text to speech, English British (Neural) — Amy
   - Text: `I'm sorry, secure card entry is only available over the phone. Please call us on 0800 123 456.`
4. Click **Save**

## Block 3 — End the Chat Path

1. Drag **Disconnect / hang up** onto canvas
2. Connect Block 2 output to it

---

## Block 4 — Initialise Collection State

1. Drag **Set contact attributes** onto canvas
2. Connect `= VOICE` from Block 1 to it
3. Add three attributes:

   | Type | Destination key | Value |
   |---|---|---|
   | User Defined | `dtmfRetries` | `0` |
   | User Defined | `dtmf_result` | `pending` |
   | User Defined | `dtmf_status` | `waiting_for_input` |

4. Click **Save**

---

## Block 5 — Instruction Prompt

1. Drag **Play prompt** onto canvas
2. Connect Block 4 output to it
3. Configure:
   - Text to speech, English British (Neural) — Amy
   - Text: `Please enter the last four digits of your card number, followed by the hash key.`
   
   > Adjust for your use case: full card = "16-digit card number", PIN = "4-digit PIN"

4. Click **Save**

---

## Block 6 — Capture and Encrypt the Digits

This is the most important block. Amazon Connect captures and encrypts the digits instantly.

1. Search for `Store customer input` — drag onto canvas
2. Connect Block 5 output to it
3. Double-click and configure:

   **Prompts tab:** Set type = Text to speech, leave text blank

   **DTMF tab:**
   - **Tick "Encrypt entry"** — this is the critical setting
   - **Key:** Select the Key ID from Step 1.4 in the dropdown
   - **Maximum number of digits:** `4` (last-four/PIN) or `16` (full card)
   - **Terminating keypress:** `#`
   - **Timeout before first entry:** `15` seconds
   - **Timeout between entries:** `5` seconds

4. Click **Save**

**Outputs:**

| Arrow | When it fires | Connect to |
|---|---|---|
| `Stored` | Customer pressed digits | Block 7 |
| `No entry` | Timed out | Block 16 (retry) |
| `Error` | Technical problem | Block 16 (retry) |

---

## Block 7 — Mark as Processing

1. Drag **Set contact attributes**
2. Connect `Stored` from Block 6
3. Set: `dtmf_status` = `processing`
4. Click **Save**

---

## Block 8 — Call the Decrypt Lambda

1. Drag **Invoke AWS Lambda function**
2. Connect Block 7 output
3. Configure:
   - **Function:** `aria-dtmf-decrypt`
   - **Timeout:** `8` seconds
   - **Function input parameters:**

     | Parameter key | Value type | Value |
     |---|---|---|
     | `encryptedValue` | System | Stored customer input |
     | `purpose` | Contact attribute | `collectionPurpose` |
     | `keyId` | Contact attribute | `connectKeyId` |

4. Connect **Error** arrow to Block 15 (Lambda error handler)
5. Click **Save**

---

## Block 9 — Mark as Validating and Store BIN

1. Drag **Set contact attributes**
2. Connect **Success** from Block 8
3. Configure two attributes:
   - Static: `dtmf_status` = `validating`
   - Set dynamically: `dtmf_card_bin` from External namespace, key `cardBin`
   
   > "Set dynamically from External key cardBin" copies the BIN returned by the Lambda into a contact attribute so the next Lambda can read it.

4. Click **Save**

---

## Block 10 — Call the Validate Lambda

1. Drag **Invoke AWS Lambda function**
2. Connect Block 9 output
3. Configure:
   - **Function:** `aria-dtmf-validate`
   - **Timeout:** `8` seconds
   - **Function input parameters:**

     | Parameter key | Value type | Value |
     |---|---|---|
     | `customerId` | Contact attribute | `customerId` |
     | `cardLastFour` | External attribute | `lastFour` |
     | `cardBin` | Contact attribute | `dtmf_card_bin` |
     | `digitCount` | External attribute | `digitCount` |
     | `purpose` | Contact attribute | `collectionPurpose` |
     | `authStatus` | Contact attribute | `authStatus` |

4. Connect **Error** arrow to Block 15
5. Click **Save**

---

## Block 11 — Did Validation Pass?

1. Drag **Check contact attributes**
2. Connect **Success** from Block 10
3. Configure:
   - **Namespace:** External
   - **Attribute:** `isValid`
   - Condition: Equals / `true`
4. Click **Save**

**Outputs:** `= true` to Block 12 (success). `No match` to Block 11a (check failure type).

---

## Block 11a — What Type of Failure?

A Luhn failure (miskey) needs a retry. An ownership failure (fraud) needs escalation.

1. Drag **Check contact attributes**
2. Connect `No match` from Block 11
3. Configure:
   - **Namespace:** External
   - **Attribute:** `validationStatus`
   - Three conditions: `not_customer_card`, `invalid_luhn`, `invalid_bin`
4. Click **Save**

**Outputs:**

| Arrow | Connect to |
|---|---|
| `= not_customer_card` | Block 11b (escalate) |
| `= invalid_luhn` | Block 11c (retry) |
| `= invalid_bin` | Block 11c (retry) |
| `No match` | Block 12 (service error — fail open) |

---

## Block 11b — Escalate Path

1. Drag **Set contact attributes**
2. Connect `= not_customer_card` from Block 11a
3. Set: `dtmf_result` = `card_not_authorised`, `dtmf_status` = `escalating`, `dtmf_requires_escalation` = `true`
4. Drag **Play prompt**: `I'm sorry, the card details you entered could not be verified. I'm connecting you with an advisor now.`
5. Drag **Transfer to queue**: select your fraud/escalation queue

---

## Block 11c — Retry Path

1. Drag **Set contact attributes**
2. Connect both `= invalid_luhn` and `= invalid_bin` from Block 11a
3. Set: `dtmf_status` = `retry_validation_error`
4. Drag **Play prompt**: `I'm sorry, I wasn't able to recognise those card details. Please try entering them again.`
5. Connect Play prompt output back to **Block 5** (the instruction prompt) to loop

---

## Block 12 — Store the Success Result

Copy Lambda return values from the temporary External namespace into persistent contact attributes.

1. Drag **Set contact attributes**
2. Connect two arrows here:
   - `= true` from Block 11
   - `No match` from Block 11a (service error — fail open)
3. Configure (all using "Set dynamically" from External except static values):

   | Destination key | Source | Source key |
   |---|---|---|
   | `dtmf_result` | Static | `success` |
   | `dtmf_masked` | External | `maskedValue` |
   | `dtmf_last_four` | External | `lastFour` |
   | `dtmf_digit_count` | External | `digitCount` |
   | `dtmf_validation_status` | External | `validationStatus` |
   | `dtmf_card_type` | External | `cardType` |
   | `dtmf_card_nickname` | External | `cardNickname` |
   | `dtmf_status` | Static | `complete` |
   | `dtmf_requires_escalation` | External | `requiresEscalation` |

4. Click **Save**

---

## Block 13 — Thank the Customer

1. Drag **Play prompt**
2. Connect Block 12 output
3. Text: `Thank you. I have securely captured your card details.`
4. Click **Save**

---

## Block 14 — End the Sub-Flow

1. Drag **End flow / Resume**
2. Connect Block 13 output

> When this block is reached, Amazon Connect returns to whichever flow transferred in, continuing from the block after the Transfer to flow block.

---

## Block 15 — Lambda Error Handler

1. Drag **Set contact attributes**
2. Connect **Error** arrows from both Block 8 and Block 10
3. Set: `dtmf_result` = `lambda_error`, `dtmf_status` = `system_error`
4. Drag **Play prompt**: `I'm sorry, I encountered a technical problem. Please try again, or I can connect you with an advisor.`
5. Connect to **End flow / Resume**

---

## Blocks 16–20 — Retry Sub-Pattern

Amazon Connect cannot add 1 to a number. Connect the **No entry** and **Error** arrows from Block 6 to Block 16.

**Block 16:** Check contact attributes — Namespace: User Defined — Attribute: `dtmfRetries`
- Conditions: Equals `0`, Equals `1`, Equals `2`

**Block 17** (retries = 0): Set `dtmfRetries = 1` > Play prompt ("I didn't catch that. Please try again.") > loop to Block 5

**Block 18** (retries = 1): Set `dtmfRetries = 2` > Play prompt ("Please try again — enter your digits followed by hash.") > loop to Block 5

**Block 19** (retries = 2): Set `dtmfRetries = 3` > Play prompt ("One more attempt.") > loop to Block 5

**Block 20** (No match — all attempts exhausted): Set `dtmf_result = failed`, `dtmf_status = collection_failed` > Play prompt ("I'm sorry, I wasn't able to collect your details securely. Your advisor will continue to help you.") > **End flow / Resume**

---

## Publish the Sub-Flow

Click **Save** (top right), then click **Publish**.

> You cannot use an unpublished flow as a transfer target. Saving creates a draft. Publishing makes it live.

---

# Phase 4 — AI Agent Path: ARIA MCP-Based Collection

> Read this phase if you are deploying the AI Agent (ARIA) path.  
> This phase is independent of Phase 5.

---

## How the AI Agent Path Works

### The Authentication Gate — ARIA Checks This First

```
Customer asks: "What is my credit card balance?"
                        |
                        v
         Is authStatus = "authenticated"?
                /                  \
              YES                   NO
               |                    |
 ARIA already has card details    ARIA has no profile data.
 from get_customer_details:        Cannot identify which card.
 last_four, BIN, card type.             |
               |                        v
 Call balance tool directly        Trigger DTMF sub-flow to
 with known card data               capture last four digits
               |                        |
               +----------+-------------+
                          |
                          v
               Answer the customer's question
```

**ARIA never triggers DTMF for authenticated customers.** An authenticated customer's card details are already known from their profile. DTMF is only for unauthenticated customers who need to identify their card.

---

### The Bridge Mechanism

ARIA cannot directly run a contact flow. A bridge is used:

```
ARIA (unauthenticated customer needs card ID)
  calls MCP tool: initiate_dtmf_card_capture(purpose="card_last_four")
         |
         v
aria-banking-mcp-dtmf-prod Lambda:
  Sets contact attributes:
    dtmf_collection_requested = "true"
    collectionPurpose = "card_last_four"
    connectKeyId = "your-key-id"
  Returns to ARIA:
    { status: "initiated",
      message: "I'll transfer you to our secure keypad briefly...",
      bridge_action: "DTMF_COLLECT" }
         |
         v
ARIA says the "message" text aloud, then stops.
AgentCore returns response text to the fulfillment Lambda.
         |
         v
aria_connect_fulfillment Lambda checks AFTER EVERY AgentCore response:
  connect.GetContactAttributes() -> sees dtmf_collection_requested = "true"
  Clears the flag to "false"
  Returns CollectCardDetails intent to Amazon Connect  <-- KEY STEP
         |
         v
Amazon Connect sees intent = "CollectCardDetails"
  Branches to DTMF section in the main contact flow
  Transfer to flow -> ARIA-DTMF-SecureCollection
         |
         v
ARIA-DTMF-SecureCollection runs (Phase 3 sub-flow)
  Customer presses digits -> encrypted -> decrypted -> validated
  Results written to contact attributes
  End flow -> returns to main contact flow
         |
         v
Main flow: copies dtmf_* contact attributes to Lex session attributes
  Get customer input (Lex) -> ARIA reinvoked
         |
         v
ARIA reads session attributes, continues conversation:
  "I can see your Visa Debit card ending 4821.
   Your outstanding balance is £1,234.56."
```

---

## Step 4.1 — Prerequisites

Before starting this phase, confirm all of the following:

- [ ] Phases 1–3 complete (keys, Lambdas, sub-flow built and published)
- [ ] `aria_connect_fulfillment` Lambda deployed and working
- [ ] `ARIA-Connect-Bot` Lex V2 bot exists in your region
- [ ] MCP gateway deployed at least once (`scripts/deploy_mcp_gateway.sh`)

---

## Step 4.2 — Deploy the DTMF MCP Tool Lambda

Source file: `scripts/lambdas/mcp_tools/aria_dtmf_handler.py`

```bash
cd /path/to/awsagentcore

# Step 1: Create deployment package
mkdir -p /tmp/dtmf-mcp-build
cp scripts/lambdas/mcp_tools/aria_dtmf_handler.py /tmp/dtmf-mcp-build/handler.py
cd /tmp/dtmf-mcp-build
zip -r dtmf_mcp.zip handler.py
cd /path/to/awsagentcore

# Step 2: Get account ID
AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)

# Step 3: Create the Lambda
aws lambda create-function \
  --function-name aria-banking-mcp-dtmf-prod \
  --runtime python3.12 \
  --handler handler.lambda_handler \
  --role arn:aws:iam::${AWS_ACCOUNT}:role/aria-lambda-mcp-role \
  --zip-file fileb:///tmp/dtmf-mcp-build/dtmf_mcp.zip \
  --timeout 15 \
  --memory-size 128 \
  --region eu-west-2
```

Set environment variables (replace with your real values):

```bash
aws lambda update-function-configuration \
  --function-name aria-banking-mcp-dtmf-prod \
  --environment "Variables={CONNECT_INSTANCE_ID=YOUR_INSTANCE_ID,CONNECT_KEY_ID=YOUR_KEY_ID}" \
  --region eu-west-2
```

Grant permission to update contact attributes:

```bash
aws iam put-role-policy \
  --role-name aria-lambda-mcp-role \
  --policy-name dtmf-connect-attributes \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["connect:UpdateContactAttributes","connect:GetContactAttributes"],"Resource":"*"}]}'
```

---

## Step 4.3 — Add the DTMF Domain to the MCP Gateway

Open the MCP gateway YAML configuration (used by `scripts/deploy_mcp_gateway.sh`) and add:

```yaml
domains:
  # ... your existing domains ...

  - name: dtmf
    lambda_function: aria-banking-mcp-dtmf-prod
    tools:
      - name: initiate_dtmf_card_capture
        description: >
          Initiates a secure DTMF card digit collection session.
          Use ONLY when authStatus is "unauthenticated" and the customer asks
          about a specific card. After this tool returns, read the "message"
          aloud verbatim, then stop. Results arrive as session attributes
          (dtmf_masked, dtmf_result, dtmf_card_type) on your next turn.
        input_schema:
          type: object
          properties:
            contact_id:
              type: string
              description: The Amazon Connect ContactId (equals the current session ID)
            purpose:
              type: string
              enum: [card_last_four, full_card_number, expiry_date, cvv, pin, account_number, sort_code]
              description: What the customer needs to enter
            customer_id:
              type: string
              description: Optional — authenticated customer ID for ownership check
          required: [contact_id, purpose]
```

Then redeploy:

```bash
./scripts/deploy_mcp_gateway.sh
```

---

## Step 4.4 — Create the `CollectCardDetails` Lex Intent

The fulfillment Lambda signals Amazon Connect by returning this intent name. The customer never says it — it is returned programmatically. Lex must know it exists.

1. Go to **Amazon Lex > Bots > ARIA-Connect-Bot**
2. Click your bot alias (e.g. `ARIA-Connect-Bot-Live`) > **Edit**
3. In the left sidebar, click **Intents**
4. Click **Add intent > Add empty intent**
5. Name it exactly: `CollectCardDetails` (case-sensitive, no spaces)
6. Leave all fields empty — no utterances, no slots, no confirmation
7. Click **Save intent**
8. Click **Build** (top right) — wait 1–2 minutes
9. Click **Publish** > choose your alias > **Publish**

---

## Step 4.5 — Update the Fulfillment Lambda

Source file: `scripts/lambdas/aria_connect_fulfillment.py` (already updated with the DTMF bridge logic).

Deploy:

```bash
cd /path/to/awsagentcore
zip -j /tmp/fulfillment.zip scripts/lambdas/aria_connect_fulfillment.py

aws lambda update-function-code \
  --function-name aria-connect-fulfillment \
  --zip-file fileb:///tmp/fulfillment.zip \
  --region eu-west-2
```

Add required IAM permission:

```bash
aws iam put-role-policy \
  --role-name aria-lambda-fulfillment-role \
  --policy-name dtmf-read-write-attrs \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["connect:GetContactAttributes","connect:UpdateContactAttributes"],"Resource":"*"}]}'
```

Set `CONNECT_INSTANCE_ID` environment variable:

```bash
aws lambda update-function-configuration \
  --function-name aria-connect-fulfillment \
  --environment "Variables={AGENTCORE_ENDPOINT=YOUR_AGENTCORE_ENDPOINT,CONNECT_INSTANCE_ID=YOUR_CONNECT_INSTANCE_ID}" \
  --region eu-west-2
```

---

## Step 4.6 — Update the Main Contact Flow

Open your main inbound contact flow in **Amazon Connect > Routing > Flows > Edit**.

---

### Block A — Add CollectCardDetails to the Lex Input Block

1. Double-click your existing **Get customer input** (Lex) block
2. Scroll to the **Intents** section
3. Click **Add intent** — type: `CollectCardDetails`
4. Click **Save**

The block now has a new output arrow labelled `CollectCardDetails`.

---

### Block B — Set Sub-Flow Parameters

1. Drag **Set contact attributes** onto canvas
2. Connect the `CollectCardDetails` arrow from Block A to this block
3. Configure:
   - `collectionPurpose` = `card_last_four`
   - `connectKeyId` = `a1b2c3d4-e5f6-7890-abcd-ef1234567890` _(your Key ID from Step 1.4)_
4. Click **Save**

---

### Block C — Transfer to the Sub-Flow

1. Drag **Transfer to flow** onto canvas
2. Connect Block B output to it
3. Double-click and select: **ARIA-DTMF-SecureCollection**
4. Click **Save**

> When this block runs, the call transfers into the shared sub-flow. When the sub-flow's End flow block is reached, Amazon Connect returns here automatically — continuing from the block after this Transfer block.

---

### Block D — Resume ARIA with DTMF Results

After the sub-flow returns, copy its results into Lex session attributes and reinvoke ARIA.

1. Drag **Get customer input** (a new Lex invocation) onto canvas
2. Connect Block C **Success** output to it
3. Configure:
   - **Lex bot:** Your ARIA bot
   - **Alias:** Your published alias
4. Under **Session attributes**, click **Add attribute** for each row:

   | Session attribute key | Value type | Contact attribute key |
   |---|---|---|
   | `dtmf_result` | Contact attribute | `dtmf_result` |
   | `dtmf_masked` | Contact attribute | `dtmf_masked` |
   | `dtmf_last_four` | Contact attribute | `dtmf_last_four` |
   | `dtmf_purpose` | Contact attribute | `collectionPurpose` |
   | `dtmf_validation_status` | Contact attribute | `dtmf_validation_status` |
   | `dtmf_card_type` | Contact attribute | `dtmf_card_type` |
   | `dtmf_card_nickname` | Contact attribute | `dtmf_card_nickname` |
   | `dtmf_requires_escalation` | Contact attribute | `dtmf_requires_escalation` |
   | `dtmf_status` | Contact attribute | `dtmf_status` |

5. Connect this block's output arrows to your existing flow branches
6. Click **Save**

---

### Block E — Handle Transfer Errors

1. Drag **Play prompt** — connect Block C **Error** output
2. Text: `I'm sorry, I had a technical problem with the secure input. Let me continue helping you.`
3. Connect back to the main Get customer input (Lex) block to resume ARIA normally

Click **Publish** on the main flow when done.

---

## Step 4.7 — Update the ARIA System Prompt

In the Amazon Connect AI Agent designer for your ARIA agent, add the following to the `<instructions>` section:

```
## DTMF Secure Card Capture

AUTHENTICATED vs UNAUTHENTICATED — CHECK THIS FIRST:

If authStatus = "authenticated":
  You already have the customer's card details from get_customer_details:
  last_four, BIN, card type, and nickname. Use these directly.
  DO NOT trigger DTMF. The customer has been verified.
  Example: "what's my credit card balance?" ->
    call get_credit_card_details using the card_last_four from their profile.

If authStatus = "unauthenticated" (or absent):
  You do not have a customer profile. If the customer asks about a specific
  card (balance, payment, block request) you must capture the last four
  digits via DTMF before looking anything up.

WHEN TO TRIGGER DTMF (unauthenticated customers only):
  1. Say: "I'll just transfer you to our secure input system for a moment
     — it will only take a few seconds."
  2. Call initiate_dtmf_card_capture with:
       contact_id = the contactId session attribute
       purpose    = "card_last_four"
  3. Read the "message" field from the tool response aloud verbatim.
  4. Stop speaking. The system handles the rest.

AFTER DTMF RETURNS (session attributes will contain):
  dtmf_result            — "success" / "failed" / "lambda_error"
  dtmf_masked            — "****4821" — always say "card ending [dtmf_masked]"
  dtmf_last_four         — "4821" — for tool calls only, never say aloud
  dtmf_validation_status — "valid" / "invalid_luhn" / "invalid_bin" / "not_customer_card"
  dtmf_card_type         — "VISA_DEBIT" / "MC_CREDIT" etc.
  dtmf_card_nickname     — "Everyday Debit" (if available)
  dtmf_requires_escalation — "true" / "false"

ON SUCCESS (dtmf_result = "success"):
  - "valid" or "validation_service_error": proceed normally
  - "invalid_luhn": "There may have been a typo — could you try again?"
    Call initiate_dtmf_card_capture again.
  - "invalid_bin": "I wasn't able to recognise that card. Try a different card?"
  - "not_customer_card" or dtmf_requires_escalation = "true":
    IMMEDIATELY say "I need to transfer you to one of our advisors."
    Use the escalate_to_human_agent tool.

ON FAILURE (dtmf_result = "failed" or "lambda_error"):
  Say: "I'm sorry, I wasn't able to collect your card details securely.
  Would you like to try again, or shall I arrange a callback?"
  Never ask the customer to say their card number aloud.

RULES — NEVER BREAK THESE:
  - NEVER say raw digits. Always say "your card ending [dtmf_masked]".
  - NEVER ask for card numbers, PINs, or CVVs in conversation — always DTMF.
  - NEVER trigger DTMF when authStatus = "authenticated".
  - NEVER attempt DTMF in chat — tell chat customers to call 0800 123 456.
```

---

## Step 4.8 — Testing the AI Agent Path

### Test A — Unauthenticated customer (DTMF should trigger)

1. Call the Connect inbound number
2. Do **not** authenticate — proceed as an unrecognised caller
3. Say: `"I want to know my credit card balance"`
4. ARIA should say it needs to identify the card and direct you to the keypad
5. You should hear the sub-flow prompt: `"Please enter the last four digits..."`
6. Press 4 digits then `#`
7. ARIA should resume: `"I can see your card ending 4821..."`

**Check CloudWatch Logs:**
- `aria-connect-fulfillment`: look for `DTMF bridge triggered for contact=`
- `aria-dtmf-decrypt`: look for `status: success`
- `aria-dtmf-validate`: look for `validationStatus: unauthenticated_skip`

### Test B — Authenticated customer (DTMF must NOT trigger)

1. Call and authenticate (session_injector sets `authStatus = "authenticated"`)
2. Say: `"I want to know my credit card balance"`
3. ARIA should respond directly with the balance — no keypad prompt
4. Check `aria-connect-fulfillment` logs — there should be **no** `DTMF bridge triggered` line

### Test C — Verify flag is cleared

```bash
aws connect get-contact-attributes \
  --instance-id YOUR_CONNECT_INSTANCE_ID \
  --initial-contact-id CONTACT_ID_FROM_LOGS \
  --region eu-west-2
```

`dtmf_collection_requested` should be `"false"` after the sub-flow ran.

### Test D — Direct Lambda invocation

```bash
aws lambda invoke \
  --function-name aria-banking-mcp-dtmf-prod \
  --payload '{"tool_name":"initiate_dtmf_card_capture","parameters":{"contact_id":"test-001","purpose":"card_last_four"}}' \
  --cli-binary-format raw-in-base64-out \
  --region eu-west-2 \
  /tmp/dtmf-mcp-test.json && cat /tmp/dtmf-mcp-test.json
```

Expected: response with `status: "initiated"` and a `message` field.

---

# Phase 5 — Human Agent Path: Quick Connect + Wrapper Flow

> Read this phase if you are deploying the human agent path.  
> This phase is independent of Phase 4.

---

## How the Human Agent Path Works

A human advisor is on a live call and needs the customer's card number.

```
Agent clicks "Collect Card - Secure" Quick Connect
         |
         v
ARIA-DTMF-HumanAgentWrapper flow triggers
  Block 1: Sets collectionPurpose and connectKeyId
  Block 2: Plays announcement to both agent and customer:
    "Your agent will now be placed on hold while you enter card details securely."
  Block 3: Puts AGENT ON HOLD
    Agent hears: hold music/silence
    Customer can still hear: sub-flow prompts
    DTMF tones from customer: DO NOT reach the agent
  Block 4: Transfer to flow -> ARIA-DTMF-SecureCollection
         |
         v
ARIA-DTMF-SecureCollection runs (Phase 3 shared sub-flow)
  Customer presses digits -> encrypted -> decrypted -> validated
  Results written to contact attributes
  End flow -> returns to wrapper flow
         |
         v
Wrapper flow continues:
  Block 5: Conference all (agent rejoined)
  Block 6: Announcement: "Card details collected. Your agent will continue."
  Block 7: End wrapper flow
         |
         v
Agent and customer continue normally.
Agent's CCP Contact Attributes tab shows: dtmf_masked = "****4821"
CCP Status Panel (Phase 6) showed live progress during the collection.
```

---

## The Key Difference from the AI Agent Path

| | AI Agent Path | Human Agent Path |
|---|---|---|
| **Trigger** | ARIA calls MCP tool -> fulfillment Lambda returns `CollectCardDetails` intent | Agent clicks Quick Connect button |
| **Flow type** | Standard contact flow | Transfer to queue flow |
| **Sub-flow** | Same `ARIA-DTMF-SecureCollection` | Same `ARIA-DTMF-SecureCollection` |
| **Agent state while sub-flow runs** | ARIA is idle, waiting to be reinvoked | Human agent is on hold (muted) |
| **Results delivered** | Session attributes on ARIA's next Lex invocation | Contact attributes visible in CCP panel |
| **Real-time feedback** | Session attributes on next turn only | CCP Status Panel (Phase 6) shows live progress |

---

## Step 5.1 — Build the Human Agent Wrapper Flow

**Flow name:** `ARIA-DTMF-HumanAgentWrapper`  
**Flow type:** Transfer to queue flow

> IMPORTANT: The flow type is critical. Click the **dropdown arrow** next to the blue "Create flow" button and select **"Transfer to queue flow"** before clicking Create. This type is required for Quick Connects.

---

**Block 1 — Set Parameters**

1. Connect to the **Entry point** block already on canvas
2. Drag **Set contact attributes** and connect to Entry point
3. Configure:
   - `collectionPurpose` = `full_card_number` (or `card_last_four`)
   - `connectKeyId` = `a1b2c3d4-...` _(your Connect Key ID)_
   - `agentMode` = `human`
4. Click **Save**

---

**Block 2 — Announce to Both Parties**

1. Drag **Play prompt** — connect Block 1 output
2. Configure:
   - Text to speech, English British (Neural) — Amy
   - Text: `Your agent will now be placed on hold while you enter your card details securely using your telephone keypad. Your conversation will resume automatically when the process is complete.`
3. Click **Save**

---

**Block 3 — Place the Agent on Hold**

This is the PCI-compliance block. The customer is still active. The agent is muted. DTMF tones cannot reach the agent.

1. Search for `Hold customer or agent` — drag onto canvas
2. Connect Block 2 output
3. Double-click and configure:
   - **Option:** Agent on hold
4. Click **Save**
5. Error handling: connect **Error** arrow -> Play prompt ("Unable to place agent on hold. Please try again.") -> End flow

---

**Block 4 — Enter the Shared Sub-Flow**

1. Drag **Transfer to flow** — connect Block 3 **Success** output
2. Double-click and select: **ARIA-DTMF-SecureCollection**
3. Click **Save**

> When the sub-flow's End flow block is reached, Connect returns here automatically.

---

**Block 5 — Bring the Agent Back**

1. Drag **Hold customer or agent** — connect Block 4 **Success** output
2. Configure:
   - **Option:** Conference all

> "Conference all" lifts the agent's hold and reconnects them to the customer. Both can hear each other again.

3. Click **Save**

---

**Block 6 — Announce Completion**

1. Drag **Play prompt** — connect Block 5 output
2. Text: `Card details have been collected securely. Your agent will now continue assisting you.`
3. Click **Save**

---

**Block 7 — End the Wrapper Flow**

1. Drag **End flow** — connect Block 6 output
2. Click **Save**
3. Click **Publish** on the entire wrapper flow

---

**What the Agent's CCP Shows After Collection**

| Attribute | Example | Meaning |
|---|---|---|
| `dtmf_result` | `success` | Collection worked |
| `dtmf_masked` | `****4821` | Card ending to reference in conversation |
| `dtmf_card_type` | `VISA_DEBIT` | Type of card |
| `dtmf_card_nickname` | `Everyday Debit` | Card nickname if available |
| `dtmf_validation_status` | `valid` | All checks passed |
| `dtmf_status` | `complete` | Process finished |
| `dtmf_requires_escalation` | `false` | No fraud flag |

---

## Step 5.2 — Create the Quick Connect

1. Go to **Amazon Connect > Routing > Quick connects**
2. Click **Add Quick connect**
3. Configure:
   - **Name:** `Collect Card — Secure`
   - **Type:** Transfer to queue
   - **Flow:** `ARIA-DTMF-HumanAgentWrapper`
   - **Queue:** The queue your agents work in (e.g. `Meridian-Banking-Queue`)
4. Click **Save**

---

## Step 5.3 — Add the Quick Connect to the Queue

1. Go to **Amazon Connect > Routing > Queues**
2. Click your agents' queue (e.g. `Meridian-Banking-Queue`)
3. Scroll to the **Quick connects** section
4. Search and add: `Collect Card — Secure`
5. Click **Save**

---

## Step 5.4 — Add the Quick Connect to the Routing Profile

1. Go to **Amazon Connect > Routing > Routing profiles**
2. Click the profile assigned to your agents (e.g. `Meridian-Bank-Agents`)
3. Scroll to the **Quick connects** section
4. Search and add: `Collect Card — Secure`
5. Click **Save**

---

## Step 5.5 — Testing the Human Agent Path

### Test A — Happy Path

1. Log into the CCP as a test agent — set yourself Available
2. As a customer, call your Connect inbound number
3. Accept the call as the agent
4. Click the Quick connects icon in the CCP > select `Collect Card — Secure`
5. Agent: you should hear hold music
6. Customer: hear `"Your agent will now be placed on hold..."` then the keypad prompt
7. Customer: press 4 digits then `#`
8. Customer: hear `"Thank you. I have securely captured your card details."`
9. Agent: you are reconnected — hear `"Card details have been collected securely..."`
10. Agent: open **Contact Attributes** panel in CCP — verify `dtmf_masked = ****XXXX`

### Test B — Fraud Escalation Path

1. Repeat Test A but enter digits of a card that is NOT seeded for the test customer
2. Expected: `dtmf_requires_escalation = "true"` appears in the contact attributes
3. If the CCP Status Panel is deployed (Phase 6), it should show the red escalation warning

---

# Phase 6 — CCP Status Panel: Real-Time Feedback for Human Agents

> This phase is for the human agent path only.  
> ARIA (AI agent) receives feedback via session attributes on its next turn — no panel is needed for the AI path.

---

## What This Panel Does

Without the panel, an agent on hold during card collection sees nothing and might rejoin the call too early. The CCP Status Panel:

1. Connects to the active call via the Amazon Connect Streams SDK (in a hidden iframe)
2. Watches the `dtmf_status` contact attribute in real time
3. Shows the agent a colour-coded live view of each step

| Status shown | `dtmf_status` value | Colour |
|---|---|---|
| Waiting for customer to press digits | `waiting_for_input` | Yellow |
| Digits received — decrypting | `processing` | Orange |
| Running card checks | `validating` | Blue |
| All checks passed — card captured | `complete` | Green |
| Card does not belong to this customer | `escalating` | Red + alert |
| All retry attempts exhausted | `collection_failed` | Dark grey |
| Technical error | `system_error` | Red |

On completion, the panel shows the masked card result: `"Card ending ****4821 — Visa Debit"`.

---

## Step 6.1 — Deploy the Panel Using the Script

The deploy script handles the entire S3 + CloudFront setup:

```bash
cd /path/to/awsagentcore

./scripts/deploy_dtmf_lambda.sh deploy-panel \
  --instance-id          YOUR_CONNECT_INSTANCE_ID \
  --connect-instance-url https://meridian-bank.my.connect.aws \
  --region eu-west-2
```

**Where to find these values:**

| Argument | Where to find it |
|---|---|
| `--instance-id` | Amazon Connect > Your instance > Instance ARN (last UUID after `instance/`) |
| `--connect-instance-url` | The URL you use to log into Connect (e.g. `https://meridian-bank.my.connect.aws`) |

**What the command does step by step:**

1. Creates an S3 bucket `aria-dtmf-panel-{account-id}` with public access blocked
2. Patches `client/dtmf-status-panel/index.html` to replace the placeholder Connect URL with your actual URL
3. Uploads the patched HTML to S3 as `dtmf-panel/index.html`
4. Creates a CloudFront Origin Access Control (OAC) for secure S3 access
5. Creates a CloudFront distribution pointing to the S3 bucket
6. Applies an S3 bucket policy allowing only CloudFront to read the file
7. Saves the deployment state for future updates
8. Prints the final panel URL

**Expected script output:**

```
OK  DTMF Status Panel deployed successfully!
    S3 Bucket:       s3://aria-dtmf-panel-123456789012/dtmf-panel/
    CloudFront ID:   E1ABC2DEF3GHI4J
    Panel URL:       https://d1234abcdef567.cloudfront.net/dtmf-panel/index.html

NOTE: CloudFront distributions take 5-15 minutes to fully propagate.
After propagation, complete Steps 6.2 and 6.3 in the console.
```

Save the **Panel URL**. You need it in the next two steps.

> CloudFront distributions take 5–15 minutes to propagate after creation. Do not try to open the URL immediately after the script finishes — wait for the propagation.

---

## Step 6.2 — Add the CloudFront Domain to Connect Approved Origins

Amazon Connect will not load third-party apps unless their domain is explicitly allowed.

1. Go to **Amazon Connect > Your instance > Approved origins**
2. Click **Add domain**
3. Enter the CloudFront domain _(just the domain, not the file path)_:  
   `https://d1234abcdef567.cloudfront.net`
4. Click **Save**

> Do not include `/dtmf-panel/index.html` — just the `https://XXXXXXXX.cloudfront.net` part.

---

## Step 6.3 — Register the Panel as a Third-Party App

1. Go to **Amazon Connect > Your instance > Application integration**
2. Click **Add integration**
3. Configure:
   - **Application name:** `DTMF Status Panel`
   - **URL:** _(the full URL)_ `https://d1234abcdef567.cloudfront.net/dtmf-panel/index.html`
   - **Application scope:** `Contact` _(refreshes per call, not per agent session)_
4. Click **Save**

The panel now appears as a tab in the Amazon Connect Agent Workspace for all agents who log in.

---

## Step 6.4 — Manual Deployment (Without the Script)

If the script is unavailable, deploy manually:

```bash
# Step 1: Edit the panel HTML
# Open client/dtmf-status-panel/index.html
# Find line approx. 349:
#   const CONNECT_INSTANCE_URL = "https://meridian-bank.my.connect.aws";
# Replace with your actual instance URL and save.

# Step 2: Create S3 bucket (eu-west-2 example)
aws s3api create-bucket \
  --bucket YOUR-PANEL-BUCKET-NAME \
  --region eu-west-2 \
  --create-bucket-configuration LocationConstraint=eu-west-2

# Step 3: Block all public access
aws s3api put-public-access-block \
  --bucket YOUR-PANEL-BUCKET-NAME \
  --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

# Step 4: Upload the file
aws s3 cp client/dtmf-status-panel/index.html \
  s3://YOUR-PANEL-BUCKET-NAME/dtmf-panel/index.html \
  --content-type "text/html" \
  --cache-control "no-cache"

# Step 5: Create a CloudFront distribution via the AWS console
#  Console > CloudFront > Create distribution
#  Origin: YOUR-PANEL-BUCKET-NAME.s3.eu-west-2.amazonaws.com
#  Origin access: OAC (create new)
#  Default root object: dtmf-panel/index.html
#  Viewer protocol: Redirect HTTP to HTTPS
#  Click Create distribution

# Step 6: Note the CloudFront domain name (e.g. d1234abcdef567.cloudfront.net)
# Then complete Steps 6.2 and 6.3 above.
```

---

# Phase 7 — Session Attribute Reference

In every **Get customer input** (Lex) block in your contact flows, add these session attribute mappings so ARIA receives the complete DTMF context on every conversation turn.

**How to add in the flow designer:**

1. Open your main inbound contact flow > Edit
2. Double-click the **Get customer input** (Lex) block
3. Scroll down to **Session attributes**
4. Click **Add attribute** for each row below
5. Set **Key** = session attribute key, **Type** = Contact attribute, **Attribute** = contact attribute key
6. Click **Save** > **Publish**

| Session attribute key (ARIA reads this) | Contact attribute key |
|---|---|
| `dtmf_result` | `dtmf_result` |
| `dtmf_masked` | `dtmf_masked` |
| `dtmf_last_four` | `dtmf_last_four` |
| `dtmf_purpose` | `collectionPurpose` |
| `dtmf_validation_status` | `dtmf_validation_status` |
| `dtmf_card_type` | `dtmf_card_type` |
| `dtmf_card_nickname` | `dtmf_card_nickname` |
| `dtmf_requires_escalation` | `dtmf_requires_escalation` |
| `dtmf_status` | `dtmf_status` |
| `aria_status` | `aria_status` |
| `aria_retry_count` | `aria_retry_count` |

---

# Phase 8 — Key Rotation (Annual Security Requirement)

RSA keys must be rotated at least annually. Amazon Connect supports 2 active security keys simultaneously — enabling zero-downtime rotation.

## Rotation Procedure

```bash
./scripts/setup_dtmf_keys.sh rotate --region eu-west-2
```

This script:
1. Generates a new RSA key pair on your laptop
2. Stores the new private key in Secrets Manager as `meridian/connect/dtmf-private-key-v2`
3. Guides you through uploading the new public key to Connect
4. Updates the Lambda environment variable to point to the new key ID

**After rotation:**
- New calls immediately use the new key
- Calls already in progress continue using the old key (key ID is embedded in the ciphertext)
- Wait for all active contacts to close (check Contact Trace Records in Connect)
- Then: Connect console > Security keys > delete the old key
- Then: `aws secretsmanager delete-secret --secret-id meridian/connect/dtmf-private-key --region eu-west-2`

---

# Phase 9 — End-to-End Testing

---

## Test 1 — Decrypt Lambda in Isolation

> You need a real ciphertext produced by Amazon Connect. You cannot make one up.

1. Call your Connect number and press digits when prompted
2. After the call, open **Connect > Analytics > Contact search** > find your contact > open it
3. Find `StoredCustomerInput` in the contact attributes and copy the base64 value
4. In the Lambda console, test with this payload:

```json
{
  "Details": {
    "ContactData": {
      "ContactId": "test-001",
      "Attributes": { "collectionPurpose": "card_last_four" }
    },
    "Parameters": {
      "encryptedValue": "PASTE_REAL_BASE64_HERE",
      "purpose": "card_last_four"
    }
  }
}
```

Expected response:

```json
{
  "status": "success",
  "maskedValue": "****4821",
  "digitCount": 4,
  "lastFour": "4821",
  "cardBin": "",
  "errorMessage": ""
}
```

---

## Test 2 — Validate Lambda in Isolation

Seed the DynamoDB tables first (Step 1.5). Then test:

```json
{
  "Details": {
    "ContactData": {
      "ContactId": "test-001",
      "Attributes": {
        "customerId": "CUST-001",
        "authStatus": "authenticated",
        "dtmf_card_bin": "414900"
      }
    },
    "Parameters": {
      "cardLastFour": "8901",
      "cardBin": "414900",
      "digitCount": "4",
      "purpose": "card_verification",
      "authStatus": "authenticated"
    }
  }
}
```

Expected:

```json
{
  "isValid": "true",
  "validationStatus": "valid",
  "cardType": "VISA_DEBIT",
  "cardNickname": "Everyday Debit",
  "requiresEscalation": "false",
  "errorMessage": ""
}
```

---

## Test 3 — Full End-to-End: AI Agent Path

1. Call your Connect inbound number
2. Do NOT authenticate — proceed as an unrecognised caller
3. Say: `"I'd like to check my credit card balance"`
4. ARIA should say it needs to identify the card and transfer you briefly
5. Hear: `"Please enter the last four digits of your card number, followed by the hash key"`
6. Press 4 digits then `#`
7. Hear: `"Thank you. I have securely captured your card details."`
8. ARIA resumes: `"I can see your card ending ****XXXX..."`

---

## Test 4 — Full End-to-End: Human Agent Path

1. Log into CCP as agent — set Available
2. Call the Connect number as a customer
3. Accept as agent
4. Click Quick connects icon > `Collect Card — Secure`
5. Agent: hear hold music
6. Customer: hear announcement + keypad prompt > press digits > hear thank you
7. Agent: reconnected — hear completion announcement
8. Agent: open Contact Attributes in CCP — verify `dtmf_masked = ****XXXX`

---

## Test 5 — Fraud Escalation Path

1. Set up an authenticated test call (`customerId = CUST-001`)
2. Trigger DTMF collection (either path)
3. Enter the last 4 digits of a card NOT seeded for CUST-001
4. Expected: `dtmf_requires_escalation = "true"` in contact attributes
5. AI path: ARIA should escalate on next turn
6. Human path: CCP Status Panel shows the red escalation warning

---

# Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| Flow errors immediately after digits pressed | Wrong Key ID in `Store customer input` block | Double-click the block > DTMF tab > re-select key from dropdown |
| `Decryption error` in decrypt Lambda logs | Key pair mismatch — private key in Secrets Manager does not match public key in Connect | Verify both files were generated as a pair; re-run setup if needed |
| Lambda timeout (taking more than 8s) | `aws-encryption-sdk` Layer not attached | Lambda console > Configuration > Layers > verify `aria-dtmf-dependencies` is listed |
| Chat customer reaches the `Store` block | Channel check block not connected before Block 5 | Move Block 1 before Block 5 — channel check must be first |
| `dtmf_masked` not visible in CCP | Block 12 not on the success path | Verify Block 12 connects after the `= true` branch from Block 11 |
| All cards show `invalid_bin` | `aria-card-bins` table is empty | Seed the table with your BIN ranges (Step 1.5) |
| Ownership check always fails | `aria-customer-cards` table empty or `customerId` format mismatch | Verify `customerId` format matches `session_injector` output |
| `validation_service_error` for all calls | DynamoDB throttling or Lambda timeout | Check CloudWatch Logs for validate Lambda; check DynamoDB capacity |
| Validate Lambda takes Error branch | Lambda not granted Connect invoke permission | Run: `aws lambda add-permission --function-name aria-dtmf-validate --statement-id ConnectInvoke --action lambda:InvokeFunction --principal connect.amazonaws.com --source-account YOUR_ACCOUNT --region eu-west-2` |
| ARIA never returns `CollectCardDetails` intent | `dtmf_collection_requested` flag not being set | Check MCP tool Lambda CloudWatch logs |
| ARIA returns the intent but flow does not branch | Intent not added to the `Get customer input` block | Open block > Intents > add `CollectCardDetails` |
| Agent cannot see the Quick Connect | Routing profile not updated | Add Quick Connect to agent's routing profile (Step 5.4) |
| `Hold customer or agent` block fails | Agent not connected to a call | Wrapper flow can only run when agent is on an active call |
| CCP Status Panel not loading | Domain not in Approved origins | Connect > Your instance > Approved origins > add CloudFront domain |
| Panel shows stale/frozen status | Validate Lambda missing `connect:UpdateContactAttributes` permission | Add the IAM permission to `aria-lambda-dtmf-validate-role` |
| CloudFront returns 403 Forbidden | S3 bucket policy not granting CloudFront OAC access | Re-run the `deploy-panel` command — it applies the bucket policy automatically |

---

# Security Checklist

Before going live, verify all of these:

- [ ] Private key deleted from all developer laptops after being stored in Secrets Manager
- [ ] Secrets Manager secret uses your CMK (not the default AWS managed key) for encryption
- [ ] Lambda CloudWatch logs contain no raw digits (search logs for your test card numbers)
- [ ] DynamoDB tables have encryption at rest enabled (verify in console — on by default)
- [ ] IAM roles use minimum permissions — no wildcard actions except where documented
- [ ] Contact Trace Records do not contain raw digits (check via Analytics > Contact search)
- [ ] Key rotation scheduled for 12 months from today (add a calendar reminder now)
- [ ] `aria-card-bins` seeded with only your approved BIN ranges
- [ ] `aria-customer-cards` populated with nightly sync from core banking
- [ ] Ownership escalation path tested with a card NOT belonging to the test customer
- [ ] CCP Status Panel URL added to both Approved origins AND Application integration in Connect
- [ ] CloudFront distribution uses HTTPS-only (redirect-to-https viewer protocol)

---

# Contact Attribute Reference

| Attribute | Written by | Safe to show agent? | Safe for ARIA to say aloud? |
|---|---|---|---|
| `dtmf_result` | Sub-flow Block 12 / failure blocks | Yes | Yes — status only |
| `dtmf_masked` | Sub-flow Block 12 | Yes | Yes — "your card ending ****4821" |
| `dtmf_last_four` | Sub-flow Block 12 | Yes | No — for tool calls only |
| `dtmf_digit_count` | Sub-flow Block 12 | Yes | No — not needed in speech |
| `dtmf_validation_status` | Sub-flow Block 12 | Yes | Yes — drives ARIA's response logic |
| `dtmf_card_type` | Sub-flow Block 12 | Yes | Yes — "your Visa Debit card" |
| `dtmf_card_nickname` | Sub-flow Block 12 | Yes | Yes — "your Everyday Debit card" |
| `dtmf_status` | Set throughout the flow | Yes (for CCP panel) | No — internal only |
| `dtmf_requires_escalation` | Validate Lambda | Yes | Yes — drives ARIA escalation logic |
| `dtmf_error_msg` | Validate Lambda | Yes (non-technical) | No — do not say error details aloud |
| `dtmf_card_bin` | Sub-flow Block 9 | Not needed | No |
| `collectionPurpose` | Pre-sub-flow blocks | Yes | No — internal |
| `connectKeyId` | Pre-sub-flow blocks | Yes | No — internal |
| `dtmf_collection_requested` | MCP tool Lambda | No — internal bridge flag | Never |
| `agentMode` | Human wrapper flow only | Yes | No — internal |

---

*Guide authored for ARIA Banking Agent — Meridian Bank, region `eu-west-2`.*  
*Lambda source files: `scripts/lambdas/aria_dtmf_decrypt.py`, `scripts/lambdas/aria_dtmf_validate.py`, `scripts/lambdas/mcp_tools/aria_dtmf_handler.py`*  
*CCP Status Panel: `client/dtmf-status-panel/index.html`*  
*Deploy scripts: `scripts/deploy_dtmf_lambda.sh`, `scripts/setup_dtmf_keys.sh`*  
*Always verify against the [Amazon Connect Administrator Guide](https://docs.aws.amazon.com/connect/latest/adminguide/).*
