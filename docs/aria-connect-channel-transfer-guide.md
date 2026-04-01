# ARIA — Voice ↔ Chat Channel Transfer Guide

**Amazon Connect Cross-Channel Handoff with Full Transcript Continuity**

> This guide is written for novices. Every step is explained with **what** to do and **why**.
> The approach works for both ARIA (AI agent) and human agents — the architecture is identical;
> the routing destination changes depending on who handles the new contact.

---

## Table of Contents

1. [What This Guide Covers](#1-what-this-guide-covers)
2. [How It Works — Key Concepts for Novices](#2-how-it-works--key-concepts-for-novices)
3. [Architecture Overview](#3-architecture-overview)
4. [Prerequisites](#4-prerequisites)
5. [Part A — How Both AI and Human Agents Receive the Transfer](#part-a--how-both-ai-and-human-agents-receive-the-transfer)
6. [Part B — Voice → Chat Transfer (Step by Step)](#part-b--voice--chat-transfer-step-by-step)
   - [Step B.1 — Create the Voice-to-Chat Transfer Lambda](#step-b1--create-the-voice-to-chat-transfer-lambda)
   - [Step B.2 — Add the Transfer Block to the Voice Flow](#step-b2--add-the-transfer-block-to-the-voice-flow)
   - [Step B.3 — Build the Chat Deep Link (Web and Mobile)](#step-b3--build-the-chat-deep-link-web-and-mobile)
   - [Step B.4 — How ARIA Picks Up the Chat with Full Context](#step-b4--how-aria-picks-up-the-chat-with-full-context)
   - [Step B.5 — How a Human Agent Picks Up the Chat](#step-b5--how-a-human-agent-picks-up-the-chat)
   - [Step B.6 — How the Voice Transcript Appears in Chat](#step-b6--how-the-voice-transcript-appears-in-chat)
7. [Part C — Chat → Voice Transfer (Step by Step)](#part-c--chat--voice-transfer-step-by-step)
   - [Step C.1 — Create the Chat-to-Voice Transfer Lambda](#step-c1--create-the-chat-to-voice-transfer-lambda)
   - [Step C.2 — Add the Transfer Block to the Chat Flow](#step-c2--add-the-transfer-block-to-the-chat-flow)
   - [Step C.3 — How ARIA Handles the Voice Callback with Chat Context](#step-c3--how-aria-handles-the-voice-callback-with-chat-context)
   - [Step C.4 — How a Human Agent Handles the Voice Callback](#step-c4--how-a-human-agent-handles-the-voice-callback)
8. [Part D — DynamoDB for Cross-Session Transcript Storage](#part-d--dynamodb-for-cross-session-transcript-storage)
9. [Part E — Session Injector Updates for Cross-Channel Context](#part-e--session-injector-updates-for-cross-channel-context)
10. [IAM Permissions for the Transfer Lambdas](#iam-permissions-for-the-transfer-lambdas)
11. [Testing](#testing)
12. [Troubleshooting](#troubleshooting)

---

## 1. What This Guide Covers

This guide shows you how to implement **two cross-channel transfer scenarios** in Amazon Connect:

**Scenario 1 — Voice → Chat**:
1. A customer is on a voice call with ARIA (or a human agent)
2. The conversation is transferred to chat
3. The customer receives an **SMS with a chat link** (web or mobile app deep link)
4. When the customer opens the link, the **same agent or ARIA is already connected** to the chat
5. The **full voice transcript** (from Contact Lens) appears at the top of the chat so neither
   the customer nor the agent needs to repeat anything

**Scenario 2 — Chat → Voice**:
1. A customer is chatting with ARIA (or a human agent)
2. The conversation is transferred to a voice call (outbound callback)
3. The customer receives a **chat message** telling them to expect a call
4. When the voice call connects, the agent/ARIA has the **full chat transcript** as context
5. The conversation continues seamlessly on voice

> **Official docs this guide is based on**:
> - [Enable persistent chat](https://docs.aws.amazon.com/connect/latest/adminguide/chat-persistence.html)
> - [StartChatContact API](https://docs.aws.amazon.com/connect/latest/APIReference/API_StartChatContact.html)
> - [StartOutboundVoiceContact API](https://docs.aws.amazon.com/connect/latest/APIReference/API_StartOutboundVoiceContact.html)
> - [ListRealtimeContactAnalysisSegments](https://docs.aws.amazon.com/contact-lens/latest/APIReference/API_ListRealtimeContactAnalysisSegments.html)
> - [Web and mobile chat](https://docs.aws.amazon.com/connect/latest/adminguide/web-and-mobile-chat.html)
> - [Contact Lens conversational analytics APIs](https://docs.aws.amazon.com/connect/latest/adminguide/contact-lens-api.html)

---

## 2. How It Works — Key Concepts for Novices

Before you build anything, you need to understand five things. This will prevent confusion later.

### Concept 1 — Amazon Connect cannot natively transfer a voice call to a chat

A voice call and a chat session are different technical protocols. When you "transfer voice to chat",
you are not literally moving one contact into another channel. What actually happens is:

1. A **new** chat contact is created (separate from the voice contact)
2. That new chat contact is **linked** to the voice contact via `RelatedContactId`
3. The voice transcript is **copied into the new chat** as the first system message(s)
4. The customer is **sent a link** (via SMS) to open the new chat session
5. The voice call **ends** (or the customer ends it — the flow can wait briefly)

This is exactly what AWS describes in the [Contact Lens API documentation](https://docs.aws.amazon.com/connect/latest/adminguide/contact-lens-api.html):
> *"When a contact is transferred from one agent to another, you can transfer a transcript of the
> conversation to the new agent using ListRealtimeContactAnalysisSegments."*

### Concept 2 — RelatedContactId links contacts across channels

When you create the new chat contact using `StartChatContact`, you pass `RelatedContactId` set to
the original voice contact's ID. This:
- Creates a permanent link between the two contacts in Connect's records
- Copies all contact attributes from the voice contact to the new chat contact automatically
- Means the agent can see both contacts linked together in their CCP (Contact Control Panel)

Think of `RelatedContactId` as "this chat is a continuation of that call."

> Official docs: [StartChatContact — RelatedContactId parameter](https://docs.aws.amazon.com/connect/latest/APIReference/API_StartChatContact.html)

### Concept 3 — The voice transcript comes from Contact Lens

Contact Lens real-time analytics (which you enabled in your unified flow's Block 6V) generates a
live text transcript of the voice call. You retrieve this transcript using the
`ListRealtimeContactAnalysisSegments` API and inject it as messages into the new chat session.

**Important limitation**: Voice transcript data is only available via this API for **24 hours**
after the call. For long-term persistence, you must store it in DynamoDB or S3 at the time of
transfer (covered in Part D).

> Official docs: [ListRealtimeContactAnalysisSegments](https://docs.aws.amazon.com/contact-lens/latest/APIReference/API_ListRealtimeContactAnalysisSegments.html)

### Concept 4 — A ParticipantToken is the key to the chat deep link

When you call `StartChatContact`, the API returns a `ParticipantToken`. This token is what
authenticates the customer into the new chat session. You encode this token into a URL that
you send to the customer via SMS. When the customer opens the URL, your web page (or mobile app)
uses this token to connect to the chat session automatically — no login required.

The token is valid for the lifetime of the chat contact. Once the chat ends, the token is no
longer valid.

> Official docs: [CreateParticipantConnection API](https://docs.aws.amazon.com/connect-participant/latest/APIReference/API_CreateParticipantConnection.html)

### Concept 5 — "Same agent" routing vs AI agent routing

**For ARIA (AI agent)**:
- When the new chat contact enters the unified inbound flow, Block 8 (Connect assistant) creates
  a new ARIA session
- The session injector (Block 9) detects the `voiceContactId` attribute and retrieves the voice
  transcript from DynamoDB, injecting it into ARIA's session context
- ARIA automatically continues the conversation with full context

**For a human agent**:
- Amazon Connect routes the new chat contact to the queue
- You can route it to the **same agent** who handled the voice call by using the agent's
  `UserId` in a **Transfer to agent** flow
- The agent sees the new chat appear in their CCP with the linked voice contact transcript

Both paths are covered in this guide.

---

## 3. Architecture Overview

### Voice → Chat Flow

```
VOICE CALL IN PROGRESS
Customer is speaking with ARIA or a human agent
         │
         │  Customer says "I'd prefer to continue on chat"
         │  OR ARIA decides voice-to-chat is appropriate
         │  OR agent clicks "Transfer to Chat" in CCP
         ▼
[Lambda: voice_to_chat_transfer]
  1. Calls ListRealtimeContactAnalysisSegments → get voice transcript
  2. Formats transcript as text summary
  3. Calls StartChatContact API
     - RelatedContactId = voice ContactId
     - Attributes: voiceContactId, customerId, authStatus, agentId
     - InitialMessage: transcript summary header
  4. Receives ParticipantToken from StartChatContact
  5. Builds chat deep link URL (web) or mobile app deep link
  6. Stores transcript in DynamoDB (for 24h+ persistence)
  7. Sends SMS to customer via AWS End User Messaging SMS
  8. Returns chat ContactId to Connect flow
         │
         ▼
[Voice Flow continues briefly]
  Play prompt: "A chat link has been sent to your mobile number.
                You can continue this conversation on chat."
  → Disconnect voice call
         │
         ▼
CUSTOMER RECEIVES SMS WITH CHAT LINK
         │
         │  Customer taps link on phone
         ▼
[Web page / Mobile App]
  Uses ParticipantToken to call CreateParticipantConnection
  Chat session opens — customer sees transcript header at top
         │
         ▼
NEW CHAT CONTACT ENTERS UNIFIED INBOUND FLOW
  Block 3C → Block 4C → Block 8 (Connect assistant)
  Block 9: session_injector reads voiceContactId from attributes
           retrieves stored transcript from DynamoDB
           injects into Q Connect session
         │
  ┌──────┴──────┐
  │             │
  ▼             ▼
ARIA          HUMAN AGENT
continues     (same agent routed via agent routing)
conversation  sees linked voice transcript in CCP
with context
```

### Chat → Voice Flow

```
CHAT SESSION IN PROGRESS
Customer is chatting with ARIA or a human agent
         │
         │  Customer types "Can you call me instead?"
         │  OR ARIA decides voice is better
         │  OR agent clicks "Initiate Callback"
         ▼
[Lambda: chat_to_voice_transfer]
  1. Calls ListRealtimeContactAnalysisSegmentsV2 → get chat transcript
  2. Formats transcript as text summary
  3. Stores transcript + summary in DynamoDB
  4. Calls StartOutboundVoiceContact API
     - DestinationPhoneNumber = customer's phone
     - RelatedContactId = chat ContactId
     - Attributes: chatContactId, chatTranscriptSummary, customerId
  5. Sends chat message to customer: "We are calling you now..."
         │
         ▼
OUTBOUND VOICE CALL INITIATED TO CUSTOMER
         │
         ▼
CUSTOMER ANSWERS VOICE CALL
Outbound flow runs:
  - Reads chatContactId and transcript from attributes
  - Session injector injects chat context into ARIA session
  - OR: agent CCP shows linked chat transcript
         │
  ┌──────┴──────┐
  │             │
  ▼             ▼
ARIA          HUMAN AGENT
continues     (same agent who handled chat
voice call    gets the outbound call)
with full
chat context
```

---

## 4. Prerequisites

Before you start building, confirm you have all of the following in place:

| Requirement | Where to find/create it | Why needed |
|---|---|---|
| Amazon Connect instance in eu-west-2 | AWS Console → Amazon Connect | Base platform |
| ARIA Unified Inbound flow published | `docs/aria-connect-voice-chat-novice-guide.md` | The flow both channels enter |
| Contact Lens real-time analytics enabled | Block 6V of unified flow | Required for voice transcript retrieval |
| Phone number claimed and assigned to unified flow | Channels → Phone numbers | Voice channel entry point |
| Chat widget assigned to unified flow | Channels → Chat → widget | Chat channel entry point |
| session_injector Lambda deployed | `scripts/lambdas/session_injector.py` | Context injection for both channels |
| SMS-enabled phone number | AWS End User Messaging SMS console | Sending chat links to customers |
| DynamoDB table for transcript storage | See Part D | Cross-session transcript persistence |
| S3 bucket for chat transcripts | Connect instance storage settings | Required for chat analytics and persistence |

**Region note**: All resources must be in the same AWS region (`eu-west-2`). The Contact Lens API
endpoint for eu-west-2 is `https://contact-lens.eu-west-2.amazonaws.com`.

---

## Part A — How Both AI and Human Agents Receive the Transfer

This is the most important section to understand before building. The transfer architecture is
**channel-neutral** — the same Lambda creates the new contact, and the routing layer decides
whether ARIA or a human agent picks it up.

### How the routing decision is made

```
New chat contact created by Lambda
  │
  ▼
Enters ARIA Unified Inbound Flow
  │
  ▼
Block 8: Connect Assistant (ARIA session created)
  │
  ▼
Block 9: Session Injector (voice transcript injected)
  │
  ▼
Block 10: Set Working Queue → ARIA Banking Agents
  │
  ▼
Block 11: Transfer to Queue
  │
  │   Is there a human agent available and flagged?
  ├── If ARIA should handle → ARIA manages the chat
  └── If human agent needed → routed to available agent
```

**For ARIA to handle the transferred chat**:
- No special routing changes needed
- ARIA automatically picks up the chat in the queue (it always does)
- ARIA reads the injected voice transcript from the Q Connect session
- ARIA continues the conversation where the voice call left off

**For a human agent to handle the transferred chat**:
- The Lambda sets a contact attribute `transferToAgent = <agent-user-id>` when creating the chat
- The unified flow checks this attribute BEFORE Block 10/11
- If `transferToAgent` is set, a **Transfer to agent** flow block routes to that specific agent
- The agent receives the chat in their CCP alongside the linked voice contact

### The contact attribute that controls routing

The transfer Lambda sets this attribute on the new chat contact:

| Attribute key | Value | Effect |
|---|---|---|
| `transferToAgent` | (empty or not set) | ARIA handles the chat |
| `transferToAgent` | `<agent-user-id>` | Routes to that specific human agent |
| `voiceContactId` | original voice contact ID | Used by session injector to retrieve transcript |
| `chatTransferSource` | `voice` | Signals this is a cross-channel transfer |

The unified flow has a **Check contact attributes** block (before Block 10) that reads
`transferToAgent`. If it has a value, the flow uses a **Transfer to agent** block instead of
the standard queue routing.

---

## Part B — Voice → Chat Transfer (Step by Step)

### Step B.1 — Create the Voice-to-Chat Transfer Lambda

This Lambda does all the work: retrieves the voice transcript, creates the chat, sends the SMS.
You deploy it to Lambda in `eu-west-2` and add it to your Connect instance allow-list.

**Create the file `scripts/lambdas/voice_to_chat_transfer.py`**:

```python
"""
voice_to_chat_transfer.py — Amazon Connect Voice-to-Chat Channel Transfer Lambda

PURPOSE:
  Called from the ARIA Unified Inbound voice flow when a voice-to-chat transfer
  is requested. Performs three actions:
  1. Retrieves the real-time voice transcript from Contact Lens
  2. Creates a new chat contact via StartChatContact (linked to the voice contact)
  3. Sends an SMS to the customer with a deep link to the new chat session

ENVIRONMENT VARIABLES:
  INSTANCE_ID         — Amazon Connect instance ID (required)
  CONTACT_FLOW_ID     — Contact flow ID of the ARIA Unified Inbound flow (required)
  CHAT_WIDGET_URL     — Base URL of your chat widget page (required)
                        e.g. https://app.meridianbank.co.uk/chat
  MOBILE_APP_SCHEME   — Deep link scheme for mobile app (optional)
                        e.g. meridianbank://chat
  SMS_ORIGINATION_NUMBER — SMS-enabled phone number in E.164 format (required)
                           e.g. +441234567890
  DYNAMODB_TABLE      — DynamoDB table name for transcript storage (required)
  AGENT_ID            — Optional: route new chat to specific human agent (UserId)

INVOCATION (from Connect flow — AWS Lambda function block):
  Parameters passed from flow:
    contactId       — Current voice contact ID (System.ContactId)
    customerId      — Customer ID (User-defined attribute)
    authStatus      — Auth status (User-defined attribute)
    locale          — Locale (User-defined attribute)
    customerPhone   — Customer ANI phone number (System.CustomerNumber)
    agentId         — Current agent user ID (System.AgentUserId) — optional
    transferMode    — 'aria' or 'human' — who should handle the new chat
"""

import json
import os
import time
import boto3
from datetime import datetime, timezone

connect_client = boto3.client('connect', region_name='eu-west-2')
contact_lens_client = boto3.client('connect-contact-lens', region_name='eu-west-2')
end_user_messaging_client = boto3.client('pinpoint-sms-voice-v2', region_name='eu-west-2')
dynamodb = boto3.resource('dynamodb', region_name='eu-west-2')

INSTANCE_ID = os.environ['INSTANCE_ID']
CONTACT_FLOW_ID = os.environ['CONTACT_FLOW_ID']
CHAT_WIDGET_URL = os.environ['CHAT_WIDGET_URL']
MOBILE_APP_SCHEME = os.environ.get('MOBILE_APP_SCHEME', '')
SMS_ORIGINATION_NUMBER = os.environ['SMS_ORIGINATION_NUMBER']
DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']


def lambda_handler(event, context):
    """
    Main handler. Called synchronously from the Connect voice flow.
    Returns a dict with chatContactId and chatLink for the flow to use.
    """
    params = event.get('Details', {}).get('Parameters', {})

    voice_contact_id = params.get('contactId', '')
    customer_id = params.get('customerId', '')
    auth_status = params.get('authStatus', 'unauthenticated')
    locale = params.get('locale', 'en-GB')
    customer_phone = params.get('customerPhone', '')  # E.164 format e.g. +447700123456
    agent_id = params.get('agentId', '')              # empty if handled by ARIA
    transfer_mode = params.get('transferMode', 'aria')  # 'aria' or 'human'

    print(f"[VoiceToChatTransfer] voiceContactId={voice_contact_id}, customerId={customer_id}")

    # ----------------------------------------------------------------
    # Step 1: Retrieve the voice transcript from Contact Lens real-time
    # ----------------------------------------------------------------
    transcript_segments = retrieve_voice_transcript(voice_contact_id)
    transcript_text = format_transcript(transcript_segments)
    transcript_summary = summarise_transcript(transcript_segments)

    print(f"[VoiceToChatTransfer] Retrieved {len(transcript_segments)} transcript segments")

    # ----------------------------------------------------------------
    # Step 2: Store transcript in DynamoDB for long-term retrieval
    # (Contact Lens real-time data expires after 24 hours)
    # ----------------------------------------------------------------
    store_transcript_in_dynamodb(
        contact_id=voice_contact_id,
        customer_id=customer_id,
        channel='voice',
        transcript=transcript_text,
        summary=transcript_summary,
    )

    # ----------------------------------------------------------------
    # Step 3: Create the new chat contact via StartChatContact API
    # ----------------------------------------------------------------
    # The InitialMessage is a system-generated header that appears at
    # the top of the chat when the customer opens it.
    initial_message = (
        f"[Continuing from your voice call — {datetime.now(timezone.utc).strftime('%H:%M UTC')}]\n\n"
        f"{transcript_summary}"
    )

    # Set transfer_to_agent attribute only if routing to a specific human agent
    chat_attributes = {
        'voiceContactId': voice_contact_id,
        'customerId': customer_id,
        'authStatus': auth_status,
        'locale': locale,
        'channel': 'chat',
        'chatTransferSource': 'voice',
        'transferToAgent': agent_id if transfer_mode == 'human' else '',
    }

    try:
        chat_response = connect_client.start_chat_contact(
            InstanceId=INSTANCE_ID,
            ContactFlowId=CONTACT_FLOW_ID,
            Attributes=chat_attributes,
            ParticipantDetails={
                'DisplayName': f'Customer ({customer_id})' if customer_id else 'Customer',
            },
            InitialMessage={
                'ContentType': 'text/plain',
                'Content': initial_message,
            },
            # Link this new chat to the voice contact
            RelatedContactId=voice_contact_id,
            # Chat stays open for 48 hours (2880 minutes) — customer may not open immediately
            ChatDurationInMinutes=2880,
            SupportedMessagingContentTypes=['text/plain', 'text/markdown'],
        )
    except Exception as e:
        print(f"[VoiceToChatTransfer] ERROR creating chat contact: {e}")
        return {'status': 'error', 'message': str(e)}

    chat_contact_id = chat_response['ContactId']
    participant_token = chat_response['ParticipantToken']

    print(f"[VoiceToChatTransfer] Chat created: contactId={chat_contact_id}")

    # ----------------------------------------------------------------
    # Step 4: Build the chat deep link
    # ----------------------------------------------------------------
    web_link = f"{CHAT_WIDGET_URL}?token={participant_token}&ref={voice_contact_id}"

    # Mobile app deep link (optional — app must handle this scheme)
    mobile_link = ''
    if MOBILE_APP_SCHEME:
        mobile_link = f"{MOBILE_APP_SCHEME}?token={participant_token}&ref={voice_contact_id}"

    # ----------------------------------------------------------------
    # Step 5: Send SMS to customer with the chat link
    # ----------------------------------------------------------------
    if customer_phone:
        # Use web link by default; prefer mobile link if available
        link_to_send = mobile_link if mobile_link else web_link

        sms_body = (
            f"Meridian Bank: Your conversation has been transferred to chat. "
            f"Tap to continue (link valid 48 hours): {link_to_send}"
        )

        try:
            send_sms(customer_phone, sms_body)
            print(f"[VoiceToChatTransfer] SMS sent to {customer_phone}")
        except Exception as e:
            # SMS failure is non-fatal — the chat is already created
            print(f"[VoiceToChatTransfer] WARNING: SMS send failed: {e}")
    else:
        print("[VoiceToChatTransfer] WARNING: No customer phone number — SMS not sent")

    return {
        'status': 'success',
        'chatContactId': chat_contact_id,
        'chatLink': web_link,
        'mobileChatLink': mobile_link,
        'smsSent': 'true' if customer_phone else 'false',
    }


def retrieve_voice_transcript(contact_id: str) -> list:
    """
    Retrieves the full real-time voice transcript from Contact Lens.
    Uses pagination to get all segments.

    Official docs: https://docs.aws.amazon.com/contact-lens/latest/APIReference/
                   API_ListRealtimeContactAnalysisSegments.html

    Important: Voice data is retained for 24 hours. Must be called during
    or immediately after the call.
    """
    segments = []
    next_token = None

    try:
        while True:
            kwargs = {
                'InstanceId': INSTANCE_ID,
                'ContactId': contact_id,
                'MaxResults': 100,
            }
            if next_token:
                kwargs['NextToken'] = next_token

            response = contact_lens_client.list_realtime_contact_analysis_segments(**kwargs)
            segments.extend(response.get('Segments', []))
            next_token = response.get('NextToken')

            # No NextToken = all segments retrieved (analysis complete)
            if not next_token:
                break

    except contact_lens_client.exceptions.ResourceNotFoundException:
        # Contact Lens not enabled for this contact, or contact not found
        print(f"[VoiceToChatTransfer] Contact Lens data not available for {contact_id}")
        return []
    except Exception as e:
        print(f"[VoiceToChatTransfer] Error retrieving transcript: {e}")
        return []

    return segments


def format_transcript(segments: list) -> str:
    """
    Converts Contact Lens transcript segments into readable text.
    Returns a formatted string with speaker labels and utterances.
    """
    if not segments:
        return "(Voice transcript not available)"

    lines = []
    for segment in segments:
        transcript = segment.get('Transcript', {})
        if not transcript:
            continue

        role = transcript.get('ParticipantRole', 'UNKNOWN')
        content = transcript.get('Content', '')

        # Map Connect participant roles to human-readable labels
        speaker = 'ARIA' if role == 'AGENT' else 'Customer'

        if content:
            lines.append(f"{speaker}: {content}")

    return '\n'.join(lines) if lines else "(No transcript segments found)"


def summarise_transcript(segments: list) -> str:
    """
    Creates a brief summary of the conversation for the chat header.
    In production this would call Bedrock/Claude for a proper AI summary.
    This implementation creates a condensed version of the last few turns.
    """
    if not segments:
        return "Your previous voice conversation has been transferred to chat."

    transcript_lines = []
    for segment in segments:
        transcript = segment.get('Transcript', {})
        if transcript and transcript.get('Content'):
            role = transcript.get('ParticipantRole', 'UNKNOWN')
            speaker = 'ARIA' if role == 'AGENT' else 'You'
            transcript_lines.append(f"{speaker}: {transcript['Content']}")

    if not transcript_lines:
        return "Your previous voice conversation has been transferred to chat."

    # Show the last 6 turns as context (keeps the header manageable)
    recent = transcript_lines[-6:]
    return (
        "📞 **Transferred from voice call** — here is what was discussed:\n\n"
        + '\n'.join(recent)
        + "\n\n---\nContinue the conversation below:"
    )


def store_transcript_in_dynamodb(contact_id: str, customer_id: str, channel: str,
                                  transcript: str, summary: str) -> None:
    """
    Stores the transcript in DynamoDB for cross-session retrieval.
    This is critical because Contact Lens real-time data expires after 24 hours.

    Table schema:
      contactId (PK, String)  — the original contact ID
      customerId (GSI, String) — for customer-based lookups
      channel                 — 'voice' or 'chat'
      transcript              — full formatted transcript
      summary                 — brief summary for injection
      timestamp               — ISO 8601
      ttl                     — DynamoDB TTL (7 days)
    """
    table = dynamodb.Table(DYNAMODB_TABLE)
    ttl = int(time.time()) + (7 * 24 * 60 * 60)  # 7 days TTL

    table.put_item(Item={
        'contactId': contact_id,
        'customerId': customer_id,
        'channel': channel,
        'transcript': transcript,
        'summary': summary,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'ttl': ttl,
    })


def send_sms(destination_number: str, message_body: str) -> None:
    """
    Sends an SMS via AWS End User Messaging SMS (pinpoint-sms-voice-v2).

    The SMS_ORIGINATION_NUMBER must be a number you procured from
    AWS End User Messaging SMS and imported into Amazon Connect.

    Official docs:
      https://docs.aws.amazon.com/connect/latest/adminguide/setup-sms-messaging.html
    """
    end_user_messaging_client.send_text_message(
        DestinationPhoneNumber=destination_number,
        OriginationIdentity=SMS_ORIGINATION_NUMBER,
        MessageBody=message_body,
        MessageType='TRANSACTIONAL',  # For one-time notifications, not marketing
    )
```

**Deploy the Lambda**:
1. Create `scripts/lambdas/voice_to_chat_transfer.py` with the code above
2. In the AWS Lambda console → **Create function**
3. Name: `voice_to_chat_transfer`
4. Runtime: Python 3.12
5. Region: `eu-west-2`
6. Set environment variables:
   - `INSTANCE_ID`: your Connect instance ID
   - `CONTACT_FLOW_ID`: ARN/ID of the ARIA Unified Inbound flow
   - `CHAT_WIDGET_URL`: `https://app.meridianbank.co.uk/chat`
   - `SMS_ORIGINATION_NUMBER`: your SMS number in E.164 format
   - `DYNAMODB_TABLE`: `aria-transcript-store` (create in Part D)
7. Attach the IAM execution role (see IAM Permissions section)
8. **Add to Connect allow-list**: Connect admin → your instance → **Flows** → **AWS Lambda** → Add `voice_to_chat_transfer`

---

### Step B.2 — Add the Transfer Block to the Voice Flow

You need to add a trigger point in the ARIA Unified Inbound flow that, when reached, invokes the
transfer Lambda. The trigger can come from:
- ARIA detecting the customer's intent to switch to chat (ARIA tool call)
- An agent pressing a button in the CCP (for human agent flows)
- A time threshold (e.g. after 10 minutes, offer chat transfer)

**Add a contact attribute check before the Transfer to Queue block**:

1. Open your `ARIA Banking Unified Inbound` flow in the Flow Designer
2. In the voice path, **after Block 9 (session injector)** and **before Block 10 (Set working queue)**,
   add a new **Check contact attributes** block:
   - Namespace: `User-defined`
   - Attribute: `requestChatTransfer`
   - Condition: `Equals` / `true`
3. Wire:
   - `true` branch → the transfer Lambda block (new block below)
   - `No match` → Block 10 (Set working queue) as before

**Add the AWS Lambda function block for the transfer**:

1. Drag a new **AWS Lambda function** block
2. Connect the `true` branch of the check above → this block
3. Configure:
   - Function: `voice_to_chat_transfer`
   - Execution mode: **Synchronous**
   - Timeout: **8 seconds**
   - Send parameters:
     - `contactId` → System / `ContactId`
     - `customerId` → User-defined / `customerId`
     - `authStatus` → User-defined / `authStatus`
     - `locale` → User-defined / `locale`
     - `customerPhone` → System / `Customer number`
     - `agentId` → System / `Agent UserId`
     - `transferMode` → (hardcode `aria` or use contact attribute)
4. Wire outputs:
   - **Success** → Play prompt block (voice farewell, see below)
   - **Error** → Block 10 (fall back to regular routing — do not drop the call)
   - **Timeout** → Block 10 (same)

**Add the farewell Play prompt (voice path after transfer)**:

1. Drag a **Play prompt** block
2. Connect the Lambda block's **Success** → this block
3. Text:
   ```
   I've transferred your conversation to chat. A link has been sent to your mobile.
   You can continue talking with ARIA on chat, and your conversation history will be there.
   ```
4. Wire its **Success** → a **Disconnect / hang up** block

**Save and publish** the updated unified flow.

> **How ARIA triggers the transfer**: ARIA has a tool called `request_channel_transfer` in its
> tool registry. When a customer says "Can we do this on chat instead?", ARIA calls this tool.
> The tool sets the contact attribute `requestChatTransfer = true` via the Connect API. The
> next time ARIA's response loop checks in with the flow, the attribute check block fires.
> *(Implementing the ARIA tool for this is covered in Part E.)*

---

### Step B.3 — Build the Chat Deep Link (Web and Mobile)

The `ParticipantToken` from `StartChatContact` is the key that opens the customer directly into
their chat session without any login friction. You need a web page that reads this token from
the URL and uses it to connect.

#### Web deep link (HTML + JavaScript)

Create a page at your `CHAT_WIDGET_URL` path (e.g. `https://app.meridianbank.co.uk/chat`):

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Meridian Bank — Continue Your Conversation</title>
</head>
<body>

  <h2>Continuing your Meridian Bank conversation</h2>
  <p>Connecting you to ARIA (or your agent) now...</p>

  <!-- Amazon Connect Chat Widget script from your Connect instance -->
  <script type="text/javascript">
    (function(w, d, x, id){
      s=d.createElement('script');
      s.src='https://dtn7rvxwwlhud.cloudfront.net/amazon-connect-chat-interface-client.js';
      s.async=1;
      s.id=id;
      d.getElementsByTagName('head')[0].appendChild(s);
      w[x] = w[x] || function() { (w[x].ac = w[x].ac || []).push(arguments) };
    })(window, document, 'amazon_connect', 'YOUR-WIDGET-ID');

    // Read the ParticipantToken from the URL query string
    const urlParams = new URLSearchParams(window.location.search);
    const participantToken = urlParams.get('token');
    const voiceRef = urlParams.get('ref');

    if (participantToken) {
      // Tell the widget to use the pre-supplied participant token
      // This skips the normal chat initiation and directly connects to
      // the already-created chat session.
      amazon_connect('authenticate', function(update) {
        update(participantToken);
      });

      // Auto-open the chat widget immediately
      amazon_connect('onLoad', function(widget) {
        widget.trigger('maximize');
      });
    } else {
      // Fallback: show an error if no token is present
      document.body.innerHTML = '<h2>Invalid or expired chat link.</h2>' +
        '<p>Please call <a href="tel:+441234567890">0800 123 4567</a> for assistance.</p>';
    }

    amazon_connect('styles', {
      openChat: { color: '#FFF', backgroundColor: '#003DA5' },
      closeChat: { color: '#FFF', backgroundColor: '#003DA5' }
    });
    amazon_connect('snippetId', 'YOUR-SNIPPET-ID');
    amazon_connect('supportedMessagingContentTypes', ['text/plain', 'text/markdown']);
  </script>

</body>
</html>
```

> **What `authenticate` does**: The `amazon_connect('authenticate', ...)` call passes the
> pre-supplied `participantToken` to the widget. This token was generated by `StartChatContact`
> and is specific to this customer's session. The widget uses it to call
> `CreateParticipantConnection` on the customer's behalf, connecting them directly into the
> active chat without creating a new contact.

#### Mobile app deep link

If you have a mobile app (iOS/Android), register a deep link scheme (e.g. `meridianbank://chat`).
Your app's chat screen should:
1. Extract the `token` parameter from the deep link URL
2. Call the Amazon Connect Participant Service's
   [CreateParticipantConnection](https://docs.aws.amazon.com/connect-participant/latest/APIReference/API_CreateParticipantConnection.html)
   API with the token to get a WebSocket URL
3. Connect to the WebSocket and start receiving/sending messages

```
meridianbank://chat?token=<ParticipantToken>&ref=<voiceContactId>
```

The mobile app uses the [Amazon Connect ChatJS library](https://github.com/amazon-connect/amazon-connect-chatjs)
or calls the Participant Service API directly.

---

### Step B.4 — How ARIA Picks Up the Chat with Full Context

When the new chat contact enters the ARIA Unified Inbound flow:

1. **Block 2** (Check Channel) detects `Channel = CHAT` → routes to chat path
2. **Block 3C** sets `channel=chat` but inherits all other attributes from `RelatedContactId`
   (including `voiceContactId`, `customerId`, `authStatus`)
3. **Block 8** creates the ARIA Q Connect session
4. **Block 9** (session injector) — this is where ARIA gets the voice context

The session injector must be **updated** to detect cross-channel transfers and retrieve the stored
transcript. See Part E for the session injector changes.

When ARIA's session is created with the voice transcript injected, ARIA's system prompt template
receives `{{$.Custom.priorTranscript}}` populated with the formatted voice conversation. ARIA can
then say something like:

> *"Welcome back. I can see we were just discussing your current account balance on the phone.
> I've transferred our conversation here so you can continue at your own pace. How can I help
> you further?"*

---

### Step B.5 — How a Human Agent Picks Up the Chat

When `transferMode = human` and `agentId` is set, the transfer Lambda sets
`transferToAgent = <agent-user-id>` on the new chat contact. The unified flow handles this:

**Add a Check + Transfer-to-Agent path to the unified flow** (after Block 9, before Block 10):

1. Add a **Check contact attributes** block:
   - Namespace: `User-defined`
   - Attribute: `transferToAgent`
   - Condition: `Greater than` / `0` (checks the string is non-empty)

2. Wire:
   - Non-empty → **Set working queue** → **Transfer to agent** block (see below)
   - No match (empty) → Block 10 (Set working queue for ARIA / standard queue)

3. Add a **Transfer to agent** block:
   - Under **Agent**: Select **Use attribute**
   - Namespace: `User-defined`
   - Attribute: `transferToAgent`
   - This routes the chat to the specific agent whose user ID is in that attribute

**What the agent sees**:
- A new chat appears in their CCP with the label `Voice Transfer — [customer name]`
- In the contact details panel, they see **Related contacts** showing the original voice call
- Clicking the related voice contact shows the voice transcript in the Contact details view
- The chat's first message is the formatted voice transcript summary (from `InitialMessage` in
  the Lambda's `StartChatContact` call)

> **Official reference**: The CCP shows linked contacts from `RelatedContactId` automatically.
> Agents do not need any special training — the transcript appears as part of the chat history.

---

### Step B.6 — How the Voice Transcript Appears in Chat

There are **two places** the voice transcript appears:

**1. As the first message in the chat (`InitialMessage`)**

When `StartChatContact` is called with an `InitialMessage`, that message appears at the very top
of the chat thread — before any customer or agent messages. This is the voice transcript summary
that the Lambda generates.

The customer sees it formatted like:

```
📞 Transferred from voice call — 14:32 UTC

ARIA: Hello, welcome to Meridian Bank. How can I help you today?
You: I want to check my account balance.
ARIA: Your current account ending in 4521 has a balance of £1,247.50 as of today.
You: And can you check if my direct debits went out?
ARIA: Yes, I can see three direct debits processed this morning...

---
Continue the conversation below:
```

**2. In the agent's Contact Lens transcript panel (for human agents)**

The CCP's Contact Lens panel shows the full transcript of the linked voice contact. The agent
can scroll through the entire voice conversation at any time during the chat. This is part of
Amazon Connect's native linked-contact transcript view and requires no additional configuration.

---

## Part C — Chat → Voice Transfer (Step by Step)

### Step C.1 — Create the Chat-to-Voice Transfer Lambda

This Lambda retrieves the chat transcript and initiates an outbound voice call to the customer.

**Create the file `scripts/lambdas/chat_to_voice_transfer.py`**:

```python
"""
chat_to_voice_transfer.py — Amazon Connect Chat-to-Voice Channel Transfer Lambda

PURPOSE:
  Called from the ARIA Unified Inbound chat flow when a chat-to-voice transfer
  is requested. Performs three actions:
  1. Retrieves the real-time chat transcript from Contact Lens (V2 API)
  2. Stores the transcript in DynamoDB
  3. Initiates an outbound voice call to the customer via StartOutboundVoiceContact

ENVIRONMENT VARIABLES:
  INSTANCE_ID               — Amazon Connect instance ID (required)
  CONTACT_FLOW_ID           — Outbound whisper flow or inbound flow ID (required)
  QUEUE_ID                  — Queue for the outbound call (required)
  SOURCE_PHONE_NUMBER       — Amazon Connect phone number for outbound call (E.164)
  DYNAMODB_TABLE            — DynamoDB table name for transcript storage (required)

INVOCATION (from Connect flow — AWS Lambda function block):
  Parameters:
    contactId       — Current chat contact ID
    customerId      — Customer ID
    authStatus      — Auth status
    locale          — Locale
    customerPhone   — Customer phone number to call back (E.164)
    agentId         — Current agent user ID (optional)
    transferMode    — 'aria' or 'human'
"""

import json
import os
import time
import boto3
from datetime import datetime, timezone

connect_client = boto3.client('connect', region_name='eu-west-2')
dynamodb = boto3.resource('dynamodb', region_name='eu-west-2')

INSTANCE_ID = os.environ['INSTANCE_ID']
CONTACT_FLOW_ID = os.environ['CONTACT_FLOW_ID']
QUEUE_ID = os.environ['QUEUE_ID']
SOURCE_PHONE_NUMBER = os.environ['SOURCE_PHONE_NUMBER']
DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']


def lambda_handler(event, context):
    params = event.get('Details', {}).get('Parameters', {})

    chat_contact_id = params.get('contactId', '')
    customer_id = params.get('customerId', '')
    auth_status = params.get('authStatus', 'unauthenticated')
    locale = params.get('locale', 'en-GB')
    customer_phone = params.get('customerPhone', '')  # Must be E.164: +447700123456
    agent_id = params.get('agentId', '')
    transfer_mode = params.get('transferMode', 'aria')

    print(f"[ChatToVoiceTransfer] chatContactId={chat_contact_id}, customerId={customer_id}")

    if not customer_phone:
        print("[ChatToVoiceTransfer] ERROR: No customer phone number provided")
        return {'status': 'error', 'message': 'Customer phone number required for callback'}

    # ----------------------------------------------------------------
    # Step 1: Retrieve the chat transcript from Contact Lens V2 API
    # ----------------------------------------------------------------
    transcript_segments = retrieve_chat_transcript(chat_contact_id)
    transcript_text = format_chat_transcript(transcript_segments)
    transcript_summary = summarise_chat_transcript(transcript_segments)

    print(f"[ChatToVoiceTransfer] Retrieved {len(transcript_segments)} chat segments")

    # ----------------------------------------------------------------
    # Step 2: Store transcript in DynamoDB
    # ----------------------------------------------------------------
    store_transcript_in_dynamodb(
        contact_id=chat_contact_id,
        customer_id=customer_id,
        channel='chat',
        transcript=transcript_text,
        summary=transcript_summary,
    )

    # ----------------------------------------------------------------
    # Step 3: Initiate outbound voice call via StartOutboundVoiceContact
    # ----------------------------------------------------------------
    voice_attributes = {
        'chatContactId': chat_contact_id,
        'customerId': customer_id,
        'authStatus': auth_status,
        'locale': locale,
        'channel': 'voice',
        'voiceTransferSource': 'chat',
        'chatTranscriptSummary': transcript_summary[:1000],  # Fits in contact attribute (32KB limit)
        'transferToAgent': agent_id if transfer_mode == 'human' else '',
    }

    try:
        voice_response = connect_client.start_outbound_voice_contact(
            DestinationPhoneNumber=customer_phone,
            InstanceId=INSTANCE_ID,
            ContactFlowId=CONTACT_FLOW_ID,
            QueueId=QUEUE_ID,
            SourcePhoneNumber=SOURCE_PHONE_NUMBER,
            Attributes=voice_attributes,
            # Link the outbound voice call to the original chat
            RelatedContactId=chat_contact_id,
            Name=f'Chat Transfer — {customer_id}',
            Description='Continuing conversation transferred from chat',
        )
    except Exception as e:
        print(f"[ChatToVoiceTransfer] ERROR starting outbound voice: {e}")
        return {'status': 'error', 'message': str(e)}

    voice_contact_id = voice_response['ContactId']
    print(f"[ChatToVoiceTransfer] Outbound voice call created: {voice_contact_id}")

    return {
        'status': 'success',
        'voiceContactId': voice_contact_id,
        'callbackNumber': customer_phone,
    }


def retrieve_chat_transcript(contact_id: str) -> list:
    """
    Retrieves the chat transcript from Contact Lens V2 API.
    Different API from the voice transcript — use V2 for chat.

    Official docs:
      https://docs.aws.amazon.com/connect/latest/APIReference/
      API_ListRealtimeContactAnalysisSegmentsV2.html
    """
    segments = []
    next_token = None

    try:
        while True:
            kwargs = {
                'InstanceId': INSTANCE_ID,
                'ContactId': contact_id,
                'MaxResults': 100,
                'OutputType': 'Raw',
                'SegmentTypes': ['TRANSCRIPT'],
            }
            if next_token:
                kwargs['NextToken'] = next_token

            response = connect_client.list_realtime_contact_analysis_segments_v2(**kwargs)
            segments.extend(response.get('Segments', []))
            next_token = response.get('NextToken')

            if not next_token:
                break

    except Exception as e:
        print(f"[ChatToVoiceTransfer] Error retrieving chat transcript: {e}")
        return []

    return segments


def format_chat_transcript(segments: list) -> str:
    """Formats chat transcript segments into readable text."""
    if not segments:
        return "(Chat transcript not available)"

    lines = []
    for segment in segments:
        # Chat segments have a different structure from voice segments
        if 'Transcript' in segment:
            t = segment['Transcript']
            role = t.get('ParticipantRole', 'UNKNOWN')
            content = t.get('Content', '')
            speaker = 'ARIA' if role == 'AGENT' else 'Customer'
            if content:
                lines.append(f"{speaker}: {content}")

    return '\n'.join(lines) if lines else "(No chat transcript segments found)"


def summarise_chat_transcript(segments: list) -> str:
    """Creates a brief summary for voice flow context injection."""
    lines = format_chat_transcript(segments).split('\n')
    if not lines or lines == ['(No chat transcript segments found)']:
        return "Customer transferred from chat conversation."

    recent = lines[-6:]
    return (
        "💬 Transferred from chat:\n"
        + '\n'.join(recent)
    )


def store_transcript_in_dynamodb(contact_id: str, customer_id: str, channel: str,
                                  transcript: str, summary: str) -> None:
    """Stores transcript in DynamoDB. Same schema as voice_to_chat_transfer."""
    table = dynamodb.Table(DYNAMODB_TABLE)
    ttl = int(time.time()) + (7 * 24 * 60 * 60)

    table.put_item(Item={
        'contactId': contact_id,
        'customerId': customer_id,
        'channel': channel,
        'transcript': transcript,
        'summary': summary,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'ttl': ttl,
    })
```

**Deploy** the same way as the voice-to-chat Lambda:
1. Function name: `chat_to_voice_transfer`
2. Runtime: Python 3.12, region `eu-west-2`
3. Environment variables: `INSTANCE_ID`, `CONTACT_FLOW_ID`, `QUEUE_ID`, `SOURCE_PHONE_NUMBER`, `DYNAMODB_TABLE`
4. Add to Connect instance allow-list

---

### Step C.2 — Add the Transfer Block to the Chat Flow

In the ARIA Unified Inbound flow, the chat path needs the same attribute-check → Lambda pattern:

**After Block 9 (session injector), add a check for `requestVoiceTransfer`**:

1. Add a **Check contact attributes** block:
   - Namespace: `User-defined`
   - Attribute: `requestVoiceTransfer`
   - Condition: `Equals` / `true`
2. Wire:
   - `true` → new **AWS Lambda function** block (`chat_to_voice_transfer`)
   - `No match` → Block 10 (normal routing)

**Configure the Lambda block**:
- Function: `chat_to_voice_transfer`
- Execution mode: **Synchronous**, timeout: 8 seconds
- Send parameters:
  - `contactId` → System / `ContactId`
  - `customerId` → User-defined / `customerId`
  - `customerPhone` → User-defined / `customerPhone`
  - `agentId` → System / `Agent UserId`
  - `transferMode` → User-defined / `transferMode` (or hardcode `aria`)

**After the Lambda, add a Send message block** (tells the customer to expect a call):

> **Note**: Use the **Send message** block for chat (not Play prompt).
> The Send message block works on chat contacts; Play prompt sends audio (voice only).

1. Connect Lambda **Success** → a **Send message** block
2. Text:
   ```
   I've requested a callback for you. You should receive a call within the next few minutes
   on your registered mobile number. The agent will have a full summary of our chat conversation.
   ```
3. Wire its output → a **Disconnect / hang up** block *(end the chat — the voice call is the continuation)*

**Save and publish** the updated flow.

---

### Step C.3 — How ARIA Handles the Voice Callback with Chat Context

When the outbound voice call connects, the flow runs with the `chatContactId` and
`chatTranscriptSummary` attributes already set (passed via `start_outbound_voice_contact`).

The session injector (updated in Part E) detects `voiceTransferSource = chat` and retrieves the
full chat transcript from DynamoDB using `chatContactId`. It injects this into ARIA's Q Connect
session so ARIA can say:

> *"Hello, this is ARIA from Meridian Bank. I can see we were just chatting about your lost debit
> card. I have the full conversation in front of me. Shall we continue from where we left off?"*

The `RelatedContactId` link ensures the voice call appears as a continuation of the chat in
Connect's contact records.

---

### Step C.4 — How a Human Agent Handles the Voice Callback

When `transferMode = human`:
1. The outbound voice contact is routed to the `ARIA Banking Agents` queue
2. If `transferToAgent` is set, a **Transfer to agent** block routes directly to that agent
3. The agent's CCP shows the call with:
   - **Contact name**: `Chat Transfer — [customer ID]`
   - **Related contacts**: the original chat contact (click to view full chat transcript)
   - **Contact attributes panel**: shows `chatTranscriptSummary` (the last 6 turns)

The agent does not need to ask the customer to repeat anything — they have the full context.

---

## Part D — DynamoDB for Cross-Session Transcript Storage

Both Lambdas need a DynamoDB table to store transcripts. The Contact Lens real-time data API
only retains voice data for **24 hours** — so if a customer opens their chat link hours later,
the Lambda must retrieve the transcript from DynamoDB rather than Contact Lens.

> Official docs: [ListRealtimeContactAnalysisSegments](https://docs.aws.amazon.com/contact-lens/latest/APIReference/API_ListRealtimeContactAnalysisSegments.html)
> — *"Voice data is retained for 24 hours. You must invoke this API during that time."*

> **Full step-by-step creation instructions** (console + CLI + IAM permissions) are in:
> [`docs/aria-connect-conversational-ai-setup-guide.md` — Step 5.4](aria-connect-conversational-ai-setup-guide.md#step-54--create-the-dynamodb-tables)
>
> This section provides a quick reference summary. Follow the setup guide for the full
> walkthrough including IAM policy attachment and verification steps.

### Table: `aria-transcript-store`

**Quick reference schema**:

| Attribute | Type | Role | Example |
|---|---|---|---|
| `contactId` | String | **Partition key** | `11111111-2222-3333-...` |
| `customerId` | String | GSI partition key | `CUST-001` |
| `channel` | String | `voice` or `chat` | `voice` |
| `transcript` | String | Full conversation text | `"ARIA: Hello...\nCustomer: ..."` |
| `summary` | String | Last 6 turns (for prompt injection) | `"💬 Transferred from chat:..."` |
| `timestamp` | String | ISO 8601 write time | `"2026-04-01T13:45:22Z"` |
| `ttl` | Number | Auto-delete epoch (7 days) | `1746000000` |

**Create via CLI (quick)**:

```bash
# Create table + GSI
aws dynamodb create-table \
  --table-name aria-transcript-store \
  --attribute-definitions \
    AttributeName=contactId,AttributeType=S \
    AttributeName=customerId,AttributeType=S \
  --key-schema \
    AttributeName=contactId,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --global-secondary-indexes '[
    {
      "IndexName": "customerId-index",
      "KeySchema": [{"AttributeName": "customerId", "KeyType": "HASH"}],
      "Projection": {
        "ProjectionType": "INCLUDE",
        "NonKeyAttributes": ["transcript", "summary", "timestamp", "channel"]
      }
    }
  ]' \
  --region eu-west-2

# Wait for Active
aws dynamodb wait table-exists \
  --table-name aria-transcript-store \
  --region eu-west-2

# Enable 7-day TTL
aws dynamodb update-time-to-live \
  --table-name aria-transcript-store \
  --time-to-live-specification "Enabled=true,AttributeName=ttl" \
  --region eu-west-2
```

**Console steps (summary)**:
1. DynamoDB → **Create table**
2. Table name: `aria-transcript-store` / Partition key: `contactId` (String)
3. Capacity mode: **On-demand** → Create
4. After Active: **Additional settings** → **Manage TTL** → attribute: `ttl` → Save
5. **Indexes** tab → **Create index**: partition key `customerId`, index name `customerId-index`,
   projected attributes: `transcript`, `summary`, `timestamp`, `channel`

**Also needed — `aria-session-memory`** (for `priorSummary`):
This table is fully documented in [Step 5.4 of the setup guide](aria-connect-conversational-ai-setup-guide.md#step-54--create-the-dynamodb-tables).
It stores one summary per customer (schema: PK=`CUSTOMER#<id>`, SK=`LAST_SESSION_SUMMARY`,
attribute: `summary` String). TTL: 90 days.

---

## Part E — Session Injector Updates for Cross-Channel Context

> **These changes are already applied** to `scripts/lambdas/session_injector.py`.
> This section explains what was added and why, so you can understand how it works
> and verify the deployment is correct.

The session injector Lambda (`session_injector.py`) was updated with two additions:

**1. New environment variable `TRANSCRIPT_TABLE_NAME`**

Set to `aria-transcript-store` (the table created in Part D). If not set, cross-channel
transcript lookup is silently skipped (safe default — the call continues without prior context).

Set it on the Lambda:
```bash
aws lambda update-function-configuration \
  --function-name aria-session-injector \
  --environment "Variables={
    ASSISTANT_ID=<your-assistant-id>,
    MEMORY_TABLE_NAME=aria-session-memory,
    TRANSCRIPT_TABLE_NAME=aria-transcript-store
  }" \
  --region eu-west-2
```

**2. New function `_get_cross_channel_transcript()`**

This function is called inside `lambda_handler` just before the Q Connect inject call.
It checks for two contact attributes that the transfer Lambdas set:

| Attribute | Value | Meaning |
|---|---|---|
| `chatTransferSource` | `voice` | This is a new CHAT contact — the customer came from a voice call |
| `voiceTransferSource` | `chat` | This is a new VOICE contact — the customer came from a chat session |

When either attribute is detected, the function reads the linked prior contact's transcript
from `aria-transcript-store` and adds four new session variables:

| Session variable | Content | Available in prompt as |
|---|---|---|
| `priorTranscript` | Full conversation text from prior channel | `{{$.Custom.priorTranscript}}` |
| `priorSummary` | Brief last-6-turns summary | `{{$.Custom.priorSummary}}` |
| `priorChannel` | `voice` or `chat` | `{{$.Custom.priorChannel}}` |
| `priorContactId` | The original contact ID | `{{$.Custom.priorContactId}}` |

**3. Update the ARIA system prompt** to use these variables

In your AI Prompt (Connect admin → AI Prompts → your ARIA prompt), add this block inside the
customer context section:

```
{% if $.Custom.priorChannel %}
CROSS-CHANNEL TRANSFER — IMPORTANT:
This {{ $.Custom.channel }} session is a continuation of a prior {{ $.Custom.priorChannel }} conversation.
Do NOT ask the customer to repeat information they already provided in that conversation.
Acknowledge the transfer naturally.

Prior conversation summary:
{{ $.Custom.priorSummary }}

Full prior transcript (for your reference only — do not read it verbatim to the customer):
{{ $.Custom.priorTranscript }}
{% endif %}
```

**Verify the update is working**

After deploying, trigger a test transfer and check the session injector's CloudWatch logs:

```
[VoiceToChatTransfer] voiceContactId=... chatContactId=...
[SessionInjector] Cross-channel context injected: priorChannel='voice' priorContactId='...'
```

If you see `Cross-channel context injected` in the logs, the integration is working correctly.
If you see `Cross-channel transcript not found in DynamoDB`, the transfer Lambda may not have
stored the transcript yet (check its CloudWatch logs for errors).

**Update the ARIA system prompt** to use these new variables:

Add the following block to the system prompt in `aria/prompts/system_prompt.txt` (or wherever
your prompt is maintained), inside the customer context section:

```
{% if $.Custom.priorChannel %}
IMPORTANT — CROSS-CHANNEL TRANSFER CONTEXT:
This {{ $.Custom.channel }} session is a continuation of a previous {{ $.Custom.priorChannel }} conversation.
Do not ask the customer to repeat information they already provided.

Prior conversation summary:
{{ $.Custom.priorSummary }}

Full prior transcript (for reference):
{{ $.Custom.priorTranscript }}
{% endif %}
```

---

## IAM Permissions for the Transfer Lambdas

Both transfer Lambdas need the following IAM permissions attached to their execution role:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ConnectChatAndVoice",
      "Effect": "Allow",
      "Action": [
        "connect:StartChatContact",
        "connect:StartOutboundVoiceContact",
        "connect:DescribeContact",
        "connect:ListRealtimeContactAnalysisSegmentsV2"
      ],
      "Resource": [
        "arn:aws:connect:eu-west-2:395402194296:instance/*"
      ]
    },
    {
      "Sid": "ContactLensVoiceTranscript",
      "Effect": "Allow",
      "Action": [
        "connect-contact-lens:ListRealtimeContactAnalysisSegments"
      ],
      "Resource": "*"
    },
    {
      "Sid": "SMSSending",
      "Effect": "Allow",
      "Action": [
        "sms-voice:SendTextMessage"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DynamoDBTranscriptStore",
      "Effect": "Allow",
      "Action": [
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:Query"
      ],
      "Resource": [
        "arn:aws:dynamodb:eu-west-2:395402194296:table/aria-transcript-store",
        "arn:aws:dynamodb:eu-west-2:395402194296:table/aria-transcript-store/index/*"
      ]
    },
    {
      "Sid": "CloudWatchLogs",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:eu-west-2:395402194296:log-group:/aws/lambda/*"
    }
  ]
}
```

---

## Testing

### Test Voice → Chat Transfer

**Step 1: Verify the Lambda works standalone**

In the Lambda console → your `voice_to_chat_transfer` function → **Test**:
```json
{
  "Details": {
    "Parameters": {
      "contactId": "11111111-2222-3333-4444-555555555555",
      "customerId": "CUST-001",
      "authStatus": "unauthenticated",
      "locale": "en-GB",
      "customerPhone": "+447700123456",
      "agentId": "",
      "transferMode": "aria"
    }
  }
}
```
Expected result:
```json
{
  "status": "success",
  "chatContactId": "aaaa-bbbb-...",
  "chatLink": "https://app.meridianbank.co.uk/chat?token=...",
  "smsSent": "true"
}
```

**Step 2: End-to-end test**

1. Make a real call to your Connect phone number
2. Say: *"I'd like to continue this conversation on chat"*
3. Wait for ARIA to respond and set `requestChatTransfer = true`
4. Check that:
   - You receive an SMS within 5–10 seconds
   - The SMS contains a link
   - Clicking the link opens the chat widget
   - The chat shows the voice conversation transcript at the top
   - ARIA continues the conversation without asking you to repeat

**Step 3: Verify DynamoDB entry**

1. AWS Console → DynamoDB → `aria-transcript-store` → **Explore table items**
2. Look for your voice contact ID
3. Verify `transcript` and `summary` fields are populated

### Test Chat → Voice Transfer

1. Open the chat widget on your website
2. Type: *"Can you call me instead?"*
3. Wait for ARIA to respond and set `requestVoiceTransfer = true`
4. Check that:
   - A chat message appears: *"I've requested a callback..."*
   - Your phone rings within 30–60 seconds
   - The voice call connects to ARIA (or an agent)
   - ARIA says something that references the chat conversation without asking you to repeat

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| SMS not received | Customer phone number not in E.164 format | Ensure format is `+447700123456` (not `07700123456`) |
| SMS not received | SMS origination number not verified | Check AWS End User Messaging SMS console — number must be Active |
| Chat link opens blank page | `participantToken` not passed correctly in URL | Check URL format in Lambda; verify `CHAT_WIDGET_URL` env var |
| Chat opens but ARIA unresponsive | Unified flow did not run on the new chat contact | Check that `CONTACT_FLOW_ID` in Lambda matches the unified flow |
| No transcript in chat | Contact Lens not enabled on voice contact | Verify Block 6V of unified flow has real-time analytics enabled |
| No transcript in chat | Lambda retrieved segments after 24h but before DynamoDB storage | Always store in DynamoDB during the Lambda call (not deferred) |
| `ResourceNotFoundException` on `StartChatContact` | Wrong `InstanceId` or `ContactFlowId` | Check environment variables — use the instance ID not the ARN |
| Outbound voice call does not connect | Customer phone number blocked or incorrect | Check phone number format; UK mobile must be `+44...` not `07...` |
| ARIA doesn't see prior transcript | Session injector not updated with cross-channel logic | Add `get_cross_channel_transcript` to `session_injector.py` (Part E) |
| DynamoDB `get_item` returns empty | Item TTL already expired | Increase `ttl` multiplier in Lambda (default 7 days) |
| `AccessDeniedException` on Lambda | Missing IAM permissions | Add IAM policy from the IAM Permissions section |
| Agent does not receive transferred chat | `transferToAgent` attribute not set or wrong UserId | Verify agent UserId in Connect admin → Users → click agent → copy ID from URL |
| Chat history not showing in CCP | `RelatedContactId` not set when creating chat | Verify Lambda passes `RelatedContactId=voice_contact_id` to `StartChatContact` |
| Lambda timeout (8s) exceeded | Contact Lens API slow or transcript is very long | Increase Lambda timeout to 30s; make the Lambda block async in the flow (treat timeout as success) |

---

*This guide is based on:*
- *[Amazon Connect chat persistence](https://docs.aws.amazon.com/connect/latest/adminguide/chat-persistence.html)*
- *[StartChatContact API](https://docs.aws.amazon.com/connect/latest/APIReference/API_StartChatContact.html)*
- *[StartOutboundVoiceContact API](https://docs.aws.amazon.com/connect/latest/APIReference/API_StartOutboundVoiceContact.html)*
- *[Contact Lens API — ListRealtimeContactAnalysisSegments](https://docs.aws.amazon.com/contact-lens/latest/APIReference/API_ListRealtimeContactAnalysisSegments.html)*
- *[Web and mobile chat](https://docs.aws.amazon.com/connect/latest/adminguide/web-and-mobile-chat.html)*
- *[Set up SMS messaging](https://docs.aws.amazon.com/connect/latest/adminguide/setup-sms-messaging.html)*
- *[Add chat to your website](https://docs.aws.amazon.com/connect/latest/adminguide/add-chat-to-website.html)*
