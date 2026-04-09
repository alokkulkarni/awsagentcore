#!/usr/bin/env bash
# =============================================================================
#  deploy_dtmf_lambda.sh
#  ARIA — DTMF Decryption Lambda — Deploy / Teardown Script
#  Meridian Bank / Amazon Connect
# =============================================================================
#
#  USAGE
#    ./scripts/deploy_dtmf_lambda.sh deploy   --instance-id <connect-uuid>
#    ./scripts/deploy_dtmf_lambda.sh deploy   --instance-id <connect-uuid> --region eu-west-2
#    ./scripts/deploy_dtmf_lambda.sh teardown
#    ./scripts/deploy_dtmf_lambda.sh status
#
#  WHAT THIS SCRIPT CREATES
#    IAM role     aria-dtmf-decrypt-role
#                   — AWSLambdaBasicExecutionRole (CloudWatch Logs)
#                   — secretsmanager:GetSecretValue on the DTMF private key secret
#                   — kms:Decrypt on the KMS CMK protecting the secret
#
#    Lambda Layer aria-dtmf-dependencies  (Python 3.12)
#                   — aws-encryption-sdk  (AWS Encryption SDK)
#                   — cryptography        (RSA decryption primitives)
#                   Built for manylinux2014_x86_64 to match Lambda runtime
#
#    Lambda       aria-dtmf-decrypt  (Python 3.12, eu-west-2)
#                   — publishes a new immutable version on every deploy
#                   — creates / updates 'prod' alias → latest version
#                   — timeout 15s, memory 256MB
#
#    Connect      resource-based policy on the :prod alias ARN so that only
#                   your Connect instance can invoke it
#
#  PROD ALIAS
#    Every deploy publishes a new immutable version and moves the 'prod' alias
#    to it automatically.  Contact flows should reference the :prod alias ARN:
#      arn:aws:lambda:<region>:<account>:function:aria-dtmf-decrypt:prod
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
PRIVATE_KEY_SECRET_ARN="${PRIVATE_KEY_SECRET_ARN:-}"
CONNECT_KEY_ID="${CONNECT_KEY_ID:-}"
KMS_KEY_ARN="${KMS_KEY_ARN:-}"

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

    # Read from key state file if not set via env
    if [[ -z "$PRIVATE_KEY_SECRET_ARN" ]]; then
        PRIVATE_KEY_SECRET_ARN=$(key_state_get "secret_arn" "")
    fi
    if [[ -z "$CONNECT_KEY_ID" ]]; then
        CONNECT_KEY_ID=$(key_state_get "connect_key_id" "")
    fi
    if [[ -z "$KMS_KEY_ARN" ]]; then
        KMS_KEY_ARN=$(key_state_get "kms_key_arn" "")
    fi
    if [[ -z "$CONNECT_INSTANCE_ID" ]]; then
        CONNECT_INSTANCE_ID=$(key_state_get "connect_instance_id" "")
    fi

    # Prompt for anything still missing
    if [[ -z "$PRIVATE_KEY_SECRET_ARN" ]]; then
        ask PRIVATE_KEY_SECRET_ARN \
            "Secrets Manager ARN for RSA private key" \
            "arn:aws:secretsmanager:${REGION}:${ACCOUNT_ID}:secret:meridian/connect/dtmf-private-key-XXXXXX"
    fi
    if [[ -z "$CONNECT_KEY_ID" ]]; then
        ask CONNECT_KEY_ID "Connect Security Key ID (from Connect console → instance → Security keys)" ""
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

    ok "Secret ARN:    ${PRIVATE_KEY_SECRET_ARN}"
    ok "Connect Key:   ${CONNECT_KEY_ID}"
    ok "KMS Key ARN:   ${KMS_KEY_ARN}"
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

    ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
    state_set "role_arn" "$ROLE_ARN"
    ok "Role ARN: ${ROLE_ARN}"
}

# =============================================================================
#  Step 2 — Lambda Layer (aws-encryption-sdk + cryptography)
# =============================================================================
ensure_lambda_layer() {
    header "Lambda Layer: ${LAYER_NAME}"

    local layer_tmp="/tmp/dtmf-layer"
    local layer_zip="/tmp/${LAYER_NAME}.zip"

    step "Building Lambda Layer (aws-encryption-sdk + cryptography for ${RUNTIME}/linux)..."
    step "  This may take 1-2 minutes on first run..."

    rm -rf "$layer_tmp"
    mkdir -p "${layer_tmp}/python"

    # Install with manylinux2014 binaries to match Lambda's Amazon Linux 2 runtime.
    # --platform manylinux2014_x86_64 fetches pre-built wheels (no compilation needed).
    pip3 install \
        "aws-encryption-sdk>=4.0.0" \
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
    env_vars="Variables={PRIVATE_KEY_SECRET_ARN=${PRIVATE_KEY_SECRET_ARN},CONNECT_KEY_ID=${CONNECT_KEY_ID}}"

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

    echo ""
    echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}${GREEN}  ARIA DTMF Decrypt Lambda — Deploy Complete${NC}"
    echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  ${BOLD}Lambda ARN (prod alias):${NC}"
    echo -e "    ${CYAN}${LAMBDA_ALIAS_ARN}${NC}"
    echo ""
    echo -e "  ${BOLD}Lambda version deployed:${NC}  ${version}"
    echo ""
    echo -e "  ${BOLD}Lambda Layer:${NC}"
    echo -e "    ${LAYER_ARN}"
    echo ""
    echo -e "  ${BOLD}IAM Role:${NC}  arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
    echo ""
    echo -e "  ${BOLD}Environment variables set on Lambda:${NC}"
    echo -e "    PRIVATE_KEY_SECRET_ARN = ${PRIVATE_KEY_SECRET_ARN}"
    echo -e "    CONNECT_KEY_ID         = ${CONNECT_KEY_ID}"
    echo ""
    echo -e "  ${BOLD}State file:${NC}  ${STATE_FILE}"
    echo ""
    echo -e "${BOLD}${YELLOW}  Required manual steps:${NC}"
    echo ""
    echo -e "  ${YELLOW}1. Add Lambda to Connect instance allow-list:${NC}"
    echo -e "     Connect console → <instance> → AWS Lambda → Add Lambda function"
    echo -e "     Select: ${FUNCTION_NAME}"
    echo ""
    echo -e "  ${YELLOW}2. In the ARIA-DTMF-SecureCollection flow — Lambda block:${NC}"
    echo -e "     Select: ${FUNCTION_NAME}  (or the :prod alias ARN)"
    echo -e "     Parameters:"
    echo -e "       encryptedValue → System → Stored customer input"
    echo -e "       purpose        → User Defined → collectionPurpose"
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
#  Teardown
# =============================================================================
cmd_teardown() {
    header "Teardown — aria-dtmf-decrypt resources"

    warn "This will remove the Lambda, Layer, IAM role, and log group."
    warn "It does NOT remove KMS keys or Secrets Manager secrets (use setup_dtmf_keys.sh teardown for those)."
    echo ""

    if ! ask_yn "Proceed with teardown?" "N"; then
        echo "Aborted."; exit 0
    fi

    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

    # ── Lambda function (deletes all versions + aliases) ─────────────────────
    if ask_yn "Delete Lambda '${FUNCTION_NAME}' (all versions + aliases)?" "N"; then
        aws lambda delete-function \
            --function-name "$FUNCTION_NAME" \
            --region        "$REGION" 2>/dev/null && \
        ok "Lambda deleted" || warn "Lambda not found — skipping"
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

    # ── CloudWatch Log Group ──────────────────────────────────────────────────
    local log_group="/aws/lambda/${FUNCTION_NAME}"
    if ask_yn "Delete CloudWatch Log Group '${log_group}'?" "N"; then
        aws logs delete-log-group \
            --log-group-name "$log_group" \
            --region         "$REGION" 2>/dev/null && \
        ok "Log group deleted" || warn "Log group not found — skipping"
    fi

    # ── IAM role + inline policies ────────────────────────────────────────────
    if ask_yn "Delete IAM role '${ROLE_NAME}' and all its policies?" "N"; then
        for policy in DTMFSecretsManagerRead DTMFKMSDecrypt; do
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
        ok "IAM role deleted" || warn "IAM role not found — skipping"
    fi

    # ── State file ────────────────────────────────────────────────────────────
    [[ -f "$STATE_FILE" ]] && rm "$STATE_FILE" && ok "Lambda state file removed"

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
        echo "  deploy     — deploy or update Lambda, Layer, IAM role, Connect permission"
        echo "  teardown   — remove Lambda, Layer, IAM role (prompts for each)"
        echo "  status     — print current deploy state"
        echo ""
        echo "Options:"
        echo "  --instance-id <uuid>         Connect Instance ID (required for Connect permission)"
        echo "  --region <region>            AWS region (default: eu-west-2)"
        echo "  --secret-arn <arn>           Secrets Manager ARN for private key"
        echo "  --connect-key-id <id>        Connect Security Key ID"
        echo "  --kms-key-arn <arn>          KMS CMK ARN for KMS Decrypt policy"
        echo "  --function-name <name>       Override Lambda function name"
        echo "  --layer-name <name>          Override Lambda Layer name"
        echo ""
        echo "If setup_dtmf_keys.sh has been run, --secret-arn / --connect-key-id / --kms-key-arn"
        echo "are read automatically from .deploy-dtmf-key-state.json"
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
            ensure_lambda_layer
            deploy_lambda_and_alias
            add_connect_permission
            print_deploy_summary
            ;;

        teardown) cmd_teardown ;;
        status)   cmd_status   ;;

        *)
            die "Unknown command '${COMMAND}'. Run $0 for usage."
            ;;
    esac
}

main "$@"
