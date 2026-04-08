#!/usr/bin/env bash
# =============================================================================
# deploy_session_injector_qconnect.sh
# =============================================================================
# Standalone deployment script for the aria-session-injector-qconnect Lambda.
#
# This script:
#   1. Creates (or updates) the IAM execution role with all Q Connect permissions
#   2. Packages and deploys the Lambda (create or update)
#   3. Publishes a numbered Lambda version
#   4. Creates or updates the "prod" alias pointing to that version
#   5. Grants Amazon Connect permission to invoke the Lambda
#
# Usage:
#   ./scripts/deploy_session_injector_qconnect.sh [OPTIONS]
#
# Options:
#   --assistant-id  ID       Q Connect assistant ID (REQUIRED)
#   --region        REGION   AWS region (default: eu-west-2)
#   --account-id    ID       AWS account ID (auto-detected if not set)
#   --instance-id   ID       Connect instance ID (optional; derived from events if not set)
#   --memory-table  NAME     DynamoDB table for prior session summaries (optional)
#   --crm-endpoint  URL      CRM API endpoint (optional; stub data used if not set)
#   --dry-run                Print what would be done without deploying
#   --help                   Show this help text
#
# Environment variable equivalents (flags take precedence):
#   ASSISTANT_ID, AWS_REGION, AWS_ACCOUNT_ID, INSTANCE_ID,
#   MEMORY_TABLE_NAME, CRM_API_ENDPOINT
#
# Requirements:
#   - AWS CLI v2 configured with credentials that can manage IAM, Lambda,
#     Connect permissions
#   - Python 3 and zip available on PATH
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
FUNCTION_NAME="aria-session-injector-qconnect"
ROLE_NAME="aria-lambda-session-injector-qconnect-role"
SOURCE_FILE="$(cd "$(dirname "$0")" && pwd)/lambdas/session_injector_qconnect.py"
ALIAS_NAME="prod"
DRY_RUN=false

REGION="${AWS_REGION:-eu-west-2}"
ACCOUNT_ID="${AWS_ACCOUNT_ID:-}"
ASSISTANT_ID="${ASSISTANT_ID:-}"
INSTANCE_ID="${INSTANCE_ID:-}"
MEMORY_TABLE_NAME="${MEMORY_TABLE_NAME:-}"
CRM_API_ENDPOINT="${CRM_API_ENDPOINT:-}"

# ── Argument parsing ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --assistant-id)  ASSISTANT_ID="$2"; shift 2 ;;
        --region)        REGION="$2";       shift 2 ;;
        --account-id)    ACCOUNT_ID="$2";   shift 2 ;;
        --instance-id)   INSTANCE_ID="$2";  shift 2 ;;
        --memory-table)  MEMORY_TABLE_NAME="$2"; shift 2 ;;
        --crm-endpoint)  CRM_API_ENDPOINT="$2";  shift 2 ;;
        --dry-run)       DRY_RUN=true; shift ;;
        --help|-h)
            sed -n '/^# Usage:/,/^# Requirements:/p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *) die "Unknown argument: $1. Run with --help for usage." ;;
    esac
done

# ── Validation ─────────────────────────────────────────────────────────────────
[[ -f "$SOURCE_FILE" ]] || die "Source file not found: ${SOURCE_FILE}"
[[ -z "$ASSISTANT_ID" ]] && die \
    "ASSISTANT_ID is required for the Q Connect variant.\n" \
    "  Pass --assistant-id <id>  or set the ASSISTANT_ID environment variable.\n" \
    "  Find it in: AWS Console → Amazon Connect → Amazon Q in Connect → Assistants"

command -v aws  >/dev/null 2>&1 || die "AWS CLI not found. Install aws-cli v2."
command -v zip  >/dev/null 2>&1 || die "zip not found. Install zip."
command -v python3 >/dev/null 2>&1 || die "python3 not found."

# ── Auto-detect account ID ─────────────────────────────────────────────────────
if [[ -z "$ACCOUNT_ID" ]]; then
    step "Auto-detecting AWS account ID..."
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) \
        || die "Could not detect account ID. Check AWS credentials."
    ok "Account ID: ${ACCOUNT_ID}"
fi

# ── Dry-run mode ───────────────────────────────────────────────────────────────
if $DRY_RUN; then
    warn "DRY-RUN mode — no AWS changes will be made."
    run() { echo "  [dry-run] $*"; }
else
    run() { "$@"; }
fi

# ── Helpers ─────────────────────────────────────────────────────────────────────
role_exists()   { aws iam get-role --role-name "$1" --query "Role.RoleName" --output text 2>/dev/null || true; }
lambda_exists() { aws lambda get-function --function-name "$1" --region "$REGION" --query "Configuration.FunctionName" --output text 2>/dev/null || true; }
alias_exists()  { aws lambda get-alias --function-name "$1" --name "$2" --region "$REGION" --query "Name" --output text 2>/dev/null || true; }

LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNCTION_NAME}"
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
ZIP_PATH="/tmp/${FUNCTION_NAME}.zip"

# =============================================================================
# Step 1 — IAM Role
# =============================================================================
header "Step 1 — IAM execution role"

if [[ -n "$(role_exists "$ROLE_NAME")" ]]; then
    warn "Role already exists — updating inline policy only: ${ROLE_NAME}"
else
    step "Creating IAM role: ${ROLE_NAME}"
    run aws iam create-role \
        --role-name "$ROLE_NAME" \
        --assume-role-policy-document '{
            "Version":"2012-10-17",
            "Statement":[{
                "Effect":"Allow",
                "Principal":{"Service":"lambda.amazonaws.com"},
                "Action":"sts:AssumeRole"
            }]
        }' \
        --query "Role.RoleName" --output text > /dev/null

    run aws iam attach-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"

    ok "Role created. Waiting 15s for IAM propagation..."
    $DRY_RUN || sleep 15
fi

# Apply (or replace) the inline policy that grants all required permissions
step "Applying inline permissions policy..."
run aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "SessionInjectorQConnectPolicy" \
    --policy-document "{
        \"Version\":\"2012-10-17\",
        \"Statement\":[
            {
                \"Sid\":\"ConnectRead\",
                \"Effect\":\"Allow\",
                \"Action\":[
                    \"connect:DescribeContact\",
                    \"connect:GetContactAttributes\"
                ],
                \"Resource\":\"arn:aws:connect:${REGION}:${ACCOUNT_ID}:instance/*\"
            },
            {
                \"Sid\":\"QConnectWrite\",
                \"Effect\":\"Allow\",
                \"Action\":[
                    \"qconnect:UpdateSessionData\",
                    \"qconnect:GetSession\",
                    \"wisdom:UpdateSessionData\",
                    \"wisdom:GetSession\"
                ],
                \"Resource\":[
                    \"arn:aws:wisdom:${REGION}:${ACCOUNT_ID}:assistant/*\",
                    \"arn:aws:wisdom:${REGION}:${ACCOUNT_ID}:session/*\"
                ]
            },
            {
                \"Sid\":\"DynamoDBMemoryRead\",
                \"Effect\":\"Allow\",
                \"Action\":[\"dynamodb:GetItem\"],
                \"Resource\":\"arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/*\"
            }
        ]
    }"

ok "IAM role ready: ${ROLE_ARN}"

# =============================================================================
# Step 2 — Build environment variables
# =============================================================================
header "Step 2 — Environment variables"

_VARS="{\"ASSISTANT_ID\":\"${ASSISTANT_ID}\""
[[ -n "$INSTANCE_ID"        ]] && _VARS="${_VARS},\"INSTANCE_ID\":\"${INSTANCE_ID}\""
[[ -n "$MEMORY_TABLE_NAME"  ]] && _VARS="${_VARS},\"MEMORY_TABLE_NAME\":\"${MEMORY_TABLE_NAME}\""
[[ -n "$CRM_API_ENDPOINT"   ]] && _VARS="${_VARS},\"CRM_API_ENDPOINT\":\"${CRM_API_ENDPOINT}\""
_VARS="${_VARS}}"
ENV_JSON="{\"Variables\":${_VARS}}"

echo "  ASSISTANT_ID    = ${ASSISTANT_ID}"
echo "  AWS_REGION      = ${REGION} (injected by Lambda runtime — not set as env var)"
[[ -n "$INSTANCE_ID"       ]] && echo "  INSTANCE_ID     = ${INSTANCE_ID}"
[[ -n "$MEMORY_TABLE_NAME" ]] && echo "  MEMORY_TABLE    = ${MEMORY_TABLE_NAME}"
[[ -n "$CRM_API_ENDPOINT"  ]] && echo "  CRM_ENDPOINT    = ${CRM_API_ENDPOINT}"

# =============================================================================
# Step 3 — Package Lambda
# =============================================================================
header "Step 3 — Packaging Lambda"

step "Zipping ${SOURCE_FILE} → ${ZIP_PATH}"
LAMBDA_DIR="$(dirname "$SOURCE_FILE")"
SOURCE_FILENAME="$(basename "$SOURCE_FILE")"
(cd "$LAMBDA_DIR" && zip -q "$ZIP_PATH" "$SOURCE_FILENAME")
ok "Package ready: ${ZIP_PATH} ($(du -h "$ZIP_PATH" | cut -f1))"

# The handler name must match the module (filename without .py) and the
# function name defined in session_injector_qconnect.py as `handler`.
HANDLER_NAME="${SOURCE_FILENAME%.py}.handler"

# =============================================================================
# Step 4 — Deploy Lambda (create or update)
# =============================================================================
header "Step 4 — Deploying Lambda: ${FUNCTION_NAME}"

if [[ -n "$(lambda_exists "$FUNCTION_NAME")" ]]; then
    step "Updating existing Lambda code..."
    run aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file "fileb://${ZIP_PATH}" \
        --region "$REGION" \
        --query "FunctionName" --output text > /dev/null

    step "Waiting for code update to complete..."
    $DRY_RUN || aws lambda wait function-updated \
        --function-name "$FUNCTION_NAME" \
        --region "$REGION" 2>/dev/null || true

    step "Updating Lambda configuration..."
    run aws lambda update-function-configuration \
        --function-name "$FUNCTION_NAME" \
        --environment "$ENV_JSON" \
        --handler "$HANDLER_NAME" \
        --timeout 30 \
        --region "$REGION" \
        --query "FunctionName" --output text > /dev/null

    step "Waiting for configuration update to complete..."
    $DRY_RUN || aws lambda wait function-updated \
        --function-name "$FUNCTION_NAME" \
        --region "$REGION" 2>/dev/null || true

else
    step "Creating new Lambda..."
    run aws lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --runtime python3.12 \
        --role "$ROLE_ARN" \
        --handler "$HANDLER_NAME" \
        --zip-file "fileb://${ZIP_PATH}" \
        --timeout 30 \
        --environment "$ENV_JSON" \
        --region "$REGION" \
        --query "FunctionName" --output text > /dev/null

    step "Waiting for Lambda to become active..."
    $DRY_RUN || aws lambda wait function-active \
        --function-name "$FUNCTION_NAME" \
        --region "$REGION" 2>/dev/null || true
fi

ok "Lambda deployed: ${LAMBDA_ARN}"

# =============================================================================
# Step 5 — Publish numbered version
# =============================================================================
header "Step 5 — Publishing Lambda version"

step "Publishing new version..."
VERSION_NUMBER=$($DRY_RUN && echo "1" || \
    aws lambda publish-version \
        --function-name "$FUNCTION_NAME" \
        --description "prod deployment $(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        --region "$REGION" \
        --query "Version" --output text)

ok "Published version: ${VERSION_NUMBER}"
VERSIONED_ARN="${LAMBDA_ARN}:${VERSION_NUMBER}"

# =============================================================================
# Step 6 — Create or update "prod" alias
# =============================================================================
header "Step 6 — '${ALIAS_NAME}' alias"

if [[ -n "$(alias_exists "$FUNCTION_NAME" "$ALIAS_NAME")" ]]; then
    step "Updating existing alias '${ALIAS_NAME}' → version ${VERSION_NUMBER}..."
    run aws lambda update-alias \
        --function-name "$FUNCTION_NAME" \
        --name "$ALIAS_NAME" \
        --function-version "$VERSION_NUMBER" \
        --description "prod alias updated $(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        --region "$REGION" \
        --query "AliasArn" --output text > /dev/null
else
    step "Creating alias '${ALIAS_NAME}' → version ${VERSION_NUMBER}..."
    run aws lambda create-alias \
        --function-name "$FUNCTION_NAME" \
        --name "$ALIAS_NAME" \
        --function-version "$VERSION_NUMBER" \
        --description "prod alias" \
        --region "$REGION" \
        --query "AliasArn" --output text > /dev/null
fi

ALIAS_ARN="${LAMBDA_ARN}:${ALIAS_NAME}"
ok "Alias ready: ${ALIAS_ARN}"

# =============================================================================
# Step 7 — Grant Amazon Connect permission to invoke via the prod alias
# =============================================================================
header "Step 7 — Connect invoke permission"

# We add the permission on the prod alias ARN, not the unqualified function,
# so Connect always invokes the published prod version.
step "Granting connect.amazonaws.com invoke permission on alias '${ALIAS_NAME}'..."
run aws lambda add-permission \
    --function-name "${LAMBDA_ARN}:${ALIAS_NAME}" \
    --statement-id  "ConnectInvokeProduction" \
    --action        "lambda:InvokeFunction" \
    --principal     "connect.amazonaws.com" \
    --source-account "${ACCOUNT_ID}" \
    --region        "$REGION" 2>/dev/null \
    || warn "Connect permission already set on alias (non-fatal)"

# Also ensure the base function allows Connect (needed for testing in console)
run aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id  "ConnectInvoke" \
    --action        "lambda:InvokeFunction" \
    --principal     "connect.amazonaws.com" \
    --source-account "${ACCOUNT_ID}" \
    --region        "$REGION" 2>/dev/null \
    || warn "Connect permission already set on function (non-fatal)"

ok "Connect permissions granted."

# =============================================================================
# Summary
# =============================================================================
header "Deployment complete"

cat <<EOF

  Function  : ${LAMBDA_ARN}
  Version   : ${VERSION_NUMBER}  (${VERSIONED_ARN})
  Alias     : ${ALIAS_ARN}
  Handler   : ${HANDLER_NAME}
  Runtime   : python3.12

  Environment:
    ASSISTANT_ID   = ${ASSISTANT_ID}
    AWS_REGION     = ${REGION}$(
    [[ -n "$INSTANCE_ID"       ]] && printf "\n    INSTANCE_ID    = %s" "$INSTANCE_ID"
    [[ -n "$MEMORY_TABLE_NAME" ]] && printf "\n    MEMORY_TABLE   = %s" "$MEMORY_TABLE_NAME"
    [[ -n "$CRM_API_ENDPOINT"  ]] && printf "\n    CRM_ENDPOINT   = %s" "$CRM_API_ENDPOINT"
)

  IAM role  : ${ROLE_ARN}
  Permissions granted:
    • connect:DescribeContact / GetContactAttributes
    • qconnect:UpdateSessionData / wisdom:UpdateSessionData
    • dynamodb:GetItem
    • AWSLambdaBasicExecutionRole (managed)

$(printf "${YELLOW}")Next steps:$(printf "${RESET}")
  1. In Connect admin → Contact flows → (your inbound flow):
       Add "Invoke AWS Lambda function" block AFTER the "Connect assistant" block.
       Select function: ${ALIAS_ARN}
       (Use the prod alias so new deployments take effect by re-running this script.)

  2. After the Lambda block, add a "Set contact attributes" block:
       Map all fields from the Lambda response ($.External.*) → contact attribute:

       ── Core identity ──────────────────────────────────────────────────────
       $.External.sessionId          → sessionId
       $.External.customerId         → customerId
       $.External.authStatus         → authStatus
       $.External.channel            → channel

       ── Customer context ───────────────────────────────────────────────────
       $.External.preferredName      → preferredName
       $.External.productSummary     → productSummary
       $.External.productContext     → productContext
       $.External.vulnerabilityContext → vulnerabilityContext
       $.External.priorSummary       → priorSummary

       ── Cross-channel transfer ─────────────────────────────────────────────
       $.External.priorChannel       → priorChannel
       $.External.priorContactId     → priorContactId
       $.External.priorTranscript    → priorTranscript

       ── Metadata ───────────────────────────────────────────────────────────
       $.External.locale             → locale
       $.External.dateTime           → dateTime
       $.External.instanceId         → instanceId

       Note: customerPhone is set separately by a "Store customer input" or
       "Set contact attributes" block using the System attribute
       $.CustomerEndpoint.Address (available on voice inbound calls).

  3. To re-deploy after code changes:
       ./scripts/deploy_session_injector_qconnect.sh \\
           --assistant-id ${ASSISTANT_ID} \\
           --region ${REGION}

EOF
