#!/usr/bin/env bash
# =============================================================================
# deploy_agent_assist.sh
# =============================================================================
# Deploys the aria-agent-assist-injector Lambda, which gives the agent-assist
# AI agent the customer and handover context for a contact.
#
# YOU run this script. It makes changes in your AWS account:
#   1. Creates (or updates) an IAM role that can read a contact and write to
#      this one assistant's sessions
#   2. Packages the Lambda together with session_injector_qconnect.py (it
#      imports the test customers from that file)
#   3. Creates or updates the Lambda
#   4. Lets your Connect instance invoke it, and adds it to the instance's
#      Lambda allow-list so flows can select it
#   5. Invokes it once to prove the package loads
#
# It uses the AWS CLI only. It does NOT create or change any contact flow, AI
# agent or AI prompt. See ../README.md for those steps.
#
# Usage:
#   ./connect-agent-assist/scripts/deploy_agent_assist.sh [OPTIONS]
#
# With no options it deploys to the "conversationbot" Connect instance in
# eu-west-2 using the defaults below. Pass an option only to override one.
#
# Options:
#   --region        REGION   AWS region                (default: eu-west-2)
#   --account-id    ID       AWS account ID            (default: 395402194296)
#   --instance-id   ID       Connect instance ID       (default: f969d4b4-f716-4974-a325-bb7899f2f293)
#   --assistant-id  ID       Q Connect assistant ID    (default: e6991ed4-e11c-4194-8d20-13889a36bd15)
#   --function-name NAME     Lambda function name      (default: aria-agent-assist-injector)
#   --role-name     NAME     IAM execution role name   (default: aria-lambda-agent-assist-injector-role)
#   --dry-run                Print what would be done without deploying
#   --help                   Show this help text
#
# Precedence for every value: command-line flag, then environment variable,
# then the default.
#
# Environment variable equivalents:
#   AWS_REGION, AWS_ACCOUNT_ID, INSTANCE_ID, ASSISTANT_ID, FUNCTION_NAME, ROLE_NAME
#
# Requirements:
#   - AWS CLI v2 configured with credentials that can manage IAM, Lambda and Connect
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
DEFAULT_INSTANCE_ID="f969d4b4-f716-4974-a325-bb7899f2f293"
DEFAULT_ASSISTANT_ID="e6991ed4-e11c-4194-8d20-13889a36bd15"
DEFAULT_FUNCTION_NAME="aria-agent-assist-injector"
ARIA_INJECTOR_FUNCTION="aria-session-injector-qconnect"
DISPUTE_FUNCTION="aria-card-dispute"      # connect-card-dispute; optional
LIVESYNC_FUNCTION="mortgage-livesync-api" # connect-livesync-mortgage; optional
DEFAULT_ROLE_NAME="aria-lambda-agent-assist-injector-role"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LAMBDA_FILE="${SCRIPT_DIR}/../lambda/aria_agent_assist_injector.py"
INJECTOR_FILE="${SCRIPT_DIR}/../../scripts/lambdas/session_injector_qconnect.py"
HANDLER_NAME="aria_agent_assist_injector.handler"
DRY_RUN=false

REGION="${AWS_REGION:-$DEFAULT_REGION}"
ACCOUNT_ID="${AWS_ACCOUNT_ID:-$DEFAULT_ACCOUNT_ID}"
INSTANCE_ID="${INSTANCE_ID:-$DEFAULT_INSTANCE_ID}"
ASSISTANT_ID="${ASSISTANT_ID:-$DEFAULT_ASSISTANT_ID}"
FUNCTION_NAME="${FUNCTION_NAME:-$DEFAULT_FUNCTION_NAME}"
ROLE_NAME="${ROLE_NAME:-$DEFAULT_ROLE_NAME}"

# ── Argument parsing ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --region)        REGION="$2";        shift 2 ;;
        --account-id)    ACCOUNT_ID="$2";    shift 2 ;;
        --instance-id)   INSTANCE_ID="$2";   shift 2 ;;
        --assistant-id)  ASSISTANT_ID="$2";  shift 2 ;;
        --function-name) FUNCTION_NAME="$2"; shift 2 ;;
        --role-name)     ROLE_NAME="$2";     shift 2 ;;
        --dry-run)       DRY_RUN=true; shift ;;
        --help|-h)
            sed -n '/^# Usage:/,/^# Requirements:/p' "$0" | sed -E 's/^# ?//'
            exit 0
            ;;
        *) die "Unknown argument: $1. Run with --help for usage." ;;
    esac
done

# ── Validation ─────────────────────────────────────────────────────────────────
[[ -f "$LAMBDA_FILE"   ]] || die "Lambda source not found: ${LAMBDA_FILE}"
[[ -f "$INJECTOR_FILE" ]] || die "Session injector source not found: ${INJECTOR_FILE}"
command -v aws     >/dev/null 2>&1 || die "AWS CLI not found. Install aws-cli v2."
command -v zip     >/dev/null 2>&1 || die "zip not found. Install zip."
command -v python3 >/dev/null 2>&1 || die "python3 not found."
python3 -m py_compile "$LAMBDA_FILE" || die "aria_agent_assist_injector.py does not compile."

# The account ID has a default, so check it against the credentials in use.
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
INSTANCE_ARN="arn:aws:connect:${REGION}:${ACCOUNT_ID}:instance/${INSTANCE_ID}"
BUILD_DIR="$(mktemp -d)"
ZIP_PATH="${BUILD_DIR}/${FUNCTION_NAME}.zip"
trap 'rm -rf "$BUILD_DIR"' EXIT

header "Deploying with"
echo "  Region        : ${REGION}"
echo "  Account       : ${ACCOUNT_ID}"
echo "  Instance      : ${INSTANCE_ID}"
echo "  Assistant     : ${ASSISTANT_ID}"
echo "  Function      : ${FUNCTION_NAME}"
echo "  Role          : ${ROLE_NAME}"

# =============================================================================
# Step 1 — IAM role
# =============================================================================
header "Step 1 — IAM execution role"

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

# Read one instance's contacts; read and write one assistant's sessions. Nothing else.
cat > "${BUILD_DIR}/policy.json" <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadContactToFindItsAssistantSession",
      "Effect": "Allow",
      "Action": "connect:DescribeContact",
      "Resource": ["${INSTANCE_ARN}", "${INSTANCE_ARN}/contact/*"]
    },
    {
      "Sid": "AskTheCardDisputeLambdaForTheScreenPop",
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": "arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${DISPUTE_FUNCTION}"
    },
    {
      "Sid": "ReadASavedMortgageApplicationForTheScreenPop",
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": "arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${LIVESYNC_FUNCTION}"
    },
    {
      "Sid": "SetTheAgentAndWriteContextOnTheSession",
      "Effect": "Allow",
      "Action": ["wisdom:UpdateSession", "wisdom:UpdateSessionData", "wisdom:SendMessage", "wisdom:ListMessages", "qconnect:UpdateSession", "qconnect:UpdateSessionData", "qconnect:SendMessage", "qconnect:ListMessages"],
      "Resource": [
        "arn:aws:wisdom:${REGION}:${ACCOUNT_ID}:assistant/${ASSISTANT_ID}",
        "arn:aws:wisdom:${REGION}:${ACCOUNT_ID}:session/${ASSISTANT_ID}/*",
        "arn:aws:wisdom:${REGION}:${ACCOUNT_ID}:message/${ASSISTANT_ID}/*"
      ]
    }
  ]
}
POLICY
step "Applying the permissions policy..."
run aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name "AgentAssistInjectorPolicy" \
    --policy-document "file://${BUILD_DIR}/policy.json"
ok "IAM role ready: ${ROLE_ARN}"

# =============================================================================
# Step 2 — Package
# =============================================================================
header "Step 2 — Packaging Lambda"

cp "$LAMBDA_FILE" "$INJECTOR_FILE" "$BUILD_DIR"/
(cd "$BUILD_DIR" && zip -q "$ZIP_PATH" ./*.py)
ok "Package ready: $(cd "$BUILD_DIR" && ls ./*.py | tr '\n' ' ')"

# =============================================================================
# Step 3 — Deploy
# =============================================================================
header "Step 3 — Deploying Lambda: ${FUNCTION_NAME}"

# ARIA's injector can be set to treat a caller recognised by phone number as a
# given level. Copy that setting, so the agent is told what ARIA was told.
CLI_MATCH_LOA="$(aws lambda get-function-configuration --function-name "$ARIA_INJECTOR_FUNCTION" \
    --region "$REGION" --query "Environment.Variables.CLI_MATCH_LOA" --output text 2>/dev/null || true)"
[[ "$CLI_MATCH_LOA" == "None" ]] && CLI_MATCH_LOA=""
ok "Level ARIA gives a caller recognised by phone number: ${CLI_MATCH_LOA:-not set}"

# The card dispute service is optional. When it is deployed, the screen pop asks it
# whether the customer has an open dispute.
DISPUTE_FUNCTION_NAME=""
if aws lambda get-function --function-name "$DISPUTE_FUNCTION" --region "$REGION" >/dev/null 2>&1; then
    DISPUTE_FUNCTION_NAME="$DISPUTE_FUNCTION"
fi
ok "Card dispute service: ${DISPUTE_FUNCTION_NAME:-not deployed}"

# Live Sync is optional too. When it is deployed, the screen pop asks it for the
# mortgage application a contact carries. It answers only once it can save
# applications (connect-livesync-mortgage v1.22); before that the screen pop
# says the form has not been saved.
LIVESYNC_FUNCTION_NAME=""
if aws lambda get-function --function-name "$LIVESYNC_FUNCTION" --region "$REGION" >/dev/null 2>&1; then
    LIVESYNC_FUNCTION_NAME="$LIVESYNC_FUNCTION"
fi
ok "Mortgage Live Sync: ${LIVESYNC_FUNCTION_NAME:-not deployed}"

ASSISTANT_ID="$ASSISTANT_ID" INSTANCE_ID="$INSTANCE_ID" CLI_MATCH_LOA="$CLI_MATCH_LOA" \
    DISPUTE_FUNCTION_NAME="$DISPUTE_FUNCTION_NAME" LIVESYNC_FUNCTION_NAME="$LIVESYNC_FUNCTION_NAME" \
    python3 - > "${BUILD_DIR}/env.json" <<'PY'
import json, os
variables = {"ASSISTANT_ID": os.environ["ASSISTANT_ID"], "INSTANCE_ID": os.environ["INSTANCE_ID"]}
for name in ("CLI_MATCH_LOA", "DISPUTE_FUNCTION_NAME", "LIVESYNC_FUNCTION_NAME"):
    if os.environ.get(name):
        variables[name] = os.environ[name]
print(json.dumps({"Variables": variables}))
PY

if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" >/dev/null 2>&1; then
    step "Updating existing Lambda code..."
    run aws lambda update-function-code --function-name "$FUNCTION_NAME" --region "$REGION" \
        --zip-file "fileb://${ZIP_PATH}" --query "FunctionName" --output text > /dev/null
    $DRY_RUN || aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
    step "Updating Lambda configuration..."
    run aws lambda update-function-configuration --function-name "$FUNCTION_NAME" --region "$REGION" \
        --environment "file://${BUILD_DIR}/env.json" --handler "$HANDLER_NAME" --timeout 15 \
        --query "FunctionName" --output text > /dev/null
    $DRY_RUN || aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
else
    step "Creating new Lambda..."
    run aws lambda create-function --function-name "$FUNCTION_NAME" --region "$REGION" \
        --runtime python3.12 --role "$ROLE_ARN" --handler "$HANDLER_NAME" \
        --zip-file "fileb://${ZIP_PATH}" --timeout 15 --environment "file://${BUILD_DIR}/env.json" \
        --query "FunctionName" --output text > /dev/null
    $DRY_RUN || aws lambda wait function-active --function-name "$FUNCTION_NAME" --region "$REGION"
fi
ok "Lambda deployed: ${LAMBDA_ARN}"

# =============================================================================
# Step 4 — Let Connect invoke it and select it
# =============================================================================
header "Step 4 — Connect permissions"

run aws lambda add-permission --function-name "$FUNCTION_NAME" --region "$REGION" \
    --statement-id "ConnectInvoke" --action "lambda:InvokeFunction" \
    --principal "connect.amazonaws.com" --source-account "$ACCOUNT_ID" --source-arn "$INSTANCE_ARN" \
    >/dev/null 2>&1 || warn "Invoke permission already set (non-fatal)"
ok "Connect instance may invoke the Lambda."

# The allow-list is what makes the function appear in a flow's Lambda block.
if aws connect list-lambda-functions --instance-id "$INSTANCE_ID" --region "$REGION" \
        --query "LambdaFunctions" --output text 2>/dev/null | tr -s '[:space:]' '\n' | grep -qx "$LAMBDA_ARN"; then
    ok "Already on the instance's Lambda allow-list."
else
    step "Adding the Lambda to the instance's allow-list..."
    run aws connect associate-lambda-function --instance-id "$INSTANCE_ID" --region "$REGION" \
        --function-arn "$LAMBDA_ARN"
    ok "Added to the instance's Lambda allow-list."
fi

# =============================================================================
# Step 5 — Prove the package loads
# =============================================================================
header "Step 5 — Testing the Lambda"

if $DRY_RUN; then
    warn "Skipped in dry-run."
else
    # A made-up contact has no assistant session, so a healthy Lambda answers
    # "error_no_assistant_session". Anything else means the package is broken.
    cat > "${BUILD_DIR}/payload.json" <<PAYLOAD
{"Details":{"ContactData":{"ContactId":"00000000-0000-0000-0000-000000000000","Channel":"VOICE","InstanceARN":"${INSTANCE_ARN}","Attributes":{"customerId":"CUST-001"}}}}
PAYLOAD
    function_error=$(aws lambda invoke --function-name "$FUNCTION_NAME" --region "$REGION" \
        --cli-binary-format raw-in-base64-out --payload "file://${BUILD_DIR}/payload.json" \
        "${BUILD_DIR}/out.json" --query "FunctionError" --output text)
    status=$(python3 -c 'import json,sys; v=json.load(open(sys.argv[1])); print(v.get("status","") if isinstance(v,dict) else "")' "${BUILD_DIR}/out.json")
    if [[ "$function_error" == "None" && "$status" == "error_no_assistant_session" ]]; then
        ok "The Lambda loads and runs (a made-up contact has no assistant session, as expected)."
        warn "This does not prove the IAM permissions: only a real contact through the flow can."
    else
        die "Unexpected answer from the Lambda (FunctionError=${function_error}): $(cat "${BUILD_DIR}/out.json")"
    fi
fi

# =============================================================================
# Summary
# =============================================================================
header "Deployment complete"

cat <<SUMMARY

  Function  : ${LAMBDA_ARN}
  Handler   : ${HANDLER_NAME}
  IAM role  : ${ROLE_ARN}

$(printf "${YELLOW}")Next steps (see connect-agent-assist/README.md, Part C onwards):$(printf "${RESET}")
  1. Update the agent-assist AI agent: add the read-only banking tools, paste the
     prompt from prompts/agent-assist-prompt-v3.yaml, and publish.
  2. Import flows/aria-agent-assist-flow.json as a new inbound flow, pinned to the
     agent version you just published.
  3. Change "ARIA human handover" so it ends by transferring to the new flow.

SUMMARY
