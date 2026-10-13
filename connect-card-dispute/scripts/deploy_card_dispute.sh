#!/usr/bin/env bash
# =============================================================================
# deploy_card_dispute.sh
# =============================================================================
# Deploys the card dispute service: its table, its Lambda, the web address for
# the customer and adviser pages, and ARIA's five dispute tools.
#
# YOU run this script. It makes changes in your AWS account:
#   1. DynamoDB table for disputes (created once, then left alone)
#   2. IAM role for the Lambda: read and write that one table, nothing else
#   3. Lambda aria-card-dispute (code and settings)
#   4. HTTP API in front of the Lambda, for the two web pages
#   5. Gateway target aria-banking-dispute on the existing MCP gateway, with the
#      five tools, and permission for the gateway to call the Lambda
#   6. Tests: one tool call and one page request
#
# It uses the AWS CLI only. It does NOT change any AI agent, prompt or contact
# flow. Those are the manual steps printed at the end and written up in
# connect-card-dispute/README.md.
#
# Safe to run again: it updates what exists and creates only what is missing.
#
# Usage:
#   ./connect-card-dispute/scripts/deploy_card_dispute.sh [OPTIONS]
#
# With no options it targets the prod ARIA tools in eu-west-2.
#
# Options:
#   --region          REGION  AWS region                  (default: eu-west-2)
#   --account-id      ID      AWS account ID              (default: 395402194296)
#   --env             ENV     Gateway environment suffix  (default: prod)
#   --merchant-topic  TOPIC   Route "problem with a payment I made" disputes to
#                             this topic, e.g. fraud_security. Default: the
#                             card's own topic (debit_card / credit_card)
#   --skip-gateway            Do not touch the MCP gateway
#   --dry-run                 Print what would be done without changing anything
#   --help                    Show this help text
#
# Environment variable equivalents (flags take precedence):
#   AWS_REGION, AWS_ACCOUNT_ID, ARIA_ENV
#
# Requirements:
#   - AWS CLI v2.27 or later (needs the bedrock-agentcore-control commands)
#   - python3 (standard library only), zip and curl on PATH
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

die()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; exit 1; }
warn()  { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
step()  { echo -e "${CYAN}[....] $*${RESET}"; }
ok()    { echo -e "${GREEN}[ OK ] $*${RESET}"; }
header(){ echo -e "\n${BOLD}━━━ $* ━━━${RESET}"; }

# ── Defaults ───────────────────────────────────────────────────────────────────
REGION="${AWS_REGION:-eu-west-2}"
ACCOUNT_ID="${AWS_ACCOUNT_ID:-395402194296}"
ENV_NAME="${ARIA_ENV:-prod}"
MERCHANT_TOPIC=""
DO_GATEWAY=true
DRY_RUN=false

FUNCTION_NAME="aria-card-dispute"
ROLE_NAME="aria-lambda-card-dispute-role"
TABLE_NAME="aria-card-disputes"
API_NAME="aria-card-dispute-pages"
TARGET_NAME="aria-banking-dispute"
HANDLER_NAME="aria_card_dispute.lambda_handler"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LAMBDA_DIR="${SCRIPT_DIR}/../lambda"
WEB_DIR="${SCRIPT_DIR}/../web"
TOOLS_FILE="${SCRIPT_DIR}/tool_schemas.json"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --region)         REGION="$2";         shift 2 ;;
        --account-id)     ACCOUNT_ID="$2";     shift 2 ;;
        --env)            ENV_NAME="$2";       shift 2 ;;
        --merchant-topic) MERCHANT_TOPIC="$2"; shift 2 ;;
        --skip-gateway)   DO_GATEWAY=false; shift ;;
        --dry-run)        DRY_RUN=true; shift ;;
        --help|-h)
            sed -n '/^# Usage:/,/^# Requirements:/p' "$0" | sed -E 's/^# ?//'
            exit 0
            ;;
        *) die "Unknown argument: $1. Run with --help for usage." ;;
    esac
done

GATEWAY_NAME="aria-banking-mcp-gateway-${ENV_NAME}"
GATEWAY_ROLE_NAME="aria-banking-mcp-gateway-role-${ENV_NAME}"

# ── Validation ─────────────────────────────────────────────────────────────────
for tool in aws zip python3 curl; do
    command -v "$tool" >/dev/null 2>&1 || die "${tool} not found on PATH."
done
[[ -f "$TOOLS_FILE" ]] || die "Tool definitions not found: ${TOOLS_FILE}"
for source in "$LAMBDA_DIR"/*.py; do
    python3 -m py_compile "$source" || die "$(basename "$source") does not compile."
done
[[ "$MERCHANT_TOPIC" =~ ^[a-z_]*$ ]] || die "--merchant-topic must be lower-case letters and underscores."

step "Checking AWS credentials..."
CALLER_ACCOUNT=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) \
    || die "Could not read AWS credentials. Sign in with the AWS CLI first."
[[ "$CALLER_ACCOUNT" == "$ACCOUNT_ID" ]] || die \
    "Your AWS credentials are for account ${CALLER_ACCOUNT}, but the target is ${ACCOUNT_ID}.\n" \
    "  Sign in to ${ACCOUNT_ID}, or pass --account-id ${CALLER_ACCOUNT} to deploy there instead."
ok "Signed in to account ${ACCOUNT_ID}"

if $DRY_RUN; then
    warn "DRY-RUN mode — no AWS changes will be made."
    run() { echo "  [dry-run] $*"; }
else
    run() { "$@"; }
fi

LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNCTION_NAME}"
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
TABLE_ARN="arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${TABLE_NAME}"
BUILD_DIR="$(mktemp -d)"
ZIP_PATH="${BUILD_DIR}/${FUNCTION_NAME}.zip"
trap 'rm -rf "$BUILD_DIR"' EXIT

# List calls are paginated, and the CLI applies --query to each page and prints
# one line per page. Collect every match and take the first real value.
first_value() { tr -s '[:space:]' '\n' | grep -v -e '^None$' -e '^$' | head -n 1 || true; }

header "Deploying with"
echo "  Region    : ${REGION}"
echo "  Account   : ${ACCOUNT_ID}"
echo "  Function  : ${FUNCTION_NAME}"
echo "  Table     : ${TABLE_NAME}"
echo "  Gateway   : ${GATEWAY_NAME} $($DO_GATEWAY || echo '(skipped)')"
# No apostrophe may appear inside a ${VAR:-default}: bash would read it as opening a quoted string.
echo "  Merchant disputes go to: ${MERCHANT_TOPIC:-the topic of the card itself}"

# =============================================================================
# Step 1 — Table
# =============================================================================
header "Step 1 — DynamoDB table"

if aws dynamodb describe-table --table-name "$TABLE_NAME" --region "$REGION" >/dev/null 2>&1; then
    ok "Table already exists: ${TABLE_NAME}"
else
    step "Creating table ${TABLE_NAME}..."
    run aws dynamodb create-table --table-name "$TABLE_NAME" --region "$REGION" \
        --attribute-definitions AttributeName=pk,AttributeType=S \
        --key-schema AttributeName=pk,KeyType=HASH --billing-mode PAY_PER_REQUEST \
        --query "TableDescription.TableName" --output text > /dev/null
    $DRY_RUN || aws dynamodb wait table-exists --table-name "$TABLE_NAME" --region "$REGION"
    ok "Table created."
fi
# Codes, page sessions and adviser links carry "ttl"; DynamoDB clears them up later.
ttl_status=$(aws dynamodb describe-time-to-live --table-name "$TABLE_NAME" --region "$REGION" \
    --query "TimeToLiveDescription.TimeToLiveStatus" --output text 2>/dev/null || echo "UNKNOWN")
if [[ "$ttl_status" == "ENABLED" || "$ttl_status" == "ENABLING" ]]; then
    ok "Time-to-live is on."
else
    run aws dynamodb update-time-to-live --table-name "$TABLE_NAME" --region "$REGION" \
        --time-to-live-specification "Enabled=true,AttributeName=ttl" >/dev/null
    ok "Time-to-live switched on."
fi

# =============================================================================
# Step 2 — IAM role
# =============================================================================
header "Step 2 — IAM execution role"

if aws iam get-role --role-name "$ROLE_NAME" --query "Role.RoleName" --output text >/dev/null 2>&1; then
    warn "Role already exists — updating its permissions only: ${ROLE_NAME}"
else
    step "Creating IAM role: ${ROLE_NAME}"
    run aws iam create-role --role-name "$ROLE_NAME" \
        --assume-role-policy-document '{
            "Version":"2012-10-17",
            "Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]
        }' --query "Role.RoleName" --output text > /dev/null
    run aws iam attach-role-policy --role-name "$ROLE_NAME" \
        --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
    ok "Role created. Waiting 15s for IAM propagation..."
    $DRY_RUN || sleep 15
fi

# Read and write single items in one table. No scans, no deletes, nothing else.
cat > "${BUILD_DIR}/policy.json" <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadAndWriteDisputes",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:PutItem"],
      "Resource": "${TABLE_ARN}"
    }
  ]
}
POLICY
run aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name "CardDisputePolicy" \
    --policy-document "file://${BUILD_DIR}/policy.json"
ok "IAM role ready: ${ROLE_ARN}"

# =============================================================================
# Step 3 — Lambda
# =============================================================================
header "Step 3 — Lambda: ${FUNCTION_NAME}"

mkdir -p "${BUILD_DIR}/package/web"
cp "$LAMBDA_DIR"/*.py "${BUILD_DIR}/package/"
cp "$WEB_DIR"/* "${BUILD_DIR}/package/web/"
(cd "${BUILD_DIR}/package" && zip -qr "$ZIP_PATH" .)
ok "Package ready: $(cd "${BUILD_DIR}/package" && find . -type f | sed 's|^\./||' | sort | tr '\n' ' ')"

# Writes the Lambda's settings file. PUBLIC_BASE_URL is empty until step 4 knows it.
write_env() {
    TABLE_NAME="$TABLE_NAME" PUBLIC_BASE_URL="$1" MERCHANT_TOPIC="$MERCHANT_TOPIC" python3 - > "${BUILD_DIR}/env.json" <<'PY'
import json, os
variables = {"DISPUTE_TABLE_NAME": os.environ["TABLE_NAME"]}
for name, key in (("PUBLIC_BASE_URL", "PUBLIC_BASE_URL"), ("MERCHANT_TOPIC", "MERCHANT_DISPUTE_TOPIC")):
    if os.environ.get(name):
        variables[key] = os.environ[name]
print(json.dumps({"Variables": variables}))
PY
}
apply_env() {
    run aws lambda update-function-configuration --function-name "$FUNCTION_NAME" --region "$REGION" \
        --environment "file://${BUILD_DIR}/env.json" --handler "$HANDLER_NAME" --timeout 10 \
        --query "FunctionName" --output text > /dev/null
    $DRY_RUN || aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
}

write_env ""
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" >/dev/null 2>&1; then
    step "Updating existing Lambda code..."
    run aws lambda update-function-code --function-name "$FUNCTION_NAME" --region "$REGION" \
        --zip-file "fileb://${ZIP_PATH}" --query "FunctionName" --output text > /dev/null
    $DRY_RUN || aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
else
    step "Creating new Lambda..."
    run aws lambda create-function --function-name "$FUNCTION_NAME" --region "$REGION" \
        --runtime python3.12 --role "$ROLE_ARN" --handler "$HANDLER_NAME" \
        --zip-file "fileb://${ZIP_PATH}" --timeout 10 --environment "file://${BUILD_DIR}/env.json" \
        --query "FunctionName" --output text > /dev/null
    $DRY_RUN || aws lambda wait function-active --function-name "$FUNCTION_NAME" --region "$REGION"
fi
ok "Lambda code deployed: ${LAMBDA_ARN}"

# =============================================================================
# Step 4 — Web address for the pages
# =============================================================================
header "Step 4 — HTTP API for the customer and adviser pages"

API_ID=$(aws apigatewayv2 get-apis --region "$REGION" \
    --query "Items[?Name=='${API_NAME}'].ApiId" --output text | first_value)
if [[ -n "$API_ID" ]]; then
    ok "HTTP API already exists: ${API_ID}"
elif $DRY_RUN; then
    echo "  [dry-run] aws apigatewayv2 create-api --name ${API_NAME} --protocol-type HTTP --target ${LAMBDA_ARN}"
    API_ID="dryrunapi"
else
    step "Creating HTTP API ${API_NAME}..."
    API_ID=$(aws apigatewayv2 create-api --name "$API_NAME" --protocol-type HTTP --region "$REGION" \
        --target "$LAMBDA_ARN" --query "ApiId" --output text)
    ok "HTTP API created: ${API_ID}"
fi
PAGE_URL="https://${API_ID}.execute-api.${REGION}.amazonaws.com"

# Only this API may call the Lambda over the web, and never faster than this.
run aws lambda add-permission --function-name "$FUNCTION_NAME" --region "$REGION" \
    --statement-id "PagesApiInvoke" --action "lambda:InvokeFunction" --principal "apigateway.amazonaws.com" \
    --source-arn "arn:aws:execute-api:${REGION}:${ACCOUNT_ID}:${API_ID}/*" \
    >/dev/null 2>&1 || warn "The API's invoke permission is already set (non-fatal)"
run aws apigatewayv2 update-stage --api-id "$API_ID" --stage-name '$default' --region "$REGION" \
    --default-route-settings "ThrottlingBurstLimit=40,ThrottlingRateLimit=20" >/dev/null
ok "Pages limited to 20 requests a second."

step "Telling the Lambda its own web address..."
write_env "$PAGE_URL"
apply_env
ok "Customer page : ${PAGE_URL}/"
ok "Adviser page  : opened from the screen pop (${PAGE_URL}/adviser#<link token>)"

# =============================================================================
# Step 5 — ARIA's tools on the MCP gateway
# =============================================================================
header "Step 5 — MCP gateway target: ${TARGET_NAME}"

if ! $DO_GATEWAY; then
    warn "Skipped (--skip-gateway)."
else
    GATEWAY_ID=$(aws bedrock-agentcore-control list-gateways --region "$REGION" \
        --query "items[?name=='${GATEWAY_NAME}'].gatewayId" --output text | first_value)
    [[ -n "$GATEWAY_ID" ]] || die "Gateway not found: ${GATEWAY_NAME}"

    # The gateway calls tool Lambdas with its own role, one named permission per extra tool Lambda.
    cat > "${BUILD_DIR}/gateway-policy.json" <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "lambda:InvokeFunction",
    "Resource": ["${LAMBDA_ARN}", "${LAMBDA_ARN}:*"]
  }]
}
POLICY
    run aws iam put-role-policy --role-name "$GATEWAY_ROLE_NAME" --policy-name "invoke-card-dispute-tool" \
        --policy-document "file://${BUILD_DIR}/gateway-policy.json"
    ok "Gateway role may call the Lambda."

    LAMBDA_ARN="$LAMBDA_ARN" python3 - "$TOOLS_FILE" > "${BUILD_DIR}/target-config.json" <<'PY'
import json, os, sys
print(json.dumps({"mcp": {"lambda": {"lambdaArn": os.environ["LAMBDA_ARN"],
                                     "toolSchema": {"inlinePayload": json.load(open(sys.argv[1]))}}}}))
PY
    echo '[{"credentialProviderType": "GATEWAY_IAM_ROLE"}]' > "${BUILD_DIR}/target-creds.json"

    TARGET_ID=$(aws bedrock-agentcore-control list-gateway-targets --gateway-identifier "$GATEWAY_ID" \
        --region "$REGION" --query "items[?name=='${TARGET_NAME}'].targetId" --output text | first_value)
    if [[ -n "$TARGET_ID" ]]; then
        step "Updating existing target ${TARGET_ID}..."
        run aws bedrock-agentcore-control update-gateway-target --region "$REGION" \
            --gateway-identifier "$GATEWAY_ID" --target-id "$TARGET_ID" \
            --name "$TARGET_NAME" --description "ARIA card dispute tools" \
            --target-configuration "file://${BUILD_DIR}/target-config.json" \
            --credential-provider-configurations "file://${BUILD_DIR}/target-creds.json" \
            --query "status" --output text > /dev/null
    elif $DRY_RUN; then
        echo "  [dry-run] aws bedrock-agentcore-control create-gateway-target --name ${TARGET_NAME}"
    else
        step "Creating target ${TARGET_NAME}..."
        # A role policy takes a few seconds to apply; the gateway checks it on create.
        sleep 10
        TARGET_ID=$(aws bedrock-agentcore-control create-gateway-target --region "$REGION" \
            --gateway-identifier "$GATEWAY_ID" --name "$TARGET_NAME" --description "ARIA card dispute tools" \
            --target-configuration "file://${BUILD_DIR}/target-config.json" \
            --credential-provider-configurations "file://${BUILD_DIR}/target-creds.json" \
            --query "targetId" --output text)
    fi

    if ! $DRY_RUN; then
        step "Waiting for the target to be READY..."
        status=""
        for _ in $(seq 1 30); do
            status=$(aws bedrock-agentcore-control get-gateway-target --gateway-identifier "$GATEWAY_ID" \
                --target-id "$TARGET_ID" --region "$REGION" --query "status" --output text)
            [[ "$status" == "READY" ]] && break
            [[ "$status" == *FAILED* ]] && die "The target failed (status ${status}). Check the gateway in the console."
            sleep 4
        done
        [[ "$status" == "READY" ]] || die "The target is still ${status} after two minutes. Check the gateway in the console."
        published=$(aws bedrock-agentcore-control get-gateway-target --gateway-identifier "$GATEWAY_ID" \
            --target-id "$TARGET_ID" --region "$REGION" \
            --query "targetConfiguration.mcp.lambda.toolSchema.inlinePayload[].name" --output text)
        ok "Gateway target READY with: $(echo $published)"
    fi
fi

# =============================================================================
# Step 6 — Tests
# =============================================================================
header "Step 6 — Testing"

if $DRY_RUN; then
    warn "Skipped in dry-run."
else
    # A tool call, the way the gateway makes one. Reads test transactions; writes nothing.
    echo '{"jsonrpc":"2.0","params":{"name":"aria-banking-dispute___list_card_transactions","arguments":{"customer_id":"CUST-001"}}}' \
        > "${BUILD_DIR}/payload.json"
    function_error=$(aws lambda invoke --function-name "$FUNCTION_NAME" --region "$REGION" \
        --cli-binary-format raw-in-base64-out --payload "file://${BUILD_DIR}/payload.json" \
        "${BUILD_DIR}/out.json" --query "FunctionError" --output text)
    count=$(python3 -c 'import json,sys; v=json.load(open(sys.argv[1])); print(len(v.get("transactions",[])) if isinstance(v,dict) else 0)' "${BUILD_DIR}/out.json")
    [[ "$function_error" == "None" && "$count" -gt 0 ]] \
        || die "Tool call failed (FunctionError=${function_error}): $(cat "${BUILD_DIR}/out.json")"
    ok "Tool call works: list_card_transactions returned ${count} test transactions."

    # The customer page, the way a browser asks for it. A new API can take a few seconds to answer.
    code=""
    for _ in 1 2 3 4 5 6; do
        code=$(curl -s -o "${BUILD_DIR}/page.html" -w '%{http_code}' "${PAGE_URL}/" || true)
        [[ "$code" == "200" ]] && break
        sleep 3
    done
    [[ "$code" == "200" ]] && grep -q "Read this code to us" "${BUILD_DIR}/page.html" \
        || die "The customer page did not load (HTTP ${code}) at ${PAGE_URL}/"
    ok "Customer page loads at ${PAGE_URL}/"

    # A page asking for its code. This writes one short-lived code to the table, which proves the role.
    code=$(curl -s -o "${BUILD_DIR}/screen.json" -w '%{http_code}' -X POST -H 'content-type: application/json' \
        -d '{}' "${PAGE_URL}/api/screen" || true)
    [[ "$code" == "200" ]] || die "The page could not get a code (HTTP ${code}). Check the Lambda's log."
    ok "The page can get a code, so the Lambda can read and write its table."
fi

# =============================================================================
# Summary
# =============================================================================
header "Done"

cat <<SUMMARY

  Customer page : ${PAGE_URL}/
  Lambda        : ${FUNCTION_NAME}
  Table         : ${TABLE_NAME}

$(printf "${YELLOW}")What is left, in this order (details in connect-card-dispute/README.md):$(printf "${RESET}")

  1. Run the agent-assist deploy script again, so the adviser's screen pop
     can ask this Lambda about a customer's dispute:
       ./connect-agent-assist/scripts/deploy_agent_assist.sh

  2. Give ARIA the five tools (README Part C): AI agent designer, AI agents,
     my-conversation-agent, add the tools from aria-banking-dispute.

  3. Build ARIA's new prompt and paste it (README Part D):
       python3 connect-card-dispute/scripts/build_aria_prompt.py

  4. Give the agent-assist agents the read-only tool get_card_dispute (README Part E).

  5. Import the new screen pop (README Part F).

SUMMARY
