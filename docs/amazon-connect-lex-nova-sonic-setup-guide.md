# Step-by-Step: Connect ARIA to Amazon Connect via Lex V2 + Nova Sonic S2S

> **Goal**: Route PSTN telephone calls to your existing ARIA AgentCore banking agent using Amazon Connect + Amazon Lex V2 + Amazon Nova Sonic Speech-to-Speech.  
> **Stack**: Existing ARIA agent running on `arn:aws:bedrock-agentcore:eu-west-2:395402194296:runtime/aria_banking_agent-ubLoKG8xsY`  
> **Region**: eu-west-2 (London) throughout unless stated

---

## Architecture Recap (What You're Building)

```
Phone Call (PSTN)
    ↓
Amazon Connect (eu-west-2)
    ↓  Contact Flow
Amazon Lex V2 Bot  ←→  Nova Sonic S2S (speech ↔ speech)
    ↓  Lambda fulfillment (every turn)
aria-connect-fulfillment (Lambda)
    ↓  HTTP POST + SigV4
ARIA AgentCore Runtime  (your existing stack, unchanged)
    ↓
ARIA Strands Agent → banking tools → response text
    ↑
Nova Sonic speaks the response back to the caller
```

**Nothing changes in your existing AgentCore/ARIA code.** You are adding:
1. An Amazon Connect instance
2. A Lex V2 bot (just a shell — ARIA handles all NLU)
3. A Lambda function (the bridge from Lex → AgentCore)
4. A Contact Flow in Connect

---

## Prerequisites

| Item | Requirement |
|---|---|
| AWS Account | Same account as your AgentCore runtime (`395402194296`) |
| IAM | Admin or a user with `AmazonConnect_FullAccess`, `AmazonLexFullAccess`, `AWSLambda_FullAccess` |
| AWS CLI | Configured with `aws configure` pointing to `eu-west-2` |
| AgentCore runtime | Running and reachable (verified from prior deployment) |
| Runtime ARN | `arn:aws:bedrock-agentcore:eu-west-2:395402194296:runtime/aria_banking_agent-ubLoKG8xsY` |

---

## Part 1 — Create the Amazon Connect Instance

> Official docs: [Create an Amazon Connect instance](https://docs.aws.amazon.com/connect/latest/adminguide/amazon-connect-instances.html)

### Step 1.1 — Open the Connect Console

1. Go to [https://console.aws.amazon.com/connect/](https://console.aws.amazon.com/connect/)
2. Make sure your region selector (top right) shows **Europe (London) eu-west-2**
3. Click **Get started** (or **Add an instance** if you have existing instances)

### Step 1.2 — Configure Identity

1. Select **Store users in Amazon Connect** (simplest for initial setup)
2. In **Access URL**, enter a unique subdomain: `meridian-aria`
   - Your Connect admin URL will be: `https://meridian-aria.my.connect.aws`
3. Click **Next**

### Step 1.3 — Add Administrator

1. Select **Specify an administrator**
2. Fill in:
   - **First name**: Admin
   - **Last name**: Meridian
   - **Username**: `admin`
   - **Password**: (strong password — you'll use this to log into Connect)
   - **Email**: (your email)
3. Click **Next**

### Step 1.4 — Configure Telephony

1. Check ✅ **Receive inbound calls with Amazon Connect**
2. Check ✅ **Make outbound calls with Amazon Connect**
3. Check ✅ **Enable early media**
4. Click **Next**

### Step 1.5 — Data Storage

1. Leave defaults (Connect creates an S3 bucket automatically)
2. Note the S3 bucket name shown (e.g., `amazon-connect-xxxxxxxxxxxx`)
3. Click **Next**

### Step 1.6 — Review and Create

1. Review settings
2. Click **Create instance**
3. Wait ~2 minutes for provisioning
4. Note your **Instance ARN** — you'll need it later:
   - Format: `arn:aws:connect:eu-west-2:395402194296:instance/XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX`

### Step 1.7 — Claim a Phone Number

1. Once the instance is created, click **Get started** on the confirmation screen
2. Or go to: Connect admin → **Channels** → **Phone numbers** → **Claim a number**
3. Select:
   - **Country**: United Kingdom
   - **Type**: DID (Direct Inward Dial) for a local number, or Toll Free
   - Pick any available number
4. Under **Flow/IVR**: leave blank for now (you'll assign it after creating the flow)
5. Click **Save**
6. Note the phone number — this is what customers will call

---

## Part 2 — Create the Lambda Fulfillment Function

> Create this **before** the Lex bot, because the bot needs to reference it.

### Step 2.1 — Create the Lambda IAM Role

1. Go to [https://console.aws.amazon.com/iam/](https://console.aws.amazon.com/iam/)
2. Click **Roles** → **Create role**
3. **Trusted entity type**: AWS service
4. **Use case**: Lambda
5. Click **Next**
6. Search for and attach: **AWSLambdaBasicExecutionRole**
7. Click **Next**, name the role: `aria-connect-fulfillment-role`
8. Click **Create role**

Now add the AgentCore permission:

9. Click on the newly created role `aria-connect-fulfillment-role`
10. Click **Add permissions** → **Create inline policy**
11. Click the **JSON** tab and paste:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InvokeARIAAgentCore",
      "Effect": "Allow",
      "Action": "bedrock-agentcore:InvokeAgentRuntime",
      "Resource": "arn:aws:bedrock-agentcore:eu-west-2:395402194296:runtime/aria_banking_agent-ubLoKG8xsY"
    }
  ]
}
```

12. Click **Next**, name it `aria-agentcore-invoke`, click **Create policy**

### Step 2.2 — Create the Lambda Function

1. Go to [https://console.aws.amazon.com/lambda/](https://console.aws.amazon.com/lambda/)
2. Make sure region is **eu-west-2**
3. Click **Create function**
4. Select **Author from scratch**
5. Configure:
   - **Function name**: `aria-connect-fulfillment`
   - **Runtime**: Python 3.12
   - **Architecture**: x86_64
   - **Execution role**: **Use an existing role** → `aria-connect-fulfillment-role`
6. Click **Create function**

### Step 2.3 — Add the Function Code

1. In the Lambda console, click the **Code** tab
2. Click the file `lambda_function.py` in the editor
3. Replace all contents with:

```python
"""
aria_connect_fulfillment.py

Lambda fulfillment function for the ARIA-Connect-Bot Lex V2 bot.
Called on every conversation turn by Amazon Lex V2.

Flow:
  Amazon Connect (PSTN voice) 
    → Lex V2 + Nova Sonic S2S (speech ↔ text)
      → This Lambda (every turn)
        → ARIA AgentCore HTTP /invocations
          → ARIA Strands agent response (plain text)
        → Lex response → Nova Sonic speaks it back

Environment variables required:
  AGENTCORE_ENDPOINT  — full HTTPS URL to the AgentCore runtime invocations endpoint

Session continuity:
  ContactId from Amazon Connect is used as the AgentCore session ID.
  This keeps the Strands agent state (auth, conversation history) consistent
  across all turns of a single phone call.
"""

import json
import logging
import os
import urllib.request
import urllib.error
import hashlib
import hmac
import datetime

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
AGENTCORE_ENDPOINT = os.environ.get(
    "AGENTCORE_ENDPOINT",
    "https://bedrock-agentcore.eu-west-2.amazonaws.com"
    "/runtimes/arn%3Aaws%3Abedrock-agentcore%3Aeu-west-2%3A395402194296"
    "%3Aruntime%2Faria_banking_agent-ubLoKG8xsY/invocations"
)
AWS_REGION = os.environ.get("AWS_REGION", "eu-west-2")
SERVICE    = "bedrock-agentcore"

# Phrases that signal ARIA wants to escalate to a human agent
ESCALATION_PHRASES = [
    "speak to an agent",
    "speak to someone",
    "transfer me",
    "transfer you",
    "human agent",
    "real person",
    "talk to a person",
    "connect you with",
    "one of our advisors",
    "one of our agents",
]


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------
def lambda_handler(event, context):
    logger.info("Lex event: %s", json.dumps(event, default=str))

    session_state  = event.get("sessionState", {})
    intent_name    = session_state.get("intent", {}).get("name", "FallbackIntent")
    input_transcript = event.get("inputTranscript", "").strip()
    session_attrs  = session_state.get("sessionAttributes", {}) or {}

    # ContactId from Amazon Connect → used as AgentCore session ID
    # Connect passes ContactId inside requestAttributes
    request_attrs  = event.get("requestAttributes", {}) or {}
    contact_id     = (
        request_attrs.get("ContactId")
        or session_attrs.get("contactId")
        or event.get("sessionId", "unknown-session")
    )

    # Store contactId in session attributes so it persists across turns
    session_attrs["contactId"] = contact_id

    logger.info(
        "Turn: intent=%s contactId=%s transcript=%r",
        intent_name, contact_id, input_transcript
    )

    # ------------------------------------------------------------------
    # Handle explicit TransferToAgent intent (customer said "agent" etc.)
    # ------------------------------------------------------------------
    if intent_name == "TransferToAgent":
        session_attrs["escalate"] = "true"
        return _build_close_response(
            "Of course. Let me connect you with one of our advisors now. "
            "Please hold for a moment.",
            session_attrs,
            escalate=True,
        )

    # ------------------------------------------------------------------
    # Nothing to say — shouldn't happen but guard anyway
    # ------------------------------------------------------------------
    if not input_transcript:
        return _build_elicit_response(
            "I'm sorry, I didn't quite catch that. Could you say that again?",
            session_attrs,
        )

    # ------------------------------------------------------------------
    # Call ARIA AgentCore
    # ------------------------------------------------------------------
    try:
        aria_response = _call_agentcore(input_transcript, contact_id)
    except Exception as exc:
        logger.error("AgentCore call failed: %s", exc, exc_info=True)
        return _build_elicit_response(
            "I'm sorry, I'm having a technical issue right now. "
            "Please bear with me, or press 0 to speak with an advisor.",
            session_attrs,
        )

    logger.info("ARIA response (session=%s): %r", contact_id, aria_response[:200])

    # ------------------------------------------------------------------
    # Detect escalation in ARIA's response
    # ------------------------------------------------------------------
    escalate = any(phrase in aria_response.lower() for phrase in ESCALATION_PHRASES)
    if escalate:
        session_attrs["escalate"] = "true"
        return _build_close_response(aria_response, session_attrs, escalate=True)

    # ------------------------------------------------------------------
    # Continue the conversation
    # ------------------------------------------------------------------
    return _build_elicit_response(aria_response, session_attrs)


# ---------------------------------------------------------------------------
# AgentCore HTTP invocation (SigV4 signed)
# ---------------------------------------------------------------------------
def _call_agentcore(user_message: str, session_id: str) -> str:
    """POST to AgentCore /invocations, return ARIA's plain-text response."""
    body = json.dumps({"message": user_message}).encode("utf-8")

    # Get credentials from Lambda's execution role
    session = boto3.Session()
    creds   = session.get_credentials().get_frozen_credentials()

    headers = {
        "Content-Type": "application/json",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
    }

    # SigV4 sign the request
    aws_request = AWSRequest(
        method="POST",
        url=AGENTCORE_ENDPOINT,
        data=body,
        headers=headers,
    )
    SigV4Auth(creds, SERVICE, AWS_REGION).add_auth(aws_request)

    # Execute with urllib (no third-party deps needed)
    req = urllib.request.Request(
        AGENTCORE_ENDPOINT,
        data=body,
        headers=dict(aws_request.headers),
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=7) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body_err = e.read().decode("utf-8", errors="replace")
        logger.error("AgentCore HTTP %s: %s", e.code, body_err)
        raise RuntimeError(f"AgentCore HTTP {e.code}: {body_err}") from e

    # AgentCore returns the plain-text string from chat_handler directly
    # (no JSON wrapper — response.text() in the client reads it raw)
    return raw.strip() or "I'm processing your request. Could you give me a moment?"


# ---------------------------------------------------------------------------
# Lex V2 response builders
# ---------------------------------------------------------------------------
def _build_elicit_response(message: str, session_attrs: dict) -> dict:
    """Keep the conversation going — ask for next customer input."""
    return {
        "sessionState": {
            "dialogAction": {
                "type": "ElicitIntent",
            },
            "sessionAttributes": session_attrs,
        },
        "messages": [
            {"contentType": "PlainText", "content": message}
        ],
    }


def _build_close_response(message: str, session_attrs: dict, escalate: bool = False) -> dict:
    """End this intent (Connect flow will check escalate attribute)."""
    if escalate:
        session_attrs["escalate"] = "true"
    return {
        "sessionState": {
            "dialogAction": {"type": "Close"},
            "intent": {
                "name": "FallbackIntent",
                "state": "Fulfilled",
            },
            "sessionAttributes": session_attrs,
        },
        "messages": [
            {"contentType": "PlainText", "content": message}
        ],
    }
```

4. Click **Deploy** (orange button)

### Step 2.4 — Set Environment Variables

1. Click the **Configuration** tab → **Environment variables** → **Edit**
2. Add:
   - **Key**: `AGENTCORE_ENDPOINT`
   - **Value**: 
     ```
     https://bedrock-agentcore.eu-west-2.amazonaws.com/runtimes/arn%3Aaws%3Abedrock-agentcore%3Aeu-west-2%3A395402194296%3Aruntime%2Faria_banking_agent-ubLoKG8xsY/invocations
     ```
3. Click **Save**

### Step 2.5 — Set Timeout

1. Still in **Configuration** tab → **General configuration** → **Edit**
2. Set **Timeout** to `0 min 7 sec` (7 seconds — just under the Connect 8s limit)
3. Click **Save**

### Step 2.6 — Test the Lambda in Isolation

1. Click the **Test** tab
2. Click **Create new test event**
3. Name it `lex-test-turn`
4. Paste this test payload:

```json
{
  "messageVersion": "1.0",
  "invocationSource": "FulfillmentCodeHook",
  "inputMode": "Speech",
  "responseContentType": "audio/pcm",
  "sessionId": "test-session-001",
  "inputTranscript": "What is my account balance?",
  "bot": {
    "id": "TESTBOTID",
    "name": "ARIA-Connect-Bot",
    "localeId": "en_GB",
    "version": "DRAFT",
    "aliasId": "TSTALIASID",
    "aliasName": "TestAlias"
  },
  "sessionState": {
    "intent": {
      "name": "FallbackIntent",
      "state": "InProgress"
    },
    "sessionAttributes": {}
  },
  "requestAttributes": {
    "ContactId": "test-contact-12345"
  }
}
```

5. Click **Test**
6. You should see ARIA's response text in the **Response** section
7. If you get a permissions error, verify the IAM role and inline policy are attached

---

## Part 3 — Create the Lex V2 Bot

> Official docs: [Amazon Lex V2 Developer Guide — Creating a bot](https://docs.aws.amazon.com/lexv2/latest/dg/build-text.html)

### Step 3.1 — Create the Bot

1. Go to [https://console.aws.amazon.com/lexv2/](https://console.aws.amazon.com/lexv2/)
2. Make sure region is **eu-west-2**
3. Click **Create bot**
4. Choose **Create a blank bot**
5. Configure:
   - **Bot name**: `ARIA-Connect-Bot`
   - **Description**: `ARIA banking agent voice bot for Amazon Connect (Nova Sonic S2S)`
   - **IAM permissions**: Select **Create a role with basic Amazon Lex permissions** (Lex creates it for you)
   - **COPPA**: Select **No**
   - **Idle session timeout**: 5 minutes
6. Click **Next**

### Step 3.2 — Configure Language (Locale)

1. On the **Add language** page:
   - **Language**: English (GB)
   - **Voice interaction**: Select `Amy` from the dropdown (we'll enable Nova Sonic S2S in Connect — Amy is the compatible voice)
   - **Intent classification confidence score threshold**: `0.40` (lower threshold so FallbackIntent fires reliably)
2. Click **Done**
3. The bot opens in the Lex V2 console

### Step 3.3 — Configure the FallbackIntent

The FallbackIntent is Lex's catch-all — it fires when no other intent matches. Since ARIA handles all NLU, we want **every utterance** to go through FallbackIntent → Lambda → ARIA.

1. In the left sidebar, click **Intents**
2. Click on **FallbackIntent** (it exists by default)
3. Scroll down to **Fulfillment**
4. Under **Fulfillment**, check ✅ **Use a Lambda function for fulfillment**
5. Click **Save intent**

### Step 3.4 — Add TransferToAgent Intent (Optional but Recommended)

This gives customers an explicit way to request a human agent via DTMF or a keyword phrase.

1. Click **Add intent** → **Add empty intent**
2. **Intent name**: `TransferToAgent`
3. Under **Sample utterances**, add:
   - `speak to an agent`
   - `speak to someone`
   - `talk to a person`
   - `I want an agent`
   - `operator`
   - `human`
   - `zero` *(for pressing 0)*
4. Under **Fulfillment**, check ✅ **Use a Lambda function for fulfillment**
5. Click **Save intent**

### Step 3.5 — Build the Bot

1. Click **Build** (top right)
2. Wait for the build to complete (1–2 minutes)
3. You should see: **Build successful**

### Step 3.6 — Create a Bot Version and Alias

Aliases are required for Connect integration and Lambda hooks.

**Create Version:**
1. In the left sidebar, click **Bot versions** (under the bot name)
2. Click **Create version**
3. Leave description blank, click **Create**
4. Note the **Version number** (e.g., `1`)

**Create Alias:**
1. Click **Aliases** in the left sidebar
2. Click **Create alias**
3. Configure:
   - **Alias name**: `production`
   - **Associate with a version**: select the version you just created (e.g., `1`)
4. Click **Create**

### Step 3.7 — Attach Lambda to the Alias

1. Click on the `production` alias you just created
2. Click the **Languages** tab
3. Click on **English (GB)**
4. Under **Source**, select the Lambda function `aria-connect-fulfillment`
5. Under **Lambda function version or alias**: `$LATEST`
6. Click **Save**

**Grant Lex permission to invoke Lambda:**

7. Go to the Lambda console → `aria-connect-fulfillment` → **Configuration** → **Permissions**
8. Under **Resource-based policy statements**, click **Add permissions**
9. Configure:
   - **Select a statement ID**: `lex-invoke-permission`
   - **Principal**: `lexv2.amazonaws.com`
   - **Action**: `lambda:InvokeFunction`
   - **Source ARN**: (your Lex bot alias ARN — find it in the Lex console under the alias details)
     Format: `arn:aws:lex:eu-west-2:395402194296:bot-alias/BOTID/ALIASID`
10. Click **Save**

> **Tip**: Alternatively, run via CLI:
> ```bash
> aws lambda add-permission \
>   --function-name aria-connect-fulfillment \
>   --statement-id lex-invoke-permission \
>   --action lambda:InvokeFunction \
>   --principal lexv2.amazonaws.com \
>   --source-arn "arn:aws:lex:eu-west-2:395402194296:bot-alias/YOUR_BOT_ID/YOUR_ALIAS_ID" \
>   --region eu-west-2
> ```

---

## Part 4 — Configure Nova Sonic Speech-to-Speech in Amazon Connect

> Official docs: [Configure Amazon Nova Sonic Speech-to-Speech](https://docs.aws.amazon.com/connect/latest/adminguide/nova-sonic-speech-to-speech.html)

Nova Sonic S2S is configured on the **Amazon Connect Conversational AI bot** — this is Connect's wrapper around the Lex V2 bot that enables speech processing.

### Step 4.1 — Add the Lex Bot to Your Connect Instance

1. Go to [https://console.aws.amazon.com/connect/](https://console.aws.amazon.com/connect/)
2. Click on your instance alias (`meridian-aria`)
3. In the left sidebar, click **Flows**
4. Scroll down to **Amazon Lex** section
5. Under **Lex V2 bots**, select `ARIA-Connect-Bot` from the dropdown
6. Select the alias: `production`
7. Click **Add Amazon Lex Bot**
8. Confirm it appears in the list

### Step 4.2 — Open the Bot in Connect's AI Bot Interface

Amazon Connect has its own "Conversational AI bot" view that wraps the Lex bot.

1. In the Connect admin sidebar, click **Channels** → **Bots** (or navigate to `https://meridian-aria.my.connect.aws/bots`)
2. You should see `ARIA-Connect-Bot` listed
3. Click on it to open the bot configuration

### Step 4.3 — Enable Nova Sonic S2S on the Locale

1. On the bot configuration page, click the **Configuration** tab
2. Click on the **en-GB** locale row
3. In the **Speech model** section, click **Edit**
4. A modal opens. In **Model type** dropdown, select: **Speech-to-Speech**
5. In **Voice provider** dropdown, select: **Amazon Nova Sonic**
6. Click **Confirm**

### Step 4.4 — Build the Locale

1. If you see **Unbuilt changes** next to the en-GB locale, click **Build language**
2. Wait for the build to complete (1–2 minutes)
3. The Speech model card should now show: `Speech-to-Speech: Amazon Nova Sonic`

---

## Part 5 — Create the Contact Flow

> Official docs: [Create contact flows](https://docs.aws.amazon.com/connect/latest/adminguide/create-contact-flow.html)

The Contact Flow is the visual IVR logic in Connect. It orchestrates the call: plays greetings, invokes the bot, handles escalation.

### Step 5.1 — Open the Flow Designer

1. In the Connect admin sidebar, click **Routing** → **Flows**
2. Click **Create flow**
3. Name it: `Meridian-ARIA-Inbound`

### Step 5.2 — Build the Flow

Connect flows use drag-and-drop blocks. Build the following flow in order:

---

#### Block 1: Entry Point (already exists)
- This is the starting block. Leave it as-is.

---

#### Block 2: Set Voice (enables Nova Sonic)

1. In the left panel, search for **Set voice**
2. Drag it onto the canvas
3. Connect the **Entry Point** output arrow → **Set voice** input
4. Click on the **Set voice** block to configure:
   - **Voice provider**: Amazon
   - **Language**: English (United Kingdom)
   - **Voice**: Amy
   - Scroll down to **Other settings**
   - Check ✅ **Override speaking style**
   - Select: **Generative** ← this is what enables Nova Sonic expressive audio
5. Click **Save**

---

#### Block 3: Set Contact Attributes (stores ContactId for Lambda)

1. Search for **Set contact attributes**
2. Drag it after **Set voice**
3. Connect **Set voice** Success → **Set contact attributes**
4. Click the block to configure:
   - Click **Add attribute**
   - **Destination key**: `contactId`
   - **Type**: System
   - **Attribute**: `Contact ID`
5. Click **Save**

---

#### Block 4: Get Customer Input (the ARIA Lex bot interaction)

1. Search for **Get customer input**
2. Drag it after **Set contact attributes**
3. Connect **Set contact attributes** Success → **Get customer input**
4. Click the block to configure:

   **Text to speech or chat text section:**
   - Select **Enter text**
   - Type: `Welcome to Meridian Bank. I'm ARIA, your automated banking assistant. How can I help you today?`
   - *(This first prompt is spoken by Nova Sonic as ARIA's greeting)*

   **Amazon Lex section:**
   - Click the **Amazon Lex** tab
   - **Bot**: `ARIA-Connect-Bot`
   - **Alias**: `production`
   
   **Intents section:**
   - Click **Add an intent**
   - Type `FallbackIntent`, press Enter
   - Click **Add another intent**
   - Type `TransferToAgent`, press Enter

   **Session attributes section (passes ContactId to Lambda):**
   - Click **Add an attribute**
   - **Destination key**: `ContactId`
   - **Type**: System
   - **Attribute**: `Contact ID`

5. Click **Save**

The **Get customer input** block will now have multiple output branches:
- **FallbackIntent** (ARIA handled the turn → loop back)
- **TransferToAgent** (customer requested human)
- **Default** (no intent matched)
- **Error** (something went wrong)
- **Timeout** (customer was silent)

---

#### Block 5: Check for Escalation (Decision block)

After the Lex bot turn, check whether ARIA set the escalate flag.

1. Search for **Check contact attributes**
2. Drag it after **Get customer input** (FallbackIntent branch)
3. Connect **Get customer input** `FallbackIntent` output → **Check contact attributes**
4. Configure:
   - **Attribute to check**: User-defined
   - **Attribute key**: `escalate`
   - **Condition**: Equals
   - **Value**: `true`
5. Click **Save**

This block has two branches:
- **Match** (escalate = true → go to human agent)
- **No match** (normal turn → loop back to bot)

---

#### Block 6: Loop Back (no escalation)

Connect the **Check contact attributes** → **No match** output back to the **Get customer input** block input. This creates the conversation loop.

> ⚠️ In Connect flow designer, to create a loop, drag from the **No match** output of the check block back to the **Get customer input** block's top input. You may need to rearrange blocks on the canvas to make the arrow visible.

---

#### Block 7: Escalation Path — Play Prompt

1. Search for **Play prompt**
2. Drag it onto the canvas
3. Connect both:
   - **Check contact attributes** → **Match** output → **Play prompt**
   - **Get customer input** → **TransferToAgent** output → **Play prompt**
4. Configure:
   - Select **Enter text**
   - Type: `Let me connect you with one of our advisors. Please hold for a moment.`
5. Click **Save**

---

#### Block 8: Set Queue (for human agent routing)

1. Search for **Set working queue**
2. Drag it after **Play prompt**
3. Connect **Play prompt** Success → **Set working queue**
4. Configure:
   - **Queue**: Select **BasicQueue** (the default queue — you can create a dedicated queue later)
5. Click **Save**

---

#### Block 9: Transfer to Queue

1. Search for **Transfer to queue**
2. Drag it after **Set working queue**
3. Connect **Set working queue** Success → **Transfer to queue**
4. The **Transfer to queue** block has these outputs:
   - **At capacity** → connect to a **Play prompt** ("All advisors are busy, please call back later") → **Disconnect**
   - **Error** → connect to a **Disconnect** block

---

#### Block 10: Error + Timeout Handling

1. Search for **Disconnect / hang up** (or **Disconnect**)
2. Add one for the error path from **Get customer input**
3. Optionally add a **Play prompt** before it: `I'm sorry, I encountered a technical issue. Please call back or visit our website.`
4. Connect:
   - **Get customer input** → **Error** → (optional prompt) → **Disconnect**
   - **Get customer input** → **Timeout** → loop back to **Get customer input** or → **Disconnect**

---

#### Complete Flow Diagram (Text)

```
[Entry Point]
    ↓
[Set Voice: Amy, Generative]
    ↓
[Set Contact Attributes: contactId = $.ContactId]
    ↓
[Get Customer Input: ARIA-Connect-Bot / production]  ←────────────┐
    ↓ FallbackIntent                                               │
[Check Contact Attributes: escalate == "true"]                    │
    ↓ No Match ───────────────────────────────────────────────────┘
    ↓ Match
[Play Prompt: "Connecting you with an advisor..."]
    ↓
[TransferToAgent] ──→ same Play Prompt + Set Queue + Transfer
    ↓
[Set Working Queue: BasicQueue]
    ↓
[Transfer to Queue]
    ↓ At capacity / Error
[Play Prompt: "All advisors busy..."]
    ↓
[Disconnect]
```

### Step 5.3 — Save and Publish the Flow

1. Click **Save** (top right)
2. Click **Publish**
3. Confirm publish — the flow is now live

---

## Part 6 — Assign the Flow to Your Phone Number

1. In the Connect admin, go to **Channels** → **Phone numbers**
2. Click on the phone number you claimed in Part 1
3. Under **Flow/IVR**, select `Meridian-ARIA-Inbound`
4. Click **Save**

---

## Part 7 — Test End-to-End

### Step 7.1 — Test via Connect's Built-in Softphone

1. Log into the Connect admin at `https://meridian-aria.my.connect.aws`
2. Click the phone icon (top right) to open the Contact Control Panel (CCP)
3. Set your status to **Available**
4. Call your phone number from any external phone
5. You should hear ARIA's greeting (Amy's voice, Nova Sonic quality)
6. Say: *"What's my account balance?"*
7. ARIA should respond with the authentication flow
8. Complete auth: say your customer ID and date of birth
9. ARIA responds with account details

### Step 7.2 — Test Escalation

1. During a call, say: *"I want to speak to an agent"*
2. ARIA should say the escalation message
3. The call should route to the Connect queue
4. In the CCP, you (as the agent) should receive the call

### Step 7.3 — Check CloudWatch Logs

Lambda logs appear in CloudWatch under:
`/aws/lambda/aria-connect-fulfillment`

Each turn logs:
- The input transcript
- The ContactId (= AgentCore session ID)
- ARIA's response (first 200 chars)
- Any errors

To view: AWS Console → CloudWatch → Log groups → `/aws/lambda/aria-connect-fulfillment`

---

## Part 8 — Add the Lambda Function to Connect (Required for Direct Lambda Invocation)

If you want to also invoke Lambda directly from Contact Flows (not just via Lex), register it:

1. Connect admin console → your instance → **Flows**
2. Scroll to **AWS Lambda** section
3. Select `aria-connect-fulfillment` from the dropdown
4. Click **Add Lambda Function**

---

## Troubleshooting

### "No response / silence after greeting"
- Check that the **Set voice** block has **Override speaking style: Generative** enabled
- Verify the Lex bot locale shows `Speech-to-Speech: Amazon Nova Sonic` (not just ASR+Polly)
- Check Lambda logs for errors invoking AgentCore

### "Lambda timeout" error
- Lambda timeout is 7s. AgentCore tool calls (account lookups) should complete within ~5s
- If ARIA is calling multiple tools, consider using the async Lambda invocation mode in the flow block (60s timeout). Add a **Play prompt** ("Please hold a moment...") before the **Get customer input** block so callers don't hear silence

### "Access denied" from Lambda → AgentCore
- Verify the Lambda execution role has `bedrock-agentcore:InvokeAgentRuntime` permission on the correct runtime ARN
- Check the IAM inline policy `aria-agentcore-invoke` is attached to `aria-connect-fulfillment-role`
- Run a test in the Lambda console — error messages will show the exact IAM denial

### "Lex intent not firing Lambda"
- Verify the Lambda is attached to the **alias** (`production`), not just the bot
- Check that the correct Lambda function version is referenced in the alias configuration
- Check the resource-based policy on the Lambda allows `lexv2.amazonaws.com` to invoke it

### "ARIA asks for customer ID every turn" (re-auth loop)
- This means the ContactId is not being passed correctly → each Lambda call generates a new AgentCore session
- Check the **Get customer input** block has the session attribute `ContactId` set
- Check Lambda logs: `contactId` in the log output should be a fixed UUID-like value for the entire call

### "Voice sounds like Polly, not Nova Sonic"
- The `Set voice` block must have **Generative** style selected (not Neural or Standard)
- The Lex bot locale in Connect must show `Speech-to-Speech: Amazon Nova Sonic`
- If you see inconsistent voices, make sure no other `Set voice` blocks in the flow use a non-Nova-Sonic Polly voice

### "Call goes to error branch immediately"
- Check the flow connections in the designer — ensure all blocks are connected
- Check CloudWatch Logs for the Connect instance under `aws/connect/{instance-alias}`
- Verify the Lex bot alias `production` is built and attached to the Lambda

---

## Next Steps After Basic Integration Works

| Enhancement | How |
|---|---|
| Dedicated human agent queues | Create queues in Connect: `meridian-general`, `meridian-id-v` |
| Call recording | Already enabled by default — review in Connect → Analytics |
| Contact Lens (PII redaction) | Connect admin → Analytics → Contact Lens → Enable |
| Business hours routing | Add **Check hours of operation** block before the bot |
| Wait time announcement | Before **Transfer to queue**, add **Get queue metrics** → **Play prompt** with `$.Queue.EstimatedWaitTime` |
| Callback when queue is full | Add **Set callback number** → **Transfer to queue** with callback enabled |
| Chat channel | Create a new flow using the same Lambda (detects `channel=CHAT` from contact data) |
| SMS via Pinpoint | Connect → Channels → SMS (attach Pinpoint) |
| Outbound calling (payment reminders) | Amazon Connect Campaigns → Outbound dialler |

---

## Reference Values

| Item | Value |
|---|---|
| AgentCore Runtime ARN | `arn:aws:bedrock-agentcore:eu-west-2:395402194296:runtime/aria_banking_agent-ubLoKG8xsY` |
| AgentCore Endpoint | `https://bedrock-agentcore.eu-west-2.amazonaws.com/runtimes/arn%3Aaws%3A...` |
| Lex Bot Name | `ARIA-Connect-Bot` |
| Lex Bot Alias | `production` |
| Lambda Function | `aria-connect-fulfillment` |
| Lambda IAM Role | `aria-connect-fulfillment-role` |
| Connect Instance | `meridian-aria.my.connect.aws` |
| Connect Region | `eu-west-2` |
| Nova Sonic Voice | `Amy` (en-GB, Feminine, Generative) |
| AgentCore Chat Payload Key | `message` (field name in the POST body) |
| AgentCore Session Header | `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` |

---

*Based on official AWS documentation: Amazon Connect Administrator Guide (Nova Sonic S2S configuration), Amazon Lex V2 Developer Guide (Lambda integration), AWS Lambda Developer Guide, Amazon Bedrock AgentCore Developer Guide (bidirectional streaming, runtime invocation).*
