# Card Transaction Disputes and Adviser Access to Applications — Specification

| | |
|---|---|
| Status | Built, not deployed. Part 1 (card disputes) is in this folder. Part 2 (mortgage application) is in Live Sync PR #9 and `connect-agent-assist/`; section 12 says what is and is not done |
| Date | 13 October 2026 |
| Depends on | `connect-agent-assist/` (PR #31): the agent-assist flow, its Lambda and the screen pop |
| Related repo | `connect-livesync-mortgage` (the mortgage application journey) |

## 0. Three findings that shape this design

These came from reading the Live Sync repository and the live Connect instance. They correct what
was assumed before this work started.

1. **Live Sync does not store the mortgage application.** The customer's answers live in their
   browser tab (`sessionStorage`) and nowhere else. The Live Sync table holds only short-lived
   codes and tokens, and submitting returns a reference without saving anything. There is nothing
   for an adviser or an assistant to look up until the form is saved on the server. That is a
   change to Live Sync's frozen requirements (Part 2).
2. **Live Sync cannot be driven by a human.** AWS provides it for an AI agent filling a page. Once a
   human adviser takes the contact, nothing drives the customer's page. So "the customer watches the
   adviser go through the form" cannot be done with Live Sync. It needs a record on the server that
   the adviser's screen writes and the customer's screen reads.
3. **ARIA cannot use Live Sync.** Live Sync belongs to a different kind of AI agent (built in the
   agentic CX designer). ARIA is a Connect AI agent and can only act through tools. In the mortgage
   journey ARIA fills nothing: it hands the contact to that other agent.

**Consequence.** Card disputes are built on one shared record: ARIA writes it with tools, the
adviser's page writes it, and the customer's page shows it. To the customer it looks like the
mortgage journey (the form fills in as they talk), but it works differently underneath.

---

# Part 1 — Card transaction disputes

## 1. Goal

A customer tells ARIA they want to dispute a card transaction (debit or credit). ARIA fills in as
much of the dispute as it can and hands the contact to an adviser. The adviser reviews the form,
completes it, confirms the details with the customer and submits it. The customer can watch the
form on their own screen while ARIA and then the adviser fill it in.

## 2. Out of scope

- Sending the dispute to a card scheme or a real case system. Submitting marks the record
  `submitted` and gives a reference. A real integration replaces one function.
- Uploading evidence (receipts, emails).
- Refunds, provisional credits and any movement of money.
- A customer starting or editing a dispute on the web page without a contact. The page is a view
  with one button.
- Notifications (email, SMS) about the dispute.

## 3. Two kinds of dispute

The first question decides the route, so ARIA asks it before anything else:
**"Did you make or authorise this payment yourself?"**

| | Unauthorised | Problem with a payment the customer made |
|---|---|---|
| Customer's answer | "No" or "I don't recognise it" | "Yes, but…" |
| `disputeType` | `unauthorised` | `merchant` |
| Reasons | `card_lost_or_stolen`, `card_details_used_without_card`, `not_recognised` | `goods_not_received`, `not_as_described`, `charged_twice`, `wrong_amount`, `cancelled_subscription`, `refund_not_received` |
| Extra questions | Do you still have the card? | Have you contacted the retailer? |
| ARIA also offers | To block the card now (existing block tools) | Nothing |
| Routed as | `fraud_security` → Fraud Team | The card's own topic: `debit_card` or `credit_card` → Cards Team |

The request named the fraud adviser for all disputes. A payment the customer made is not fraud, so
it goes to the Cards Team by default. `MERCHANT_DISPUTE_TOPIC=fraud_security` on the Lambda sends
everything to the Fraud Team instead.

## 4. The record

One item per dispute in the DynamoDB table `aria-card-disputes`.

| Field | Values | Set by |
|---|---|---|
| `disputeId` | `DSP-` + 8 characters | System |
| `customerId` | From the session, never from the customer's words | System |
| `status` | `draft` → `with_adviser` → `submitted` (or `withdrawn`) | System |
| `version` | Counts every change | System |
| `cardType`, `cardLastFour` | `debit` / `credit`, 4 digits | From the chosen transaction |
| `transactionId`, `transactionDate`, `merchant`, `amount`, `currency` | | From the chosen transaction |
| `disputeType` | `unauthorised` / `merchant` | ARIA or adviser |
| `reason` | One of the reasons for the type (section 3) | ARIA or adviser |
| `cardInPossession` | `yes` / `no` (unauthorised only) | ARIA or adviser |
| `cardBlocked` | `yes` / `no` | ARIA or adviser |
| `contactedMerchant` | `yes` / `no` (merchant only) | ARIA or adviser |
| `narrative` | The customer's own account, up to 600 characters | ARIA or adviser |
| `filledBy` | For each field: `aria` or `adviser` | System |
| `customerConfirmation` | `accepted`, `source` (`customer_click` or `adviser_recorded`), time | Customer page or adviser page |
| `history` | Time, who, action, field names. Never values | System |

**Complete** means: transaction, `disputeType`, `reason`, `narrative`, and `cardInPossession`
(unauthorised) or `contactedMerchant` (merchant).

**Rules the Lambda enforces, whoever asks:**

- R1. ARIA's tools can change a dispute only while it is `draft`.
- R2. ARIA's tools can never set `customerConfirmation` and can never submit.
- R3. A dispute can be submitted only when it is complete and `customerConfirmation.accepted` is true.
- R4. A dispute belongs to one customer. Every tool call must carry the same `customerId` the
  dispute was created with.
- R5. The transaction's details are copied from the bank's record of that transaction, never from
  what a caller passes in.
- R6. Changing the transaction, type or reason after the customer confirmed clears the confirmation.

## 5. Who does what

```mermaid
sequenceDiagram
    participant C as Customer
    participant A as ARIA
    participant L as aria-card-dispute Lambda
    participant P as Customer page
    participant S as Screen pop
    participant V as Adviser page
    C->>A: I want to dispute a transaction
    A->>L: list_card_transactions
    A->>C: Did you make this payment?
    A->>L: start_card_dispute, update_card_dispute
    Note over C,P: optional: customer opens the page, reads its code to ARIA
    A->>L: attach_dispute_screen(code)
    P-->>C: form appears and fills in live
    A->>C: I'll pass you to a colleague to review and submit it
    A->>A: Escalate (fraud_security or card topic)
    S->>L: dispute for this customer? (via the agent-assist Lambda)
    L-->>S: summary lines + link to the adviser page
    V->>L: adviser edits
    P-->>C: edits appear live
    C->>P: Confirm these details (or adviser records a verbal yes)
    V->>L: submit
    P-->>C: Submitted, reference DSP-…
```

### 5.1 ARIA's tools

Published on the existing MCP gateway as a new target, `aria-banking-dispute`.

| Tool | Does | Returns |
|---|---|---|
| `list_card_transactions` | Recent card transactions for the customer, optionally one card type | Transactions with a stable `transaction_id` |
| `start_card_dispute` | Creates a draft for one transaction and type. If the customer already has an open draft for that transaction, returns it | `dispute_id`, the record, `missing` |
| `update_card_dispute` | Sets any of: `dispute_type`, `reason`, `card_in_possession`, `card_blocked`, `contacted_merchant`, `narrative` | The record, `missing` |
| `get_card_dispute` | Reads a dispute by id, or the customer's latest open one | The record, `missing`, `status` |
| `attach_dispute_screen` | Shows the dispute on the customer page whose 6-digit code the customer read out | `attached` |

`get_card_dispute` is also given to the agent-assist agents. It only reads.

### 5.2 The customer page

A public web page that shows nothing until a contact attaches a dispute to it.

1. The customer opens the page. It shows a 6-digit code: "Read this code to the assistant."
2. The customer reads the code to ARIA (or types it in chat). ARIA calls `attach_dispute_screen`.
3. Within two seconds the page shows the dispute, and keeps it up to date every two seconds: each
   field, who filled it in, and a highlight when it changes.
4. When the dispute is with the adviser and complete, a button appears: **"These details are
   correct."** Pressing it records the customer's confirmation.
5. After the adviser submits, the page shows the reference.

**Why the code goes from the page to the call, not the other way.** A code read out by ARIA and
typed into a public page would show a customer's dispute to anyone who guessed or overheard a code.
Here the page holds a long secret it never shows, and the code only works when a verified caller
reads it out on their own contact. This is the pattern Live Sync uses for its help code.

The page is optional. A customer who is not near a screen gets the same service without it.

### 5.3 The adviser

- **Screen pop.** When a contact arrives and the customer has an open dispute, the screen pop shows
  a "Card dispute" section: reference, type, transaction, what is still missing, whether the
  customer is watching, and a link, **Open dispute form**.
- **Adviser page.** The link opens the dispute form. The adviser can change every field in
  section 4, see whether the customer has confirmed, tick "Customer confirmed these details to me"
  when the customer is not using the page, and press **Submit**. Submit is refused until R3 holds.
- **Assistant.** The arrival briefing and the Connect assistant panel can read the dispute with
  `get_card_dispute` and tell the adviser what is missing.

The link carries a token that is made for that contact, lasts 60 minutes, and is kept in the part
of the address that browsers do not send to servers. Opening the adviser page moves the dispute
from `draft` to `with_adviser`.

## 6. Components

| Component | Where | Notes |
|---|---|---|
| `aria-card-dispute` Lambda | `lambda/` | One function, three ways in (below) |
| DynamoDB table `aria-card-disputes` | Created by the deploy script | One table: disputes, page sessions, codes, adviser tokens. Time-to-live on the short-lived items |
| HTTP API | Created by the deploy script | Serves the two pages and their JSON calls |
| Gateway target `aria-banking-dispute` | Added by the deploy script | The five tools |
| Customer page, adviser page | `web/` | Plain HTML, CSS and JavaScript, served by the Lambda. No inline script |
| ARIA prompt block | `prompts/` + `scripts/build_aria_prompt.py` | Inserted into the live prompt by a script, so it is always based on the current version |
| Screen pop | `connect-agent-assist/flows/` | Gains a "Card dispute" view |
| Agent-assist Lambda | `connect-agent-assist/lambda/` | `get_briefing` also asks the dispute Lambda about this customer |

**Three ways into the Lambda, told apart by the shape of the request:**

| Way in | Caller | May do |
|---|---|---|
| Web | Anyone, through the HTTP API | Page files; customer calls (with the page's secret); adviser calls (with an adviser token) |
| Tool | The MCP gateway's role | The five tools |
| Internal | The agent-assist Lambda's role | `screen_pop`: summary lines and a new adviser link |

The way in is decided by how a request arrived, never by what it asks for:

- A web request can never be treated as a tool or internal call. The HTTP API always adds its own
  envelope, and the Lambda checks for it first.
- A request from the MCP gateway is always a tool call, even if its arguments ask for `screen_pop`.
  That matters because `screen_pop` hands out an adviser link, which can confirm and submit. If
  ARIA could reach it by passing an argument, rule R2 would be a suggestion, not a rule.

## 7. Security

| Risk | Control |
|---|---|
| Someone opens the customer page and sees another person's dispute | The page shows nothing until a verified contact attaches a dispute by code. Codes are 6 digits, single use, 10 minutes. Five wrong codes on one dispute lock attaching for that dispute |
| A code is overheard | A code alone opens nothing. It only tells the Lambda which waiting page a verified caller means |
| The adviser link leaks | It lasts 60 minutes, is tied to one dispute, is never sent to a server by the browser, and is stored only as a hash. The screen-pop flow has its logging switched off, because a flow's log records the view it shows |
| ARIA submits or confirms for the customer | R1 and R2 are enforced in the Lambda, not in the prompt |
| A caller disputes someone else's transaction | R4 and R5: the customer id comes from the session, and the transaction must be in that customer's own list |
| Personal data in logs | Logs carry the operation, the outcome and the dispute id only. Never the narrative, merchant, amount, codes or tokens |
| The pages run injected script | No inline script; a content security policy allowing only the page's own files; all text written with `textContent` |
| Verification level | ARIA starts a dispute only for an authenticated customer at Level 2 or above, the same bar as account information. The adviser is told the level in the screen pop, as today |

## 8. Known gaps

- **Not tested live.** Everything here is unit-tested only until the first test contact.
- **A direct call arrives at Level 3 on the phone number alone** when `CLI_MATCH_LOA=3`. A dispute
  started on such a call is drafted on a spoofable identity. The adviser's own verification before
  submitting is the control. The screen pop says so.
- **The screen-pop flow no longer logs.** A flow's log records the whole view it shows, which
  would include the adviser link and, for a mortgage application, date of birth and income. The
  cost is that a screen-pop fault can no longer be read from the flow log; the Lambda's own log
  still shows each request.
- **Any adviser with the link can open the form.** It is not tied to the adviser's login.
- **Whether the screen pop's link opens the page** depends on the Detail view accepting a link
  whose address is filled in at run time. If it does not, the address is also shown as text.
- **The transactions are test data** held in the Lambda, not the account tool's list.
- **Default table encryption.** The table uses AWS-owned keys. Use a customer-managed key in
  production.
- **Polling every two seconds.** Fine for a demo. A WebSocket would replace it at scale.

## 9. Acceptance

1. ARIA drafts an unauthorised dispute end to end; the contact reaches the Fraud Team; the screen
   pop shows the dispute and the link.
2. ARIA drafts a merchant dispute; the contact reaches the Cards Team.
3. With the customer page open and attached, a field ARIA sets appears on the page within about
   two seconds, and so does a field the adviser changes.
4. Submit is refused before the customer confirms, and accepted after either kind of confirmation.
5. ARIA's tools cannot change a dispute once the adviser has opened it, and can never submit.
6. A wrong code attaches nothing; five wrong codes lock attaching for that dispute.

---

# Part 2 — Adviser access to a mortgage application

## 10. What is wanted

A mortgage adviser can see a customer's application, in progress or submitted, and its status. When
the customer asks, the assistant can bring it forward.

## 11. What has to change, and where

| # | Change | Repo | State |
|---|---|---|---|
| M1 | Save the application on the server as the customer fills it in | Live Sync | Built: [connect-livesync-mortgage PR #9](https://github.com/alokkulkarni/connect-livesync-mortgage/pull/9). Not merged or deployed |
| M2 | Read an application by its id | Live Sync | Built in the same PR (`getApplication`, no internet route) |
| M4 | The adviser sees the form | this repo | Built: the screen pop's "Mortgage application" view lists the saved form, read-only |
| M3 | A `get_mortgage_application` tool for the assistant | this repo | Not built. The assistant cannot yet report on an application |

**M1 in detail.** A new page operation, `saveApplication`, called a moment after each change. It
stores stage, field values, uploaded document types, the Decision in Principle result, the chosen
product, and whether it was submitted. This changes two things Live Sync's design states today:
items would live for days, not minutes (decision D5), and date of birth and income would be stored
at rest (the table is already encrypted with a customer-managed key). Both need a new requirement
in `docs/REQUIREMENTS.md` before any code, under that repo's rules.

**Finding a customer's application.** The web journey gives each browser tab a random application
id and knows no customer id. An application can be found by customer only when the contact carried
one in: a call transferred by ARIA does, a customer who started on the website does not. Until the
bank's login supplies the customer id to the page, the adviser can open an application only on a
contact that carries its `applicationId`.

**Adviser changes to the customer's form are not in scope.** Finding 2: nothing can push an
adviser's edit into the customer's Live Sync page. M4 is read-only.

## 12. What was built, and what it needs

**In Live Sync (PR #9).** Requirements v1.22 add FR-38 (save), FR-39 (read) and NFR-21 (30 days,
never logged). The page saves a moment after each change. Reading is by direct Lambda invocation
only. Because the reference page has no sign-in, the first save returns a key that later saves must
present, so nobody can overwrite an application by guessing its id.

**Here.** `aria-agent-assist-injector` reads the application a contact carries (the contact
attribute `applicationId`) and returns six lines, which the screen pop's "Mortgage application" view
shows under **Application form**: status, About you, Property and loan, Decision and product,
Documents, and what is still to fill in. It shows a submitted application the same way, with its
reference.

**To switch it on:** merge and deploy Live Sync PR #9 (its backend and web scripts), then run
`connect-agent-assist/scripts/deploy_agent_assist.sh` and re-import the screen pop.

**Limits.**

- Only a contact that carries `applicationId` shows a form. A customer who rings the main number
  about an application does not carry one, and there is no find-by-customer (section 11).
- The view is read-only, and nothing the adviser does changes the customer's page (finding 2).
- The assistant panel cannot yet answer questions about the application (M3).
- "Bring it forward" is the screen pop showing it. Nothing opens the customer's page for the adviser.
