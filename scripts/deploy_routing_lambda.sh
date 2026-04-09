#!/usr/bin/env bash
# =============================================================================
#  deploy_routing_lambda.sh
#  ARIA — Proficiency-Based Queue Routing — Lambda + DynamoDB Deploy Script
# =============================================================================
#
#  USAGE
#    ./scripts/deploy_routing_lambda.sh deploy
#    ./scripts/deploy_routing_lambda.sh deploy --instance-id <connect-uuid>
#    ./scripts/deploy_routing_lambda.sh teardown
#
#  WHAT THIS SCRIPT CREATES
#    IAM role     aria-routing-lookup-role
#                   — AWSLambdaBasicExecutionRole (CloudWatch Logs)
#                   — DynamoDB GetItem on aria-routing-config
#    Lambda       aria-routing-lookup  (Python 3.12, eu-west-2)
#                   — publishes a new version on every deploy
#                   — creates / updates 'prod' alias → latest version
#    DynamoDB     aria-routing-config  (PAY_PER_REQUEST, PK: topicCategory)
#                   — seeds 8 placeholder routing rows (update UUIDs after deploy)
#    Connect      resource-based policy granting your Connect instance
#                   permission to invoke the Lambda (optional, needs --instance-id)
#
#  PROD ALIAS BEHAVIOUR
#    Every run of "deploy" publishes a new immutable Lambda version and points
#    the "prod" alias to it automatically. Contact flows should invoke the
#    Lambda using its :prod alias ARN — never the $LATEST qualifier.
#    ARN format: arn:aws:lambda:<region>:<account>:function:aria-routing-lookup:prod
#
#  PREREQUISITES
#    • aws CLI v2 configured with sufficient IAM permissions
#    • python3 in PATH
#    • zip in PATH
#
#  ENVIRONMENT VARIABLES (all optional overrides)
#    AWS_REGION           default: eu-west-2
#    CONNECT_INSTANCE_ID  Connect instance UUID — needed to authorise Lambda invocation
#
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAMBDA_DIR="${SCRIPT_DIR}/lambdas"
LAMBDA_SOURCE="${LAMBDA_DIR}/aria_routing_lookup.py"
STATE_FILE="${SCRIPT_DIR}/.deploy-routing-state.json"

FUNCTION_NAME="aria-routing-lookup"
ALIAS_NAME="prod"
ROLE_NAME="aria-routing-lookup-role"
TABLE_NAME="aria-routing-config"
REGION="${AWS_REGION:-eu-west-2}"
CONNECT_INSTANCE_ID="${CONNECT_INSTANCE_ID:-}"

# ── Colour helpers ─────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

header() { echo -e "\n${BOLD}${BLUE}══ $* ══${NC}" >&2; }
step()   { echo -e "${CYAN}  ▶ $*${NC}" >&2; }
ok()     { echo -e "${GREEN}  ✔ $*${NC}" >&2; }
warn()   { echo -e "${YELLOW}  ⚠ $*${NC}" >&2; }
error()  { echo -e "${RED}  ✖ $*${NC}" >&2; }
die()    { error "$*"; exit 1; }

# ── Prompt helper ──────────────────────────────────────────────────────────────
ask() {
    local var="$1" prompt="$2" default="${3:-}"
    local display_default=""
    [[ -n "$default" ]] && display_default=" [${default}]"
    printf "${BOLD}  ? ${prompt}${display_default}: ${NC}" >/dev/tty
    local input
    read -r input </dev/tty
    [[ -z "$input" ]] && input="$default"
    printf -v "$var" '%s' "$input"
}

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

# ── State management ───────────────────────────────────────────────────────────
state_init() { [[ -f "$STATE_FILE" ]] || echo '{}' > "$STATE_FILE"; }

state_set() {
    local key="$1" value="$2"
    python3 - "$STATE_FILE" "$key" "$value" <<'PYEOF'
import sys, json
path, key, value = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path) as f: data = json.load(f)
data[key] = value
with open(path, "w") as f: json.dump(data, f, indent=2)
PYEOF
}

state_get() {
    local key="$1"
    python3 - "$STATE_FILE" "$key" <<'PYEOF'
import sys, json
path, key = sys.argv[1], sys.argv[2]
with open(path) as f: data = json.load(f)
print(data.get(key, ""))
PYEOF
}

# ── AWS helpers ────────────────────────────────────────────────────────────────
lambda_exists() {
    aws lambda get-function --function-name "$1" --region "$2" \
        --query "Configuration.FunctionName" --output text 2>/dev/null || true
}

iam_role_exists() {
    aws iam get-role --role-name "$1" \
        --query "Role.RoleName" --output text 2>/dev/null || true
}

dynamodb_table_exists() {
    aws dynamodb describe-table --table-name "$1" --region "$2" \
        --query "Table.TableName" --output text 2>/dev/null || true
}

alias_exists() {
    # $1=function-name  $2=alias-name  $3=region
    aws lambda get-alias --function-name "$1" --name "$2" --region "$3" \
        --query "Name" --output text 2>/dev/null || true
}

# =============================================================================
#  Step 1 — IAM Role
# =============================================================================
ensure_iam_role() {
    header "IAM role: ${ROLE_NAME}"

    if [[ -n "$(iam_role_exists "$ROLE_NAME")" ]]; then
        ok "Role already exists — verifying policies"
    else
        step "Creating role ${ROLE_NAME}"
        aws iam create-role \
            --role-name "$ROLE_NAME" \
            --assume-role-policy-document '{
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect":    "Allow",
                    "Principal": {"Service": "lambda.amazonaws.com"},
                    "Action":    "sts:AssumeRole"
                }]
            }' \
            --query "Role.RoleName" --output text > /dev/null

        aws iam attach-role-policy \
            --role-name "$ROLE_NAME" \
            --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"

        ok "Role created"
        step "Waiting 15s for IAM propagation..."
        sleep 15
    fi

    # Always ensure the DynamoDB inline policy is up-to-date (idempotent put).
    # Using put-role-policy (inline) keeps permissions co-located with this script.
    step "Ensuring DynamoDB GetItem policy on ${TABLE_NAME}"
    aws iam put-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-name "RoutingDynamoDBRead" \
        --policy-document "{
            \"Version\": \"2012-10-17\",
            \"Statement\": [{
                \"Effect\":   \"Allow\",
                \"Action\":   [\"dynamodb:GetItem\"],
                \"Resource\": \"arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${TABLE_NAME}\"
            }]
        }"
    ok "DynamoDB GetItem policy in place"

    ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
    state_set "role_arn" "$ROLE_ARN"
}

# =============================================================================
#  Step 2 — DynamoDB Table
# =============================================================================
ensure_dynamodb_table() {
    header "DynamoDB table: ${TABLE_NAME}"

    if [[ -n "$(dynamodb_table_exists "$TABLE_NAME" "$REGION")" ]]; then
        ok "Table already exists — skipping creation"
        state_set "dynamodb_table_arn" \
            "arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${TABLE_NAME}"
        return
    fi

    step "Creating table ${TABLE_NAME} (PAY_PER_REQUEST)"
    aws dynamodb create-table \
        --table-name "$TABLE_NAME" \
        --attribute-definitions AttributeName=topicCategory,AttributeType=S \
        --key-schema             AttributeName=topicCategory,KeyType=HASH \
        --billing-mode           PAY_PER_REQUEST \
        --region "$REGION" \
        --query "TableDescription.TableName" --output text > /dev/null

    step "Waiting for table to become ACTIVE..."
    aws dynamodb wait table-exists --table-name "$TABLE_NAME" --region "$REGION"
    ok "Table ACTIVE"

    TABLE_ARN="arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${TABLE_NAME}"
    state_set "dynamodb_table_arn" "$TABLE_ARN"

    seed_dynamodb_table
}

seed_dynamodb_table() {
    header "Seeding routing rows (Meridian Bank Queue UUIDs)"

    # Real Meridian Bank Connect Queue UUIDs — sourced from docs/aria-connect-voice-chat-novice-guide.md
    # Format: topicCategory|queueId|queueName|proficiencyLevel|proficiencySkill
    # All values stored as DynamoDB String (S) — Lambda reads them back as plain strings,
    # no Decimal conversion required.
    local rows=(
        'mortgage|a87c313c-53dc-4272-8a20-03b7f2cce4a7|Mortgage Advisors|3|Mortgage'
        'credit_card|d3037cfb-f265-47ff-a28e-f96bf6ab1279|Cards Team|2|Cards'
        'debit_card|846c08b2-574a-415f-84d3-11d46a5f8a16|Cards Team|2|Cards'
        'fraud_security|42646d26-77fb-49f7-a525-a40856c97539|Fraud Team|4|Fraud'
        'complaint|ac5724b6-3602-4045-bb60-1fa81a6fa22c|Senior Advisors|3|Complaints'
        'current_account|846c08b2-574a-415f-84d3-11d46a5f8a16|Retail Banking|1|Retail'
        'savings_account|846c08b2-574a-415f-84d3-11d46a5f8a16|Retail Banking|1|Retail'
        'general_banking|ae9b5b06-06e6-487c-945e-e67dc1462ea9|General Queue|1|General'
    )

    for row in "${rows[@]}"; do
        IFS='|' read -r topic queue_id queue_name prof_level prof_skill <<< "$row"

        aws dynamodb put-item \
            --table-name "$TABLE_NAME" \
            --region     "$REGION" \
            --item "{
                \"topicCategory\":    {\"S\": \"${topic}\"},
                \"queueId\":          {\"S\": \"${queue_id}\"},
                \"queueName\":        {\"S\": \"${queue_name}\"},
                \"proficiencyLevel\": {\"S\": \"${prof_level}\"},
                \"proficiencySkill\": {\"S\": \"${prof_skill}\"}
            }"
        step "  seeded: ${topic} → ${queue_name} (id=${queue_id}, L${prof_level} ${prof_skill})"
    done

    ok "8 routing rows seeded"
}

# =============================================================================
#  Step 3 — Deploy Lambda code + publish version + update prod alias
# =============================================================================
deploy_lambda_and_alias() {
    header "Lambda: ${FUNCTION_NAME}"

    local zip_path="/tmp/${FUNCTION_NAME}.zip"

    step "Packaging ${FUNCTION_NAME}"
    (cd "$LAMBDA_DIR" && zip -q "$zip_path" "aria_routing_lookup.py")

    local env_vars="{ROUTING_TABLE=${TABLE_NAME}}"

    if [[ -n "$(lambda_exists "$FUNCTION_NAME" "$REGION")" ]]; then
        # ── Update existing function ─────────────────────────────────────────
        step "Updating code for existing Lambda ${FUNCTION_NAME}"
        aws lambda update-function-code \
            --function-name "$FUNCTION_NAME" \
            --zip-file      "fileb://${zip_path}" \
            --region        "$REGION" \
            --query         "FunctionName" --output text > /dev/null

        step "Waiting for code update to complete..."
        aws lambda wait function-updated \
            --function-name "$FUNCTION_NAME" \
            --region        "$REGION" 2>/dev/null || true

        step "Updating configuration (env vars, timeout)"
        aws lambda update-function-configuration \
            --function-name "$FUNCTION_NAME" \
            --environment   "Variables=${env_vars}" \
            --timeout       30 \
            --region        "$REGION" \
            --query         "FunctionName" --output text > /dev/null

        step "Waiting for configuration update to complete..."
        aws lambda wait function-updated \
            --function-name "$FUNCTION_NAME" \
            --region        "$REGION" 2>/dev/null || true

    else
        # ── Create new function ──────────────────────────────────────────────
        step "Creating Lambda ${FUNCTION_NAME}"
        aws lambda create-function \
            --function-name "$FUNCTION_NAME" \
            --runtime        python3.12 \
            --role           "$ROLE_ARN" \
            --handler        "aria_routing_lookup.handler" \
            --zip-file       "fileb://${zip_path}" \
            --timeout        30 \
            --environment    "Variables=${env_vars}" \
            --region         "$REGION" \
            --query          "FunctionName" --output text > /dev/null

        step "Waiting for Lambda to become active..."
        aws lambda wait function-active \
            --function-name "$FUNCTION_NAME" \
            --region        "$REGION" 2>/dev/null || true
    fi

    ok "Lambda code deployed"

    # ── Publish an immutable version ─────────────────────────────────────────
    step "Publishing new version..."
    local new_version
    new_version=$(aws lambda publish-version \
        --function-name "$FUNCTION_NAME" \
        --description   "Deployed $(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
        --region        "$REGION" \
        --query         "Version" --output text)
    ok "Published version: ${new_version}"

    # ── Create or update the 'prod' alias → new version ──────────────────────
    if [[ -n "$(alias_exists "$FUNCTION_NAME" "$ALIAS_NAME" "$REGION")" ]]; then
        step "Updating '${ALIAS_NAME}' alias → version ${new_version}"
        aws lambda update-alias \
            --function-name    "$FUNCTION_NAME" \
            --name             "$ALIAS_NAME" \
            --function-version "$new_version" \
            --description      "Production alias — updated $(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
            --region           "$REGION" \
            --query            "AliasArn" --output text > /dev/null
    else
        step "Creating '${ALIAS_NAME}' alias → version ${new_version}"
        aws lambda create-alias \
            --function-name    "$FUNCTION_NAME" \
            --name             "$ALIAS_NAME" \
            --function-version "$new_version" \
            --description      "Production alias" \
            --region           "$REGION" \
            --query            "AliasArn" --output text > /dev/null
    fi

    LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNCTION_NAME}"
    LAMBDA_ALIAS_ARN="${LAMBDA_ARN}:${ALIAS_NAME}"
    state_set "lambda_arn"       "$LAMBDA_ARN"
    state_set "lambda_alias_arn" "$LAMBDA_ALIAS_ARN"
    state_set "lambda_version"   "$new_version"
    ok "prod alias ARN: ${LAMBDA_ALIAS_ARN}"
}

# =============================================================================
#  Step 4 — Grant Amazon Connect permission to invoke the Lambda alias
# =============================================================================
add_connect_permission() {
    if [[ -z "$CONNECT_INSTANCE_ID" ]]; then
        warn "No --instance-id provided — skipping Connect resource-based policy."
        warn "Add it later:"
        warn "  aws lambda add-permission \\"
        warn "    --function-name '${LAMBDA_ALIAS_ARN}' \\"
        warn "    --statement-id  ConnectInvoke \\"
        warn "    --action        lambda:InvokeFunction \\"
        warn "    --principal     connect.amazonaws.com \\"
        warn "    --source-account '${ACCOUNT_ID}' \\"
        warn "    --region        ${REGION}"
        return
    fi

    header "Connect → Lambda permission (instance: ${CONNECT_INSTANCE_ID})"

    # Add permission on the alias ARN so only the prod alias is callable, not $LATEST.
    aws lambda add-permission \
        --function-name  "$LAMBDA_ALIAS_ARN" \
        --statement-id   "ConnectInvoke" \
        --action         "lambda:InvokeFunction" \
        --principal      "connect.amazonaws.com" \
        --source-account "$ACCOUNT_ID" \
        --region         "$REGION" 2>/dev/null || \
    warn "ConnectInvoke permission already set (non-fatal)"

    ok "Connect can now invoke ${LAMBDA_ALIAS_ARN}"

    warn "NEXT STEP: Add Lambda to Connect instance allow-list:"
    warn "  Connect console → your instance → AWS Lambda → Add Lambda function"
    warn "  Select: ${FUNCTION_NAME}  (the :prod alias will inherit the permission)"
}

# =============================================================================
#  Summary
# =============================================================================
print_summary() {
    local version
    version=$(state_get "lambda_version" 2>/dev/null || echo "?")

    echo ""
    echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}${GREEN}  ARIA Routing Lambda — Deploy Complete${NC}"
    echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  ${BOLD}Lambda ARN (prod alias):${NC}"
    echo -e "    ${CYAN}${LAMBDA_ALIAS_ARN}${NC}"
    echo ""
    echo -e "  ${BOLD}Lambda version deployed:${NC}  ${version}"
    echo ""
    echo -e "  ${BOLD}DynamoDB table:${NC}"
    echo -e "    arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${TABLE_NAME}"
    echo ""
    echo -e "  ${BOLD}State file:${NC}  ${STATE_FILE}"
    echo ""
    echo -e "${BOLD}${YELLOW}  Required manual steps:${NC}"
    echo -e "  ${YELLOW}1. Add Lambda to Connect instance allow-list:${NC}"
    echo -e "     Connect console → <instance> → AWS Lambda → Add Lambda function"
    echo -e "     Function name: ${FUNCTION_NAME}"
    echo ""
    echo -e "  ${YELLOW}2. In your Contact Flow — after the Escalate branch:${NC}"
    echo -e "     'Invoke AWS Lambda' block → select ${FUNCTION_NAME}"
    echo -e "     (Connect resolves the :prod alias automatically)"
    echo ""
    echo -e "  ${YELLOW}3. 'Set Working Queue' block:${NC}"
    echo -e "     Set queue to → Dynamic → $.External.queueId"
    echo ""
    echo -e "${BOLD}${GREEN}  Re-run this script after every Lambda code change.${NC}"
    echo -e "${BOLD}${GREEN}  The prod alias will automatically track the latest version.${NC}"
    echo ""
}

# =============================================================================
#  Teardown
# =============================================================================
cmd_teardown() {
    header "Teardown — aria-routing-lookup resources"

    # ── Lambda (deletes function + all versions + all aliases) ───────────────
    if ask_yn "Delete Lambda function '${FUNCTION_NAME}' (all versions + aliases)?" "N"; then
        aws lambda delete-function \
            --function-name "$FUNCTION_NAME" \
            --region        "$REGION" 2>/dev/null && \
        ok "Lambda deleted" || warn "Lambda not found — skipping"
    fi

    # ── CloudWatch Log Group ─────────────────────────────────────────────────
    # Lambda creates /aws/lambda/<function-name> automatically and it is NOT
    # removed when the function is deleted. Delete it explicitly to avoid
    # orphaned log data and costs.
    local log_group="/aws/lambda/${FUNCTION_NAME}"
    if ask_yn "Delete CloudWatch Log Group '${log_group}'?" "N"; then
        aws logs delete-log-group \
            --log-group-name "$log_group" \
            --region         "$REGION" 2>/dev/null && \
        ok "Log group deleted" || warn "Log group not found — skipping"
    fi

    # ── IAM role + policies ──────────────────────────────────────────────────
    if ask_yn "Delete IAM role '${ROLE_NAME}' and its policies?" "N"; then
        aws iam detach-role-policy \
            --role-name  "$ROLE_NAME" \
            --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" \
            2>/dev/null || true
        aws iam delete-role-policy \
            --role-name   "$ROLE_NAME" \
            --policy-name "RoutingDynamoDBRead" \
            2>/dev/null || true
        aws iam delete-role \
            --role-name "$ROLE_NAME" \
            2>/dev/null && \
        ok "IAM role deleted" || warn "IAM role not found — skipping"
    fi

    # ── DynamoDB table ───────────────────────────────────────────────────────
    if ask_yn "Delete DynamoDB table '${TABLE_NAME}' (ALL routing data will be lost)?" "N"; then
        aws dynamodb delete-table \
            --table-name "$TABLE_NAME" \
            --region     "$REGION" 2>/dev/null && \
        ok "DynamoDB table deleted" || warn "Table not found — skipping"
    fi

    # ── Local artefacts ──────────────────────────────────────────────────────
    local zip_path="/tmp/${FUNCTION_NAME}.zip"
    [[ -f "$zip_path"   ]] && rm "$zip_path"   && ok "Removed temp zip: ${zip_path}"
    [[ -f "$STATE_FILE" ]] && rm "$STATE_FILE" && ok "State file removed"

    ok "Teardown complete"
}

# =============================================================================
#  Argument parsing  (called directly — NOT in a subshell — so variable
#  assignments to CONNECT_INSTANCE_ID, REGION etc. persist in the caller)
# =============================================================================
parse_args() {
    # $1 is the command (deploy|teardown); shift it off then process flags
    COMMAND="${1:-}"
    shift || true

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --instance-id)   CONNECT_INSTANCE_ID="$2"; shift 2 ;;
            --region)        REGION="$2";               shift 2 ;;
            --function-name) FUNCTION_NAME="$2";        shift 2 ;;
            --table-name)    TABLE_NAME="$2";            shift 2 ;;
            *) die "Unknown argument: $1. Usage: $0 deploy|teardown [--instance-id <uuid>] [--region <region>]" ;;
        esac
    done
}

# =============================================================================
#  Entry point
# =============================================================================
main() {
    if [[ $# -eq 0 ]]; then
        echo "Usage: $0 deploy|teardown [--instance-id <connect-uuid>] [--region <region>]"
        exit 1
    fi

    # parse_args sets COMMAND and optional overrides directly (no subshell)
    parse_args "$@"

    state_init

    case "$COMMAND" in
        deploy)
            echo ""
            echo -e "${BOLD}${BLUE}ARIA — Proficiency Routing Lambda Deploy${NC}"
            echo -e "${BOLD}${BLUE}Region: ${REGION}${NC}"
            echo ""

            ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
            ok "AWS Account: ${ACCOUNT_ID}  Region: ${REGION}"

            ensure_iam_role
            ensure_dynamodb_table
            deploy_lambda_and_alias
            add_connect_permission
            print_summary
            ;;

        teardown)
            ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
            cmd_teardown
            ;;

        *)
            die "Unknown command '${COMMAND}'. Use: deploy | teardown"
            ;;
    esac
}

main "$@"
