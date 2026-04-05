#!/usr/bin/env bash
# =============================================================================
# deploy_mcp_gateway.sh
# =============================================================================
# Deploys ALL ARIA backend infrastructure: the AgentCore MCP Gateway (10 domain
# Lambdas) plus the three support Lambdas required by the Connect contact flow.
#
# What this script deploys
# ────────────────────────
# MCP Gateway tier (10 functions + 1 gateway):
#   aria-banking-mcp-{domain}-{env}   — one per banking domain (10 total)
#   aria-banking-mcp-gateway-{env}    — AgentCore MCP Gateway + 10 targets
#
# Support Lambda tier (3 functions):
#   aria-banking-session-injector-{env}       — injects customer context into
#                                               Q Connect sessions (Block 9)
#   aria-banking-voice-to-chat-transfer-{env} — handles voice→chat SMS deflection
#                                               (Part I of novice guide)
#   aria-banking-chat-to-voice-transfer-{env} — handles chat→voice callback
#                                               (Part I of novice guide)
#
# Supporting infrastructure:
#   aria-transcript-store    — DynamoDB table for cross-channel transcript storage
#   aria-banking-support-lambda-role-{env}    — IAM role for all 3 support Lambdas
#
# Usage:
#   chmod +x scripts/deploy_mcp_gateway.sh
#   ./scripts/deploy_mcp_gateway.sh deploy \
#       --env dev --region eu-west-2 \
#       --instance-id  <connect-instance-id> \
#       --assistant-id <q-connect-assistant-id> \
#       --chat-widget-url https://yourbank.example.com/chat \
#       --sms-number  +441234567890 \
#       --source-phone +441234567890 \
#       --queue-id    <queue-arn-or-id> \
#       --flow-id     <unified-inbound-flow-id>
#
# All --instance-id / --assistant-id / etc. args can also be provided as the
# environment variables CONNECT_INSTANCE_ID, CONNECT_ASSISTANT_ID,
# CHAT_WIDGET_URL, SMS_ORIGINATION_NUMBER, SOURCE_PHONE_NUMBER,
# CONNECT_QUEUE_ID, CONNECT_CONTACT_FLOW_ID.
#
# Prerequisites:
#   - AWS CLI configured with sufficient permissions
#   - Python 3.12 available
#   - pip available
#   - jq available (brew install jq / apt-get install jq)
#   - zip available
#   - The awsagentcore project is your current working directory
#
# What this script does (in order):
#   1.  Creates IAM role for MCP domain Lambda functions
#   2.  Creates DynamoDB table aria-transcript-store (TTL enabled)
#   3.  Creates IAM role for support Lambda functions
#   4.  Deploys session_injector Lambda + Connect resource-based policy
#   5.  Deploys voice_to_chat_transfer Lambda + Connect resource-based policy
#   6.  Deploys chat_to_voice_transfer Lambda + Connect resource-based policy
#   7.  Packages and deploys 10 domain MCP Lambda functions
#   8.  Creates AgentCore MCP Gateway IAM role
#   9.  Creates the AgentCore MCP Gateway
#   10. Adds one MCP target per domain
#   11. Outputs the final MCP endpoint URL and all Lambda ARNs
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve the repository root regardless of where the script is invoked from.
# All relative paths (scripts/lambdas/, scripts/iam/, etc.) are anchored here.
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ---------------------------------------------------------------------------
# Configuration — edit these values to match your environment
# ---------------------------------------------------------------------------
AWS_ACCOUNT_ID="395402194296"
AWS_REGION="${AWS_REGION:-eu-west-2}"
ENV="${ENV:-prod}"
PROJECT="aria-banking"
GATEWAY_NAME="${PROJECT}-mcp-gateway-${ENV}"
LAMBDA_ROLE_NAME="${PROJECT}-mcp-lambda-role-${ENV}"
GATEWAY_ROLE_NAME="${PROJECT}-mcp-gateway-role-${ENV}"

# ARIA AgentCore runtime ARN (already deployed — tools forward to this)
AGENTCORE_RUNTIME_ARN="arn:aws:bedrock-agentcore:${AWS_REGION}:${AWS_ACCOUNT_ID}:runtime/aria_banking_agent-xedQS9HNJe"

# ---------------------------------------------------------------------------
# Support Lambda configuration — override via CLI args or env vars
# ---------------------------------------------------------------------------
# Amazon Connect instance ID  (UUID format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)
CONNECT_INSTANCE_ID="${CONNECT_INSTANCE_ID:-}"
# Q Connect assistant ID (Connect → AI Agent Designer → Assistants)
CONNECT_ASSISTANT_ID="${CONNECT_ASSISTANT_ID:-}"
# ID of the ARIA Unified Inbound contact flow (needed by transfer Lambdas)
CONNECT_CONTACT_FLOW_ID="${CONNECT_CONTACT_FLOW_ID:-}"
# ARN or ID of the Connect queue for outbound voice callbacks
CONNECT_QUEUE_ID="${CONNECT_QUEUE_ID:-}"
# Base URL for the chat widget (e.g. https://yourbank.example.com/chat)
CHAT_WIDGET_URL="${CHAT_WIDGET_URL:-}"
# SMS-capable phone number in E.164 format for voice→chat notifications
SMS_ORIGINATION_NUMBER="${SMS_ORIGINATION_NUMBER:-}"
# Connect phone number in E.164 format for chat→voice outbound calls
SOURCE_PHONE_NUMBER="${SOURCE_PHONE_NUMBER:-}"
# CRM API endpoint (leave empty to use stub data)
CRM_API_ENDPOINT="${CRM_API_ENDPOINT:-}"
# DynamoDB table name for cross-channel transcript storage
TRANSCRIPT_TABLE="aria-transcript-store"

# Support Lambda resource names (derived — do not edit directly)
SUPPORT_LAMBDA_ROLE_NAME="${PROJECT}-support-lambda-role-${ENV}"
SUPPORT_LAMBDA_ROLE_ARN=""   # populated by create_support_lambda_role
SESSION_INJECTOR_NAME="${PROJECT}-session-injector-${ENV}"
SESSION_INJECTOR_ARN=""      # populated by deploy_session_injector
VOICE_TO_CHAT_LAMBDA_NAME="${PROJECT}-voice-to-chat-transfer-${ENV}"
VOICE_TO_CHAT_ARN=""         # populated by deploy_transfer_lambdas
CHAT_TO_VOICE_LAMBDA_NAME="${PROJECT}-chat-to-voice-transfer-${ENV}"
CHAT_TO_VOICE_ARN=""         # populated by deploy_transfer_lambdas

# Colours for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Colour

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()    { echo -e "${BLUE}[INFO]${NC}  $*" >&2; }
ok()     { echo -e "${GREEN}[OK]${NC}    $*" >&2; }
warn()   { echo -e "${YELLOW}[WARN]${NC}  $*" >&2; }
error()  { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()    { error "$*"; exit 1; }

check_prereqs() {
  log "Checking prerequisites..."
  command -v aws    >/dev/null 2>&1 || die "aws CLI not found. Install from https://aws.amazon.com/cli/"
  command -v python3 >/dev/null 2>&1 || die "python3 not found"
  command -v pip3   >/dev/null 2>&1 || die "pip3 not found"
  command -v jq     >/dev/null 2>&1 || die "jq not found. Install with: brew install jq"
  command -v zip    >/dev/null 2>&1 || die "zip not found"
  python3 -c "import boto3" 2>/dev/null || die "boto3 not installed. Run: pip3 install boto3"

  # Verify AWS credentials
  aws sts get-caller-identity --region "${AWS_REGION}" >/dev/null 2>&1 \
    || die "AWS credentials not configured or no access. Run: aws configure"

  ACTUAL_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
  [[ "$ACTUAL_ACCOUNT" == "$AWS_ACCOUNT_ID" ]] \
    || warn "Account mismatch: expected ${AWS_ACCOUNT_ID}, got ${ACTUAL_ACCOUNT}. Proceeding anyway."

  ok "Prerequisites satisfied"
}

# ---------------------------------------------------------------------------
# Step 1 — Create Lambda IAM Role
# ---------------------------------------------------------------------------
create_lambda_role() {
  log "Creating Lambda IAM role: ${LAMBDA_ROLE_NAME}..."

  # Check if role already exists
  if aws iam get-role --role-name "${LAMBDA_ROLE_NAME}" >/dev/null 2>&1; then
    ok "Lambda role already exists — skipping creation"
    LAMBDA_ROLE_ARN=$(aws iam get-role --role-name "${LAMBDA_ROLE_NAME}" \
      --query 'Role.Arn' --output text)
    return 0
  fi

  # Trust policy
  TRUST_POLICY=$(cat <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "lambda.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
EOF
)

  aws iam create-role \
    --role-name "${LAMBDA_ROLE_NAME}" \
    --assume-role-policy-document "${TRUST_POLICY}" \
    --description "IAM role for ARIA MCP Gateway Lambda functions" \
    --region "${AWS_REGION}" >/dev/null

  # Basic Lambda execution (CloudWatch Logs)
  aws iam attach-role-policy \
    --role-name "${LAMBDA_ROLE_NAME}" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

  # Inline policy: allow calling the existing ARIA AgentCore runtime
  INLINE_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["bedrock-agentcore:InvokeAgentRuntime"],
      "Resource": "${AGENTCORE_RUNTIME_ARN}"
    }
  ]
}
EOF
)
  aws iam put-role-policy \
    --role-name "${LAMBDA_ROLE_NAME}" \
    --policy-name aria-mcp-lambda-policy \
    --policy-document "${INLINE_POLICY}"

  LAMBDA_ROLE_ARN=$(aws iam get-role --role-name "${LAMBDA_ROLE_NAME}" \
    --query 'Role.Arn' --output text)

  # IAM propagation delay
  log "Waiting 15 seconds for IAM role to propagate..."
  sleep 15

  ok "Lambda role created: ${LAMBDA_ROLE_ARN}"
}

# ---------------------------------------------------------------------------
# Step 2 — Build Lambda package for a domain
# ---------------------------------------------------------------------------
build_lambda_package() {
  local domain="$1"
  local build_dir="/tmp/aria-mcp-build-${domain}"

  log "Building Lambda package for domain: ${domain}..."

  rm -rf "${build_dir}" && mkdir -p "${build_dir}"

  # Write the Lambda handler for this domain
  cat > "${build_dir}/handler.py" <<PYTHON
"""
ARIA MCP Gateway Lambda — domain: ${domain}

This Lambda acts as an MCP tool server for the '${domain}' domain.
It receives tool invocations from the AgentCore MCP Gateway and
dispatches them to the appropriate ARIA business logic.

In a production environment, replace the stub implementations below
with calls to your actual banking backend APIs or to the ARIA
AgentCore runtime.
"""
import json
import logging
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DOMAIN = "${domain}"


def lambda_handler(event, context):
    """
    Entry point for MCP Gateway tool invocations.
    
    The AgentCore MCP Gateway sends requests in the format:
    {
        "tool_name": "get_account_details",
        "tool_input": {"customer_id": "C123", "account_number": "4821", "query_subtype": "balance"}
    }
    
    Returns:
    {
        "result": <tool result object>
    }
    """
    logger.info(f"MCP invocation [{DOMAIN}]: {json.dumps(event)}")

    tool_name  = event.get("tool_name", "")
    tool_input = event.get("tool_input", event.get("input", {}))

    # Parse stringified inputs if needed (MCP sends all params as strings)
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except json.JSONDecodeError:
            pass

    # Route to the correct handler
    handler_fn = TOOL_HANDLERS.get(tool_name)
    if not handler_fn:
        logger.warning(f"Unknown tool: {tool_name}")
        return {
            "result": {
                "error": f"Tool '{tool_name}' not found in domain '{DOMAIN}'",
                "available_tools": list(TOOL_HANDLERS.keys())
            }
        }

    try:
        result = handler_fn(tool_input)
        return {"result": result}
    except Exception as exc:
        logger.exception(f"Tool {tool_name} raised an exception")
        return {
            "result": {
                "error": str(exc),
                "tool": tool_name
            }
        }


# ---------------------------------------------------------------------------
# Domain-specific tool handlers
# Each function receives the tool_input dict and returns a dict result.
# Replace these stubs with real banking API calls.
# ---------------------------------------------------------------------------

TOOL_HANDLERS = {}  # populated at module load below


def _register(tool_name):
    """Decorator to register a function as a tool handler."""
    def decorator(fn):
        TOOL_HANDLERS[tool_name] = fn
        return fn
    return decorator

PYTHON

  # Append domain-specific handlers
  case "${domain}" in

    auth)
      cat >> "${build_dir}/handler.py" <<'PYTHON'

@_register("verify_customer_identity")
def verify_customer_identity(inp):
    # TODO: Replace with CRM identity validation API call
    customer_id = inp.get("requested_customer_id", "")
    return {
        "identity_match": bool(customer_id),
        "risk_score": 10,
        "verification_ref": f"VERIFY-{customer_id}"
    }

@_register("initiate_customer_auth")
def initiate_customer_auth(inp):
    # TODO: Replace with authentication service call
    return {
        "auth_session_id": f"AUTH-{inp.get('customer_id', '')}",
        "auth_method": inp.get("auth_method", "voice_knowledge_based"),
        "challenges_required": ["dob", "mobile_last_four"],
        "attempts_allowed": 3
    }

@_register("validate_customer_auth")
def validate_customer_auth(inp):
    # TODO: Replace with authentication validation service call
    return {
        "auth_passed": True,
        "attempts_remaining": 2,
        "auth_level": "full",
        "auth_ref": f"AUTH-PASS-{inp.get('customer_id', '')}"
    }

@_register("cross_validate_session_identity")
def cross_validate_session_identity(inp):
    # TODO: Replace with session identity cross-check
    header_id = inp.get("header_customer_id", "")
    auth_id   = inp.get("auth_verified_customer_id", "")
    match = header_id == auth_id if header_id and auth_id else True
    return {
        "identity_consistent": match,
        "validation_ref": f"XVAL-{inp.get('session_id', '')}"
    }
PYTHON
      ;;

    account)
      cat >> "${build_dir}/handler.py" <<'PYTHON'

@_register("get_account_details")
def get_account_details(inp):
    # TODO: Replace with core banking API call
    subtype  = inp.get("query_subtype", "balance")
    last_four = inp.get("account_number", "****")
    stub = {
        "account_last_four": last_four,
        "account_type": "Current Account",
        "sort_code": "20-**-**",
    }
    if subtype == "balance":
        stub.update({"balance": 2450.75, "available_balance": 2200.00, "overdraft_limit": 500.00})
    elif subtype == "transactions":
        stub["transactions"] = [
            {"date": "2026-03-31", "description": "TESCO STORES", "amount": -42.50, "balance": 2450.75},
            {"date": "2026-03-30", "description": "SALARY MERIDIAN", "amount": 2800.00, "balance": 2493.25},
            {"date": "2026-03-29", "description": "DIRECT DEBIT UTILITIES", "amount": -89.99, "balance": -306.75},
        ]
    elif subtype == "statement":
        stub["statement_url"] = "https://online.meridianbank.co.uk/statements/latest"
        stub["message"] = "Your latest statement is available in online banking."
    elif subtype == "standing_orders":
        stub["standing_orders"] = [
            {"payee": "Council Tax", "amount": 145.00, "frequency": "Monthly", "next_payment": "2026-04-01"},
            {"payee": "Gym Membership", "amount": 35.00, "frequency": "Monthly", "next_payment": "2026-04-05"},
        ]
    return stub
PYTHON
      ;;

    customer)
      cat >> "${build_dir}/handler.py" <<'PYTHON'

@_register("get_customer_details")
def get_customer_details(inp):
    # TODO: Replace with CRM API call
    customer_id = inp.get("customer_id", "")
    return {
        "customer_id": customer_id,
        "preferred_name": "Alex",
        "full_name": "Alex Johnson",
        "email": "a***@example.com",
        "products": [
            {"type": "current_account", "ref_last_four": "4821", "nickname": "main account"},
            {"type": "credit_card",     "ref_last_four": "6619", "nickname": "Visa card"},
            {"type": "mortgage",        "ref_last_four": "3392", "nickname": "home loan"},
        ],
        "vulnerability_flags": [],
        "preferred_contact": "mobile"
    }
PYTHON
      ;;

    debit-card)
      cat >> "${build_dir}/handler.py" <<'PYTHON'

@_register("get_debit_card_details")
def get_debit_card_details(inp):
    # TODO: Replace with card management API call
    subtype   = inp.get("query_subtype", "status")
    last_four = inp.get("card_last_four", "****")
    stub = {"card_last_four": last_four, "card_type": "Visa Debit", "status": "active"}
    if subtype == "limits":
        stub.update({"daily_atm_limit": 500, "daily_purchase_limit": 3000, "contactless_limit": 100})
    elif subtype == "transactions":
        stub["transactions"] = [
            {"date": "2026-03-31", "description": "SAINSBURYS", "amount": -23.40},
            {"date": "2026-03-30", "description": "COSTA COFFEE", "amount": -4.20},
        ]
    return stub

@_register("block_debit_card")
def block_debit_card(inp):
    # TODO: Replace with card management API call
    last_four = inp.get("card_last_four", "****")
    reason    = inp.get("reason", "lost")
    replacement = inp.get("request_replacement", "true").lower() == "true"
    return {
        "card_last_four": last_four,
        "block_status": "blocked",
        "block_reason": reason,
        "block_ref": f"BLOCK-{last_four}-{reason[:3].upper()}",
        "replacement_ordered": replacement,
        "replacement_delivery": "5-7 working days" if replacement else None
    }
PYTHON
      ;;

    credit-card)
      cat >> "${build_dir}/handler.py" <<'PYTHON'

@_register("get_credit_card_details")
def get_credit_card_details(inp):
    # TODO: Replace with credit card API call
    subtype   = inp.get("query_subtype", "balance")
    last_four = inp.get("card_last_four", "****")
    stub = {"card_last_four": last_four, "card_type": "Visa Credit", "status": "active"}
    if subtype == "balance":
        stub.update({"balance": 1240.50, "credit_limit": 5000.00, "available_credit": 3759.50})
    elif subtype == "available_credit":
        stub.update({"available_credit": 3759.50, "credit_limit": 5000.00})
    elif subtype == "minimum_payment":
        stub.update({"minimum_payment": 25.00, "due_date": "2026-04-22", "statement_balance": 1240.50})
    elif subtype == "transactions":
        stub["transactions"] = [
            {"date": "2026-03-31", "description": "AMAZON", "amount": -89.99},
            {"date": "2026-03-28", "description": "NETFLIX", "amount": -17.99},
        ]
    return stub
PYTHON
      ;;

    mortgage)
      cat >> "${build_dir}/handler.py" <<'PYTHON'

@_register("get_mortgage_details")
def get_mortgage_details(inp):
    # TODO: Replace with mortgage system API call
    subtype = inp.get("query_subtype", "balance")
    ref_last_four = inp.get("mortgage_reference", "****")
    stub = {"mortgage_ref_last_four": ref_last_four, "product": "2-Year Fixed"}
    if subtype == "balance":
        stub.update({"outstanding_balance": 187450.00, "original_loan": 225000.00})
    elif subtype == "rate":
        stub.update({"current_rate": "4.99%", "rate_type": "Fixed", "fixed_until": "2026-11-30"})
    elif subtype == "monthly_payment":
        stub.update({"monthly_payment": 1245.80, "next_payment_date": "2026-04-01"})
    elif subtype == "overpayment_allowance":
        stub.update({"annual_overpayment_allowance": 22500.00, "overpaid_this_year": 0.00})
    elif subtype == "term":
        stub.update({"term_years": 25, "years_remaining": 22, "end_date": "2048-01-01"})
    return stub
PYTHON
      ;;

    products)
      cat >> "${build_dir}/handler.py" <<'PYTHON'

@_register("get_product_catalogue")
def get_product_catalogue(inp):
    # TODO: Replace with product catalogue API call
    category = inp.get("product_category", "current_accounts")
    catalogue = {
        "current_accounts": [
            {"name": "Meridian Select", "tagline": "Everyday banking, rewarding you more", "features": ["0% arranged overdraft up to £500", "1% cashback on bills", "24/7 mobile app"]},
            {"name": "Meridian Classic", "tagline": "Simple, reliable banking", "features": ["No monthly fee", "Debit card included", "Online and mobile banking"]}
        ],
        "savings": [
            {"name": "Meridian Instant Access", "tagline": "Save today, access whenever", "features": ["4.20% AER variable", "No notice period", "Linked to your current account"]}
        ],
        "credit_cards": [
            {"name": "Meridian Rewards Visa", "tagline": "Every purchase earns you more", "features": ["1.5% cashback", "No foreign transaction fee", "0% for 12 months on purchases"]}
        ]
    }
    return {"category": category, "products": catalogue.get(category, [])}

@_register("analyse_spending")
def analyse_spending(inp):
    # TODO: Replace with transaction analytics API call
    source_type    = inp.get("source_type", "current_account")
    ref_last_four  = inp.get("source_ref_last_four", "****")
    period         = inp.get("period", "last_2_months")
    category_filter = inp.get("category_filter", "")
    return {
        "source_type": source_type,
        "source_ref_last_four": ref_last_four,
        "period": period,
        "total_spent": 1847.32,
        "category_filter": category_filter or "all",
        "top_categories": [
            {"category": "groceries", "total": 423.50, "transactions": 12},
            {"category": "eating_out", "total": 187.20, "transactions": 8},
            {"category": "utilities", "total": 145.00, "transactions": 2}
        ],
        "transactions": [
            {"date": "2026-03-31", "merchant": "TESCO", "category": "groceries", "amount": 42.50},
            {"date": "2026-03-30", "merchant": "COSTA", "category": "eating_out", "amount": 4.20},
            {"date": "2026-03-29", "merchant": "NETFLIX", "category": "entertainment", "amount": 17.99},
        ]
    }
PYTHON
      ;;

    pii)
      cat >> "${build_dir}/handler.py" <<'PYTHON'
import re
import uuid

# In-memory PII vault — replace with AWS Secrets Manager or DynamoDB in production
_VAULT = {}

@_register("pii_detect_and_redact")
def pii_detect_and_redact(inp):
    text     = inp.get("message", "")
    session  = inp.get("session_id", "default")
    pii_map  = {}
    redacted = text

    patterns = {
        "account_number": r'\b\d{8}\b',
        "sort_code":      r'\b\d{2}[-–]\d{2}[-–]\d{2}\b',
        "card_number":    r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b',
        "mobile":         r'\b0[0-9]{10}\b',
        "dob":            r'\b\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b',
    }

    for pii_type, pattern in patterns.items():
        matches = re.findall(pattern, text)
        if matches:
            for m in matches:
                token = f"{pii_type.upper()}_{uuid.uuid4().hex[:6]}"
                pii_map[token] = m
                redacted = redacted.replace(m, f"[{pii_type}]")

    return {
        "redacted_text": redacted,
        "pii_detected": bool(pii_map),
        "pii_map": pii_map,
        "pii_types_found": list(set(k.rsplit("_", 1)[0] for k in pii_map.keys()))
    }

@_register("pii_vault_store")
def pii_vault_store(inp):
    session = inp.get("session_id", "default")
    pii_map = inp.get("pii_map", {})
    if isinstance(pii_map, str):
        import json
        try:
            pii_map = json.loads(pii_map)
        except Exception:
            pii_map = {}
    if session not in _VAULT:
        _VAULT[session] = {}
    vault_refs = {}
    for token, value in pii_map.items():
        vault_ref = f"vault://{session}/{token}"
        _VAULT[session][token] = value
        vault_refs[token] = vault_ref
    return {"vault_status": "stored", "vault_refs": vault_refs}

@_register("pii_vault_retrieve")
def pii_vault_retrieve(inp):
    session    = inp.get("session_id", "default")
    vault_refs_raw = inp.get("vault_refs", "[]")
    if isinstance(vault_refs_raw, str):
        import json
        try:
            vault_refs = json.loads(vault_refs_raw)
        except Exception:
            vault_refs = []
    else:
        vault_refs = vault_refs_raw
    results = {}
    session_data = _VAULT.get(session, {})
    for ref in vault_refs:
        token = ref.split("/")[-1]
        results[ref] = session_data.get(token, "[NOT_FOUND]")
    return {"retrieved": results, "purpose": inp.get("purpose", "")}

@_register("pii_vault_purge")
def pii_vault_purge(inp):
    session = inp.get("session_id", "default")
    if session in _VAULT:
        del _VAULT[session]
    return {"purge_status": "purged", "session_id": session, "reason": inp.get("purge_reason", "")}
PYTHON
      ;;

    escalation)
      cat >> "${build_dir}/handler.py" <<'PYTHON'
import uuid
from datetime import datetime

@_register("generate_transcript_summary")
def generate_transcript_summary(inp):
    # TODO: Replace with transcript service API call
    session = inp.get("session_id", "")
    return {
        "session_id": session,
        "summary": "Customer called to enquire about account balance and card status.",
        "intent": "account_inquiry",
        "auth_status": "authenticated",
        "products_discussed": ["current_account"],
        "actions_taken": [],
        "format": inp.get("summary_format", "structured")
    }

@_register("escalate_to_human_agent")
def escalate_to_human_agent(inp):
    # TODO: Replace with contact centre routing API call
    session     = inp.get("session_id", "")
    customer_id = inp.get("customer_id", "")
    reason      = inp.get("escalation_reason", "customer_request")
    priority    = inp.get("priority", "standard")
    handoff_ref = f"HO-{datetime.now().strftime('%Y%m%d')}-{customer_id[:6].upper()}"
    return {
        "handoff_status": "accepted",
        "handoff_ref": handoff_ref,
        "agent_id": f"AGT-{uuid.uuid4().hex[:5].upper()}",
        "estimated_wait_seconds": 30,
        "escalation_reason": reason,
        "priority": priority,
        "queue": "ARIA-Escalations"
    }
PYTHON
      ;;

    knowledge)
      cat >> "${build_dir}/handler.py" <<'PYTHON'

@_register("search_knowledge_base")
def search_knowledge_base(inp):
    # TODO: Replace with Amazon Bedrock Knowledge Base API call
    query = inp.get("query", "")
    return {
        "query": query,
        "results": [
            {
                "title": "How to block a lost or stolen card",
                "content": "You can block your card immediately by calling 0161 900 9000 or through the Meridian Bank mobile app. A replacement card will arrive within 5-7 working days.",
                "relevance_score": 0.92
            },
            {
                "title": "Account statement access",
                "content": "Statements are available to download in PDF format from online banking or the mobile app. Paper statements are sent monthly.",
                "relevance_score": 0.78
            }
        ],
        "total_results": 2
    }

@_register("get_feature_parity")
def get_feature_parity(inp):
    # TODO: Replace with feature registry API call
    feature_area = inp.get("feature_area", "")
    return {
        "feature_area": feature_area,
        "available_channels": ["voice", "chat", "mobile", "web"],
        "channel_notes": {
            "voice": "Full self-service available",
            "chat": "Full self-service available",
            "mobile": "Available in the Meridian Bank app",
            "web": "Available at meridianbank.co.uk"
        }
    }
PYTHON
      ;;

    *)
      cat >> "${build_dir}/handler.py" <<PYTHON

# No specific handlers registered for domain: ${domain}
# Add tool handlers above using the @_register("tool_name") decorator.
PYTHON
      ;;
  esac

  # Package
  cd "${build_dir}"
  zip -r "aria-mcp-${domain}.zip" handler.py >/dev/null
  cd - >/dev/null

  echo "${build_dir}/aria-mcp-${domain}.zip"
}

# ---------------------------------------------------------------------------
# Step 3 — Deploy a Lambda function
# ---------------------------------------------------------------------------
deploy_lambda() {
  local domain="$1"
  local zip_path="$2"
  local function_name="${PROJECT}-mcp-${domain}-${ENV}"

  log "Deploying Lambda: ${function_name}..."

  if aws lambda get-function --function-name "${function_name}" \
      --region "${AWS_REGION}" >/dev/null 2>&1; then
    # Update existing function
    aws lambda update-function-code \
      --function-name "${function_name}" \
      --zip-file "fileb://${zip_path}" \
      --region "${AWS_REGION}" >/dev/null
    ok "Lambda updated: ${function_name}"
  else
    # Create new function
    aws lambda create-function \
      --function-name "${function_name}" \
      --runtime python3.12 \
      --role "${LAMBDA_ROLE_ARN}" \
      --handler handler.lambda_handler \
      --zip-file "fileb://${zip_path}" \
      --timeout 30 \
      --memory-size 256 \
      --description "ARIA MCP Gateway — ${domain} domain tools" \
      --region "${AWS_REGION}" \
      --environment "Variables={ARIA_DOMAIN=${domain},ARIA_ENV=${ENV}}" >/dev/null

    ok "Lambda created: ${function_name}"
  fi

  # Return the Lambda ARN
  aws lambda get-function --function-name "${function_name}" \
    --region "${AWS_REGION}" \
    --query 'Configuration.FunctionArn' --output text
}

# ---------------------------------------------------------------------------
# Step 4 — Create DynamoDB table for cross-channel transcript storage
# ---------------------------------------------------------------------------
create_dynamodb_table() {
  log "Creating DynamoDB table: ${TRANSCRIPT_TABLE}..."

  if aws dynamodb describe-table \
      --table-name "${TRANSCRIPT_TABLE}" \
      --region "${AWS_REGION}" >/dev/null 2>&1; then
    ok "DynamoDB table already exists — skipping: ${TRANSCRIPT_TABLE}"
  else
    aws dynamodb create-table \
      --region "${AWS_REGION}" \
      --table-name "${TRANSCRIPT_TABLE}" \
      --attribute-definitions AttributeName=contactId,AttributeType=S \
      --key-schema AttributeName=contactId,KeyType=HASH \
      --billing-mode PAY_PER_REQUEST \
      --tags Key=Project,Value="${PROJECT}" Key=Environment,Value="${ENV}" \
      >/dev/null

    # Wait for the table to reach ACTIVE status before enabling TTL
    log "Waiting for DynamoDB table to become ACTIVE..."
    aws dynamodb wait table-active \
      --table-name "${TRANSCRIPT_TABLE}" \
      --region "${AWS_REGION}"

    ok "DynamoDB table created: ${TRANSCRIPT_TABLE}"
  fi

  # Always check and enable TTL — idempotent whether table is new or pre-existing
  local ttl_status
  ttl_status=$(aws dynamodb describe-time-to-live \
    --table-name "${TRANSCRIPT_TABLE}" \
    --region "${AWS_REGION}" \
    --query 'TimeToLiveDescription.TimeToLiveStatus' \
    --output text 2>/dev/null || echo "DISABLED")

  if [[ "${ttl_status}" == "ENABLED" || "${ttl_status}" == "ENABLING" ]]; then
    ok "DynamoDB TTL already enabled (status: ${ttl_status}): ${TRANSCRIPT_TABLE}"
  else
    log "Enabling TTL on DynamoDB table (attribute: ttl)..."
    aws dynamodb update-time-to-live \
      --region "${AWS_REGION}" \
      --table-name "${TRANSCRIPT_TABLE}" \
      --time-to-live-specification "Enabled=true,AttributeName=ttl" \
      >/dev/null
    ok "DynamoDB TTL enabled: ${TRANSCRIPT_TABLE}"
  fi
}

# ---------------------------------------------------------------------------
# Step 5 — Create shared IAM role for all support Lambda functions
#
# One role is shared by: session_injector, voice_to_chat_transfer,
# chat_to_voice_transfer.  It grants the union of all their permissions.
# ---------------------------------------------------------------------------
create_support_lambda_role() {
  log "Creating Support Lambda IAM role: ${SUPPORT_LAMBDA_ROLE_NAME}..."

  if aws iam get-role --role-name "${SUPPORT_LAMBDA_ROLE_NAME}" >/dev/null 2>&1; then
    ok "Support Lambda role already exists — skipping"
    SUPPORT_LAMBDA_ROLE_ARN=$(aws iam get-role \
      --role-name "${SUPPORT_LAMBDA_ROLE_NAME}" \
      --query 'Role.Arn' --output text)
    return 0
  fi

  local TRUST_POLICY
  TRUST_POLICY=$(cat <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "lambda.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
EOF
)

  aws iam create-role \
    --role-name "${SUPPORT_LAMBDA_ROLE_NAME}" \
    --assume-role-policy-document "${TRUST_POLICY}" \
    --description "IAM role for ARIA support Lambdas (session injector + channel transfers)" \
    >/dev/null

  aws iam attach-role-policy \
    --role-name "${SUPPORT_LAMBDA_ROLE_NAME}" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

  local INLINE_POLICY
  INLINE_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ConnectReadWrite",
      "Effect": "Allow",
      "Action": [
        "connect:DescribeContact",
        "connect:GetContactAttributes",
        "connect:UpdateContactAttributes",
        "connect:StartChatContact",
        "connect:StartOutboundVoiceContact",
        "connect:ListRealtimeContactAnalysisSegmentsV2"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ContactLens",
      "Effect": "Allow",
      "Action": [
        "connect-contact-lens:ListRealtimeContactAnalysisSegments"
      ],
      "Resource": "*"
    },
    {
      "Sid": "QConnect",
      "Effect": "Allow",
      "Action": [
        "qconnect:UpdateSessionData",
        "wisdom:UpdateSessionData"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DynamoDB",
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem"
      ],
      "Resource": "arn:aws:dynamodb:${AWS_REGION}:${AWS_ACCOUNT_ID}:table/${TRANSCRIPT_TABLE}"
    },
    {
      "Sid": "SMSVoice",
      "Effect": "Allow",
      "Action": [
        "sms-voice:SendTextMessage"
      ],
      "Resource": "*"
    }
  ]
}
EOF
)

  aws iam put-role-policy \
    --role-name "${SUPPORT_LAMBDA_ROLE_NAME}" \
    --policy-name "aria-support-lambda-policy" \
    --policy-document "${INLINE_POLICY}"

  SUPPORT_LAMBDA_ROLE_ARN=$(aws iam get-role \
    --role-name "${SUPPORT_LAMBDA_ROLE_NAME}" \
    --query 'Role.Arn' --output text)

  log "Waiting 15 seconds for Support Lambda IAM role to propagate..."
  sleep 15

  ok "Support Lambda role created: ${SUPPORT_LAMBDA_ROLE_ARN}"
}

# ---------------------------------------------------------------------------
# Step 6 — Package and deploy a support Lambda from a source .py file
#
# Unlike the MCP domain Lambdas (which have a generated handler), support
# Lambdas are deployed directly from their source file, renamed to
# lambda_function.py, with handler = lambda_function.lambda_handler.
#
# Arguments:
#   $1 — fully-qualified function name
#   $2 — path to the source .py file
#   $3 — human-readable description
#   $4 — JSON string for --environment Variables={...}
#   $5 — (optional) timeout in seconds (default: 60)
# Prints the deployed Lambda ARN to stdout.
# ---------------------------------------------------------------------------
deploy_support_lambda() {
  local function_name="$1"
  local source_file="$2"
  local description="$3"
  local env_vars="$4"
  local timeout="${5:-60}"

  log "Deploying support Lambda: ${function_name}..."

  local tmpdir
  tmpdir=$(mktemp -d)
  local zipfile="${tmpdir}/${function_name}.zip"

  cp "${source_file}" "${tmpdir}/lambda_function.py"
  (cd "${tmpdir}" && zip -q "${zipfile}" lambda_function.py)

  if aws lambda get-function \
      --function-name "${function_name}" \
      --region "${AWS_REGION}" >/dev/null 2>&1; then
    # Update code
    aws lambda update-function-code \
      --function-name "${function_name}" \
      --zip-file "fileb://${zipfile}" \
      --region "${AWS_REGION}" >/dev/null
    # Update env vars in case config changed
    aws lambda update-function-configuration \
      --function-name "${function_name}" \
      --environment "${env_vars}" \
      --region "${AWS_REGION}" >/dev/null
    ok "Lambda updated: ${function_name}"
  else
    aws lambda create-function \
      --function-name "${function_name}" \
      --runtime python3.12 \
      --role "${SUPPORT_LAMBDA_ROLE_ARN}" \
      --handler lambda_function.lambda_handler \
      --zip-file "fileb://${zipfile}" \
      --timeout "${timeout}" \
      --memory-size 256 \
      --description "${description}" \
      --region "${AWS_REGION}" \
      --environment "${env_vars}" \
      --tags "Project=${PROJECT},Environment=${ENV}" \
      >/dev/null
    ok "Lambda created: ${function_name}"
  fi

  rm -rf "${tmpdir}"

  aws lambda get-function \
    --function-name "${function_name}" \
    --region "${AWS_REGION}" \
    --query 'Configuration.FunctionArn' --output text
}

# ---------------------------------------------------------------------------
# Step 6a — Add a Connect resource-based policy to a Lambda function
#
# Amazon Connect requires lambda:InvokeFunction from connect.amazonaws.com
# before it can call a Lambda from a contact flow.  This is in addition to
# the Lambda execution role permissions granted above.
# ---------------------------------------------------------------------------
add_connect_resource_policy() {
  local function_name="$1"
  local statement_id="${function_name}-connect-invoke"

  log "Adding Connect resource-based policy to: ${function_name}..."

  # Remove an existing statement first so the call is idempotent
  aws lambda remove-permission \
    --function-name "${function_name}" \
    --statement-id "${statement_id}" \
    --region "${AWS_REGION}" >/dev/null 2>&1 || true

  aws lambda add-permission \
    --function-name "${function_name}" \
    --statement-id "${statement_id}" \
    --action lambda:InvokeFunction \
    --principal connect.amazonaws.com \
    --source-account "${AWS_ACCOUNT_ID}" \
    --region "${AWS_REGION}" >/dev/null

  ok "Connect resource policy added: ${function_name}"
}

# ---------------------------------------------------------------------------
# Step 6b — Deploy the session_injector Lambda
#
# Injects customer context (name, products, auth status, prior summary) into
# Q Connect sessions.  Runs immediately after Block 8 (Connect assistant) in
# the Unified Inbound contact flow (Block 9).
# ---------------------------------------------------------------------------
deploy_session_injector() {
  local source_file="${REPO_ROOT}/scripts/lambdas/session_injector.py"
  [[ -f "${source_file}" ]] || die "Session injector source not found: ${source_file}"

  if [[ -z "${CONNECT_ASSISTANT_ID}" ]]; then
    warn "CONNECT_ASSISTANT_ID is not set. The session injector will deploy but ARIA cannot"
    warn "personalise sessions until ASSISTANT_ID is configured in its environment variables."
    warn "Re-run with --assistant-id <id> after noting the Q Connect assistant ID from Part D.1"
    warn "of the novice guide."
  fi

  local env_vars
  env_vars=$(cat <<EOF
{"Variables":{"ASSISTANT_ID":"${CONNECT_ASSISTANT_ID}","CRM_API_ENDPOINT":"${CRM_API_ENDPOINT}","TRANSCRIPT_TABLE_NAME":"${TRANSCRIPT_TABLE}","INSTANCE_ID":"${CONNECT_INSTANCE_ID}"}}
EOF
)

  SESSION_INJECTOR_ARN=$(deploy_support_lambda \
    "${SESSION_INJECTOR_NAME}" \
    "${source_file}" \
    "ARIA session injector — injects customer context into Q Connect sessions" \
    "${env_vars}" \
    60)

  add_connect_resource_policy "${SESSION_INJECTOR_NAME}"
  ok "Session injector deployed: ${SESSION_INJECTOR_ARN}"
}

# ---------------------------------------------------------------------------
# Step 6c — Deploy voice_to_chat_transfer and chat_to_voice_transfer Lambdas
#
# voice_to_chat_transfer: called when ARIA sets requestChatTransfer=true.
#   Retrieves the Contact Lens voice transcript, starts a new chat contact,
#   and sends the customer an SMS with a deep-link to the chat widget.
#
# chat_to_voice_transfer: called when ARIA sets requestVoiceTransfer=true.
#   Retrieves the chat transcript via Contact Lens V2 API, then initiates an
#   outbound voice callback via StartOutboundVoiceContact.
# ---------------------------------------------------------------------------
deploy_transfer_lambdas() {
  # ── voice_to_chat_transfer ───────────────────────────────────────────────
  local v2c_source="${REPO_ROOT}/scripts/lambdas/voice_to_chat_transfer.py"
  [[ -f "${v2c_source}" ]] || die "voice_to_chat_transfer source not found: ${v2c_source}"

  [[ -z "${CONNECT_INSTANCE_ID}" ]] \
    && warn "CONNECT_INSTANCE_ID not set — transfer Lambdas will deploy but will fail at runtime."
  [[ -z "${SMS_ORIGINATION_NUMBER}" ]] \
    && warn "SMS_ORIGINATION_NUMBER not set — voice→chat SMS deflection will not send messages."
  [[ -z "${CHAT_WIDGET_URL}" ]] \
    && warn "CHAT_WIDGET_URL not set — the SMS deep-link will be empty."

  local v2c_env
  v2c_env=$(cat <<EOF
{"Variables":{"INSTANCE_ID":"${CONNECT_INSTANCE_ID}","CONTACT_FLOW_ID":"${CONNECT_CONTACT_FLOW_ID}","CHAT_WIDGET_URL":"${CHAT_WIDGET_URL}","SMS_ORIGINATION_NUMBER":"${SMS_ORIGINATION_NUMBER}","DYNAMODB_TABLE":"${TRANSCRIPT_TABLE}"}}
EOF
)

  VOICE_TO_CHAT_ARN=$(deploy_support_lambda \
    "${VOICE_TO_CHAT_LAMBDA_NAME}" \
    "${v2c_source}" \
    "ARIA voice→chat transfer — creates chat contact and sends SMS deep-link" \
    "${v2c_env}" \
    60)

  add_connect_resource_policy "${VOICE_TO_CHAT_LAMBDA_NAME}"
  ok "voice_to_chat_transfer deployed: ${VOICE_TO_CHAT_ARN}"

  # ── chat_to_voice_transfer ───────────────────────────────────────────────
  local c2v_source="${REPO_ROOT}/scripts/lambdas/chat_to_voice_transfer.py"
  [[ -f "${c2v_source}" ]] || die "chat_to_voice_transfer source not found: ${c2v_source}"

  [[ -z "${SOURCE_PHONE_NUMBER}" ]] \
    && warn "SOURCE_PHONE_NUMBER not set — chat→voice callbacks will not dial out."
  [[ -z "${CONNECT_QUEUE_ID}" ]] \
    && warn "CONNECT_QUEUE_ID not set — chat→voice callbacks will not be queued correctly."

  local c2v_env
  c2v_env=$(cat <<EOF
{"Variables":{"INSTANCE_ID":"${CONNECT_INSTANCE_ID}","CONTACT_FLOW_ID":"${CONNECT_CONTACT_FLOW_ID}","QUEUE_ID":"${CONNECT_QUEUE_ID}","SOURCE_PHONE_NUMBER":"${SOURCE_PHONE_NUMBER}","DYNAMODB_TABLE":"${TRANSCRIPT_TABLE}"}}
EOF
)

  CHAT_TO_VOICE_ARN=$(deploy_support_lambda \
    "${CHAT_TO_VOICE_LAMBDA_NAME}" \
    "${c2v_source}" \
    "ARIA chat→voice transfer — retrieves chat transcript and initiates outbound callback" \
    "${c2v_env}" \
    60)

  add_connect_resource_policy "${CHAT_TO_VOICE_LAMBDA_NAME}"
  ok "chat_to_voice_transfer deployed: ${CHAT_TO_VOICE_ARN}"
}

# ---------------------------------------------------------------------------
# Step 7 — Create the AgentCore MCP Gateway IAM Role
# ---------------------------------------------------------------------------
create_gateway_role() {
  log "Creating AgentCore MCP Gateway IAM role: ${GATEWAY_ROLE_NAME}..."

  if aws iam get-role --role-name "${GATEWAY_ROLE_NAME}" >/dev/null 2>&1; then
    ok "Gateway role already exists — skipping"
    GATEWAY_ROLE_ARN=$(aws iam get-role --role-name "${GATEWAY_ROLE_NAME}" \
      --query 'Role.Arn' --output text)
    return 0
  fi

  TRUST_POLICY=$(cat <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
EOF
)

  aws iam create-role \
    --role-name "${GATEWAY_ROLE_NAME}" \
    --assume-role-policy-document "${TRUST_POLICY}" \
    --description "IAM role for ARIA AgentCore MCP Gateway" >/dev/null

  # Allow the gateway to invoke Lambda functions
  LAMBDA_INVOKE_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["lambda:InvokeFunction"],
      "Resource": "arn:aws:lambda:${AWS_REGION}:${AWS_ACCOUNT_ID}:function:${PROJECT}-mcp-*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "*"
    }
  ]
}
EOF
)

  aws iam put-role-policy \
    --role-name "${GATEWAY_ROLE_NAME}" \
    --policy-name aria-mcp-gateway-policy \
    --policy-document "${LAMBDA_INVOKE_POLICY}"

  GATEWAY_ROLE_ARN=$(aws iam get-role --role-name "${GATEWAY_ROLE_NAME}" \
    --query 'Role.Arn' --output text)

  log "Waiting 15 seconds for gateway IAM role to propagate..."
  sleep 15

  ok "Gateway role created: ${GATEWAY_ROLE_ARN}"
}

# ---------------------------------------------------------------------------
# Step 5 — Create the AgentCore MCP Gateway
# ---------------------------------------------------------------------------
create_mcp_gateway() {
  log "Creating AgentCore MCP Gateway: ${GATEWAY_NAME}..."

  # Check if gateway already exists (AWS CLI doesn't support bedrock-agentcore-control
  # in v2.24.x — use boto3 directly for all AgentCore control-plane operations)
  local existing=""
  existing=$(python3 - <<PYEOF
import boto3, sys
c = boto3.client('bedrock-agentcore-control', region_name='${AWS_REGION}')
try:
    paginator = c.get_paginator('list_gateways')
    for page in paginator.paginate():
        for gw in page.get('items', []):
            if gw['name'] == '${GATEWAY_NAME}':
                print(gw['gatewayId'])
                sys.exit(0)
except Exception as exc:
    print('ERROR: ' + str(exc), file=sys.stderr)
    sys.exit(1)
PYEOF
)

  if [[ -n "${existing}" ]]; then
    ok "Gateway already exists with ID: ${existing}"
    GATEWAY_ID="${existing}"
    # Wait for READY in case a previous run left it in CREATING/UPDATING
    log "Checking gateway status..."
    local status="" attempts=0 max_attempts=40
    while [[ $attempts -lt $max_attempts ]]; do
      status=$(python3 - <<PYEOF
import boto3
c = boto3.client('bedrock-agentcore-control', region_name='${AWS_REGION}')
r = c.get_gateway(gatewayIdentifier='${GATEWAY_ID}')
print(r.get('status', 'UNKNOWN') + '|' + r.get('gatewayUrl', ''))
PYEOF
)
      local gw_status="${status%%|*}"
      GATEWAY_URL="${status##*|}"
      case "${gw_status}" in
        READY)
          ok "Gateway is READY"
          return 0
          ;;
        FAILED)
          die "Existing gateway is in FAILED status — delete it first with: $0 teardown --env ${ENV}"
          ;;
        CREATING|UPDATING)
          attempts=$(( attempts + 1 ))
          log "  Status: ${gw_status} (attempt ${attempts}/${max_attempts}) — waiting 15s..."
          sleep 15
          ;;
        *)
          warn "Unexpected status '${gw_status}'"
          GATEWAY_URL=$(python3 - <<PYEOF
import boto3
c = boto3.client('bedrock-agentcore-control', region_name='${AWS_REGION}')
r = c.get_gateway(gatewayIdentifier='${GATEWAY_ID}')
print(r.get('gatewayUrl', ''))
PYEOF
)
          return 0
          ;;
      esac
    done
    die "Gateway did not reach READY after $(( max_attempts * 15 ))s"
  fi

  # Create the gateway — authorizerType must be 'AWS_IAM' (not 'IAM')
  local result=""
  result=$(python3 - <<PYEOF
import boto3, sys
c = boto3.client('bedrock-agentcore-control', region_name='${AWS_REGION}')
try:
    r = c.create_gateway(
        name='${GATEWAY_NAME}',
        roleArn='${GATEWAY_ROLE_ARN}',
        protocolType='MCP',
        authorizerType='AWS_IAM',
        description='AgentCore MCP Gateway for ARIA Banking Agent - ${ENV}'
    )
    print(r['gatewayId'] + '|' + r.get('gatewayUrl', ''))
except Exception as exc:
    print('ERROR: ' + str(exc), file=sys.stderr)
    sys.exit(1)
PYEOF
)

  GATEWAY_ID="${result%%|*}"
  GATEWAY_URL="${result##*|}"

  ok "MCP Gateway created: ${GATEWAY_ID}"
  log "Gateway URL: ${GATEWAY_URL}"

  # Poll until READY (gateway stays in CREATING for ~30-60s after creation)
  log "Waiting for gateway to reach READY status..."
  local status="" attempts=0 max_attempts=40
  while [[ $attempts -lt $max_attempts ]]; do
    status=$(python3 - <<PYEOF
import boto3
c = boto3.client('bedrock-agentcore-control', region_name='${AWS_REGION}')
r = c.get_gateway(gatewayIdentifier='${GATEWAY_ID}')
print(r.get('status', 'UNKNOWN'))
PYEOF
)
    case "${status}" in
      READY)
        ok "Gateway is READY"
        return 0
        ;;
      FAILED)
        die "Gateway entered FAILED status — check AWS console for details"
        ;;
      CREATING|UPDATING)
        attempts=$(( attempts + 1 ))
        log "  Status: ${status} (attempt ${attempts}/${max_attempts}) — waiting 15s..."
        sleep 15
        ;;
      *)
        warn "Unexpected status '${status}' — waiting 15s..."
        attempts=$(( attempts + 1 ))
        sleep 15
        ;;
    esac
  done
  die "Gateway did not reach READY after $(( max_attempts * 15 ))s — aborting"
}

# ---------------------------------------------------------------------------
# Step 6 — Add a Lambda target to the gateway for a domain
# ---------------------------------------------------------------------------
add_gateway_target() {
  local domain="$1"
  local lambda_arn="$2"
  local target_name="${PROJECT}-${domain}"

  log "Adding MCP target: ${target_name} → ${lambda_arn}..."

  # inputSchema takes type/properties/required directly — no 'json' wrapper
  python3 - <<PYEOF
import boto3, sys
c = boto3.client('bedrock-agentcore-control', region_name='${AWS_REGION}')
try:
    c.create_gateway_target(
        gatewayIdentifier='${GATEWAY_ID}',
        name='${target_name}',
        description='ARIA ${domain} domain tools',
        targetConfiguration={
            'mcp': {
                'lambda': {
                    'lambdaArn': '${lambda_arn}',
                    'toolSchema': {
                        'inlinePayload': [
                            {
                                'name': '${target_name}',
                                'description': 'ARIA banking tools for the ${domain} domain',
                                'inputSchema': {
                                    'type': 'object',
                                    'properties': {
                                        'tool_name': {
                                            'type': 'string',
                                            'description': 'Name of the ARIA tool to invoke'
                                        },
                                        'tool_input': {
                                            'type': 'object',
                                            'description': 'Input parameters for the tool'
                                        }
                                    },
                                    'required': ['tool_name']
                                }
                            }
                        ]
                    }
                }
            }
        },
        credentialProviderConfigurations=[
            {'credentialProviderType': 'GATEWAY_IAM_ROLE'}
        ]
    )
except Exception as exc:
    print('ERROR: ' + str(exc), file=sys.stderr)
    sys.exit(1)
PYEOF

  ok "Target added: ${target_name}"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# cmd_deploy — Steps 1–6: build and deploy everything
# ---------------------------------------------------------------------------
cmd_deploy() {
  echo ""
  echo -e "${BLUE}=====================================================================${NC}"
  echo -e "${BLUE}  ARIA AgentCore — Full Infrastructure Deployment${NC}"
  echo -e "${BLUE}  Environment: ${ENV} | Region: ${AWS_REGION}${NC}"
  echo -e "${BLUE}=====================================================================${NC}"
  echo ""

  check_prereqs

  # Step 1 — DynamoDB table (no dependencies)
  create_dynamodb_table

  # Step 2 — Support Lambda IAM role (session injector + transfer Lambdas share this)
  create_support_lambda_role

  # Step 3 — Deploy support Lambdas (requires SUPPORT_LAMBDA_ROLE_ARN from step 2)
  deploy_session_injector
  deploy_transfer_lambdas

  # Step 4 — MCP domain Lambda IAM role
  create_lambda_role

  # Step 5 — Build and deploy each domain Lambda
  declare -A LAMBDA_ARNS
  local DOMAINS=(auth account customer debit-card credit-card mortgage products pii escalation knowledge)

  for domain in "${DOMAINS[@]}"; do
    zip_path=$(build_lambda_package "${domain}")
    lambda_arn=$(deploy_lambda "${domain}" "${zip_path}")
    LAMBDA_ARNS["${domain}"]="${lambda_arn}"
    rm -f "${zip_path}"
  done

  ok "All ${#DOMAINS[@]} MCP domain Lambda functions deployed"

  # Step 6 — Gateway IAM role
  create_gateway_role

  # Step 7 — Create gateway
  create_mcp_gateway

  # Step 8 — Add targets
  for domain in "${DOMAINS[@]}"; do
    add_gateway_target "${domain}" "${LAMBDA_ARNS[${domain}]}"
  done

  echo ""
  echo -e "${GREEN}=====================================================================${NC}"
  echo -e "${GREEN}  Deployment Complete!${NC}"
  echo -e "${GREEN}=====================================================================${NC}"
  echo ""
  echo -e "  Gateway ID:   ${YELLOW}${GATEWAY_ID}${NC}"
  echo -e "  Gateway URL:  ${YELLOW}${GATEWAY_URL:-<check console — may take a moment>}${NC}"
  echo ""
  echo "  Support Lambdas:"
  echo -e "    ${GREEN}✓${NC}  ${SESSION_INJECTOR_NAME}"
  echo -e "       ARN: ${SESSION_INJECTOR_ARN}"
  echo -e "    ${GREEN}✓${NC}  ${VOICE_TO_CHAT_LAMBDA_NAME}"
  echo -e "       ARN: ${VOICE_TO_CHAT_ARN}"
  echo -e "    ${GREEN}✓${NC}  ${CHAT_TO_VOICE_LAMBDA_NAME}"
  echo -e "       ARN: ${CHAT_TO_VOICE_ARN}"
  echo ""
  echo "  MCP domain Lambdas:"
  for domain in "${DOMAINS[@]}"; do
    echo -e "    ${GREEN}✓${NC}  ${PROJECT}-mcp-${domain}-${ENV}"
  done
  echo ""
  echo "  MCP targets registered:"
  for domain in "${DOMAINS[@]}"; do
    echo -e "    ${GREEN}✓${NC}  ${PROJECT}-${domain}"
  done
  echo ""
  echo -e "${BLUE}Next steps:${NC}"
  echo "  1. In Connect, add all 4 Lambdas to the instance allow-list:"
  echo "     Connect console → Instance settings → Flows → Lambda functions → Add"
  echo "     Add: ${SESSION_INJECTOR_NAME}"
  echo "     Add: ${VOICE_TO_CHAT_LAMBDA_NAME}"
  echo "     Add: ${CHAT_TO_VOICE_LAMBDA_NAME}"
  echo "  2. Copy the Gateway URL above and paste it into the ARIA AI Agent's"
  echo "     MCP tool configuration in the Connect AI Agent Builder."
  echo "  3. In Block 9 of the Unified Inbound flow, select: ${SESSION_INJECTOR_NAME}"
  echo "  4. Update Blocks 9A/9B in the flow to invoke the transfer Lambdas."
  echo "  5. Test by sending 'Hello Aria' in the Connect test chat widget."
  echo "  6. Check CloudWatch Logs for each Lambda to verify invocations."
  echo ""
  if [[ -z "${CONNECT_ASSISTANT_ID}" ]]; then
    echo -e "  ${YELLOW}⚠  CONNECT_ASSISTANT_ID was not set. Run again with --assistant-id${NC}"
    echo "     after noting the Q Connect assistant ID from Connect → AI Agent Designer."
    echo ""
  fi
  echo "  To retrieve the gateway URL later:"
  echo -e "    ${YELLOW}aws bedrock-agentcore-control get-gateway \\"
  echo -e "      --gateway-id ${GATEWAY_ID} \\"
  echo -e "      --region ${AWS_REGION} \\"
  echo -e "      --query 'gatewayUrl' --output text${NC}"
  echo ""
}

# ---------------------------------------------------------------------------
# cmd_teardown — delete every resource created by cmd_deploy, in reverse order
#
# Deletion order (reverse of creation):
#   1. MCP Gateway targets    (must be removed before the gateway can be deleted)
#   2. MCP Gateway
#   3. MCP domain Lambdas     (10 functions)
#   4. Support Lambdas        (session_injector, voice_to_chat, chat_to_voice)
#   5. DynamoDB table         (aria-transcript-store)
#   6. MCP Lambda IAM role    (detach managed policy, delete inline policy, delete role)
#   7. Support Lambda IAM role
#   8. Gateway IAM role
# ---------------------------------------------------------------------------
cmd_teardown() {
  local DOMAINS=(auth account customer debit-card credit-card mortgage products pii escalation knowledge)

  echo ""
  echo -e "${BLUE}======================================================${NC}"
  echo -e "${BLUE}  ARIA AgentCore MCP Gateway Teardown${NC}"
  echo -e "${BLUE}  Environment: ${ENV} | Region: ${AWS_REGION}${NC}"
  echo -e "${BLUE}======================================================${NC}"
  echo ""

  # Just need AWS CLI + creds + boto3 for AgentCore control-plane operations
  command -v aws  >/dev/null 2>&1 || die "aws CLI not found."
  python3 -c "import boto3" 2>/dev/null || die "boto3 not installed. Run: pip3 install boto3"
  aws sts get-caller-identity --region "${AWS_REGION}" >/dev/null 2>&1 \
    || die "AWS credentials not configured."

  echo -e "${RED}  The following resources will be permanently deleted:${NC}"
  echo "    • MCP Gateway:              ${GATEWAY_NAME}"
  echo "    • MCP targets:              ${PROJECT}-{domain}  (${#DOMAINS[@]} targets)"
  echo "    • MCP domain Lambdas:       ${PROJECT}-mcp-{domain}-${ENV}  (${#DOMAINS[@]} functions)"
  echo "    • Session injector Lambda:  ${SESSION_INJECTOR_NAME}"
  echo "    • Transfer Lambdas:         ${VOICE_TO_CHAT_LAMBDA_NAME}"
  echo "                                ${CHAT_TO_VOICE_LAMBDA_NAME}"
  echo "    • DynamoDB table:           ${TRANSCRIPT_TABLE}"
  echo "    • IAM roles:                ${LAMBDA_ROLE_NAME}"
  echo "                                ${SUPPORT_LAMBDA_ROLE_NAME}"
  echo "                                ${GATEWAY_ROLE_NAME}"
  echo ""
  printf "  Are you sure? [y/N]: "
  read -r confirm
  [[ "${confirm,,}" == "y" ]] || { echo "  Cancelled."; exit 0; }
  echo ""

  # ------------------------------------------------------------------
  # Step 1 — Delete MCP Gateway targets, then the gateway itself
  # (uses boto3 — bedrock-agentcore-control is not in AWS CLI v2.24.x)
  # ------------------------------------------------------------------
  log "Looking up MCP Gateway: ${GATEWAY_NAME}..."
  local gateway_id=""
  gateway_id=$(python3 - <<PYEOF
import boto3, sys
c = boto3.client('bedrock-agentcore-control', region_name='${AWS_REGION}')
try:
    paginator = c.get_paginator('list_gateways')
    for page in paginator.paginate():
        for gw in page.get('items', []):
            if gw['name'] == '${GATEWAY_NAME}':
                print(gw['gatewayId'])
                sys.exit(0)
except Exception as exc:
    print('ERROR: ' + str(exc), file=sys.stderr)
    sys.exit(1)
PYEOF
)

  if [[ -n "${gateway_id}" ]]; then
    log "Deleting MCP Gateway targets for gateway: ${gateway_id}..."
    local target_ids=""
    target_ids=$(python3 - <<PYEOF
import boto3, sys
c = boto3.client('bedrock-agentcore-control', region_name='${AWS_REGION}')
try:
    paginator = c.get_paginator('list_gateway_targets')
    for page in paginator.paginate(gatewayIdentifier='${gateway_id}'):
        for t in page.get('items', []):
            print(t['targetId'])
except Exception as exc:
    print('ERROR: ' + str(exc), file=sys.stderr)
    sys.exit(1)
PYEOF
)

    while IFS= read -r target_id; do
      [[ -z "${target_id}" ]] && continue
      if python3 - <<PYEOF >/dev/null 2>&1
import boto3, sys
c = boto3.client('bedrock-agentcore-control', region_name='${AWS_REGION}')
try:
    c.delete_gateway_target(gatewayIdentifier='${gateway_id}', targetId='${target_id}')
except Exception as exc:
    print('ERROR: ' + str(exc), file=sys.stderr)
    sys.exit(1)
PYEOF
      then
        ok "Target deleted: ${target_id}"
      else
        warn "Could not delete target: ${target_id} (may already be gone)"
      fi
    done <<< "${target_ids}"

    log "Deleting MCP Gateway: ${gateway_id}..."
    if python3 - <<PYEOF >/dev/null 2>&1
import boto3, sys
c = boto3.client('bedrock-agentcore-control', region_name='${AWS_REGION}')
try:
    c.delete_gateway(gatewayIdentifier='${gateway_id}')
except Exception as exc:
    print('ERROR: ' + str(exc), file=sys.stderr)
    sys.exit(1)
PYEOF
    then
      ok "Gateway deleted: ${GATEWAY_NAME} (${gateway_id})"
    else
      warn "Could not delete gateway — check AWS console"
    fi
  else
    warn "MCP Gateway '${GATEWAY_NAME}' not found — skipping"
  fi

  # ------------------------------------------------------------------
  # Step 2 — Delete MCP domain Lambda functions
  # ------------------------------------------------------------------
  log "Deleting ${#DOMAINS[@]} MCP domain Lambda functions..."
  for domain in "${DOMAINS[@]}"; do
    local fn="${PROJECT}-mcp-${domain}-${ENV}"
    if aws lambda delete-function \
        --function-name "${fn}" \
        --region "${AWS_REGION}" >/dev/null 2>&1; then
      ok "Lambda deleted: ${fn}"
    else
      warn "Lambda not found (already deleted?): ${fn}"
    fi
  done

  # ------------------------------------------------------------------
  # Step 2b — Delete support Lambda functions
  # ------------------------------------------------------------------
  log "Deleting support Lambda functions..."
  for fn in "${SESSION_INJECTOR_NAME}" "${VOICE_TO_CHAT_LAMBDA_NAME}" "${CHAT_TO_VOICE_LAMBDA_NAME}"; do
    if aws lambda delete-function \
        --function-name "${fn}" \
        --region "${AWS_REGION}" >/dev/null 2>&1; then
      ok "Lambda deleted: ${fn}"
    else
      warn "Lambda not found (already deleted?): ${fn}"
    fi
  done

  # ------------------------------------------------------------------
  # Step 2c — Delete DynamoDB table
  # ------------------------------------------------------------------
  log "Deleting DynamoDB table: ${TRANSCRIPT_TABLE}..."
  if aws dynamodb delete-table \
      --table-name "${TRANSCRIPT_TABLE}" \
      --region "${AWS_REGION}" >/dev/null 2>&1; then
    ok "DynamoDB table deleted: ${TRANSCRIPT_TABLE}"
  else
    warn "DynamoDB table not found (already deleted?): ${TRANSCRIPT_TABLE}"
  fi

  # ------------------------------------------------------------------
  # Step 3 — Delete Lambda IAM role
  # ------------------------------------------------------------------
  log "Deleting MCP Lambda IAM role: ${LAMBDA_ROLE_NAME}..."
  aws iam detach-role-policy \
    --role-name "${LAMBDA_ROLE_NAME}" \
    --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" \
    >/dev/null 2>&1 || true
  aws iam delete-role-policy \
    --role-name "${LAMBDA_ROLE_NAME}" \
    --policy-name "aria-mcp-lambda-policy" \
    >/dev/null 2>&1 || true
  if aws iam delete-role \
      --role-name "${LAMBDA_ROLE_NAME}" \
      >/dev/null 2>&1; then
    ok "Lambda role deleted: ${LAMBDA_ROLE_NAME}"
  else
    warn "Lambda role not found (already deleted?): ${LAMBDA_ROLE_NAME}"
  fi

  # ------------------------------------------------------------------
  # Step 3b — Delete Support Lambda IAM role
  # ------------------------------------------------------------------
  log "Deleting Support Lambda IAM role: ${SUPPORT_LAMBDA_ROLE_NAME}..."
  aws iam detach-role-policy \
    --role-name "${SUPPORT_LAMBDA_ROLE_NAME}" \
    --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" \
    >/dev/null 2>&1 || true
  aws iam delete-role-policy \
    --role-name "${SUPPORT_LAMBDA_ROLE_NAME}" \
    --policy-name "aria-support-lambda-policy" \
    >/dev/null 2>&1 || true
  if aws iam delete-role \
      --role-name "${SUPPORT_LAMBDA_ROLE_NAME}" \
      >/dev/null 2>&1; then
    ok "Support Lambda role deleted: ${SUPPORT_LAMBDA_ROLE_NAME}"
  else
    warn "Support Lambda role not found (already deleted?): ${SUPPORT_LAMBDA_ROLE_NAME}"
  fi

  # ------------------------------------------------------------------
  # Step 4 — Delete Gateway IAM role
  # ------------------------------------------------------------------
  log "Deleting Gateway IAM role: ${GATEWAY_ROLE_NAME}..."
  aws iam delete-role-policy \
    --role-name "${GATEWAY_ROLE_NAME}" \
    --policy-name "aria-mcp-gateway-policy" \
    >/dev/null 2>&1 || true
  if aws iam delete-role \
      --role-name "${GATEWAY_ROLE_NAME}" \
      >/dev/null 2>&1; then
    ok "Gateway role deleted: ${GATEWAY_ROLE_NAME}"
  else
    warn "Gateway role not found (already deleted?): ${GATEWAY_ROLE_NAME}"
  fi

  echo ""
  echo -e "${GREEN}======================================================${NC}"
  echo -e "${GREEN}  Teardown Complete${NC}"
  echo -e "${GREEN}======================================================${NC}"
  echo ""
}

# ---------------------------------------------------------------------------
# usage
# ---------------------------------------------------------------------------
usage() {
  echo ""
  echo "  Usage: $0 [deploy|teardown] [OPTIONS]"
  echo ""
  echo "  Subcommands:"
  echo "    deploy   — (default) deploy all ARIA infrastructure"
  echo "    teardown — delete all resources created by deploy"
  echo ""
  echo "  Core options:"
  echo "    --env <env>              Environment tag              (default: prod)"
  echo "    --region <region>        AWS region                   (default: eu-west-2)"
  echo "    --help                   Show this help"
  echo ""
  echo "  Connect / support Lambda options (required for full deployment):"
  echo "    --instance-id  <id>      Amazon Connect instance ID"
  echo "    --assistant-id <id>      Q Connect assistant ID (from Part D.1)"
  echo "    --flow-id      <id>      Unified Inbound contact flow ID (from Part E)"
  echo "    --queue-id     <id>      Queue ARN/ID for outbound voice callbacks"
  echo "    --chat-widget-url <url>  Base URL of the chat widget page"
  echo "    --sms-number   <e164>    SMS origination number (E.164, e.g. +441234567890)"
  echo "    --source-phone <e164>    Outbound call number for chat→voice callbacks"
  echo "    --crm-endpoint <url>     CRM API endpoint (leave unset to use stub data)"
  echo ""
  echo "  All --* options can also be set as environment variables:"
  echo "    CONNECT_INSTANCE_ID, CONNECT_ASSISTANT_ID, CONNECT_CONTACT_FLOW_ID,"
  echo "    CONNECT_QUEUE_ID, CHAT_WIDGET_URL, SMS_ORIGINATION_NUMBER,"
  echo "    SOURCE_PHONE_NUMBER, CRM_API_ENDPOINT"
  echo ""
  echo "  Examples:"
  echo "    # Minimal — deploy MCP Gateway only (support Lambdas created with empty config)"
  echo "    $0 deploy --env dev --region eu-west-2"
  echo ""
  echo "    # Full deployment with all options"
  echo "    $0 deploy --env dev --region eu-west-2 \\"
  echo "          --instance-id  xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx \\"
  echo "          --assistant-id yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy \\"
  echo "          --flow-id      zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz \\"
  echo "          --queue-id     arn:aws:connect:eu-west-2:ACCOUNT:instance/INST/queue/QUEUE \\"
  echo "          --chat-widget-url https://yourbank.example.com/chat \\"
  echo "          --sms-number   +441234567890 \\"
  echo "          --source-phone +441234567890"
  echo ""
  echo "    # Teardown"
  echo "    $0 teardown --env dev --region eu-west-2"
  echo ""
}

# ---------------------------------------------------------------------------
# main — parse optional subcommand + flags, dispatch
# ---------------------------------------------------------------------------
main() {
  local subcmd="deploy"

  # Optional positional subcommand (first arg, if not a flag)
  case "${1:-}" in
    deploy|teardown) subcmd="$1"; shift ;;
    --*|"")          ;;  # no subcommand given — default to deploy
    *)
      error "Unknown subcommand: $1"
      usage; exit 1
      ;;
  esac

  # Parse all flags
  while [[ $# -gt 0 ]]; do
    case $1 in
      --env)              ENV="$2";                      shift 2 ;;
      --region)           AWS_REGION="$2";               shift 2 ;;
      --instance-id)      CONNECT_INSTANCE_ID="$2";      shift 2 ;;
      --assistant-id)     CONNECT_ASSISTANT_ID="$2";     shift 2 ;;
      --flow-id)          CONNECT_CONTACT_FLOW_ID="$2";  shift 2 ;;
      --queue-id)         CONNECT_QUEUE_ID="$2";         shift 2 ;;
      --chat-widget-url)  CHAT_WIDGET_URL="$2";          shift 2 ;;
      --sms-number)       SMS_ORIGINATION_NUMBER="$2";   shift 2 ;;
      --source-phone)     SOURCE_PHONE_NUMBER="$2";      shift 2 ;;
      --crm-endpoint)     CRM_API_ENDPOINT="$2";         shift 2 ;;
      --help)             usage; exit 0 ;;
      *)                  warn "Unknown argument: $1"; shift ;;
    esac
  done

  # Recompute env-dependent resource names after arg parsing
  GATEWAY_NAME="${PROJECT}-mcp-gateway-${ENV}"
  LAMBDA_ROLE_NAME="${PROJECT}-mcp-lambda-role-${ENV}"
  GATEWAY_ROLE_NAME="${PROJECT}-mcp-gateway-role-${ENV}"
  SUPPORT_LAMBDA_ROLE_NAME="${PROJECT}-support-lambda-role-${ENV}"
  SESSION_INJECTOR_NAME="${PROJECT}-session-injector-${ENV}"
  VOICE_TO_CHAT_LAMBDA_NAME="${PROJECT}-voice-to-chat-transfer-${ENV}"
  CHAT_TO_VOICE_LAMBDA_NAME="${PROJECT}-chat-to-voice-transfer-${ENV}"

  case "${subcmd}" in
    deploy)   cmd_deploy   ;;
    teardown) cmd_teardown ;;
  esac
}

main "$@"
