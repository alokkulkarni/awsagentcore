# Step-by-Step: Connect ARIA to Amazon Connect via Lex V2 + Nova Sonic S2S

> **Goal**: Route PSTN telephone calls to your existing ARIA AgentCore banking agent using Amazon Connect + Amazon Lex V2 + Amazon Nova Sonic Speech-to-Speech.
> **Stack**: Existing ARIA agent running on `arn:aws:bedrock-agentcore:eu-west-2:395402194296:runtime/aria_banking_agent-ubLoKG8xsY`
> **Region**: eu-west-2 (London) throughout unless stated
> **Level**: Step-by-step for beginners — every click is described

---

## How the Whole Thing Works (Read This First)

Before touching the AWS console, take 2 minutes to understand what each piece does and why it exists.

```
+------------------------------------------------------------------------+
|  PSTN Phone Call                                                       |
|       |                                                                |
|       v                                                                |
|  Amazon Connect  ---- Contact Flow runs top-to-bottom ---->           |
|       |                                                                |
|       |  Block 1: Entry Point         (call arrives here)             |
|       |  Block 2: Set Voice           (enable Nova Sonic audio)       |
|       |  Block 3: Set Contact Attrs   (store ContactId)               |
|       |  Block 4: Invoke Lambda  <--- aria-session-injector           |
|       |              |                Looks up caller by phone/CRM    |
|       |              |                Returns: customerId, authStatus  |
|       |  Block 5: Set Contact Attrs   (store customerId + authStatus  |
|       |                               from Lambda result)             |
|       |  Block 6: Get Customer Input  <--- ARIA-Connect-Bot (Lex V2)  |
|       |    |  (loops every turn)           + Nova Sonic S2S           |
|       |    |                               + aria-lex-fulfillment     |
|       |    |  Every turn the fulfillment Lambda:                      |
|       |    |    - Reads contactId, customerId, authStatus             |
|       |    |    - POSTs to AgentCore with those attributes            |
|       |    |    - Returns ARIA response -> Nova Sonic speaks it       |
|       |    |                                                           |
|       |    +-- FallbackIntent --> Block 7: Check escalate flag        |
|       |    |                          +-- escalate=true --> Transfer  |
|       |    |                          +-- escalate=false --> loop  <--+
|       |    +-- TransferToAgent --> Transfer to agent queue            |
|       |    +-- Error ----------->  Play Error Prompt -> Disconnect    |
|       |    +-- Timeout ----------> loop back                         |
+------------------------------------------------------------------------+
```

### The Two Lambdas Explained

**Lambda 1 - `aria-session-injector`** (runs ONCE at call start, before Lex)

This Lambda runs when the call first arrives, before any conversation starts. It:
1. Receives the caller's **phone number** and **ContactId** from Connect
2. Looks up whether that phone number matches a known customer in the CRM
3. If **found**: sets `customerId = "CUST-001"` and `authStatus = "authenticated"`
4. If **not found**: sets `customerId = ""` and `authStatus = "unauthenticated"`
5. Returns these values to Connect, which stores them as **contact attributes**
6. Also injects customer context (name, products, vulnerability flags) into the Q Connect session

**Lambda 2 - `aria-lex-fulfillment`** (runs on EVERY conversation turn)

This Lambda is called by Lex V2 each time the customer says something. It:
1. Reads `contactId`, `customerId`, and `authStatus` from the Lex session attributes
2. Sends the customer's words + those attributes to ARIA AgentCore
3. ARIA processes the request (already knowing who the caller is)
4. Returns ARIA's text response to Lex, which Nova Sonic speaks aloud

### The Pre-Authentication Flow

```
Phone number matches CRM?
  YES -> customerId = "CUST-001", authStatus = "authenticated"
         -> ARIA greets: "Hello James, how can I help you?"
         -> ARIA has full product context, skips identity verification
  NO  -> customerId = "",          authStatus = "unauthenticated"
         -> ARIA greets: "Welcome to Meridian Bank, I'm ARIA."
         -> ARIA runs full identity verification before any account data
```

**Nothing changes in your existing AgentCore/ARIA code.** You are adding:
1. An Amazon Connect instance (the phone system)
2. A Lex V2 bot (shell for voice input - ARIA handles all understanding)
3. Two Lambda functions (the glue between Connect and AgentCore)
4. A Contact Flow (the IVR script)

---

## Prerequisites

| Item | Requirement |
|---|---|
| AWS Account | Same account as your AgentCore runtime (`395402194296`) |
| IAM | Admin or a user with `AmazonConnect_FullAccess`, `AmazonLexFullAccess`, `AWSLambda_FullAccess` |
| AWS CLI | Configured with `aws configure` pointing to `eu-west-2` |
| AgentCore runtime | Running and reachable (verified from prior deployment) |
| Runtime ARN | `arn:aws:bedrock-agentcore:eu-west-2:395402194296:runtime/aria_banking_agent-ubLoKG8xsY` |
| Session Injector Lambda | Deployed (`aria-session-injector` - see `scripts/deploy_mcp_gateway.sh`) |
| Fulfillment Lambda | Deployed (`aria-lex-fulfillment` - see `scripts/deploy.sh`) |

> **Quick check**: Run `aws lambda get-function --function-name aria-session-injector --region eu-west-2` to verify the Lambda exists.

---

## Part 1 - Create the Amazon Connect Instance

> Official docs: [Create an Amazon Connect instance](https://docs.aws.amazon.com/connect/latest/adminguide/amazon-connect-instances.html)

### Step 1.1 - Open the Connect Console

1. Go to https://console.aws.amazon.com/connect/
2. Make sure your region selector (top right) shows **Europe (London) eu-west-2**
3. Click **Get started** (or **Add an instance** if you have existing instances)

### Step 1.2 - Configure Identity

1. Select **Store users in Amazon Connect** (simplest for initial setup)
2. In **Access URL**, enter a unique subdomain: `meridian-aria`
   - Your Connect admin URL will be: `https://meridian-aria.my.connect.aws`
3. Click **Next**

### Step 1.3 - Add Administrator

1. Select **Specify an administrator**
2. Fill in:
   - **First name**: Admin
   - **Last name**: Meridian
   - **Username**: `admin`
   - **Password**: (strong password - you will use this to log into Connect)
   - **Email**: (your email)
3. Click **Next**

### Step 1.4 - Configure Telephony

1. Check **Receive inbound calls with Amazon Connect**
2. Check **Make outbound calls with Amazon Connect**
3. Check **Enable early media**
4. Click **Next**

### Step 1.5 - Data Storage

1. Leave defaults (Connect creates an S3 bucket automatically)
2. Note the S3 bucket name shown (e.g., `amazon-connect-xxxxxxxxxxxx`)
3. Click **Next**

### Step 1.6 - Review and Create

1. Review settings
2. Click **Create instance**
3. Wait about 2 minutes for provisioning
4. Note your **Instance ARN** - you will need it later:
   - Format: `arn:aws:connect:eu-west-2:395402194296:instance/XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX`
   - Also note just the **Instance ID** (the UUID part after `instance/`)

### Step 1.7 - Claim a Phone Number

1. Once the instance is created, click **Get started** on the confirmation screen
2. Or go to: Connect admin -> **Channels** -> **Phone numbers** -> **Claim a number**
3. Select:
   - **Country**: United Kingdom
   - **Type**: DID (Direct Inward Dial) for a local number, or Toll Free
   - Pick any available number
4. Under **Flow/IVR**: leave blank for now (you will assign it after creating the flow)
5. Click **Save**
6. Note the phone number - this is what customers will call

---

## Part 2 - Register Both Lambdas with Connect

Before any Lambda can be called from a Contact Flow, you must explicitly allow it in the Connect instance settings. This is a security whitelist. If you skip this, the flow will fail with a confusing "resource not found" error even though the Lambda exists.

### Step 2.1 - Add `aria-session-injector`

1. Go to https://console.aws.amazon.com/connect/
2. Click on your instance alias (`meridian-aria`)
3. In the left sidebar, click **Flows**
4. Scroll down to the **AWS Lambda** section
5. In the dropdown, find and select `aria-session-injector`
   - If you do not see it, make sure it was deployed in the same region (eu-west-2)
6. Click **Add Lambda Function**
7. Confirm it appears in the list below the dropdown

### Step 2.2 - Add `aria-lex-fulfillment`

1. Still on the same **Flows** settings page
2. In the **AWS Lambda** dropdown, now select `aria-lex-fulfillment`
3. Click **Add Lambda Function**
4. Confirm both functions now appear in the list

> WARNING: If you skip this step, the Contact Flow will fail when it tries to call the Lambda. The error message in CloudWatch will say "The resource you tried to access does not exist" - this is misleading. The Lambda exists, it just has not been authorised for this Connect instance.

---

## Part 3 - Create the Lex V2 Bot

> Official docs: [Amazon Lex V2 Developer Guide - Creating a bot](https://docs.aws.amazon.com/lexv2/latest/dg/build-text.html)

### Step 3.1 - Create the Bot

1. Go to https://console.aws.amazon.com/lexv2/
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

### Step 3.2 - Configure Language (Locale)

1. On the **Add language** page:
   - **Language**: English (GB)
   - **Voice interaction**: Select `Amy` from the dropdown
   - **Intent classification confidence score threshold**: `0.40`
     (Lower threshold means FallbackIntent fires more reliably when ARIA handles all NLU)
2. Click **Done**
3. The bot opens in the Lex V2 console

### Step 3.3 - Configure the FallbackIntent

The FallbackIntent fires when no other intent matches. Since ARIA handles all conversation understanding, every customer utterance should go through: FallbackIntent -> Lambda -> ARIA.

1. In the left sidebar, click **Intents**
2. Click on **FallbackIntent** (it exists by default)
3. Scroll down to **Fulfillment**
4. Under **Fulfillment**, check the box **Use a Lambda function for fulfillment**
5. Click **Save intent**

### Step 3.4 - Add TransferToAgent Intent

This gives callers an explicit way to request a human agent.

1. Click **Add intent** -> **Add empty intent**
2. **Intent name**: `TransferToAgent`
3. Under **Sample utterances**, add each of the following (type each one and press Enter):
   - `speak to an agent`
   - `speak to someone`
   - `talk to a person`
   - `I want an agent`
   - `operator`
   - `human`
   - `zero`
4. Under **Fulfillment**, check the box **Use a Lambda function for fulfillment**
5. Click **Save intent**

### Step 3.5 - Build the Bot

1. Click **Build** (top right)
2. Wait for the build to complete (1-2 minutes)
3. You should see: **Build successful**

### Step 3.6 - Create a Bot Version and Alias

Aliases are required for Connect integration. An alias is like a pointer to a specific bot version. Connect always uses an alias, not a version directly.

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

### Step 3.7 - Attach Lambda to the Alias

1. Click on the `production` alias you just created
2. Click the **Languages** tab
3. Click on **English (GB)**
4. Under **Source**, select the Lambda function `aria-lex-fulfillment`
5. Under **Lambda function version or alias**: `$LATEST`
6. Click **Save**

**Grant Lex permission to invoke Lambda:**

7. Go to the Lambda console -> `aria-lex-fulfillment` -> **Configuration** -> **Permissions**
8. Under **Resource-based policy statements**, click **Add permissions**
9. Configure:
   - **Statement ID**: `lex-invoke-permission`
   - **Principal**: `lexv2.amazonaws.com`
   - **Action**: `lambda:InvokeFunction`
   - **Source ARN**: (your Lex bot alias ARN)
     Format: `arn:aws:lex:eu-west-2:395402194296:bot-alias/BOTID/ALIASID`
10. Click **Save**

> Tip: Alternatively, run via CLI:
> ```bash
> aws lambda add-permission \
>   --function-name aria-lex-fulfillment \
>   --statement-id lex-invoke-permission \
>   --action lambda:InvokeFunction \
>   --principal lexv2.amazonaws.com \
>   --source-arn "arn:aws:lex:eu-west-2:395402194296:bot-alias/YOUR_BOT_ID/YOUR_ALIAS_ID" \
>   --region eu-west-2
> ```

---

## Part 4 - Configure Nova Sonic Speech-to-Speech in Amazon Connect

> Official docs: [Configure Amazon Nova Sonic Speech-to-Speech](https://docs.aws.amazon.com/connect/latest/adminguide/nova-sonic-speech-to-speech.html)

Nova Sonic S2S is configured on the **Amazon Connect Conversational AI bot** - this is Connect's wrapper around the Lex V2 bot that enables neural speech processing.

### Step 4.1 - Add the Lex Bot to Your Connect Instance

1. Go to https://console.aws.amazon.com/connect/
2. Click on your instance alias (`meridian-aria`)
3. In the left sidebar, click **Flows**
4. Scroll down to **Amazon Lex** section
5. Under **Lex V2 bots**, select `ARIA-Connect-Bot` from the dropdown
6. Select the alias: `production`
7. Click **Add Amazon Lex Bot**
8. Confirm it appears in the list

### Step 4.2 - Open the Bot in Connect's AI Bot Interface

1. In the Connect admin sidebar, click **Channels** -> **Bots**
2. You should see `ARIA-Connect-Bot` listed
3. Click on it to open the bot configuration

### Step 4.3 - Enable Nova Sonic S2S on the Locale

1. On the bot configuration page, click the **Configuration** tab
2. Click on the **en-GB** locale row
3. In the **Speech model** section, click **Edit**
4. A modal opens. In **Model type** dropdown, select: **Speech-to-Speech**
5. In **Voice provider** dropdown, select: **Amazon Nova Sonic**
6. Click **Confirm**

### Step 4.4 - Build the Locale

1. If you see **Unbuilt changes** next to the en-GB locale, click **Build language**
2. Wait for the build to complete (1-2 minutes)
3. The Speech model card should now show: `Speech-to-Speech: Amazon Nova Sonic`

---

## Part 5 - Create the Contact Flow

> Official docs: [Create contact flows](https://docs.aws.amazon.com/connect/latest/adminguide/create-contact-flow.html)

This is the most important part. The Contact Flow is the visual IVR script - it is the logic that runs every time someone calls. We will build it block by block. For each block we explain exactly what to configure and which output arrows to connect.

### Step 5.1 - Open the Flow Designer

1. In the Connect admin sidebar, click **Routing** -> **Flows**
2. Click **Create flow**
3. Name it: `Meridian-ARIA-Inbound`
4. Click **Create flow**

The flow designer opens as a blank canvas with one block already present: **Entry point**. This is where every call begins.

---

### Understanding the Flow Designer Canvas

Before building, here is how the designer works:

- **Blocks** are dragged from the left panel onto the canvas
- Each block has one **input** (the arrow tip on the left/top side)
- Each block has one or more **outputs** (the dots on the right/bottom side, labelled with outcomes like "Success", "Error", "Timeout", "Match", "No match")
- You **connect blocks** by clicking an output dot and dragging to the next block's input
- **Every output must be connected** - unconnected outputs cause call failures
- To **configure** a block, click on it to open its settings panel on the right side

---

### Step 5.2 - Build the Flow (Block by Block)

#### Block 1: Entry Point (already exists on the canvas)

**What it does**: Every inbound call begins here automatically. You cannot delete this block.

**Configuration**: None needed - leave it as-is.

**Outputs to connect**:
- The single output arrow on this block connects to **Block 2** (Set Voice)

---

#### Block 2: Set Voice

**What it does**: Configures Nova Sonic as the voice engine for this call. Without this block, calls use the older Polly text-to-speech engine instead of Nova Sonic's natural-sounding voice.

**How to add**:
1. In the left panel, under the **Set** category, find **Set voice**
2. Drag it onto the canvas to the right of the Entry Point
3. Connect Block 1 to Block 2: click on the Entry Point block - you will see a small circle on its right edge. Click and drag from that circle to the **Set voice** block's left edge. A line (arrow) connects them.

**Configuration** (click on the Set Voice block to open settings):
1. **Voice provider**: Amazon
2. **Language**: English (United Kingdom)
3. **Voice**: Amy
4. Scroll down to **Other settings**
5. Check the box **Override speaking style**
6. Select: **Generative** - this is the critical setting that activates Nova Sonic
7. Click **Save**

**Outputs to connect**:
- **Success** output -> connect to **Block 3** (Set Contact Attributes - ContactId)
- **Error** output -> connect to a Disconnect block (add one from Terminate/Transfer category)

---

#### Block 3: Set Contact Attributes - Store ContactId

**What it does**: Saves the unique identifier for this phone call (ContactId) as a named variable. We need it stored so other blocks and Lambdas can reference it. The ContactId is used as the AgentCore session ID - it ties all conversation turns together for a single call.

**How to add**:
1. Under the **Set** category, find **Set contact attributes**
2. Drag it onto the canvas after **Set voice**
3. Connect: **Set voice** -> **Success** output -> **Set contact attributes** input (left side)

**Configuration** (click on the block):
1. Click **Add attribute**
2. Fill in:
   - **Destination key**: `contactId`
   - **Type**: `System`
   - **Attribute**: `Contact ID`
     (This pulls the built-in Connect ContactId into your named variable)
3. Click **Save**

**In plain English**: This creates a variable called `contactId` and sets it to the system's Contact ID value. Every block after this can read it using `$.Attributes.contactId`.

**Outputs to connect**:
- **Success** output -> connect to **Block 4** (Invoke Lambda - Session Injector)

---

#### Block 4: Invoke AWS Lambda - Session Injector (Pre-Authentication)

**What it does**: This is where caller identification happens. Connect calls `aria-session-injector`, which:

1. Receives the caller's phone number and ContactId from Connect
2. Looks up the phone number in the CRM
3. **If the caller IS a known customer**: returns `customerId = "CUST-001"` and `authStatus = "authenticated"`
4. **If the caller is NOT recognised**: returns `customerId = ""` and `authStatus = "unauthenticated"`

The Lambda result is available to the NEXT block via `$.External.customerId` and `$.External.authStatus`.

**How to add**:
1. Under the **Interact** category, find **Invoke AWS Lambda function**
2. Drag it onto the canvas after **Set contact attributes**
3. Connect: **Set contact attributes** -> **Success** output -> **Invoke AWS Lambda function** input

**Configuration** (click on the block):
1. **Function ARN**: Click the dropdown and select `aria-session-injector`
   - If it does not appear, go back to Part 2 and add it to the instance allow-list first
2. **Timeout**: Leave at the default (8 seconds)
3. You do NOT need to add any Parameters - the Lambda reads ContactId automatically from the Connect event
4. Click **Save**

**Outputs to connect**:
- **Success** output -> connect to **Block 5** (Set Contact Attributes - Store Lambda Result)
- **Error** output -> connect to **Block 6** (Get Customer Input) directly
  (If the Lambda errors, we still let the call through - ARIA will handle unauthenticated callers gracefully)

---

#### Block 5: Set Contact Attributes - Store Session Injector Result

**What it does**: Takes the values the Lambda returned (`customerId`, `authStatus`, `preferredName`) and stores them as permanent contact attributes so they persist for the entire call.

**Why this block is needed**: Lambda return values are only available as `$.External.*` immediately after the Lambda block. To make them available for the whole call - including inside Lex - you must copy them into contact attributes (`$.Attributes.*`) using this block.

**How to add**:
1. Under the **Set** category, find **Set contact attributes** (same type as Block 3)
2. Drag it onto the canvas after **Invoke AWS Lambda function**
3. Connect: **Invoke AWS Lambda function** -> **Success** output -> this **Set contact attributes** input

**Configuration** (click on the block):

Click **Add attribute** ten separate times to create all ten attributes:

**Attribute 1 - Customer ID:**
- **Destination key**: `customerId`
- **Type**: `External`
- **Attribute**: `customerId`
  (Copies `$.External.customerId` into `$.Attributes.customerId`)

**Attribute 2 - Auth Status:**
- **Destination key**: `authStatus`
- **Type**: `External`
- **Attribute**: `authStatus`
  (Copies `$.External.authStatus` into `$.Attributes.authStatus`)

**Attribute 3 - Preferred Name:**
- **Destination key**: `preferredName`
- **Type**: `External`
- **Attribute**: `preferredName`
  (Customer's first name — ARIA uses this to greet immediately without a tool call)

**Attribute 4 - Product Summary:**
- **Destination key**: `productSummary`
- **Type**: `External`
- **Attribute**: `productSummary`
  (Natural-language sentence e.g. "James has a current account ending 4821 and a Visa debit card.")

**Attribute 5 - Product Context:**
- **Destination key**: `productContext`
- **Type**: `External`
- **Attribute**: `productContext`
  (JSON string of masked account/card refs. Allows ARIA to resolve "my account" before calling tools.)

**Attribute 6 - Vulnerability Context:**
- **Destination key**: `vulnerabilityContext`
- **Type**: `External`
- **Attribute**: `vulnerabilityContext`
  (JSON string of vulnerability flags. ARIA reads silently — never discloses to customer.)

**Attribute 7 - Prior Session Summary:**
- **Destination key**: `priorSummary`
- **Type**: `External`
- **Attribute**: `priorSummary`
  (Summary of the customer's previous interaction, from AgentCore Memory.)

**Attribute 8 - Channel:**
- **Destination key**: `channel`
- **Type**: `External`
- **Attribute**: `channel`
  (Value will be "voice" — tells ARIA which communication channel this is.)

**Attribute 9 - Locale:**
- **Destination key**: `locale`
- **Type**: `External`
- **Attribute**: `locale`
  (Defaults to "en-GB" — used for language and formatting context.)

**Attribute 10 - Date/Time:**
- **Destination key**: `dateTime`
- **Type**: `External`
- **Attribute**: `dateTime`
  (UTC ISO timestamp for compliance logging.)

Click **Save**

**In plain English**: After this block runs, the call has all ten variables set for its lifetime. Every subsequent block can read them. The fulfillment Lambda will read all of them and include them in the AgentCore payload so ARIA has full context before the first word is spoken.

**Outputs to connect**:
- **Success** output -> connect to **Block 6** (Get Customer Input)

---

#### Block 6: Get Customer Input - ARIA Lex Bot Conversation

**What it does**: This is the main conversation block. It:
1. Plays a greeting to the caller (spoken by Nova Sonic)
2. Listens for the caller's speech
3. Sends the speech to the Lex V2 bot (`ARIA-Connect-Bot`)
4. The Lex bot calls `aria-lex-fulfillment` Lambda on every turn
5. The Lambda reads `customerId` and `authStatus` from session attributes, calls AgentCore, returns ARIA's response
6. Nova Sonic speaks ARIA's response back to the caller
7. The block stays active and loops through turns until an intent fires

**How to add**:
1. Under the **Interact** category, find **Get customer input**
2. Drag it onto the canvas
3. Connect: **Set contact attributes (Block 5)** -> **Success** output -> **Get customer input** input
   Also connect: **Invoke AWS Lambda (Block 4)** -> **Error** output -> **Get customer input** input
   (Two arrows can connect to the same input block)

**Configuration** (click on the block):

**Section: Text to speech or chat text**
- Select **Enter text**
- Type the greeting:
  `Welcome to Meridian Bank. I am ARIA, your banking assistant. How can I help you today?`
  (Nova Sonic speaks this when the call first reaches this block. On loop-back turns, this greeting is NOT replayed - only ARIA's responses are spoken.)

**Section: Amazon Lex** (click the Amazon Lex tab, not Amazon Lex Classic)
- **Bot**: `ARIA-Connect-Bot`
- **Bot alias**: `production`

**Section: Session attributes** - THIS IS CRITICAL - this is the data pipe that carries all pre-auth context from Connect into Lex and on to the fulfillment Lambda

Click **Add an attribute** for each row in the table below (11 total):

| Destination key | Type | Attribute | What it carries |
|---|---|---|---|
| `contactId` | System | `Contact ID` | Unique call ID → AgentCore session ID |
| `customerId` | User-defined | `customerId` | CRM customer ID (blank if unauthenticated) |
| `authStatus` | User-defined | `authStatus` | "authenticated" or "unauthenticated" |
| `preferredName` | User-defined | `preferredName` | Customer's first name for immediate greeting |
| `productSummary` | User-defined | `productSummary` | Natural-language product sentence |
| `productContext` | User-defined | `productContext` | JSON of masked account/card refs |
| `vulnerabilityContext` | User-defined | `vulnerabilityContext` | JSON vulnerability flags (ARIA reads silently) |
| `priorSummary` | User-defined | `priorSummary` | Summary from AgentCore Memory (prior session) |
| `channel` | User-defined | `channel` | "voice" |
| `locale` | User-defined | `locale` | "en-GB" |
| `dateTime` | User-defined | `dateTime` | UTC ISO timestamp |

> WARNING: Without these session attributes, the fulfillment Lambda cannot read who the caller is or any of their context. ARIA will treat every caller as unauthenticated and ask them to verify their identity, even if the session injector already identified them.

**Section: Intents**
- Click **Add an intent**, type `FallbackIntent`, press Enter
- Click **Add another intent**, type `TransferToAgent`, press Enter

Click **Save**

**Understanding the four outputs of this block** (you must connect ALL of them):

| Output label | When it fires | Where to connect it |
|---|---|---|
| `FallbackIntent` | ARIA handled the turn normally | Block 7 (Check escalate flag) |
| `TransferToAgent` | Customer said "agent", "human", etc. | Block 8 (Set escalate=true) |
| `Timeout` | Customer was silent for too long | Play prompt "Didn't hear you" -> loop back to Block 6 |
| `Error` | Technical error in Lex or Lambda | Play prompt "Technical issue" -> Disconnect |

---

#### Block 7: Check Contact Attributes - Did ARIA Request Escalation?

**What it does**: After each Lex turn, ARIA's fulfillment Lambda may have set `escalate = "true"` in the Lex session attributes - this happens when ARIA's response contains phrases like "let me connect you with an advisor". This Check block reads that flag and routes accordingly.

**Why it is needed**: The Lex bot returns control to Connect via the `FallbackIntent` output whether or not ARIA wants to escalate. Connect cannot inspect Lex session attributes directly - it must check the contact attribute that the Lambda wrote.

**How to add**:
1. Under the **Branch** category, find **Check contact attributes**
2. Drag it onto the canvas
3. Connect: **Get customer input** -> `FallbackIntent` output -> **Check contact attributes** input

**Configuration** (click on the block):
1. **Attribute to check**: User-defined
2. **Attribute key**: `escalate`
3. Click **Add condition**:
   - **Condition**: Equals
   - **Value**: `true`
4. Click **Save**

**Outputs to connect**:
- **Match** output -> connect to **Block 9** (Play Escalation Prompt)
- **No match** output -> loop back to **Block 6** (Get Customer Input) input

**How to create the loop back**: Drag from the **No match** output dot of Block 7 and drop onto the input of Block 6 (Get Customer Input). A curved arrow will appear.

---

#### Block 8: Set Contact Attributes - Store Escalation from TransferToAgent Intent

**What it does**: When the Lex bot fires the `TransferToAgent` intent (customer explicitly said "agent" or "human"), this block marks the call for transfer by writing `escalate = true` into the contact attributes.

**How to add**:
1. Under the **Set** category, find **Set contact attributes**
2. Drag it onto the canvas
3. Connect: **Get customer input** -> `TransferToAgent` output -> **Set contact attributes** input

**Configuration** (click on the block):
1. Click **Add attribute**:
   - **Destination key**: `escalate`
   - **Type**: `Static`
   - **Value**: `true`
2. Click **Save**

**Outputs to connect**:
- **Success** output -> connect to **Block 9** (Play Escalation Prompt)

---

#### Block 9: Play Prompt - Escalation Message

**What it does**: Plays a message to the caller confirming they are being transferred to a human agent.

**How to add**:
1. Under the **Interact** category, find **Play prompt**
2. Drag it onto the canvas
3. Connect TWO inputs to this block:
   - **Check contact attributes (Block 7)** -> **Match** output -> **Play prompt** input
   - **Set contact attributes (Block 8)** -> **Success** output -> **Play prompt** input
   (Both escalation paths - ARIA-requested and customer-requested - arrive here)

**Configuration** (click on the block):
- Select **Enter text**
- Type: `Please hold for a moment. I am connecting you with one of our advisors now.`
- Click **Save**

**Outputs to connect**:
- **Success** output -> connect to **Block 10** (Set Working Queue)

---

#### Block 10: Set Working Queue

**What it does**: Selects which queue of human agents the call will be sent to.

**How to add**:
1. Under the **Set** category, find **Set working queue**
2. Drag it after **Play prompt**
3. Connect: **Play prompt** -> **Success** output -> **Set working queue** input

**Configuration** (click on the block):
- **Queue**: Select **BasicQueue** (the default queue - create a dedicated `CustomerService` queue later if needed)
- Click **Save**

**Outputs to connect**:
- **Success** output -> connect to **Block 11** (Transfer to Queue)

---

#### Block 11: Transfer to Queue

**What it does**: Transfers the call to human agents waiting in the selected queue.

**How to add**:
1. Under the **Terminate/Transfer** category, find **Transfer to queue**
2. Drag it after **Set working queue**
3. Connect: **Set working queue** -> **Success** output -> **Transfer to queue** input

**Configuration**: No configuration needed - it uses the queue set in Block 10.

**Outputs to connect**:
- **At capacity** output -> **Play prompt**: "All our advisors are currently busy. Please call back shortly." -> **Disconnect**
- **Error** output -> **Disconnect**

---

#### Block 12: Timeout Handling

**What it does**: Handles the case where the caller did not speak when Lex was listening.

**How to add**:
1. Add a **Play prompt** block with text: `I am sorry, I did not hear you. Could you say that again?`
2. Connect: **Get customer input** -> **Timeout** output -> **Play prompt** input
3. Connect: **Play prompt** -> **Success** output -> loop back to **Block 6** (Get Customer Input)

---

#### Block 13: Error Handling - Disconnect

**What it does**: Gracefully ends the call on technical errors.

**How to add**:
1. Under **Terminate/Transfer**, find **Disconnect / hang up**
2. Add one or two Disconnect blocks for error paths
3. Connect error paths to them:
   - **Get customer input** -> **Error** output -> (optional Play prompt: "I encountered a technical issue. Please call back.") -> **Disconnect**

---

### Step 5.3 - Complete Flow Connections Summary

Here is every block and every output connection you need to make:

```
[Block 1: Entry Point]
    | (single output)
    v
[Block 2: Set Voice - Amy, Generative]
    | Success ----> [Block 3: Set Contact Attrs - contactId]
    | Error ------> [Disconnect]

[Block 3: Set Contact Attrs - contactId]
    | Success ----> [Block 4: Invoke Lambda - aria-session-injector]

[Block 4: Invoke Lambda - aria-session-injector]
    | Success ----> [Block 5: Set Contact Attrs - customerId/authStatus/preferredName]
    | Error ------> [Block 6: Get Customer Input]  (unauthenticated fallback)

[Block 5: Set Contact Attrs - customerId/authStatus/preferredName]
    | Success ----> [Block 6: Get Customer Input]

[Block 6: Get Customer Input - ARIA-Connect-Bot/production]
    Session attrs passed in: contactId, customerId, authStatus, preferredName
    |
    | FallbackIntent  -----> [Block 7: Check Contact Attrs - escalate]
    | TransferToAgent -----> [Block 8: Set Contact Attrs - escalate=true]
    | Timeout         -----> [Play Prompt: "Didn't hear you"] -> loop back to Block 6
    | Error           -----> [Play Prompt: "Technical issue"] -> [Disconnect]

[Block 7: Check Contact Attrs - escalate == "true"]
    | Match    -----> [Block 9: Play Prompt - escalation message]
    | No match -----> loop back to [Block 6: Get Customer Input]

[Block 8: Set Contact Attrs - escalate=true]
    | Success -----> [Block 9: Play Prompt - escalation message]

[Block 9: Play Prompt - "Connecting you with an advisor..."]
    | Success -----> [Block 10: Set Working Queue - BasicQueue]

[Block 10: Set Working Queue - BasicQueue]
    | Success -----> [Block 11: Transfer to Queue]

[Block 11: Transfer to Queue]
    | At capacity -----> [Play Prompt: "All advisors busy"] -> [Disconnect]
    | Error       -----> [Disconnect]
```

---

### Step 5.4 - How the Session Attributes Flow Through the System

This shows exactly where each piece of data lives at each stage of a call:

```
CALL ARRIVES: caller phone = "+447765309252", ContactId = "abc-123-def-456"

Block 3 writes:
  $.Attributes.contactId = "abc-123-def-456"

Block 4 runs aria-session-injector Lambda:
  Lambda receives: ContactId="abc-123-def-456", callerPhone="+447765309252"
  Lambda looks up phone in CRM:
    FOUND ->
      Returns (all as $.External.*):
        customerId           = "CUST-001"
        authStatus           = "authenticated"
        preferredName        = "James"
        productSummary       = "James has a current account ending 4821, a savings account, and a Visa debit card."
        productContext       = '{"accounts":[{"masked":"****4821","type":"current"}],...}'
        vulnerabilityContext = '{"flag_type":"mental_health","suppress_promotion":true,...}'
        priorSummary         = "Customer called last week about a standing order. Resolved."
        channel              = "voice"
        locale               = "en-GB"
        dateTime             = "2026-04-06T09:35:21.833Z"
    NOT FOUND ->
      Returns: customerId="", authStatus="unauthenticated", all context fields=""

Block 5 writes ALL External values into permanent $.Attributes.*:
  $.Attributes.customerId           = "CUST-001"
  $.Attributes.authStatus           = "authenticated"
  $.Attributes.preferredName        = "James"
  $.Attributes.productSummary       = "James has a current account..."
  $.Attributes.productContext       = '{"accounts":[...],...}'
  $.Attributes.vulnerabilityContext = '{"flag_type":"mental_health",...}'
  $.Attributes.priorSummary         = "Customer called last week..."
  $.Attributes.channel              = "voice"
  $.Attributes.locale               = "en-GB"
  $.Attributes.dateTime             = "2026-04-06T09:35:21.833Z"

Block 6 passes ALL $.Attributes.* as Lex session attributes:
  contactId           = "abc-123-def-456"
  customerId          = "CUST-001"
  authStatus          = "authenticated"
  preferredName       = "James"
  productSummary      = "James has a current account..."
  productContext      = '{"accounts":[...],...}'
  vulnerabilityContext = '{"flag_type":"mental_health",...}'
  priorSummary        = "Customer called last week..."
  channel             = "voice"
  locale              = "en-GB"
  dateTime            = "2026-04-06T09:35:21.833Z"

aria-lex-fulfillment Lambda reads ALL Lex session attributes and builds:
  AgentCore POST body = {
    "message":            "What is my account balance?",
    "authenticated":      true,
    "customer_id":        "CUST-001",
    "channel":            "voice",
    "preferred_name":     "James",
    "product_summary":    "James has a current account ending 4821...",
    "product_context":    '{"accounts":[...],...}',
    "vulnerability_context": '{"flag_type":"mental_health",...}',
    "prior_summary":      "Customer called last week about a standing order.",
    "locale":             "en-GB",
    "date_time":          "2026-04-06T09:35:21.833Z"
  }
  AgentCore session header = X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: abc-123-def-456

agentcore_app chat_handler receives payload, builds SESSION_START:
  "SESSION_START: An authenticated customer has connected.
   X-Channel-Auth: authenticated. X-Customer-ID: CUST-001.
   X-Channel: voice. X-Locale: en-GB.
   X-Preferred-Name: James. Greet the customer as James immediately.
   X-Product-Summary: James has a current account ending 4821...
   X-Product-Context: {"accounts":[...],...}
   X-Vulnerability-Context: {"flag_type":"mental_health",...} [SILENT: ...]
   X-Prior-Session-Summary: Customer called last week about a standing order.
   Use X-Product-Context to resolve account/card references. Call get_customer_details
   for real-time balances or detailed account data. Do not ask to re-verify identity.

   Customer's first message: What is my account balance?"

ARIA responds immediately:
  "Hi James! Your current account ending 4821 has a balance of 1,245.30 pounds.
   Would you like to see recent transactions or is there anything else I can help with?"

Nova Sonic speaks ARIA's response back to the caller.
```

---

### Step 5.5 - Save and Publish the Flow

1. Click **Save** (top right of the flow designer)
2. Look for any blocks with a **red warning icon** - this means an output is not connected
3. Fix any warnings by connecting the highlighted outputs
4. Click **Publish**
5. Confirm the publish - the flow is now live

> WARNING: If you see "One or more blocks are not connected" - every output arrow on every block must connect somewhere, even if just to a Disconnect block. A block with an unconnected output will crash the call when that output is reached.

---

## Part 6 - The Fulfillment Lambda and AgentCore App are Already Updated

The code changes needed for the full pre-auth + context pipeline have already been implemented in:
- `scripts/lambdas/aria_connect_fulfillment.py`
- `aria/agentcore_app.py`

This section documents what was changed and the complete payload contract for reference.

### What `aria_connect_fulfillment.py` now does (per turn)

1. Reads **all** session attributes from the Lex event (placed there by Block 6)
2. Builds the AgentCore POST body with all available context
3. Only includes non-empty fields — the React app and other callers that send only `"message"` work exactly as before

**Full AgentCore payload (voice channel, authenticated):**
```json
{
  "message":             "What is my account balance?",
  "authenticated":       true,
  "customer_id":         "CUST-001",
  "channel":             "voice",
  "preferred_name":      "James",
  "product_summary":     "James has a current account ending 4821, a savings account, and a Visa debit card.",
  "product_context":     "{\"accounts\":[{\"masked\":\"****4821\",\"type\":\"current\"}],...}",
  "vulnerability_context": "{\"flag_type\":\"mental_health\",\"suppress_promotion\":true,...}",
  "prior_summary":       "Customer called last week about a standing order dispute. Resolved.",
  "locale":              "en-GB",
  "date_time":           "2026-04-06T09:35:21.833Z"
}
```

**Minimal payload (React app / unauthenticated):**
```json
{
  "message":       "What is my account balance?",
  "authenticated": false,
  "channel":       "agentcore-chat"
}
```

### What `agentcore_app.py` now does on first turn

The `chat_handler` extracts all optional context fields from the payload and builds a rich `SESSION_START` injection. For voice with pre-auth context, the SESSION_START looks like:

```
SESSION_START: An authenticated customer has connected.
X-Channel-Auth: authenticated. X-Customer-ID: CUST-001.
X-Channel: voice. X-Locale: en-GB.
X-Preferred-Name: James. Greet the customer as James immediately.
X-Product-Summary: James has a current account ending 4821, a savings account, and a Visa debit card.
X-Product-Context: {"accounts":[...],"cards":[...],"mortgages":[]}
X-Vulnerability-Context: {"flag_type":"mental_health",...} [SILENT: read to adjust communication style only]
X-Prior-Session-Summary: Customer called last week about a standing order. Resolved.
Use X-Product-Context to resolve account/card references. Call get_customer_details for real-time balances.
Do not ask the customer to re-verify their identity.

Customer's first message: What is my account balance?
```

For the React app (no context fields in payload), SESSION_START is identical to the original behaviour.

### Redeploy to apply the changes

```bash
bash scripts/deploy.sh deploy
```

This rebuilds and redeploys `aria-lex-fulfillment` Lambda and the AgentCore container image.


---

## Part 7 - Assign the Flow to Your Phone Number

1. In the Connect admin, go to **Channels** -> **Phone numbers**
2. Click on the phone number you claimed in Part 1
3. Under **Flow/IVR**, select `Meridian-ARIA-Inbound`
4. Click **Save**

After saving, calls to this number immediately use the new flow. There is no additional activation step.

---

## Part 8 - Test End-to-End

### Step 8.1 - Test the Session Injector Lambda in Isolation

Before making a real call, verify the Lambda works with a simulated Connect event.

1. Go to AWS Lambda -> `aria-session-injector` -> **Test** tab
2. Create a new test event named `connect-voice-test`
3. Paste this test payload (replace YOUR-INSTANCE-ID with your Connect Instance ID):

```json
{
  "Details": {
    "ContactData": {
      "ContactId": "test-contact-12345",
      "InstanceARN": "arn:aws:connect:eu-west-2:395402194296:instance/YOUR-INSTANCE-ID",
      "Channel": "VOICE",
      "Attributes": {},
      "CustomerEndpoint": {
        "Address": "+447765309252",
        "Type": "TELEPHONE_NUMBER"
      },
      "SystemEndpoint": {
        "Address": "+441612345678",
        "Type": "TELEPHONE_NUMBER"
      }
    },
    "Parameters": {}
  },
  "Name": "ContactFlowEvent",
  "Version": "1.0"
}
```

4. Click **Test**
5. Expected response (phone `+447765309252` maps to `CUST-001` in the stub data):

```json
{
  "sessionId": "test-contact-12345",
  "customerId": "CUST-001",
  "authStatus": "authenticated",
  "status": "injected",
  "injectedKeys": ["sessionId", "customerId", "authStatus", "channel", "preferredName"]
}
```

If you see `"customerId": ""` and `"authStatus": "unauthenticated"` - the phone number was not found in the stub data. This is the expected unauthenticated result.

### Step 8.2 - Test the Fulfillment Lambda in Isolation

1. Go to AWS Lambda -> `aria-lex-fulfillment` -> **Test** tab
2. Create a new test event named `lex-auth-test`
3. Paste this payload simulating a pre-authenticated caller:

```json
{
  "messageVersion": "1.0",
  "invocationSource": "FulfillmentCodeHook",
  "inputMode": "Speech",
  "inputTranscript": "What is my account balance?",
  "sessionId": "test-contact-12345",
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
    "sessionAttributes": {
      "contactId":     "test-contact-12345",
      "customerId":    "CUST-001",
      "authStatus":    "authenticated",
      "preferredName": "James"
    }
  },
  "requestAttributes": {
    "ContactId": "test-contact-12345"
  }
}
```

4. Click **Test**
5. Expected: ARIA's response text - it should greet James by name and provide account details without asking for authentication.

Test the unauthenticated path by changing `sessionAttributes` to:
```json
"sessionAttributes": {
  "contactId":  "test-contact-99999",
  "customerId": "",
  "authStatus": "unauthenticated"
}
```
Expected: ARIA asks for the customer's ID before providing any data.

### Step 8.3 - Test via Real Phone Call

1. Log into the Connect admin at `https://meridian-aria.my.connect.aws`
2. Click the phone icon (top right) to open the Contact Control Panel (CCP)
3. Set your status to **Available**
4. Call your claimed phone number from test number `+447765309252` (James Hartley in stub data)
5. You should hear the greeting spoken by Nova Sonic
6. Say: "What is my balance?"
7. ARIA should respond immediately with account details (no authentication needed - pre-auth worked)
8. Call again from an unknown number - ARIA should ask for your customer ID

### Step 8.4 - Test Escalation

1. During a call, say: "I want to speak to an agent"
2. ARIA should say: "Please hold for a moment. I am connecting you with one of our advisors now."
3. The call routes to the Connect queue

### Step 8.5 - Verify in CloudWatch Logs

**Session Injector logs** (`/aws/lambda/aria-session-injector`):
```
Contact: id=abc-123 channel=voice customerId='CUST-001' authStatus='authenticated'
Customer context built: name='James' ...
Session injector complete: {"sessionId": "abc-123", "customerId": "CUST-001", ...}
```

**Fulfillment Lambda logs** (`/aws/lambda/aria-lex-fulfillment`):
```
Turn: intent=FallbackIntent contactId=abc-123 transcript='What is my account balance?'
ARIA response (session=abc-123): 'Hi James, your current account ending 4821...'
```

To view: AWS Console -> **CloudWatch** -> **Log groups** -> search for the log group name above.

---

## Troubleshooting

### "Session injector returns customerId='' even for registered test numbers"

The stub phone-to-customer mapping in `session_injector.py` is:
```python
_PHONE_TO_CUSTOMER = {
    "+447765309252": "CUST-001",   # James Hartley
    "+447700900001": "CUST-002",   # Sarah Chen
    ...
}
```
Call from one of these numbers, or add your own test number to the Lambda's `_PHONE_TO_CUSTOMER` dict and redeploy.

### "customerId is empty in the fulfillment Lambda even though session injector found the customer"

Check each step in the data chain:
1. Session Injector returned it? - Check `aria-session-injector` CloudWatch logs: look for `customerId='CUST-001'` in the output
2. Block 5 stored it? - In the flow designer, click Block 5 and confirm the `customerId` attribute uses Type `External` (not `Static` or `System`)
3. Block 6 passes it to Lex? - In Block 6 (Get Customer Input), confirm the session attribute `customerId` is set to Type `User-defined`, Attribute `customerId`
4. Lambda reads it? - Verify the Lambda code was updated as described in Part 6

### "ARIA asks for customer ID even though phone was matched"

The fulfillment Lambda may not be reading `customerId` from session attributes, or may not be passing it to AgentCore. Check CloudWatch logs for the fulfillment Lambda and look for the customerId in the logged session attributes.

### "Lambda timeout error"

- Session injector has 8 seconds. If CRM API is slow, raise Lambda timeout to 10 seconds in Lambda -> Configuration -> General configuration.
- Fulfillment Lambda has 7 seconds. AgentCore tool calls should complete within about 5 seconds.

### "Access denied from Lambda to AgentCore"

- Verify `aria-lex-fulfillment` execution role has `bedrock-agentcore:InvokeAgentRuntime` permission
- The `deploy.sh` script creates `aria-lambda-fulfillment-role` with this permission automatically
- To verify: IAM -> Roles -> `aria-lambda-fulfillment-role` -> Permissions -> look for `AgentCoreInvoke` inline policy

### "No response / silence after greeting"

- Check that the Set Voice block has **Override speaking style: Generative** enabled
- Verify the Lex bot locale shows `Speech-to-Speech: Amazon Nova Sonic`
- Check `aria-lex-fulfillment` CloudWatch logs for errors invoking AgentCore

### "Lex intent not firing Lambda"

- Verify the Lambda `aria-lex-fulfillment` is attached to the **alias** (`production`), not just the bot version
- Check the resource-based policy on the Lambda allows `lexv2.amazonaws.com` to invoke it

### "Call goes to error branch immediately"

- Check the flow connections - every output must be connected
- Verify the Lex bot alias `production` is built and attached to the bot

### "Voice sounds like Polly, not Nova Sonic"

- The Set Voice block must have **Generative** style selected (not Neural or Standard)
- The Lex bot locale in Connect must show `Speech-to-Speech: Amazon Nova Sonic`

---

## Next Steps After Basic Integration Works

| Enhancement | How |
|---|---|
| Real CRM lookup | Replace stub `_PHONE_TO_CUSTOMER` dict in `session_injector.py` with a real CRM API call using `CRM_API_ENDPOINT` env var |
| IVR digit collection | Add a **Store customer input** block before Block 4 to collect account digits, then pass them as a contact attribute to the Lambda |
| Dedicated agent queues | Create queues in Connect: `CustomerService`, `Fraud`, `Complaints` |
| Business hours routing | Add **Check hours of operation** block before Block 6 |
| Wait time announcement | Before **Transfer to queue**, add **Get queue metrics** then **Play prompt** with estimated wait time |
| Call recording | Already enabled by default - review in Connect -> Analytics |
| Contact Lens (PII redaction) | Connect admin -> Analytics -> Contact Lens -> Enable |
| Chat channel | Create a new flow using the same Lambda (detects `channel=CHAT` from contact data) |

---

## Reference Values

| Item | Value |
|---|---|
| AgentCore Runtime ARN | `arn:aws:bedrock-agentcore:eu-west-2:395402194296:runtime/aria_banking_agent-ubLoKG8xsY` |
| Lex Bot Name | `ARIA-Connect-Bot` |
| Lex Bot Alias | `production` |
| Session Injector Lambda | `aria-session-injector` |
| Fulfillment Lambda | `aria-lex-fulfillment` |
| Fulfillment IAM Role | `aria-lambda-fulfillment-role` |
| Connect Instance | `meridian-aria.my.connect.aws` |
| Connect Region | `eu-west-2` |
| Nova Sonic Voice | `Amy` (en-GB, Generative) |
| AgentCore Session Header | `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` |
| Test phone -> CUST-001 | `+447765309252` (James Hartley) |
| Test phone -> CUST-002 | `+447700900001` (Sarah Chen) |
