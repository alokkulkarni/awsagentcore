#!/usr/bin/env bash
# =============================================================================
#  deploy_callback_lambda.sh
#  ARIA — Callback Scheduler — Lambda + DynamoDB Update Deploy Script
# =============================================================================
#
#  USAGE
#    ./scripts/deploy_callback_lambda.sh deploy
#    ./scripts/deploy_callback_lambda.sh deploy --instance-id <connect-uuid>
#    ./scripts/deploy_callback_lambda.sh update-queues      # update placeholder IDs only
#    ./scripts/deploy_callback_lambda.sh status
#    ./scripts/deploy_callback_lambda.sh teardown
#
#  WHAT THIS SCRIPT CREATES
#    IAM role     aria-callback-scheduler-role
#                   — AWSLambdaBasicExecutionRole (CloudWatch Logs)
#                   — DynamoDB GetItem on aria-routing-config
#    Lambda       aria-callback-scheduler  (Python 3.12, eu-west-2)
#                   — publishes a new version on every deploy
#                   — creates / updates 'prod' alias → latest version
#    DynamoDB     aria-routing-config  (existing table)
#                   — adds callbackQueueId / callbackQueueArn / callbackQueueName
#                     fields to each existing routing row (PLACEHOLDER values
#                     initially — run 'update-queues' after creating real queues)
#    Connect      resource-based policy granting your Connect instance
#                   permission to invoke the Lambda (optional, needs --instance-id)
#
#  PROD ALIAS BEHAVIOUR
#    Every run of "deploy" publishes a new immutable Lambda version and points
#    the "prod" alias to it automatically. Contact flows should invoke the
#    Lambda using its :prod alias ARN — never the $LATEST qualifier.
#    ARN format: arn:aws:lambda:<region>:<account>:function:aria-callback-scheduler:prod
#
#  PREREQUISITES
#    • aws CLI v2 configured with sufficient IAM permissions
#    • python3 in PATH (for state file management)
#    • zip in PATH
#    • deploy_routing_lambda.sh must have been run first (aria-routing-config table
#      must already exist with seeded topicCategory rows)
#
#  ENVIRONMENT VARIABLES (all optional overrides)
#    AWS_REGION           default: eu-west-2
#    CONNECT_INSTANCE_ID  Connect instance UUID — needed to authorise Lambda invocation
#
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAMBDA_DIR="${SCRIPT_DIR}/lambdas"
LAMBDA_SOURCE="${LAMBDA_DIR}/aria_callback_scheduler.py"
STATE_FILE="${SCRIPT_DIR}/.deploy-callback-state.json"

FUNCTION_NAME="aria-callback-scheduler"
ALIAS_NAME="prod"
ROLE_NAME="aria-callback-scheduler-role"
TABLE_NAME="aria-routing-config"
REGION="${AWS_REGION:-eu-west-2}"
CONNECT_INSTANCE_ID="${CONNECT_INSTANCE_ID:-}"

LAMBDA_ALIAS_ARN=""   # set after deploy

# ── Colour helpers ─────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

header() { echo -e "\n${BOLD}${BLUE}══ $* ══${NC}" >&2; }
step()   { echo -e "${CYAN}  ▶ $*${NC}" >&2; }
ok()     { echo -e "${GREEN}  ✔ $*${NC}" >&2; }
warn()   { echo -e "${YELLOW}  ⚠ $*${NC}" >&2; }
error()  { echo -e "${RED}  ✖ $*${NC}" >&2; }
die()    { error "$*"; exit 1; }

# ── Prompt helpers ─────────────────────────────────────────────────────────────
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

# =============================================================================
#  Step 1 — IAM Role
# =============================================================================
ensure_iam_role() {
    header "IAM Role: ${ROLE_NAME}"

    if [[ -n "$(iam_role_exists "$ROLE_NAME")" ]]; then
        ok "Role '${ROLE_NAME}' already exists — skipping creation"
    else
        step "Creating role '${ROLE_NAME}'"
        aws iam create-role \
            --role-name "$ROLE_NAME" \
            --assume-role-policy-document '{
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": { "Service": "lambda.amazonaws.com" },
                    "Action": "sts:AssumeRole"
                }]
            }' \
            --description "ARIA Callback Scheduler Lambda execution role" \
            --region "$REGION" \
            --output text --query "Role.Arn" > /dev/null
        ok "Role created"
    fi

    # Attach managed logging policy (idempotent)
    step "Attaching AWSLambdaBasicExecutionRole"
    aws iam attach-role-policy \
        --role-name  "$ROLE_NAME" \
        --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" \
        2>/dev/null || true
    ok "AWSLambdaBasicExecutionRole attached"

    # DynamoDB GetItem inline policy (idempotent put)
    step "Ensuring DynamoDB GetItem policy on ${TABLE_NAME}"
    aws iam put-role-policy \
        --role-name   "$ROLE_NAME" \
        --policy-name "CallbackSchedulerDynamoDBRead" \
        --policy-document "{
            \"Version\": \"2012-10-17\",
            \"Statement\": [{
                \"Effect\": \"Allow\",
                \"Action\": [\"dynamodb:GetItem\"],
                \"Resource\": \"arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${TABLE_NAME}\"
            }]
        }"
    ok "DynamoDB GetItem policy in place"

    ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
    state_set "role_arn" "$ROLE_ARN"
    state_set "role_name" "$ROLE_NAME"

    # IAM propagation — Lambda create will fail immediately after iam create-role
    step "Waiting 15 s for IAM role propagation …"
    sleep 15
}

# =============================================================================
#  Step 2 — Update DynamoDB with callback queue placeholder fields
# =============================================================================
update_routing_table_with_callback_queues() {
    header "DynamoDB: add callbackQueueId fields to ${TABLE_NAME}"

    if [[ -z "$(dynamodb_table_exists "$TABLE_NAME" "$REGION")" ]]; then
        warn "Table '${TABLE_NAME}' does not exist."
        warn "Run ./scripts/deploy_routing_lambda.sh deploy first, then re-run this script."
        return 0
    fi

    # Format: topicCategory|callbackQueueName
    # callbackQueueId / callbackQueueArn are set to PLACEHOLDER — update after
    # creating callback queues in Connect console.
    local rows=(
        'mortgage|Mortgage Callback'
        'credit_card|Cards Callback'
        'debit_card|Cards Callback'
        'fraud_security|Fraud Callback'
        'complaint|Complaints Callback'
        'current_account|Retail Callback'
        'savings_account|Retail Callback'
        'general_banking|General Callback'
    )

    for row in "${rows[@]}"; do
        IFS='|' read -r topic cb_queue_name <<< "$row"

        aws dynamodb update-item \
            --table-name "$TABLE_NAME" \
            --region     "$REGION" \
            --key "{\"topicCategory\": {\"S\": \"${topic}\"}}" \
            --update-expression "SET callbackQueueId = :cid, callbackQueueArn = :carn, callbackQueueName = :cname" \
            --expression-attribute-values "{
                \":cid\":   {\"S\": \"PLACEHOLDER_${topic}_callback_queue_uuid\"},
                \":carn\":  {\"S\": \"PLACEHOLDER_arn:aws:connect:${REGION}:${ACCOUNT_ID}:instance/INSTANCE_ID/queue/CALLBACK_QUEUE_UUID\"},
                \":cname\": {\"S\": \"${cb_queue_name}\"}
            }"

        step "  updated: ${topic} → ${cb_queue_name} (PLACEHOLDER — update UUID after creating queue)"
    done

    ok "8 rows updated with callbackQueueId placeholders"
    warn "ACTION REQUIRED: replace PLACEHOLDER values in DynamoDB after creating callback queues"
    warn "  Run: ./scripts/deploy_callback_lambda.sh update-queues"
    warn "  Or manually update via AWS Console → DynamoDB → Tables → ${TABLE_NAME}"
}

# =============================================================================
#  Interactive update-queues command: prompts for real queue IDs
# =============================================================================
cmd_update_queues() {
    header "Update DynamoDB callback queue IDs — ${TABLE_NAME}"

    if [[ -z "$(dynamodb_table_exists "$TABLE_NAME" "$REGION")" ]]; then
        die "Table '${TABLE_NAME}' does not exist. Run deploy_routing_lambda.sh first."
    fi

    echo -e "${YELLOW}  For each topic, enter the real callback queue UUID (from Connect console).${NC}"
    echo -e "${YELLOW}  Leave blank to skip (keep existing value).${NC}"
    echo ""
    echo -e "  To find a queue UUID: Connect console → Routing → Queues → click queue"
    echo -e "  The UUID is the last segment of the URL, e.g.:"
    echo -e "  ${CYAN}  https://.../routing/queues/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee${NC}"
    echo ""

    local topics=(
        'mortgage:Mortgage Callback'
        'credit_card:Cards Callback'
        'debit_card:Cards Callback'
        'fraud_security:Fraud Callback'
        'complaint:Complaints Callback'
        'current_account:Retail Callback'
        'savings_account:Retail Callback'
        'general_banking:General Callback'
    )

    local instance_id=""
    ask instance_id "Connect instance ID (for ARN construction)" ""

    for entry in "${topics[@]}"; do
        IFS=':' read -r topic cb_name <<< "$entry"
        local queue_uuid=""
        ask queue_uuid "  ${topic} → ${cb_name} — queue UUID" ""

        if [[ -n "$queue_uuid" ]]; then
            local cb_arn=""
            if [[ -n "$instance_id" ]]; then
                cb_arn="arn:aws:connect:${REGION}:${ACCOUNT_ID}:instance/${instance_id}/queue/${queue_uuid}"
            fi

            aws dynamodb update-item \
                --table-name "$TABLE_NAME" \
                --region     "$REGION" \
                --key "{\"topicCategory\": {\"S\": \"${topic}\"}}" \
                --update-expression "SET callbackQueueId = :cid, callbackQueueArn = :carn" \
                --expression-attribute-values "{
                    \":cid\":  {\"S\": \"${queue_uuid}\"},
                    \":carn\": {\"S\": \"${cb_arn}\"}
                }"
            ok "  ${topic} updated → ${queue_uuid}"
        else
            step "  ${topic} — skipped"
        fi
    done

    ok "Callback queue IDs updated"
}

# =============================================================================
#  Step 3 — Deploy Lambda code + publish version + update prod alias
# =============================================================================
deploy_lambda_and_alias() {
    header "Lambda: ${FUNCTION_NAME}"

    local zip_path="/tmp/${FUNCTION_NAME}.zip"
    step "Packaging ${LAMBDA_SOURCE}"
    (cd "$LAMBDA_DIR" && zip -j "$zip_path" aria_callback_scheduler.py)
    ok "Package ready: ${zip_path}"

    # ── Create or update ─────────────────────────────────────────────────────
    if [[ -n "$(lambda_exists "$FUNCTION_NAME" "$REGION")" ]]; then
        step "Updating function code"
        aws lambda update-function-code \
            --function-name "$FUNCTION_NAME" \
            --zip-file      "fileb://${zip_path}" \
            --region        "$REGION" \
            --output text --query "FunctionArn" > /dev/null
        ok "Function code updated"

        # Wait for update to settle before publishing
        step "Waiting for update to settle …"
        aws lambda wait function-updated \
            --function-name "$FUNCTION_NAME" \
            --region        "$REGION" 2>/dev/null || sleep 10

        # Keep env vars in sync
        step "Updating environment variables"
        aws lambda update-function-configuration \
            --function-name "$FUNCTION_NAME" \
            --environment "Variables={ROUTING_TABLE=${TABLE_NAME}}" \
            --region "$REGION" \
            --output text --query "FunctionArn" > /dev/null
        aws lambda wait function-updated \
            --function-name "$FUNCTION_NAME" \
            --region        "$REGION" 2>/dev/null || sleep 5
    else
        step "Creating Lambda function '${FUNCTION_NAME}'"
        aws lambda create-function \
            --function-name "$FUNCTION_NAME" \
            --runtime       python3.12 \
            --role          "arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}" \
            --handler       aria_callback_scheduler.handler \
            --zip-file      "fileb://${zip_path}" \
            --timeout       10 \
            --memory-size   256 \
            --environment   "Variables={ROUTING_TABLE=${TABLE_NAME}}" \
            --description   "ARIA callback queue resolver — reads DynamoDB, returns callbackQueueId for dynamic Set Working Queue" \
            --region        "$REGION" \
            --output text --query "FunctionArn" > /dev/null
        ok "Lambda created"

        step "Waiting for Lambda to become active …"
        aws lambda wait function-active \
            --function-name "$FUNCTION_NAME" \
            --region        "$REGION" 2>/dev/null || sleep 15
    fi

    # ── Publish immutable version ─────────────────────────────────────────────
    step "Publishing new version"
    local new_version
    new_version=$(aws lambda publish-version \
        --function-name "$FUNCTION_NAME" \
        --region        "$REGION" \
        --query         "Version" \
        --output        text)
    ok "Published version ${new_version}"
    state_set "lambda_version" "$new_version"

    # ── Create or update prod alias ───────────────────────────────────────────
    local alias_exists
    alias_exists=$(aws lambda get-alias \
        --function-name "$FUNCTION_NAME" \
        --name          "$ALIAS_NAME" \
        --region        "$REGION" \
        --query         "Name" \
        --output        text 2>/dev/null || true)

    if [[ -n "$alias_exists" ]]; then
        step "Updating '${ALIAS_NAME}' alias → version ${new_version}"
        aws lambda update-alias \
            --function-name    "$FUNCTION_NAME" \
            --name             "$ALIAS_NAME" \
            --function-version "$new_version" \
            --region           "$REGION" \
            --output text --query "AliasArn" > /dev/null
    else
        step "Creating '${ALIAS_NAME}' alias → version ${new_version}"
        aws lambda create-alias \
            --function-name    "$FUNCTION_NAME" \
            --name             "$ALIAS_NAME" \
            --function-version "$new_version" \
            --region           "$REGION" \
            --output text --query "AliasArn" > /dev/null
    fi

    LAMBDA_ALIAS_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNCTION_NAME}:${ALIAS_NAME}"
    state_set "lambda_alias_arn" "$LAMBDA_ALIAS_ARN"
    ok "Alias '${ALIAS_NAME}' → version ${new_version}: ${LAMBDA_ALIAS_ARN}"

    rm -f "$zip_path"
}

# =============================================================================
#  Step 4 — Grant Connect permission to invoke the Lambda
# =============================================================================
add_connect_permission() {
    if [[ -z "$CONNECT_INSTANCE_ID" ]]; then
        warn "No --instance-id provided — skipping Connect resource-based policy."
        warn "You will need to add the Lambda to Connect manually:"
        warn "  Connect console → your instance → AWS Lambda → Add Lambda function"
        warn "  Function name: ${FUNCTION_NAME}"
        return
    fi

    header "Connect permission on :${ALIAS_NAME} alias"

    local instance_arn="arn:aws:connect:${REGION}:${ACCOUNT_ID}:instance/${CONNECT_INSTANCE_ID}"

    step "Adding resource-based policy for Connect instance"
    aws lambda add-permission \
        --function-name    "${FUNCTION_NAME}:${ALIAS_NAME}" \
        --statement-id     "ConnectInvoke-callback-scheduler" \
        --action           "lambda:InvokeFunction" \
        --principal        "connect.amazonaws.com" \
        --source-arn       "$instance_arn" \
        --source-account   "$ACCOUNT_ID" \
        --region           "$REGION" 2>/dev/null || \
    warn "ConnectInvoke permission already set (non-fatal)"

    ok "Connect can now invoke ${LAMBDA_ALIAS_ARN}"

    state_set "connect_instance_id" "$CONNECT_INSTANCE_ID"

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
    echo -e "${BOLD}${GREEN}  ARIA Callback Scheduler Lambda — Deploy Complete${NC}"
    echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  ${BOLD}Lambda ARN (prod alias):${NC}"
    echo -e "    ${CYAN}${LAMBDA_ALIAS_ARN}${NC}"
    echo ""
    echo -e "  ${BOLD}Lambda version deployed:${NC}  ${version}"
    echo ""
    echo -e "  ${BOLD}DynamoDB table:${NC}"
    echo -e "    arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${TABLE_NAME}"
    echo -e "    ${YELLOW}callbackQueueId fields added with PLACEHOLDER values${NC}"
    echo ""
    echo -e "  ${BOLD}State file:${NC}  ${STATE_FILE}"
    echo ""
    echo -e "${BOLD}${YELLOW}  Required manual steps (in order):${NC}"
    echo ""
    echo -e "  ${YELLOW}1. Create dedicated callback queues in Connect console:${NC}"
    echo -e "     Connect → Routing → Queues → Add new queue"
    echo -e "     Create one per topic: aria-callback-mortgage, aria-callback-cards,"
    echo -e "     aria-callback-fraud, aria-callback-retail, aria-callback-general"
    echo -e "     Set: Hours of operation, Outbound caller ID phone number"
    echo ""
    echo -e "  ${YELLOW}2. Add each callback queue to routing profiles:${NC}"
    echo -e "     Connect → Users → Routing profiles → ARIA Banking"
    echo -e "     Add callback queues at LOWER priority than inbound queues"
    echo ""
    echo -e "  ${YELLOW}3. Update DynamoDB with real callback queue UUIDs:${NC}"
    echo -e "     ./scripts/deploy_callback_lambda.sh update-queues"
    echo ""
    echo -e "  ${YELLOW}4. Add Lambda to Connect instance allow-list:${NC}"
    echo -e "     Connect console → <instance> → AWS Lambda → Add Lambda function"
    echo -e "     Function name: ${FUNCTION_NAME}"
    echo ""
    echo -e "  ${YELLOW}5. In the ARIA-Callback-Offer flow (block by block — see Part L of guide):${NC}"
    echo -e "     'Invoke AWS Lambda' block → select ${FUNCTION_NAME} (:prod alias)"
    echo -e "     'Set working queue' block → Dynamic → \$.External.callbackQueueId"
    echo -e "     'Transfer to queue' → Transfer to Callback tab"
    echo ""
    echo -e "  ${YELLOW}6. Build outbound whisper and agent whisper flows (Part L guide).${NC}"
    echo ""
    echo -e "${BOLD}${GREEN}  Re-run 'deploy' after every Lambda code change.${NC}"
    echo -e "${BOLD}${GREEN}  The prod alias tracks the latest version automatically.${NC}"
    echo ""
}

# =============================================================================
#  Status
# =============================================================================
cmd_status() {
    header "Status — ${FUNCTION_NAME}"

    echo -e "${BOLD}  State file:${NC} ${STATE_FILE}"
    if [[ -f "$STATE_FILE" ]]; then
        cat "$STATE_FILE"
    else
        warn "State file does not exist — run 'deploy' first"
    fi

    echo ""
    echo -e "${BOLD}  Live Lambda status:${NC}"
    aws lambda get-function \
        --function-name "${FUNCTION_NAME}:${ALIAS_NAME}" \
        --region        "$REGION" \
        --query         "Configuration.[FunctionArn,Runtime,Timeout,MemorySize,LastModified]" \
        --output        table 2>/dev/null || warn "Lambda not deployed yet"

    echo ""
    echo -e "${BOLD}  DynamoDB rows (callback queue fields):${NC}"
    aws dynamodb scan \
        --table-name        "$TABLE_NAME" \
        --region            "$REGION" \
        --projection-expression "topicCategory,callbackQueueId,callbackQueueName" \
        --output            table 2>/dev/null || warn "DynamoDB table not found or no rows"
}

# =============================================================================
#  Teardown
# =============================================================================
cmd_teardown() {
    header "Teardown — aria-callback-scheduler resources"

    # Lambda (all versions + aliases)
    if ask_yn "Delete Lambda function '${FUNCTION_NAME}' (all versions + aliases)?" "N"; then
        aws lambda delete-function \
            --function-name "$FUNCTION_NAME" \
            --region        "$REGION" 2>/dev/null && \
        ok "Lambda deleted" || warn "Lambda not found — skipping"
    fi

    # CloudWatch Log Group
    local log_group="/aws/lambda/${FUNCTION_NAME}"
    if ask_yn "Delete CloudWatch Log Group '${log_group}'?" "N"; then
        aws logs delete-log-group \
            --log-group-name "$log_group" \
            --region         "$REGION" 2>/dev/null && \
        ok "Log group deleted" || warn "Log group not found — skipping"
    fi

    # IAM role + policies
    if ask_yn "Delete IAM role '${ROLE_NAME}' and its policies?" "N"; then
        aws iam detach-role-policy \
            --role-name  "$ROLE_NAME" \
            --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" \
            2>/dev/null || true
        aws iam delete-role-policy \
            --role-name   "$ROLE_NAME" \
            --policy-name "CallbackSchedulerDynamoDBRead" \
            2>/dev/null || true
        aws iam delete-role \
            --role-name "$ROLE_NAME" \
            2>/dev/null && \
        ok "IAM role deleted" || warn "IAM role not found — skipping"
    fi

    # DynamoDB callback fields — note: we do NOT delete the table (shared with routing lambda)
    # Instead, offer to clear the callbackQueueId fields back to PLACEHOLDER
    if ask_yn "Reset callbackQueueId fields in '${TABLE_NAME}' to PLACEHOLDER values?" "N"; then
        local topics=('mortgage' 'credit_card' 'debit_card' 'fraud_security' 'complaint' 'current_account' 'savings_account' 'general_banking')
        for topic in "${topics[@]}"; do
            aws dynamodb update-item \
                --table-name "$TABLE_NAME" \
                --region     "$REGION" \
                --key "{\"topicCategory\": {\"S\": \"${topic}\"}}" \
                --update-expression "REMOVE callbackQueueId, callbackQueueArn, callbackQueueName" \
                2>/dev/null || true
        done
        ok "callbackQueueId fields removed from routing rows"
    fi

    # Local artefacts
    local zip_path="/tmp/${FUNCTION_NAME}.zip"
    [[ -f "$zip_path"   ]] && rm "$zip_path"   && ok "Removed temp zip: ${zip_path}"
    [[ -f "$STATE_FILE" ]] && rm "$STATE_FILE" && ok "State file removed"

    ok "Teardown complete"
}

# =============================================================================
#  Argument parsing
# =============================================================================
parse_args() {
    COMMAND="${1:-}"
    shift || true

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --instance-id)   CONNECT_INSTANCE_ID="$2"; shift 2 ;;
            --region)        REGION="$2";               shift 2 ;;
            *)               warn "Unknown flag: $1";   shift   ;;
        esac
    done
}

# =============================================================================
#  Main
# =============================================================================
main() {
    if [[ $# -eq 0 ]]; then
        echo "Usage: $0 deploy|update-queues|status|teardown [--instance-id <connect-uuid>] [--region <region>]"
        exit 1
    fi

    parse_args "$@"
    state_init

    case "$COMMAND" in
        deploy)
            echo ""
            echo -e "${BOLD}${BLUE}ARIA — Callback Scheduler Lambda Deploy${NC}"
            echo -e "${BOLD}${BLUE}Region: ${REGION}${NC}"
            echo ""

            ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
            ok "AWS Account: ${ACCOUNT_ID}  Region: ${REGION}"

            ensure_iam_role
            update_routing_table_with_callback_queues
            deploy_lambda_and_alias
            add_connect_permission
            print_summary
            ;;

        update-queues)
            ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
            cmd_update_queues
            ;;

        status)
            ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "unknown")
            cmd_status
            ;;

        teardown)
            ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
            cmd_teardown
            ;;

        *)
            die "Unknown command '${COMMAND}'. Use: deploy | update-queues | status | teardown"
            ;;
    esac
}

main "$@"
