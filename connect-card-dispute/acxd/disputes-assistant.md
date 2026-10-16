# CX designer guide — the "Card dispute" assistant

This guide builds, step by step, the assistant that takes a card dispute over from ARIA. It is
written for someone who has never built anything in agentic CX designer. Every click is listed,
and each part ends with a check, so you know it worked before you move on.

**What the assistant does.** When a customer tells ARIA they want to dispute a card payment, ARIA
passes them to this assistant without saying so. The assistant then:

- finds the payment;
- fills in the dispute form, asking only for what it doesn't already know;
- blocks the card and orders a replacement, if the customer says yes;
- shares the form if the customer wants to see it: **texted** on a phone call, **posted in the
  chat** on chat.

When it's finished, it hands the customer back, and Connect passes them to an adviser, who checks
the form and submits it.

It works the same on a **phone call** and on **chat**.

**Time:** allow about two hours the first time. You can stop between parts; everything you save is
kept.

---

## Before you start

**Have these open:**

1. **This file**, in VS Code. You'll copy text from it. Always copy from the file, not from a chat
   or an email, so nothing gets changed on the way.
2. **The AWS console**, signed in, region **Europe (London)** (top right).
3. **The output of `deploy_card_dispute.sh`** (README step 2). You need one line from it, the
   **Data request address**, which looks like
   `https://abcd1234.execute-api.eu-west-2.amazonaws.com/acxd/ops`.

**Five words you'll meet:**

| Word | What it means |
|---|---|
| **Workspace** | A container for everything you build. Your mortgage assistant lives in `ariaworkspace`; so will this one, and it shares some of the mortgage assistant's pieces |
| **Resource** | Something flows use: a context variable, a Secret, a Data request. Created once, in the workspace |
| **Flow** | A diagram of boxes (**nodes**) joined by lines (**paths**). It's the script of the conversation |
| **Application** | A package of flows that you build and deploy. Connect talks to the application |
| **Chip** | A coloured tag inside a text box that stands for a variable or Secret. You insert it from a menu; you never type it |

**Three habits that avoid almost every problem:**

1. **Never type `{` … `}` by hand.** When a value in this guide contains `{something}`, type only
   `{`. A menu opens; choose the item. It turns into a chip. Text you type with braces is sent as
   plain text, and the assistant breaks without any error message.
2. **Save often.** Nothing saves on its own. If you close the tab without saving, it's gone.
3. **Type names exactly.** `CardDispute` and `carddispute` are different things to the designer.

---

## Part 1 — Open the designer and your workspace

1. In the AWS console, type `Amazon Connect` in the search bar at the top and open it.
2. You see a list of instances. Click your instance's **alias**, the blue link in the first
   column. Don't tick the checkbox.
3. On the instance page, look for **agentic CX designer** (in the left menu or on the page) and
   click it. It opens in a new browser tab.
4. At the **top left** there's a drop-down with a workspace name. Click it and choose
   **`ariaworkspace`**.

✅ **Check:** in the left menu, open **Resources** → **Data requests**. You see your mortgage
assistant's Data requests (for example `attachToScreen`). That proves you're in the right workspace.

---

## Part 2 — Create the resources

Resources come first, because a flow can only use a resource that already exists.

### 2a. Context variables (7 used, only 1 to create)

**What they are.** A context variable is a named box that carries a value between Connect and the
assistant. Connect puts values in when the conversation starts (for example the customer's first
name), and the assistant puts values in when it finishes (for example its note for the adviser).
Connect can only fill a box that has **Allow frontend updates** switched on.

They belong to the whole workspace, so the mortgage assistant's boxes are shared with this one.
Six of the seven this assistant uses already exist from the mortgage build
([connect-livesync-mortgage](https://github.com/alokkulkarni/connect-livesync-mortgage), GUIDE
Part 3a). **Don't create those again; only check them.**

**Check the six that exist:**

1. Left menu → **Resources** → **Context variables**. A list appears.
2. Find each row marked "Yes" in the table below. Click it, check **Type** is **String** and **Allow
   frontend updates** is as shown, and close it without changing anything.
3. If one is missing (it shouldn't be), create it as below.

**Create the new one:**

4. Click **Add context variable**.
5. **Name**: `channel`. **Type**: **String**. **Allow frontend updates**: switch it **On**.
6. **Save**.

| Name | Type | Allow frontend updates | Already there? | What it holds here |
|------|------|------------------------|----------------|--------------------|
| `entry` | String | On | Yes (mortgage) | where the customer came from: `aria` |
| `contactId` | String | On | Yes (mortgage) | the call's or chat's ID; every Data request sends it |
| `firstName` | String | On | Yes (mortgage) | the customer's first name |
| `handoverSummary` | String | On | Yes (mortgage) | what the customer already told ARIA |
| `channel` | String | On | **No: create it** | `VOICE` or `CHAT` |
| `summary` | String | Off | Yes (mortgage) | the assistant's note for the adviser |
| `escalationReason` | String | Off | Yes (mortgage) | why the customer goes to a person |

Sharing them with the mortgage assistant is safe: every conversation has its own values. The
mortgage flows keep setting `entry` to `phone` or `web_widget`; only this assistant sees `aria`.

There's no "verified" variable. The dispute service checks every request itself, and answers
`customer_not_identified` for anyone ARIA didn't verify; the assistant then passes them to a
colleague.

✅ **Check:** the list shows `channel`, and the six others are as in the table.

### 2b. The Secret (1)

**What it is.** The assistant's tools call the dispute service over the internet. The service only
answers callers who present the right key, like a password. The deploy script created that key in
AWS Secrets Manager; you copy it into the designer once, as a **Secret**, so the tools can present
it without anyone seeing it.

This is a new Secret. The mortgage assistant's `mortgage_api_key` unlocks a different service and
won't work here.

1. **AWS console tab**: search `Secrets Manager` and open it.
2. Click the secret named **`aria-card-dispute/acxd-key`**.
3. Scroll to **Secret value** → click **Retrieve secret value** → click the copy icon next to the
   value.
4. **Designer tab**: left menu → **Resources** → **Secrets** → **Add secret**.
5. **Name**: `card_dispute_api_key`. **Value**: paste (Cmd+V). **Save**.
6. Don't paste the key anywhere else (not in notes, chats or emails).

✅ **Check:** `card_dispute_api_key` appears in the Secrets list. The designer won't show its value
again; that's normal.

### 2c. Data requests (7)

**What they are.** A Data request is one tool the assistant can use: a call to the dispute service.
Each has a **name**, a **description** the assistant reads to decide when to use it, and a
**request** and **response** shape. All seven call the same address; only the `operation` field and
the other fields differ.

Below are seven sections, one per Data request, each with every step and every value written out.
Do them in order. Each takes about five minutes. Already made them? Open each one and compare it
with its section: the description and both samples must match exactly. Where they differ, paste
the new ones and **Auto-generate** the models again.

Every reply has `ok`, `reason` and `message`. When `ok` is false, `message` tells the assistant what
to do, and it follows it. None of these takes a customer ID or a phone number: the service finds
both from the call or chat itself, and does nothing for a customer ARIA didn't verify. None can
confirm or submit a dispute.

If a test goes wrong:
- **`401`**: the `x-api-key` header isn't using the Secret chip (step 4.5).
- **The response sample comes back unchanged**: the Data request is Static; choose External.
- **Timeout or "could not connect"**: the endpoint URL is wrong; copy it again from the deploy output.

#### `listCardsAndPayments`

Data request 1 of 7. This one looks up the customer's cards and one page of their recent payments.

1. Left menu → **Resources** → **Data requests** → **New data request**.
2. **Name**: `listCardsAndPayments`
3. **Description**: copy and paste this (the assistant reads it, so don't change it):
   ```text
   Customer's cards and one page of 5 card payments, newest first, numbered. page 1 is newest; 2, 3 are older. Optional fromDate/toDate (YYYY-MM-DD) and cardType. Show the list to the customer.
   ```
4. Open the **Implementation** tab and choose **External** (not Static).
   1. **Method**: `POST`.
   2. **Production** endpoint URL: the **Data request address** from the deploy script.
   3. **Development** endpoint URL: the same address.
   4. **Headers** → add a header: key `Content-Type`, value `application/json`.
   5. Add a second header: key `x-api-key`. Click in its value box, type `{`, choose **Secrets**,
      then `card_dispute_api_key`. It becomes a chip.
5. **Request model** → **Auto-generate** (star icon) → paste this, then confirm:
   ```json
   {"operation":"listCardsAndPayments","contactId":"0a1b2c3d-1111-2222-3333-444455556666","page":1,"fromDate":"2026-10-01","toDate":"2026-10-15","cardType":"debit"}
   ```
   Check that `page` came out as type **Number**, not Text.
6. **Response model** → **Auto-generate** → paste this, then confirm:
   ```json
   {"ok":true,"reason":"","message":"","today":"2026-10-15","cards":[{"cardType":"debit","cardLastFour":"4821","status":"active"}],"payments":[{"number":1,"transactionId":"TXN-4821-20261011-8999","date":"2026-10-11","merchant":"AMAZON.CO.UK","amount":"89.99","cardType":"debit","cardLastFour":"4821","label":"11 Oct 2026, AMAZON.CO.UK, £89.99, debit card ending 4821"}],"page":1,"totalPages":2,"totalPayments":8,"hasMore":true}
   ```
7. **Save**.
8. **Test**: **Test** tab → environment **Development** → enter these values → **Run**:
      - `operation`: `listCardsAndPayments`
      - `contactId`: `0a1b2c3d-1111-2222-3333-444455556666`
      - `page`: `1`
      - `fromDate`: `2026-10-01`
      - `toDate`: `2026-10-15`
      - `cardType`: `debit`

   ✅ `"ok": false` and `"reason": "customer_not_identified"`. That's correct for a test (no real
   verified customer), and proves it reached the service. ❌ `401`: redo step 4.5.

The same two samples, for reference only (nothing more to do):

| Request sample | `{"operation":"listCardsAndPayments","contactId":"0a1b2c3d-1111-2222-3333-444455556666","page":1,"fromDate":"2026-10-01","toDate":"2026-10-15","cardType":"debit"}` |
|---|---|
| Response sample | `{"ok":true,"reason":"","message":"","today":"2026-10-15","cards":[{"cardType":"debit","cardLastFour":"4821","status":"active"}],"payments":[{"number":1,"transactionId":"TXN-4821-20261011-8999","date":"2026-10-11","merchant":"AMAZON.CO.UK","amount":"89.99","cardType":"debit","cardLastFour":"4821","label":"11 Oct 2026, AMAZON.CO.UK, £89.99, debit card ending 4821"}],"page":1,"totalPages":2,"totalPayments":8,"hasMore":true}` |

#### `startDispute`

Data request 2 of 7. This one starts the dispute for the payment the customer chose.

1. Left menu → **Resources** → **Data requests** → **New data request**.
2. **Name**: `startDispute`
3. **Description**: copy and paste this (the assistant reads it, so don't change it):
   ```text
   Starts the case for the chosen payment (transactionId or its number). disputeType: unauthorised (fraud: not made), scam (made, but tricked) or merchant (made, but went wrong).
   ```
4. Open the **Implementation** tab and choose **External** (not Static).
   1. **Method**: `POST`.
   2. **Production** endpoint URL: the **Data request address** from the deploy script.
   3. **Development** endpoint URL: the same address.
   4. **Headers** → add a header: key `Content-Type`, value `application/json`.
   5. Add a second header: key `x-api-key`. Click in its value box, type `{`, choose **Secrets**,
      then `card_dispute_api_key`. It becomes a chip.
5. **Request model** → **Auto-generate** (star icon) → paste this, then confirm:
   ```json
   {"operation":"startDispute","contactId":"0a1b2c3d-1111-2222-3333-444455556666","transactionId":"TXN-4821-20261011-8999","disputeType":"unauthorised"}
   ```
6. **Response model** → **Auto-generate** → paste this, then confirm:
   ```json
   {"ok":true,"reason":"","message":"","disputeId":"DSP-ABCD2345","status":"draft","payment":"AMAZON.CO.UK, £89.99 on 2026-10-11, debit card ending 4821","disputeType":"unauthorised","caseType":"Fraud","whatHappensNext":"Our fraud team will investigate this payment. Fraud cases are usually looked into within 15 working days, and we'll keep you updated. A colleague will now check the details with you.","reasonCode":"","reasonsAllowed":"card_lost_or_stolen, card_details_used_without_card, not_recognised","cardInPossession":"","cardBlocked":"","contactedMerchant":"","narrative":"","missing":"Reason, Customer still has the card, In the customer's words","complete":false,"customerWatching":false,"linkSent":false}
   ```
7. **Save**.
8. **Test**: **Test** tab → environment **Development** → enter these values → **Run**:
      - `operation`: `startDispute`
      - `contactId`: `0a1b2c3d-1111-2222-3333-444455556666`
      - `transactionId`: `TXN-4821-20261011-8999`
      - `disputeType`: `unauthorised`

   ✅ `"ok": false` and `"reason": "customer_not_identified"`. That's correct for a test (no real
   verified customer), and proves it reached the service. ❌ `401`: redo step 4.5.

The same two samples, for reference only (nothing more to do):

| Request sample | `{"operation":"startDispute","contactId":"0a1b2c3d-1111-2222-3333-444455556666","transactionId":"TXN-4821-20261011-8999","disputeType":"unauthorised"}` |
|---|---|
| Response sample | `{"ok":true,"reason":"","message":"","disputeId":"DSP-ABCD2345","status":"draft","payment":"AMAZON.CO.UK, £89.99 on 2026-10-11, debit card ending 4821","disputeType":"unauthorised","caseType":"Fraud","whatHappensNext":"Our fraud team will investigate this payment. Fraud cases are usually looked into within 15 working days, and we'll keep you updated. A colleague will now check the details with you.","reasonCode":"","reasonsAllowed":"card_lost_or_stolen, card_details_used_without_card, not_recognised","cardInPossession":"","cardBlocked":"","contactedMerchant":"","narrative":"","missing":"Reason, Customer still has the card, In the customer's words","complete":false,"customerWatching":false,"linkSent":false}` |

#### `updateDispute`

Data request 3 of 7. This one saves the customer's answers on the dispute.

1. Left menu → **Resources** → **Data requests** → **New data request**.
2. **Name**: `updateDispute`
3. **Description**: copy and paste this (the assistant reads it, so don't change it):
   ```text
   Saves the customer's answers. Send only fields you have. reasonCode: one of reasonsAllowed. cardInPossession, cardBlocked, contactedMerchant: yes or no. narrative: their own words.
   ```
4. Open the **Implementation** tab and choose **External** (not Static).
   1. **Method**: `POST`.
   2. **Production** endpoint URL: the **Data request address** from the deploy script.
   3. **Development** endpoint URL: the same address.
   4. **Headers** → add a header: key `Content-Type`, value `application/json`.
   5. Add a second header: key `x-api-key`. Click in its value box, type `{`, choose **Secrets**,
      then `card_dispute_api_key`. It becomes a chip.
5. **Request model** → **Auto-generate** (star icon) → paste this, then confirm:
   ```json
   {"operation":"updateDispute","contactId":"0a1b2c3d-1111-2222-3333-444455556666","disputeId":"DSP-ABCD2345","disputeType":"unauthorised","reasonCode":"card_details_used_without_card","cardInPossession":"yes","cardBlocked":"yes","contactedMerchant":"no","narrative":"I have never ordered from Amazon."}
   ```
6. **Response model** → **Auto-generate** → paste this, then confirm:
   ```json
   {"ok":true,"reason":"","message":"","disputeId":"DSP-ABCD2345","status":"draft","payment":"AMAZON.CO.UK, £89.99 on 2026-10-11, debit card ending 4821","disputeType":"unauthorised","caseType":"Fraud","whatHappensNext":"Our fraud team will investigate this payment. Fraud cases are usually looked into within 15 working days, and we'll keep you updated. A colleague will now check the details with you.","reasonCode":"","reasonsAllowed":"card_lost_or_stolen, card_details_used_without_card, not_recognised","cardInPossession":"","cardBlocked":"","contactedMerchant":"","narrative":"","missing":"Reason, Customer still has the card, In the customer's words","complete":false,"customerWatching":false,"linkSent":false}
   ```
7. **Save**.
8. **Test**: **Test** tab → environment **Development** → enter these values → **Run**:
      - `operation`: `updateDispute`
      - `contactId`: `0a1b2c3d-1111-2222-3333-444455556666`
      - `disputeId`: `DSP-ABCD2345`
      - `disputeType`: `unauthorised`
      - `reasonCode`: `card_details_used_without_card`
      - `cardInPossession`: `yes`
      - `cardBlocked`: `yes`
      - `contactedMerchant`: `no`
      - `narrative`: `I have never ordered from Amazon.`

   ✅ `"ok": false` and `"reason": "customer_not_identified"`. That's correct for a test (no real
   verified customer), and proves it reached the service. ❌ `401`: redo step 4.5.

The same two samples, for reference only (nothing more to do):

| Request sample | `{"operation":"updateDispute","contactId":"0a1b2c3d-1111-2222-3333-444455556666","disputeId":"DSP-ABCD2345","disputeType":"unauthorised","reasonCode":"card_details_used_without_card","cardInPossession":"yes","cardBlocked":"yes","contactedMerchant":"no","narrative":"I have never ordered from Amazon."}` |
|---|---|
| Response sample | `{"ok":true,"reason":"","message":"","disputeId":"DSP-ABCD2345","status":"draft","payment":"AMAZON.CO.UK, £89.99 on 2026-10-11, debit card ending 4821","disputeType":"unauthorised","caseType":"Fraud","whatHappensNext":"Our fraud team will investigate this payment. Fraud cases are usually looked into within 15 working days, and we'll keep you updated. A colleague will now check the details with you.","reasonCode":"","reasonsAllowed":"card_lost_or_stolen, card_details_used_without_card, not_recognised","cardInPossession":"","cardBlocked":"","contactedMerchant":"","narrative":"","missing":"Reason, Customer still has the card, In the customer's words","complete":false,"customerWatching":false,"linkSent":false}` |

#### `getDispute`

Data request 4 of 7. This one reads the dispute back, including anything the customer typed on the form.

1. Left menu → **Resources** → **Data requests** → **New data request**.
2. **Name**: `getDispute`
3. **Description**: copy and paste this (the assistant reads it, so don't change it):
   ```text
   The dispute as it stands, including anything the customer typed on the form themselves. Leave disputeId empty for the customer's latest open dispute.
   ```
4. Open the **Implementation** tab and choose **External** (not Static).
   1. **Method**: `POST`.
   2. **Production** endpoint URL: the **Data request address** from the deploy script.
   3. **Development** endpoint URL: the same address.
   4. **Headers** → add a header: key `Content-Type`, value `application/json`.
   5. Add a second header: key `x-api-key`. Click in its value box, type `{`, choose **Secrets**,
      then `card_dispute_api_key`. It becomes a chip.
5. **Request model** → **Auto-generate** (star icon) → paste this, then confirm:
   ```json
   {"operation":"getDispute","contactId":"0a1b2c3d-1111-2222-3333-444455556666","disputeId":"DSP-ABCD2345"}
   ```
6. **Response model** → **Auto-generate** → paste this, then confirm:
   ```json
   {"ok":true,"reason":"","message":"","disputeId":"DSP-ABCD2345","status":"draft","payment":"AMAZON.CO.UK, £89.99 on 2026-10-11, debit card ending 4821","disputeType":"unauthorised","caseType":"Fraud","whatHappensNext":"Our fraud team will investigate this payment. Fraud cases are usually looked into within 15 working days, and we'll keep you updated. A colleague will now check the details with you.","reasonCode":"","reasonsAllowed":"card_lost_or_stolen, card_details_used_without_card, not_recognised","cardInPossession":"","cardBlocked":"","contactedMerchant":"","narrative":"","missing":"Reason, Customer still has the card, In the customer's words","complete":false,"customerWatching":false,"linkSent":false}
   ```
7. **Save**.
8. **Test**: **Test** tab → environment **Development** → enter these values → **Run**:
      - `operation`: `getDispute`
      - `contactId`: `0a1b2c3d-1111-2222-3333-444455556666`
      - `disputeId`: `DSP-ABCD2345`

   ✅ `"ok": false` and `"reason": "customer_not_identified"`. That's correct for a test (no real
   verified customer), and proves it reached the service. ❌ `401`: redo step 4.5.

The same two samples, for reference only (nothing more to do):

| Request sample | `{"operation":"getDispute","contactId":"0a1b2c3d-1111-2222-3333-444455556666","disputeId":"DSP-ABCD2345"}` |
|---|---|
| Response sample | `{"ok":true,"reason":"","message":"","disputeId":"DSP-ABCD2345","status":"draft","payment":"AMAZON.CO.UK, £89.99 on 2026-10-11, debit card ending 4821","disputeType":"unauthorised","caseType":"Fraud","whatHappensNext":"Our fraud team will investigate this payment. Fraud cases are usually looked into within 15 working days, and we'll keep you updated. A colleague will now check the details with you.","reasonCode":"","reasonsAllowed":"card_lost_or_stolen, card_details_used_without_card, not_recognised","cardInPossession":"","cardBlocked":"","contactedMerchant":"","narrative":"","missing":"Reason, Customer still has the card, In the customer's words","complete":false,"customerWatching":false,"linkSent":false}` |

#### `blockCard`

Data request 5 of 7. This one blocks a card and, if the customer wants, orders its replacement in the same call.

1. Left menu → **Resources** → **Data requests** → **New data request**.
2. **Name**: `blockCard`
3. **Description**: copy and paste this (the assistant reads it, so don't change it):
   ```text
   Blocks the customer's debit or credit card at once. orderReplacement yes also orders a new card. Only after the customer agrees. Then say the confirmation from the reply, word for word.
   ```
4. Open the **Implementation** tab and choose **External** (not Static).
   1. **Method**: `POST`.
   2. **Production** endpoint URL: the **Data request address** from the deploy script.
   3. **Development** endpoint URL: the same address.
   4. **Headers** → add a header: key `Content-Type`, value `application/json`.
   5. Add a second header: key `x-api-key`. Click in its value box, type `{`, choose **Secrets**,
      then `card_dispute_api_key`. It becomes a chip.
5. **Request model** → **Auto-generate** (star icon) → paste this, then confirm:
   ```json
   {"operation":"blockCard","contactId":"0a1b2c3d-1111-2222-3333-444455556666","cardType":"debit","orderReplacement":"yes"}
   ```
6. **Response model** → **Auto-generate** → paste this, then confirm:
   ```json
   {"ok":true,"reason":"","message":"","cardType":"debit","cardLastFour":"4821","reference":"BLOCK-4821-ABC234","replacementOrdered":true,"replacementReference":"REPL-4821-XYZ789","arrivesInWorkingDays":"3 to 5","confirmation":"Your debit card ending 4821 is now blocked, so it can't be used again. Your reference is BLOCK-4821-ABC234. A replacement debit card is on its way and should arrive in 3 to 5 working days. Its reference is REPL-4821-XYZ789."}
   ```
7. **Save**.
8. **Test**: **Test** tab → environment **Development** → enter these values → **Run**:
      - `operation`: `blockCard`
      - `contactId`: `0a1b2c3d-1111-2222-3333-444455556666`
      - `cardType`: `debit`
      - `orderReplacement`: `yes`

   ✅ `"ok": false` and `"reason": "customer_not_identified"`. That's correct for a test (no real
   verified customer), and proves it reached the service. ❌ `401`: redo step 4.5.

The same two samples, for reference only (nothing more to do):

| Request sample | `{"operation":"blockCard","contactId":"0a1b2c3d-1111-2222-3333-444455556666","cardType":"debit","orderReplacement":"yes"}` |
|---|---|
| Response sample | `{"ok":true,"reason":"","message":"","cardType":"debit","cardLastFour":"4821","reference":"BLOCK-4821-ABC234","replacementOrdered":true,"replacementReference":"REPL-4821-XYZ789","arrivesInWorkingDays":"3 to 5","confirmation":"Your debit card ending 4821 is now blocked, so it can't be used again. Your reference is BLOCK-4821-ABC234. A replacement debit card is on its way and should arrive in 3 to 5 working days. Its reference is REPL-4821-XYZ789."}` |

#### `orderReplacementCard`

Data request 6 of 7. This one orders a replacement for a blocked card.

1. Left menu → **Resources** → **Data requests** → **New data request**.
2. **Name**: `orderReplacementCard`
3. **Description**: copy and paste this (the assistant reads it, so don't change it):
   ```text
   Orders a replacement for a card already blocked (cardType), when blockCard did not. Only after the customer agrees. Then say the confirmation from the reply, word for word.
   ```
4. Open the **Implementation** tab and choose **External** (not Static).
   1. **Method**: `POST`.
   2. **Production** endpoint URL: the **Data request address** from the deploy script.
   3. **Development** endpoint URL: the same address.
   4. **Headers** → add a header: key `Content-Type`, value `application/json`.
   5. Add a second header: key `x-api-key`. Click in its value box, type `{`, choose **Secrets**,
      then `card_dispute_api_key`. It becomes a chip.
5. **Request model** → **Auto-generate** (star icon) → paste this, then confirm:
   ```json
   {"operation":"orderReplacementCard","contactId":"0a1b2c3d-1111-2222-3333-444455556666","cardType":"debit"}
   ```
6. **Response model** → **Auto-generate** → paste this, then confirm:
   ```json
   {"ok":true,"reason":"","message":"","cardType":"debit","cardLastFour":"4821","reference":"REPL-4821-ABC234","arrivesInWorkingDays":"3 to 5","confirmation":"A replacement debit card is on its way and should arrive in 3 to 5 working days. Its reference is REPL-4821-ABC234."}
   ```
7. **Save**.
8. **Test**: **Test** tab → environment **Development** → enter these values → **Run**:
      - `operation`: `orderReplacementCard`
      - `contactId`: `0a1b2c3d-1111-2222-3333-444455556666`
      - `cardType`: `debit`

   ✅ `"ok": false` and `"reason": "customer_not_identified"`. That's correct for a test (no real
   verified customer), and proves it reached the service. ❌ `401`: redo step 4.5.

The same two samples, for reference only (nothing more to do):

| Request sample | `{"operation":"orderReplacementCard","contactId":"0a1b2c3d-1111-2222-3333-444455556666","cardType":"debit"}` |
|---|---|
| Response sample | `{"ok":true,"reason":"","message":"","cardType":"debit","cardLastFour":"4821","reference":"REPL-4821-ABC234","arrivesInWorkingDays":"3 to 5","confirmation":"A replacement debit card is on its way and should arrive in 3 to 5 working days. Its reference is REPL-4821-ABC234."}` |

#### `sendFormLink`

Data request 7 of 7. This one texts the form (phone) or gives a link to post (chat).

1. Left menu → **Resources** → **Data requests** → **New data request**.
2. **Name**: `sendFormLink`
3. **Description**: copy and paste this (the assistant reads it, so don't change it):
   ```text
   Shares the dispute form, joined to this conversation, when the customer wants it. Phone: it is texted; say only sentTo. Chat: post the link from the reply exactly as given.
   ```
4. Open the **Implementation** tab and choose **External** (not Static).
   1. **Method**: `POST`.
   2. **Production** endpoint URL: the **Data request address** from the deploy script.
   3. **Development** endpoint URL: the same address.
   4. **Headers** → add a header: key `Content-Type`, value `application/json`.
   5. Add a second header: key `x-api-key`. Click in its value box, type `{`, choose **Secrets**,
      then `card_dispute_api_key`. It becomes a chip.
5. **Request model** → **Auto-generate** (star icon) → paste this, then confirm:
   ```json
   {"operation":"sendFormLink","contactId":"0a1b2c3d-1111-2222-3333-444455556666","disputeId":"DSP-ABCD2345"}
   ```
6. **Response model** → **Auto-generate** → paste this, then confirm:
   ```json
   {"ok":true,"reason":"","message":"","sent":true,"sentTo":"the mobile ending 123","link":""}
   ```
7. **Save**.
8. **Test**: **Test** tab → environment **Development** → enter these values → **Run**:
      - `operation`: `sendFormLink`
      - `contactId`: `0a1b2c3d-1111-2222-3333-444455556666`
      - `disputeId`: `DSP-ABCD2345`

   ✅ `"ok": false` and `"reason": "customer_not_identified"`. That's correct for a test (no real
   verified customer), and proves it reached the service. ❌ `401`: redo step 4.5.

The same two samples, for reference only (nothing more to do):

| Request sample | `{"operation":"sendFormLink","contactId":"0a1b2c3d-1111-2222-3333-444455556666","disputeId":"DSP-ABCD2345"}` |
|---|---|
| Response sample | `{"ok":true,"reason":"","message":"","sent":true,"sentTo":"the mobile ending 123","link":""}` |

✅ **Check before Part 3:** the Data requests list shows all seven new names, and each tested as above.

---

## Part 3 — Build the flows

### How flows and the canvas work (read this once)

A **flow** is drawn on a **canvas**, a big empty page you can scroll and zoom.

- A **node** is a box that does one thing: say a message, ask the AI to write something, let the
  assistant talk, hand over. Every flow starts with a **Start** node that's already there.
- A **path** is a line from one node to the next. Most nodes have several exits, shown as small
  dots or labels on their edge: for example **Success**, **Failure** and **Timeout**. Each exit
  needs a line to wherever that outcome should go.
- An **output variable** is a name you give a node's result, so later nodes can use it as a chip.

**The moves you need:**

| To | Do |
|---|---|
| Add a node | Click **Add** on the toolbar, or right-click empty canvas → **New node**, then choose the node type |
| Connect two nodes | Press and hold on an exit dot of the first node, drag to the second node, let go. A line appears |
| Change a node | Click it. Its settings open in a panel on the right. Close the panel when done |
| Remove a line | Click the line and press Delete (or use its menu) |
| Move around | Drag empty canvas to scroll; use the zoom buttons or your trackpad to zoom |
| Find problems | Click **Validation** on the toolbar. It lists anything not connected |

**Node types used here:**

| Node | What it does |
|---|---|
| **Generative text** | Asks the AI to write some text from a prompt you give it, and stores it in an output variable. The customer doesn't see it |
| **Basic** | Says (or, on chat, writes) a message to the customer |
| **Live Sync** | The assistant itself: talks with the customer, uses tools, and can see the form on the customer's screen |
| **Escalate** | Ends the assistant's part and hands the customer back to Connect |
| **Redirect** | Jumps to another flow |

You build two flows. **Build `HandBackToARIA` first**, because the main flow jumps to it, and a
Redirect can only choose a flow that exists.

### 3a. Flow `HandBackToARIA`

**What it does.** It runs at the very end. It asks the AI for a one-line note for the adviser and a
reason, then hands the customer back to Connect. The finished flow looks like this:

```
Start → Generative text "handoffNote" → Generative text "handoffReason" → Escalate
```

1. **Create the flow.** Left menu → **Resources** → **Flows** → **New flow**. **Name**:
   `HandBackToARIA` (flow names can't contain spaces). Click **Create flow**. The canvas opens with
   a **Start** node.
2. **The note for the adviser.**
   1. Add a **Generative text** node. Place it to the right of **Start**.
   2. Drag a line from **Start**'s exit to it.
   3. Click it to open its settings.
   4. **Output variable**: `handoffNote`.
   5. **Prompt**: copy this text and paste it in:
      "In one sentence for a bank adviser, say anything they should know that is not on the dispute form: how the customer is feeling, anything they asked for that was not done, anything else they want help with. Write 'Nothing further.' if there is nothing. No card numbers. Conversation: {System.transcript}"
   6. At the end of the prompt, delete the pasted `{System.transcript}`. In its place type `{`,
      choose **System**, then **transcript**. A chip appears. This chip gives the AI the whole
      conversation so far.
3. **The reason.**
   1. Add a second **Generative text** node to the right of the first.
   2. From the **first** node, drag **three** lines to it: from **Success**, from **Failure** and
      from **Timeout**. That way the hand-over carries on even if the AI fails to answer.
   3. Click it. **Output variable**: `handoffReason`.
   4. **Prompt**: paste, then replace `{System.transcript}` with the chip as before:
      "Why is this going to a person? Output exactly one of: dispute_ready_for_review, dispute_incomplete, customer_request, vulnerability, tool_failure, other. No markdown, no explanation. Conversation: {System.transcript}"
4. **The hand-back.**
   1. Add an **Escalate** node to the right.
   2. From the second Generative text node, drag lines from **Success**, **Failure** and **Timeout**
      to it.
   3. Click it. **Message** (what the customer hears or reads):
      "That's everything I need. A colleague will now check the form with you before it's
      submitted. You won't need to repeat anything."
   4. Click **Add functionality** → **State modifications**. This is how values reach Connect.
      Add two rows with **Set**:

      | Context variable | Value |
      |------------------|-------|
      | `summary` | `{handoffNote}` |
      | `escalationReason` | `{handoffReason}` |

      For each row, choose the context variable from the list. For the value, type `{` and choose
      the output variable (`handoffNote` or `handoffReason`) so it becomes a chip.
   5. The Escalate node has an exit called **Continuation**. **Leave it unconnected.**
5. Click **Save**.

You don't choose the adviser's team or write the dispute summary here. Connect builds both from
what the assistant saved, so they're always right.

✅ **Check:** four nodes in a row, every exit connected except the Escalate node's **Continuation**.
**Validation** may mention that Continuation; that's expected.

### 3b. Flow `CardDispute` (the main flow)

**What it does.** It's the whole conversation. It has two parts: an **opening** that asks the first
question, and the **assistant** that does the dispute. When the assistant finishes, it jumps to
`HandBackToARIA`. The finished flow looks like this:

```
Start → Generative text "openingQuestion" ─ Success ─────────► Basic "{openingQuestion}" ─┐
                                          └ Failure / Timeout ► Basic (fixed question) ───┤
                                                                                           ▼
                                        Live Sync node "CardDisputeAssistant" ─ exits ─► Redirect → HandBackToARIA
```

1. **Create the flow.** Left menu → **Resources** → **Flows** → **New flow**. **Name**:
   `CardDispute`. Click **Create flow**.

**The opening.** The assistant node only ever *replies*; it never speaks first. Coming from ARIA,
the customer has just heard (or read) one short sentence and is waiting. So the flow must speak
first and end with a question, or the conversation goes silent. Your mortgage build found this the
hard way. The opening writes a question that fits what the customer already told ARIA, and has a
fixed question as a back-up.

2. **Write the first question.**
   1. Add a **Generative text** node and drag a line from **Start** to it.
   2. Click it. **Output variable**: `openingQuestion`.
   3. **Prompt**: paste this, then delete the pasted `{handoverSummary}` and insert the chip (type
      `{`, choose the context variable `handoverSummary`):
      "The customer wants to dispute a card payment. They already told our assistant: {handoverSummary}. Write one short, warm question, in plain UK English, that moves the dispute on without asking for anything they already said. If they clearly named the payment, ask them to confirm it in a few words, naming it. If they said someone else is using the card or it is lost, ask if they would like it blocked straight away. Otherwise offer to show them their most recent card payments, or payments from a particular time if they remember roughly when it was, and ask which they would like. Never ask them for the shop name or the amount. Do not greet them, do not say who you are, and do not mention transferring. Output only the question."
3. **Say that question.**
   1. Add a **Basic** node. Drag a line from the Generative text node's **Success** to it.
   2. Click it. **Message**: type `{` and choose `openingQuestion`. The message is just that chip.
4. **The back-up question.**
   1. Add another **Basic** node. Drag lines from the Generative text node's **Failure** and
      **Timeout** to it.
   2. Click it. **Message**: "I can show you your most recent card payments, or payments from a
      particular time if you remember roughly when it was. Which would you like?"

**The assistant.**

5. **Add the assistant node.**
   1. Add a **Live Sync** node.
   2. Name it `CardDisputeAssistant`.
   3. Drag a line from **each** Basic node to it (two lines in total).

   Live Sync means the assistant can also see the dispute form if the customer opens the link, and
   see anything they type. When no form is open, it's an ordinary phone or chat conversation.
6. **Prompt** (the assistant's instructions). Click the node and find its **Prompt** box. Copy the
   whole block below (everything between the two lines of three backticks, but not the backticks)
   and paste it in. Then find these three, delete each, and insert it as a chip with `{`:
   `{channel}`, `{firstName}`, `{handoverSummary}`.

```
You are the card dispute assistant for the bank. The customer was just talking to our assistant,
ARIA, and has been passed to you without being told: to them it is the same conversation. Never
introduce yourself, never greet them again, and never ask for anything they already said. You
handle the whole dispute. A colleague then checks it with the customer and submits it.

Conversation details (empty when not known):
channel: {channel} | first name: {firstName}
already said to ARIA: {handoverSummary}

Channel
- channel VOICE is a phone call: you are speaking. Keep turns short and never spell things out.
- channel CHAT is a chat: you are writing. Keep messages short; you may use a short list.

Before anything else
- If any tool replies with reason customer_not_identified or contact_not_recognised, you cannot
  act for this customer: do nothing on their cards or disputes, say a colleague will help, and use
  Escalation requested.
- Never give a full card number; "your debit card ending 4821" is fine.

Follow these steps in this order. Ask one question per turn. Protecting the card comes before the
dispute form. Never skip step 3 or step 5.

Step 1. Which card
- Call listCardsAndPayments with page 1, to see their cards.
- If they have more than one card and have not said which, your next message must be this question,
  naming each card, before you show any payments: "Is it your debit card ending 4821 or your credit
  card ending 2291?" Never show payments from more than one card unless they say they aren't sure.
- If they have only one card, don't ask; use it.

Step 2. Find the payment by showing it, not by asking for it
- Customers rarely remember the exact shop or amount. Never ask them for the shop name or amount.
- Call listCardsAndPayments with that card's cardType (debit or credit) and page 1. If they gave a
  rough time ("last week", "early October", "since the 1st"), also give fromDate and toDate as
  YYYY-MM-DD, worked out from today in the last reply.
- Show every payment in the reply, in the order given (newest first), with its number:
  - On CHAT: one per line, exactly "number. label", for example
    "1. 11 Oct 2026, AMAZON.CO.UK, £89.99, debit card ending 4821".
  - On VOICE: read them briefly, for example "Number 1: Amazon, eighty-nine pounds ninety-nine,
    on the 11th of October."
  Then ask which one they want to dispute. If hasMore is true, add that they can say "more" to see
  older payments, or give a date.
- If they say "more" or "older", call it again with page plus one, the same cardType and dates. If
  they give a period, call it with those dates and page 1.
- When they choose, by number, shop, amount or date, note that payment's transactionId (its number
  also works). If their answer fits more than one, ask one question to tell them apart.
- If they cannot find it in any page or period, say you can't see it and use Escalation requested.

Step 3. Decide what kind of case it is: fraud, scam or dispute
- Ask "Did you make or agree to this payment yourself?", unless they have already said.
- Then decide, from what they say:
  - FRAUD (disputeType unauthorised): they did not make or agree to it, don't recognise it, or the
    card or its details were lost or stolen.
  - SCAM (disputeType scam): they made or agreed to it, but were tricked: a fake website or seller,
    someone pretending to be a company, the police or the bank, an investment or romance scam, or
    being pressured to pay.
  - DISPUTE (disputeType merchant): they made it knowingly, and the problem is with what they paid
    for: not received, faulty or not as described, charged twice or the wrong amount, charged after
    cancelling, or a refund not received.
- If they made it but you can't tell whether they were tricked, ask one question: "Were you tricked
  into paying, for example by a fake website or someone pretending to be a company or the bank, or
  did something go wrong with what you bought?"
- Tell them in one short sentence how you are treating it, for example "This sounds like fraud, so
  I'll treat it as a fraud case.", "This sounds like a scam, so I'll treat it as a scam case." or
  "I'll raise this as a dispute with the retailer."
- For FRAUD or SCAM, protect the card now, before anything else:
  - If listCardsAndPayments shows the card's status as blocked already, say so, and offer only the
    replacement (orderReplacementCard).
  - Otherwise ask one question: "Would you like me to block your <debit/credit> card ending <last
    four> now, so it can't be used again, and send you a replacement?"
  - With their yes, call blockCard with that cardType and orderReplacement yes. If they want it
    blocked but no new card, use orderReplacement no.
  - When blockCard replies ok true, tell them its confirmation, word for word: it says the card is
    blocked, when the new card will arrive, and both references. Never say a card is blocked or
    ordered unless blockCard or orderReplacementCard replied ok true in this conversation.
  - If it replies ok false, tell them it hasn't been done and a colleague will do it, and carry on.
  - With their no, remember it: in step 4, save cardBlocked no.
- For a DISPUTE, don't block or replace the card: it wasn't misused. Only do it if they ask.

Step 4. Start the dispute, and save what you already know
- Call startDispute with the transactionId and the disputeType you decided in step 3 (unauthorised,
  scam or merchant). The case is marked Fraud, Scam or Dispute from that. If you blocked the card in
  step 3, the dispute already says so.
- Straight away, call updateDispute with everything they have told ARIA and you: for example
  reasonCode not_recognised for a payment they don't recognise, fake_seller_or_website for a fake
  shop, cardInPossession yes if they still have the card, cardBlocked no if they said not to block
  it, and narrative in their own words. Don't ask for these first.

Step 5. Offer the form (always, straight after step 4)
- Ask: "Would you like to see the dispute form, so you can watch it being filled in as we go?"
- With their yes, call sendFormLink.
  - On VOICE: say it has been texted to sentTo. Never read out a link or a number.
  - On CHAT: post the link from the reply exactly as given, on its own line, with one short line
    saying it opens their dispute form.
  - If ok is false, say you can't share it right now, and carry on.
- With their no, carry on.
- Once it is open, they see your changes within a couple of seconds and can type in it too. Call
  getDispute to see what they typed. Saving with updateDispute is enough; you never fill in the page
  yourself.

Step 6. Fill in the rest
- Ask only for what the last reply's missing field lists, one question at a time, and save each
  answer with updateDispute as soon as you have it. Keep going until complete is true.
- For the reason, choose from reasonsAllowed using their words; never show or say the codes. Write
  narrative in their own words; do not improve it.
- Never say you have saved something unless updateDispute replied ok=true.

Step 7. Finish
- When complete is true, sum up in one or two sentences: the type of case (fraud, scam or dispute),
  the payment, what happened, the card you blocked and the replacement (with references), and
  whether they have the form. Ask if it is right. Correct anything with updateDispute.
- When they agree, tell them whatHappensNext from your last dispute reply, word for word. It gives
  the timescale for their kind of case.
- Then use Escalation requested. A colleague checks it with them and submits it.

When you may use Escalation requested
- Only when one of these is true: complete is true and they agreed your summary; they ask for a
  person; they are vulnerable; the payment cannot be found; they are not verified; or the same
  tool has failed twice.
- Never use it to pass on something you have a tool for, such as blocking a card or saving an
  answer. Do it yourself.

What you never do
- Never submit, confirm or accept a dispute, and never say it has been submitted or accepted.
- Never state a timescale or an outcome, or promise a refund, except by saying whatHappensNext word
  for word. If they ask anything more, say: "My colleague will explain what happens next."
- Never block or replace a card without the customer's yes.
- Never give a full card number or phone number, and never read out a link on a phone call.
- Never say you are transferring or connecting them unless you use Escalation requested in the
  same turn. Asking for a person is always Escalation requested.
- If they ask about something other than this dispute, say your colleague can help with that too,
  and carry on; it goes in the hand-over.

Vulnerability
- If the customer is distressed, confused, or mentions bereavement, illness or money worries,
  acknowledge it kindly and use Escalation requested.

Tone
- Warm, plain English, UK spelling. Two short sentences per turn at most, except when you show
  payments.
```

7. **Tools.** Still in the `CardDisputeAssistant` node, find its **Tools** section. You add seven
   tools here, one for each Data request from Part 2c. The tool prompt is the same text as that Data
   request's description. Each tool below has every step written out. Already added them? Open
   each one and compare: the tool prompt and the inputs must match its section below.

   **The rule for inputs, the same in every tool:**
   - `operation` → **Explicit text**, typed exactly as shown.
   - `contactId` → **Variable** → the context variable `contactId`. ⚠️ Never Explicit text with a
     `{contactId}` chip inside it: the designer then sends the chip's placeholder instead of the
     real ID, and every tool answers `customer_not_identified`. The mortgage build hit exactly this.
   - Everything else → **LLM prompt**: the assistant fills it in from the conversation.

   **Tool 1 of 7: `listCardsAndPayments`** (looks up the customer's cards and one page of their recent payments)

   1. In the **Tools** section, click **Add tool** (or **+**). Choose type **Data request**.
   2. Pick **`listCardsAndPayments`** from the list.
   3. **Tool prompt** (some screens say **Description** or **Instructions**): paste
      ```text
      Customer's cards and one page of 5 card payments, newest first, numbered. page 1 is newest; 2, 3 are older. Optional fromDate/toDate (YYYY-MM-DD) and cardType. Show the list to the customer.
      ```
   4. The tool lists its **inputs**, one for each field below. For each input, open its source
      drop-down and choose as shown:

      | Input | Source | Value |
      |-------|--------|-------|
      | `operation` | **Explicit text** | type exactly: `listCardsAndPayments` |
      | `contactId` | **Variable** | pick the context variable `contactId` from the list |
      | `page` | **LLM prompt** | if there's a description box: Which page of five payments: 1 for the newest, then 2, 3 and so on when the customer asks for older ones. |
      | `fromDate` | **LLM prompt** | if there's a description box: Start of the period the customer gave, as YYYY-MM-DD, worked out from today in the last reply. Empty if they gave none. |
      | `toDate` | **LLM prompt** | if there's a description box: End of the period the customer gave, as YYYY-MM-DD. Empty if they gave none. |
      | `cardType` | **LLM prompt** | if there's a description box: debit or credit: which card. Leave empty for both. |

   5. **Save** the tool (or close its panel), and check `listCardsAndPayments` now appears in the Tools list.

   **Tool 2 of 7: `startDispute`** (starts the dispute for the payment the customer chose)

   1. In the **Tools** section, click **Add tool** (or **+**). Choose type **Data request**.
   2. Pick **`startDispute`** from the list.
   3. **Tool prompt** (some screens say **Description** or **Instructions**): paste
      ```text
      Starts the case for the chosen payment (transactionId or its number). disputeType: unauthorised (fraud: not made), scam (made, but tricked) or merchant (made, but went wrong).
      ```
   4. The tool lists its **inputs**, one for each field below. For each input, open its source
      drop-down and choose as shown:

      | Input | Source | Value |
      |-------|--------|-------|
      | `operation` | **Explicit text** | type exactly: `startDispute` |
      | `contactId` | **Variable** | pick the context variable `contactId` from the list |
      | `transactionId` | **LLM prompt** | if there's a description box: The transactionId of the payment the customer chose, from listCardsAndPayments. Its number (for example 3) also works. |
      | `disputeType` | **LLM prompt** | if there's a description box: unauthorised if the customer did not make or does not recognise the payment (fraud); scam if they made it but were tricked; merchant if they made it but something went wrong. |

   5. **Save** the tool (or close its panel), and check `startDispute` now appears in the Tools list.

   **Tool 3 of 7: `updateDispute`** (saves the customer's answers on the dispute)

   1. In the **Tools** section, click **Add tool** (or **+**). Choose type **Data request**.
   2. Pick **`updateDispute`** from the list.
   3. **Tool prompt** (some screens say **Description** or **Instructions**): paste
      ```text
      Saves the customer's answers. Send only fields you have. reasonCode: one of reasonsAllowed. cardInPossession, cardBlocked, contactedMerchant: yes or no. narrative: their own words.
      ```
   4. The tool lists its **inputs**, one for each field below. For each input, open its source
      drop-down and choose as shown:

      | Input | Source | Value |
      |-------|--------|-------|
      | `operation` | **Explicit text** | type exactly: `updateDispute` |
      | `contactId` | **Variable** | pick the context variable `contactId` from the list |
      | `disputeId` | **LLM prompt** | if there's a description box: The disputeId from startDispute. |
      | `disputeType` | **LLM prompt** | if there's a description box: unauthorised if the customer did not make or does not recognise the payment (fraud); scam if they made it but were tricked; merchant if they made it but something went wrong. |
      | `reasonCode` | **LLM prompt** | if there's a description box: One of reasonsAllowed from the last dispute reply, matching what the customer said. |
      | `cardInPossession` | **LLM prompt** | if there's a description box: yes or no: does the customer still have the card? |
      | `cardBlocked` | **LLM prompt** | if there's a description box: yes or no: is the card blocked? |
      | `contactedMerchant` | **LLM prompt** | if there's a description box: yes or no: has the customer contacted the retailer? |
      | `narrative` | **LLM prompt** | if there's a description box: What happened, in the customer's own words. |

   5. **Save** the tool (or close its panel), and check `updateDispute` now appears in the Tools list.

   **Tool 4 of 7: `getDispute`** (reads the dispute back, including anything the customer typed on the form)

   1. In the **Tools** section, click **Add tool** (or **+**). Choose type **Data request**.
   2. Pick **`getDispute`** from the list.
   3. **Tool prompt** (some screens say **Description** or **Instructions**): paste
      ```text
      The dispute as it stands, including anything the customer typed on the form themselves. Leave disputeId empty for the customer's latest open dispute.
      ```
   4. The tool lists its **inputs**, one for each field below. For each input, open its source
      drop-down and choose as shown:

      | Input | Source | Value |
      |-------|--------|-------|
      | `operation` | **Explicit text** | type exactly: `getDispute` |
      | `contactId` | **Variable** | pick the context variable `contactId` from the list |
      | `disputeId` | **LLM prompt** | if there's a description box: The disputeId from startDispute. |

   5. **Save** the tool (or close its panel), and check `getDispute` now appears in the Tools list.

   **Tool 5 of 7: `blockCard`** (blocks a card and, if the customer wants, orders its replacement in the same call)

   1. In the **Tools** section, click **Add tool** (or **+**). Choose type **Data request**.
   2. Pick **`blockCard`** from the list.
   3. **Tool prompt** (some screens say **Description** or **Instructions**): paste
      ```text
      Blocks the customer's debit or credit card at once. orderReplacement yes also orders a new card. Only after the customer agrees. Then say the confirmation from the reply, word for word.
      ```
   4. The tool lists its **inputs**, one for each field below. For each input, open its source
      drop-down and choose as shown:

      | Input | Source | Value |
      |-------|--------|-------|
      | `operation` | **Explicit text** | type exactly: `blockCard` |
      | `contactId` | **Variable** | pick the context variable `contactId` from the list |
      | `cardType` | **LLM prompt** | if there's a description box: debit or credit: which card. Leave empty for both. |
      | `orderReplacement` | **LLM prompt** | if there's a description box: yes if the customer also wants a new card sent, no if not. |

   5. **Save** the tool (or close its panel), and check `blockCard` now appears in the Tools list.

   **Tool 6 of 7: `orderReplacementCard`** (orders a replacement for a blocked card)

   1. In the **Tools** section, click **Add tool** (or **+**). Choose type **Data request**.
   2. Pick **`orderReplacementCard`** from the list.
   3. **Tool prompt** (some screens say **Description** or **Instructions**): paste
      ```text
      Orders a replacement for a card already blocked (cardType), when blockCard did not. Only after the customer agrees. Then say the confirmation from the reply, word for word.
      ```
   4. The tool lists its **inputs**, one for each field below. For each input, open its source
      drop-down and choose as shown:

      | Input | Source | Value |
      |-------|--------|-------|
      | `operation` | **Explicit text** | type exactly: `orderReplacementCard` |
      | `contactId` | **Variable** | pick the context variable `contactId` from the list |
      | `cardType` | **LLM prompt** | if there's a description box: debit or credit: which card. Leave empty for both. |

   5. **Save** the tool (or close its panel), and check `orderReplacementCard` now appears in the Tools list.

   **Tool 7 of 7: `sendFormLink`** (texts the form (phone) or gives a link to post (chat))

   1. In the **Tools** section, click **Add tool** (or **+**). Choose type **Data request**.
   2. Pick **`sendFormLink`** from the list.
   3. **Tool prompt** (some screens say **Description** or **Instructions**): paste
      ```text
      Shares the dispute form, joined to this conversation, when the customer wants it. Phone: it is texted; say only sentTo. Chat: post the link from the reply exactly as given.
      ```
   4. The tool lists its **inputs**, one for each field below. For each input, open its source
      drop-down and choose as shown:

      | Input | Source | Value |
      |-------|--------|-------|
      | `operation` | **Explicit text** | type exactly: `sendFormLink` |
      | `contactId` | **Variable** | pick the context variable `contactId` from the list |
      | `disputeId` | **LLM prompt** | if there's a description box: The disputeId from startDispute. |

   5. **Save** the tool (or close its panel), and check `sendFormLink` now appears in the Tools list.

   ✅ The Tools list shows all seven: `listCardsAndPayments`, `startDispute`, `updateDispute`, `getDispute`, `blockCard`, `orderReplacementCard`, `sendFormLink`.

8. **Data capture.** If the node has a **Data capture** section, remove it (or leave it empty). The
   tools save the dispute; data capture slots would stay empty and make the node fail.
9. **Live Sync actions.** Find the node's **Live Sync actions** box. In VS Code, open
   `acxd/live-sync-actions.json`, copy all of it (`{"actions": []}`), and paste it in. It's empty on
   purpose: nothing on the page can confirm or submit.
10. **Exit conditions.** These are the ways the assistant can finish. In the node, find **Exit
    conditions** and add two. Paste the descriptions exactly; the assistant reads them to decide
    when to leave.

    | Name | Description for the agent |
    |------|---------------------------|
    | `Escalation requested` | Use only when the dispute is complete and the customer agreed the summary, the customer asks for a person, the customer is vulnerable, the payment cannot be found, the customer is not verified, or a tool failed twice. Never to pass on something you can do with a tool. |
    | `Unable to help` | A Data request failed twice. |

    Each exit you add appears as a new exit dot on the node, next to its built-in **Timeout** and
    **Failure** exits. Don't add a "Task complete" exit: this assistant never finishes a dispute;
    an adviser does.

11. **Send every way out to the hand-back.**
    1. Add a **Redirect** node to the right of the assistant. Click it and choose the flow
       **`HandBackToARIA`**.
    2. Drag four lines from `CardDisputeAssistant` to the Redirect: from **Escalation requested**,
       **Unable to help**, **Timeout** and **Failure**.
12. **Save**, then click **Validation** on the toolbar. It lists anything not connected. Fix each
    one by drawing the missing line. The only thing it may still mention is the Escalate node's
    Continuation in `HandBackToARIA`, which is fine.

✅ **Check:** the flow matches the picture at the top of 3b. The assistant node has a prompt, seven
tools, no data capture, two exit conditions, and four lines to the Redirect.

---

## Part 4 — Create, build and deploy the application

**What this is.** The flows exist, but nothing can use them until they're in an **application**
that's been built and deployed. Make a **new** application for this assistant. Don't add these flows
to the Mortgage application: an application has one starting flow, and the mortgage one starts the
mortgage conversation.

1. **Create it.** Left menu → **Applications** → **New application**. **Name**: `Card dispute`.
   **Create**.
2. **Design tab: attach the flows and set the defaults.**
   1. Attach the two flows `CardDispute` and `HandBackToARIA` (not the mortgage flows). **Save**.
      A Redirect only works if its target flow is attached.
   2. Click the **Default behavior** icon under the **Flows** list (or the three-dot menu next to a
      flow). Set all four, then **Save**:

      | Default | Flow | When it's used |
      |---------|------|----------------|
      | **Welcome** | `CardDispute` | a conversation starts |
      | **Unknown** | `CardDispute` | the assistant didn't understand; it asks again |
      | **Fallback** | `HandBackToARIA` | something keeps going wrong; send to a person |
      | **Escalation** | `HandBackToARIA` | the customer needs a person |

      If Unknown or Fallback is left empty, the build warns about "Default quick replies" and the
      assistant uses generic built-in replies. Set both.
3. **Voice.** Open the application's settings and find its voice. Choose **Amy, English (UK)**,
   the voice ARIA uses, so a caller hears one voice throughout. Connect's own Set voice block
   doesn't change this assistant's voice; only this setting does. If Amy isn't offered, choose the
   closest British voice, write its name down, and set ARIA's Set voice block to the same one
   (README step 10). On chat, the voice doesn't matter.
4. **Deploy tab: build and deploy.**
   1. Choose the **Development** environment → **Build & deploy**.
   2. Read the checks it shows. **Red** items must be fixed (it says which flow or node). **Yellow**
      items are warnings; read them, but you can go on.
   3. **Description**: `v1 card dispute`. Click **Build**. Wait; it takes a few minutes.
   4. When it finishes, hover over the build's status and choose **Deploy**. Wait until it shows
      **Live**.
5. **Test tab: quick check.** The Test tab has no real call, so the assistant can't act for a real
   customer. What you can check is that every piece is wired up.
   1. **New conversation test**. The opening question should appear by itself, asking about the
      payment.
   2. Reply "I want to dispute a payment". The assistant calls `listCardsAndPayments`, gets told it
      can't act for this customer, and ends with "That's everything I need. A colleague will…",
      then **Application exited via Escalation**. **That's the expected result here.**
   3. **Check that `contactId` is mapped correctly** (the most common mistake). AWS console →
      **CloudWatch** → **Log groups** → `/aws/lambda/aria-card-dispute` → the newest log stream.
      Find the line with `route=/acxd/ops` from your test:
      - `outcome=listCardsAndPayments:contact_not_recognised:empty`: correct. The test simply has
        no contact ID. On a real call it will have one.
      - `…:contact_not_recognised:placeholder`: **wrong**. `contactId` is set as Explicit text with
        a chip inside. Go back to step 7 of Part 3b and set it to **Variable** in all seven tools.
      - `status=401`: the Secret isn't being sent. See Part 2c.
   4. The real test, with a verified customer, is in the README, "Test it".
6. **Production.** Repeat step 4, choosing **Production** instead of Development.
7. **Write down four things.** You need them in the README, steps 7 and 8:
   - the **application ID**: in the application's settings, or in the browser's address bar;
   - the **alias code** of the **Production** environment: a random-looking string such as
     `MyX46JWMLhtmdRWZgXTDe`. Not the word `Production`: Connect rejects that ("NLX Streaming Request
     Failed With Status: 400");
   - the build's **deployment key**: click the deployed build;
   - the application's **API key**: application settings → **Access**.

✅ **Check:** the application `Card dispute` shows **Live** in Production, and you have the four
values written down.

---

## If something goes wrong here

| What you see | What it means | Fix |
|---|---|---|
| A Data request test gives `401` | The key isn't being sent | Part 2c step 4: the `x-api-key` value must be the Secret chip |
| A test returns exactly the sample | The Data request is Static | Part 2c step 4: choose External |
| A flow can't find `HandBackToARIA` in the Redirect | That flow wasn't saved, or isn't attached to the application | Save it (3a step 5); attach it (Part 4 step 2) |
| The build shows red items | Something is unconnected or missing | Click the item; it opens the node. Usually a missing line |
| In a real call, the assistant says nothing after ARIA | The opening isn't connected to the assistant | 3b steps 2 to 5 |
| In a real call, every tool says `customer_not_identified` | `contactId` isn't set as a Variable, or ARIA hadn't verified the customer | 3b step 7 |
| Prompt text shows `{channel}` as typed words, not a chip | The braces were typed | Delete it and insert with `{` |
