#!/usr/bin/env bash
# =============================================================================
#  deploy_meeting_id_lambda.sh
#  ARIA — Meeting ID Capture Lambda Deploy / Status / Teardown
# =============================================================================
#
#  USAGE
#    ./scripts/deploy_meeting_id_lambda.sh deploy
#    ./scripts/deploy_meeting_id_lambda.sh deploy --instance-id <connect-uuid>
#    ./scripts/deploy_meeting_id_lambda.sh status
#    ./scripts/deploy_meeting_id_lambda.sh teardown
#
#  WHAT THIS SCRIPT CREATES
#    IAM role     aria-meeting-id-capture-role
#                   — AWSLambdaBasicExecutionRole (CloudWatch Logs)
#    Lambda       aria-meeting-id-capture (Python 3.12, eu-west-2 default)
#                   — publishes a new version on every deploy
#                   — creates / updates 'prod' alias → latest version
#    Connect      resource-based policy so your Connect instance can invoke
#                 the alias (optional, needs --instance-id)
#
#  PROD ALIAS
#    Contact flows should invoke:
#      arn:aws:lambda:<region>:<account>:function:aria-meeting-id-capture:prod
#
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAMBDA_DIR="${SCRIPT_DIR}/lambdas"
LAMBDA_SOURCE="${LAMBDA_DIR}/aria_meeting_id_capture.py"
STATE_FILE="${SCRIPT_DIR}/.deploy-meeting-id-state.json"

FUNCTION_NAME="aria-meeting-id-capture"
ALIAS_NAME="prod"
ROLE_NAME="aria-meeting-id-capture-role"
REGION="${AWS_REGION:-eu-west-2}"
CONNECT_INSTANCE_ID="${CONNECT_INSTANCE_ID:-}"

ACCOUNT_ID=""
ROLE_ARN=""
LAMBDA_ALIAS_ARN=""

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

header() { echo -e "\n${BOLD}${BLUE}══ $* ══${NC}" >&2; }
step()   { echo -e "${CYAN}  ▶ $*${NC}" >&2; }
ok()     { echo -e "${GREEN}  ✔ $*${NC}" >&2; }
warn()   { echo -e "${YELLOW}  ⚠ $*${NC}" >&2; }
error()  { echo -e "${RED}  ✖ $*${NC}" >&2; }
die()    { error "$*"; exit 1; }

ask_yn() {
    local prompt="$1" default="${2:-Y}"
    local display="y/n"
    [[ "${default^^}" == "Y" ]] && display="Y/n" || display="y/N"
    printf "${BOLD}  ? ${prompt} [${display}]: ${NC}" >/dev/tty
    local input
    read -r input </dev/tty
    [[ -z "$input" ]] && input="$default"
    [[ "${input^^}" == "Y" ]]
}

state_init() { [[ -f "$STATE_FILE" ]] || echo '{}' > "$STATE_FILE"; }

state_set() {
    local key="$1" value="$2"
    python3 - "$STATE_FILE" "$key" "$value" <<'PYEOF'
import json
import sys

path, key, value = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)
data[key] = value
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
PYEOF
}

state_get() {
    local key="$1" default="${2:-}"
    python3 - "$STATE_FILE" "$key" "$default" <<'PYEOF'
import json
import sys

path, key, default = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)
print(data.get(key, default))
PYEOF
}

lambda_exists() {
    aws lambda get-function --function-name "$1" --region "$2" \
      --query "Configuration.FunctionName" --output text 2>/dev/null || true
}

iam_role_exists() {
    aws iam get-role --role-name "$1" --query "Role.RoleName" --output text 2>/dev/null || true
}

alias_exists() {
    aws lambda get-alias --function-name "$1" --name "$2" --region "$3" \
      --query "Name" --output text 2>/dev/null || true
}

ensure_iam_role() {
    header "IAM role: ${ROLE_NAME}"

    if [[ -n "$(iam_role_exists "$ROLE_NAME")" ]]; then
        ok "Role already exists — reusing"
    else
        step "Creating role ${ROLE_NAME}"
        aws iam create-role \
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
        ok "Role created"
    fi

    step "Attaching AWSLambdaBasicExecutionRole"
    aws iam attach-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" \
        2>/dev/null || true
    ok "Policy attached"

    ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
    state_set "role_name" "$ROLE_NAME"
    state_set "role_arn" "$ROLE_ARN"

    step "Waiting 15s for IAM role propagation..."
    sleep 15
}

deploy_lambda_and_alias() {
    header "Lambda: ${FUNCTION_NAME}"
    [[ -f "$LAMBDA_SOURCE" ]] || die "Lambda source not found: ${LAMBDA_SOURCE}"

    local zip_path="/tmp/${FUNCTION_NAME}.zip"
    rm -f "$zip_path"

    step "Packaging ${LAMBDA_SOURCE}"
    (cd "$LAMBDA_DIR" && zip -q -j "$zip_path" "$(basename "$LAMBDA_SOURCE")")
    ok "Package ready: ${zip_path}"

    if [[ -n "$(lambda_exists "$FUNCTION_NAME" "$REGION")" ]]; then
        step "Updating existing Lambda code"
        aws lambda update-function-code \
            --function-name "$FUNCTION_NAME" \
            --zip-file "fileb://${zip_path}" \
            --region "$REGION" \
            --query "FunctionName" --output text > /dev/null
        aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION" 2>/dev/null || true

        step "Ensuring configuration"
        aws lambda update-function-configuration \
            --function-name "$FUNCTION_NAME" \
            --timeout 10 \
            --memory-size 128 \
            --region "$REGION" \
            --query "FunctionName" --output text > /dev/null
        aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION" 2>/dev/null || true
    else
        step "Creating Lambda ${FUNCTION_NAME}"
        aws lambda create-function \
            --function-name "$FUNCTION_NAME" \
            --runtime python3.12 \
            --role "$ROLE_ARN" \
            --handler "aria_meeting_id_capture.handler" \
            --zip-file "fileb://${zip_path}" \
            --timeout 10 \
            --memory-size 128 \
            --description "ARIA Connect meeting ID capture (6-digit) from customer input" \
            --region "$REGION" \
            --query "FunctionName" --output text > /dev/null
        aws lambda wait function-active --function-name "$FUNCTION_NAME" --region "$REGION" 2>/dev/null || true
    fi
    ok "Lambda code deployed"

    step "Publishing version"
    local new_version
    new_version=$(aws lambda publish-version \
      --function-name "$FUNCTION_NAME" \
      --description "Deployed $(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
      --region "$REGION" \
      --query "Version" --output text)
    ok "Published version ${new_version}"

    if [[ -n "$(alias_exists "$FUNCTION_NAME" "$ALIAS_NAME" "$REGION")" ]]; then
        step "Updating alias ${ALIAS_NAME} → ${new_version}"
        aws lambda update-alias \
          --function-name "$FUNCTION_NAME" \
          --name "$ALIAS_NAME" \
          --function-version "$new_version" \
          --region "$REGION" \
          --query "AliasArn" --output text > /dev/null
    else
        step "Creating alias ${ALIAS_NAME} → ${new_version}"
        aws lambda create-alias \
          --function-name "$FUNCTION_NAME" \
          --name "$ALIAS_NAME" \
          --function-version "$new_version" \
          --description "Production alias" \
          --region "$REGION" \
          --query "AliasArn" --output text > /dev/null
    fi

    local lambda_arn="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNCTION_NAME}"
    LAMBDA_ALIAS_ARN="${lambda_arn}:${ALIAS_NAME}"
    state_set "function_name" "$FUNCTION_NAME"
    state_set "lambda_arn" "$lambda_arn"
    state_set "lambda_alias_arn" "$LAMBDA_ALIAS_ARN"
    state_set "lambda_version" "$new_version"
    ok "Alias ARN: ${LAMBDA_ALIAS_ARN}"

    rm -f "$zip_path"
}

add_connect_permission() {
    if [[ -z "$CONNECT_INSTANCE_ID" ]]; then
        warn "No --instance-id provided; skipping Connect invoke permission."
        warn "To add later:"
        warn "  aws lambda add-permission --function-name '${FUNCTION_NAME}:${ALIAS_NAME}' \\"
        warn "    --statement-id ConnectInvokeMeetingIdCapture --action lambda:InvokeFunction \\"
        warn "    --principal connect.amazonaws.com --source-account '${ACCOUNT_ID}' \\"
        warn "    --source-arn 'arn:aws:connect:${REGION}:${ACCOUNT_ID}:instance/<instance-id>'"
        return
    fi

    header "Connect permission (instance: ${CONNECT_INSTANCE_ID})"
    local instance_arn="arn:aws:connect:${REGION}:${ACCOUNT_ID}:instance/${CONNECT_INSTANCE_ID}"
    aws lambda add-permission \
        --function-name "${FUNCTION_NAME}:${ALIAS_NAME}" \
        --statement-id "ConnectInvokeMeetingIdCapture" \
        --action "lambda:InvokeFunction" \
        --principal "connect.amazonaws.com" \
        --source-account "$ACCOUNT_ID" \
        --source-arn "$instance_arn" \
        --region "$REGION" 2>/dev/null || warn "Permission already exists (non-fatal)"
    ok "Connect can invoke ${FUNCTION_NAME}:${ALIAS_NAME}"
    state_set "connect_instance_id" "$CONNECT_INSTANCE_ID"
}

cmd_status() {
    header "Status: ${FUNCTION_NAME}"

    echo -e "${BOLD}State file:${NC} ${STATE_FILE}"
    if [[ -f "$STATE_FILE" ]]; then
        cat "$STATE_FILE"
    else
        warn "State file does not exist."
    fi

    echo ""
    echo -e "${BOLD}Live Lambda status:${NC}"
    aws lambda get-function \
      --function-name "${FUNCTION_NAME}:${ALIAS_NAME}" \
      --region "$REGION" \
      --query "Configuration.[FunctionArn,Runtime,Timeout,MemorySize,LastModified]" \
      --output table 2>/dev/null || warn "Lambda alias not found."
}

cmd_teardown() {
    header "Teardown: ${FUNCTION_NAME}"

    if ask_yn "Delete Lambda '${FUNCTION_NAME}' (all versions + aliases)?" "N"; then
        aws lambda delete-function --function-name "$FUNCTION_NAME" --region "$REGION" 2>/dev/null && \
          ok "Lambda deleted" || warn "Lambda not found — skipping"
    fi

    local log_group="/aws/lambda/${FUNCTION_NAME}"
    if ask_yn "Delete CloudWatch Log Group '${log_group}'?" "N"; then
        aws logs delete-log-group --log-group-name "$log_group" --region "$REGION" 2>/dev/null && \
          ok "Log group deleted" || warn "Log group not found — skipping"
    fi

    if ask_yn "Delete IAM role '${ROLE_NAME}' and policies?" "N"; then
        aws iam detach-role-policy \
          --role-name "$ROLE_NAME" \
          --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" \
          2>/dev/null || true
        aws iam delete-role --role-name "$ROLE_NAME" 2>/dev/null && \
          ok "IAM role deleted" || warn "IAM role not found — skipping"
    fi

    local zip_path="/tmp/${FUNCTION_NAME}.zip"
    [[ -f "$zip_path" ]] && rm -f "$zip_path" && ok "Removed temp zip: ${zip_path}"
    [[ -f "$STATE_FILE" ]] && rm -f "$STATE_FILE" && ok "State file removed"

    ok "Teardown complete"
}

parse_args() {
    COMMAND="${1:-}"
    shift || true

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --instance-id) CONNECT_INSTANCE_ID="$2"; shift 2 ;;
            --region) REGION="$2"; shift 2 ;;
            --function-name) FUNCTION_NAME="$2"; shift 2 ;;
            --role-name) ROLE_NAME="$2"; shift 2 ;;
            *) die "Unknown argument: $1" ;;
        esac
    done
}

print_summary() {
    local version
    version=$(state_get "lambda_version" "?")
    echo ""
    echo -e "${BOLD}${GREEN}Meeting ID Lambda deploy complete.${NC}"
    echo -e "  Alias ARN: ${CYAN}${LAMBDA_ALIAS_ARN}${NC}"
    echo -e "  Version:   ${version}"
    echo -e "  State:     ${STATE_FILE}"
    echo ""
    echo -e "${BOLD}${YELLOW}Contact Flow mapping:${NC}"
    echo -e "  Invoke AWS Lambda block: ${FUNCTION_NAME} (use :${ALIAS_NAME})"
    echo -e "  Store customer input block should map meeting ID to an attribute/parameter"
    echo -e "  Read outputs as:"
    echo -e "    $.External.success"
    echo -e "    $.External.meetingId"
    echo -e "    $.External.message"
    echo ""
}

main() {
    if [[ $# -eq 0 ]]; then
        echo "Usage: $0 deploy|status|teardown [--instance-id <connect-uuid>] [--region <region>]"
        exit 1
    fi

    parse_args "$@"
    state_init
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    ok "AWS Account: ${ACCOUNT_ID}  Region: ${REGION}"

    case "$COMMAND" in
        deploy)
            ensure_iam_role
            deploy_lambda_and_alias
            add_connect_permission
            print_summary
            ;;
        status)
            cmd_status
            ;;
        teardown)
            cmd_teardown
            ;;
        *)
            die "Unknown command '${COMMAND}'. Use: deploy | status | teardown"
            ;;
    esac
}

main "$@"

