#!/usr/bin/env bash
# =============================================================================
# deploy_idv_test_harness.sh
# =============================================================================
# Deployment script for the aria-idv-test-harness Lambda (TEST TOOL ONLY).
#
# YOU run this script. It makes changes in your AWS account:
#   1. Creates (or reuses) an IAM execution role with CloudWatch Logs access only
#   2. Packages the harness code together with session_injector_qconnect.py
#      (the harness imports its test customers from that file)
#   3. Creates or updates the Lambda
#   4. Grants Amazon Connect permission to invoke it
#
# It does NOT create or change any contact flow, and it does NOT touch the
# aria-session-injector-qconnect Lambda. See ../README.md for those steps.
#
# Usage:
#   ./connect-idv-test-harness/scripts/deploy_idv_test_harness.sh [OPTIONS]
#
# Options:
#   --instance-id   ID       Connect instance ID (recommended; scopes the invoke permission)
#   --region        REGION   AWS region (default: eu-west-2)
#   --account-id    ID       AWS account ID (auto-detected if not set)
#   --secret        VALUE    Signing secret, 16+ characters (generated if not set)
#   --bank-name     NAME     Spoken bank name (default: Meridian Bank)
#   --dry-run                Print what would be done without deploying
#   --help                   Show this help text
#
# Environment variable equivalents (flags take precedence):
#   INSTANCE_ID, AWS_REGION, AWS_ACCOUNT_ID, IDV_TEST_SIGNING_SECRET, BANK_NAME
#
# Requirements:
#   - AWS CLI v2 configured with credentials that can manage IAM and Lambda
#   - zip and openssl available on PATH
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
FUNCTION_NAME="aria-idv-test-harness"
ROLE_NAME="aria-lambda-idv-test-harness-role"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HARNESS_DIR="${SCRIPT_DIR}/../lambda"
INJECTOR_FILE="${SCRIPT_DIR}/../../scripts/lambdas/session_injector_qconnect.py"
HANDLER_NAME="aria_idv_test_harness.handler"
DRY_RUN=false

REGION="${AWS_REGION:-eu-west-2}"
ACCOUNT_ID="${AWS_ACCOUNT_ID:-}"
INSTANCE_ID="${INSTANCE_ID:-}"
SECRET="${IDV_TEST_SIGNING_SECRET:-}"
BANK_NAME="${BANK_NAME:-Meridian Bank}"

# ── Argument parsing ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --instance-id)  INSTANCE_ID="$2"; shift 2 ;;
        --region)       REGION="$2";      shift 2 ;;
        --account-id)   ACCOUNT_ID="$2";  shift 2 ;;
        --secret)       SECRET="$2";      shift 2 ;;
        --bank-name)    BANK_NAME="$2";   shift 2 ;;
        --dry-run)      DRY_RUN=true; shift ;;
        --help|-h)
            sed -n '/^# Usage:/,/^# Requirements:/p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *) die "Unknown argument: $1. Run with --help for usage." ;;
    esac
done

# ── Validation ─────────────────────────────────────────────────────────────────
[[ -d "$HARNESS_DIR"   ]] || die "Harness source directory not found: ${HARNESS_DIR}"
[[ -f "$INJECTOR_FILE" ]] || die "Session injector source not found: ${INJECTOR_FILE}"
command -v aws     >/dev/null 2>&1 || die "AWS CLI not found. Install aws-cli v2."
command -v zip     >/dev/null 2>&1 || die "zip not found. Install zip."
command -v openssl >/dev/null 2>&1 || die "openssl not found."

if [[ -z "$SECRET" ]]; then
    SECRET="$(openssl rand -hex 24)"
    GENERATED_SECRET=true
else
    GENERATED_SECRET=false
fi
[[ ${#SECRET} -ge 16 ]] || die "The signing secret must be at least 16 characters."

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

LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNCTION_NAME}"
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
BUILD_DIR="$(mktemp -d)"
ZIP_PATH="${BUILD_DIR}/${FUNCTION_NAME}.zip"
trap 'rm -rf "$BUILD_DIR"' EXIT

# =============================================================================
# Step 1 — IAM Role
# =============================================================================
header "Step 1 — IAM execution role"

if [[ -n "$(role_exists "$ROLE_NAME")" ]]; then
    warn "Role already exists — reusing: ${ROLE_NAME}"
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

    # The harness calls no AWS APIs, so CloudWatch Logs is all it needs.
    run aws iam attach-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"

    ok "Role created. Waiting 15s for IAM propagation..."
    $DRY_RUN || sleep 15
fi

ok "IAM role ready: ${ROLE_ARN}"

# =============================================================================
# Step 2 — Package Lambda
# =============================================================================
header "Step 2 — Packaging Lambda"

step "Collecting harness modules and the session injector..."
cp "$HARNESS_DIR"/*.py "$BUILD_DIR"/
cp "$INJECTOR_FILE" "$BUILD_DIR"/
(cd "$BUILD_DIR" && zip -q "$ZIP_PATH" ./*.py)
ok "Package ready: $(cd "$BUILD_DIR" && ls ./*.py | tr '\n' ' ')"

# =============================================================================
# Step 3 — Deploy Lambda (create or update)
# =============================================================================
header "Step 3 — Deploying Lambda: ${FUNCTION_NAME}"

ENV_FILE="${BUILD_DIR}/env.json"
BANK_NAME="$BANK_NAME" SECRET="$SECRET" python3 - > "$ENV_FILE" <<'PY'
import json, os
print(json.dumps({"Variables": {
    "IDV_TEST_HARNESS_ENABLED": "true",
    "IDV_TEST_SIGNING_SECRET": os.environ["SECRET"],
    "BANK_NAME": os.environ["BANK_NAME"],
}}))
PY

if [[ -n "$(lambda_exists "$FUNCTION_NAME")" ]]; then
    step "Updating existing Lambda code..."
    run aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file "fileb://${ZIP_PATH}" \
        --region "$REGION" \
        --query "FunctionName" --output text > /dev/null

    $DRY_RUN || aws lambda wait function-updated \
        --function-name "$FUNCTION_NAME" --region "$REGION" 2>/dev/null || true

    step "Updating Lambda configuration..."
    run aws lambda update-function-configuration \
        --function-name "$FUNCTION_NAME" \
        --environment "file://${ENV_FILE}" \
        --handler "$HANDLER_NAME" \
        --timeout 8 \
        --region "$REGION" \
        --query "FunctionName" --output text > /dev/null

    $DRY_RUN || aws lambda wait function-updated \
        --function-name "$FUNCTION_NAME" --region "$REGION" 2>/dev/null || true
else
    step "Creating new Lambda..."
    run aws lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --runtime python3.12 \
        --role "$ROLE_ARN" \
        --handler "$HANDLER_NAME" \
        --zip-file "fileb://${ZIP_PATH}" \
        --timeout 8 \
        --environment "file://${ENV_FILE}" \
        --region "$REGION" \
        --query "FunctionName" --output text > /dev/null

    $DRY_RUN || aws lambda wait function-active \
        --function-name "$FUNCTION_NAME" --region "$REGION" 2>/dev/null || true
fi

ok "Lambda deployed: ${LAMBDA_ARN}"

# =============================================================================
# Step 4 — Grant Amazon Connect permission to invoke
# =============================================================================
header "Step 4 — Connect invoke permission"

# Scope the permission to one Connect instance when its ID is known.
SOURCE_ARGS=(--source-account "$ACCOUNT_ID")
if [[ -n "$INSTANCE_ID" ]]; then
    SOURCE_ARGS+=(--source-arn "arn:aws:connect:${REGION}:${ACCOUNT_ID}:instance/${INSTANCE_ID}")
else
    warn "No --instance-id given: any Connect instance in this account may invoke the harness."
fi

run aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id  "ConnectInvoke" \
    --action        "lambda:InvokeFunction" \
    --principal     "connect.amazonaws.com" \
    "${SOURCE_ARGS[@]}" \
    --region        "$REGION" 2>/dev/null \
    || warn "Connect permission already set on function (non-fatal)"

ok "Connect permission granted."

# =============================================================================
# Summary
# =============================================================================
header "Deployment complete"

cat <<SUMMARY

  Function  : ${LAMBDA_ARN}
  Handler   : ${HANDLER_NAME}
  Runtime   : python3.12
  IAM role  : ${ROLE_ARN}  (CloudWatch Logs only)

  Environment:
    IDV_TEST_HARNESS_ENABLED = true
    BANK_NAME                = ${BANK_NAME}
    IDV_TEST_SIGNING_SECRET  = $($GENERATED_SECRET && echo "$SECRET" || echo "(the value you supplied)")

SUMMARY

$GENERATED_SECRET && warn "A signing secret was generated. Keep it: mint_test_token.py needs the same value.
        export IDV_TEST_SIGNING_SECRET='${SECRET}'
        Re-running this script without --secret generates a NEW one and invalidates old tokens."

cat <<SUMMARY

$(printf "${YELLOW}")Next steps (see connect-idv-test-harness/README.md, Part C onwards):$(printf "${RESET}")
  1. Add the Lambda to your Connect instance so flows can select it:
       Connect console → your instance → Flows → AWS Lambda → add ${FUNCTION_NAME}
  2. Import flows/aria-idv-test-harness-flow.json as a new inbound flow.
  3. Point a TEST phone number at the new flow.
  4. To switch the harness off without deleting it:
       aws lambda update-function-configuration --function-name ${FUNCTION_NAME} \\
           --region ${REGION} --environment 'Variables={IDV_TEST_HARNESS_ENABLED=false}'

SUMMARY
