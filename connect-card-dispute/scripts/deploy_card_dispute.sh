#!/usr/bin/env bash
# =============================================================================
# deploy_card_dispute.sh
# =============================================================================
# Deploys the card dispute service: its table, its Lambda, the web address for
# the customer and adviser pages and for the CX designer disputes assistant's
# tools, and the read-only dispute tool for agent assist.
#
# YOU run this script. It makes changes in your AWS account:
#   1. DynamoDB table for disputes (created once, then left alone)
#   2. IAM role for the Lambda: read and write that one table, nothing else
#   3. Lambda aria-card-dispute (code and settings), and a key in Secrets
#      Manager that the CX designer assistant's Data requests must present
#   4. HTTP API in front of the Lambda, for the pages and the CX designer
#   5. Connect may call the Lambda from a flow (the hand-back to ARIA), and the
#      Lambda is added to the instance, so the flow's Lambda block can pick it
#   6. Gateway target aria-banking-dispute on the existing MCP gateway, with the
#      dispute tools, and permission for the gateway to call the Lambda
#   7. Tests: a tool call, the hand-back call, the pages and the CX designer door
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
#   --instance-id     ID      Connect instance ID         (default: f969d4b4-f716-4974-a325-bb7899f2f293)
#   --merchant-topic  TOPIC   Route "problem with a payment I made" disputes to
#                             this topic, e.g. fraud_security. Default: the
#                             card's own topic (debit_card / credit_card)
#   --sms-from        ID      AWS End User Messaging sender for texting the form
#                             link: a phone number, sender ID or pool, as its ID or
#                             ARN. Kept from the last run if not given. Without it
#                             the assistant says it cannot text, and carries on
#   --sms-prefixes    LIST    Comma-separated number prefixes a text may go to
#                             (default: +447, UK mobiles; kept from the last run)
#   --bank-name       NAME    How the text names the sender (default: "Your bank")
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
#   - npm, only for the Live Sync route (it fetches Amazon's Touchpoint library)
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
SMS_FROM=""
SMS_PREFIXES=""
BANK_NAME=""
INSTANCE_ID="${INSTANCE_ID:-f969d4b4-f716-4974-a325-bb7899f2f293}"
DO_GATEWAY=true
DRY_RUN=false

FUNCTION_NAME="aria-card-dispute"
ROLE_NAME="aria-lambda-card-dispute-role"
TABLE_NAME="aria-card-disputes"
API_NAME="aria-card-dispute-pages"
TARGET_NAME="aria-banking-dispute"
HANDLER_NAME="aria_card_dispute.lambda_handler"
ACXD_KEY_SECRET="aria-card-dispute/acxd-key"        # made by this script
TOUCHPOINT_SECRET="aria-card-dispute/touchpoint"    # made by you, once you have the keys (README step 7)
TOUCHPOINT_VERSION="1.0.1"                          # pinned; the version the mortgage page runs

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LAMBDA_DIR="${SCRIPT_DIR}/../lambda"
WEB_DIR="${SCRIPT_DIR}/../web"
TOOLS_FILE="${SCRIPT_DIR}/tool_schemas.json"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --region)         REGION="$2";         shift 2 ;;
        --account-id)     ACCOUNT_ID="$2";     shift 2 ;;
        --env)            ENV_NAME="$2";       shift 2 ;;
        --instance-id)    INSTANCE_ID="$2";    shift 2 ;;
        --merchant-topic) MERCHANT_TOPIC="$2"; shift 2 ;;
        --sms-from)       SMS_FROM="$2";       shift 2 ;;
        --sms-prefixes)   SMS_PREFIXES="$2";   shift 2 ;;
        --bank-name)      BANK_NAME="$2";      shift 2 ;;
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
[[ "$INSTANCE_ID" =~ ^[0-9a-f-]{36}$ ]] || die "--instance-id is not a Connect instance ID."
[[ "$SMS_FROM" =~ ^[A-Za-z0-9:/+_.-]*$ ]] || die "--sms-from must be a phone number, sender ID, pool ID or ARN."
[[ "$SMS_PREFIXES" =~ ^[+0-9,]*$ ]] || die "--sms-prefixes must be prefixes like +447, comma-separated."
[[ "$BANK_NAME" =~ ^[A-Za-z0-9\ \&.-]{0,30}$ ]] || die "--bank-name: letters, digits, spaces, & . - only, up to 30."

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

# Settings not given on the command line are kept from the last run, so running the
# script again never switches texting off.
current_setting() {      # "" on a first deploy, when the Lambda does not exist yet (and under pipefail)
    { aws lambda get-function-configuration --function-name "$FUNCTION_NAME" --region "$REGION" \
        --query "Environment.Variables.$1" --output text 2>/dev/null || true; } | first_value
}
[[ -n "$SMS_FROM" ]] || SMS_FROM=$(current_setting SMS_ORIGINATION_IDENTITY)
[[ -n "$SMS_PREFIXES" ]] || SMS_PREFIXES=$(current_setting SMS_ALLOWED_PREFIXES)
[[ -n "$BANK_NAME" ]] || BANK_NAME=$(current_setting BANK_NAME)

header "Deploying with"
echo "  Region    : ${REGION}"
echo "  Account   : ${ACCOUNT_ID}"
echo "  Function  : ${FUNCTION_NAME}"
echo "  Table     : ${TABLE_NAME}"
echo "  Gateway   : ${GATEWAY_NAME} $($DO_GATEWAY || echo '(skipped)')"
# No apostrophe may appear inside a ${VAR:-default}: bash would read it as opening a quoted string.
echo "  Merchant disputes go to: ${MERCHANT_TOPIC:-the topic of the card itself}"
echo "  Form link texts from    : ${SMS_FROM:-not set, so the assistant will not text}"

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
# Texting is allowed only once a sender is set.
SMS_STATEMENT=""
if [[ -n "$SMS_FROM" ]]; then
    SMS_STATEMENT=',
    {
      "Sid": "TextTheFormLink",
      "Effect": "Allow",
      "Action": "sms-voice:SendTextMessage",
      "Resource": "*"
    }'
fi
cat > "${BUILD_DIR}/policy.json" <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadAndWriteDisputes",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:PutItem"],
      "Resource": "${TABLE_ARN}"
    },
    {
      "Sid": "FindTheCustomerAndPhoneOfAContact",
      "Effect": "Allow",
      "Action": "connect:GetContactAttributes",
      "Resource": "arn:aws:connect:${REGION}:${ACCOUNT_ID}:instance/${INSTANCE_ID}/contact/*"
    },
    {
      "Sid": "ReadItsOwnTwoSecrets",
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": [
        "arn:aws:secretsmanager:${REGION}:${ACCOUNT_ID}:secret:${ACXD_KEY_SECRET}-??????",
        "arn:aws:secretsmanager:${REGION}:${ACCOUNT_ID}:secret:${TOUCHPOINT_SECRET}-??????"
      ]
    }${SMS_STATEMENT}
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
# The sample bank's one copy of its customers, cards and payments (dispute_model reads it).
mkdir -p "${BUILD_DIR}/package/moneyhub"
cp "${SCRIPT_DIR}/../../connect-money-hub/moneyhub/__init__.py" "${SCRIPT_DIR}/../../connect-money-hub/moneyhub/data.py" \
    "${BUILD_DIR}/package/moneyhub/"
cp "$WEB_DIR"/*.html "$WEB_DIR"/*.js "$WEB_DIR"/*.css "${BUILD_DIR}/package/web/"

# The Live Sync route needs Amazon's Touchpoint library on the customer page. It
# is fetched from npm at a pinned version and served by the Lambda. Without it the
# page still works as a form the customer fills in by hand.
if command -v npm >/dev/null 2>&1; then
    step "Fetching the Touchpoint library ${TOUCHPOINT_VERSION}..."
    mkdir -p "${BUILD_DIR}/touchpoint" "${BUILD_DIR}/package/web/vendor/touchpoint-${TOUCHPOINT_VERSION}"
    if (cd "${BUILD_DIR}/touchpoint" && npm init -y >/dev/null 2>&1 \
            && npm install --no-save --silent "@amazon-connect-touchpoint/web@${TOUCHPOINT_VERSION}" >/dev/null 2>&1); then
        cp "${BUILD_DIR}/touchpoint/node_modules/@amazon-connect-touchpoint/web/lib/"*.js \
            "${BUILD_DIR}/package/web/vendor/touchpoint-${TOUCHPOINT_VERSION}/"
        ok "Touchpoint library added to the package."
    else
        warn "Could not fetch the Touchpoint library. Live Sync will be off; everything else works."
    fi
else
    warn "npm not found, so the Touchpoint library was not added. Live Sync will be off; everything else works."
fi
(cd "${BUILD_DIR}/package" && zip -qr "$ZIP_PATH" .)
ok "Package ready: $(cd "${BUILD_DIR}/package" && find . -type f | wc -l | tr -d ' ') files"

# Writes the Lambda's settings file. PUBLIC_BASE_URL is empty until step 4 knows it.
write_env() {
    TABLE_NAME="$TABLE_NAME" PUBLIC_BASE_URL="$1" MERCHANT_TOPIC="$MERCHANT_TOPIC" INSTANCE_ID="$INSTANCE_ID" \
    ACXD_KEY_SECRET="$ACXD_KEY_SECRET" TOUCHPOINT_SECRET="$TOUCHPOINT_SECRET_IN_USE" \
    SMS_FROM="$SMS_FROM" SMS_PREFIXES="$SMS_PREFIXES" BANK_NAME="$BANK_NAME" \
        python3 - > "${BUILD_DIR}/env.json" <<'PY'
import json, os
variables = {"DISPUTE_TABLE_NAME": os.environ["TABLE_NAME"], "CONNECT_INSTANCE_ID": os.environ["INSTANCE_ID"],
             "ACXD_KEY_SECRET_ID": os.environ["ACXD_KEY_SECRET"]}
for name, key in (("PUBLIC_BASE_URL", "PUBLIC_BASE_URL"), ("MERCHANT_TOPIC", "MERCHANT_DISPUTE_TOPIC"),
                  ("TOUCHPOINT_SECRET", "TOUCHPOINT_SECRET_ID"), ("SMS_FROM", "SMS_ORIGINATION_IDENTITY"),
                  ("SMS_PREFIXES", "SMS_ALLOWED_PREFIXES"), ("BANK_NAME", "BANK_NAME")):
    if os.environ.get(name):
        variables[key] = os.environ[name]
print(json.dumps({"Variables": variables}))
PY
}

# The key the CX designer assistant's Data requests must present. Made once,
# by this script, straight into Secrets Manager. The script never reads it back.
if aws secretsmanager describe-secret --secret-id "$ACXD_KEY_SECRET" --region "$REGION" >/dev/null 2>&1; then
    ok "CX designer key already exists: ${ACXD_KEY_SECRET} (kept as it is)"
else
    step "Creating the CX designer key..."
    (umask 077; python3 -c 'import secrets; print(secrets.token_urlsafe(32), end="")' > "${BUILD_DIR}/acxd-key")
    run aws secretsmanager create-secret --name "$ACXD_KEY_SECRET" --region "$REGION" \
        --description "Key the CX designer card-dispute agent presents to aria-card-dispute" \
        --secret-string "file://${BUILD_DIR}/acxd-key" --query "Name" --output text > /dev/null
    rm -f "${BUILD_DIR}/acxd-key"
    ok "CX designer key created: ${ACXD_KEY_SECRET}"
fi

# The Live Sync keys for the page come from your CX designer application, so only
# you can create this secret (README step 7). Until it exists the page is a plain form.
TOUCHPOINT_SECRET_IN_USE=""
if aws secretsmanager describe-secret --secret-id "$TOUCHPOINT_SECRET" --region "$REGION" >/dev/null 2>&1; then
    TOUCHPOINT_SECRET_IN_USE="$TOUCHPOINT_SECRET"
    ok "Live Sync keys found: ${TOUCHPOINT_SECRET}"
else
    warn "No Live Sync keys yet (${TOUCHPOINT_SECRET}). The page works as a form; Live Sync stays off until you add them."
fi
apply_env() {
    run aws lambda update-function-configuration --function-name "$FUNCTION_NAME" --region "$REGION" \
        --environment "file://${BUILD_DIR}/env.json" --handler "$HANDLER_NAME" --timeout 10 --memory-size 512 \
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
        --zip-file "fileb://${ZIP_PATH}" --timeout 10 --memory-size 512 --environment "file://${BUILD_DIR}/env.json" \
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
API_URL="https://${API_ID}.execute-api.${REGION}.amazonaws.com"
PAGE_URL="$API_URL"
# If CloudFront has been put in front of the pages (deploy_pages_cloudfront.sh),
# customers and advisers use its address, and links are built with it.
CF_DOMAIN=$(aws cloudfront list-distributions \
    --query "DistributionList.Items[?Comment=='${API_NAME}'].DomainName" --output text 2>/dev/null | first_value)
if [[ -n "$CF_DOMAIN" ]]; then
    PAGE_URL="https://${CF_DOMAIN}"
    ok "CloudFront is in front of the pages: ${PAGE_URL}"
fi

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
# Step 5 — Connect may call the Lambda from a flow
# =============================================================================
header "Step 5 — Connect flows may call ${FUNCTION_NAME}"

# The "Card dispute assistant" flow calls the Lambda when the assistant hands the
# call back. Only this Connect instance may, and the Lambda must be added to the
# instance before a flow's Lambda block can choose it.
INSTANCE_ARN="arn:aws:connect:${REGION}:${ACCOUNT_ID}:instance/${INSTANCE_ID}"
run aws lambda add-permission --function-name "$FUNCTION_NAME" --region "$REGION" \
    --statement-id "ConnectFlowInvoke" --action "lambda:InvokeFunction" --principal "connect.amazonaws.com" \
    --source-account "$ACCOUNT_ID" --source-arn "$INSTANCE_ARN" \
    >/dev/null 2>&1 || warn "Connect's invoke permission is already set (non-fatal)"
associated=$({ aws connect list-lambda-functions --instance-id "$INSTANCE_ID" --region "$REGION" \
    --query "LambdaFunctions[?@=='${LAMBDA_ARN}']" --output text 2>/dev/null || true; } | first_value)
if [[ -n "$associated" ]]; then
    ok "Already added to the Connect instance."
else
    run aws connect associate-lambda-function --instance-id "$INSTANCE_ID" --region "$REGION" \
        --function-arn "$LAMBDA_ARN"
    ok "Added to the Connect instance."
fi

# =============================================================================
# Step 6 — The read-only dispute tool on the MCP gateway
# =============================================================================
header "Step 6 — MCP gateway target: ${TARGET_NAME}"

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
# Step 7 — Tests
# =============================================================================
header "Step 7 — Testing"

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

    # The hand-back call, the way the Connect flow makes it. An unverified test contact: reads, writes nothing.
    echo '{"Name":"ContactFlowEvent","Details":{"ContactData":{"Attributes":{}},"Parameters":{"operation":"handover"}}}' \
        > "${BUILD_DIR}/handover.json"
    aws lambda invoke --function-name "$FUNCTION_NAME" --region "$REGION" --cli-binary-format raw-in-base64-out \
        --payload "file://${BUILD_DIR}/handover.json" "${BUILD_DIR}/handover-out.json" >/dev/null
    topic=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("topicCategory",""))' "${BUILD_DIR}/handover-out.json")
    [[ "$topic" == "fraud_security" ]] || die "The hand-back call did not answer as expected: $(cat "${BUILD_DIR}/handover-out.json")"
    ok "The hand-back call works (an unknown caller goes to fraud_security)."

    # The CX designer door refuses a request without the key. (The right key is only in Secrets Manager.)
    code=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'content-type: application/json' \
        -d '{"operation":"listCardsAndPayments"}' "${API_URL}/acxd/ops" || true)
    [[ "$code" == "401" ]] || die "The CX designer door answered HTTP ${code} without a key; expected 401."
    ok "The CX designer door is up and refuses requests without the key."
fi

# =============================================================================
# Summary
# =============================================================================
header "Done"

cat <<SUMMARY

  Customer page : ${PAGE_URL}/
  Lambda        : ${FUNCTION_NAME}
  Table         : ${TABLE_NAME}

  For the CX designer disputes assistant (acxd/disputes-assistant.md):
    Data request address : ${API_URL}/acxd/ops
    Its key              : Secrets Manager secret ${ACXD_KEY_SECRET}
    Live Sync keys       : ${TOUCHPOINT_SECRET_IN_USE:-not set yet; create secret ${TOUCHPOINT_SECRET} and run this again}
    Form link texts      : ${SMS_FROM:-off; run again with --sms-from to switch on}

$(printf "${YELLOW}")What is left, in this order (connect-card-dispute/README.md, "Set it up"):$(printf "${RESET}")

  1. ./connect-agent-assist/scripts/deploy_agent_assist.sh   (screen pop reads disputes)
  2. Build the "Card dispute" application in the CX designer (acxd/disputes-assistant.md)
  3. Store its Live Sync keys as secret ${TOUCHPOINT_SECRET}, then run this script again
  4. python3 connect-card-dispute/flows/build_card_dispute_flow.py --application-id <id> --alias <alias>
     and import connect-card-dispute/flows/card-dispute-flow.json as "Card dispute assistant"
  5. ARIA: the StartCardDispute tool, and the prompt from
       python3 connect-card-dispute/scripts/build_aria_prompt.py --mode cx
  6. conversation bot flow: one StartCardDispute branch, then point it at ARIA's new version
     (If ARIA has the Money Hub collaborator, skip 5-6: StartCardDispute can't hand over then.
      Follow connect-money-hub/docs/collaborator-setup.md, "Hand-overs while ARIA has collaborators".)
  7. Import the screen pop; give the agent-assist agents get_card_dispute

SUMMARY
