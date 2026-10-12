#!/usr/bin/env bash
# =============================================================================
# deploy_payment_stepup_tools.sh
# =============================================================================
# Deploys what ARIA needs for the level 4 payment step-up (app approval with
# number matching), in the order that keeps the live tools working.
#
# YOU run this script. It makes changes in your AWS account:
#   1. Sets MOCK_DATA=true on the tool Lambdas whose code requires it, keeping
#      every environment variable they already have
#   2. Deploys the auth handler code to the auth Lambda only
#   3. Tests the two new tools by invoking the Lambda directly
#   4. Adds the two tool definitions to the auth target on the MCP gateway,
#      leaving the target's existing tools exactly as they are
#
# It uses the AWS CLI only. It does NOT need boto3. (deploy_mcp_gateway.sh uses
# boto3 because older AWS CLI versions had no bedrock-agentcore-control command.)
#
# It does NOT change the AI agent, the prompt or any contact flow. Those are the
# manual steps printed at the end.
#
# Usage:
#   ./connect-idv-test-harness/scripts/deploy_payment_stepup_tools.sh [OPTIONS]
#
# With no options it targets the prod ARIA banking tools in eu-west-2.
#
# Options:
#   --region        REGION   AWS region                  (default: eu-west-2)
#   --account-id    ID       AWS account ID              (default: 395402194296)
#   --env           ENV      Tool environment suffix     (default: prod)
#   --mock-domains  LIST     Comma-separated tool domains that get MOCK_DATA=true
#                            (default: auth,account,customer)
#   --skip-mock-data         Do not touch any environment variables
#   --skip-code              Do not deploy the auth handler code
#   --skip-gateway           Do not update the gateway target
#   --dry-run                Print what would be done without changing anything
#   --help                   Show this help text
#
# Environment variable equivalents (flags take precedence):
#   AWS_REGION, AWS_ACCOUNT_ID, ARIA_ENV
#
# Requirements:
#   - AWS CLI v2.27 or later (needs the bedrock-agentcore-control commands)
#   - python3 (standard library only) and zip on PATH
# =============================================================================

set -euo pipefail

# ── Colour helpers ─────────────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

die()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; exit 1; }
warn()  { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
step()  { echo -e "${CYAN}[....] $*${RESET}"; }
ok()    { echo -e "${GREEN}[ OK ] $*${RESET}"; }
header(){ echo -e "\n${BOLD}━━━ $* ━━━${RESET}"; }

# ── Defaults ───────────────────────────────────────────────────────────────────
DEFAULT_REGION="eu-west-2"
DEFAULT_ACCOUNT_ID="395402194296"
DEFAULT_ENV="prod"
PROJECT="aria-banking"
# The handlers that return "No data source configured" unless MOCK_DATA=true.
DEFAULT_MOCK_DOMAINS="auth,account,customer"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AUTH_HANDLER="${SCRIPT_DIR}/../../scripts/lambdas/mcp_tools/aria_auth_handler.py"

REGION="${AWS_REGION:-$DEFAULT_REGION}"
ACCOUNT_ID="${AWS_ACCOUNT_ID:-$DEFAULT_ACCOUNT_ID}"
ENV_NAME="${ARIA_ENV:-$DEFAULT_ENV}"
MOCK_DOMAINS="$DEFAULT_MOCK_DOMAINS"
DO_MOCK=true; DO_CODE=true; DO_GATEWAY=true; DRY_RUN=false

# ── Argument parsing ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --region)        REGION="$2";       shift 2 ;;
        --account-id)    ACCOUNT_ID="$2";   shift 2 ;;
        --env)           ENV_NAME="$2";     shift 2 ;;
        --mock-domains)  MOCK_DOMAINS="$2"; shift 2 ;;
        --skip-mock-data) DO_MOCK=false;    shift ;;
        --skip-code)      DO_CODE=false;    shift ;;
        --skip-gateway)   DO_GATEWAY=false; shift ;;
        --dry-run)        DRY_RUN=true;     shift ;;
        --help|-h)
            sed -n '/^# Usage:/,/^# Requirements:/p' "$0" | sed -E 's/^# ?//'
            exit 0
            ;;
        *) die "Unknown argument: $1. Run with --help for usage." ;;
    esac
done

AUTH_FUNCTION="${PROJECT}-mcp-auth-${ENV_NAME}"
GATEWAY_NAME="${PROJECT}-mcp-gateway-${ENV_NAME}"
TARGET_NAME="${PROJECT}-auth"

# ── Validation ─────────────────────────────────────────────────────────────────
[[ -f "$AUTH_HANDLER" ]] || die "Auth handler source not found: ${AUTH_HANDLER}"
command -v aws     >/dev/null 2>&1 || die "AWS CLI not found. Install aws-cli v2."
command -v zip     >/dev/null 2>&1 || die "zip not found. Install zip."
command -v python3 >/dev/null 2>&1 || die "python3 not found."
if $DO_GATEWAY; then
    aws bedrock-agentcore-control help >/dev/null 2>&1 || die \
        "This AWS CLI has no 'bedrock-agentcore-control' command ($(aws --version 2>&1 | cut -d' ' -f1)).\n" \
        "  Update the AWS CLI, or run again with --skip-gateway."
fi

step "Checking AWS credentials..."
CALLER_ACCOUNT=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) \
    || die "Could not read AWS credentials. Sign in with the AWS CLI first."
[[ "$CALLER_ACCOUNT" == "$ACCOUNT_ID" ]] || die \
    "Your AWS credentials are for account ${CALLER_ACCOUNT}, but the target is ${ACCOUNT_ID}.\n" \
    "  Sign in to ${ACCOUNT_ID}, or pass --account-id ${CALLER_ACCOUNT} to deploy there instead."
ok "Signed in to account ${ACCOUNT_ID}"

if $DRY_RUN; then
    warn "DRY-RUN mode — no AWS changes will be made. Read-only lookups still run."
    run() { echo "  [dry-run] $*"; }
else
    run() { "$@"; }
fi

BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT

header "Deploying with"
echo "  Region          : ${REGION}"
echo "  Account         : ${ACCOUNT_ID}"
echo "  Auth Lambda     : ${AUTH_FUNCTION}"
echo "  Gateway         : ${GATEWAY_NAME}  (target ${TARGET_NAME})"
echo "  MOCK_DATA on    : $($DO_MOCK && echo "$MOCK_DOMAINS" || echo "(skipped)")"

wait_for_lambda() {
    $DRY_RUN || aws lambda wait function-updated --function-name "$1" --region "$REGION"
}

# =============================================================================
# Step 1 — MOCK_DATA=true, keeping every existing environment variable
# =============================================================================
header "Step 1 — MOCK_DATA on the tool Lambdas"

if ! $DO_MOCK; then
    warn "Skipped (--skip-mock-data)."
else
    IFS=',' read -r -a DOMAINS <<< "$MOCK_DOMAINS"
    for domain in "${DOMAINS[@]}"; do
        fn="${PROJECT}-mcp-${domain}-${ENV_NAME}"
        current=$(aws lambda get-function-configuration --function-name "$fn" --region "$REGION" \
            --query "Environment.Variables" --output json 2>/dev/null) \
            || { warn "Lambda not found, skipped: ${fn}"; continue; }

        env_file="${BUILD_DIR}/env-${domain}.json"
        # Merge, do not replace: update-function-configuration overwrites the whole set.
        status=$(CURRENT="$current" python3 - "$env_file" <<'PY'
import json, os, sys
variables = json.loads(os.environ["CURRENT"] or "null") or {}
already = variables.get("MOCK_DATA", "").lower() == "true"
variables["MOCK_DATA"] = "true"
json.dump({"Variables": variables}, open(sys.argv[1], "w"))
print("already" if already else "set:" + ",".join(sorted(variables)))
PY
)
        if [[ "$status" == "already" ]]; then
            ok "${fn}: MOCK_DATA already true"
            continue
        fi
        step "${fn}: setting MOCK_DATA=true (keeping ${status#set:})"
        run aws lambda update-function-configuration --function-name "$fn" --region "$REGION" \
            --environment "file://${env_file}" --query "FunctionName" --output text > /dev/null
        wait_for_lambda "$fn"
        ok "${fn}: MOCK_DATA=true"
    done
fi

# =============================================================================
# Step 2 — Auth handler code (this Lambda only)
# =============================================================================
header "Step 2 — Auth handler code"

if ! $DO_CODE; then
    warn "Skipped (--skip-code)."
else
    python3 -m py_compile "$AUTH_HANDLER" || die "aria_auth_handler.py does not compile."
    grep -q '"send_push_challenge"' "$AUTH_HANDLER" \
        || die "aria_auth_handler.py has no send_push_challenge tool. Are you on the right branch?"

    # The Lambda's handler setting is handler.lambda_handler, so the file is
    # packaged as handler.py — the same convention deploy_mcp_gateway.sh uses.
    cp "$AUTH_HANDLER" "${BUILD_DIR}/handler.py"
    (cd "$BUILD_DIR" && zip -q auth.zip handler.py)
    step "Uploading aria_auth_handler.py to ${AUTH_FUNCTION}..."
    run aws lambda update-function-code --function-name "$AUTH_FUNCTION" --region "$REGION" \
        --zip-file "fileb://${BUILD_DIR}/auth.zip" --query "FunctionName" --output text > /dev/null
    wait_for_lambda "$AUTH_FUNCTION"
    ok "Code deployed: ${AUTH_FUNCTION}"
fi

# =============================================================================
# Step 3 — Prove the two new tools work
# =============================================================================
header "Step 3 — Testing the tools"

invoke_tool() {   # invoke_tool <tool_name> <json parameters> -> prints the JSON result
    local out="${BUILD_DIR}/out-$1.json"
    TOOL="$1" PARAMS="$2" python3 -c \
        'import json,os; print(json.dumps({"tool_name": os.environ["TOOL"], "parameters": json.loads(os.environ["PARAMS"])}))' \
        > "${BUILD_DIR}/payload.json"
    aws lambda invoke --function-name "$AUTH_FUNCTION" --region "$REGION" \
        --cli-binary-format raw-in-base64-out --payload "file://${BUILD_DIR}/payload.json" \
        "$out" --query "FunctionError" --output text > "${BUILD_DIR}/invoke-status.txt"
    cat "$out"
}
field() {         # field <json> <key> -> prints the value, or nothing
    JSON="$1" python3 -c 'import json,os,sys; v=json.loads(os.environ["JSON"] or "{}"); print(v.get(sys.argv[1], "") if isinstance(v, dict) else "")' "$2"
}

if $DRY_RUN; then
    warn "Skipped in dry-run (it would test code that has not been uploaded)."
else
    sent=$(invoke_tool send_push_challenge '{"customer_id":"CUST-001","payee":"Deploy check","amount":"1.00"}')
    [[ "$(field "$sent" error)" == "" ]] || die "send_push_challenge returned an error: $(field "$sent" error)"
    [[ "$(field "$sent" sent)" == "True" ]] || die "send_push_challenge did not send a challenge. Response: ${sent}"
    number="$(field "$sent" match_number)"
    ok "send_push_challenge works (match number ${number})"

    verify_params=$(JSON="$sent" python3 -c \
        'import json,os; s=json.loads(os.environ["JSON"]); print(json.dumps({"customer_id":"CUST-001","challenge_id":s["challenge_id"],"selected_number":s["match_number"]}))')
    approved=$(invoke_tool verify_push_challenge "$verify_params")
    [[ "$(field "$approved" verified)" == "True" ]] || die "verify_push_challenge did not approve the right number. Response: ${approved}"
    ok "verify_push_challenge approves the right number"

    wrong_params=$(JSON="$sent" python3 -c \
        'import json,os; s=json.loads(os.environ["JSON"]); print(json.dumps({"customer_id":"CUST-001","challenge_id":s["challenge_id"],"selected_number":"00"}))')
    declined=$(invoke_tool verify_push_challenge "$wrong_params")
    [[ "$(field "$declined" verified)" == "False" ]] || die "verify_push_challenge approved a wrong number. Response: ${declined}"
    ok "verify_push_challenge rejects a wrong number"

    kba=$(invoke_tool validate_customer_auth '{"customer_id":"CUST-001","dob":"09/09/1982","mobile_last_four":"9252"}')
    [[ "$(field "$kba" verified)" == "True" ]] \
        && ok "validate_customer_auth (existing security check) works" \
        || warn "validate_customer_auth did not verify the test answers. Response: ${kba}"
fi

# =============================================================================
# Step 4 — Add the two tools to the gateway's auth target
# =============================================================================
header "Step 4 — MCP gateway target"

if ! $DO_GATEWAY; then
    warn "Skipped (--skip-gateway)."
else
    GATEWAY_ID=$(aws bedrock-agentcore-control list-gateways --region "$REGION" \
        --query "items[?name=='${GATEWAY_NAME}'].gatewayId | [0]" --output text)
    [[ -n "$GATEWAY_ID" && "$GATEWAY_ID" != "None" ]] || die "Gateway not found: ${GATEWAY_NAME}"
    TARGET_ID=$(aws bedrock-agentcore-control list-gateway-targets --gateway-identifier "$GATEWAY_ID" \
        --region "$REGION" --query "items[?name=='${TARGET_NAME}'].targetId | [0]" --output text)
    [[ -n "$TARGET_ID" && "$TARGET_ID" != "None" ]] || die "Target not found on the gateway: ${TARGET_NAME}"
    ok "Gateway ${GATEWAY_ID}, target ${TARGET_ID}"

    aws bedrock-agentcore-control get-gateway-target --gateway-identifier "$GATEWAY_ID" \
        --target-id "$TARGET_ID" --region "$REGION" --output json > "${BUILD_DIR}/target.json"

    # Start from the target exactly as it is and add (or refresh) only the two
    # new tools, so nothing else about the target changes.
    summary=$(python3 - "${BUILD_DIR}" <<'PY'
import json, sys
build = sys.argv[1]
target = json.load(open(f"{build}/target.json"))
new_tools = [
    {
        "name": "send_push_challenge",
        "description": "Sends an approval request with a two-digit match number to the customer's registered banking app, for one payment. Returns the number to read out and a challenge_id",
        "inputSchema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Customer ID from the session context"},
                "payee": {"type": "string", "description": "Who the payment is to, as confirmed by the customer"},
                "amount": {"type": "string", "description": "Payment amount, as confirmed by the customer, e.g. 250.00"},
            },
            "required": ["customer_id", "payee", "amount"],
        },
    },
    {
        "name": "verify_push_challenge",
        "description": "Checks the outcome of an app approval request. Returns verified true only when the customer approved with the correct match number",
        "inputSchema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Customer ID from the session context"},
                "challenge_id": {"type": "string", "description": "The challenge_id returned by send_push_challenge, unchanged"},
                "selected_number": {"type": "string", "description": "The two-digit number the customer says they chose in the app. Empty if they chose nothing"},
            },
            "required": ["customer_id", "challenge_id"],
        },
    },
]
config = target["targetConfiguration"]
tools = config["mcp"]["lambda"]["toolSchema"]["inlinePayload"]
before = [t["name"] for t in tools]
names = {t["name"] for t in new_tools}
tools[:] = [t for t in tools if t["name"] not in names] + new_tools
json.dump(config, open(f"{build}/target-config.json", "w"))
json.dump(target.get("credentialProviderConfigurations") or [{"credentialProviderType": "GATEWAY_IAM_ROLE"}],
          open(f"{build}/target-creds.json", "w"))
open(f"{build}/target-description.txt", "w").write(target.get("description") or "ARIA auth domain tools")
added = sorted(names - set(before))
print(("adding " + ", ".join(added)) if added else "refreshing the two existing definitions")
print("tools after update: " + ", ".join(t["name"] for t in tools))
PY
)
    echo "$summary" | sed 's/^/  /'

    step "Updating target ${TARGET_NAME}..."
    run aws bedrock-agentcore-control update-gateway-target --region "$REGION" \
        --gateway-identifier "$GATEWAY_ID" --target-id "$TARGET_ID" \
        --name "$TARGET_NAME" --description "$(cat "${BUILD_DIR}/target-description.txt")" \
        --target-configuration "file://${BUILD_DIR}/target-config.json" \
        --credential-provider-configurations "file://${BUILD_DIR}/target-creds.json" \
        --query "status" --output text > /dev/null

    if ! $DRY_RUN; then
        step "Waiting for the target to be READY..."
        status=""
        for _ in $(seq 1 30); do
            status=$(aws bedrock-agentcore-control get-gateway-target --gateway-identifier "$GATEWAY_ID" \
                --target-id "$TARGET_ID" --region "$REGION" --query "status" --output text)
            [[ "$status" == "READY" ]] && break
            [[ "$status" == *FAILED* ]] && die "The target update failed (status ${status}). Check the gateway in the console."
            sleep 4
        done
        [[ "$status" == "READY" ]] || die "The target is still ${status} after two minutes. Check the gateway in the console."
        published=$(aws bedrock-agentcore-control get-gateway-target --gateway-identifier "$GATEWAY_ID" \
            --target-id "$TARGET_ID" --region "$REGION" \
            --query "targetConfiguration.mcp.lambda.toolSchema.inlinePayload[].name" --output text)
        for tool in send_push_challenge verify_push_challenge; do
            [[ " $published " == *"$tool"* ]] || die "The gateway target does not list ${tool} after the update."
        done
        ok "Gateway target READY with: $(echo $published)"
    fi
fi

# =============================================================================
# Summary
# =============================================================================
header "Done"

cat <<SUMMARY

$(printf "${YELLOW}")What is left is manual, in the Connect admin website:$(printf "${RESET}")

  1. AI agent designer → AI agents → my-conversation-agent → Edit.
     Add the tools send_push_challenge and verify_push_challenge.
     If they are not offered, remove the '${GATEWAY_NAME}' MCP integration
     from the agent and add it again: Connect caches a gateway's tool list.

  2. AI agent designer → AI prompts → ARIA-Banking-Ochestration-Prompt.
     Paste connect-idv-test-harness/prompts/aria-orchestration-prompt-v15.yaml,
     save and publish.

  3. Set the agent to the new prompt version and publish the agent.

  4. Routing → Flows → conversation bot flow: move both agent references
     (first Connect assistant block, and the Lex block's
     x-amz-lex:q-in-connect:ai-agent-arn attribute) to the new agent version.
     Save and publish.

  Details: connect-idv-test-harness/ORCHESTRATOR-PROMPT-CHANGES.md

SUMMARY
