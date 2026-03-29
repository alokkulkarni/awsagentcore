#!/usr/bin/env bash
# =============================================================================
#  ARIA — Amazon Bedrock AgentCore Full Stack Deploy & Teardown
# =============================================================================
#
#  USAGE
#    ./scripts/deploy.sh deploy     — deploy the full stack to AWS
#    ./scripts/deploy.sh teardown   — destroy all AWS resources
#    ./scripts/deploy.sh status     — print current deployment state
#
#  PREREQUISITES
#    • aws CLI v2       (brew install awscli  OR  pip install awscli)
#    • agentcore CLI    (pip install bedrock-agentcore-starter-toolkit)
#    • python3          (already in PATH if you have the venv active)
#    • Bedrock model access enabled:
#        - Claude Sonnet in eu-west-2  (Bedrock console → Model access)
#        - Nova Sonic 2  in eu-north-1 (Bedrock console → Model access)
#
#  WHAT IT CREATES
#    S3             meridian-aria-transcripts-<account>  (transcript storage)
#    S3             meridian-aria-audit-<account>         (WORM audit archive)
#    DynamoDB       aria-audit-events                     (hot audit queries, 90d TTL)
#    EventBridge    aria-audit                            (custom audit bus)
#    CloudTrail     aria-banking-audit (data store + channel, 7yr)
#    Lambda ×2      audit_cloudtrail_writer, audit_dynamodb_writer
#    Firehose       aria-audit-firehose                   (S3 WORM delivery)
#    IAM roles      aria-lambda-audit-role, aria-firehose-audit-role
#    ECR repo       bedrock-agentcore-aria-banking-agent  (auto-created by agentcore)
#    AgentCore      aria_banking_agent runtime            (eu-west-2)
#
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
STATE_FILE="${SCRIPT_DIR}/.deploy-state.json"
YAML_FILE="${PROJECT_ROOT}/.bedrock_agentcore.yaml"
LAMBDA_DIR="${SCRIPT_DIR}/lambdas"

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

header()  { echo -e "\n${BOLD}${BLUE}══ $* ══${NC}" >&2; }
step()    { echo -e "${CYAN}  ▶ $*${NC}" >&2; }
ok()      { echo -e "${GREEN}  ✔ $*${NC}" >&2; }
warn()    { echo -e "${YELLOW}  ⚠ $*${NC}" >&2; }
error()   { echo -e "${RED}  ✖ $*${NC}" >&2; }
die()     { error "$*"; exit 1; }

# ── Prompt helper (reads from TTY directly so piping doesn't break it) ────────
ask() {
    # ask VAR "Question" "default"
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
    # ask_yn "Question" "Y|N" → returns 0 (yes) or 1 (no)
    local prompt="$1" default="${2:-Y}"
    local display="y/n"
    [[ "${default^^}" == "Y" ]] && display="Y/n" || display="y/N"
    printf "${BOLD}  ? ${prompt} [${display}]: ${NC}" >/dev/tty
    local input
    read -r input </dev/tty
    [[ -z "$input" ]] && input="$default"
    [[ "${input^^}" == "Y" ]]
}

# ── State management (Python-backed JSON, no jq needed) ──────────────────────
state_init() {
    [[ -f "$STATE_FILE" ]] || echo '{}' > "$STATE_FILE"
}

# A short random hex suffix generated once per deployment and persisted in
# state. Used in place of account ID for resource names (S3 buckets, CloudTrail
# Lake fallback name) so no AWS account number appears in any resource name.
get_or_create_deploy_id() {
    local existing
    existing=$(state_get "deploy_id" 2>/dev/null || true)
    if [[ -n "$existing" ]]; then
        echo "$existing"
    else
        local new_id
        new_id=$(python3 -c "import secrets; print(secrets.token_hex(3))")
        state_set "deploy_id" "$new_id"
        echo "$new_id"
    fi
}

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

# ── YAML patcher (Python yaml) ────────────────────────────────────────────────
patch_yaml_env() {
    # patch_yaml_env KEY VALUE
    python3 - "$YAML_FILE" "$1" "$2" <<'PYEOF'
import sys, re

yaml_file, key, value = sys.argv[1], sys.argv[2], sys.argv[3]
with open(yaml_file) as f:
    content = f.read()

# Match "        KEY: anything_or_empty" and replace value
pattern = rf'^(\s+{re.escape(key)}:).*$'
replacement = rf'\g<1> {value}'
new_content, n = re.subn(pattern, replacement, content, flags=re.MULTILINE)

if n == 0:
    print(f"WARN: key '{key}' not found in {yaml_file}", file=sys.stderr)
else:
    with open(yaml_file, "w") as f:
        f.write(new_content)
    print(f"  patched {key} = {value}")
PYEOF
}

# ── AWS helpers ───────────────────────────────────────────────────────────────
aws_account_id() {
    aws sts get-caller-identity --query Account --output text
}

bucket_exists() {
    aws s3api head-bucket --bucket "$1" 2>/dev/null
}

dynamodb_table_exists() {
    aws dynamodb describe-table --table-name "$1" --region "$2" \
        --query "Table.TableName" --output text 2>/dev/null || true
}

eventbus_exists() {
    aws events describe-event-bus --name "$1" --region "$2" \
        --query "Name" --output text 2>/dev/null || true
}

lambda_exists() {
    aws lambda get-function --function-name "$1" --region "$2" \
        --query "Configuration.FunctionName" --output text 2>/dev/null || true
}

iam_role_exists() {
    aws iam get-role --role-name "$1" \
        --query "Role.RoleName" --output text 2>/dev/null || true
}

# =============================================================================
#  DEPLOY
# =============================================================================

check_prerequisites() {
    header "Checking prerequisites"
    local ok=true

    command -v aws    >/dev/null 2>&1 && ok "aws CLI found"    || { error "aws CLI not found. brew install awscli"; ok=false; }
    command -v python3 >/dev/null 2>&1 && ok "python3 found"   || { error "python3 not found"; ok=false; }

    if command -v agentcore >/dev/null 2>&1; then
        ok "agentcore CLI found ($(agentcore --version 2>/dev/null || echo 'unknown version'))"
    else
        error "agentcore CLI not found. Run: pip install bedrock-agentcore-starter-toolkit"
        ok=false
    fi

    if aws sts get-caller-identity >/dev/null 2>&1; then
        ok "AWS credentials valid (account: $(aws_account_id))"
    else
        error "AWS credentials not configured. Run: aws configure"
        ok=false
    fi

    [[ "$ok" == "true" ]] || die "Fix the above issues then re-run."
}

collect_inputs() {
    header "Deployment configuration"
    echo -e "  Press Enter to accept defaults shown in [brackets].\n"

    # Auto-detect account ID (used only for ARN construction, not in resource names)
    ACCOUNT_ID=$(aws_account_id)

    # A stable random suffix stored in state — avoids account ID in resource names
    state_init
    DEPLOY_ID=$(get_or_create_deploy_id)

    ask AGENTCORE_REGION   "AgentCore Runtime region"       "eu-west-2"
    ask CLAUDE_REGION      "Claude (chat) region"           "eu-west-2"
    ask NOVA_SONIC_REGION  "Nova Sonic (voice) region"      "eu-north-1"
    ask TRANSCRIPT_BUCKET  "Transcript S3 bucket name"      "meridian-aria-transcripts-${DEPLOY_ID}"
    ask AUDIT_BUCKET       "Audit archive S3 bucket name"   "meridian-aria-audit-${DEPLOY_ID}"
    ask AGENT_NAME         "AgentCore agent name"           "aria_banking_agent"
    # AgentCore agentRuntimeName only allows [a-zA-Z][a-zA-Z0-9_]{0,47} — sanitize hyphens
    AGENT_NAME="${AGENT_NAME//-/_}"
    ask BANK_API_BASE_URL  "Bank API base URL"              "https://api.meridianbank.internal"
    ask BANK_API_KEY       "Bank API key"                   "your-api-key-here"

    echo ""
    ask DEPLOY_MODE "Build mode — 1=CodeBuild/cloud (recommended, no Docker needed), 2=Local Docker build" "1"

    echo -e "\n  ${BOLD}Summary:${NC}"
    echo "    Deploy ID:            ${DEPLOY_ID}"
    echo "    AgentCore region:     ${AGENTCORE_REGION}"
    echo "    Claude region:        ${CLAUDE_REGION}"
    echo "    Nova Sonic region:    ${NOVA_SONIC_REGION}"
    echo "    Transcript bucket:    ${TRANSCRIPT_BUCKET}"
    echo "    Audit bucket:         ${AUDIT_BUCKET}"
    echo "    Agent name:           ${AGENT_NAME}"
    echo "    Build mode:           $([[ "$DEPLOY_MODE" == "1" ]] && echo 'CodeBuild (cloud)' || echo 'Local Docker')"
    echo ""

    ask_yn "Proceed with deployment?" "Y" || die "Deployment cancelled."

    # Persist to state file (account_id kept for ARN construction, not used in names)
    state_set "account_id"        "$ACCOUNT_ID"
    state_set "agentcore_region"  "$AGENTCORE_REGION"
    state_set "claude_region"     "$CLAUDE_REGION"
    state_set "nova_sonic_region" "$NOVA_SONIC_REGION"
    state_set "transcript_bucket" "$TRANSCRIPT_BUCKET"
    state_set "audit_bucket"      "$AUDIT_BUCKET"
    state_set "agent_name"        "$AGENT_NAME"
}

create_s3_buckets() {
    header "S3 Buckets"

    # Transcript bucket (standard)
    step "Creating transcript bucket: ${TRANSCRIPT_BUCKET}"
    if bucket_exists "$TRANSCRIPT_BUCKET"; then
        warn "Bucket already exists — skipping"
    else
        if [[ "$AGENTCORE_REGION" == "us-east-1" ]]; then
            aws s3api create-bucket --bucket "$TRANSCRIPT_BUCKET" \
                --region "$AGENTCORE_REGION"
        else
            aws s3api create-bucket --bucket "$TRANSCRIPT_BUCKET" \
                --region "$AGENTCORE_REGION" \
                --create-bucket-configuration LocationConstraint="${AGENTCORE_REGION}"
        fi
        aws s3api put-bucket-versioning --bucket "$TRANSCRIPT_BUCKET" \
            --versioning-configuration Status=Enabled
        ok "Transcript bucket created"
    fi

    # Audit bucket (Object Lock WORM for PCI-DSS compliance)
    step "Creating audit WORM bucket: ${AUDIT_BUCKET}"
    if bucket_exists "$AUDIT_BUCKET"; then
        warn "Bucket already exists — skipping"
    else
        if [[ "$AGENTCORE_REGION" == "us-east-1" ]]; then
            aws s3api create-bucket --bucket "$AUDIT_BUCKET" \
                --region "$AGENTCORE_REGION" \
                --object-lock-enabled-for-bucket
        else
            aws s3api create-bucket --bucket "$AUDIT_BUCKET" \
                --region "$AGENTCORE_REGION" \
                --create-bucket-configuration LocationConstraint="${AGENTCORE_REGION}" \
                --object-lock-enabled-for-bucket
        fi
        # Default COMPLIANCE retention: 7 years (2557 days)
        aws s3api put-object-lock-configuration \
            --bucket "$AUDIT_BUCKET" \
            --object-lock-configuration '{
                "ObjectLockEnabled": "Enabled",
                "Rule": {
                    "DefaultRetention": {
                        "Mode": "COMPLIANCE",
                        "Days": 2557
                    }
                }
            }'
        ok "Audit WORM bucket created (Object Lock COMPLIANCE, 7yr default)"
    fi
}

create_dynamodb_table() {
    header "DynamoDB audit table"
    step "Creating aria-audit-events"

    if [[ -n "$(dynamodb_table_exists 'aria-audit-events' "$AGENTCORE_REGION")" ]]; then
        warn "Table already exists — ensuring TTL is enabled"
        aws dynamodb wait table-exists \
            --table-name aria-audit-events \
            --region "$AGENTCORE_REGION"
        aws dynamodb update-time-to-live \
            --table-name aria-audit-events \
            --time-to-live-specification "Enabled=true,AttributeName=ttl" \
            --region "$AGENTCORE_REGION" > /dev/null 2>&1 || true
    else
        aws dynamodb create-table \
            --table-name aria-audit-events \
            --attribute-definitions \
                AttributeName=customer_id,AttributeType=S \
                AttributeName=timestamp,AttributeType=S \
            --key-schema \
                AttributeName=customer_id,KeyType=HASH \
                AttributeName=timestamp,KeyType=RANGE \
            --billing-mode PAY_PER_REQUEST \
            --region "$AGENTCORE_REGION" \
            --output text --query "TableDescription.TableName" > /dev/null

        # Wait for table to reach ACTIVE state before enabling TTL
        step "Waiting for aria-audit-events to become ACTIVE..."
        aws dynamodb wait table-exists \
            --table-name aria-audit-events \
            --region "$AGENTCORE_REGION"

        # Enable TTL
        aws dynamodb update-time-to-live \
            --table-name aria-audit-events \
            --time-to-live-specification "Enabled=true,AttributeName=ttl" \
            --region "$AGENTCORE_REGION" > /dev/null

        ok "DynamoDB table created with TTL on 'ttl' attribute"
    fi
}

create_eventbridge_bus() {
    header "EventBridge audit bus"
    step "Creating aria-audit custom event bus"

    if [[ -n "$(eventbus_exists 'aria-audit' "$AGENTCORE_REGION")" ]]; then
        warn "Event bus already exists — skipping"
        BUS_ARN="arn:aws:events:${AGENTCORE_REGION}:${ACCOUNT_ID}:event-bus/aria-audit"
    else
        BUS_ARN=$(aws events create-event-bus \
            --name aria-audit \
            --region "$AGENTCORE_REGION" \
            --query "EventBusArn" --output text)
        ok "Event bus created: ${BUS_ARN}"
    fi
    state_set "eventbridge_bus_arn" "$BUS_ARN"
}

create_cloudtrail_lake() {
    header "CloudTrail Lake (immutable audit store)"

    local ACTIVITY_SELECTORS='[{"Name":"ARIA custom audit events","FieldSelectors":[{"Field":"eventCategory","Equals":["ActivityAuditLog"]}]}]'
    local PRIMARY_NAME="aria-banking-audit"
    local FALLBACK_NAME="aria-banking-audit-${DEPLOY_ID}"

    step "Checking CloudTrail Lake event data store"
    local eds_arn="" eds_name=""

    # Fetch store list with explicit timeouts — avoids infinite hang if the API
    # is slow or the region has a cold-start delay. Falls back to empty list.
    local stores_json
    stores_json=$(aws cloudtrail list-event-data-stores \
        --region "$AGENTCORE_REGION" \
        --cli-connect-timeout 10 --cli-read-timeout 20 \
        --output json 2>/dev/null || echo '{"EventDataStores":[]}')

    # Find first ENABLED store — no process substitution, no read/heredoc
    local eds_info
    eds_info=$(echo "$stores_json" | python3 -c "
import json, sys
try:
    stores = json.load(sys.stdin).get('EventDataStores', [])
except Exception:
    stores = []
for name in ['${PRIMARY_NAME}', '${FALLBACK_NAME}']:
    for s in stores:
        if s.get('Name') == name and s.get('Status') == 'ENABLED':
            print(s['EventDataStoreArn'] + '|' + s['Name'])
            raise SystemExit(0)
" 2>/dev/null || true)

    if [[ -n "$eds_info" ]]; then
        eds_arn="${eds_info%%|*}"
        eds_name="${eds_info##*|}"
        warn "Event data store '${eds_name}' is ENABLED — skipping creation"
    else
        # Check if primary name is blocked in any non-ENABLED status
        local primary_exists
        primary_exists=$(echo "$stores_json" | python3 -c "
import json, sys
try:
    stores = json.load(sys.stdin).get('EventDataStores', [])
except Exception:
    stores = []
print('yes' if any(s.get('Name') == '${PRIMARY_NAME}' for s in stores) else '')
" 2>/dev/null || true)

        if [[ -n "$primary_exists" ]]; then
            warn "Primary name blocked (PENDING_DELETION) — using fallback: ${FALLBACK_NAME}"
            eds_name="$FALLBACK_NAME"
        else
            eds_name="$PRIMARY_NAME"
        fi

        step "Creating event data store: ${eds_name}"
        local create_out create_err
        create_out=$(aws cloudtrail create-event-data-store \
            --name "$eds_name" \
            --retention-period 2557 \
            --no-multi-region-enabled \
            --advanced-event-selectors "$ACTIVITY_SELECTORS" \
            --region "$AGENTCORE_REGION" \
            --query "EventDataStoreArn" --output text 2>/tmp/ctl_err) \
            && eds_arn="$create_out" \
            || {
                create_err=$(cat /tmp/ctl_err)
                if echo "$create_err" | grep -q "AlreadyExists"; then
                    warn "Store already exists — looking up ARN"
                    eds_arn=$(aws cloudtrail list-event-data-stores \
                        --region "$AGENTCORE_REGION" \
                        --cli-read-timeout 20 \
                        --query "EventDataStores[?Name=='${eds_name}'].EventDataStoreArn | [0]" \
                        --output text 2>/dev/null || true)
                else
                    warn "CloudTrail Lake unavailable: ${create_err} — audit continues via DynamoDB/S3"
                fi
            }
        rm -f /tmp/ctl_err
        [[ -n "$eds_arn" ]] && ok "Event data store ready: ${eds_name}"
    fi

    state_set "cloudtrail_eds_arn"  "${eds_arn:-}"
    state_set "cloudtrail_eds_name" "${eds_name:-}"

    # ── Channel (non-fatal — DynamoDB/S3 audit paths work without it) ──────────
    step "Creating CloudTrail Lake channel"
    local channel_arn
    channel_arn=$(aws cloudtrail list-channels \
        --region "$AGENTCORE_REGION" \
        --cli-read-timeout 20 \
        --query "Channels[?Name=='aria-audit-channel'].ChannelArn" \
        --output text 2>/dev/null || true)

    if [[ "$channel_arn" == "None" || -z "$channel_arn" ]]; then
        if [[ -n "$eds_arn" ]]; then
            channel_arn=$(aws cloudtrail create-channel \
                --name aria-audit-channel \
                --source Custom \
                --destinations "[{\"Type\":\"EVENT_DATA_STORE\",\"Location\":\"${eds_arn}\"}]" \
                --region "$AGENTCORE_REGION" \
                --query "ChannelArn" --output text 2>/dev/null) \
                && ok "Channel created: ${channel_arn}" \
                || { warn "Channel creation failed — audit continues via DynamoDB/S3 only"; channel_arn=""; }
        else
            warn "Skipping channel — no valid event data store ARN"
            channel_arn=""
        fi
    else
        warn "Channel already exists — skipping"
    fi

    state_set "cloudtrail_channel_arn" "${channel_arn:-}"
    CLOUDTRAIL_CHANNEL_ARN="${channel_arn:-}"
}




create_lambda_iam_role() {
    header "Lambda IAM role for audit writers"
    local role_name="aria-lambda-audit-role"

    if [[ -n "$(iam_role_exists "$role_name")" ]]; then
        warn "IAM role already exists — skipping"
    else
        step "Creating ${role_name}"
        aws iam create-role \
            --role-name "$role_name" \
            --assume-role-policy-document '{
                "Version":"2012-10-17",
                "Statement":[{
                    "Effect":"Allow",
                    "Principal":{"Service":"lambda.amazonaws.com"},
                    "Action":"sts:AssumeRole"
                }]
            }' \
            --query "Role.RoleName" --output text > /dev/null

        aws iam attach-role-policy \
            --role-name "$role_name" \
            --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"

        # CloudTrail Lake write
        aws iam put-role-policy \
            --role-name "$role_name" \
            --policy-name "CloudTrailLakeWrite" \
            --policy-document "{
                \"Version\":\"2012-10-17\",
                \"Statement\":[{
                    \"Effect\":\"Allow\",
                    \"Action\":[\"cloudtrail-data:PutAuditEvents\"],
                    \"Resource\":\"${CLOUDTRAIL_CHANNEL_ARN}\"
                }]
            }"

        # DynamoDB write
        aws iam put-role-policy \
            --role-name "$role_name" \
            --policy-name "DynamoDBAuditWrite" \
            --policy-document "{
                \"Version\":\"2012-10-17\",
                \"Statement\":[{
                    \"Effect\":\"Allow\",
                    \"Action\":[\"dynamodb:PutItem\"],
                    \"Resource\":\"arn:aws:dynamodb:${AGENTCORE_REGION}:${ACCOUNT_ID}:table/aria-audit-events\"
                }]
            }"

        ok "Lambda IAM role created"
        step "Waiting 15s for IAM role propagation..."
        sleep 15
    fi

    LAMBDA_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${role_name}"
    state_set "lambda_role_arn" "$LAMBDA_ROLE_ARN"
}

deploy_lambda() {
    local fn_name="$1" source_file="$2" env_vars="$3"
    local zip_path="/tmp/${fn_name}.zip"

    step "Packaging ${fn_name}"
    (cd "$LAMBDA_DIR" && zip -q "$zip_path" "$(basename "$source_file")")

    if [[ -n "$(lambda_exists "$fn_name" "$AGENTCORE_REGION")" ]]; then
        step "Updating existing Lambda ${fn_name}"
        aws lambda update-function-code \
            --function-name "$fn_name" \
            --zip-file "fileb://${zip_path}" \
            --region "$AGENTCORE_REGION" \
            --query "FunctionName" --output text > /dev/null
        # Wait for code update to complete before updating configuration
        aws lambda wait function-updated \
            --function-name "$fn_name" \
            --region "$AGENTCORE_REGION" 2>/dev/null || true
        aws lambda update-function-configuration \
            --function-name "$fn_name" \
            --environment "Variables=${env_vars}" \
            --region "$AGENTCORE_REGION" \
            --query "FunctionName" --output text > /dev/null
    else
        step "Creating Lambda ${fn_name}"
        aws lambda create-function \
            --function-name "$fn_name" \
            --runtime python3.12 \
            --role "$LAMBDA_ROLE_ARN" \
            --handler "$(basename "${source_file%.py}").handler" \
            --zip-file "fileb://${zip_path}" \
            --timeout 30 \
            --environment "Variables=${env_vars}" \
            --region "$AGENTCORE_REGION" \
            --query "FunctionName" --output text > /dev/null
    fi

    local fn_arn
    fn_arn="arn:aws:lambda:${AGENTCORE_REGION}:${ACCOUNT_ID}:function:${fn_name}"
    ok "Lambda deployed: ${fn_arn}"
    echo "$fn_arn"
}

deploy_audit_lambdas() {
    header "Audit Lambda functions"

    CLOUDTRAIL_LAMBDA_ARN=$(deploy_lambda \
        "aria-audit-cloudtrail-writer" \
        "${LAMBDA_DIR}/audit_cloudtrail_writer.py" \
        "{CLOUDTRAIL_CHANNEL_ARN=${CLOUDTRAIL_CHANNEL_ARN}}"
    )
    state_set "cloudtrail_lambda_arn" "$CLOUDTRAIL_LAMBDA_ARN"

    DYNAMODB_LAMBDA_ARN=$(deploy_lambda \
        "aria-audit-dynamodb-writer" \
        "${LAMBDA_DIR}/audit_dynamodb_writer.py" \
        "{DYNAMODB_TABLE=aria-audit-events,TTL_DAYS=90}"
    )
    state_set "dynamodb_lambda_arn" "$DYNAMODB_LAMBDA_ARN"

    # Grant EventBridge permission to invoke both Lambdas
    for fn_arn in "$CLOUDTRAIL_LAMBDA_ARN" "$DYNAMODB_LAMBDA_ARN"; do
        fn_name="${fn_arn##*:}"
        aws lambda add-permission \
            --function-name "$fn_name" \
            --statement-id "EventBridgeInvoke" \
            --action "lambda:InvokeFunction" \
            --principal "events.amazonaws.com" \
            --source-arn "arn:aws:events:${AGENTCORE_REGION}:${ACCOUNT_ID}:rule/aria-audit/*" \
            --region "$AGENTCORE_REGION" 2>/dev/null || \
        warn "Permission already set for ${fn_name}"
    done
}

create_firehose() {
    header "Kinesis Firehose → S3 WORM delivery stream"

    # Firehose IAM role
    local role_name="aria-firehose-audit-role"
    if [[ -z "$(iam_role_exists "$role_name")" ]]; then
        step "Creating Firehose IAM role"
        aws iam create-role \
            --role-name "$role_name" \
            --assume-role-policy-document '{
                "Version":"2012-10-17",
                "Statement":[{
                    "Effect":"Allow",
                    "Principal":{"Service":"firehose.amazonaws.com"},
                    "Action":"sts:AssumeRole"
                }]
            }' \
            --query "Role.RoleName" --output text > /dev/null

        aws iam put-role-policy \
            --role-name "$role_name" \
            --policy-name "S3WORMWrite" \
            --policy-document "{
                \"Version\":\"2012-10-17\",
                \"Statement\":[{
                    \"Effect\":\"Allow\",
                    \"Action\":[\"s3:PutObject\",\"s3:GetBucketLocation\",\"s3:ListBucket\"],
                    \"Resource\":[
                        \"arn:aws:s3:::${AUDIT_BUCKET}\",
                        \"arn:aws:s3:::${AUDIT_BUCKET}/*\"
                    ]
                }]
            }"
        step "Waiting 15s for Firehose IAM role propagation..."
        sleep 15
        ok "Firehose IAM role created"
    else
        warn "Firehose IAM role already exists — skipping"
    fi

    local firehose_role_arn="arn:aws:iam::${ACCOUNT_ID}:role/${role_name}"

    step "Creating Firehose delivery stream"
    local existing
    existing=$(aws firehose list-delivery-streams --region "$AGENTCORE_REGION" \
        --query "DeliveryStreamNames[?@=='aria-audit-firehose']" \
        --output text 2>/dev/null || true)

    if [[ -n "$existing" ]]; then
        warn "Firehose stream already exists — skipping"
    else
        local stream_arn
        stream_arn=$(aws firehose create-delivery-stream \
            --delivery-stream-name aria-audit-firehose \
            --delivery-stream-type DirectPut \
            --extended-s3-destination-configuration \
                "RoleARN=${firehose_role_arn},BucketARN=arn:aws:s3:::${AUDIT_BUCKET},Prefix=audit-events/,ErrorOutputPrefix=error/,CompressionFormat=GZIP,BufferingHints={SizeInMBs=5,IntervalInSeconds=300}" \
            --region "$AGENTCORE_REGION" \
            --query "DeliveryStreamARN" --output text)
        ok "Firehose stream created: ${stream_arn}"
    fi

    FIREHOSE_ARN="arn:aws:firehose:${AGENTCORE_REGION}:${ACCOUNT_ID}:deliverystream/aria-audit-firehose"
    state_set "firehose_arn" "$FIREHOSE_ARN"
    state_set "firehose_role_arn" "$firehose_role_arn"
}

create_eventbridge_rules() {
    header "EventBridge rules (fan-out)"

    local pattern='{"source":["com.meridianbank.aria"],"detail-type":["BankingAuditEvent"]}'
    local bus="aria-audit"

    # Rule → CloudTrail Lambda
    step "Rule: audit bus → CloudTrail Lake Lambda"
    aws events put-rule \
        --name "aria-audit-to-cloudtrail" \
        --event-bus-name "$bus" \
        --event-pattern "$pattern" \
        --state ENABLED \
        --region "$AGENTCORE_REGION" \
        --query "RuleArn" --output text > /dev/null
    aws events put-targets \
        --rule "aria-audit-to-cloudtrail" \
        --event-bus-name "$bus" \
        --targets "[{\"Id\":\"cloudtrail-writer\",\"Arn\":\"${CLOUDTRAIL_LAMBDA_ARN}\"}]" \
        --region "$AGENTCORE_REGION" > /dev/null
    ok "Rule → CloudTrail Lambda"

    # Rule → DynamoDB Lambda
    step "Rule: audit bus → DynamoDB Lambda"
    aws events put-rule \
        --name "aria-audit-to-dynamodb" \
        --event-bus-name "$bus" \
        --event-pattern "$pattern" \
        --state ENABLED \
        --region "$AGENTCORE_REGION" \
        --query "RuleArn" --output text > /dev/null
    aws events put-targets \
        --rule "aria-audit-to-dynamodb" \
        --event-bus-name "$bus" \
        --targets "[{\"Id\":\"dynamodb-writer\",\"Arn\":\"${DYNAMODB_LAMBDA_ARN}\"}]" \
        --region "$AGENTCORE_REGION" > /dev/null
    ok "Rule → DynamoDB Lambda"

    # Rule → Firehose (direct target, no Lambda needed)
    step "Rule: audit bus → Firehose (S3 WORM)"
    local firehose_role_arn
    firehose_role_arn=$(state_get "firehose_role_arn")
    aws events put-rule \
        --name "aria-audit-to-firehose" \
        --event-bus-name "$bus" \
        --event-pattern "$pattern" \
        --state ENABLED \
        --region "$AGENTCORE_REGION" \
        --query "RuleArn" --output text > /dev/null
    aws events put-targets \
        --rule "aria-audit-to-firehose" \
        --event-bus-name "$bus" \
        --targets "[{\"Id\":\"firehose-writer\",\"Arn\":\"${FIREHOSE_ARN}\",\"RoleArn\":\"${firehose_role_arn}\"}]" \
        --region "$AGENTCORE_REGION" > /dev/null
    ok "Rule → Firehose"
}

patch_agentcore_yaml() {
    header "Patching .bedrock_agentcore.yaml"

    # Always regenerate from state — this self-heals if the SDK deleted the file
    local mem_id; mem_id=$(state_get "memory_id" "" 2>/dev/null || echo "")
    local exec_role; exec_role=$(state_get "execution_role_arn" "" 2>/dev/null || echo "null")
    local ecr_repo; ecr_repo=$(state_get "ecr_repository" "" 2>/dev/null || echo "null")
    local cb_project; cb_project=$(state_get "codebuild_project_name" "" 2>/dev/null || echo "null")
    local cb_role; cb_role=$(state_get "codebuild_execution_role" "" 2>/dev/null || echo "null")
    local cb_bucket; cb_bucket=$(state_get "codebuild_source_bucket" "" 2>/dev/null || echo "null")

    python3 - "$YAML_FILE" "$AGENT_NAME" "$AGENTCORE_REGION" "$ACCOUNT_ID" \
              "$exec_role" "$ecr_repo" "$cb_project" "$cb_role" "$cb_bucket" "$mem_id" <<'PYEOF'
import sys, yaml

(yaml_file, agent_name, region, account,
 exec_role, ecr_repo, cb_project, cb_role, cb_bucket, mem_id) = sys.argv[1:11]

def _or_none(v): return None if v in ("", "null") else v

# If the file exists and was written by the SDK (has bedrock_agentcore.agent_id set), preserve it
# but update mutable fields. Otherwise regenerate from scratch.
existing = {}
try:
    with open(yaml_file) as f:
        existing = yaml.safe_load(f) or {}
except Exception:
    pass

sdk_agent = (existing.get('agents') or {}).get(agent_name, {})
sdk_aws   = sdk_agent.get('aws', {})
sdk_cb    = sdk_agent.get('codebuild', {})
sdk_bac   = sdk_agent.get('bedrock_agentcore', {})
sdk_mem   = sdk_agent.get('memory', {})

import subprocess

def iam_role_exists(arn):
    """Return True only if the IAM role actually exists in AWS right now."""
    if not arn:
        return False
    role_name = arn.split('/')[-1]
    r = subprocess.run(
        ['aws', 'iam', 'get-role', '--role-name', role_name, '--query', 'Role.Arn', '--output', 'text'],
        capture_output=True, text=True
    )
    return r.returncode == 0

def ecr_repo_exists(uri):
    """Return True only if the ECR repository actually exists."""
    if not uri:
        return False
    repo_name = uri.split('/')[-1]
    region_from_uri = uri.split('.')[3] if '.' in uri else region
    r = subprocess.run(
        ['aws', 'ecr', 'describe-repositories', '--repository-names', repo_name,
         '--region', region_from_uri, '--query', 'repositories[0].repositoryName', '--output', 'text'],
        capture_output=True, text=True
    )
    return r.returncode == 0

# Validate each stored ARN — if the resource was deleted, treat as None so SDK auto-creates
candidate_exec_role  = sdk_aws.get('execution_role')  or _or_none(exec_role)
candidate_ecr        = sdk_aws.get('ecr_repository')  or _or_none(ecr_repo)
candidate_cb_role    = sdk_cb.get('execution_role')   or _or_none(cb_role)
candidate_cb_project = sdk_cb.get('project_name')     or _or_none(cb_project)
candidate_cb_bucket  = sdk_cb.get('source_bucket')    or _or_none(cb_bucket)

resolved_exec_role   = candidate_exec_role  if iam_role_exists(candidate_exec_role)  else None
resolved_cb_role     = candidate_cb_role    if iam_role_exists(candidate_cb_role)     else None
resolved_ecr         = candidate_ecr        if ecr_repo_exists(candidate_ecr)         else None
# CodeBuild project and bucket are only valid if the CB role also exists
resolved_cb_project  = candidate_cb_project if resolved_cb_role else None
resolved_cb_bucket   = candidate_cb_bucket  if resolved_cb_role else None
resolved_account     = sdk_aws.get('account') or _or_none(account)
resolved_mem_id      = sdk_mem.get('memory_id')        or _or_none(mem_id)
resolved_mem_created = sdk_mem.get('was_created_by_toolkit', bool(_or_none(mem_id)))

data = {
    'default_agent': agent_name,
    'agents': {
        agent_name: {
            'name': agent_name,
            'language': 'python',
            'node_version': None,
            'entrypoint': 'aria/agentcore_app.py',
            'deployment_type': 'container',
            'runtime_type': None,
            'platform': 'linux/amd64',
            'container_runtime': None,
            'source_path': None,
            'aws': {
                'execution_role': resolved_exec_role,
                'execution_role_auto_create': resolved_exec_role is None,
                'account': resolved_account,
                'region': region,
                'ecr_repository': resolved_ecr,
                'ecr_auto_create': resolved_ecr is None,
                's3_path': None,
                's3_auto_create': False,
                'network_configuration': {'network_mode': 'PUBLIC', 'network_mode_config': None},
                'protocol_configuration': {'server_protocol': 'HTTP'},
                'observability': {'enabled': True},
                'lifecycle_configuration': {'idle_runtime_session_timeout': 1800, 'max_lifetime': 28800},
            },
            'bedrock_agentcore': {
                'agent_id':         sdk_bac.get('agent_id'),
                'agent_arn':        sdk_bac.get('agent_arn'),
                'agent_session_id': sdk_bac.get('agent_session_id'),
            },
            'codebuild': {
                'project_name':   resolved_cb_project,
                'execution_role': resolved_cb_role,
                'source_bucket':  resolved_cb_bucket,
            },
            'memory': {
                'mode':                       'STM_AND_LTM' if resolved_mem_id else sdk_mem.get('mode', 'STM_ONLY'),
                'memory_id':                  resolved_mem_id,
                'memory_arn':                 sdk_mem.get('memory_arn'),
                'memory_name':                agent_name,
                'event_expiry_days':          30,
                'first_invoke_memory_check_done': False,
                'was_created_by_toolkit':     resolved_mem_created,
            },
            'identity':      sdk_agent.get('identity',      {'credential_providers': [], 'workload': None}),
            'aws_jwt':        sdk_agent.get('aws_jwt',       {'enabled': False, 'audiences': [], 'signing_algorithm': 'ES384', 'issuer_url': None, 'duration_seconds': 300}),
            'authorizer_configuration':      None,
            'request_header_configuration':  None,
            'oauth_configuration':           None,
            'api_key_env_var_name':          None,
            'api_key_credential_provider_name': None,
            'is_generated_by_agentcore_create': False,
        }
    }
}

with open(yaml_file, 'w') as f:
    yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

print(f'  region           = {region}')
print(f'  account          = {resolved_account}')
print(f'  execution_role   = {resolved_exec_role or "(auto-create)"}')
print(f'  ecr_repository   = {resolved_ecr or "(auto-create)"}')
print(f'  memory_id        = {resolved_mem_id or "(none)"}')
PYEOF

    ok ".bedrock_agentcore.yaml regenerated"
}

create_agentcore_memory() {
    header "AgentCore Memory Resource"

    # Check if memory_id already stored from a previous run
    local existing_id
    existing_id=$(state_get "memory_id" "" 2>/dev/null || echo "")
    if [[ -n "$existing_id" ]]; then
        step "Reusing existing memory: $existing_id"
        _patch_yaml_memory_id "$existing_id"
        ok "Memory ready: $existing_id"
        return
    fi

    # Memory name must match [a-zA-Z][a-zA-Z0-9_]{0,47} — no hyphens
    local mem_name="aria_bank_mem"
    step "Creating AgentCore memory resource (name: ${mem_name})"
    echo -e "  ${YELLOW}LTM memory provisioning takes 1–3 minutes. Please wait...${NC}" >&2

    local mem_id_file="/tmp/aria-mem-id-$$.txt"
    local mem_log="/tmp/aria-mem-log-$$.txt"
    local mem_py="/tmp/aria-mem-$$.py"

    # Write the Python script to a temp file so it can be run cleanly
    # (avoids heredoc stdin conflicts inside $() or background subshells)
    cat > "$mem_py" << 'PYEOF'
import sys, os
name, region, out_file = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    from bedrock_agentcore_starter_toolkit.operations.memory.manager import MemoryManager
    from rich.console import Console
    console = Console(stderr=True)  # force Rich output to stderr; stdout stays clean
    mgr = MemoryManager(region_name=region, console=console)
    try:
        memories = mgr.list_memories()
        for m in memories:
            if str(getattr(m, 'name', '')).startswith(name) or str(getattr(m, 'id', '')).startswith(name):
                with open(out_file, 'w') as f: f.write(m.id)
                sys.exit(0)
    except Exception:
        pass
    strategies = [
        {'semanticMemoryStrategy': {'name': 'CustomerFacts', 'description': 'Key customer facts'}},
        {'userPreferenceMemoryStrategy': {'name': 'Preferences', 'description': 'Customer preferences'}},
    ]
    memory = mgr.create_memory_and_wait(
        name=name,
        description='ARIA Banking Agent long-term memory',
        strategies=strategies,
        event_expiry_days=90,
        enable_observability=False,  # X-Ray requires CloudWatch Logs trace destination pre-configured
    )
    with open(out_file, 'w') as f: f.write(memory.id)
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
PYEOF

    # Run creation in background; all output goes to log, ID written to file
    (
        source "$PROJECT_ROOT/venv/bin/activate" 2>/dev/null || true
        python3 "$mem_py" "$mem_name" "$AGENTCORE_REGION" "$mem_id_file"
    ) > "$mem_log" 2>&1 &
    local bg_pid=$!

    # Spinner so the user knows the script is alive
    local spin=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
    local i=0 elapsed=0
    while kill -0 "$bg_pid" 2>/dev/null; do
        printf "\r  %s  Memory provisioning... (%ds elapsed)" "${spin[$i]}" "$elapsed" >&2
        i=$(( (i+1) % 10 ))
        sleep 2
        elapsed=$(( elapsed + 2 ))
    done
    printf "\r  %-60s\n" "" >&2  # clear spinner line
    wait "$bg_pid" || true

    local mem_id=""
    [[ -f "$mem_id_file" ]] && mem_id=$(cat "$mem_id_file" | tr -d '[:space:]')
    rm -f "$mem_id_file" "$mem_log" "$mem_py"

    if [[ -z "$mem_id" ]]; then
        warn "Memory creation failed — agent will run with STM only (in-session context only)"
        _patch_yaml_memory_mode "STM_ONLY"
        return
    fi

    ok "Memory ready: ${mem_id}"
    state_set "memory_id" "$mem_id"
    _patch_yaml_memory_id "$mem_id"
}

_patch_yaml_memory_id() {
    local mem_id="$1"
    python3 -c "
import sys, yaml
yaml_file, mem_id = sys.argv[1], sys.argv[2]
with open(yaml_file) as f:
    data = yaml.safe_load(f)
for agent in data.get('agents', {}).values():
    if 'memory' in agent:
        agent['memory']['memory_id'] = mem_id
        agent['memory']['was_created_by_toolkit'] = True
with open(yaml_file, 'w') as f:
    yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
print(f'  patched memory_id = {mem_id}')
" "$YAML_FILE" "$mem_id"
}

_patch_yaml_memory_mode() {
    local mode="$1"
    python3 -c "
import sys, yaml
yaml_file, mode = sys.argv[1], sys.argv[2]
with open(yaml_file) as f:
    data = yaml.safe_load(f)
for agent in data.get('agents', {}).values():
    if 'memory' in agent:
        agent['memory']['mode'] = mode
with open(yaml_file, 'w') as f:
    yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
print(f'  patched memory.mode = {mode}')
" "$YAML_FILE" "$mode"
}

launch_agentcore() {
    header "Deploying ARIA to AgentCore Runtime"
    echo -e "  ${YELLOW}This step uses AWS CodeBuild to build an ARM64 container.${NC}"
    echo -e "  ${YELLOW}It typically takes 10–15 minutes. Do not interrupt.${NC}\n"

    cd "$PROJECT_ROOT"

    local launch_log="/tmp/agentcore-launch-$$.log"

    # Build --env flags — env vars are injected into the AgentCore runtime container
    local env_args=(
        --env "NOVA_SONIC_REGION=${NOVA_SONIC_REGION}"
        --env "TRANSCRIPT_S3_BUCKET=${TRANSCRIPT_BUCKET}"
        --env "TRANSCRIPT_S3_PREFIX=transcripts"
        --env "TRANSCRIPT_STORE=s3"
        --env "AUDIT_STORE=eventbridge"
        --env "AUDIT_EVENTBRIDGE_BUS=aria-audit"
        --env "AUDIT_REGION=${AGENTCORE_REGION}"
        --env "BANK_API_BASE_URL=${BANK_API_BASE_URL}"
        --env "BANK_API_KEY=${BANK_API_KEY}"
        --env "LOG_LEVEL=INFO"
    )

    local attempt=0 max_attempts=3 launch_exit=0
    while (( attempt < max_attempts )); do
        attempt=$(( attempt + 1 ))
        launch_exit=0
        rm -f "$launch_log"

        if [[ "$DEPLOY_MODE" == "2" ]]; then
            step "Running: agentcore launch --agent $AGENT_NAME --local-build (attempt ${attempt}/${max_attempts})"
            agentcore launch --agent "$AGENT_NAME" --local-build "${env_args[@]}" 2>&1 | tee "$launch_log" || launch_exit=1
        else
            step "Running: agentcore launch --agent $AGENT_NAME (attempt ${attempt}/${max_attempts})"
            agentcore launch --agent "$AGENT_NAME" "${env_args[@]}" 2>&1 | tee "$launch_log" || launch_exit=1
        fi

        # Detect IAM propagation error — retry after a wait
        if grep -q "not authorized to perform: sts:AssumeRole\|CodeBuild is not authorized\|IAM\|trust policy" "$launch_log" 2>/dev/null \
           && (( attempt < max_attempts )); then
            warn "IAM propagation delay detected — waiting 30s before retry (attempt ${attempt}/${max_attempts})"
            sleep 30
            # Regenerate YAML in case SDK deleted it during the failed attempt
            patch_agentcore_yaml
            continue
        fi
        break
    done

    # Extract Agent Runtime ARN from output
    local runtime_arn
    runtime_arn=$(grep -oE 'arn:aws:bedrock-agentcore:[a-z0-9-]+:[0-9]+:agent-runtime/[a-zA-Z0-9_-]+' \
        "$launch_log" | tail -1 || true)

    if [[ -z "$runtime_arn" ]]; then
        warn "Could not auto-detect Runtime ARN from output. Check the log above."
        ask runtime_arn "Paste the Agent Runtime ARN from the output above" ""
    fi

    state_set "runtime_arn" "$runtime_arn"
    ok "Agent deployed: ${runtime_arn}"
    rm -f "$launch_log"
}

deploy_cognito_identity_pool() {
    header "Cognito Identity Pool (React client auth)"

    local COGNITO_POOL_ID POOL_NAME RUNTIME_ARN UNAUTH_TRUST UNAUTH_ROLE_NAME UNAUTH_ROLE_ARN
    COGNITO_POOL_ID=$(state_get "cognito_identity_pool_id")

    if [[ -n "$COGNITO_POOL_ID" ]]; then
        if aws cognito-identity describe-identity-pool \
                --identity-pool-id "$COGNITO_POOL_ID" \
                --region "$AGENTCORE_REGION" --no-cli-pager &>/dev/null; then
            ok "Cognito Identity Pool already exists — $COGNITO_POOL_ID"
            return
        else
            warn "Cognito pool $COGNITO_POOL_ID no longer exists — recreating"
            COGNITO_POOL_ID=""
        fi
    fi

    step "Creating Cognito Identity Pool"
    POOL_NAME="aria_banking_pool_${DEPLOY_ID}"
    COGNITO_POOL_ID=$(aws cognito-identity create-identity-pool \
        --identity-pool-name "$POOL_NAME" \
        --allow-unauthenticated-identities \
        --region "$AGENTCORE_REGION" \
        --no-cli-pager \
        --query 'IdentityPoolId' --output text)

    state_set "cognito_identity_pool_id" "$COGNITO_POOL_ID"
    ok "Cognito Identity Pool created: $COGNITO_POOL_ID"

    step "Creating Cognito unauthenticated IAM role"
    RUNTIME_ARN=$(state_get "runtime_arn")

    UNAUTH_TRUST=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Federated": "cognito-identity.amazonaws.com"},
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {"cognito-identity.amazonaws.com:aud": "${COGNITO_POOL_ID}"},
      "ForAnyValue:StringLike": {"cognito-identity.amazonaws.com:amr": "unauthenticated"}
    }
  }]
}
EOF
)

    UNAUTH_ROLE_NAME="aria-cognito-unauth-role-${DEPLOY_ID}"
    UNAUTH_ROLE_ARN=$(aws iam create-role \
        --role-name "$UNAUTH_ROLE_NAME" \
        --assume-role-policy-document "$UNAUTH_TRUST" \
        --no-cli-pager \
        --query 'Role.Arn' --output text 2>/dev/null || \
        aws iam get-role --role-name "$UNAUTH_ROLE_NAME" --no-cli-pager --query 'Role.Arn' --output text)

    aws iam put-role-policy \
        --role-name "$UNAUTH_ROLE_NAME" \
        --policy-name "aria-cognito-unauth-policy" \
        --policy-document "{
          \"Version\": \"2012-10-17\",
          \"Statement\": [
            {
              \"Effect\": \"Allow\",
              \"Action\": [\"bedrock-agentcore:InvokeAgentRuntime\", \"bedrock-agentcore:InvokeAgentRuntimeForUser\"],
              \"Resource\": \"${RUNTIME_ARN}\"
            }
          ]
        }" --no-cli-pager

    aws cognito-identity set-identity-pool-roles \
        --identity-pool-id "$COGNITO_POOL_ID" \
        --roles "unauthenticated=${UNAUTH_ROLE_ARN}" \
        --region "$AGENTCORE_REGION" \
        --no-cli-pager

    state_set "cognito_unauth_role_arn" "$UNAUTH_ROLE_ARN"
    ok "Cognito unauthenticated role configured"
}

deploy_ecs_fargate_voice() {
    header "ECS Fargate Voice Service (WebSocket /ws)"

    local ECR_IMAGE ECR_IMAGE_URI LATEST_TAG
    local DEFAULT_VPC SUBNETS SUBNET_LIST
    local ALB_SG_NAME ECS_SG_NAME ALB_SG_ID ECS_SG_ID
    local LOG_GROUP CLUSTER_NAME EXISTING_CLUSTER
    local TASK_EXEC_ROLE_NAME TASK_EXEC_ROLE_ARN
    local ECS_TASK_ROLE_NAME ECS_TASK_ROLE_ARN
    local TASK_DEF_FAMILY TASK_DEF_ARN
    local ALB_NAME ALB_ARN ALB_DNS
    local TG_NAME TG_ARN LISTENER_ARN
    local SERVICE_NAME EXISTING_SERVICE SUBNET_LIST_JSON
    local MEMORY_ID EB_BUS_ARN EB_BUS_NAME
    local wait_start dots elapsed running

    ECR_IMAGE="${ACCOUNT_ID}.dkr.ecr.${AGENTCORE_REGION}.amazonaws.com/bedrock-agentcore-aria-banking-agent"

    # Get latest image tag from ECR
    LATEST_TAG=$(aws ecr describe-images \
        --repository-name bedrock-agentcore-aria-banking-agent \
        --region "$AGENTCORE_REGION" \
        --query 'sort_by(imageDetails,&imagePushedAt)[-1].imageTags[0]' \
        --output text --no-cli-pager 2>/dev/null || echo "latest")
    ECR_IMAGE_URI="${ECR_IMAGE}:${LATEST_TAG}"

    # Get default VPC and subnets
    step "Resolving default VPC and subnets"
    DEFAULT_VPC=$(aws ec2 describe-vpcs \
        --filters "Name=is-default,Values=true" \
        --query 'Vpcs[0].VpcId' --output text \
        --region "$AGENTCORE_REGION" --no-cli-pager)

    SUBNETS=$(aws ec2 describe-subnets \
        --filters "Name=vpc-id,Values=${DEFAULT_VPC}" \
        --query 'Subnets[*].SubnetId' --output text \
        --region "$AGENTCORE_REGION" --no-cli-pager | tr '\t' ',')

    ok "VPC: $DEFAULT_VPC | Subnets: $SUBNETS"

    # --- Security Groups ---
    ALB_SG_NAME="aria-alb-sg-${DEPLOY_ID}"
    ECS_SG_NAME="aria-ecs-sg-${DEPLOY_ID}"

    ALB_SG_ID=$(aws ec2 describe-security-groups \
        --filters "Name=group-name,Values=${ALB_SG_NAME}" \
        --region "$AGENTCORE_REGION" --no-cli-pager \
        --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null | grep -v "None" || echo "")

    if [[ -z "$ALB_SG_ID" ]]; then
        step "Creating ALB security group"
        ALB_SG_ID=$(aws ec2 create-security-group \
            --group-name "$ALB_SG_NAME" \
            --description "ARIA ALB security group" \
            --vpc-id "$DEFAULT_VPC" \
            --region "$AGENTCORE_REGION" --no-cli-pager \
            --query 'GroupId' --output text)

        aws ec2 authorize-security-group-ingress \
            --group-id "$ALB_SG_ID" \
            --protocol tcp --port 80 --cidr "0.0.0.0/0" \
            --region "$AGENTCORE_REGION" --no-cli-pager &>/dev/null || true
        ok "ALB security group: $ALB_SG_ID"
    else
        ok "ALB security group already exists: $ALB_SG_ID"
    fi

    ECS_SG_ID=$(aws ec2 describe-security-groups \
        --filters "Name=group-name,Values=${ECS_SG_NAME}" \
        --region "$AGENTCORE_REGION" --no-cli-pager \
        --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null | grep -v "None" || echo "")

    if [[ -z "$ECS_SG_ID" ]]; then
        step "Creating ECS security group"
        ECS_SG_ID=$(aws ec2 create-security-group \
            --group-name "$ECS_SG_NAME" \
            --description "ARIA ECS tasks security group" \
            --vpc-id "$DEFAULT_VPC" \
            --region "$AGENTCORE_REGION" --no-cli-pager \
            --query 'GroupId' --output text)

        aws ec2 authorize-security-group-ingress \
            --group-id "$ECS_SG_ID" \
            --protocol tcp --port 8080 \
            --source-group "$ALB_SG_ID" \
            --region "$AGENTCORE_REGION" --no-cli-pager &>/dev/null || true

        aws ec2 authorize-security-group-egress \
            --group-id "$ECS_SG_ID" \
            --ip-permissions 'IpProtocol=-1,IpRanges=[{CidrIp=0.0.0.0/0}]' \
            --region "$AGENTCORE_REGION" --no-cli-pager &>/dev/null || true
        ok "ECS security group: $ECS_SG_ID"
    else
        ok "ECS security group already exists: $ECS_SG_ID"
    fi

    state_set "alb_sg_id" "$ALB_SG_ID"
    state_set "ecs_sg_id" "$ECS_SG_ID"

    # --- CloudWatch Logs ---
    LOG_GROUP="/ecs/aria-banking-${DEPLOY_ID}"
    aws logs create-log-group --log-group-name "$LOG_GROUP" \
        --region "$AGENTCORE_REGION" --no-cli-pager &>/dev/null || true

    # --- ECS Cluster ---
    CLUSTER_NAME="aria-banking-cluster-${DEPLOY_ID}"
    EXISTING_CLUSTER=$(aws ecs describe-clusters \
        --clusters "$CLUSTER_NAME" \
        --region "$AGENTCORE_REGION" --no-cli-pager \
        --query 'clusters[?status==`ACTIVE`].clusterName' \
        --output text 2>/dev/null || true)

    if [[ -z "$EXISTING_CLUSTER" ]]; then
        step "Creating ECS cluster: $CLUSTER_NAME"
        aws ecs create-cluster \
            --cluster-name "$CLUSTER_NAME" \
            --region "$AGENTCORE_REGION" --no-cli-pager &>/dev/null
        ok "ECS cluster created"
    else
        ok "ECS cluster already exists: $CLUSTER_NAME"
    fi

    # --- ECS Task Execution Role ---
    TASK_EXEC_ROLE_NAME="aria-ecs-task-exec-role-${DEPLOY_ID}"
    TASK_EXEC_ROLE_ARN=$(aws iam get-role \
        --role-name "$TASK_EXEC_ROLE_NAME" \
        --no-cli-pager \
        --query 'Role.Arn' --output text 2>/dev/null || echo "")

    if [[ -z "$TASK_EXEC_ROLE_ARN" || "$TASK_EXEC_ROLE_ARN" == "None" ]]; then
        step "Creating ECS task execution role"
        TASK_EXEC_ROLE_ARN=$(aws iam create-role \
            --role-name "$TASK_EXEC_ROLE_NAME" \
            --assume-role-policy-document '{
              "Version":"2012-10-17",
              "Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]
            }' \
            --no-cli-pager \
            --query 'Role.Arn' --output text)

        aws iam attach-role-policy \
            --role-name "$TASK_EXEC_ROLE_NAME" \
            --policy-arn "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy" \
            --no-cli-pager

        aws iam attach-role-policy \
            --role-name "$TASK_EXEC_ROLE_NAME" \
            --policy-arn "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly" \
            --no-cli-pager
        ok "ECS task execution role: $TASK_EXEC_ROLE_ARN"
        step "Waiting 10s for IAM propagation..."
        sleep 10
    else
        ok "ECS task execution role already exists"
    fi

    # --- ECS Task Role (app permissions) ---
    ECS_TASK_ROLE_NAME="aria-ecs-task-role-${DEPLOY_ID}"
    ECS_TASK_ROLE_ARN=$(aws iam get-role \
        --role-name "$ECS_TASK_ROLE_NAME" \
        --no-cli-pager \
        --query 'Role.Arn' --output text 2>/dev/null || echo "")

    if [[ -z "$ECS_TASK_ROLE_ARN" || "$ECS_TASK_ROLE_ARN" == "None" ]]; then
        step "Creating ECS task role"
        ECS_TASK_ROLE_ARN=$(aws iam create-role \
            --role-name "$ECS_TASK_ROLE_NAME" \
            --assume-role-policy-document '{
              "Version":"2012-10-17",
              "Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]
            }' \
            --no-cli-pager \
            --query 'Role.Arn' --output text)

        MEMORY_ID=$(state_get "memory_id")
        EB_BUS_ARN=$(state_get "eventbridge_bus_arn")

        aws iam put-role-policy \
            --role-name "$ECS_TASK_ROLE_NAME" \
            --policy-name "aria-ecs-task-policy" \
            --policy-document "{
              \"Version\": \"2012-10-17\",
              \"Statement\": [
                {
                  \"Effect\": \"Allow\",
                  \"Action\": [
                    \"bedrock:InvokeModel\",
                    \"bedrock:InvokeModelWithResponseStream\",
                    \"bedrock:InvokeModelWithBidirectionalStream\"
                  ],
                  \"Resource\": \"*\"
                },
                {
                  \"Effect\": \"Allow\",
                  \"Action\": [\"bedrock-agentcore:*\"],
                  \"Resource\": \"*\"
                },
                {
                  \"Effect\": \"Allow\",
                  \"Action\": [\"s3:PutObject\", \"s3:GetObject\"],
                  \"Resource\": [
                    \"arn:aws:s3:::${TRANSCRIPT_BUCKET}/*\",
                    \"arn:aws:s3:::${AUDIT_BUCKET}/*\"
                  ]
                },
                {
                  \"Effect\": \"Allow\",
                  \"Action\": \"events:PutEvents\",
                  \"Resource\": \"${EB_BUS_ARN}\"
                },
                {
                  \"Effect\": \"Allow\",
                  \"Action\": [\"logs:CreateLogStream\", \"logs:PutLogEvents\"],
                  \"Resource\": \"arn:aws:logs:${AGENTCORE_REGION}:${ACCOUNT_ID}:log-group:/ecs/aria-banking-${DEPLOY_ID}:*\"
                }
              ]
            }" --no-cli-pager

        state_set "ecs_task_role_arn" "$ECS_TASK_ROLE_ARN"
        ok "ECS task role: $ECS_TASK_ROLE_ARN"
        step "Waiting 10s for IAM propagation..."
        sleep 10
    else
        ok "ECS task role already exists"
    fi

    # --- ECS Task Definition ---
    TASK_DEF_FAMILY="aria-banking-task-${DEPLOY_ID}"
    MEMORY_ID=$(state_get "memory_id")
    EB_BUS_ARN=$(state_get "eventbridge_bus_arn")
    EB_BUS_NAME="${EB_BUS_ARN##*/}"
    EB_BUS_NAME="${EB_BUS_NAME:-aria-audit}"

    step "Registering ECS task definition: $TASK_DEF_FAMILY"
    TASK_DEF_ARN=$(aws ecs register-task-definition \
        --family "$TASK_DEF_FAMILY" \
        --network-mode awsvpc \
        --requires-compatibilities FARGATE \
        --cpu "1024" \
        --memory "2048" \
        --execution-role-arn "$TASK_EXEC_ROLE_ARN" \
        --task-role-arn "$ECS_TASK_ROLE_ARN" \
        --container-definitions "[
          {
            \"name\": \"aria-banking\",
            \"image\": \"${ECR_IMAGE_URI}\",
            \"portMappings\": [{\"containerPort\": 8080, \"protocol\": \"tcp\"}],
            \"essential\": true,
            \"environment\": [
              {\"name\": \"AWS_DEFAULT_REGION\", \"value\": \"${AGENTCORE_REGION}\"},
              {\"name\": \"NOVA_SONIC_REGION\", \"value\": \"${NOVA_SONIC_REGION}\"},
              {\"name\": \"BEDROCK_AGENTCORE_MEMORY_ID\", \"value\": \"${MEMORY_ID}\"},
              {\"name\": \"BEDROCK_AGENTCORE_MEMORY_NAME\", \"value\": \"aria_banking_agent\"},
              {\"name\": \"TRANSCRIPT_S3_BUCKET\", \"value\": \"${TRANSCRIPT_BUCKET}\"},
              {\"name\": \"TRANSCRIPT_S3_PREFIX\", \"value\": \"transcripts\"},
              {\"name\": \"TRANSCRIPT_STORE\", \"value\": \"s3\"},
              {\"name\": \"AUDIT_EVENTBRIDGE_BUS\", \"value\": \"${EB_BUS_NAME}\"},
              {\"name\": \"AUDIT_REGION\", \"value\": \"${AGENTCORE_REGION}\"},
              {\"name\": \"AUDIT_STORE\", \"value\": \"eventbridge\"},
              {\"name\": \"LOG_LEVEL\", \"value\": \"INFO\"}
            ],
            \"logConfiguration\": {
              \"logDriver\": \"awslogs\",
              \"options\": {
                \"awslogs-group\": \"/ecs/aria-banking-${DEPLOY_ID}\",
                \"awslogs-region\": \"${AGENTCORE_REGION}\",
                \"awslogs-stream-prefix\": \"aria\"
              }
            },
            \"healthCheck\": {
              \"command\": [\"CMD-SHELL\", \"curl -f http://localhost:8080/ping || exit 1\"],
              \"interval\": 30,
              \"timeout\": 5,
              \"retries\": 3,
              \"startPeriod\": 60
            }
          }
        ]" \
        --region "$AGENTCORE_REGION" --no-cli-pager \
        --query 'taskDefinition.taskDefinitionArn' --output text)

    state_set "ecs_task_def_arn" "$TASK_DEF_ARN"
    ok "Task definition registered"

    # --- ALB ---
    ALB_NAME="aria-banking-alb-${DEPLOY_ID}"
    ALB_ARN=$(aws elbv2 describe-load-balancers \
        --names "$ALB_NAME" \
        --region "$AGENTCORE_REGION" --no-cli-pager \
        --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null | grep -v "None" || echo "")

    if [[ -z "$ALB_ARN" ]]; then
        step "Creating Application Load Balancer: $ALB_NAME"
        SUBNET_LIST=$(echo "$SUBNETS" | tr ',' ' ')
        ALB_ARN=$(aws elbv2 create-load-balancer \
            --name "$ALB_NAME" \
            --subnets $SUBNET_LIST \
            --security-groups "$ALB_SG_ID" \
            --scheme internet-facing \
            --type application \
            --region "$AGENTCORE_REGION" --no-cli-pager \
            --query 'LoadBalancers[0].LoadBalancerArn' --output text)
        ok "ALB created: $ALB_ARN"
    else
        ok "ALB already exists: $ALB_ARN"
    fi

    ALB_DNS=$(aws elbv2 describe-load-balancers \
        --load-balancer-arns "$ALB_ARN" \
        --region "$AGENTCORE_REGION" --no-cli-pager \
        --query 'LoadBalancers[0].DNSName' --output text)

    state_set "alb_arn" "$ALB_ARN"
    state_set "alb_dns" "$ALB_DNS"

    # --- Target Group ---
    TG_NAME="aria-banking-tg-${DEPLOY_ID}"
    TG_ARN=$(aws elbv2 describe-target-groups \
        --names "$TG_NAME" \
        --region "$AGENTCORE_REGION" --no-cli-pager \
        --query 'TargetGroups[0].TargetGroupArn' --output text 2>/dev/null | grep -v "None" || echo "")

    if [[ -z "$TG_ARN" ]]; then
        step "Creating target group"
        TG_ARN=$(aws elbv2 create-target-group \
            --name "$TG_NAME" \
            --protocol HTTP \
            --port 8080 \
            --vpc-id "$DEFAULT_VPC" \
            --target-type ip \
            --health-check-path "/ping" \
            --health-check-interval-seconds 30 \
            --health-check-timeout-seconds 5 \
            --healthy-threshold-count 2 \
            --unhealthy-threshold-count 3 \
            --region "$AGENTCORE_REGION" --no-cli-pager \
            --query 'TargetGroups[0].TargetGroupArn' --output text)
        ok "Target group: $TG_ARN"
    else
        ok "Target group already exists"
    fi

    aws elbv2 modify-target-group-attributes \
        --target-group-arn "$TG_ARN" \
        --attributes \
            "Key=stickiness.enabled,Value=true" \
            "Key=stickiness.type,Value=lb_cookie" \
            "Key=stickiness.lb_cookie.duration_seconds,Value=86400" \
        --region "$AGENTCORE_REGION" --no-cli-pager &>/dev/null || true

    state_set "alb_target_group_arn" "$TG_ARN"

    # --- ALB Listener ---
    LISTENER_ARN=$(aws elbv2 describe-listeners \
        --load-balancer-arn "$ALB_ARN" \
        --region "$AGENTCORE_REGION" --no-cli-pager \
        --query 'Listeners[?Port==`80`].ListenerArn' --output text 2>/dev/null | grep -v "None" || echo "")

    if [[ -z "$LISTENER_ARN" ]]; then
        step "Creating ALB listener (port 80)"
        aws elbv2 create-listener \
            --load-balancer-arn "$ALB_ARN" \
            --protocol HTTP --port 80 \
            --default-actions "Type=forward,TargetGroupArn=${TG_ARN}" \
            --region "$AGENTCORE_REGION" --no-cli-pager \
            --query 'Listeners[0].ListenerArn' --output text > /dev/null
        ok "Listener created"
    else
        ok "Listener already exists"
    fi

    # --- ECS Service ---
    SERVICE_NAME="aria-banking-service-${DEPLOY_ID}"
    EXISTING_SERVICE=$(aws ecs describe-services \
        --cluster "$CLUSTER_NAME" \
        --services "$SERVICE_NAME" \
        --region "$AGENTCORE_REGION" --no-cli-pager \
        --query 'services[?status==`ACTIVE`].serviceName' \
        --output text 2>/dev/null || true)

    SUBNET_LIST_JSON=$(echo "$SUBNETS" | python3 -c \
        "import sys; s=sys.stdin.read().strip().split(','); print('[\"'+'\\\"','\\\"'.join(s)+'\"]')" \
        2>/dev/null || echo "[\"${SUBNETS//,/\",\"}\"]")

    if [[ -z "$EXISTING_SERVICE" ]]; then
        step "Creating ECS Fargate service: $SERVICE_NAME"
        aws ecs create-service \
            --cluster "$CLUSTER_NAME" \
            --service-name "$SERVICE_NAME" \
            --task-definition "$TASK_DEF_ARN" \
            --desired-count 1 \
            --launch-type FARGATE \
            --network-configuration "awsvpcConfiguration={subnets=[${SUBNETS}],securityGroups=[${ECS_SG_ID}],assignPublicIp=ENABLED}" \
            --load-balancers "targetGroupArn=${TG_ARN},containerName=aria-banking,containerPort=8080" \
            --region "$AGENTCORE_REGION" --no-cli-pager &>/dev/null
        ok "ECS service created"
    else
        step "Updating existing ECS service with new task definition"
        aws ecs update-service \
            --cluster "$CLUSTER_NAME" \
            --service "$SERVICE_NAME" \
            --task-definition "$TASK_DEF_ARN" \
            --region "$AGENTCORE_REGION" --no-cli-pager &>/dev/null
        ok "ECS service updated"
    fi

    state_set "ecs_cluster_name" "$CLUSTER_NAME"
    state_set "ecs_service_name" "$SERVICE_NAME"

    # Wait for service stability with progress indicator
    step "Waiting for ECS service to become stable (this may take 3-5 minutes)..."
    wait_start=$SECONDS
    dots=0
    while true; do
        elapsed=$(( SECONDS - wait_start ))
        running=$(aws ecs describe-services \
            --cluster "$CLUSTER_NAME" \
            --services "$SERVICE_NAME" \
            --region "$AGENTCORE_REGION" --no-cli-pager \
            --query 'services[0].runningCount' --output text 2>/dev/null || echo "0")

        if [[ "$running" == "1" ]]; then
            echo "" >&2
            ok "ECS service stable — 1 task running (${elapsed}s)"
            break
        fi

        if (( elapsed > 600 )); then
            echo "" >&2
            warn "ECS service did not stabilize within 10 minutes — check ECS console"
            break
        fi

        dots=$(( (dots + 1) % 4 ))
        printf "\r  ⏳ Waiting for task to start... %ds %s" "$elapsed" "$(printf '%0.s.' $(seq 1 $((dots+1))))" >&2
        sleep 10
    done

    echo "" >&2
    echo "  ╔═══════════════════════════════════════════════════════════╗" >&2
    echo "  ║  ARIA Voice WebSocket endpoint:                           ║" >&2
    printf "  ║  ws://%-53s ║\n" "${ALB_DNS}/ws" >&2
    printf "  ║  http://%-51s ║\n" "${ALB_DNS}/invocations" >&2
    echo "  ╚═══════════════════════════════════════════════════════════╝" >&2
}

find_and_patch_execution_role() {
    header "Attaching additional IAM policies to execution role"

    step "Searching for AgentCore execution role in IAM..."
    local role_name
    role_name=$(aws iam list-roles \
        --query "Roles[?contains(RoleName,'BedrockAgentCore')].RoleName" \
        --output text | tr '\t' '\n' | head -1 || true)

    if [[ -z "$role_name" ]]; then
        warn "Auto-detect failed. The role is typically named BedrockAgentCoreExecutionRole_<id>"
        ask role_name "Enter the execution role name" ""
    fi
    [[ -z "$role_name" ]] && die "Execution role name required."

    ok "Found execution role: ${role_name}"
    state_set "execution_role_name" "$role_name"

    # Policy 1: Cross-region Bedrock (Claude + Nova Sonic)
    step "Attaching Bedrock cross-region policy"
    aws iam put-role-policy \
        --role-name "$role_name" \
        --policy-name "ARIABedrockCrossRegion" \
        --policy-document '{
            "Version":"2012-10-17",
            "Statement":[{
                "Sid":"BedrockCrossRegion",
                "Effect":"Allow",
                "Action":[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:InvokeModelWithBidirectionalStream"
                ],
                "Resource":"arn:aws:bedrock:*::foundation-model/*"
            }]
        }'
    ok "Bedrock cross-region policy attached"

    # Policy 2: S3 transcript writes
    step "Attaching S3 transcript policy"
    aws iam put-role-policy \
        --role-name "$role_name" \
        --policy-name "ARIATranscriptS3Write" \
        --policy-document "{
            \"Version\":\"2012-10-17\",
            \"Statement\":[{
                \"Sid\":\"TranscriptS3Write\",
                \"Effect\":\"Allow\",
                \"Action\":[\"s3:PutObject\",\"s3:GetObject\",\"s3:ListBucket\"],
                \"Resource\":[
                    \"arn:aws:s3:::${TRANSCRIPT_BUCKET}\",
                    \"arn:aws:s3:::${TRANSCRIPT_BUCKET}/*\"
                ]
            }]
        }"
    ok "S3 transcript policy attached"

    # Policy 3: EventBridge audit put
    step "Attaching EventBridge audit policy"
    aws iam put-role-policy \
        --role-name "$role_name" \
        --policy-name "ARIAAuditEventBridge" \
        --policy-document "{
            \"Version\":\"2012-10-17\",
            \"Statement\":[{
                \"Sid\":\"AuditEventBridge\",
                \"Effect\":\"Allow\",
                \"Action\":[\"events:PutEvents\"],
                \"Resource\":\"arn:aws:events:${AGENTCORE_REGION}:${ACCOUNT_ID}:event-bus/aria-audit\"
            }]
        }"
    ok "EventBridge policy attached"
}

print_summary() {
    header "Deployment complete"

    local runtime_arn account_id
    runtime_arn=$(state_get "runtime_arn")
    account_id=$(state_get "account_id")

    echo -e "${GREEN}${BOLD}
  ╔══════════════════════════════════════════════════════════════╗
  ║                ARIA deployed to AgentCore                    ║
  ╚══════════════════════════════════════════════════════════════╝${NC}

  ${BOLD}Agent Runtime ARN:${NC}
    ${runtime_arn}

  ${BOLD}Quick test (chat):${NC}
    agentcore invoke '{\"message\": \"Hello Aria\", \"authenticated\": true, \"customer_id\": \"CUST-001\"}'

  ${BOLD}Quick test (boto3):${NC}
    python3 scripts/test_invoke.py  (auto-generated in next step)

  ${BOLD}Resources created:${NC}
    S3 transcripts:  s3://${TRANSCRIPT_BUCKET}/transcripts/
    S3 audit WORM:   s3://${AUDIT_BUCKET}/audit-events/
    DynamoDB:        aria-audit-events (${AGENTCORE_REGION})
    EventBridge bus: aria-audit (${AGENTCORE_REGION})
    CloudTrail Lake: aria-banking-audit (7yr retention)
    Firehose:        aria-audit-firehose → S3 WORM

  ${BOLD}Logs:${NC}
    aws logs tail /aws/bedrock-agentcore/runtimes --follow

  ${BOLD}React client endpoints:${NC}
    COGNITO_POOL_ID : $(state_get 'cognito_identity_pool_id')
    ALB_DNS         : $(state_get 'alb_dns')
    Voice WS URL    : ws://$(state_get 'alb_dns')/ws

  ${BOLD}Teardown:${NC}
    ./scripts/deploy.sh teardown
"

    # Write a quick test script
    cat > "${PROJECT_ROOT}/scripts/test_invoke.py" <<PYEOF
"""Quick smoke-test for the deployed AgentCore agent."""
import boto3, json, uuid

RUNTIME_ARN = "${runtime_arn}"
REGION      = "${AGENTCORE_REGION}"

client     = boto3.client("bedrock-agentcore-runtime", region_name=REGION)
session_id = str(uuid.uuid4())

payload = json.dumps({
    "message":       "Hello Aria, can you confirm you are operational?",
    "authenticated": True,
    "customer_id":   "CUST-SMOKETEST",
}).encode()

print(f"Invoking {RUNTIME_ARN} ...")
response = client.invoke_agent_runtime(
    agentRuntimeArn=RUNTIME_ARN,
    runtimeSessionId=session_id,
    payload=payload,
    qualifier="DEFAULT",
)

for chunk in response["response"]:
    print(chunk.decode("utf-8"), end="", flush=True)
print()
PYEOF
    ok "Test script written to scripts/test_invoke.py"
}

cmd_deploy() {
    header "ARIA AgentCore Full Stack Deployment"
    state_init
    check_prerequisites
    collect_inputs
    create_s3_buckets
    create_dynamodb_table
    create_eventbridge_bus
    create_cloudtrail_lake
    create_lambda_iam_role
    deploy_audit_lambdas
    create_firehose
    create_eventbridge_rules
    patch_agentcore_yaml
    create_agentcore_memory
    launch_agentcore
    find_and_patch_execution_role
    deploy_cognito_identity_pool
    deploy_ecs_fargate_voice
    print_summary
}

# =============================================================================
#  TEARDOWN
# =============================================================================

cmd_teardown() {
    header "ARIA AgentCore Teardown"

    [[ -f "$STATE_FILE" ]] || die "No state file found at ${STATE_FILE}. Nothing to tear down."

    echo -e "${RED}${BOLD}  This will permanently delete all ARIA AWS resources.${NC}"
    echo -e "  Reading state from: ${STATE_FILE}\n"

    local account_id agentcore_region transcript_bucket audit_bucket
    account_id=$(state_get "account_id")
    agentcore_region=$(state_get "agentcore_region")
    transcript_bucket=$(state_get "transcript_bucket")
    audit_bucket=$(state_get "audit_bucket")

    echo "  Account:     ${account_id}"
    echo "  Region:      ${agentcore_region}"
    echo ""

    ask_yn "Are you sure you want to tear down everything?" "N" || {
        echo "  Teardown cancelled."
        exit 0
    }

    # ── Step 1: Stop running AgentCore session ────────────────────────────────
    header "Stopping AgentCore session"
    step "agentcore stop-session"
    agentcore stop-session 2>/dev/null && ok "Session stopped" || warn "No active session"

    # ── Step 2: Destroy AgentCore agent (Runtime, ECR, IAM role, CloudWatch) ──
    header "Destroying AgentCore agent"
    step "agentcore destroy (removes Runtime endpoint, ECR repo, execution role)"
    cd "$PROJECT_ROOT"
    agentcore destroy 2>/dev/null && ok "AgentCore agent destroyed" || warn "agentcore destroy returned non-zero — check console"

    # ── Step 3: Delete EventBridge rules ─────────────────────────────────────
    header "Deleting EventBridge rules"
    for rule in aria-audit-to-cloudtrail aria-audit-to-dynamodb aria-audit-to-firehose; do
        step "Removing targets and rule: ${rule}"
        aws events remove-targets \
            --rule "$rule" --event-bus-name aria-audit \
            --ids cloudtrail-writer dynamodb-writer firehose-writer \
            --region "$agentcore_region" 2>/dev/null || true
        aws events delete-rule \
            --name "$rule" --event-bus-name aria-audit \
            --region "$agentcore_region" 2>/dev/null && ok "Deleted ${rule}" || warn "Rule not found: ${rule}"
    done

    # ── Step 4: Delete EventBridge bus ────────────────────────────────────────
    header "Deleting EventBridge bus"
    step "Deleting aria-audit bus"
    aws events delete-event-bus --name aria-audit \
        --region "$agentcore_region" 2>/dev/null && ok "Bus deleted" || warn "Bus not found"

    # ── Step 5: Delete Lambda functions ──────────────────────────────────────
    header "Deleting Lambda functions"
    for fn in aria-audit-cloudtrail-writer aria-audit-dynamodb-writer; do
        step "Deleting Lambda: ${fn}"
        aws lambda delete-function --function-name "$fn" \
            --region "$agentcore_region" 2>/dev/null && ok "Deleted ${fn}" || warn "Lambda not found: ${fn}"
    done

    # ── Step 6: Delete Lambda IAM role ────────────────────────────────────────
    header "Deleting Lambda IAM role"
    step "Detaching policies from aria-lambda-audit-role"
    aws iam delete-role-policy --role-name aria-lambda-audit-role --policy-name CloudTrailLakeWrite  2>/dev/null || true
    aws iam delete-role-policy --role-name aria-lambda-audit-role --policy-name DynamoDBAuditWrite   2>/dev/null || true
    aws iam detach-role-policy --role-name aria-lambda-audit-role \
        --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole 2>/dev/null || true
    aws iam delete-role --role-name aria-lambda-audit-role 2>/dev/null && \
        ok "Lambda role deleted" || warn "Lambda role not found"

    # ── Step 7: Delete Firehose ───────────────────────────────────────────────
    header "Deleting Kinesis Firehose"
    step "Deleting aria-audit-firehose"
    aws firehose delete-delivery-stream --delivery-stream-name aria-audit-firehose \
        --region "$agentcore_region" 2>/dev/null && ok "Firehose deleted" || warn "Firehose not found"

    step "Deleting Firehose IAM role"
    aws iam delete-role-policy --role-name aria-firehose-audit-role --policy-name S3WORMWrite 2>/dev/null || true
    aws iam delete-role --role-name aria-firehose-audit-role 2>/dev/null && \
        ok "Firehose role deleted" || warn "Role not found"

    # ── Step 8: Delete CloudTrail Lake ────────────────────────────────────────
    header "Deleting CloudTrail Lake"
    local channel_arn eds_arn
    channel_arn=$(state_get "cloudtrail_channel_arn")
    eds_arn=$(state_get "cloudtrail_eds_arn")

    if [[ -n "$channel_arn" ]]; then
        step "Deleting CloudTrail Lake channel"
        aws cloudtrail delete-channel --channel "$channel_arn" \
            --region "$agentcore_region" 2>/dev/null && ok "Channel deleted" || warn "Channel not found"
    fi

    if [[ -n "$eds_arn" ]]; then
        local eds_name
        eds_name=$(state_get "cloudtrail_eds_name")
        step "Deleting CloudTrail Lake event data store: ${eds_name:-aria-banking-audit}"
        aws cloudtrail delete-event-data-store --event-data-store "$eds_arn" \
            --region "$agentcore_region" 2>/dev/null && ok "Event data store deletion initiated (enters PENDING_DELETION)" || warn "Data store not found"
    fi

    # ── Step 9: Delete DynamoDB table ─────────────────────────────────────────
    header "Deleting DynamoDB table"
    step "Deleting aria-audit-events"
    aws dynamodb delete-table --table-name aria-audit-events \
        --region "$agentcore_region" 2>/dev/null && ok "Table deleted" || warn "Table not found"

    # ── Step 10: S3 buckets (optional) ────────────────────────────────────────
    header "S3 buckets"
    echo -e "  ${YELLOW}The transcript and audit S3 buckets were NOT automatically deleted.${NC}"
    echo -e "  ${YELLOW}The audit bucket has Object Lock COMPLIANCE mode — objects cannot be deleted.${NC}\n"

    if ask_yn "Delete transcript bucket ${transcript_bucket}? (you will lose all transcripts)" "N"; then
        step "Emptying and deleting ${transcript_bucket}"
        aws s3 rm "s3://${transcript_bucket}" --recursive --region "$agentcore_region" 2>/dev/null || true
        aws s3api delete-bucket --bucket "$transcript_bucket" \
            --region "$agentcore_region" 2>/dev/null && ok "Transcript bucket deleted" || warn "Bucket not found"
    else
        warn "Transcript bucket retained: s3://${transcript_bucket}"
    fi

    if ask_yn "Attempt to delete audit WORM bucket ${audit_bucket}? (will fail if objects are under retention)" "N"; then
        warn "Attempting — this will fail if any objects are within their 7-year retention window."
        aws s3 rm "s3://${audit_bucket}" --recursive --region "$agentcore_region" 2>/dev/null || true
        aws s3api delete-bucket --bucket "$audit_bucket" \
            --region "$agentcore_region" 2>/dev/null && ok "Audit bucket deleted" || \
            warn "Audit bucket delete failed (expected if retention active). Delete manually when retention expires."
    else
        warn "Audit bucket retained (expected for compliance): s3://${audit_bucket}"
    fi

    # ── Step 10.5: Cognito Identity Pool ──────────────────────────────────────
    local cognito_pool_id cognito_unauth_role deploy_id
    cognito_pool_id=$(state_get "cognito_identity_pool_id")
    cognito_unauth_role="aria-cognito-unauth-role-$(state_get 'deploy_id')"
    if [[ -n "$cognito_pool_id" ]]; then
        step "Deleting Cognito Identity Pool: $cognito_pool_id"
        aws cognito-identity delete-identity-pool \
            --identity-pool-id "$cognito_pool_id" \
            --region "$agentcore_region" --no-cli-pager &>/dev/null && \
            ok "Cognito pool deleted" || warn "Could not delete Cognito pool"
        step "Deleting Cognito unauth IAM role: $cognito_unauth_role"
        aws iam delete-role-policy --role-name "$cognito_unauth_role" \
            --policy-name "aria-cognito-unauth-policy" 2>/dev/null || true
        aws iam delete-role --role-name "$cognito_unauth_role" 2>/dev/null && \
            ok "Cognito unauth role deleted" || warn "Cognito unauth role not found"
    fi

    # ── Step 10.6: ECS Fargate / ALB resources ────────────────────────────────
    local ecs_service ecs_cluster alb_arn tg_arn alb_sg_id ecs_sg_id ecs_exec_role ecs_task_role
    ecs_service=$(state_get "ecs_service_name")
    ecs_cluster=$(state_get "ecs_cluster_name")
    alb_arn=$(state_get "alb_arn")
    tg_arn=$(state_get "alb_target_group_arn")
    alb_sg_id=$(state_get "alb_sg_id")
    ecs_sg_id=$(state_get "ecs_sg_id")
    deploy_id=$(state_get "deploy_id")
    ecs_exec_role="aria-ecs-task-exec-role-${deploy_id}"
    ecs_task_role="aria-ecs-task-role-${deploy_id}"

    if [[ -n "$ecs_service" && -n "$ecs_cluster" ]]; then
        header "Deleting ECS Fargate service"
        step "Scaling down and deleting ECS service: $ecs_service"
        aws ecs update-service --cluster "$ecs_cluster" --service "$ecs_service" \
            --desired-count 0 --region "$agentcore_region" --no-cli-pager &>/dev/null || true
        aws ecs delete-service --cluster "$ecs_cluster" --service "$ecs_service" \
            --force --region "$agentcore_region" --no-cli-pager &>/dev/null && \
            ok "ECS service deleted" || warn "ECS service not found"
    fi

    if [[ -n "$alb_arn" ]]; then
        header "Deleting ALB and Target Group"
        local listener_arn
        listener_arn=$(aws elbv2 describe-listeners \
            --load-balancer-arn "$alb_arn" \
            --region "$agentcore_region" --no-cli-pager \
            --query 'Listeners[0].ListenerArn' --output text 2>/dev/null || true)
        [[ -n "$listener_arn" && "$listener_arn" != "None" ]] && \
            aws elbv2 delete-listener --listener-arn "$listener_arn" \
                --region "$agentcore_region" --no-cli-pager &>/dev/null || true
        aws elbv2 delete-load-balancer --load-balancer-arn "$alb_arn" \
            --region "$agentcore_region" --no-cli-pager &>/dev/null && \
            ok "ALB deleted" || warn "ALB not found"
        step "Waiting 15s for ALB deletion before removing target group..."
        sleep 15
        [[ -n "$tg_arn" ]] && \
            aws elbv2 delete-target-group --target-group-arn "$tg_arn" \
                --region "$agentcore_region" --no-cli-pager &>/dev/null && \
            ok "Target group deleted" || true
    fi

    if [[ -n "$ecs_cluster" ]]; then
        aws ecs delete-cluster --cluster "$ecs_cluster" \
            --region "$agentcore_region" --no-cli-pager &>/dev/null && \
            ok "ECS cluster deleted" || warn "ECS cluster not found"
    fi

    # Delete ECS IAM roles
    if [[ -n "$deploy_id" ]]; then
        step "Deleting ECS IAM roles"
        aws iam detach-role-policy --role-name "$ecs_exec_role" \
            --policy-arn "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy" 2>/dev/null || true
        aws iam detach-role-policy --role-name "$ecs_exec_role" \
            --policy-arn "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly" 2>/dev/null || true
        aws iam delete-role --role-name "$ecs_exec_role" 2>/dev/null && \
            ok "ECS exec role deleted" || warn "ECS exec role not found"
        aws iam delete-role-policy --role-name "$ecs_task_role" \
            --policy-name "aria-ecs-task-policy" 2>/dev/null || true
        aws iam delete-role --role-name "$ecs_task_role" 2>/dev/null && \
            ok "ECS task role deleted" || warn "ECS task role not found"
    fi

    # Delete security groups (after ALB is gone)
    if [[ -n "$ecs_sg_id" ]]; then
        aws ec2 delete-security-group --group-id "$ecs_sg_id" \
            --region "$agentcore_region" --no-cli-pager &>/dev/null && \
            ok "ECS security group deleted" || warn "ECS security group not found"
    fi
    if [[ -n "$alb_sg_id" ]]; then
        aws ec2 delete-security-group --group-id "$alb_sg_id" \
            --region "$agentcore_region" --no-cli-pager &>/dev/null && \
            ok "ALB security group deleted" || warn "ALB security group not found"
    fi

    # Delete CloudWatch log group
    aws logs delete-log-group \
        --log-group-name "/ecs/aria-banking-${deploy_id}" \
        --region "$agentcore_region" --no-cli-pager &>/dev/null || true

    # ── Step 11: Clean up state file ─────────────────────────────────────────
    rm -f "$STATE_FILE"
    rm -f "${PROJECT_ROOT}/scripts/test_invoke.py"
    ok "State file removed"

    echo -e "\n${GREEN}${BOLD}  Teardown complete.${NC}\n"
}

# =============================================================================
#  STATUS
# =============================================================================

cmd_status() {
    header "ARIA Deployment Status"
    [[ -f "$STATE_FILE" ]] || { warn "No deployment state found. Run: ./scripts/deploy.sh deploy"; exit 0; }

    echo ""
    python3 - "$STATE_FILE" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    state = json.load(f)
keys_labels = [
    ("deploy_id",             "Deploy ID"),
    ("agentcore_region",      "AgentCore region"),
    ("claude_region",         "Claude region"),
    ("nova_sonic_region",     "Nova Sonic region"),
    ("runtime_arn",           "Runtime ARN"),
    ("transcript_bucket",     "Transcript bucket"),
    ("audit_bucket",          "Audit WORM bucket"),
    ("eventbridge_bus_arn",   "EventBridge bus"),
    ("cloudtrail_channel_arn","CloudTrail channel"),
    ("cloudtrail_eds_name",   "CloudTrail data store name"),
    ("cloudtrail_eds_arn",    "CloudTrail data store ARN"),
    ("cloudtrail_lambda_arn", "CloudTrail Lambda"),
    ("dynamodb_lambda_arn",   "DynamoDB Lambda"),
    ("firehose_arn",          "Firehose stream"),
    ("execution_role_name",   "Execution role"),
    ("cognito_identity_pool_id", "Cognito Identity Pool"),
    ("cognito_unauth_role_arn",  "Cognito unauth role"),
    ("alb_dns",               "ALB DNS"),
    ("alb_arn",               "ALB ARN"),
    ("ecs_cluster_name",      "ECS cluster"),
    ("ecs_service_name",      "ECS service"),
    ("ecs_task_def_arn",      "ECS task definition"),
]
for key, label in keys_labels:
    val = state.get(key, "(not set)")
    print(f"  {label:<28} {val}")
PYEOF
    echo ""
}

# =============================================================================
#  ENTRYPOINT
# =============================================================================

usage() {
    echo -e "${BOLD}Usage:${NC}  $0 <command>"
    echo ""
    echo "  deploy    — deploy the full ARIA stack to AWS AgentCore"
    echo "  teardown  — destroy all AWS resources created by deploy"
    echo "  status    — print current deployment state"
    echo ""
}

case "${1:-}" in
    deploy)   cmd_deploy   ;;
    teardown) cmd_teardown ;;
    status)   cmd_status   ;;
    *)        usage; exit 1 ;;
esac
