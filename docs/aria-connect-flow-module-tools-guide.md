# Amazon Connect Flow Modules as Tools — Complete Step-by-Step Guide

> **Who this is for:** Developers and contact centre admins who want to create reusable Flow Modules and connect them as callable tools to a Connect AI Agent (Q in Connect Orchestration Agent) such as ARIA.
>
> **Official references:**
> - [Flow modules for reusable functions](https://docs.aws.amazon.com/connect/latest/adminguide/contact-flow-modules.html)
> - [Create AI agents](https://docs.aws.amazon.com/connect/latest/adminguide/create-ai-agents.html)
> - [Customize Connect AI agents](https://docs.aws.amazon.com/connect/latest/adminguide/customize-connect-ai-agents.html)
> - [Contact attributes](https://docs.aws.amazon.com/connect/latest/adminguide/connect-contact-attributes.html)
> - [Set contact attributes block](https://docs.aws.amazon.com/connect/latest/adminguide/set-contact-attributes.html)

---

## What is a Flow Module?

A **Flow Module** is a reusable, self-contained section of a contact flow. Think of it like a function or a microservice inside Amazon Connect. You define the logic once and call it from many different flows.

**Why use modules?**
- Define business logic once, reuse it everywhere
- Propagate changes instantly — update the module and all flows that invoke it are updated
- Separate concerns — technical developers build modules, non-technical flow designers invoke them
- Support versioning — create immutable snapshots, test new versions before promoting

**What is a "Module as Tool"?**

A newer capability allows a Flow Module to be invoked *directly by a Connect AI Agent* — outside the normal flow context. This means an Orchestration AI Agent (like ARIA) can call a Flow Module as a tool mid-conversation to execute business logic such as:
- Checking queue status before offering a callback
- Running an authentication check
- Creating a task in the CRM
- Sending a message to the customer
- Checking hours of operation before routing

This is different from invoking a Lambda — the module runs inside Amazon Connect's flow execution engine, with access to Connect system resources (queues, hours of operation, staffing, routing profiles).

---

## Architecture Overview

```
Connect AI Agent (Orchestration — ARIA)
  │
  │ AI decides to execute a tool during conversation
  │
  ▼
Flow Module Tool: "aria-tool-check-queue-capacity"
  │
  │ (Runs inside Connect flow engine)
  │
  ├── CheckQueueStatus block
  │     ↓ Queue: ARIA-Banking-Escalations
  │     ↓ Returns: contacts_in_queue, oldest_contact_age
  │
  ├── CheckHoursOfOperation block
  │     ↓ Returns: in_hours | out_of_hours
  │
  └── Return block
        ↓ Output: {queue_available: true, wait_seconds: 45}
        ↓ Back to AI Agent
```

---

## Prerequisites

| Requirement | Where to check |
|---|---|
| Amazon Connect instance in `eu-west-2` | Connect console → Instances |
| AI Agents feature enabled | Instance settings → AI agents |
| Security profile with **Flow modules — Create, Edit, Publish** | Users → Security profiles |
| Security profile with **AI agents — Create, Edit** | Users → Security profiles |
| ARIA AI Agent already created | From the companion setup guide |
| AWS CLI configured | `aws --version` |

---

## Part 1 — Understanding Flow Modules vs Module as Tool

Before you start building, understand the key differences:

| Feature | Regular Flow Module | Module as Tool |
|---|---|---|
| **Invoked by** | Inbound contact flow (Invoke flow module block) | Connect AI Agent during conversation |
| **Can invoke another module** | No | No |
| **Input/output** | Via contact attributes | Custom typed input/output schema |
| **Custom branches** | Yes | Yes (up to 8) |
| **External attributes** | Not available inside module | Not available inside module |
| **Lex/Connect AI attributes** | Not available inside module | Not available inside module |
| **Lambda invocable** | Yes | Yes |
| **Versioning** | Yes | Yes |
| **Aliasing** | Yes | Yes |

> **Key limitation:** Modules (of both types) cannot access External attributes, Amazon Lex attributes, Customer Profiles attributes, Connect AI agents attributes, Queue metrics, or Stored customer input. Data must be passed in via the input schema or contact attributes.

---

## Part 2 — Supported Blocks in Module as Tool

When you create a Module as Tool, only the following blocks are available in the block library. If you convert an existing module, any unsupported blocks will be flagged.

| Block | Purpose |
|---|---|
| `Cases` | Create or update customer service cases |
| `ChangeRoutingPriority` | Escalate or de-escalate a contact's queue priority |
| `CheckCallProgress` | Check whether a call is connected, ringing, or in voicemail |
| `CheckContactAttributes` | Branch based on contact attribute values |
| `CheckHoursOfOperation` | Check whether it is within business hours |
| `CheckQueueStatus` | Check queue depth and oldest contact age |
| `CheckStaffing` | Check available agent staffing in a queue |
| `CheckVoiceId` | Check a customer's Voice ID authentication status |
| `CreatePersistentContactAssociation` | Associate a contact as a child of a parent contact |
| `CreateTask` | Create a task/work item in Connect |
| `CustomerProfiles` | Retrieve or update a Customer Profile record |
| `DataTable` | Look up values in a Connect data table |
| `DistributeByPercentage` | Route a percentage of contacts to different branches |
| `GetQueueMetrics` | Retrieve real-time queue metrics |
| `InvokeFlowModule` | Invoke a nested module (call another module from this module — **not** a recursive call) |
| `InvokeLambdaFunction` | Call an AWS Lambda function |
| `InvokeThirdPartyAction` | Call a registered third-party connector action |
| `Loop` | Iterate a set of blocks N times |
| `Resume` | Resume a paused contact |
| `ResumeContact` | Resume a contact from a waiting state |
| `Return` | Return control from the module to the caller, with output |
| `SendMessage` | Send a message (for chat contacts) |
| `SetAttributes` | Set contact attributes |
| `SetCallbackNumber` | Set the customer's callback number |
| `SetCustomerQueueFlow` | Override the customer queue flow |
| `SetDisconnectFlow` | Set the disconnect handling flow |
| `SetEventHook` | Configure event hooks |
| `SetHoldFlow` | Set the hold flow |
| `SetLoggingBehavior` | Enable or disable flow logging |
| `SetQueue` | Assign a contact to a queue |
| `SetRecordingAndAnalyticsBehavior` | Configure recording and Contact Lens analytics |
| `SetRoutingCriteria` | Set routing criteria for the contact |
| `SetRoutingProficiency` | Set required agent proficiencies |
| `SetVoice` | Set voice language and neural TTS voice |
| `SetVoiceId` | Set Voice ID configuration |
| `SetWhisperFlow` | Set the agent or customer whisper flow |
| `SetWisdomAssistant` | Configure the Connect AI assistant for this contact |
| `TagContact` | Add tags to the contact record |

---

## Part 3 — Create a New Flow Module as Tool (From Scratch)

We will create a practical example: **aria-tool-check-queue-status**, which the ARIA AI Agent calls when it wants to know whether it is safe to offer a callback or direct transfer.

### Step 3.1 — Navigate to Flow Modules

1. Open the Amazon Connect admin website: `https://<instance-name>.my.connect.aws/`
2. In the left navigation menu, choose **Routing** → **Contact flows**.
3. On the Contact Flows page, choose the **Modules** tab.
4. Click **Create flow module**.

### Step 3.2 — Open the Settings Tab

The module editor opens with three tabs: **Details**, **Settings**, and **Designer**.

1. Click the **Settings** tab.

This is where you configure the module as a tool with typed inputs, typed outputs, and custom branches.

### Step 3.3 — Configure Module Inputs

In the **Input** section of the Settings tab:

The input schema is an Object by default. You define the properties that the AI Agent must provide when calling this tool.

1. Click **Add property** in the Input section.
2. Add the following properties:

| Property name | Type | Description | Required |
|---|---|---|---|
| `queue_arn` | String | The ARN of the queue to check. Passed in from the AI Agent's context. | Yes |
| `max_wait_seconds` | Integer | Maximum acceptable wait time in seconds. AI Agent sets this based on customer priority. | No |

Your input schema in JSON Schema mode should look like this:
```json
{
  "type": "object",
  "properties": {
    "queue_arn": {
      "type": "string",
      "description": "ARN of the Connect queue to check availability for"
    },
    "max_wait_seconds": {
      "type": "integer",
      "description": "Maximum acceptable wait time in seconds"
    }
  },
  "required": ["queue_arn"]
}
```

### Step 3.4 — Configure Module Outputs

In the **Output** section of the Settings tab, define what the module returns to the AI Agent.

1. Click **Add property** in the Output section.
2. Add the following properties:

| Property name | Type | Description |
|---|---|---|
| `queue_available` | Boolean | Whether the queue has agents available and is within hours |
| `contacts_in_queue` | Integer | Current number of contacts waiting |
| `estimated_wait_seconds` | Integer | Estimated wait time in seconds |
| `in_hours` | Boolean | Whether the queue is within its configured hours of operation |
| `message` | String | A human-readable description to pass back to the AI Agent |

Your output schema in JSON Schema mode:
```json
{
  "type": "object",
  "properties": {
    "queue_available": {
      "type": "boolean",
      "description": "True if the queue is available and within acceptable wait time"
    },
    "contacts_in_queue": {
      "type": "integer",
      "description": "Number of contacts currently waiting in the queue"
    },
    "estimated_wait_seconds": {
      "type": "integer",
      "description": "Estimated wait time for a new contact"
    },
    "in_hours": {
      "type": "boolean",
      "description": "Whether the queue is currently within its hours of operation"
    },
    "message": {
      "type": "string",
      "description": "Human-readable summary for the AI Agent to use in its response"
    }
  }
}
```

### Step 3.5 — Configure Custom Branches

In the **Branches** section of the Settings tab, define the routing branches the module can return.

By default, modules have **Success** and **Error** branches. For this module, add:

1. Click **Add branch**.
2. Add branch: `QueueAvailable` — "Queue has agents and acceptable wait time"
3. Add branch: `QueueUnavailable` — "Queue is busy, out of hours, or wait time exceeds limit"
4. Add branch: `Error` — "An error occurred checking the queue"

You can define up to **8 custom branches**.

### Step 3.6 — Build the Module Logic in the Designer

Click the **Designer** tab. You will add blocks to implement the queue check logic.

**Block 1: Check Hours of Operation**

1. Drag a **Check hours of operation** block.
2. Connect it to the module's **Entry** point.
3. Configure:
   - **Hours of operation:** Select your `ARIA-Banking-Hours` (or your relevant hours of operation resource)
4. Connect:
   - **In hours** → Block 2
   - **Out of hours** → Set Attributes (out_of_hours result)
   - **Error** → Error branch

**Block 2: Get Queue Metrics**

1. Drag a **Get queue metrics** block.
2. Connect from the **In hours** branch.
3. Configure:
   - **Queue:** Use attribute reference — `$.Attributes.queue_arn` (the input we defined)
   - **Metrics to retrieve:** Contacts in queue, Oldest contact in queue

> **Important:** To pass the input `queue_arn` from the module inputs into a block that needs a queue reference, use the **Set contact attributes** block first to copy `$.Module.Input.queue_arn` to a contact attribute called `queue_arn`. Then reference `$.Attributes.queue_arn` in the queue block.

**Block 2a: Set Contact Attributes (copy inputs to attributes)**

Before the queue check, add a **Set contact attributes** block to copy module inputs to contact attributes:

1. Drag a **Set contact attributes** block.
2. Connect it between the hours check and the queue metrics block.
3. Configure:
   - Destination type: **User defined**
   - Key: `queue_arn` | Value type: **Module input** | Value: `$.Module.Input.queue_arn`
   - Key: `max_wait_seconds` | Value type: **Module input** | Value: `$.Module.Input.max_wait_seconds`

**Block 3: Check Queue Status**

1. Drag a **Check queue status** block.
2. Connect from **Get queue metrics**.
3. Configure conditions:
   - Compare `$.QueueMetrics.ContactsInQueue` **Less than or equal to** `10`
4. Connect:
   - **True (within limit)** → Set Output Attributes (available)
   - **False (over limit)** → Set Output Attributes (unavailable)

**Block 4a: Set Output — Available**

1. Drag a **Set contact attributes** block.
2. Configure to write module output values:
   - Key: `$.Module.Output.queue_available` | Value: `true`
   - Key: `$.Module.Output.in_hours` | Value: `true`
   - Key: `$.Module.Output.contacts_in_queue` | Value type: **Queue metric** | `$.QueueMetrics.ContactsInQueue`
   - Key: `$.Module.Output.message` | Value: `The queue is available and accepting contacts.`
3. Connect **Success** to a **Return** block branching to `QueueAvailable`.

**Block 4b: Set Output — Unavailable**

1. Drag another **Set contact attributes** block.
2. Configure:
   - Key: `$.Module.Output.queue_available` | Value: `false`
   - Key: `$.Module.Output.in_hours` | Value: `true`
   - Key: `$.Module.Output.message` | Value: `The queue is currently busy. Estimated wait may exceed acceptable limits.`
3. Connect **Success** to a **Return** block branching to `QueueUnavailable`.

**Block 4c: Set Output — Out of Hours**

1. Drag another **Set contact attributes** block.
2. Configure:
   - Key: `$.Module.Output.queue_available` | Value: `false`
   - Key: `$.Module.Output.in_hours` | Value: `false`
   - Key: `$.Module.Output.message` | Value: `The queue is outside its operating hours.`
3. Connect **Success** to a **Return** block branching to `QueueUnavailable`.

**Block 5: Return Blocks**

Add a **Return** block for each branch:
- `QueueAvailable` Return — on success path
- `QueueUnavailable` Return — on busy/out-of-hours paths
- `Error` Return — on error paths from any block

The Return block signals to the AI Agent that the tool execution is complete and passes back the output.

### Step 3.7 — Complete Designer View

Your module flow should look like this:

```
Entry
  │
  ▼
Set Attributes (copy inputs → attributes)
  │ Success
  ▼
Check Hours of Operation
  │ In hours           │ Out of hours       │ Error
  ▼                    ▼                    ▼
Get Queue Metrics   Set Output           Error Return
  │                 (out_of_hours)
  ▼
Check Queue Status (contacts ≤ 10?)
  │ True (available)    │ False (busy)
  ▼                     ▼
Set Output            Set Output
(available=true)      (available=false)
  │                     │
  ▼                     ▼
Return                Return
(QueueAvailable)      (QueueUnavailable)
```

### Step 3.8 — Save and Publish the Module

1. Click **Save** to save a draft.
2. Click **Publish** to publish version 1. The module status changes to **Published**.
3. Note the **Module ARN** from the URL or the module detail page.

---

## Part 4 — Convert an Existing Module to a Tool

If you already have a regular flow module that you want to expose to the AI Agent:

### Step 4.1 — Open the Existing Module

1. Choose **Routing** → **Contact flows** → **Modules**.
2. Click on the module you want to convert.
3. Click **Edit**.

### Step 4.2 — Navigate to Settings Tab

1. Click the **Settings** tab.
2. In the **Module type** section, toggle **Enable as tool**.

You will see a warning if any blocks in your module are not supported as tool blocks. The unsupported blocks will be listed. You must remove or replace them before converting.

### Step 4.3 — Common Blocks to Replace

| Unsupported block | Replace with |
|---|---|
| `Play prompt` | Remove — AI Agent generates speech; don't need TTS inside a tool |
| `Get customer input` | Remove — AI Agent handles conversation; tool should just return data |
| `Lex bot` | Replace with Lambda that calls Lex directly |
| `Set voice` | Remove — not needed inside a tool |
| `Disconnect` | Replace with a **Return** block on the Error branch |

### Step 4.4 — Define Input/Output Schema

After enabling as tool, the Settings tab shows the input and output schema editors. Define them as described in Part 3 Steps 3.3 and 3.4.

### Step 4.5 — Publish

Click **Save** then **Publish**.

---

## Part 5 — Version and Alias Management

AWS recommends using versions and aliases to manage your module tools safely.

### Step 5.1 — Create a Version

After publishing, create a named immutable version:

1. On the module detail page, click **Create version**.
2. Enter a description: `v1.0.0 — Initial queue check implementation`.
3. Click **Create**. The version is now immutable — you cannot edit it.

### Step 5.2 — Create an Alias

Aliases let your AI Agent always call a stable name rather than a specific version number.

1. On the module detail page, click **Create alias**.
2. **Alias name:** `stable`
3. **Points to version:** `1` (the version you just created)
4. Click **Create**.

### Step 5.3 — Use Aliases When Assigning to AI Agent

When you add this module as a tool to the AI Agent (next section), reference the `stable` alias rather than a version number. When you release a new version, update the alias to point to the new version — the AI Agent picks it up automatically with no prompt or agent changes required.

---

## Part 6 — Connect the Module Tool to the ARIA AI Agent

Now that the module is published as a tool, wire it into the ARIA AI Agent.

### Step 6.1 — Navigate to the AI Agent

1. In the Connect admin website, choose **AI agent designer** → **AI agents**.
2. Click on `ARIA-Banking-Agent`.
3. Click **Edit**.

### Step 6.2 — Add the Module Tool

1. In the **Tools** section of the AI Agent builder page, click **Add tool**.
2. Select **Flow module** as the tool type.
3. In the dropdown, select `aria-tool-check-queue-status` → alias `stable` (or the specific version).
4. The tool name, input schema, and output schema are automatically populated from the module settings.
5. Add a **Tool description** that guides the AI Agent on when to use it:
   ```
   Check whether the escalation queue currently has available agents and an acceptable wait time. 
   Call this tool before offering a human agent transfer to give the customer an accurate wait time estimate.
   Returns: queue_available (bool), estimated_wait_seconds (int), in_hours (bool), and a message string.
   ```
6. Click **Save tool**.

### Step 6.3 — Update the AI Prompt to Reference the Tool

Open the AI Prompt assigned to ARIA (`ARIA-Banking-Orchestration-Prompt`):

1. Choose **AI agent designer** → **AI prompts**.
2. Click `ARIA-Banking-Orchestration-Prompt` → **Edit**.
3. In the YAML, add the new tool to the `tools:` section:

```yaml
  - name: check_queue_status
    description: >
      Check whether a specific Connect queue has available agents and an acceptable wait time.
      Call before offering to transfer the customer to a human agent.
      Returns queue_available, estimated_wait_seconds, in_hours, and a summary message.
    input_schema:
      type: object
      properties:
        queue_arn:
          type: string
          description: The ARN of the Connect queue to check, e.g. arn:aws:connect:eu-west-2:395402194296:instance/.../queue/...
        max_wait_seconds:
          type: string
          description: Maximum acceptable wait time in seconds. Use 120 for standard, 30 for urgent/safeguarding.
      required: [queue_arn]
```

4. In the system prompt instructions, add guidance for when ARIA should call this tool:

```yaml
  ## Escalation Pre-check
  Before offering a human agent transfer, call check_queue_status in <thinking>.
  If queue_available is false or in_hours is false: inform the customer in <message>
  that agents are not currently available and offer a callback or alternative.
  If queue_available is true: proceed with escalation using the estimated_wait_seconds
  value to set customer expectations in <message>.
```

5. Click **Save**, then **Publish** to create a new version.
6. Go back to the AI Agent and update it to use the new prompt version.

---

## Part 7 — More ARIA Tool Module Examples

Below are step-by-step recipes for additional module tools useful for ARIA.

### Tool Module 7.1 — aria-tool-create-callback-task

**Purpose:** When ARIA cannot immediately connect a customer, create a task in Connect for a human agent to call back.

**Input schema:**
```json
{
  "type": "object",
  "properties": {
    "customer_id":     { "type": "string", "description": "Authenticated customer ID" },
    "callback_number": { "type": "string", "description": "Vault reference or masked phone number" },
    "reason":          { "type": "string", "description": "Reason for callback request" },
    "priority":        { "type": "string", "description": "standard | urgent | safeguarding" }
  },
  "required": ["customer_id", "reason", "priority"]
}
```

**Output schema:**
```json
{
  "type": "object",
  "properties": {
    "task_created":  { "type": "boolean" },
    "task_id":       { "type": "string" },
    "task_ref":      { "type": "string", "description": "Human-readable reference for the customer" },
    "message":       { "type": "string" }
  }
}
```

**Branches:** `TaskCreated`, `TaskFailed`, `Error`

**Key blocks to use:**
1. **Set contact attributes** — copy inputs to attributes
2. **Create task** block — configure: `Name = Callback Request — {{$.Attributes.customer_id}}`, `Description = {{$.Attributes.reason}}`, route to `ARIA-Callbacks` queue
3. **Set contact attributes** — write task_created=true, task_id from `$.Task.TaskId`
4. **Return** blocks for each branch

---

### Tool Module 7.2 — aria-tool-check-staffing

**Purpose:** Check whether any agents in a specific routing profile/queue are currently available.

**Input schema:**
```json
{
  "type": "object",
  "properties": {
    "queue_arn": { "type": "string", "description": "ARN of the queue to check staffing for" }
  },
  "required": ["queue_arn"]
}
```

**Output schema:**
```json
{
  "type": "object",
  "properties": {
    "agents_available": { "type": "integer", "description": "Number of available agents" },
    "agents_online":    { "type": "integer", "description": "Total agents online" },
    "staffed":          { "type": "boolean", "description": "True if at least one agent is available" }
  }
}
```

**Branches:** `Staffed`, `Understaffed`, `NotStaffed`, `Error`

**Key blocks:**
1. **Check staffing** block — check available agents in the specified queue
2. Condition branches for `agents_available > 0` → Staffed, else NotStaffed
3. **Return** blocks

---

### Tool Module 7.3 — aria-tool-set-recording-flag

**Purpose:** Set Contact Lens recording and analytics flags for compliance (e.g., enable PCI-DSS hold during card number capture).

**Input schema:**
```json
{
  "type": "object",
  "properties": {
    "recording_enabled":    { "type": "boolean" },
    "analytics_enabled":    { "type": "boolean" },
    "pci_mode":             { "type": "boolean", "description": "If true, pauses recording for PCI compliance" }
  },
  "required": ["pci_mode"]
}
```

**Output schema:**
```json
{
  "type": "object",
  "properties": {
    "recording_status": { "type": "string" },
    "analytics_status": { "type": "string" }
  }
}
```

**Key blocks:**
1. **Check contact attributes** — check pci_mode value
2. **Set recording and analytics behavior** block — configure recording on/off, Contact Lens on/off
3. **Return** blocks

---

## Part 8 — Testing the Module Tool Integration

### Step 8.1 — Test the Module in Isolation

Before connecting it to ARIA, test the module works on its own:

1. In the Connect flow designer, create a temporary **Test inbound flow**.
2. Add an **Invoke flow module** block.
3. Select `aria-tool-check-queue-status` and configure the input attributes.
4. Add a **Play prompt** block after the module that says the output attribute values using text-to-speech.
5. Publish the test flow, assign it to a test phone number, and call in.
6. Verify the prompt reads back the correct queue status.

### Step 8.2 — Test via Connect Test Chat

1. In the Connect admin website, choose **Test chat**.
2. Select your ARIA inbound flow.
3. Type: `Are there agents available if I need to be transferred?`
4. ARIA should call `check_queue_status` (visible in thinking tags if the prompt includes thinking output) and respond with queue availability.

### Step 8.3 — Verify in CloudWatch

1. In the CloudWatch console, open log group `/aws/connect/<instance-id>/flow-logs`.
2. Filter by your module's ARN.
3. Confirm the module was invoked and returned the expected output attributes.

---

## Part 9 — Versioning Strategy

AWS recommends this versioning workflow for production module tools:

```
Development          Staging              Production
    │                    │                    │
    ▼                    ▼                    ▼
[Draft edits]    [Version N+1]          [Version N]
                         │                    │
                    alias: staging        alias: stable
                         │                    │
                    AI Agent (test)    AI Agent (prod)
```

1. **Always work on drafts** — edit and test in draft mode.
2. **Create a version** when the draft is ready to test in staging.
3. **Update the staging alias** to point to the new version.
4. **Run regression tests** against the staging AI Agent.
5. **Update the production alias** (`stable`) to the new version when tests pass.
6. **ARIA's AI Agent** references the `stable` alias — zero downtime upgrade.

---

## Part 10 — Troubleshooting

### Module tool is not visible in the AI Agent tool picker

1. Confirm the module was published (not just saved as draft).
2. Confirm the module was enabled as a tool in the **Settings** tab.
3. Confirm your user has **AI agents — Edit** permission in their security profile.
4. Wait 1–2 minutes for the tool to propagate.

### AI Agent calls the tool but gets no output

1. Check that your module has **Return** blocks on all exit paths.
2. Confirm the output schema properties are being written correctly (use `$.Module.Output.<property>` syntax in Set contact attributes blocks).
3. Check flow logs in CloudWatch for error messages from inside the module.

### Input attributes not available inside the module

1. Copy module inputs to contact attributes in the first block of the module using a **Set contact attributes** block: Key: `myattr`, Value type: **Module input**, Value: `$.Module.Input.myattr`.
2. Then reference `$.Attributes.myattr` inside the module.

### Module conversion from existing module fails

1. Check for unsupported blocks (the console lists them in red). Replace or remove each one.
2. The most common unsupported blocks are `Play prompt`, `Get customer input`, and `Set voice` — remove these.
3. Confirm no module invokes another module recursively.

---

## Appendix — Module Attribute Namespaces

| Namespace | Available in | Example |
|---|---|---|
| `$.Module.Input.<key>` | Inside module | `$.Module.Input.queue_arn` |
| `$.Module.Output.<key>` | Set by module, read by caller | `$.Module.Output.queue_available` |
| `$.Module.Branch` | After invocation, read by calling flow | `$.Module.Branch` → `QueueAvailable` |
| `$.Attributes.<key>` | Inside module (after Set contact attributes) | `$.Attributes.queue_arn` |
| `$.QueueMetrics.*` | After Get queue metrics block | `$.QueueMetrics.ContactsInQueue` |
| `$.Task.TaskId` | After Create task block | `$.Task.TaskId` |
