# CX designer configuration — "Card dispute assistant"

Everything to create in the agentic CX designer for the Live Sync dispute route (SPEC Part 3,
route 3). Create the resources in section 1 first; a flow can only pick what already exists.
The click-by-click mechanics are the same as for the mortgage application: see
`connect-livesync-mortgage/docs/GUIDE.md` Parts 3 to 5. This file gives the values.

Use the workspace you already have (`ariaworkspace`). Typing `{` in a text field opens the menu of
variables and Secrets; always insert them from that menu, never type the braces by hand.

## 1. Resources

### 1a. Context variables

| Name | Type | Allow frontend updates | Set by | Used for |
|------|------|------------------------|--------|----------|
| `entry` | String | On | Connect | `phone`: how the customer arrived |
| `contactId` | String | On | Connect (namespace **System**, **Contact id**) | `attachToScreen` |
| `firstName` | String | On | Connect | greeting |
| `verification` | String | On | Connect | `authenticated` or not |
| `handoverSummary` | String | On | Connect | what the customer already told ARIA |
| `screenCode` | String | On | Connect | the code the customer read to ARIA |
| `summary` | String | Off | the assistant | sent to the adviser |
| `topicCategory` | String | Off | the assistant | which team the contact goes to |
| `escalationReason` | String | Off | the assistant | sent to the adviser |

### 1b. Secret

Create a Secret named `card_dispute_api_key`. Its value is the key the deploy script made: in the
AWS console open **Secrets Manager**, the secret `aria-card-dispute/acxd-key`, **Retrieve secret
value**, and copy it across. Nobody needs to see it again after that.

### 1c. Data request: `attachToScreen`

| Setting | Value |
|---------|-------|
| Name | `attachToScreen` |
| Description | Connects this call to the card dispute page the customer has open. Call it once, with the 6 digits the customer read from that page. attached=true means their screen is now connected and the form will appear. locked=true means too many wrong codes: carry on without the screen. |
| Implementation | External, `POST` |
| Endpoint URL (both environments) | the "CX designer tool address" the deploy script printed, ending `/acxd/ops` |
| Header | `Content-Type` = `application/json` |
| Header | `x-api-key` = the Secret `card_dispute_api_key` (insert with `{`) |
| Request sample | `{"operation":"attachToScreen","contactId":"0a1b2c3d-1111-2222-3333-444455556666","code":"482913"}` |
| Response sample | `{"attached":true,"locked":false,"reason":""}` |
| Sensitive | the field `code`, and the Data request itself |

Keep every request field at the top level. The address accepts no other operation.

There is deliberately no Data request to confirm or submit a dispute, and none that takes a
customer ID: the service works out the customer from the call itself.

## 2. Flow `HandDisputeToAdviser`

Build this first; the main flow points to it. After **Start**, add three **Generative text** nodes
in a row. Connect Success, Failure and Timeout of each to the next, so an empty answer never
blocks the hand-off.

| # | Output variable | Prompt |
|---|-----------------|--------|
| 1 | `handoffSummary` | "In one or two sentences for a bank adviser, say which card payment the customer is disputing (retailer and amount), whether they made the payment, and what is still to be filled in on the form, using {System.transcript}. Do not include card numbers or any code." |
| 2 | `handoffTopic` | "Which team should take this? Output exactly one of: fraud_security, debit_card, credit_card. Output fraud_security if the customer did not make or does not recognise the payment. Otherwise output debit_card or credit_card for the card the payment was on. No markdown, no explanation. Conversation: {System.transcript}" |
| 3 | `handoffReason` | "Why is this going to a person? Output exactly one of: dispute_ready_for_review, customer_request, vulnerability, tool_failure, other. No markdown, no explanation. Conversation: {System.transcript}" |

Then an **Escalate** node:

- **Message**: "Thank you. I'm passing you to a colleague who'll check the form with you and submit
  it. You won't need to repeat anything."
- **State modifications**, one **Set** per row:

| Context variable | Value |
|------------------|-------|
| `summary` | `Card dispute drafted on the customer's screen. {handoffSummary}` |
| `topicCategory` | `{handoffTopic}` |
| `escalationReason` | `{handoffReason}` |

Only context variables set this way reach Connect. Leave the Escalate node's Continuation
unconnected.

## 3. Flow `CardDispute` (the main flow): the Live Sync node

### 3a. Agent prompt

```
You are the card dispute assistant for Nationwide Building Society. The customer is on the phone
and has our card dispute form open on their screen. You fill the form in with them. Every change
you make appears on their screen, and they can type in it themselves.

Call details (empty when not known):
entry: {entry} | contact: {contactId} | first name: {firstName} | verified: {verification}
already said to our phone assistant: {handoverSummary}
code read out before the hand-off: {screenCode}

First
- If "verified" is not "authenticated", do not attach a screen or fill anything: say you will pass
  them to a colleague, and use Escalation requested.
- If the screen is not attached yet (no form fields in the page context), call attachToScreen once
  with {contactId} and {screenCode}. If attached is false, ask them to read the six digits on their
  screen again and try once more. If locked is true or it still fails, use Escalation requested.
- When the form appears, say in one sentence that you can see it. Do not greet again or ask them
  to repeat what "already said" covers.

Filling the form
- Work down the form in order: which payment, whether they made it, what went wrong, whether they
  still have the card or have contacted the retailer, and what happened in their own words.
- Ask for one detail at a time. Fill the matching field as soon as they answer, using the fields
  and options in the page context, then say briefly what you filled.
- For a dropdown, use one of the options shown for that field. For "which payment", choose the
  option that matches the retailer, amount or date they give. If two match, ask one question to
  tell them apart. If none match, say you cannot see that payment and use Escalation requested.
- "Did you make this payment?" decides which reasons are offered, so fill it before the reason.
- For "in your own words", write what they said. Do not improve it.
- Never say you have filled something unless you sent it to the page.

Finishing
- When every field on the form is filled, read the dispute back in one or two sentences and ask if
  it is right. Correct anything they change.
- Then use Escalation requested. A colleague checks the form with them and submits it.

What you never do
- Never submit, confirm or accept a dispute, and never say it has been submitted or accepted.
- Never state or guess a refund, a timescale or an outcome. Say: "My colleague will explain what
  happens next."
- Never read a code aloud yourself, and never read out a full card number.
- Never block a card: you cannot. If they want it blocked, say your colleague will do it next.
- Never say you are transferring or connecting them unless you use Escalation requested in the
  same turn. Asking for a person is always Escalation requested.

Vulnerability
- If the customer is distressed, confused, or mentions bereavement, illness or money worries,
  acknowledge it kindly and use Escalation requested.

Tone
- Warm, plain English, UK spelling. Two short sentences per turn at most.
```

Re-insert every `{name}` in the prompt with the `{` menu so it becomes a real variable.

### 3b. Tools

| Type | Name | Tool prompt |
|------|------|-------------|
| Data request | `attachToScreen` | The Description from 1c |
| Data capture | none | Don't add it. The page holds the details. |

### 3c. Live Sync actions

None. Paste `acxd/live-sync-actions.json` (an empty list). The form is filled with Touchpoint's own
form fill. There is one page, so there is no navigation, and there is no action that confirms or
submits.

### 3d. Exit conditions

| Name | Description for the agent | Connect to |
|------|---------------------------|------------|
| Escalation requested | Use when the form is complete and read back, when the customer asks for a person, when the screen cannot be attached, when the payment cannot be found, when the customer is not verified, or at any sign of vulnerability. Always use this exit for any transfer. | Redirect to `HandDisputeToAdviser` |
| Unable to help | A tool failed twice. | Redirect to `HandDisputeToAdviser` |

Also connect **Timeout** and **Failure** to `HandDisputeToAdviser`. There is no "Task complete"
exit: this assistant never finishes a dispute; an adviser does.

## 4. Build, test, deploy

Create the application (name it `Card dispute`), add the `CardDispute` flow as its entry, build
and deploy it to an environment, as in the mortgage guide Part 5. Note three things for later:

- the application's name, to pick in the Connect flow block;
- its **deployment key** and **API key**, for the page (README Part J, step 3).
