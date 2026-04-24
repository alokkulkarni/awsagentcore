#!/usr/bin/env bash
# =============================================================================
#  deploy_dtmf_lambda.sh
#  ARIA — DTMF Decryption + Validation Lambdas — Deploy / Teardown Script
#  Meridian Bank / Amazon Connect
# =============================================================================
#
#  USAGE
#    ./scripts/deploy_dtmf_lambda.sh deploy          ← fully interactive; prompts for all values
#    ./scripts/deploy_dtmf_lambda.sh deploy --region eu-west-2   ← only override region
#    ./scripts/deploy_dtmf_lambda.sh teardown
#    ./scripts/deploy_dtmf_lambda.sh status
#
#  WHAT THIS SCRIPT CREATES
#    DynamoDB     aria-card-bins      — BIN prefix → card type mapping (seeded with example BINs)
#                 aria-customer-cards — customer ID → card last-four fallback lookup
#
#    IAM role     aria-dtmf-decrypt-role
#                   — AWSLambdaBasicExecutionRole (CloudWatch Logs)
#                   — secretsmanager:GetSecretValue on the DTMF private key secret
#                   — kms:Decrypt on the KMS CMK protecting the secret
#                   — dynamodb:GetItem/Query/Scan on aria-card-bins and aria-customer-cards
#
#                 aria-lambda-dtmf-validate-role
#                   — AWSLambdaBasicExecutionRole (CloudWatch Logs)
#                   — dynamodb:GetItem/Query/Scan on aria-card-bins and aria-customer-cards
#                   — lambda:InvokeFunction on aria-banking-mcp-customer-prod
#                   — connect:UpdateContactAttributes (pushes real-time status to agent CCP)
#
#    Lambda Layer aria-dtmf-dependencies  (Python 3.12)
#                   — aws-encryption-sdk  (AWS Encryption SDK, v3.x — v4.x removed RawRSAMasterKeyProvider)
#                   — cryptography        (RSA decryption primitives)
#                   Built for manylinux2014_x86_64 to match Lambda runtime
#
#    Lambda       aria-dtmf-decrypt  (Python 3.12, eu-west-2)
#                   — decrypts encrypted DTMF digits using RSA private key from Secrets Manager
#                   — publishes a new immutable version on every deploy
#                   — creates / updates 'prod' alias → latest version
#                   — timeout 15s, memory 256MB
#
#                 aria-dtmf-validate  (Python 3.12, eu-west-2)
#                   — Luhn check, BIN lookup (DynamoDB), card ownership check
#                   — publishes a new immutable version on every deploy
#                   — creates / updates 'prod' alias → latest version
#                   — timeout 15s, memory 256MB
#
#    Connect      resource-based policy on the :prod alias ARN of both Lambdas
#                   so that only your Connect instance can invoke them
#
#  PROD ALIAS
#    Every deploy publishes a new immutable version and moves the 'prod' alias
#    to it automatically.  Contact flows should reference the :prod alias ARN:
#      arn:aws:lambda:<region>:<account>:function:aria-dtmf-decrypt:prod
#      arn:aws:lambda:<region>:<account>:function:aria-dtmf-validate:prod
#    Never reference $LATEST in production flows.
#
#  PREREQUISITES
#    • aws CLI v2 configured with sufficient IAM permissions
#    • python3 + pip3 in PATH
#    • zip in PATH
#    • Run setup_dtmf_keys.sh first to generate keys and populate state file
#
#  ENVIRONMENT VARIABLES (overrides — script reads state file automatically)
#    AWS_REGION              default: eu-west-2
#    CONNECT_INSTANCE_ID     Connect instance UUID
#    PRIVATE_KEY_SECRET_ARN  Secrets Manager ARN from setup_dtmf_keys.sh
#    CONNECT_KEY_ID          Connect Security Key ID from setup_dtmf_keys.sh
#    KMS_KEY_ARN             KMS CMK ARN from setup_dtmf_keys.sh
#
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAMBDA_DIR="${SCRIPT_DIR}/lambdas"
LAMBDA_SOURCE="${LAMBDA_DIR}/aria_dtmf_decrypt.py"
STATE_FILE="${SCRIPT_DIR}/.deploy-dtmf-lambda-state.json"
KEY_STATE_FILE="${SCRIPT_DIR}/.deploy-dtmf-key-state.json"

FUNCTION_NAME="aria-dtmf-decrypt"
LAYER_NAME="aria-dtmf-dependencies"
ALIAS_NAME="prod"
ROLE_NAME="aria-dtmf-decrypt-role"
RUNTIME="python3.12"
REGION="${AWS_REGION:-eu-west-2}"
CONNECT_INSTANCE_ID="${CONNECT_INSTANCE_ID:-}"
CONNECT_INSTANCE_URL="${CONNECT_INSTANCE_URL:-}"
PRIVATE_KEY_SECRET_ARN="${PRIVATE_KEY_SECRET_ARN:-}"
CONNECT_KEY_ID="${CONNECT_KEY_ID:-}"
KMS_KEY_ARN="${KMS_KEY_ARN:-}"

# DynamoDB table names
CARD_BINS_TABLE="aria-card-bins"
CUSTOMER_CARDS_TABLE="aria-customer-cards"

# Runtime state (populated during deploy)
ACCOUNT_ID=""
ROLE_ARN=""
LAYER_ARN=""
LAMBDA_ARN=""
LAMBDA_ALIAS_ARN=""

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
    local input; read -r input </dev/tty
    [[ -z "$input" ]] && input="$default"
    printf -v "$var" '%s' "$input"
}

ask_yn() {
    local prompt="$1" default="${2:-Y}"
    local display="y/n"
    [[ "${default^^}" == "Y" ]] && display="Y/n" || display="y/N"
    printf "${BOLD}  ? ${prompt} [${display}]: ${NC}" >/dev/tty
    local input; read -r input </dev/tty
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
    local key="$1" default="${2:-}"
    python3 - "$STATE_FILE" "$key" "$default" <<'PYEOF'
import sys, json
path, key, default = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path) as f: data = json.load(f)
print(data.get(key, default))
PYEOF
}

# Read a value from the keys state file (written by setup_dtmf_keys.sh)
key_state_get() {
    local key="$1" default="${2:-}"
    if [[ ! -f "$KEY_STATE_FILE" ]]; then
        echo "$default"
        return
    fi
    python3 - "$KEY_STATE_FILE" "$key" "$default" <<'PYEOF'
import sys, json
path, key, default = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    with open(path) as f: data = json.load(f)
    print(data.get(key, default))
except Exception:
    print(default)
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

alias_exists() {
    aws lambda get-alias --function-name "$1" --name "$2" --region "$3" \
        --query "Name" --output text 2>/dev/null || true
}

layer_exists() {
    # Returns the latest version number of the layer, or empty if none
    aws lambda list-layer-versions \
        --layer-name "$1" \
        --region "$2" \
        --query "LayerVersions[0].Version" \
        --output text 2>/dev/null || true
}

# ── Resolve config from key state file + env vars ─────────────────────────────
resolve_config() {
    header "Resolving configuration"

    # Priority order: CLI arg / env var → KEY_STATE_FILE (setup_dtmf_keys.sh) → STATE_FILE (previous deploy)
    if [[ -z "$PRIVATE_KEY_SECRET_ARN" ]]; then
        PRIVATE_KEY_SECRET_ARN=$(key_state_get "secret_arn" "")
    fi
    if [[ -z "$PRIVATE_KEY_SECRET_ARN" ]]; then
        PRIVATE_KEY_SECRET_ARN=$(state_get "private_key_secret_arn" "")
    fi

    if [[ -z "$CONNECT_KEY_ID" ]]; then
        CONNECT_KEY_ID=$(key_state_get "connect_key_id" "")
    fi
    if [[ -z "$CONNECT_KEY_ID" ]]; then
        CONNECT_KEY_ID=$(state_get "connect_key_id" "")
    fi

    if [[ -z "$KMS_KEY_ARN" ]]; then
        KMS_KEY_ARN=$(key_state_get "kms_key_arn" "")
    fi
    if [[ -z "$KMS_KEY_ARN" ]]; then
        KMS_KEY_ARN=$(state_get "kms_key_arn" "")
    fi

    if [[ -z "$CONNECT_INSTANCE_ID" ]]; then
        CONNECT_INSTANCE_ID=$(key_state_get "connect_instance_id" "")
    fi
    if [[ -z "$CONNECT_INSTANCE_ID" ]]; then
        CONNECT_INSTANCE_ID=$(state_get "connect_instance_id" "")
    fi

    if [[ -z "$CONNECT_INSTANCE_URL" ]]; then
        CONNECT_INSTANCE_URL=$(state_get "connect_instance_url" "")
    fi

    # Prompt only for values still missing after reading both state files
    if [[ -z "$PRIVATE_KEY_SECRET_ARN" ]]; then
        ask PRIVATE_KEY_SECRET_ARN \
            "Secrets Manager ARN for RSA private key" \
            "arn:aws:secretsmanager:${REGION}:${ACCOUNT_ID}:secret:meridian/connect/dtmf-private-key-XXXXXX"
    fi
    if [[ -z "$CONNECT_KEY_ID" ]]; then
        ask CONNECT_KEY_ID "Connect Flow Security Key ID (from Connect console → instance → Contact flows → Flow security keys)" ""
        if [[ -z "$CONNECT_KEY_ID" ]]; then
            warn "No Connect Key ID — Lambda will use env var CONNECT_KEY_ID=meridian-connect-key-id as placeholder"
            CONNECT_KEY_ID="meridian-connect-key-id"
        fi
    fi
    if [[ -z "$KMS_KEY_ARN" ]]; then
        ask KMS_KEY_ARN \
            "KMS CMK ARN for Secrets Manager decryption" \
            "arn:aws:kms:${REGION}:${ACCOUNT_ID}:key/<KEY_ID>"
    fi
    if [[ -z "$CONNECT_INSTANCE_ID" ]]; then
        ask CONNECT_INSTANCE_ID \
            "Amazon Connect Instance ID (UUID from Connect console → instance → Overview → Instance ARN)" ""
        if [[ -z "$CONNECT_INSTANCE_ID" ]]; then
            warn "No Connect Instance ID — skipping Connect resource-based policy (add manually later)"
        fi
    fi

    # Connect instance URL — needed for the CCP Status Panel
    if [[ -z "$CONNECT_INSTANCE_URL" ]]; then
        ask CONNECT_INSTANCE_URL \
            "Connect instance URL for CCP Status Panel (e.g. https://meridian-bank.my.connect.aws)" ""
        if [[ -z "$CONNECT_INSTANCE_URL" ]]; then
            warn "No Connect instance URL — CCP Status Panel deploy will be skipped (re-run with --connect-instance-url to deploy later)"
        fi
    fi

    # Persist all values to STATE_FILE so subsequent deploys skip these prompts
    [[ -n "$PRIVATE_KEY_SECRET_ARN" ]] && state_set "private_key_secret_arn" "$PRIVATE_KEY_SECRET_ARN"
    [[ -n "$CONNECT_KEY_ID"         ]] && state_set "connect_key_id"         "$CONNECT_KEY_ID"
    [[ -n "$KMS_KEY_ARN"            ]] && state_set "kms_key_arn"            "$KMS_KEY_ARN"
    [[ -n "$CONNECT_INSTANCE_ID"    ]] && state_set "connect_instance_id"    "$CONNECT_INSTANCE_ID"
    [[ -n "$CONNECT_INSTANCE_URL"   ]] && state_set "connect_instance_url"   "$CONNECT_INSTANCE_URL"

    ok "Secret ARN:      ${PRIVATE_KEY_SECRET_ARN}"
    ok "Connect Key:     ${CONNECT_KEY_ID}"
    ok "KMS Key ARN:     ${KMS_KEY_ARN}"
    [[ -n "$CONNECT_INSTANCE_ID" ]]  && ok "Instance ID:     ${CONNECT_INSTANCE_ID}"  || warn "Instance ID:     (not set)"
    [[ -n "$CONNECT_INSTANCE_URL" ]] && ok "Instance URL:    ${CONNECT_INSTANCE_URL}" || warn "Instance URL:    (not set — panel will be skipped)"
}

# =============================================================================
#  Step 1 — IAM Role
# =============================================================================
ensure_iam_role() {
    header "IAM role: ${ROLE_NAME}"

    if [[ -n "$(iam_role_exists "$ROLE_NAME")" ]]; then
        ok "Role already exists — verifying inline policies"
    else
        step "Creating IAM role ${ROLE_NAME}..."
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

        ok "Role created and AWSLambdaBasicExecutionRole attached"
        step "Waiting 15s for IAM propagation..."
        sleep 15
    fi

    # Always put-role-policy (idempotent) — Secrets Manager GetSecretValue
    step "Ensuring Secrets Manager read policy..."
    aws iam put-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-name "DTMFSecretsManagerRead" \
        --policy-document "{
            \"Version\": \"2012-10-17\",
            \"Statement\": [{
                \"Sid\":    \"GetPrivateKey\",
                \"Effect\": \"Allow\",
                \"Action\": \"secretsmanager:GetSecretValue\",
                \"Resource\": \"${PRIVATE_KEY_SECRET_ARN}\"
            }]
        }"
    ok "Secrets Manager GetSecretValue policy in place"

    # KMS Decrypt policy (needed so Secrets Manager can decrypt the secret)
    if [[ -n "$KMS_KEY_ARN" && "$KMS_KEY_ARN" != *"<KEY_ID>"* ]]; then
        step "Ensuring KMS Decrypt policy..."
        aws iam put-role-policy \
            --role-name "$ROLE_NAME" \
            --policy-name "DTMFKMSDecrypt" \
            --policy-document "{
                \"Version\": \"2012-10-17\",
                \"Statement\": [{
                    \"Sid\":    \"KMSDecryptForSecrets\",
                    \"Effect\": \"Allow\",
                    \"Action\": \"kms:Decrypt\",
                    \"Resource\": \"${KMS_KEY_ARN}\"
                }]
            }"
        ok "KMS Decrypt policy in place"
    else
        warn "KMS_KEY_ARN not set or placeholder — skipping KMS policy."
        warn "Add it later with: aws iam put-role-policy --role-name ${ROLE_NAME} ..."
    fi

    # DynamoDB read policy — Lambda needs GetItem/Query on both tables
    step "Ensuring DynamoDB read policy..."
    local CARD_BINS_ARN="arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${CARD_BINS_TABLE}"
    local CUSTOMER_CARDS_ARN="arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${CUSTOMER_CARDS_TABLE}"
    aws iam put-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-name "DTMFDynamoDBRead" \
        --policy-document "{
            \"Version\": \"2012-10-17\",
            \"Statement\": [{
                \"Sid\":    \"DTMFReadDynamoDB\",
                \"Effect\": \"Allow\",
                \"Action\": [
                    \"dynamodb:GetItem\",
                    \"dynamodb:Query\",
                    \"dynamodb:Scan\"
                ],
                \"Resource\": [
                    \"${CARD_BINS_ARN}\",
                    \"${CUSTOMER_CARDS_ARN}\"
                ]
            }]
        }"
    ok "DynamoDB read policy in place (${CARD_BINS_TABLE}, ${CUSTOMER_CARDS_TABLE})"

    # connect:UpdateContactAttributes — decrypt Lambda pushes system_error on failure
    step "Ensuring connect:UpdateContactAttributes policy on ${ROLE_NAME}..."
    if [[ -n "$CONNECT_INSTANCE_ID" ]]; then
        local connect_arn="arn:aws:connect:${REGION}:${ACCOUNT_ID}:instance/${CONNECT_INSTANCE_ID}"
        aws iam put-role-policy \
            --role-name "$ROLE_NAME" \
            --policy-name "DTMFConnectPushStatus" \
            --policy-document "{
                \"Version\": \"2012-10-17\",
                \"Statement\": [{
                    \"Sid\":    \"ConnectUpdateAttributes\",
                    \"Effect\": \"Allow\",
                    \"Action\": \"connect:UpdateContactAttributes\",
                    \"Resource\": \"${connect_arn}/contact/*\"
                }]
            }"
        ok "connect:UpdateContactAttributes policy in place on ${ROLE_NAME}"
    else
        warn "CONNECT_INSTANCE_ID not set — skipping connect policy on ${ROLE_NAME}. Run deploy again after setting it."
    fi

    ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
    state_set "role_arn" "$ROLE_ARN"
    ok "Role ARN: ${ROLE_ARN}"
}

# =============================================================================
#  Step 2 — DynamoDB tables (create + seed)
# =============================================================================
dynamodb_table_exists() {
    aws dynamodb describe-table \
        --table-name "$1" \
        --region "$REGION" \
        --query "Table.TableName" --output text 2>/dev/null || true
}

ensure_dynamodb_tables() {
    header "DynamoDB: ${CARD_BINS_TABLE} and ${CUSTOMER_CARDS_TABLE}"

    # ── aria-card-bins ────────────────────────────────────────────────────────
    if [[ -n "$(dynamodb_table_exists "$CARD_BINS_TABLE")" ]]; then
        ok "Table already exists: ${CARD_BINS_TABLE}"
    else
        step "Creating table ${CARD_BINS_TABLE}..."
        aws dynamodb create-table \
            --table-name "$CARD_BINS_TABLE" \
            --attribute-definitions AttributeName=binPrefix,AttributeType=S \
            --key-schema AttributeName=binPrefix,KeyType=HASH \
            --billing-mode PAY_PER_REQUEST \
            --region "$REGION" \
            --query "TableDescription.TableName" --output text > /dev/null
        step "Waiting for table to become ACTIVE..."
        aws dynamodb wait table-exists --table-name "$CARD_BINS_TABLE" --region "$REGION"
        ok "Table created: ${CARD_BINS_TABLE}"

        step "Seeding ${CARD_BINS_TABLE} with example BIN data..."
        local bins=(
            '{"binPrefix":{"S":"414900"},"cardType":{"S":"VISA_DEBIT"},"isActive":{"BOOL":true}}'
            '{"binPrefix":{"S":"415900"},"cardType":{"S":"VISA_DEBIT"},"isActive":{"BOOL":true}}'
            '{"binPrefix":{"S":"532188"},"cardType":{"S":"MC_CREDIT"},"isActive":{"BOOL":true}}'
            '{"binPrefix":{"S":"543210"},"cardType":{"S":"MC_DEBIT"},"isActive":{"BOOL":true}}'
            '{"binPrefix":{"S":"601100"},"cardType":{"S":"MAESTRO"},"isActive":{"BOOL":true}}'
        )
        for item in "${bins[@]}"; do
            aws dynamodb put-item \
                --table-name "$CARD_BINS_TABLE" \
                --item "$item" \
                --region "$REGION"
        done
        ok "Seeded ${#bins[@]} example BIN entries — replace with your real BIN ranges from card operations"
    fi

    state_set "card_bins_table" "$CARD_BINS_TABLE"

    # ── aria-customer-cards ────────────────────────────────────────────────────
    if [[ -n "$(dynamodb_table_exists "$CUSTOMER_CARDS_TABLE")" ]]; then
        ok "Table already exists: ${CUSTOMER_CARDS_TABLE}"
    else
        step "Creating table ${CUSTOMER_CARDS_TABLE}..."
        aws dynamodb create-table \
            --table-name "$CUSTOMER_CARDS_TABLE" \
            --attribute-definitions \
                AttributeName=customerId,AttributeType=S \
                AttributeName=cardLastFour,AttributeType=S \
            --key-schema \
                AttributeName=customerId,KeyType=HASH \
                AttributeName=cardLastFour,KeyType=RANGE \
            --billing-mode PAY_PER_REQUEST \
            --region "$REGION" \
            --query "TableDescription.TableName" --output text > /dev/null
        step "Waiting for table to become ACTIVE..."
        aws dynamodb wait table-exists --table-name "$CUSTOMER_CARDS_TABLE" --region "$REGION"
        ok "Table created: ${CUSTOMER_CARDS_TABLE}"

        step "Seeding ${CUSTOMER_CARDS_TABLE} with test customer data..."
        # CUST-001 = James Hartley — Visa debit ending 4821, Mastercard credit ending 2291
        # cardBin stored so DynamoDB fallback validates customerId + BIN + lastFour
        aws dynamodb put-item \
            --table-name "$CUSTOMER_CARDS_TABLE" \
            --item '{"customerId":{"S":"CUST-001"},"cardLastFour":{"S":"4821"},"cardBin":{"S":"414900"},"isActive":{"BOOL":true},"cardType":{"S":"VISA_DEBIT"},"nickname":{"S":"Everyday Debit"}}' \
            --region "$REGION"
        aws dynamodb put-item \
            --table-name "$CUSTOMER_CARDS_TABLE" \
            --item '{"customerId":{"S":"CUST-001"},"cardLastFour":{"S":"2291"},"cardBin":{"S":"531908"},"isActive":{"BOOL":true},"cardType":{"S":"MC_CREDIT"},"nickname":{"S":"Rewards Credit Card"}}' \
            --region "$REGION"
        aws dynamodb put-item \
            --table-name "$CUSTOMER_CARDS_TABLE" \
            --item '{"customerId":{"S":"CUST-001"},"cardLastFour":{"S":"8901"},"cardBin":{"S":"453978"},"isActive":{"BOOL":true},"cardType":{"S":"VISA_DEBIT"}}' \
            --region "$REGION"
        # CUST-002 fallback test record
        aws dynamodb put-item \
            --table-name "$CUSTOMER_CARDS_TABLE" \
            --item '{"customerId":{"S":"CUST-002"},"cardLastFour":{"S":"4821"},"cardBin":{"S":"524860"},"isActive":{"BOOL":true},"cardType":{"S":"MC_CREDIT"}}' \
            --region "$REGION"
        ok "Seeded 4 test customer records — replace with data from your core banking sync"
    fi

    state_set "customer_cards_table" "$CUSTOMER_CARDS_TABLE"
    ok "DynamoDB tables ready"
}

# =============================================================================
#  Step 3 — Lambda Layer (aws-encryption-sdk + cryptography)
# =============================================================================
ensure_lambda_layer() {
    header "Lambda Layer: ${LAYER_NAME}"

    # Check state file first — reuse existing layer if it still exists in AWS
    if [[ -z "$LAYER_ARN" ]]; then
        LAYER_ARN=$(state_get "layer_arn" "")
    fi

    if [[ -n "$LAYER_ARN" ]]; then
        local existing_arn
        existing_arn=$(aws lambda get-layer-version-by-arn \
            --arn "$LAYER_ARN" \
            --region "$REGION" \
            --query "LayerVersionArn" --output text 2>/dev/null || echo "")
        if [[ -n "$existing_arn" && "$existing_arn" != "None" ]]; then
            ok "Reusing existing layer (skipping rebuild): ${LAYER_ARN}"
            return 0
        fi
        warn "Stored layer ARN no longer exists — rebuilding layer"
        LAYER_ARN=""
    fi

    local layer_tmp="/tmp/dtmf-layer"
    local layer_zip="/tmp/${LAYER_NAME}.zip"

    step "Building Lambda Layer (aws-encryption-sdk + cryptography for ${RUNTIME}/linux)..."
    step "  This may take 1-2 minutes on first run..."

    rm -rf "$layer_tmp"
    mkdir -p "${layer_tmp}/python"

    # Install with manylinux2014 binaries to match Lambda's Amazon Linux 2 runtime.
    # --platform manylinux2014_x86_64 fetches pre-built wheels (no compilation needed).
    pip3 install \
        "aws-encryption-sdk>=3.1.0,<4.0.0" \
        "cryptography>=42.0.0" \
        --target "${layer_tmp}/python" \
        --platform manylinux2014_x86_64 \
        --python-version 3.12 \
        --only-binary=:all: \
        --quiet

    step "  Packaging layer zip..."
    (cd "$layer_tmp" && zip -qr "$layer_zip" python/)
    local zip_size
    zip_size=$(du -sh "$layer_zip" | cut -f1)
    ok "Layer package ready: ${layer_zip} (${zip_size})"

    step "Publishing Lambda Layer version..."
    LAYER_ARN=$(aws lambda publish-layer-version \
        --layer-name "$LAYER_NAME" \
        --description "aws-encryption-sdk + cryptography for ARIA DTMF decryption (built $(date -u +%Y-%m-%d))" \
        --zip-file "fileb://${layer_zip}" \
        --compatible-runtimes "$RUNTIME" \
        --region "$REGION" \
        --query "LayerVersionArn" --output text)

    ok "Layer published: ${LAYER_ARN}"
    state_set "layer_arn"     "$LAYER_ARN"
    state_set "layer_name"    "$LAYER_NAME"

    rm -rf "$layer_tmp" "$layer_zip"
}

# =============================================================================
#  Step 3 — Lambda function + version + prod alias
# =============================================================================
deploy_lambda_and_alias() {
    header "Lambda: ${FUNCTION_NAME}"

    [[ -f "$LAMBDA_SOURCE" ]] || die "Lambda source not found: ${LAMBDA_SOURCE}"

    local zip_path="/tmp/${FUNCTION_NAME}.zip"
    step "Packaging ${FUNCTION_NAME}..."
    (cd "$LAMBDA_DIR" && zip -q "$zip_path" "aria_dtmf_decrypt.py")

    local env_vars
    env_vars="Variables={PRIVATE_KEY_SECRET_ARN=${PRIVATE_KEY_SECRET_ARN},CONNECT_KEY_ID=${CONNECT_KEY_ID},CARD_BINS_TABLE=${CARD_BINS_TABLE},CUSTOMER_CARDS_TABLE=${CUSTOMER_CARDS_TABLE},CONNECT_INSTANCE_ID=${CONNECT_INSTANCE_ID}}"

    if [[ -n "$(lambda_exists "$FUNCTION_NAME" "$REGION")" ]]; then
        # ── Update existing function ─────────────────────────────────────────
        step "Updating code for existing Lambda ${FUNCTION_NAME}..."
        aws lambda update-function-code \
            --function-name "$FUNCTION_NAME" \
            --zip-file      "fileb://${zip_path}" \
            --region        "$REGION" \
            --query         "FunctionName" --output text > /dev/null

        step "Waiting for code update..."
        aws lambda wait function-updated \
            --function-name "$FUNCTION_NAME" \
            --region        "$REGION" 2>/dev/null || true

        step "Updating configuration (env vars, layers, timeout)..."
        aws lambda update-function-configuration \
            --function-name "$FUNCTION_NAME" \
            --environment   "$env_vars" \
            --layers        "$LAYER_ARN" \
            --timeout       15 \
            --memory-size   256 \
            --region        "$REGION" \
            --query         "FunctionName" --output text > /dev/null

        step "Waiting for configuration update..."
        aws lambda wait function-updated \
            --function-name "$FUNCTION_NAME" \
            --region        "$REGION" 2>/dev/null || true

        ok "Lambda code and config updated"

    else
        # ── Create new function ──────────────────────────────────────────────
        step "Creating Lambda ${FUNCTION_NAME}..."
        aws lambda create-function \
            --function-name "$FUNCTION_NAME" \
            --runtime        "$RUNTIME" \
            --role           "$ROLE_ARN" \
            --handler        "aria_dtmf_decrypt.handler" \
            --zip-file       "fileb://${zip_path}" \
            --timeout        15 \
            --memory-size    256 \
            --environment    "$env_vars" \
            --layers         "$LAYER_ARN" \
            --description    "Amazon Connect DTMF RSA decryption — Meridian Bank" \
            --region         "$REGION" \
            --query          "FunctionName" --output text > /dev/null

        step "Waiting for Lambda to become active..."
        aws lambda wait function-active \
            --function-name "$FUNCTION_NAME" \
            --region        "$REGION" 2>/dev/null || true

        ok "Lambda created"
    fi

    # ── Publish an immutable version ─────────────────────────────────────────
    step "Publishing new Lambda version..."
    local new_version
    new_version=$(aws lambda publish-version \
        --function-name "$FUNCTION_NAME" \
        --description   "Deployed $(date -u '+%Y-%m-%dT%H:%M:%SZ') — layer:${LAYER_ARN##*:}" \
        --region        "$REGION" \
        --query         "Version" --output text)
    ok "Published version: ${new_version}"

    # ── Create or update the 'prod' alias ─────────────────────────────────────
    if [[ -n "$(alias_exists "$FUNCTION_NAME" "$ALIAS_NAME" "$REGION")" ]]; then
        step "Updating '${ALIAS_NAME}' alias → version ${new_version}..."
        aws lambda update-alias \
            --function-name    "$FUNCTION_NAME" \
            --name             "$ALIAS_NAME" \
            --function-version "$new_version" \
            --description      "Production — deployed $(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
            --region           "$REGION" \
            --query            "AliasArn" --output text > /dev/null
    else
        step "Creating '${ALIAS_NAME}' alias → version ${new_version}..."
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

    rm -f "$zip_path"
}

# =============================================================================
#  Step 4 — Grant Amazon Connect permission to invoke the Lambda :prod alias
# =============================================================================
add_connect_permission() {
    header "Connect → Lambda permission"

    if [[ -z "$CONNECT_INSTANCE_ID" ]]; then
        warn "No --instance-id provided — skipping Connect resource-based policy."
        warn "Add it manually:"
        warn "  aws lambda add-permission \\"
        warn "    --function-name '${LAMBDA_ALIAS_ARN}' \\"
        warn "    --statement-id  ConnectInvoke \\"
        warn "    --action        lambda:InvokeFunction \\"
        warn "    --principal     connect.amazonaws.com \\"
        warn "    --source-account '${ACCOUNT_ID}' \\"
        warn "    --region        ${REGION}"
        return
    fi

    step "Adding resource-based policy on ${LAMBDA_ALIAS_ARN}..."

    # The permission is on the :prod alias ARN so only the prod alias is callable
    # (not $LATEST). source-account is required when source-arn isn't specified,
    # to prevent the confused deputy problem.
    aws lambda add-permission \
        --function-name  "$LAMBDA_ALIAS_ARN" \
        --statement-id   "AllowConnectInvoke" \
        --action         "lambda:InvokeFunction" \
        --principal      "connect.amazonaws.com" \
        --source-account "$ACCOUNT_ID" \
        --region         "$REGION" 2>/dev/null && \
    ok "Resource-based policy added — Connect can invoke ${LAMBDA_ALIAS_ARN}" || \
    warn "AllowConnectInvoke policy already set on alias (non-fatal)"

    # Also add permission on the unqualified function ARN (belt-and-braces)
    aws lambda add-permission \
        --function-name  "$LAMBDA_ARN" \
        --statement-id   "AllowConnectInvokeUnqualified" \
        --action         "lambda:InvokeFunction" \
        --principal      "connect.amazonaws.com" \
        --source-account "$ACCOUNT_ID" \
        --region         "$REGION" 2>/dev/null && \
    ok "Resource-based policy also added on unqualified function ARN" || \
    warn "AllowConnectInvokeUnqualified already set (non-fatal)"

    state_set "connect_permission_added" "true"

    echo ""
    warn "MANUAL STEP REQUIRED — Add Lambda to Connect allow-list:"
    warn "  1. AWS Console → Amazon Connect → Your instance"
    warn "  2. Left panel → AWS Lambda"
    warn "  3. Click 'Add Lambda function'"
    warn "  4. Select: ${FUNCTION_NAME}"
    warn "     (The :prod alias inherits this permission automatically)"
}

# =============================================================================
#  Summary
# =============================================================================
print_deploy_summary() {
    local version
    version=$(state_get "lambda_version" "?")
    local validate_version
    validate_version=$(state_get "validate_lambda_version" "?")
    local validate_alias_arn
    validate_alias_arn=$(state_get "validate_lambda_alias_arn" "(not yet deployed)")

    echo ""
    echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}${GREEN}  ARIA DTMF Lambdas — Deploy Complete${NC}"
    echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  ${BOLD}Decrypt Lambda ARN (prod alias):${NC}"
    echo -e "    ${CYAN}${LAMBDA_ALIAS_ARN}${NC}"
    echo -e "    Version: ${version}"
    echo ""
    echo -e "  ${BOLD}Validate Lambda ARN (prod alias):${NC}"
    echo -e "    ${CYAN}${validate_alias_arn}${NC}"
    echo -e "    Version: ${validate_version}"
    echo ""
    echo -e "  ${BOLD}Lambda Layer:${NC}"
    echo -e "    ${LAYER_ARN}"
    echo ""
    echo -e "  ${BOLD}IAM Roles:${NC}"
    echo -e "    arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
    echo -e "    arn:aws:iam::${ACCOUNT_ID}:role/${VALIDATE_ROLE_NAME}"
    echo ""
    echo -e "  ${BOLD}Environment variables (decrypt):${NC}"
    echo -e "    PRIVATE_KEY_SECRET_ARN = ${PRIVATE_KEY_SECRET_ARN}"
    echo -e "    CONNECT_KEY_ID         = ${CONNECT_KEY_ID}"
    echo -e "    CARD_BINS_TABLE        = ${CARD_BINS_TABLE}"
    echo -e "    CUSTOMER_CARDS_TABLE   = ${CUSTOMER_CARDS_TABLE}"
    echo ""
    echo -e "  ${BOLD}Environment variables (validate):${NC}"
    echo -e "    CARD_BINS_TABLE        = ${CARD_BINS_TABLE}"
    echo -e "    CUSTOMER_CARDS_TABLE   = ${CUSTOMER_CARDS_TABLE}"
    echo -e "    CUSTOMER_LAMBDA_NAME   = ${CUSTOMER_LAMBDA_NAME}"
    echo -e "    CONNECT_INSTANCE_ID    = ${CONNECT_INSTANCE_ID}"
    echo ""
    echo -e "  ${BOLD}DynamoDB tables:${NC}"
    echo -e "    ${CARD_BINS_TABLE}      (BIN → card type)"
    echo -e "    ${CUSTOMER_CARDS_TABLE}  (customer ownership fallback)"
    echo ""
    echo -e "  ${BOLD}State file:${NC}  ${STATE_FILE}"
    echo ""

    # Panel URL (if deployed)
    local panel_url
    panel_url=$(state_get "panel_url" "")
    if [[ -n "$panel_url" ]]; then
        echo -e "  ${BOLD}CCP Status Panel URL:${NC}"
        echo -e "    ${CYAN}${panel_url}${NC}"
        echo -e "    (CloudFront may take 5–15 min to propagate on first deploy)"
        echo ""
    else
        echo -e "  ${YELLOW}CCP Status Panel:${NC}  not deployed (no Connect instance URL provided)"
        echo ""
    fi
    echo -e "${BOLD}${YELLOW}  Required manual steps:${NC}"
    echo ""
    echo -e "  ${YELLOW}1. Add both Lambdas to Connect instance allow-list:${NC}"
    echo -e "     Connect console → <instance> → AWS Lambda → Add Lambda function"
    echo -e "     Select: ${FUNCTION_NAME}"
    echo -e "     Select: ${VALIDATE_FUNCTION_NAME}"
    echo ""
    echo -e "  ${YELLOW}2. In the ARIA-DTMF-SecureCollection flow:${NC}"
    echo -e "     Decrypt Lambda block  → Select: ${FUNCTION_NAME}:prod"
    echo -e "       Parameters: encryptedValue → System → Stored customer input"
    echo -e "                   purpose        → User Defined → collectionPurpose"
    echo -e "     Validate Lambda block → Select: ${VALIDATE_FUNCTION_NAME}:prod"
    echo -e "       Parameters: cardBin   → User Defined → dtmf_card_bin"
    echo -e "                   lastFour  → User Defined → dtmf_card_last_four"
    echo ""
    echo -e "  ${YELLOW}3. In every 'Store customer input' block:${NC}"
    echo -e "     Encrypt entry: ON"
    echo -e "     Key: ${CONNECT_KEY_ID}"
    echo ""
    echo -e "${BOLD}${GREEN}  Re-run 'deploy' after every Lambda code change.${NC}"
    echo -e "${BOLD}${GREEN}  The prod alias automatically tracks the latest version.${NC}"
    echo ""
}

# =============================================================================
#  Status command
# =============================================================================
cmd_status() {
    header "DTMF Lambda Deploy Status"
    echo ""
    for sf in "$STATE_FILE" "$KEY_STATE_FILE"; do
        if [[ -f "$sf" ]]; then
            echo -e "  ${BOLD}State file: ${sf}${NC}"
            python3 - "$sf" <<'PYEOF'
import sys, json
with open(sys.argv[1]) as f:
    data = json.load(f)
maxk = max((len(k) for k in data.keys()), default=10)
for k, v in data.items():
    print(f"    {k.ljust(maxk+2)} {v or '(not set)'}")
PYEOF
            echo ""
        else
            warn "State file not found: ${sf}"
        fi
    done
}

# =============================================================================
#  Deploy validate Lambda
#  Creates the IAM role, packages aria_dtmf_validate.py, creates/updates the
#  Lambda function, publishes a version, creates/updates the prod alias, and
#  grants Amazon Connect permission to invoke it.
# =============================================================================
VALIDATE_FUNCTION_NAME="${VALIDATE_FUNCTION_NAME:-aria-dtmf-validate}"
VALIDATE_ROLE_NAME="${VALIDATE_ROLE_NAME:-aria-lambda-dtmf-validate-role}"
CUSTOMER_LAMBDA_NAME="${CUSTOMER_LAMBDA_NAME:-aria-banking-mcp-customer-prod}"

# Status proxy Lambda + API Gateway
STATUS_PROXY_FUNCTION_NAME="${STATUS_PROXY_FUNCTION_NAME:-aria-dtmf-status-proxy}"
STATUS_PROXY_ROLE_NAME="${STATUS_PROXY_ROLE_NAME:-aria-lambda-dtmf-status-proxy-role}"
STATUS_PROXY_API_NAME="${STATUS_PROXY_API_NAME:-aria-dtmf-status-proxy-api}"

# DynamoDB sessions table + start-session Lambda
SESSIONS_TABLE_NAME="${SESSIONS_TABLE_NAME:-dtmf_active_sessions}"
START_SESSION_FUNCTION_NAME="${START_SESSION_FUNCTION_NAME:-aria-dtmf-start-session}"
START_SESSION_ROLE_NAME="${START_SESSION_ROLE_NAME:-aria-lambda-dtmf-start-session-role}"

# =============================================================================
#  DynamoDB — dtmf_active_sessions table
#  Stores the current active DTMF session so the launcher iframe and panel
#  popup can auto-discover contactId without requiring a URL parameter.
#
#  Schema:   session_id (S) — PK; always "ACTIVE" for the current session
#            contact_id (S) — Amazon Connect contact UUID
#            status (S)     — mirrors dtmf_status contact attribute
#            updated_at (S) — ISO-8601 timestamp
#            ttl (N)        — Unix epoch; DynamoDB TTL auto-expires after 1 h
# =============================================================================
deploy_sessions_table() {
    header "DynamoDB: ${SESSIONS_TABLE_NAME}"

    local TABLE_ARN="arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${SESSIONS_TABLE_NAME}"

    # Idempotent — skip if already exists
    local existing
    existing=$(aws dynamodb describe-table \
        --table-name "$SESSIONS_TABLE_NAME" \
        --region     "$REGION" \
        --query      "Table.TableName" --output text 2>/dev/null || echo "")

    if [[ -n "$existing" ]]; then
        ok "Table ${SESSIONS_TABLE_NAME} already exists — ensuring TTL is enabled"
    else
        step "Creating DynamoDB table ${SESSIONS_TABLE_NAME}..."
        aws dynamodb create-table \
            --table-name            "$SESSIONS_TABLE_NAME" \
            --attribute-definitions  "AttributeName=session_id,AttributeType=S" \
            --key-schema             "AttributeName=session_id,KeyType=HASH" \
            --billing-mode           PAY_PER_REQUEST \
            --region                 "$REGION" \
            --query                  "TableDescription.TableName" --output text > /dev/null

        step "Waiting for table to become ACTIVE..."
        aws dynamodb wait table-exists \
            --table-name "$SESSIONS_TABLE_NAME" \
            --region     "$REGION"
        ok "Table created: ${SESSIONS_TABLE_NAME}"
    fi

    # Enable TTL (idempotent)
    aws dynamodb update-time-to-live \
        --table-name     "$SESSIONS_TABLE_NAME" \
        --time-to-live-specification "Enabled=true,AttributeName=ttl" \
        --region         "$REGION" > /dev/null 2>&1 || true
    ok "TTL enabled on 'ttl' attribute"

    state_set "sessions_table_name" "$SESSIONS_TABLE_NAME"
}

# =============================================================================
#  Start-Session Lambda
#  Called from Connect flow at the start of each secure DTMF capture.
#  Writes ACTIVE session to DynamoDB + sets dtmf_status=awaiting_trigger.
# =============================================================================
deploy_start_session_lambda() {
    header "Lambda: ${START_SESSION_FUNCTION_NAME}"

    local start_source="${LAMBDA_DIR}/aria_dtmf_start_session.py"
    [[ -f "$start_source" ]] || die "Start-session Lambda source not found: ${start_source}"

    # ── IAM Role ──────────────────────────────────────────────────────────────
    local start_role_arn="arn:aws:iam::${ACCOUNT_ID}:role/${START_SESSION_ROLE_NAME}"

    if [[ -n "$(iam_role_exists "$START_SESSION_ROLE_NAME")" ]]; then
        ok "Role ${START_SESSION_ROLE_NAME} already exists — updating policies"
    else
        step "Creating IAM role ${START_SESSION_ROLE_NAME}..."
        aws iam create-role \
            --role-name "$START_SESSION_ROLE_NAME" \
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
            --role-name "$START_SESSION_ROLE_NAME" \
            --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"

        ok "Role created and AWSLambdaBasicExecutionRole attached"
        step "Waiting 15s for IAM propagation..."
        sleep 15
    fi

    # connect:UpdateContactAttributes
    step "Ensuring connect:UpdateContactAttributes policy on ${START_SESSION_ROLE_NAME}..."
    aws iam put-role-policy \
        --role-name "$START_SESSION_ROLE_NAME" \
        --policy-name "StartSessionConnectUpdate" \
        --policy-document "{
            \"Version\": \"2012-10-17\",
            \"Statement\": [{
                \"Effect\": \"Allow\",
                \"Action\": \"connect:UpdateContactAttributes\",
                \"Resource\": \"*\"
            }]
        }"
    ok "connect:UpdateContactAttributes policy in place"

    # dynamodb:PutItem on sessions table
    local SESSIONS_ARN="arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${SESSIONS_TABLE_NAME}"
    step "Ensuring dynamodb:PutItem policy on ${START_SESSION_ROLE_NAME}..."
    aws iam put-role-policy \
        --role-name "$START_SESSION_ROLE_NAME" \
        --policy-name "StartSessionDynamoDBWrite" \
        --policy-document "{
            \"Version\": \"2012-10-17\",
            \"Statement\": [{
                \"Effect\": \"Allow\",
                \"Action\": [\"dynamodb:PutItem\"],
                \"Resource\": \"${SESSIONS_ARN}\"
            }]
        }"
    ok "dynamodb:PutItem policy in place"

    # ── Package Lambda ────────────────────────────────────────────────────────
    local zip_path="/tmp/${START_SESSION_FUNCTION_NAME}.zip"
    step "Packaging ${START_SESSION_FUNCTION_NAME}..."
    (cd "$LAMBDA_DIR" && zip -q "$zip_path" "aria_dtmf_start_session.py")

    local start_env
    start_env=$(printf '{"Variables":{"CONNECT_INSTANCE_ID":"%s","SESSIONS_TABLE_NAME":"%s"}}' \
        "${CONNECT_INSTANCE_ID}" "${SESSIONS_TABLE_NAME}")

    # ── Create or update Lambda ───────────────────────────────────────────────
    if aws lambda get-function --function-name "$START_SESSION_FUNCTION_NAME" --region "$REGION" > /dev/null 2>&1; then
        step "Updating Lambda ${START_SESSION_FUNCTION_NAME}..."
        aws lambda update-function-code \
            --function-name "$START_SESSION_FUNCTION_NAME" \
            --zip-file       "fileb://${zip_path}" \
            --region         "$REGION" \
            --query          "FunctionName" --output text > /dev/null
        aws lambda wait function-updated \
            --function-name "$START_SESSION_FUNCTION_NAME" \
            --region        "$REGION" 2>/dev/null || true
        aws lambda update-function-configuration \
            --function-name "$START_SESSION_FUNCTION_NAME" \
            --environment    "$start_env" \
            --timeout        10 \
            --memory-size    128 \
            --region         "$REGION" \
            --query          "FunctionName" --output text > /dev/null
        aws lambda wait function-updated \
            --function-name "$START_SESSION_FUNCTION_NAME" \
            --region        "$REGION" 2>/dev/null || true
        ok "Lambda updated"
    else
        step "Creating Lambda ${START_SESSION_FUNCTION_NAME}..."
        aws lambda create-function \
            --function-name  "$START_SESSION_FUNCTION_NAME" \
            --runtime        "$RUNTIME" \
            --role           "$start_role_arn" \
            --handler        "aria_dtmf_start_session.handler" \
            --zip-file       "fileb://${zip_path}" \
            --timeout        10 \
            --memory-size    128 \
            --environment    "$start_env" \
            --description    "DTMF session start — writes DynamoDB ACTIVE record + sets dtmf_status" \
            --region         "$REGION" \
            --query          "FunctionName" --output text > /dev/null
        aws lambda wait function-active \
            --function-name "$START_SESSION_FUNCTION_NAME" \
            --region        "$REGION" 2>/dev/null || true
        ok "Lambda created"
    fi

    local START_SESSION_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${START_SESSION_FUNCTION_NAME}"
    state_set "start_session_lambda_arn" "$START_SESSION_ARN"
    rm -f "$zip_path"

    # ── Connect resource-based policy ─────────────────────────────────────────
    if [[ -n "$CONNECT_INSTANCE_ID" ]]; then
        aws lambda add-permission \
            --function-name  "$START_SESSION_FUNCTION_NAME" \
            --statement-id   "AllowConnectInvokeStartSession" \
            --action         "lambda:InvokeFunction" \
            --principal      "connect.amazonaws.com" \
            --source-account "$ACCOUNT_ID" \
            --region         "$REGION" 2>/dev/null && \
        ok "Connect can invoke ${START_SESSION_FUNCTION_NAME}" || \
        warn "AllowConnectInvokeStartSession policy already set (non-fatal)"
    fi

    echo ""
    warn "MANUAL STEP REQUIRED — Add Lambda to Connect allow-list AND flow:"
    warn "  1. AWS Console → Amazon Connect → Your instance → AWS Lambda"
    warn "     Add Lambda function: ${START_SESSION_FUNCTION_NAME}"
    warn "  2. In your secure capture Contact Flow, add a Invoke AWS Lambda block"
    warn "     BEFORE the 'Store customer input' block and select:"
    warn "     ${START_SESSION_FUNCTION_NAME}"
}

deploy_validate_lambda() {
    header "Lambda: ${VALIDATE_FUNCTION_NAME}"

    local validate_source="${LAMBDA_DIR}/aria_dtmf_validate.py"
    [[ -f "$validate_source" ]] || die "Validate Lambda source not found: ${validate_source}"

    # ── IAM Role ──────────────────────────────────────────────────────────────
    local validate_role_arn="arn:aws:iam::${ACCOUNT_ID}:role/${VALIDATE_ROLE_NAME}"

    if [[ -n "$(iam_role_exists "$VALIDATE_ROLE_NAME")" ]]; then
        ok "Role ${VALIDATE_ROLE_NAME} already exists — updating policies"
    else
        step "Creating IAM role ${VALIDATE_ROLE_NAME}..."
        aws iam create-role \
            --role-name "$VALIDATE_ROLE_NAME" \
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
            --role-name "$VALIDATE_ROLE_NAME" \
            --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"

        ok "Role created and AWSLambdaBasicExecutionRole attached"
        step "Waiting 15s for IAM propagation..."
        sleep 15
    fi

    # DynamoDB read — BIN lookup + ownership fallback
    local CARD_BINS_ARN="arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${CARD_BINS_TABLE}"
    local CUSTOMER_CARDS_ARN="arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${CUSTOMER_CARDS_TABLE}"
    step "Ensuring DynamoDB read policy on ${VALIDATE_ROLE_NAME}..."
    aws iam put-role-policy \
        --role-name "$VALIDATE_ROLE_NAME" \
        --policy-name "ValidateDynamoDBRead" \
        --policy-document "{
            \"Version\": \"2012-10-17\",
            \"Statement\": [{
                \"Sid\":    \"ValidateReadDynamoDB\",
                \"Effect\": \"Allow\",
                \"Action\": [\"dynamodb:GetItem\",\"dynamodb:Query\",\"dynamodb:Scan\"],
                \"Resource\": [\"${CARD_BINS_ARN}\",\"${CUSTOMER_CARDS_ARN}\"]
            }]
        }"
    ok "DynamoDB read policy in place"

    # connect:UpdateContactAttributes — validate Lambda pushes status to agent CCP
    step "Ensuring connect:UpdateContactAttributes policy on ${VALIDATE_ROLE_NAME}..."
    aws iam put-role-policy \
        --role-name "$VALIDATE_ROLE_NAME" \
        --policy-name "ValidateConnectUpdateAttributes" \
        --policy-document "{
            \"Version\": \"2012-10-17\",
            \"Statement\": [{
                \"Sid\":    \"ConnectUpdateAttributes\",
                \"Effect\": \"Allow\",
                \"Action\": \"connect:UpdateContactAttributes\",
                \"Resource\": \"*\"
            }]
        }"
    ok "connect:UpdateContactAttributes policy in place"

    # dynamodb:PutItem / UpdateItem / DeleteItem on sessions table (status sync)
    local SESSIONS_ARN_V="arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${SESSIONS_TABLE_NAME}"
    step "Ensuring DynamoDB session write policy on ${VALIDATE_ROLE_NAME}..."
    aws iam put-role-policy \
        --role-name "$VALIDATE_ROLE_NAME" \
        --policy-name "ValidateDTMFSessionWrite" \
        --policy-document "{
            \"Version\": \"2012-10-17\",
            \"Statement\": [{
                \"Sid\":    \"ValidateWriteSession\",
                \"Effect\": \"Allow\",
                \"Action\": [\"dynamodb:PutItem\",\"dynamodb:UpdateItem\",\"dynamodb:DeleteItem\"],
                \"Resource\": \"${SESSIONS_ARN_V}\"
            }]
        }"
    ok "DynamoDB session write policy in place"

    # lambda:InvokeFunction on the customer Lambda (ownership check)
    local CUSTOMER_LAMBDA_ARN
    CUSTOMER_LAMBDA_ARN=$(aws lambda get-function \
        --function-name "$CUSTOMER_LAMBDA_NAME" \
        --region "$REGION" \
        --query "Configuration.FunctionArn" \
        --output text 2>/dev/null || echo "")

    if [[ -z "$CUSTOMER_LAMBDA_ARN" ]]; then
        warn "Lambda '${CUSTOMER_LAMBDA_NAME}' not found — using wildcard ARN in policy."
        warn "Deploy aria-banking-mcp-customer-prod first for least-privilege."
        CUSTOMER_LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${CUSTOMER_LAMBDA_NAME}"
    fi

    step "Ensuring lambda:InvokeFunction policy for customer Lambda..."
    aws iam put-role-policy \
        --role-name "$VALIDATE_ROLE_NAME" \
        --policy-name "ValidateInvokeCustomerLambda" \
        --policy-document "{
            \"Version\": \"2012-10-17\",
            \"Statement\": [{
                \"Sid\":    \"InvokeCustomerLambda\",
                \"Effect\": \"Allow\",
                \"Action\": \"lambda:InvokeFunction\",
                \"Resource\": \"${CUSTOMER_LAMBDA_ARN}\"
            }]
        }"
    ok "lambda:InvokeFunction policy in place → ${CUSTOMER_LAMBDA_NAME}"

    # ── Package ───────────────────────────────────────────────────────────────
    local zip_path="/tmp/${VALIDATE_FUNCTION_NAME}.zip"
    step "Packaging ${VALIDATE_FUNCTION_NAME}..."
    (cd "$LAMBDA_DIR" && zip -q "$zip_path" "aria_dtmf_validate.py")

    local validate_env
    validate_env="Variables={CARD_BINS_TABLE=${CARD_BINS_TABLE},CUSTOMER_CARDS_TABLE=${CUSTOMER_CARDS_TABLE},CUSTOMER_LAMBDA_NAME=${CUSTOMER_LAMBDA_NAME},CONNECT_INSTANCE_ID=${CONNECT_INSTANCE_ID},SKIP_OWNERSHIP_IF_UNAUTH=true,SESSIONS_TABLE_NAME=${SESSIONS_TABLE_NAME}}"

    # ── Create or update Lambda ───────────────────────────────────────────────
    if [[ -n "$(lambda_exists "$VALIDATE_FUNCTION_NAME" "$REGION")" ]]; then
        step "Updating code for existing Lambda ${VALIDATE_FUNCTION_NAME}..."
        aws lambda update-function-code \
            --function-name "$VALIDATE_FUNCTION_NAME" \
            --zip-file      "fileb://${zip_path}" \
            --region        "$REGION" \
            --query         "FunctionName" --output text > /dev/null

        step "Waiting for code update..."
        aws lambda wait function-updated \
            --function-name "$VALIDATE_FUNCTION_NAME" \
            --region        "$REGION" 2>/dev/null || true

        step "Updating configuration (env vars, layers, timeout)..."
        aws lambda update-function-configuration \
            --function-name "$VALIDATE_FUNCTION_NAME" \
            --environment   "$validate_env" \
            --layers        "$LAYER_ARN" \
            --timeout       15 \
            --memory-size   256 \
            --region        "$REGION" \
            --query         "FunctionName" --output text > /dev/null

        step "Waiting for configuration update..."
        aws lambda wait function-updated \
            --function-name "$VALIDATE_FUNCTION_NAME" \
            --region        "$REGION" 2>/dev/null || true

        ok "Lambda code and config updated"
    else
        step "Creating Lambda ${VALIDATE_FUNCTION_NAME}..."
        aws lambda create-function \
            --function-name "$VALIDATE_FUNCTION_NAME" \
            --runtime        "$RUNTIME" \
            --role           "$validate_role_arn" \
            --handler        "aria_dtmf_validate.handler" \
            --zip-file       "fileb://${zip_path}" \
            --timeout        15 \
            --memory-size    256 \
            --environment    "$validate_env" \
            --layers         "$LAYER_ARN" \
            --description    "Amazon Connect DTMF card validation — Meridian Bank" \
            --region         "$REGION" \
            --query          "FunctionName" --output text > /dev/null

        step "Waiting for Lambda to become active..."
        aws lambda wait function-active \
            --function-name "$VALIDATE_FUNCTION_NAME" \
            --region        "$REGION" 2>/dev/null || true

        ok "Lambda created"
    fi

    # ── Publish version + alias ───────────────────────────────────────────────
    step "Publishing new version..."
    local validate_version
    validate_version=$(aws lambda publish-version \
        --function-name "$VALIDATE_FUNCTION_NAME" \
        --description   "Deployed $(date -u '+%Y-%m-%dT%H:%M:%SZ') — layer:${LAYER_ARN##*:}" \
        --region        "$REGION" \
        --query         "Version" --output text)
    ok "Published version: ${validate_version}"

    local validate_arn="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${VALIDATE_FUNCTION_NAME}"
    local validate_alias_arn="${validate_arn}:${ALIAS_NAME}"

    if [[ -n "$(alias_exists "$VALIDATE_FUNCTION_NAME" "$ALIAS_NAME" "$REGION")" ]]; then
        step "Updating '${ALIAS_NAME}' alias → version ${validate_version}..."
        aws lambda update-alias \
            --function-name    "$VALIDATE_FUNCTION_NAME" \
            --name             "$ALIAS_NAME" \
            --function-version "$validate_version" \
            --description      "Production — deployed $(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
            --region           "$REGION" \
            --query            "AliasArn" --output text > /dev/null
    else
        step "Creating '${ALIAS_NAME}' alias → version ${validate_version}..."
        aws lambda create-alias \
            --function-name    "$VALIDATE_FUNCTION_NAME" \
            --name             "$ALIAS_NAME" \
            --function-version "$validate_version" \
            --description      "Production alias" \
            --region           "$REGION" \
            --query            "AliasArn" --output text > /dev/null
    fi
    ok "prod alias ARN: ${validate_alias_arn}"

    state_set "validate_lambda_arn"       "$validate_arn"
    state_set "validate_lambda_alias_arn" "$validate_alias_arn"
    state_set "validate_lambda_version"   "$validate_version"

    # ── Connect resource-based policy ─────────────────────────────────────────
    if [[ -n "$CONNECT_INSTANCE_ID" ]]; then
        step "Adding resource-based policy on ${validate_alias_arn}..."
        aws lambda add-permission \
            --function-name  "$validate_alias_arn" \
            --statement-id   "AllowConnectInvoke" \
            --action         "lambda:InvokeFunction" \
            --principal      "connect.amazonaws.com" \
            --source-account "$ACCOUNT_ID" \
            --region         "$REGION" 2>/dev/null && \
        ok "Connect can invoke ${validate_alias_arn}" || \
        warn "AllowConnectInvoke policy already set on alias (non-fatal)"

        aws lambda add-permission \
            --function-name  "$validate_arn" \
            --statement-id   "AllowConnectInvokeUnqualified" \
            --action         "lambda:InvokeFunction" \
            --principal      "connect.amazonaws.com" \
            --source-account "$ACCOUNT_ID" \
            --region         "$REGION" 2>/dev/null && \
        ok "Connect can invoke ${validate_arn} (unqualified)" || \
        warn "AllowConnectInvokeUnqualified policy already set (non-fatal)"
    else
        warn "No CONNECT_INSTANCE_ID — skipping Connect resource-based policy for validate Lambda."
    fi

    rm -f "$zip_path"

    echo ""
    warn "MANUAL STEP REQUIRED — Add Lambda to Connect allow-list:"
    warn "  1. AWS Console → Amazon Connect → Your instance"
    warn "  2. Left panel → AWS Lambda"
    warn "  3. Click 'Add Lambda function'"
    warn "  4. Select: ${VALIDATE_FUNCTION_NAME}"
}

# =============================================================================
#  Status Proxy Lambda + HTTP API Gateway
#  Creates aria-dtmf-status-proxy Lambda with connect:GetContactAttributes
#  permission and exposes it via a minimal HTTP API Gateway (v2).
#  The panel polls GET /dtmf-status?contactId=<id> every 2 s.
# =============================================================================
deploy_status_proxy() {
    header "Status Proxy Lambda + API Gateway: ${STATUS_PROXY_FUNCTION_NAME}"

    # Ensure sessions table exists before creating Lambda policies that reference it
    deploy_sessions_table

    local proxy_source="${LAMBDA_DIR}/aria_dtmf_status_proxy.py"
    [[ -f "$proxy_source" ]] || die "Status proxy Lambda source not found: ${proxy_source}"

    # ── IAM Role ──────────────────────────────────────────────────────────────
    local proxy_role_arn="arn:aws:iam::${ACCOUNT_ID}:role/${STATUS_PROXY_ROLE_NAME}"

    if [[ -n "$(iam_role_exists "$STATUS_PROXY_ROLE_NAME")" ]]; then
        ok "Role ${STATUS_PROXY_ROLE_NAME} already exists — updating policies"
    else
        step "Creating IAM role ${STATUS_PROXY_ROLE_NAME}..."
        aws iam create-role \
            --role-name "$STATUS_PROXY_ROLE_NAME" \
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
            --role-name "$STATUS_PROXY_ROLE_NAME" \
            --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
        ok "Role created and AWSLambdaBasicExecutionRole attached"
        step "Waiting 15s for IAM propagation..."
        sleep 15
    fi

    # connect:GetContactAttributes — read DTMF status attributes for the panel
    step "Ensuring connect:GetContactAttributes policy on ${STATUS_PROXY_ROLE_NAME}..."
    aws iam put-role-policy \
        --role-name "$STATUS_PROXY_ROLE_NAME" \
        --policy-name "ProxyConnectGetAttributes" \
        --policy-document "{
            \"Version\": \"2012-10-17\",
            \"Statement\": [{
                \"Sid\":    \"ConnectGetContactAttributes\",
                \"Effect\": \"Allow\",
                \"Action\": \"connect:GetContactAttributes\",
                \"Resource\": \"*\"
            }]
        }"
    ok "connect:GetContactAttributes policy in place"

    # dynamodb:GetItem on sessions table — for /dtmf-active route
    local SESSIONS_ARN_P="arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${SESSIONS_TABLE_NAME}"
    step "Ensuring DynamoDB GetItem policy on ${STATUS_PROXY_ROLE_NAME}..."
    aws iam put-role-policy \
        --role-name "$STATUS_PROXY_ROLE_NAME" \
        --policy-name "ProxyDynamoDBGetSession" \
        --policy-document "{
            \"Version\": \"2012-10-17\",
            \"Statement\": [{
                \"Effect\": \"Allow\",
                \"Action\": [\"dynamodb:GetItem\"],
                \"Resource\": \"${SESSIONS_ARN_P}\"
            }]
        }"
    ok "DynamoDB GetItem policy in place"

    # ── Package Lambda ────────────────────────────────────────────────────────
    local proxy_zip="/tmp/aria-dtmf-status-proxy-$(date +%s).zip"
    step "Packaging ${STATUS_PROXY_FUNCTION_NAME}..."
    (
        tmp_dir=$(mktemp -d)
        cp "$proxy_source" "${tmp_dir}/aria_dtmf_status_proxy.py"
        cd "$tmp_dir"
        zip -q "$proxy_zip" aria_dtmf_status_proxy.py
        rm -rf "$tmp_dir"
    )
    ok "Lambda packaged: ${proxy_zip}"

    local proxy_env
    proxy_env=$(printf '{"Variables":{"CONNECT_INSTANCE_ID":"%s","SESSIONS_TABLE_NAME":"%s"}}' \
        "${CONNECT_INSTANCE_ID}" "${SESSIONS_TABLE_NAME}")

    # ── Create or Update Lambda ───────────────────────────────────────────────
    if aws lambda get-function --function-name "$STATUS_PROXY_FUNCTION_NAME" --region "$REGION" > /dev/null 2>&1; then
        step "Updating Lambda ${STATUS_PROXY_FUNCTION_NAME}..."
        aws lambda update-function-code \
            --function-name "$STATUS_PROXY_FUNCTION_NAME" \
            --zip-file       "fileb://${proxy_zip}" \
            --region         "$REGION" \
            --query          "FunctionName" --output text > /dev/null
        aws lambda wait function-updated \
            --function-name "$STATUS_PROXY_FUNCTION_NAME" \
            --region        "$REGION" 2>/dev/null || true
        aws lambda update-function-configuration \
            --function-name "$STATUS_PROXY_FUNCTION_NAME" \
            --environment    "$proxy_env" \
            --timeout        10 \
            --memory-size    128 \
            --region         "$REGION" \
            --query          "FunctionName" --output text > /dev/null
        aws lambda wait function-updated \
            --function-name "$STATUS_PROXY_FUNCTION_NAME" \
            --region        "$REGION" 2>/dev/null || true
        ok "Lambda updated"
    else
        step "Creating Lambda ${STATUS_PROXY_FUNCTION_NAME}..."
        aws lambda create-function \
            --function-name  "$STATUS_PROXY_FUNCTION_NAME" \
            --runtime        "$RUNTIME" \
            --role           "$proxy_role_arn" \
            --handler        "aria_dtmf_status_proxy.handler" \
            --zip-file       "fileb://${proxy_zip}" \
            --timeout        10 \
            --memory-size    128 \
            --environment    "$proxy_env" \
            --description    "DTMF status proxy — reads contact attributes for CCP panel" \
            --region         "$REGION" \
            --query          "FunctionName" --output text > /dev/null
        aws lambda wait function-active \
            --function-name "$STATUS_PROXY_FUNCTION_NAME" \
            --region        "$REGION" 2>/dev/null || true
        ok "Lambda created"
    fi

    local PROXY_LAMBDA_ARN
    PROXY_LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${STATUS_PROXY_FUNCTION_NAME}"
    state_set "status_proxy_lambda_arn" "$PROXY_LAMBDA_ARN"
    rm -f "$proxy_zip"

    # ── HTTP API Gateway (v2) ─────────────────────────────────────────────────
    local PROXY_API_ID
    PROXY_API_ID=$(state_get "status_proxy_api_id" "")

    if [[ -z "$PROXY_API_ID" ]]; then
        step "Creating HTTP API Gateway ${STATUS_PROXY_API_NAME}..."
        PROXY_API_ID=$(aws apigatewayv2 create-api \
            --name            "$STATUS_PROXY_API_NAME" \
            --protocol-type   HTTP \
            --cors-configuration '{"AllowOrigins":["*"],"AllowMethods":["GET","OPTIONS"],"AllowHeaders":["Content-Type"]}' \
            --region          "$REGION" \
            --query           "ApiId" --output text)
        ok "API created: ${PROXY_API_ID}"
        state_set "status_proxy_api_id" "$PROXY_API_ID"
    else
        ok "Existing API Gateway: ${PROXY_API_ID}"
    fi

    # Integration
    local INTEGRATION_ID
    INTEGRATION_ID=$(aws apigatewayv2 get-integrations \
        --api-id  "$PROXY_API_ID" \
        --region  "$REGION" \
        --query   "Items[?IntegrationUri=='${PROXY_LAMBDA_ARN}'].IntegrationId | [0]" \
        --output  text 2>/dev/null || true)

    if [[ -z "$INTEGRATION_ID" || "$INTEGRATION_ID" == "None" ]]; then
        step "Creating Lambda integration..."
        INTEGRATION_ID=$(aws apigatewayv2 create-integration \
            --api-id                "$PROXY_API_ID" \
            --integration-type      AWS_PROXY \
            --integration-uri       "$PROXY_LAMBDA_ARN" \
            --payload-format-version "2.0" \
            --region                "$REGION" \
            --query                 "IntegrationId" --output text)
        ok "Integration created: ${INTEGRATION_ID}"
    else
        ok "Existing integration: ${INTEGRATION_ID}"
    fi

    # Route: GET /dtmf-status
    local ROUTE_ID
    ROUTE_ID=$(aws apigatewayv2 get-routes \
        --api-id  "$PROXY_API_ID" \
        --region  "$REGION" \
        --query   "Items[?RouteKey=='GET /dtmf-status'].RouteId | [0]" \
        --output  text 2>/dev/null || true)

    if [[ -z "$ROUTE_ID" || "$ROUTE_ID" == "None" ]]; then
        step "Creating GET /dtmf-status route..."
        aws apigatewayv2 create-route \
            --api-id    "$PROXY_API_ID" \
            --route-key "GET /dtmf-status" \
            --target    "integrations/${INTEGRATION_ID}" \
            --region    "$REGION" > /dev/null
        ok "Route created"
    else
        ok "Existing route: ${ROUTE_ID}"
    fi

    # Route: GET /dtmf-active  (DynamoDB session lookup for auto-discovery)
    local ACTIVE_ROUTE_ID
    ACTIVE_ROUTE_ID=$(aws apigatewayv2 get-routes \
        --api-id  "$PROXY_API_ID" \
        --region  "$REGION" \
        --query   "Items[?RouteKey=='GET /dtmf-active'].RouteId | [0]" \
        --output  text 2>/dev/null || true)

    if [[ -z "$ACTIVE_ROUTE_ID" || "$ACTIVE_ROUTE_ID" == "None" ]]; then
        step "Creating GET /dtmf-active route..."
        aws apigatewayv2 create-route \
            --api-id    "$PROXY_API_ID" \
            --route-key "GET /dtmf-active" \
            --target    "integrations/${INTEGRATION_ID}" \
            --region    "$REGION" > /dev/null
        ok "Route /dtmf-active created"
    else
        ok "Existing /dtmf-active route: ${ACTIVE_ROUTE_ID}"
    fi

    # \$default stage with auto-deploy
    local STAGE_NAME
    STAGE_NAME=$(aws apigatewayv2 get-stage \
        --api-id    "$PROXY_API_ID" \
        --stage-name '$default' \
        --region    "$REGION" \
        --query     "StageName" --output text 2>/dev/null || true)

    if [[ -z "$STAGE_NAME" || "$STAGE_NAME" == "None" ]]; then
        step "Creating \$default stage with auto-deploy..."
        aws apigatewayv2 create-stage \
            --api-id     "$PROXY_API_ID" \
            --stage-name '$default' \
            --auto-deploy \
            --region     "$REGION" > /dev/null
        ok "Stage created"
    else
        ok "Stage already exists"
    fi

    # Lambda invoke permission for API Gateway
    aws lambda add-permission \
        --function-name  "$STATUS_PROXY_FUNCTION_NAME" \
        --statement-id   "apigateway-invoke-status-proxy" \
        --action         "lambda:InvokeFunction" \
        --principal      "apigateway.amazonaws.com" \
        --source-arn     "arn:aws:execute-api:${REGION}:${ACCOUNT_ID}:${PROXY_API_ID}/*" \
        --region         "$REGION" > /dev/null 2>&1 || ok "Invoke permission already exists"

    local PROXY_API_URL="https://${PROXY_API_ID}.execute-api.${REGION}.amazonaws.com/dtmf-status"
    state_set "status_proxy_api_url" "$PROXY_API_URL"
    ok "Status proxy URL: ${PROXY_API_URL}"
}

# =============================================================================
#  Resolve CCP Status Panel configuration (interactive prompts)
#  Called before cmd_deploy_panel to ensure all required values are set.
# =============================================================================
resolve_panel_config() {
    header "Resolving CCP Status Panel configuration"

    # Read from state file if not already set
    if [[ -z "$CONNECT_INSTANCE_URL" ]]; then
        CONNECT_INSTANCE_URL=$(state_get "connect_instance_url" "")
    fi
    if [[ -z "$CONNECT_INSTANCE_ID" ]]; then
        CONNECT_INSTANCE_ID=$(key_state_get "connect_instance_id" "")
        [[ -z "$CONNECT_INSTANCE_ID" ]] && CONNECT_INSTANCE_ID=$(state_get "connect_instance_id" "")
    fi

    # Prompt for anything still missing
    if [[ -z "$CONNECT_INSTANCE_URL" ]]; then
        ask CONNECT_INSTANCE_URL \
            "Amazon Connect instance URL (e.g. https://meridian-bank.my.connect.aws)" ""
        if [[ -z "$CONNECT_INSTANCE_URL" ]]; then
            warn "No Connect instance URL — CCP Status Panel deploy will be skipped."
            warn "Re-run:  $0 deploy-panel --connect-instance-url https://<your-instance>.my.connect.aws"
        fi
    fi

    if [[ -z "$CONNECT_INSTANCE_ID" ]]; then
        ask CONNECT_INSTANCE_ID \
            "Amazon Connect Instance ID (UUID — used for Approved Origins instructions; press Enter to skip)" ""
        if [[ -z "$CONNECT_INSTANCE_ID" ]]; then
            warn "No instance ID — Approved Origins reminder in summary will be generic"
        fi
    fi

    # Persist to STATE_FILE for subsequent runs
    [[ -n "$CONNECT_INSTANCE_URL" ]] && state_set "connect_instance_url" "$CONNECT_INSTANCE_URL"
    [[ -n "$CONNECT_INSTANCE_ID"  ]] && state_set "connect_instance_id"  "$CONNECT_INSTANCE_ID"

    [[ -n "$CONNECT_INSTANCE_URL" ]] && ok "Instance URL:  ${CONNECT_INSTANCE_URL}" || warn "Instance URL:  (not set — panel deploy will be skipped)"
    [[ -n "$CONNECT_INSTANCE_ID" ]] && ok "Instance ID:   ${CONNECT_INSTANCE_ID}"  || warn "Instance ID:   (not set)"
    ok "Region:        ${REGION}"
}

# =============================================================================
#  CCP Status Panel — S3 + CloudFront deploy
# =============================================================================
cmd_deploy_panel() {
    # resolve_panel_config() must be called before this function when running
    # deploy-panel standalone. When called from the main deploy flow,
    # resolve_config() has already set CONNECT_INSTANCE_URL.
    if [[ -z "$CONNECT_INSTANCE_URL" ]]; then
        warn "No Connect instance URL — skipping CCP Status Panel deploy."
        warn "Re-run:  $0 deploy-panel --connect-instance-url https://<your-instance>.my.connect.aws"
        return 0
    fi

    header "CCP Status Panel — S3 + CloudFront Deploy"

    local PANEL_SOURCE
    PANEL_SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/client/dtmf-status-panel/index.html"
    [[ ! -f "$PANEL_SOURCE" ]] && die "Panel source not found: ${PANEL_SOURCE}"

    # Deploy the status proxy Lambda + API Gateway first so its URL is known
    if [[ -n "$CONNECT_INSTANCE_ID" ]]; then
        deploy_status_proxy
        deploy_start_session_lambda
    else
        warn "CONNECT_INSTANCE_ID not set — skipping status proxy, start-session Lambda."
        warn "Panel will be deployed with STATUS_PROXY_URL placeholder unchanged."
    fi
    local STATUS_PROXY_API_URL
    STATUS_PROXY_API_URL=$(state_get "status_proxy_api_url" "")

    local BUCKET_NAME="aria-dtmf-panel-${ACCOUNT_ID}"
    local OAC_NAME="aria-dtmf-panel-oac"
    local PATCHED_HTML="/tmp/dtmf-status-panel-patched.html"

    # ── Create S3 bucket (idempotent) ─────────────────────────────────────────
    header "S3 Bucket"
    if aws s3api head-bucket --bucket "$BUCKET_NAME" --region "$REGION" 2>/dev/null; then
        ok "Bucket already exists: ${BUCKET_NAME}"
    else
        step "Creating bucket ${BUCKET_NAME} in ${REGION} …"
        if [[ "$REGION" == "us-east-1" ]]; then
            aws s3api create-bucket \
                --bucket "$BUCKET_NAME" \
                --region "$REGION" >/dev/null
        else
            aws s3api create-bucket \
                --bucket "$BUCKET_NAME" \
                --region "$REGION" \
                --create-bucket-configuration LocationConstraint="$REGION" >/dev/null
        fi
        ok "Bucket created: ${BUCKET_NAME}"
    fi

    step "Blocking all public access on bucket …"
    aws s3api put-public-access-block \
        --bucket "$BUCKET_NAME" \
        --public-access-block-configuration \
            "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" \
        --region "$REGION"
    ok "Public access blocked"

    # ── Patch panel HTML with real URLs ──────────────────────────────────────
    header "Patching panel HTML"
    step "Replacing URL placeholders …"
    local STATUS_ACTIVE_URL="${STATUS_PROXY_API_URL/dtmf-status/dtmf-active}"
    sed \
        -e "s|https://your-api-id.execute-api.eu-west-2.amazonaws.com/dtmf-status|${STATUS_PROXY_API_URL}|g" \
        -e "s|https://your-api-id.execute-api.eu-west-2.amazonaws.com/dtmf-active|${STATUS_ACTIVE_URL}|g" \
        "$PANEL_SOURCE" > "$PATCHED_HTML"
    ok "Patched HTML written to ${PATCHED_HTML}"

    # ── Upload to S3 ─────────────────────────────────────────────────────────
    step "Uploading panel to s3://${BUCKET_NAME}/dtmf-panel/index.html …"
    aws s3 cp "$PATCHED_HTML" \
        "s3://${BUCKET_NAME}/dtmf-panel/index.html" \
        --content-type "text/html" \
        --cache-control "no-cache,no-store,must-revalidate" \
        --region "$REGION" >/dev/null
    ok "Panel uploaded"

    # ── Create / find CloudFront OAC ──────────────────────────────────────────
    header "CloudFront OAC"
    local OAC_ID
    OAC_ID=$(aws cloudfront list-origin-access-controls \
        --query "OriginAccessControlList.Items[?Name=='${OAC_NAME}'].Id | [0]" \
        --output text 2>/dev/null || true)

    if [[ -z "$OAC_ID" || "$OAC_ID" == "None" ]]; then
        step "Creating OAC ${OAC_NAME} …"
        OAC_ID=$(aws cloudfront create-origin-access-control \
            --origin-access-control-config \
                "Name=${OAC_NAME},Description=DTMF panel OAC,SigningProtocol=sigv4,SigningBehavior=always,OriginAccessControlOriginType=s3" \
            --query "OriginAccessControl.Id" --output text)
        ok "OAC created: ${OAC_ID}"
    else
        ok "Existing OAC found: ${OAC_ID}"
    fi

    # ── Create / find CloudFront distribution ─────────────────────────────────
    header "CloudFront Distribution"
    local DIST_ID DIST_DOMAIN
    local S3_ORIGIN_DOMAIN="${BUCKET_NAME}.s3.${REGION}.amazonaws.com"

    DIST_ID=$(aws cloudfront list-distributions \
        --query "DistributionList.Items[?Origins.Items[0].DomainName=='${S3_ORIGIN_DOMAIN}'].Id | [0]" \
        --output text 2>/dev/null || true)

    if [[ -z "$DIST_ID" || "$DIST_ID" == "None" ]]; then
        step "Creating CloudFront distribution for ${S3_ORIGIN_DOMAIN} …"
        local CALLER_REF="aria-dtmf-panel-$(date +%s)"
        DIST_ID=$(aws cloudfront create-distribution \
            --distribution-config "{
                \"CallerReference\": \"${CALLER_REF}\",
                \"Comment\": \"ARIA DTMF CCP Status Panel\",
                \"DefaultRootObject\": \"dtmf-panel/index.html\",
                \"Origins\": {
                    \"Quantity\": 1,
                    \"Items\": [{
                        \"Id\": \"dtmf-panel-s3\",
                        \"DomainName\": \"${S3_ORIGIN_DOMAIN}\",
                        \"OriginAccessControlId\": \"${OAC_ID}\",
                        \"S3OriginConfig\": { \"OriginAccessIdentity\": \"\" }
                    }]
                },
                \"DefaultCacheBehavior\": {
                    \"TargetOriginId\": \"dtmf-panel-s3\",
                    \"ViewerProtocolPolicy\": \"redirect-to-https\",
                    \"CachePolicyId\": \"4135ea2d-6df8-44a3-9df3-4b5a84be39ad\",
                    \"AllowedMethods\": {
                        \"Quantity\": 2,
                        \"Items\": [\"GET\", \"HEAD\"]
                    }
                },
                \"Enabled\": true
            }" \
            --query "Distribution.Id" --output text)
        ok "Distribution created: ${DIST_ID}"
    else
        ok "Existing distribution found: ${DIST_ID}"
    fi

    DIST_DOMAIN=$(aws cloudfront get-distribution \
        --id "$DIST_ID" \
        --query "Distribution.DomainName" --output text)

    # ── Apply S3 bucket policy for CloudFront OAC ─────────────────────────────
    header "S3 Bucket Policy"
    local DIST_ARN="arn:aws:cloudfront::${ACCOUNT_ID}:distribution/${DIST_ID}"
    step "Applying bucket policy (CloudFront OAC only) …"
    aws s3api put-bucket-policy \
        --bucket "$BUCKET_NAME" \
        --region "$REGION" \
        --policy "{
            \"Version\": \"2012-10-17\",
            \"Statement\": [{
                \"Sid\": \"AllowCloudFrontOAC\",
                \"Effect\": \"Allow\",
                \"Principal\": { \"Service\": \"cloudfront.amazonaws.com\" },
                \"Action\": \"s3:GetObject\",
                \"Resource\": \"arn:aws:s3:::${BUCKET_NAME}/*\",
                \"Condition\": {
                    \"StringEquals\": {
                        \"AWS:SourceArn\": \"${DIST_ARN}\"
                    }
                }
            }]
        }"
    ok "Bucket policy applied"

    # ── Deploy launcher iframe ────────────────────────────────────────────────
    header "Launcher iframe"
    local LAUNCHER_SOURCE
    LAUNCHER_SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/client/dtmf-launcher/index.html"
    local PATCHED_LAUNCHER="/tmp/dtmf-launcher-patched.html"

    if [[ -f "$LAUNCHER_SOURCE" ]]; then
        local ACTIVE_API_URL="${STATUS_PROXY_API_URL/dtmf-status/dtmf-active}"
        local PANEL_FULL_URL="https://${DIST_DOMAIN}/dtmf-panel/index.html"
        sed \
            -e "s|https://your-api-id.execute-api.eu-west-2.amazonaws.com/dtmf-active|${ACTIVE_API_URL}|g" \
            -e "s|https://your-cloudfront-domain.cloudfront.net/dtmf-panel/index.html|${PANEL_FULL_URL}|g" \
            "$LAUNCHER_SOURCE" > "$PATCHED_LAUNCHER"

        step "Uploading launcher to s3://${BUCKET_NAME}/dtmf-launcher/index.html …"
        aws s3 cp "$PATCHED_LAUNCHER" \
            "s3://${BUCKET_NAME}/dtmf-launcher/index.html" \
            --content-type "text/html" \
            --cache-control "no-cache,no-store,must-revalidate" \
            --region "$REGION" >/dev/null
        ok "Launcher uploaded"

        state_set "launcher_url" "https://${DIST_DOMAIN}/dtmf-launcher/index.html"
        rm -f "$PATCHED_LAUNCHER"
    else
        warn "Launcher source not found at ${LAUNCHER_SOURCE} — skipping launcher deploy"
    fi

    # ── Invalidate CloudFront cache (panel + launcher in one request) ─────────
    step "Invalidating CloudFront cache for panel and launcher …"
    local INVALIDATION_ID
    INVALIDATION_ID=$(aws cloudfront create-invalidation \
        --distribution-id "$DIST_ID" \
        --paths "/dtmf-panel/index.html" "/dtmf-launcher/index.html" \
        --query "Invalidation.Id" --output text)
    ok "Invalidation ${INVALIDATION_ID} submitted — propagates within ~60s"
    warn "Hard-refresh (Cmd+Shift+R / Ctrl+Shift+R) the popup panel after 60s if still showing old content."

    # ── Save state ────────────────────────────────────────────────────────────
    state_set "panel_bucket"         "$BUCKET_NAME"
    state_set "panel_oac_id"         "$OAC_ID"
    state_set "panel_dist_id"        "$DIST_ID"
    state_set "panel_dist_domain"    "$DIST_DOMAIN"
    state_set "panel_url"            "https://${DIST_DOMAIN}/dtmf-panel/index.html"
    state_set "connect_instance_url" "$CONNECT_INSTANCE_URL"

    # ── Print summary ─────────────────────────────────────────────────────────
    local panel_full_url="https://${DIST_DOMAIN}/dtmf-panel/index.html"
    local launcher_full_url="https://${DIST_DOMAIN}/dtmf-launcher/index.html"
    echo ""
    echo -e "${BOLD}${GREEN}══════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}${GREEN}  CCP Status Panel Deployed${NC}"
    echo -e "${BOLD}${GREEN}══════════════════════════════════════════════════════${NC}"
    echo ""
    echo "  S3 Bucket:              s3://${BUCKET_NAME}/dtmf-panel/index.html"
    echo "  CloudFront Dist:        ${DIST_ID}"
    echo "  CloudFront Domain:      ${DIST_DOMAIN}"
    echo "  Status proxy Lambda:    ${STATUS_PROXY_FUNCTION_NAME}"
    echo "  Status proxy URL:       ${STATUS_PROXY_API_URL:-<not deployed>}"
    echo "  Start-session Lambda:   ${START_SESSION_FUNCTION_NAME}"
    echo ""
    echo -e "${BOLD}  Panel URL:   ${CYAN}${panel_full_url}${NC}"
    echo -e "${BOLD}  Launcher URL:${CYAN}${launcher_full_url}${NC}"
    echo ""
    warn "CloudFront distributions take 5–15 minutes to propagate on first deploy."
    echo ""
    echo -e "${BOLD}${YELLOW}  Required manual steps after propagation:${NC}"
    echo ""
    echo -e "  ${YELLOW}1. Add domain to Connect Approved Origins (domain only — no path):${NC}"
    echo -e "     Connect console → Your instance → Approved origins → Add domain"
    echo -e "     Domain: https://${DIST_DOMAIN}"
    echo ""
    echo -e "  ${YELLOW}2. Add Lambda functions to Connect allow-list:${NC}"
    echo -e "     Connect console → Your instance → AWS Lambda → Add Lambda function"
    echo -e "     Add: ${START_SESSION_FUNCTION_NAME}"
    echo ""
    echo -e "  ${YELLOW}3. Register LAUNCHER as Third-Party App (scope: User — stays open all shift):${NC}"
    echo -e "     Connect console → Your instance → Application integration → Add integration"
    echo -e "     Name:  DTMF Launcher"
    echo -e "     URL:   ${launcher_full_url}"
    echo -e "     Scope: User"
    echo ""
    echo -e "  ${YELLOW}4. Register PANEL as Third-Party App (scope: User):${NC}"
    echo -e "     Connect console → Your instance → Application integration → Add integration"
    echo -e "     Name:  DTMF Status Panel"
    echo -e "     URL:   ${panel_full_url}"
    echo -e "     Scope: User"
    echo ""
    echo -e "  ${YELLOW}5. In your secure capture Contact Flow, add an Invoke AWS Lambda block${NC}"
    echo -e "     BEFORE the 'Store customer input' (DTMF) block:"
    echo -e "     Lambda: ${START_SESSION_FUNCTION_NAME}"
    echo ""
    echo -e "  ${YELLOW}6. Assign both apps (DTMF Launcher + DTMF Status Panel) to the agent${NC}"
    echo -e "     security profile."
    echo ""

    rm -f "$PATCHED_HTML"
}

# =============================================================================
#  Teardown
# =============================================================================
cmd_teardown() {
    header "Teardown — aria-dtmf resources"

    warn "This will remove both Lambdas, the Layer, IAM roles, DynamoDB tables, and log groups."
    warn "It does NOT remove KMS keys or Secrets Manager secrets (use setup_dtmf_keys.sh teardown for those)."
    echo ""

    if ! ask_yn "Proceed with teardown?" "N"; then
        echo "Aborted."; exit 0
    fi

    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

    # ── DynamoDB tables ────────────────────────────────────────────────────────
    if ask_yn "Delete DynamoDB table '${CARD_BINS_TABLE}' (ALL data will be lost)?" "N"; then
        aws dynamodb delete-table \
            --table-name "$CARD_BINS_TABLE" \
            --region     "$REGION" 2>/dev/null && \
        ok "Table ${CARD_BINS_TABLE} deleted" || warn "Table not found — skipping"
    fi

    if ask_yn "Delete DynamoDB table '${CUSTOMER_CARDS_TABLE}' (ALL data will be lost)?" "N"; then
        aws dynamodb delete-table \
            --table-name "$CUSTOMER_CARDS_TABLE" \
            --region     "$REGION" 2>/dev/null && \
        ok "Table ${CUSTOMER_CARDS_TABLE} deleted" || warn "Table not found — skipping"
    fi

    # ── Decrypt Lambda function (deletes all versions + aliases) ─────────────
    if ask_yn "Delete Lambda '${FUNCTION_NAME}' (all versions + aliases)?" "N"; then
        aws lambda delete-function \
            --function-name "$FUNCTION_NAME" \
            --region        "$REGION" 2>/dev/null && \
        ok "Lambda ${FUNCTION_NAME} deleted" || warn "Lambda not found — skipping"
    fi

    # ── Validate Lambda function (deletes all versions + aliases) ────────────
    if ask_yn "Delete Lambda '${VALIDATE_FUNCTION_NAME}' (all versions + aliases)?" "N"; then
        aws lambda delete-function \
            --function-name "$VALIDATE_FUNCTION_NAME" \
            --region        "$REGION" 2>/dev/null && \
        ok "Lambda ${VALIDATE_FUNCTION_NAME} deleted" || warn "Lambda not found — skipping"
    fi

    # ── Lambda Layer (delete all versions) ────────────────────────────────────
    if ask_yn "Delete all versions of Lambda Layer '${LAYER_NAME}'?" "N"; then
        local versions
        versions=$(aws lambda list-layer-versions \
            --layer-name "$LAYER_NAME" \
            --region "$REGION" \
            --query "LayerVersions[*].Version" \
            --output text 2>/dev/null || echo "")
        for v in $versions; do
            aws lambda delete-layer-version \
                --layer-name    "$LAYER_NAME" \
                --version-number "$v" \
                --region        "$REGION" 2>/dev/null && \
            ok "  Layer version ${v} deleted" || true
        done
        ok "Lambda Layer versions deleted"
    fi

    # ── CloudWatch Log Groups ─────────────────────────────────────────────────
    local decrypt_log_group="/aws/lambda/${FUNCTION_NAME}"
    if ask_yn "Delete CloudWatch Log Group '${decrypt_log_group}'?" "N"; then
        aws logs delete-log-group \
            --log-group-name "$decrypt_log_group" \
            --region         "$REGION" 2>/dev/null && \
        ok "Log group deleted" || warn "Log group not found — skipping"
    fi

    local validate_log_group="/aws/lambda/${VALIDATE_FUNCTION_NAME}"
    if ask_yn "Delete CloudWatch Log Group '${validate_log_group}'?" "N"; then
        aws logs delete-log-group \
            --log-group-name "$validate_log_group" \
            --region         "$REGION" 2>/dev/null && \
        ok "Log group deleted" || warn "Log group not found — skipping"
    fi

    # ── IAM role for decrypt Lambda ───────────────────────────────────────────
    if ask_yn "Delete IAM role '${ROLE_NAME}' and all its policies?" "N"; then
        for policy in DTMFSecretsManagerRead DTMFKMSDecrypt DTMFDynamoDBRead; do
            aws iam delete-role-policy \
                --role-name   "$ROLE_NAME" \
                --policy-name "$policy" \
                2>/dev/null || true
        done
        aws iam detach-role-policy \
            --role-name  "$ROLE_NAME" \
            --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" \
            2>/dev/null || true
        aws iam delete-role \
            --role-name "$ROLE_NAME" \
            2>/dev/null && \
        ok "IAM role ${ROLE_NAME} deleted" || warn "IAM role not found — skipping"
    fi

    # ── IAM role for validate Lambda ──────────────────────────────────────────
    if ask_yn "Delete IAM role '${VALIDATE_ROLE_NAME}' and all its policies?" "N"; then
        for policy in ValidateDynamoDBRead ValidateConnectUpdateAttributes ValidateInvokeCustomerLambda ValidateDTMFSessionWrite; do
            aws iam delete-role-policy \
                --role-name   "$VALIDATE_ROLE_NAME" \
                --policy-name "$policy" \
                2>/dev/null || true
        done
        aws iam detach-role-policy \
            --role-name  "$VALIDATE_ROLE_NAME" \
            --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" \
            2>/dev/null || true
        aws iam delete-role \
            --role-name "$VALIDATE_ROLE_NAME" \
            2>/dev/null && \
        ok "IAM role ${VALIDATE_ROLE_NAME} deleted" || warn "IAM role not found — skipping"
    fi

    # ── Status proxy Lambda ───────────────────────────────────────────────────
    if ask_yn "Delete Lambda '${STATUS_PROXY_FUNCTION_NAME}' (status proxy)?" "N"; then
        aws lambda delete-function \
            --function-name "$STATUS_PROXY_FUNCTION_NAME" \
            --region        "$REGION" 2>/dev/null && \
        ok "Lambda ${STATUS_PROXY_FUNCTION_NAME} deleted" || warn "Lambda not found — skipping"
    fi

    local proxy_log_group="/aws/lambda/${STATUS_PROXY_FUNCTION_NAME}"
    if ask_yn "Delete CloudWatch Log Group '${proxy_log_group}'?" "N"; then
        aws logs delete-log-group \
            --log-group-name "$proxy_log_group" \
            --region         "$REGION" 2>/dev/null && \
        ok "Log group deleted" || warn "Log group not found — skipping"
    fi

    if ask_yn "Delete IAM role '${STATUS_PROXY_ROLE_NAME}' and its policies?" "N"; then
        for policy in ProxyConnectGetAttributes ProxyDynamoDBGetSession; do
            aws iam delete-role-policy \
                --role-name   "$STATUS_PROXY_ROLE_NAME" \
                --policy-name "$policy" \
                2>/dev/null || true
        done
        aws iam detach-role-policy \
            --role-name  "$STATUS_PROXY_ROLE_NAME" \
            --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" \
            2>/dev/null || true
        aws iam delete-role \
            --role-name "$STATUS_PROXY_ROLE_NAME" \
            2>/dev/null && \
        ok "IAM role ${STATUS_PROXY_ROLE_NAME} deleted" || warn "IAM role not found — skipping"
    fi

    local proxy_api_id
    proxy_api_id=$(state_get "status_proxy_api_id" "")
    if [[ -n "$proxy_api_id" ]]; then
        if ask_yn "Delete HTTP API Gateway '${STATUS_PROXY_API_NAME}' (${proxy_api_id})?" "N"; then
            aws apigatewayv2 delete-api \
                --api-id  "$proxy_api_id" \
                --region  "$REGION" 2>/dev/null && \
            ok "API Gateway ${proxy_api_id} deleted" || warn "API Gateway not found — skipping"
        fi
    fi

    # ── DynamoDB sessions table ───────────────────────────────────────────────
    if ask_yn "Delete DynamoDB table '${SESSIONS_TABLE_NAME}' (active session data)?" "N"; then
        aws dynamodb delete-table \
            --table-name "$SESSIONS_TABLE_NAME" \
            --region     "$REGION" 2>/dev/null && \
        ok "Table ${SESSIONS_TABLE_NAME} deleted" || warn "Table not found — skipping"
    fi

    # ── Start-session Lambda ──────────────────────────────────────────────────
    if ask_yn "Delete Lambda '${START_SESSION_FUNCTION_NAME}'?" "N"; then
        aws lambda delete-function \
            --function-name "$START_SESSION_FUNCTION_NAME" \
            --region        "$REGION" 2>/dev/null && \
        ok "Lambda ${START_SESSION_FUNCTION_NAME} deleted" || warn "Lambda not found — skipping"
    fi

    local start_log_group="/aws/lambda/${START_SESSION_FUNCTION_NAME}"
    if ask_yn "Delete CloudWatch Log Group '${start_log_group}'?" "N"; then
        aws logs delete-log-group \
            --log-group-name "$start_log_group" \
            --region         "$REGION" 2>/dev/null && \
        ok "Log group deleted" || warn "Log group not found — skipping"
    fi

    if ask_yn "Delete IAM role '${START_SESSION_ROLE_NAME}' and its policies?" "N"; then
        for policy in StartSessionConnectUpdate StartSessionDynamoDBWrite; do
            aws iam delete-role-policy \
                --role-name   "$START_SESSION_ROLE_NAME" \
                --policy-name "$policy" \
                2>/dev/null || true
        done
        aws iam detach-role-policy \
            --role-name  "$START_SESSION_ROLE_NAME" \
            --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" \
            2>/dev/null || true
        aws iam delete-role \
            --role-name "$START_SESSION_ROLE_NAME" \
            2>/dev/null && \
        ok "IAM role ${START_SESSION_ROLE_NAME} deleted" || warn "IAM role not found — skipping"
    fi

    # ── State file ────────────────────────────────────────────────────────────
    [[ -f "$STATE_FILE" ]] && rm "$STATE_FILE" && ok "Lambda state file removed"

    # ── CCP Status Panel (S3 bucket + CloudFront distribution) ───────────────
    local panel_bucket="aria-dtmf-panel-${ACCOUNT_ID}"
    if ask_yn "Delete CCP Status Panel S3 bucket '${panel_bucket}' and all contents?" "N"; then
        step "Emptying bucket ${panel_bucket} …"
        aws s3 rm "s3://${panel_bucket}" --recursive --region "$REGION" 2>/dev/null || true
        aws s3api delete-bucket \
            --bucket "$panel_bucket" \
            --region "$REGION" 2>/dev/null && \
        ok "Bucket ${panel_bucket} deleted" || warn "Bucket not found — skipping"
    fi

    local panel_dist_id
    panel_dist_id=$(state_get "panel_dist_id" "")
    if [[ -n "$panel_dist_id" ]]; then
        if ask_yn "Disable + delete CloudFront distribution '${panel_dist_id}'? (takes ~10 min to propagate)" "N"; then
            step "Getting current distribution config …"
            local dist_etag dist_config
            dist_etag=$(aws cloudfront get-distribution-config \
                --id "$panel_dist_id" \
                --query "ETag" --output text 2>/dev/null || echo "")
            if [[ -n "$dist_etag" ]]; then
                dist_config=$(aws cloudfront get-distribution-config \
                    --id "$panel_dist_id" \
                    --query "DistributionConfig" --output json 2>/dev/null)
                local disabled_config
                disabled_config=$(echo "$dist_config" | python3 -c "
import sys, json
cfg = json.load(sys.stdin)
cfg['Enabled'] = False
print(json.dumps(cfg))
")
                step "Disabling distribution (this triggers a ~10 min propagation) …"
                local new_etag
                new_etag=$(aws cloudfront update-distribution \
                    --id "$panel_dist_id" \
                    --if-match "$dist_etag" \
                    --distribution-config "$disabled_config" \
                    --query "ETag" --output text 2>/dev/null || echo "")
                if [[ -n "$new_etag" ]]; then
                    ok "Distribution disabled — waiting for propagation (up to 10 min) …"
                    aws cloudfront wait distribution-deployed --id "$panel_dist_id" 2>/dev/null || true
                    aws cloudfront delete-distribution \
                        --id "$panel_dist_id" \
                        --if-match "$new_etag" \
                        2>/dev/null && \
                    ok "CloudFront distribution ${panel_dist_id} deleted" || \
                    warn "Could not delete distribution — delete manually from AWS console"
                else
                    warn "Could not disable distribution — delete manually: aws cloudfront delete-distribution --id ${panel_dist_id}"
                fi
            else
                warn "Distribution ${panel_dist_id} not found — skipping"
            fi
        fi
    fi

    echo ""
    warn "KMS key and Secrets Manager secret NOT removed."
    warn "To remove key material: ./scripts/setup_dtmf_keys.sh teardown"
    ok "Teardown complete"
}

# =============================================================================
#  Argument parsing
# =============================================================================
parse_args() {
    COMMAND="${1:-help}"
    shift || true

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --instance-id)            CONNECT_INSTANCE_ID="$2";      shift 2 ;;
            --connect-instance-url)   CONNECT_INSTANCE_URL="$2";     shift 2 ;;
            --region)                 REGION="$2";                   shift 2 ;;
            --secret-arn)             PRIVATE_KEY_SECRET_ARN="$2";   shift 2 ;;
            --connect-key-id)         CONNECT_KEY_ID="$2";           shift 2 ;;
            --kms-key-arn)            KMS_KEY_ARN="$2";              shift 2 ;;
            --function-name)          FUNCTION_NAME="$2";            shift 2 ;;
            --layer-name)             LAYER_NAME="$2";               shift 2 ;;
            *) die "Unknown argument: $1. Run $0 for usage." ;;
        esac
    done
}

# =============================================================================
#  Entry point
# =============================================================================
main() {
    if [[ $# -eq 0 ]]; then
        echo ""
        echo "Usage: $0 <command> [options]"
        echo ""
        echo "Commands:"
        echo "  deploy        — deploy/update both Lambdas, Layer, DynamoDB, IAM roles, CCP Panel"
        echo "                  (all parameters prompted interactively if not provided)"
        echo "  deploy-panel  — deploy or update CCP Status Panel only (S3 + CloudFront)"
        echo "                  (prompts for Connect instance URL and instance ID)"
        echo "  teardown      — remove all resources: Lambdas, Layer, DynamoDB, IAM roles, Panel (prompts for each)"
        echo "  status        — print current deploy state"
        echo ""
        echo "Options (all optional — script prompts for any that are missing):"
        echo "  --instance-id <uuid>             Connect Instance ID"
        echo "  --connect-instance-url <url>     Connect instance URL (e.g. https://xxx.my.connect.aws)"
        echo "  --region <region>                AWS region (default: eu-west-2)"
        echo "  --secret-arn <arn>               Secrets Manager ARN for private key  [deploy only]"
        echo "  --connect-key-id <id>            Connect Flow Security Key ID          [deploy only]"
        echo "  --kms-key-arn <arn>              KMS CMK ARN for KMS Decrypt policy    [deploy only]"
        echo "  --function-name <name>           Override Lambda function name         [deploy only]"
        echo "  --layer-name <name>              Override Lambda Layer name            [deploy only]"
        echo ""
        echo "If setup_dtmf_keys.sh has been run, --secret-arn / --connect-key-id / --kms-key-arn"
        echo "and --connect-instance-url are read automatically from state files."
        echo ""
        exit 0
    fi

    parse_args "$@"
    state_init

    case "$COMMAND" in
        deploy)
            echo ""
            echo -e "${BOLD}${BLUE}ARIA — DTMF Decrypt Lambda Deploy${NC}"
            echo -e "${BOLD}${BLUE}Region: ${REGION}${NC}"
            echo ""

            ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
            ok "AWS Account: ${ACCOUNT_ID}  Region: ${REGION}"

            resolve_config
            ensure_iam_role
            ensure_dynamodb_tables
            ensure_lambda_layer
            deploy_lambda_and_alias
            add_connect_permission
            deploy_validate_lambda
            cmd_deploy_panel
            print_deploy_summary
            ;;

        teardown) cmd_teardown ;;
        status)   cmd_status   ;;

        deploy-panel)
            echo ""
            echo -e "${BOLD}${BLUE}ARIA — DTMF CCP Status Panel Deploy${NC}"
            echo -e "${BOLD}${BLUE}Region: ${REGION}${NC}"
            echo ""

            ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
            ok "AWS Account: ${ACCOUNT_ID}  Region: ${REGION}"

            state_init
            resolve_panel_config
            cmd_deploy_panel
            ;;

        *)
            die "Unknown command '${COMMAND}'. Run $0 for usage."
            ;;
    esac
}

main "$@"
