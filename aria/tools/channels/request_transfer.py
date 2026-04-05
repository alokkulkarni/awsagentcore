"""
request_transfer.py
====================
ARIA Connect Channel Transfer Request Tool

Signals the Amazon Connect contact flow to initiate a cross-channel transfer.

HOW IT WORKS
------------
When the customer on a voice call wants to continue on chat (or vice versa),
ARIA calls this tool. The tool calls connect:UpdateContactAttributes to set a
flag attribute on the live contact. The Unified Inbound contact flow checks
this attribute after the Connect Assistant block exits and branches to the
appropriate transfer Lambda (voice_to_chat_transfer or chat_to_voice_transfer).

ARIA must then end its conversational turn naturally and call
escalate_to_human_agent with escalation_reason='channel_transfer' to signal
that the Connect Assistant block should exit, allowing the flow to proceed
to the attribute-check branch.

ENVIRONMENT VARIABLES
---------------------
  INSTANCE_ID   — Amazon Connect instance ID
  AWS_REGION    — AWS region (default: eu-west-2)

Official docs:
  https://docs.aws.amazon.com/connect/latest/APIReference/API_UpdateContactAttributes.html
"""

import logging
import os
from typing import Literal

import boto3
from strands import tool

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

INSTANCE_ID = os.environ.get("INSTANCE_ID", "")
AWS_REGION = os.environ.get("AWS_REGION", "eu-west-2")

_connect_client = None


def _connect():
    global _connect_client
    if _connect_client is None:
        _connect_client = boto3.client("connect", region_name=AWS_REGION)
    return _connect_client


@tool
def request_channel_transfer(
    session_id: str,
    instance_id: str,
    target_channel: Literal["chat", "voice"],
    customer_phone: str = "",
    reason: str = "",
) -> dict:
    """
    Signal the contact flow to transfer this contact to a different channel.
    Call when the customer asks to switch from voice to chat (receive a chat link)
    or from chat to voice (receive a phone callback).

    target_channel: 'chat'  — voice caller wants a chat link delivered by SMS.
                    'voice' — chat customer wants an outbound phone callback.
    customer_phone: Required when target_channel='voice' (E.164 format, e.g. +447700900000).
                    Recommended for target_channel='chat' so the SMS can be delivered.
    reason:         Brief description of the transfer reason (max 200 chars).

    After calling this tool successfully, inform the customer what will happen
    next, then call escalate_to_human_agent with escalation_reason='channel_transfer'
    so the Connect Assistant block exits and the flow can route to the Lambda.
    """
    contact_id = session_id  # session_injector sets sessionId = ContactId
    instance = instance_id or INSTANCE_ID

    if not contact_id:
        return {"status": "error", "message": "session_id is required"}

    if target_channel == "voice" and not customer_phone:
        return {
            "status": "error",
            "message": "customer_phone is required for a voice callback — please ask the customer for their number",
        }

    attr_key = "requestChatTransfer" if target_channel == "chat" else "requestVoiceTransfer"
    attributes = {
        attr_key:        "true",
        "customerPhone": customer_phone,
        "transferReason": reason[:200] if reason else "",
    }

    try:
        _connect().update_contact_attributes(
            InitialContactId=contact_id,
            InstanceId=instance,
            Attributes=attributes,
        )
        logger.info(
            "Channel transfer requested: contactId=%r target=%r phone=%r",
            contact_id, target_channel, customer_phone,
        )
        if target_channel == "chat":
            next_step = (
                "Tell the customer you will send them a secure chat link by SMS "
                "and that the link will be valid for 48 hours. "
                "Then call escalate_to_human_agent with escalation_reason='channel_transfer'."
            )
        else:
            next_step = (
                "Tell the customer to expect a call on the number they provided within "
                "the next few minutes. "
                "Then call escalate_to_human_agent with escalation_reason='channel_transfer'."
            )
        return {
            "status":         "transfer_requested",
            "target_channel": target_channel,
            "next_step":      next_step,
        }
    except Exception as exc:
        logger.error("UpdateContactAttributes failed: %s", exc)
        return {"status": "error", "message": str(exc)}
