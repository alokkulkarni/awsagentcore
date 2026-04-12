# ARIA — Proactive Intent Prediction & Conversation History Guide

**System:** Meridian Bank · ARIA AI Agent · Amazon Connect  
**Purpose:** Surface conversation history and predict likely contact reasons before the AI agent greets the customer, and present those predictions as selectable options in chat or spoken options in voice.

---

## Overview

When a customer contacts Meridian Bank, ARIA currently greets them with no context about their history or why they are likely calling. This guide describes how to:

1. **Capture and retrieve** the last 4 conversation summaries (voice or chat, PII-redacted) from Contact Lens and replay them as context into the current session.
2. **Detect recent failed journeys** across channels (app, mobile, web) — failed payments, login errors, broken transfers — and use them as signals to predict the most likely reason for the call or chat.
3. **Surface predicted reasons** as a **selectable list** in the chat widget (interactive List Picker) and as **spoken options** in voice (S2S), so the customer can confirm or redirect rather than re-explain their issue.

---

## Architecture Overview

```
Customer starts contact (voice or chat)
         │
         ▼
  ┌─────────────────────┐
  │  Contact Flow       │
  │  (existing)         │
  └──────────┬──────────┘
             │
             ▼
  ┌─────────────────────┐
  │  session_injector   │  ← sets customerId in session attributes
  │  Lambda (existing)  │
  └──────────┬──────────┘
             │  customerId available
             ▼
  ┌─────────────────────────────────────────────┐
  │  aria_intent_enrichment Lambda  (NEW)        │
  │                                             │
  │  1. Query DynamoDB: last 4 contact summaries│
  │  2. Query DynamoDB: recent failed journeys  │
  │  3. Run intent prediction logic             │
  │  4. Set contact attributes                  │
  │  5. CHAT ONLY: Send List Picker via         │
  │     Connect Participant API                 │
  └──────────┬──────────────────────────────────┘
             │
             ▼
  ┌─────────────────────┐        ┌──────────────────────────┐
  │  Voice path         │        │  Chat path               │
  │  Lex → ARIA         │        │  List Picker sent to     │
  │  ARIA greets with   │        │  customer → selection    │
  │  predicted reasons  │        │  → Lex → ARIA            │
  └─────────────────────┘        └──────────────────────────┘
```

**AWS services used:**

| Service | Role |
|---|---|
| Contact Lens | Generates post-contact summaries after each call/chat |
| EventBridge | Captures Contact Lens completion events → triggers summary persistence |
| DynamoDB | Stores contact summaries + cross-channel failed journey events |
| Lambda (`aria_intent_enrichment`) | Queries history, predicts intent, sends interactive message |
| Connect Participant Service | Sends List Picker interactive message into chat at contact start |
| Amazon Bedrock (optional) | Classifies raw event list into human-readable predicted reasons |
| Amazon Connect Contact Flow | Orchestrates the Lambda invocations |

---

## Part A — Capturing Conversation Summaries (Contact Lens Pipeline)

### A.1 — Enable Contact Lens on your Connect instance

**Connect console → Data storage → Contact Lens → Enable**

Contact Lens automatically analyses every voice call and chat transcript once the contact ends. It produces:
- Full transcript (speaker-labelled, time-stamped)
- Sentiment scores per turn
- Issue detection (keyword phrases from transcript)
- **Post-contact summary** — a 2–4 sentence AI-generated summary of the conversation

### A.2 — Subscribe to Contact Lens completion events via EventBridge

Contact Lens publishes an EventBridge event when post-contact analysis completes:

**Event source:** `aws.connect`  
**Detail-type:** `Contact Lens Analysis State Change`  
**Detail.Status:** `SUCCEEDED`

Create an EventBridge rule in your Connect region to capture these:

```json
{
  "source": ["aws.connect"],
  "detail-type": ["Contact Lens Analysis State Change"],
  "detail": {
    "status": ["SUCCEEDED"],
    "instanceId": ["YOUR_CONNECT_INSTANCE_ID"]
  }
}
```

Target: `aria_contact_summary_persister` Lambda (described below).

### A.3 — aria_contact_summary_persister Lambda

This Lambda fires after every completed contact. It:

1. Receives the EventBridge event containing `contactId`, `instanceId`, `channel`
2. Calls the **Contact Lens API** to retrieve the post-contact summary
3. Calls `connect.GetContactAttributes` to retrieve `customerId` from the contact
4. Stores a PII-redacted summary record in DynamoDB

**Contact Lens API call to get the summary:**

```python
import boto3

contact_lens = boto3.client('connect-contact-lens', region_name='eu-west-2')

response = contact_lens.list_realtime_contact_analysis_segments(
    InstanceId=instance_id,
    ContactId=contact_id,
    MaxResults=100
)

# Post-contact summary is in the Segments list
for segment in response['Segments']:
    if 'PostContactSummary' in segment:
        summary_text = segment['PostContactSummary']['Content']
        break
```

> **Note:** `ListRealtimeContactAnalysisSegments` returns the `PostContactSummary` segment for both voice (retained 24 h) and chat. For permanent storage, always persist the summary to DynamoDB immediately.

**DynamoDB schema — `aria_contact_summaries` table:**

| Field | Type | Notes |
|---|---|---|
| `customerId` (PK) | String | Partition key — customer identifier |
| `contactId` (SK) | String | Sort key — unique per contact |
| `timestamp` | Number | Unix epoch — used for ordering |
| `channel` | String | `VOICE` or `CHAT` |
| `summary` | String | PII-redacted summary text |
| `issuesDetected` | List | Issue keywords from Contact Lens |
| `categories` | List | Contact Lens categories matched (if configured) |
| `ttl` | Number | Auto-expire after 90 days (DynamoDB TTL) |

**PII redaction before storage:**  
Before writing the summary to DynamoDB, call ARIA's existing `pii_detect_and_redact` MCP tool (or use Amazon Comprehend's `DetectPiiEntities`) to mask any account numbers, phone numbers, or names that appeared in the summary text.

**Full Lambda skeleton:**

```python
import boto3
import json
import time

connect = boto3.client('connect', region_name='eu-west-2')
contact_lens = boto3.client('connect-contact-lens', region_name='eu-west-2')
dynamodb = boto3.resource('dynamodb', region_name='eu-west-2')
table = dynamodb.Table('aria_contact_summaries')

def lambda_handler(event, context):
    detail = event['detail']
    contact_id = detail['contactId']
    instance_id = detail['instanceId']

    # 1. Get customerId from contact attributes
    attrs = connect.get_contact_attributes(
        InstanceId=instance_id,
        InitialContactId=contact_id
    )['Attributes']
    customer_id = attrs.get('customerId')
    if not customer_id:
        return  # no customer ID — anonymous contact, skip

    # 2. Get post-contact summary from Contact Lens
    summary_text = None
    issues = []
    categories = []
    try:
        resp = contact_lens.list_realtime_contact_analysis_segments(
            InstanceId=instance_id,
            ContactId=contact_id,
            MaxResults=100
        )
        for segment in resp.get('Segments', []):
            if 'PostContactSummary' in segment:
                pcs = segment['PostContactSummary']
                if pcs.get('Status') == 'COMPLETED':
                    summary_text = pcs.get('Content', '')
            if 'Transcript' in segment:
                for issue in segment['Transcript'].get('IssuesDetected', []):
                    # CharacterOffsets only — extract text separately if needed
                    issues.append(issue)
            if 'Categories' in segment:
                categories.extend(segment['Categories'].get('MatchedCategories', []))
    except Exception as e:
        print(f"Contact Lens API error: {e}")
        return

    if not summary_text:
        return

    # 3. (Optional) Redact PII from summary text here via Comprehend or ARIA PII tool

    # 4. Persist to DynamoDB
    now = int(time.time())
    table.put_item(Item={
        'customerId': customer_id,
        'contactId': contact_id,
        'timestamp': now,
        'channel': detail.get('channel', 'UNKNOWN'),
        'summary': summary_text,
        'issuesDetected': issues,
        'categories': categories,
        'ttl': now + (90 * 86400)  # 90-day TTL
    })
```

---

## Part B — Cross-Channel Failed Journey Detection

### B.1 — What is a failed journey?

A failed journey is any user action in a digital channel that did not complete successfully:

| Channel | Event examples |
|---|---|
| Mobile app | Payment failed, login failed, biometric auth failed, beneficiary add failed |
| Web banking | Transfer failed, document upload failed, card activation failed |
| Self-service IVR | PIN change failed, balance inquiry timed out |
| Open Banking API | Third-party connection failed, consent declined |

These events are strong signals that the customer may be calling about that specific issue.

### B.2 — Publishing failed journey events

Your mobile app and web banking platform should publish events to **Amazon EventBridge** (custom event bus) whenever a user journey fails. If you use a direct API, route through **API Gateway → Lambda → EventBridge**.

**Example event payload:**

```json
{
  "source": "meridian.digital.app",
  "detail-type": "Customer Journey Failed",
  "detail": {
    "customerId": "CUST-001234",
    "channel": "MOBILE_APP",
    "journeyType": "PAYMENT",
    "errorCode": "INSUFFICIENT_FUNDS",
    "productType": "CURRENT_ACCOUNT",
    "accountRef": "****1234",
    "timestamp": "2026-04-10T10:22:00Z"
  }
}
```

### B.3 — Persisting failed journey events to DynamoDB

Create an EventBridge rule targeting an `aria_journey_event_persister` Lambda:

**DynamoDB schema — `aria_failed_journeys` table:**

| Field | Type | Notes |
|---|---|---|
| `customerId` (PK) | String | Partition key |
| `eventId` (SK) | String | UUID |
| `timestamp` | Number | Unix epoch (use as GSI for date range queries) |
| `channel` | String | `MOBILE_APP`, `WEB`, `IVR`, `API` |
| `journeyType` | String | `PAYMENT`, `LOGIN`, `TRANSFER`, `CARD_ACTIVATION`, etc. |
| `errorCode` | String | Raw error code |
| `productType` | String | Product involved |
| `accountRef` | String | Last 4 digits only — never full account number |
| `ttl` | Number | Auto-expire after 30 days |

### B.4 — Intent prediction rules

The `aria_intent_enrichment` Lambda applies rules to the list of recent failed journeys and conversation history to produce ranked predicted reasons. Start with a rules-based approach — it is predictable and auditable.

**Rule table (ordered by confidence):**

| Failed journey type | Predicted reason label |
|---|---|
| `PAYMENT` + error in last 24 h | "Chase a payment that may have failed" |
| `LOGIN` 3+ times in 24 h | "Trouble logging into online/mobile banking" |
| `TRANSFER` failed | "Query a transfer that didn't go through" |
| `CARD_ACTIVATION` failed | "Activate a new card" |
| `DIRECT_DEBIT` failed | "Direct debit query" |
| `DOCUMENT_UPLOAD` failed | "Help uploading a document" |
| Last summary contains "mortgage" keyword | "Mortgage payment or balance query" |
| Last summary contains "blocked" or "frozen" | "Dispute a blocked transaction" |

**Bedrock-enhanced classification (optional):**  
If the failed event list is complex or ambiguous, pass it to Bedrock Claude with a short prompt:

```python
prompt = f"""
You are a banking contact centre assistant.
A customer with ID {customer_id} recently experienced these events: {json.dumps(events)}.
Their last contact summary was: "{last_summary}".
List the top 3 most likely reasons they are contacting us today.
Reply as a JSON array of short reason strings (max 6 words each).
Example: ["Failed payment query", "Card not working", "Balance check"]
"""
```

This produces natural-language labels for the list picker.

---

## Part C — aria_intent_enrichment Lambda

This Lambda is invoked in the contact flow **after** `session_injector` (which has already set `customerId` in contact attributes). It runs for both voice and chat contacts.

### C.1 — What it does

1. Reads `customerId` from contact attributes (set by session_injector)
2. Queries `aria_contact_summaries` DynamoDB — last 4 contacts, sorted by timestamp descending
3. Queries `aria_failed_journeys` DynamoDB — last 14 days of events
4. Applies intent prediction rules → produces ranked list of up to 3 reasons
5. Sets contact attributes in Connect for ARIA to consume
6. **Chat only:** calls Connect Participant Service `SendMessage` to send a List Picker interactive message before Lex receives control

### C.2 — Contact attributes set

| Attribute | Value | Example |
|---|---|---|
| `history_summary_1` | Most recent contact summary (PII-redacted) | "Customer called about a failed payment from 05 Apr. Issue was resolved." |
| `history_summary_2` | Second most recent summary | "Customer asked about mortgage balance." |
| `history_summary_3` | Third most recent summary | "Customer queried a direct debit." |
| `history_summary_4` | Fourth most recent summary | "Customer asked about card blocking." |
| `predicted_reason_1` | Top predicted reason (short label) | "Failed payment query" |
| `predicted_reason_2` | Second predicted reason | "Trouble logging into app" |
| `predicted_reason_3` | Third predicted reason | "Check account balance" |
| `predicted_product` | Product associated with top reason | "CURRENT_ACCOUNT" |
| `has_recent_failure` | Boolean string | "true" / "false" |

### C.3 — Lambda skeleton

```python
import boto3
import json
import time
from boto3.dynamodb.conditions import Key

connect = boto3.client('connect', region_name='eu-west-2')
connect_participant = boto3.client('connectparticipant', region_name='eu-west-2')
dynamodb = boto3.resource('dynamodb', region_name='eu-west-2')
summaries_table = dynamodb.Table('aria_contact_summaries')
journeys_table = dynamodb.Table('aria_failed_journeys')

INSTANCE_ID = 'YOUR_CONNECT_INSTANCE_ID'


def lambda_handler(event, context):
    contact_id = event['Details']['ContactData']['ContactId']
    attributes = event['Details']['ContactData']['Attributes']
    customer_id = attributes.get('customerId')
    channel = event['Details']['ContactData']['Channel']  # VOICE or CHAT

    if not customer_id:
        return _no_data_response()

    # 1. Last 4 conversation summaries
    summaries = _get_last_n_summaries(customer_id, 4)

    # 2. Recent failed journeys
    journeys = _get_recent_failed_journeys(customer_id, days=14)

    # 3. Predict intent
    predicted_reasons = _predict_intent(summaries, journeys)

    # 4. Build contact attribute updates
    result = {}
    for i, summary in enumerate(summaries[:4], 1):
        result[f'history_summary_{i}'] = summary.get('summary', '')[:500]  # 500 char limit

    for i, reason in enumerate(predicted_reasons[:3], 1):
        result[f'predicted_reason_{i}'] = reason

    result['has_recent_failure'] = 'true' if journeys else 'false'
    result['predicted_product'] = _extract_product(journeys)

    # 5. For chat: send List Picker interactive message
    if channel == 'CHAT':
        participant_token = attributes.get('participantToken')
        if participant_token and predicted_reasons:
            _send_list_picker(participant_token, predicted_reasons)

    return result


def _get_last_n_summaries(customer_id, n):
    resp = summaries_table.query(
        KeyConditionExpression=Key('customerId').eq(customer_id),
        ScanIndexForward=False,  # newest first
        Limit=n
    )
    return resp.get('Items', [])


def _get_recent_failed_journeys(customer_id, days=14):
    cutoff = int(time.time()) - (days * 86400)
    resp = journeys_table.query(
        KeyConditionExpression=Key('customerId').eq(customer_id),
        FilterExpression='#ts >= :cutoff',
        ExpressionAttributeNames={'#ts': 'timestamp'},
        ExpressionAttributeValues={':cutoff': cutoff},
        ScanIndexForward=False,
        Limit=20
    )
    return resp.get('Items', [])


def _predict_intent(summaries, journeys):
    reasons = []
    journey_types = [j.get('journeyType', '') for j in journeys]
    summary_text = ' '.join([s.get('summary', '') for s in summaries]).lower()

    if 'PAYMENT' in journey_types:
        reasons.append('Query a payment that may have failed')
    if journey_types.count('LOGIN') >= 2:
        reasons.append('Trouble logging into online or mobile banking')
    if 'TRANSFER' in journey_types:
        reasons.append('Query a transfer that did not complete')
    if 'CARD_ACTIVATION' in journey_types:
        reasons.append('Help activating a new card')
    if 'DIRECT_DEBIT' in journey_types:
        reasons.append('Direct debit query')
    if 'mortgage' in summary_text:
        reasons.append('Mortgage payment or balance query')
    if 'blocked' in summary_text or 'frozen' in summary_text:
        reasons.append('Dispute a blocked transaction')

    # Always include a catch-all
    if 'Check my account balance' not in reasons:
        reasons.append('Check my account balance or recent transactions')

    return reasons[:3]  # top 3 only


def _extract_product(journeys):
    if journeys:
        return journeys[0].get('productType', 'UNKNOWN')
    return 'UNKNOWN'


def _send_list_picker(participant_token, reasons):
    """Send a List Picker interactive message to the chat participant."""
    # Get connection token
    conn = connect_participant.create_participant_connection(
        Type=['CONNECTION_CREDENTIALS'],
        ParticipantToken=participant_token
    )
    connection_token = conn['ConnectionCredentials']['ConnectionToken']

    elements = [{'title': r} for r in reasons[:6]]  # max 6 elements in list picker

    message = {
        'templateType': 'ListPicker',
        'version': '1.0',
        'data': {
            'replyMessage': {
                'title': 'Got it — I\'ll look into that for you now.'
            },
            'content': {
                'title': 'I can see you\'ve been in touch before. Is one of these the reason for your chat today?',
                'subtitle': 'Tap to select, or type your own reason below',
                'elements': elements
            }
        }
    }

    connect_participant.send_message(
        ContentType='application/vnd.amazonaws.connect.message.interactive',
        Content=json.dumps(message),
        ConnectionToken=connection_token
    )


def _no_data_response():
    return {
        'has_recent_failure': 'false',
        'predicted_reason_1': '',
        'predicted_reason_2': '',
        'predicted_reason_3': ''
    }
```

> **`participantToken` requirement for chat:** The participant token is only available if you store it as a contact attribute when the chat starts. Alternatively, use `GetContactAttributes` inside the Lambda to retrieve the token if your chat initiation flow sets it.

---

## Part D — Chat Widget: Selectable List Picker

### D.1 — How it works

When the `aria_intent_enrichment` Lambda sends the List Picker message via the Connect Participant API, the chat widget renders it as a set of tappable buttons **before** the AI agent sends its greeting.

```
┌─────────────────────────────────────────────────────┐
│  ARIA — Meridian Bank                               │
├─────────────────────────────────────────────────────┤
│                                                     │
│  I can see you've been in touch before. Is one      │
│  of these the reason for your chat today?           │
│                                                     │
│  ┌─────────────────────────────────────────────┐   │
│  │  Query a payment that may have failed        │   │
│  └─────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────┐   │
│  │  Trouble logging into online banking         │   │
│  └─────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────┐   │
│  │  Check my account balance                    │   │
│  └─────────────────────────────────────────────┘   │
│                                                     │
│  Tap to select, or type your own reason below      │
│                                                     │
└─────────────────────────────────────────────────────┘
│  Type a message...                          [Send]  │
└─────────────────────────────────────────────────────┘
```

### D.2 — What happens when the customer taps

When the customer taps a List Picker option, the widget sends the `title` text as a plain-text chat message to the conversation. ARIA receives this as the customer's first message and uses it as intent confirmation — the conversation begins with the customer's reason already established.

**Example flow:**
1. List Picker shows: "Query a payment that may have failed"
2. Customer taps it → message sent: `"Query a payment that may have failed"`
3. ARIA receives: `"Query a payment that may have failed"` as customer message
4. ARIA (with conversation history in context) responds:
   > *"I can see you had a payment issue recently. Let me look into your account for you..."*
   Then calls `get_account_balance` or `get_recent_transactions`.

### D.3 — Interactive message content types

Amazon Connect Participant API `SendMessage` uses these content types:

| Content type | Use case |
|---|---|
| `text/plain` | Plain text message |
| `application/vnd.amazonaws.connect.message.interactive` | List Picker, Time Picker, Quick Reply, Panel, Carousel |
| `application/vnd.amazonaws.connect.message.interactive.response` | Customer's selection response |

### D.4 — Quick Reply alternative (simpler)

If you want simpler button-only chips (no list styling), use the **Quick Reply** template instead. It renders as horizontal tap chips at the bottom of the chat:

```json
{
  "templateType": "QuickReply",
  "version": "1.0",
  "data": {
    "replyMessage": { "title": "Got it." },
    "content": {
      "title": "What are you getting in touch about today?",
      "elements": [
        { "title": "Failed payment" },
        { "title": "Login trouble" },
        { "title": "Account balance" }
      ]
    }
  }
}
```

Use Quick Replies when you have 2–4 short options. Use List Picker when you want descriptions or up to 10 options.

---

## Part E — Voice (S2S): Spoken Predicted Reasons

### E.1 — Mechanism

Voice does not have a visual list component. Instead, ARIA uses the conversation history and predicted reasons (injected as session attributes by `aria_intent_enrichment`) to open the call proactively and present the options verbally.

This is achieved entirely through the **ARIA system prompt** — no additional Lambda or Connect flow changes are needed for voice.

### E.2 — ARIA system prompt addition (voice greeting with predicted reasons)

Add the following to ARIA's system prompt inside the `<instructions>` block:

```yaml
<proactive_greeting>
At the start of every conversation, before asking what you can help with, check the 
following session attributes which will be available to you:

  - history_summary_1 through history_summary_4: PII-redacted summaries of the 
    customer's last 4 contacts (most recent first). These may be empty for new customers.
  - predicted_reason_1 through predicted_reason_3: ranked predicted reasons for this 
    contact based on recent channel activity.
  - has_recent_failure: "true" or "false". If "true", the customer recently experienced 
    a failure in a digital channel.

VOICE greeting protocol:
  1. Greet the customer warmly by first name if available.
  2. If has_recent_failure is "true", acknowledge it:
     "I can see you recently had a [predicted_reason_1] — is that why you're calling 
      today?"
     Wait for yes/no. If yes, proceed directly to resolve. If no, ask what you can help 
     with.
  3. If has_recent_failure is "false" but predicted reasons exist, offer them more 
     softly:
     "Based on your recent activity, you might be calling about [predicted_reason_1] 
      or [predicted_reason_2]. Is either of those right, or something else?"
  4. If no history or predictions exist, greet normally:
     "How can I help you today?"

CHAT greeting protocol:
  The customer has already been shown a selectable list of predicted reasons and may 
  have tapped one. If their first message matches a predicted reason, acknowledge it 
  directly and proceed. If they typed their own reason, handle it normally.

HISTORY usage:
  Use history_summary_1 through history_summary_4 as background context throughout 
  the conversation. Do NOT read these summaries aloud verbatim. Reference them only 
  if relevant — e.g. "I can see last time you called about X — is this related?"

IMPORTANT: Never fabricate reasons or history. Only reference what is in the session 
attributes. If attributes are empty, greet normally.
</proactive_greeting>
```

### E.3 — Example voice exchange

**Scenario:** Customer calls after a failed mobile payment yesterday.

> **ARIA:** *"Good afternoon, and welcome to Meridian Bank. I'm ARIA, your digital banking assistant. I can see you had an issue with a payment recently — is that why you're calling today?"*
>
> **Customer:** *"Yes, exactly — it said it failed but the money left my account."*
>
> **ARIA:** *"I'm sorry to hear that. Let me pull up your recent transactions right away."*  
> *(calls `get_recent_transactions` — no dead air needed, purpose established)*

---

## Part F — Contact Flow Changes

### F.1 — Updated flow (both voice and chat)

Add one new **Invoke AWS Lambda function** block after the existing `session_injector` invoke block:

```
[Set logging behaviour]
        ↓
[session_injector Lambda]        ← sets customerId, authStatus
        ↓
[aria_intent_enrichment Lambda]  ← NEW: sets history, predictions; sends List Picker for chat
        ↓
[Check Contact Attributes]       ← existing auth routing logic
        ↓
[Set contact attributes]         ← pass predictions to Lex session attributes
        ↓
[Get customer input — Lex]       ← ARIA AI agent
```

### F.2 — Pass predictions as Lex session attributes

In the **Set contact attributes** block (before the Lex block), add entries to pass predictions into the Lex session so ARIA can read them:

| Destination key | Source |
|---|---|
| `history_summary_1` | Contact attribute `history_summary_1` |
| `history_summary_2` | Contact attribute `history_summary_2` |
| `history_summary_3` | Contact attribute `history_summary_3` |
| `history_summary_4` | Contact attribute `history_summary_4` |
| `predicted_reason_1` | Contact attribute `predicted_reason_1` |
| `predicted_reason_2` | Contact attribute `predicted_reason_2` |
| `predicted_reason_3` | Contact attribute `predicted_reason_3` |
| `has_recent_failure` | Contact attribute `has_recent_failure` |

In the **Get customer input** (Lex block) → set **Session attributes type** to `Use existing contact attributes`. This passes all contact attributes through to the Lex session, which are then visible to ARIA.

---

## Part G — Data Flow for DynamoDB Queries

### G.1 — DynamoDB table design for efficient queries

**`aria_contact_summaries`**

```
Partition key:  customerId   (String)
Sort key:       timestamp    (Number)  ← allows range query + sort

GSI (optional): contactId-index  ← for lookup by contactId if needed
```

Query pattern: `customerId = :cid ORDER BY timestamp DESC LIMIT 4`

**`aria_failed_journeys`**

```
Partition key:  customerId   (String)
Sort key:       timestamp    (Number)

GSI (optional): journeyType-timestamp-index  ← for analytics
```

Query pattern: `customerId = :cid AND timestamp >= :cutoff ORDER BY timestamp DESC`

### G.2 — Lambda permissions required

Add to the `aria_intent_enrichment` Lambda execution role:

```json
{
  "Effect": "Allow",
  "Action": [
    "dynamodb:Query",
    "dynamodb:GetItem"
  ],
  "Resource": [
    "arn:aws:dynamodb:eu-west-2:ACCOUNT:table/aria_contact_summaries",
    "arn:aws:dynamodb:eu-west-2:ACCOUNT:table/aria_failed_journeys"
  ]
},
{
  "Effect": "Allow",
  "Action": [
    "connect:GetContactAttributes",
    "connectparticipant:CreateParticipantConnection",
    "connectparticipant:SendMessage"
  ],
  "Resource": "*"
},
{
  "Effect": "Allow",
  "Action": [
    "connect:UpdateContactAttributes"
  ],
  "Resource": "arn:aws:connect:eu-west-2:ACCOUNT:instance/INSTANCE_ID/contact/*"
}
```

Add to the `aria_contact_summary_persister` Lambda execution role:

```json
{
  "Effect": "Allow",
  "Action": [
    "connect-contact-lens:ListRealtimeContactAnalysisSegments",
    "connect:GetContactAttributes"
  ],
  "Resource": "*"
},
{
  "Effect": "Allow",
  "Action": [
    "dynamodb:PutItem"
  ],
  "Resource": "arn:aws:dynamodb:eu-west-2:ACCOUNT:table/aria_contact_summaries"
}
```

---

## Part H — Cross-Channel Event Publisher (App / Mobile / Web)

### H.1 — Mobile app integration

In your React Native or iOS/Android app, publish to EventBridge via API Gateway (do **not** call EventBridge directly from the client — it would expose AWS credentials):

```
Mobile App
    ↓ HTTPS POST
API Gateway (POST /events/journey-failed)
    ↓
Lambda (aria_journey_event_receiver)
    ↓ PutEvents
EventBridge custom bus (meridian-digital-events)
    ↓
Lambda (aria_journey_event_persister)
    ↓
DynamoDB (aria_failed_journeys)
```

**API Gateway request body:**

```json
{
  "customerId": "CUST-001234",
  "channel": "MOBILE_APP",
  "journeyType": "PAYMENT",
  "errorCode": "INSUFFICIENT_FUNDS",
  "productType": "CURRENT_ACCOUNT",
  "accountRef": "1234"
}
```

Authenticate the API Gateway endpoint with **Cognito User Pool** or **API key** tied to the mobile app.

### H.2 — Web banking integration

Same pattern — call the API Gateway endpoint from your web banking front-end on any unhandled error condition. Use the customer's authenticated session to include `customerId`.

---

## Part I — Privacy and Compliance Considerations

| Concern | Mitigation |
|---|---|
| PII in summaries | Always run `pii_detect_and_redact` before storing. Never store full names, account numbers, or full phone numbers in plain text. |
| Data retention | Set DynamoDB TTL on all records. Summaries: 90 days. Failed journeys: 30 days. |
| Customer consent | Summarising call content for service improvement must be disclosed in your privacy policy and IVR/chat consent prompts. |
| Predictions accuracy | Rules-based predictions are transparent and auditable. If using Bedrock classification, log inputs/outputs to CloudWatch. |
| Right to erasure | When a customer requests data deletion, trigger a Lambda that deletes all `aria_contact_summaries` and `aria_failed_journeys` records for their `customerId`. |
| Contact Lens data | Contact Lens transcripts and summaries are stored in your Connect S3 bucket. Ensure bucket is encrypted (SSE-KMS) and access is restricted. |

---

## Part J — Testing

### J.1 — Test the summary persistence pipeline

1. Make a test voice call or chat through your Connect instance with a known `customerId`
2. End the contact — Contact Lens analysis runs (allow 2–5 minutes after contact ends)
3. Check EventBridge rule metrics in CloudWatch → confirm event was delivered to Lambda
4. Check DynamoDB `aria_contact_summaries` table → confirm record written for your `customerId`

### J.2 — Test the enrichment Lambda

Invoke `aria_intent_enrichment` directly with a test event:

```json
{
  "Details": {
    "ContactData": {
      "ContactId": "test-contact-123",
      "Channel": "CHAT",
      "Attributes": {
        "customerId": "CUST-001234",
        "participantToken": "YOUR_TEST_PARTICIPANT_TOKEN"
      }
    }
  }
}
```

Check Lambda response — confirm `history_summary_1..4` and `predicted_reason_1..3` are populated.

### J.3 — Test the chat List Picker

Start a chat via your Connect chat widget. Within 2–3 seconds of starting, the List Picker should appear before ARIA's greeting. Tap a reason and confirm ARIA's response acknowledges it directly.

### J.4 — Test voice greeting

Call your Connect voice number. After authentication, ARIA should greet with a predicted reason if `has_recent_failure = true`. Confirm the conversation takes the confirmed-intent path without asking the customer to repeat why they called.

---

## Summary of Components to Build

| Component | Type | New or Existing |
|---|---|---|
| `aria_contact_summary_persister` | Lambda | **New** |
| `aria_journey_event_persister` | Lambda | **New** |
| `aria_journey_event_receiver` | Lambda + API Gateway | **New** |
| `aria_intent_enrichment` | Lambda | **New** |
| `aria_contact_summaries` | DynamoDB table | **New** |
| `aria_failed_journeys` | DynamoDB table | **New** |
| EventBridge rule (Contact Lens completion) | EventBridge rule | **New** |
| EventBridge custom bus (digital events) | EventBridge bus | **New** |
| Contact flow — add Lambda invoke block | Connect flow update | **Update existing** |
| ARIA system prompt — proactive greeting | AI Agent system prompt | **Update existing** |
