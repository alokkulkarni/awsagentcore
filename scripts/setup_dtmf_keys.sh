#!/usr/bin/env bash
# =============================================================================
#  setup_dtmf_keys.sh
#  ARIA — DTMF Encryption Key Setup
#  Meridian Bank / Amazon Connect
# =============================================================================
#
#  USAGE
#    ./scripts/setup_dtmf_keys.sh setup     — full first-time setup
#    ./scripts/setup_dtmf_keys.sh rotate    — add a second key for rotation
#    ./scripts/setup_dtmf_keys.sh teardown  — remove all key resources
#    ./scripts/setup_dtmf_keys.sh status    — print current key state
#
#  WHAT THIS SCRIPT DOES (setup command)
#    1. Generates a 4096-bit RSA key pair locally (openssl)
#    2. Creates an AWS KMS Customer Managed Key (CMK) + alias
#    3. Stores the RSA private key in AWS Secrets Manager, encrypted by the KMS CMK
#    4. Uploads the RSA public key (.pem) to your Amazon Connect instance
#       → Connect assigns a Key ID used in all "Store customer input" blocks
#    5. Saves state to .deploy-dtmf-key-state.json
#    6. Securely deletes the local private key
#
#  ROTATION (rotate command)
#    Connect supports up to 2 active security keys simultaneously.
#    Use this to add a new key without downtime.  After verifying the new key
#    works, remove the old one using teardown --old-key-only.
#
#  PREREQUISITES
#    • openssl ≥ 1.1 in PATH
#    • aws CLI v2 configured with IAM permissions for:
#        kms:CreateKey, kms:CreateAlias, kms:DescribeKey
#        secretsmanager:CreateSecret, secretsmanager:GetSecretValue
#        connect:AssociateSecurityKey, connect:ListSecurityKeys
#    • python3 in PATH (for state file management)
#    • shred (Linux) or srm / rm -P (macOS) for secure delete
#
#  ENVIRONMENT VARIABLES (all optional — script will prompt if not set)
#    AWS_REGION           default: eu-west-2
#    CONNECT_INSTANCE_ID  Your Connect instance UUID
#    KEY_PREFIX           default: meridian-connect
#    KMS_ALIAS            default: alias/meridian-connect-dtmf
#    SECRET_NAME          default: meridian/connect/dtmf-private-key
#
#  STATE FILE
#    .deploy-dtmf-key-state.json  — persists ARNs, Connect Key IDs, KMS key IDs
#    Reference it from deploy_dtmf_lambda.sh to auto-populate env vars.
#
#  SECURITY NOTES
#    • The private key file is SECURELY DELETED after upload to Secrets Manager.
#    • The public .pem file is safe to retain; it is also not secret.
#    • If this script is interrupted before the secure delete step, manually run:
#        rm -P ~/meridian-dtmf-keys/meridian-connect-private-*.pem  (macOS)
#        shred -u ~/meridian-dtmf-keys/meridian-connect-private-*.pem  (Linux)
#
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_FILE="${SCRIPT_DIR}/.deploy-dtmf-key-state.json"

# ── Defaults (overridable by env or --flags) ──────────────────────────────────
REGION="${AWS_REGION:-eu-west-2}"
CONNECT_INSTANCE_ID="${CONNECT_INSTANCE_ID:-}"
KEY_PREFIX="${KEY_PREFIX:-meridian-connect}"
KMS_ALIAS="${KMS_ALIAS:-alias/meridian-connect-dtmf}"
SECRET_NAME="${SECRET_NAME:-meridian/connect/dtmf-private-key}"
KEY_DIR="${HOME}/meridian-dtmf-keys"

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

# ── Prerequisites check ────────────────────────────────────────────────────────
check_prerequisites() {
    header "Checking prerequisites"
    local missing=0

    for cmd in openssl aws python3; do
        if command -v "$cmd" &>/dev/null; then
            ok "$cmd found: $(command -v "$cmd")"
        else
            error "$cmd not found — install it before proceeding"
            (( missing++ ))
        fi
    done

    # Check openssl version supports RSA 4096
    local openssl_version
    openssl_version=$(openssl version 2>/dev/null | awk '{print $2}' || echo "unknown")
    ok "openssl version: ${openssl_version}"

    [[ $missing -gt 0 ]] && die "Missing $missing prerequisite(s). Cannot continue."
    ok "All prerequisites satisfied"
}

# ── Secure delete ──────────────────────────────────────────────────────────────
secure_delete() {
    local file="$1"
    if [[ ! -f "$file" ]]; then
        return
    fi

    # macOS: use rm -P (overwrites before delete)
    # Linux: use shred
    if command -v shred &>/dev/null; then
        shred -uz "$file"
    elif [[ "$(uname)" == "Darwin" ]]; then
        rm -P "$file" 2>/dev/null || rm -f "$file"
    else
        # Fallback: overwrite with zeros then delete
        dd if=/dev/zero of="$file" bs=1024 count=1 2>/dev/null || true
        rm -f "$file"
    fi
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

# ── Gather config interactively if not set ─────────────────────────────────────
gather_config() {
    header "Configuration"

    echo ""
    echo -e "  ${BOLD}This script will create:${NC}"
    echo -e "    1. RSA 4096-bit key pair  →  stored in ~/meridian-dtmf-keys/"
    echo -e "    2. KMS Customer Managed Key  →  protects private key at rest"
    echo -e "    3. Secrets Manager secret  →  holds the RSA private key (KMS-encrypted)"
    echo -e "    4. Connect Security Key  →  registers public key with Connect"
    echo ""

    if [[ -z "$REGION" ]]; then
        ask REGION "AWS region" "eu-west-2"
    else
        ok "Region: ${REGION}"
    fi

    if [[ -z "$CONNECT_INSTANCE_ID" ]]; then
        ask CONNECT_INSTANCE_ID "Connect Instance ID (UUID, e.g. 12345678-1234-1234-1234-123456789012)"
    fi

    if [[ -z "$CONNECT_INSTANCE_ID" ]]; then
        warn "No Connect Instance ID provided."
        warn "The RSA key pair and Secrets Manager secret will be created."
        warn "You must manually upload the public key to Connect:"
        warn "  Connect console → Your instance → Security keys → Add key"
    fi

    ok "Region: ${REGION}"
    ok "Key prefix: ${KEY_PREFIX}"
    ok "KMS alias: ${KMS_ALIAS}"
    ok "Secret name: ${SECRET_NAME}"
    ok "Key directory: ${KEY_DIR}"

    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --region "$REGION")
    ok "AWS Account: ${ACCOUNT_ID}"
}

# ── Step 1: Generate RSA key pair ──────────────────────────────────────────────
generate_key_pair() {
    header "Step 1 — Generate RSA 4096-bit key pair"

    local timestamp
    timestamp=$(date +%Y%m%d-%H%M%S)
    PRIVATE_KEY_FILE="${KEY_DIR}/${KEY_PREFIX}-private-${timestamp}.pem"
    PUBLIC_KEY_FILE="${KEY_DIR}/${KEY_PREFIX}-public-${timestamp}.pem"

    mkdir -p "$KEY_DIR"
    chmod 700 "$KEY_DIR"

    step "Generating RSA 4096-bit private key..."
    openssl genrsa -out "$PRIVATE_KEY_FILE" 4096 2>/dev/null
    chmod 600 "$PRIVATE_KEY_FILE"
    ok "Private key: ${PRIVATE_KEY_FILE}"

    step "Generating self-signed X.509 certificate (public key for Connect)..."
    openssl req -new -x509 \
        -key "$PRIVATE_KEY_FILE" \
        -out "$PUBLIC_KEY_FILE" \
        -days 1825 \
        -subj "/CN=${KEY_PREFIX}-dtmf/O=Meridian Bank/C=GB" \
        2>/dev/null
    chmod 644 "$PUBLIC_KEY_FILE"
    ok "Public certificate: ${PUBLIC_KEY_FILE}"

    # Verify the key pair
    local key_modulus cert_modulus
    key_modulus=$(openssl rsa  -in "$PRIVATE_KEY_FILE" -modulus -noout 2>/dev/null | md5sum)
    cert_modulus=$(openssl x509 -in "$PUBLIC_KEY_FILE"  -modulus -noout 2>/dev/null | md5sum)

    if [[ "$key_modulus" == "$cert_modulus" ]]; then
        ok "Key pair verified — private key and certificate match"
    else
        die "Key pair verification failed — moduli do not match. Aborting."
    fi

    state_set "public_key_file" "$PUBLIC_KEY_FILE"
    state_set "private_key_file_tmp" "$PRIVATE_KEY_FILE"
    state_set "key_timestamp" "$timestamp"
}

# ── Step 2: Create KMS Customer Managed Key ────────────────────────────────────
create_kms_key() {
    header "Step 2 — Create KMS Customer Managed Key"

    # Check if alias already exists
    local existing_kms_id
    existing_kms_id=$(aws kms describe-key \
        --key-id "$KMS_ALIAS" \
        --region "$REGION" \
        --query "KeyMetadata.KeyId" --output text 2>/dev/null || echo "")

    if [[ -n "$existing_kms_id" ]]; then
        warn "KMS alias '${KMS_ALIAS}' already exists (KeyId: ${existing_kms_id})"
        if ask_yn "Reuse the existing KMS key?" "Y"; then
            KMS_KEY_ID="$existing_kms_id"
            KMS_KEY_ARN="arn:aws:kms:${REGION}:${ACCOUNT_ID}:key/${KMS_KEY_ID}"
            ok "Reusing KMS key: ${KMS_KEY_ARN}"
            state_set "kms_key_id"  "$KMS_KEY_ID"
            state_set "kms_key_arn" "$KMS_KEY_ARN"
            state_set "kms_alias"   "$KMS_ALIAS"
            return
        fi
        # Generate a different alias for rotation
        KMS_ALIAS="${KMS_ALIAS}-v2"
        warn "Using new alias: ${KMS_ALIAS}"
    fi

    step "Creating KMS CMK for DTMF private key protection..."
    KMS_KEY_ID=$(aws kms create-key \
        --description "Meridian Bank Connect DTMF RSA private key protection" \
        --key-usage ENCRYPT_DECRYPT \
        --key-spec SYMMETRIC_DEFAULT \
        --origin AWS_KMS \
        --region "$REGION" \
        --query "KeyMetadata.KeyId" --output text)

    step "Creating KMS alias: ${KMS_ALIAS}"
    aws kms create-alias \
        --alias-name "$KMS_ALIAS" \
        --target-key-id "$KMS_KEY_ID" \
        --region "$REGION"

    # Enable automatic key rotation (recommended for long-lived CMKs)
    step "Enabling automatic annual KMS key rotation..."
    aws kms enable-key-rotation \
        --key-id "$KMS_KEY_ID" \
        --region "$REGION"

    KMS_KEY_ARN="arn:aws:kms:${REGION}:${ACCOUNT_ID}:key/${KMS_KEY_ID}"
    ok "KMS CMK created: ${KMS_KEY_ARN}"
    ok "Alias: ${KMS_ALIAS}"
    ok "Annual key rotation: enabled"

    state_set "kms_key_id"  "$KMS_KEY_ID"
    state_set "kms_key_arn" "$KMS_KEY_ARN"
    state_set "kms_alias"   "$KMS_ALIAS"
}

# ── Step 3: Store private key in Secrets Manager ───────────────────────────────
store_private_key() {
    header "Step 3 — Store private key in Secrets Manager (KMS-encrypted)"

    # Check if secret already exists
    local existing_arn
    existing_arn=$(aws secretsmanager describe-secret \
        --secret-id "$SECRET_NAME" \
        --region "$REGION" \
        --query "ARN" --output text 2>/dev/null || echo "")

    if [[ -n "$existing_arn" ]]; then
        warn "Secret '${SECRET_NAME}' already exists."
        if ask_yn "Update the existing secret with the new private key?" "Y"; then
            step "Updating existing secret with new private key..."
            SECRET_ARN=$(aws secretsmanager update-secret \
                --secret-id "$SECRET_NAME" \
                --secret-string "file://${PRIVATE_KEY_FILE}" \
                --kms-key-id "$KMS_KEY_ARN" \
                --region "$REGION" \
                --query "ARN" --output text)
            ok "Secret updated: ${SECRET_ARN}"
        else
            # Create a versioned secret name for rotation
            SECRET_NAME="${SECRET_NAME}-v2"
            warn "Using new secret name: ${SECRET_NAME}"
            existing_arn=""
        fi
    fi

    if [[ -z "$existing_arn" ]]; then
        step "Creating Secrets Manager secret '${SECRET_NAME}'..."
        SECRET_ARN=$(aws secretsmanager create-secret \
            --name "$SECRET_NAME" \
            --description "RSA private key for Amazon Connect DTMF decryption — Meridian Bank" \
            --secret-string "file://${PRIVATE_KEY_FILE}" \
            --kms-key-id "$KMS_KEY_ARN" \
            --region "$REGION" \
            --query "ARN" --output text)
        ok "Secret created: ${SECRET_ARN}"
    fi

    state_set "secret_name" "$SECRET_NAME"
    state_set "secret_arn"  "$SECRET_ARN"

    # ── SECURE DELETE the local private key ────────────────────────────────────
    echo ""
    warn "IMPORTANT: Securely deleting local private key file..."
    warn "  ${PRIVATE_KEY_FILE}"
    echo ""
    if ask_yn "Confirm: securely delete local private key (it is now in Secrets Manager)?" "Y"; then
        secure_delete "$PRIVATE_KEY_FILE"
        ok "Private key securely deleted from local filesystem"
        state_set "private_key_file_tmp" ""
    else
        warn "Local private key NOT deleted: ${PRIVATE_KEY_FILE}"
        warn "You must manually delete it: rm -P '${PRIVATE_KEY_FILE}' (macOS)"
        warn "                             shred -uz '${PRIVATE_KEY_FILE}' (Linux)"
    fi
}

# ── Step 4: Register public key with Amazon Connect ────────────────────────────
register_connect_key() {
    header "Step 4 — Register public key with Amazon Connect"

    if [[ -z "$CONNECT_INSTANCE_ID" ]]; then
        warn "No Connect Instance ID — skipping automated key registration."
        echo ""
        echo -e "  ${BOLD}Manual step required:${NC}"
        echo -e "  1. Go to: AWS Console → Amazon Connect → Your instance → Security keys"
        echo -e "  2. Click ${BOLD}Add key${NC}"
        echo -e "  3. Upload: ${PUBLIC_KEY_FILE}"
        echo -e "  4. Note the ${BOLD}Key ID${NC} assigned by Connect"
        echo -e "  5. Run: ${CYAN}./scripts/setup_dtmf_keys.sh register-key-id <key-id>${NC}"
        echo ""
        return
    fi

    # Check how many security keys are already registered
    local key_count
    key_count=$(aws connect list-security-keys \
        --instance-id "$CONNECT_INSTANCE_ID" \
        --region "$REGION" \
        --query "length(SecurityKeysList)" --output text 2>/dev/null || echo "0")

    if [[ "$key_count" -ge 2 ]]; then
        die "Connect already has 2 security keys registered (the maximum allowed)." \
            "Remove one before adding a new key." \
            "Use: teardown --old-key-only"
    fi

    step "Registering public key with Connect instance ${CONNECT_INSTANCE_ID}..."
    step "  Key file: ${PUBLIC_KEY_FILE}"

    CONNECT_KEY_ASSOCIATION_ID=$(aws connect associate-security-key \
        --instance-id "$CONNECT_INSTANCE_ID" \
        --key "$(cat "${PUBLIC_KEY_FILE}")" \
        --region "$REGION" \
        --query "AssociationId" --output text)

    ok "Connect Security Key registered"
    ok "  Association ID (= Key ID for flows): ${CONNECT_KEY_ASSOCIATION_ID}"

    state_set "connect_key_id"            "$CONNECT_KEY_ASSOCIATION_ID"
    state_set "connect_instance_id"       "$CONNECT_INSTANCE_ID"
    state_set "connect_public_key_file"   "$PUBLIC_KEY_FILE"
}

# ── Print summary ──────────────────────────────────────────────────────────────
print_setup_summary() {
    echo ""
    echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}${GREEN}  ARIA DTMF Key Setup — Complete${NC}"
    echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  ${BOLD}KMS CMK ARN:${NC}"
    echo -e "    ${CYAN}${KMS_KEY_ARN}${NC}"
    echo ""
    echo -e "  ${BOLD}KMS alias:${NC}  ${KMS_ALIAS}"
    echo ""
    echo -e "  ${BOLD}Secrets Manager secret:${NC}"
    echo -e "    ${CYAN}${SECRET_ARN}${NC}"
    echo ""

    if [[ -n "$CONNECT_INSTANCE_ID" ]]; then
        local connect_key_id
        connect_key_id=$(state_get "connect_key_id" "NOT_REGISTERED")
        echo -e "  ${BOLD}Connect Key ID (use in 'Store customer input' blocks):${NC}"
        echo -e "    ${CYAN}${connect_key_id}${NC}"
        echo ""
    fi

    echo -e "  ${BOLD}Public key file (safe to keep):${NC}"
    echo -e "    ${PUBLIC_KEY_FILE}"
    echo ""
    echo -e "  ${BOLD}State file:${NC}  ${STATE_FILE}"
    echo ""
    echo -e "${BOLD}${YELLOW}  Next steps:${NC}"
    echo ""

    if [[ -z "$CONNECT_INSTANCE_ID" ]]; then
        echo -e "  ${YELLOW}1. Upload public key to Connect:${NC}"
        echo -e "     AWS Console → Connect → Your instance → Security keys → Add key"
        echo -e "     File: ${PUBLIC_KEY_FILE}"
        echo -e "     Then: ./scripts/setup_dtmf_keys.sh register-key-id <KEY_ID>"
        echo ""
        echo -e "  ${YELLOW}2.${NC} Run the Lambda deploy script:"
    else
        echo -e "  ${YELLOW}1.${NC} Run the Lambda deploy script:"
    fi

    echo -e "     ${CYAN}./scripts/deploy_dtmf_lambda.sh deploy \\${NC}"
    echo -e "     ${CYAN}  --instance-id ${CONNECT_INSTANCE_ID:-<your-connect-instance-id>} \\${NC}"
    echo -e "     ${CYAN}  --region ${REGION}${NC}"
    echo ""
    echo -e "  ${YELLOW}  Set these environment variables for the Lambda:${NC}"
    echo -e "     PRIVATE_KEY_SECRET_ARN = ${SECRET_ARN:-<from state file>}"
    echo -e "     CONNECT_KEY_ID         = $(state_get "connect_key_id" "<from Connect console>")"
    echo ""
    echo -e "${BOLD}${GREEN}  Private key has been securely deleted from local disk.${NC}"
    echo -e "${BOLD}${GREEN}  It is protected by KMS in Secrets Manager.${NC}"
    echo ""
}

# ── Status command ─────────────────────────────────────────────────────────────
cmd_status() {
    header "DTMF Key Setup Status"

    if [[ ! -f "$STATE_FILE" ]]; then
        warn "No state file found at ${STATE_FILE}"
        warn "Run: ./scripts/setup_dtmf_keys.sh setup"
        return
    fi

    echo ""
    python3 - "$STATE_FILE" <<'PYEOF'
import sys, json
with open(sys.argv[1]) as f:
    data = json.load(f)
if not data:
    print("  State file is empty — run: ./scripts/setup_dtmf_keys.sh setup")
else:
    maxk = max(len(k) for k in data.keys())
    for k, v in data.items():
        val = v if v else "(not set)"
        print(f"  {k.ljust(maxk+2)} {val}")
PYEOF
    echo ""
}

# ── Register key ID manually (for when Connect ID wasn't available at setup) ───
cmd_register_key_id() {
    local key_id="$1"
    if [[ -z "$key_id" ]]; then
        die "Usage: $0 register-key-id <connect-key-id>"
    fi
    state_init
    state_set "connect_key_id" "$key_id"
    ok "Connect Key ID saved to state file: ${key_id}"
    warn "Update CONNECT_KEY_ID env var on the aria-dtmf-decrypt Lambda:"
    warn "  aws lambda update-function-configuration \\"
    warn "    --function-name aria-dtmf-decrypt \\"
    warn "    --environment 'Variables={CONNECT_KEY_ID=${key_id},PRIVATE_KEY_SECRET_ARN=$(state_get "secret_arn" "<arn>")}' \\"
    warn "    --region ${REGION}"
}

# ── Rotation command ───────────────────────────────────────────────────────────
cmd_rotate() {
    header "DTMF Key Rotation"

    echo ""
    echo -e "  ${BOLD}Key rotation allows you to replace your RSA key pair without downtime.${NC}"
    echo -e "  Connect supports 2 active security keys simultaneously."
    echo ""
    echo -e "  During rotation:"
    echo -e "    • New calls use the new key from the moment you update the Lambda"
    echo -e "    • Old calls (open contacts) keep working with the old key"
    echo -e "    • Remove old key only after all old contacts have closed"
    echo ""

    if ! ask_yn "Continue with key rotation?" "N"; then
        echo "Aborted."
        exit 0
    fi

    # Generate a new key pair with a v2 suffix
    local old_secret_name="$SECRET_NAME"
    local old_kms_alias="$KMS_ALIAS"
    SECRET_NAME="${SECRET_NAME}-v2"
    KMS_ALIAS="${KMS_ALIAS}-v2"

    warn "Old secret:    ${old_secret_name}"
    warn "New secret:    ${SECRET_NAME}"
    warn "New KMS alias: ${KMS_ALIAS}"

    gather_config
    generate_key_pair
    create_kms_key
    store_private_key
    register_connect_key

    echo ""
    echo -e "${BOLD}${YELLOW}  ROTATION NEXT STEPS:${NC}"
    echo -e ""
    echo -e "  1. Update Lambda CONNECT_KEY_ID to the new key ID:"
    echo -e "     aws lambda update-function-configuration \\"
    echo -e "       --function-name aria-dtmf-decrypt \\"
    echo -e "       --environment 'Variables={CONNECT_KEY_ID=$(state_get "connect_key_id" "<new-key-id>"),PRIVATE_KEY_SECRET_ARN=${SECRET_ARN:-<arn>}}' \\"
    echo -e "       --region ${REGION}"
    echo ""
    echo -e "  2. Update EVERY 'Store customer input' block in Connect flows:"
    echo -e "     Change the key selection to the new Key ID"
    echo ""
    echo -e "  3. Monitor — wait until all contacts encrypted with the old key are closed"
    echo -e "     (check Contact Trace Records in Connect)"
    echo ""
    echo -e "  4. Remove old Connect security key:"
    echo -e "     aws connect disassociate-security-key \\"
    echo -e "       --instance-id ${CONNECT_INSTANCE_ID} \\"
    echo -e "       --association-id <OLD_CONNECT_KEY_ID> \\"
    echo -e "       --region ${REGION}"
    echo ""
    echo -e "  5. (Optional) Delete old Secrets Manager secret when no longer needed:"
    echo -e "     aws secretsmanager delete-secret --secret-id ${old_secret_name} --region ${REGION}"
    echo ""
}

# ── Teardown command ───────────────────────────────────────────────────────────
cmd_teardown() {
    header "Teardown — DTMF encryption key resources"

    echo ""
    warn "⚠️  DANGER: Deleting these resources means:"
    warn "   • Existing encrypted DTMF values CANNOT be decrypted"
    warn "   • In-flight calls using DTMF masking will fail"
    warn "   • You must also update all Connect flows to remove the security key"
    echo ""

    if ! ask_yn "Are you sure you want to proceed with teardown?" "N"; then
        echo "Aborted."
        exit 0
    fi

    local connect_instance_id connect_key_id secret_arn kms_key_id
    connect_instance_id=$(state_get "connect_instance_id" "")
    connect_key_id=$(state_get "connect_key_id" "")
    secret_arn=$(state_get "secret_arn" "")
    kms_key_id=$(state_get "kms_key_id" "")

    # ── Disassociate from Connect ──────────────────────────────────────────────
    if [[ -n "$connect_instance_id" && -n "$connect_key_id" ]]; then
        if ask_yn "Remove security key from Connect instance? (Key ID: ${connect_key_id})" "N"; then
            aws connect disassociate-security-key \
                --instance-id "$connect_instance_id" \
                --association-id "$connect_key_id" \
                --region "$REGION" 2>/dev/null && \
            ok "Security key removed from Connect" || \
            warn "Could not remove from Connect — may already be removed"
        fi
    else
        warn "No Connect key ID in state — skipping Connect disassociation"
    fi

    # ── Delete Secrets Manager secret ─────────────────────────────────────────
    if [[ -n "$secret_arn" ]]; then
        if ask_yn "Delete Secrets Manager secret? (ARN: ${secret_arn})" "N"; then
            aws secretsmanager delete-secret \
                --secret-id "$secret_arn" \
                --force-delete-without-recovery \
                --region "$REGION" 2>/dev/null && \
            ok "Secrets Manager secret deleted" || \
            warn "Could not delete secret — may already be deleted"
        fi
    fi

    # ── Schedule KMS key deletion (minimum 7 days, recommended 30) ────────────
    if [[ -n "$kms_key_id" ]]; then
        warn "KMS keys cannot be deleted immediately."
        warn "AWS enforces a minimum 7-day waiting period."
        if ask_yn "Schedule KMS key deletion (30-day waiting period)? (Key ID: ${kms_key_id})" "N"; then
            aws kms schedule-key-deletion \
                --key-id "$kms_key_id" \
                --pending-window-in-days 30 \
                --region "$REGION" 2>/dev/null && \
            ok "KMS key deletion scheduled (30 days)" || \
            warn "Could not schedule KMS deletion — check manually"
        fi
    fi

    # ── Clean up local files ───────────────────────────────────────────────────
    if [[ -d "$KEY_DIR" ]]; then
        if ask_yn "Remove local key directory? (${KEY_DIR})" "Y"; then
            rm -rf "$KEY_DIR"
            ok "Local key directory removed: ${KEY_DIR}"
        fi
    fi

    [[ -f "$STATE_FILE" ]] && rm "$STATE_FILE" && ok "State file removed"
    ok "Teardown complete"
}

# ── Main setup command ─────────────────────────────────────────────────────────
cmd_setup() {
    echo ""
    echo -e "${BOLD}${BLUE}═══════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}${BLUE}  ARIA — DTMF Encryption Key Setup${NC}"
    echo -e "${BOLD}${BLUE}  Meridian Bank / Amazon Connect${NC}"
    echo -e "${BOLD}${BLUE}═══════════════════════════════════════════════════${NC}"
    echo ""

    check_prerequisites
    gather_config
    generate_key_pair
    create_kms_key
    store_private_key
    register_connect_key
    print_setup_summary
}

# ── Argument parsing ───────────────────────────────────────────────────────────
parse_args() {
    COMMAND="${1:-help}"
    shift || true

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --region)             REGION="$2";               shift 2 ;;
            --instance-id)        CONNECT_INSTANCE_ID="$2";  shift 2 ;;
            --key-prefix)         KEY_PREFIX="$2";           shift 2 ;;
            --kms-alias)          KMS_ALIAS="$2";            shift 2 ;;
            --secret-name)        SECRET_NAME="$2";          shift 2 ;;
            *) die "Unknown argument: $1" ;;
        esac
    done
}

# ── Entry point ────────────────────────────────────────────────────────────────
main() {
    if [[ $# -eq 0 ]]; then
        echo ""
        echo "Usage: $0 <command> [options]"
        echo ""
        echo "Commands:"
        echo "  setup              — full first-time key setup"
        echo "  rotate             — add a second key for rotation"
        echo "  teardown           — remove all key resources (DANGER)"
        echo "  status             — print current state"
        echo "  register-key-id    — manually save a Connect Key ID to state"
        echo ""
        echo "Options:"
        echo "  --region <region>          AWS region (default: eu-west-2)"
        echo "  --instance-id <uuid>       Connect Instance ID"
        echo "  --key-prefix <prefix>      Key name prefix (default: meridian-connect)"
        echo "  --kms-alias <alias>        KMS alias (default: alias/meridian-connect-dtmf)"
        echo "  --secret-name <name>       Secrets Manager name"
        echo ""
        exit 0
    fi

    parse_args "$@"
    state_init

    case "$COMMAND" in
        setup)          cmd_setup        ;;
        rotate)         cmd_rotate       ;;
        teardown)       cmd_teardown     ;;
        status)         cmd_status       ;;
        register-key-id) cmd_register_key_id "${1:-}" ;;
        *)              die "Unknown command: ${COMMAND}. Run $0 for help." ;;
    esac
}

main "$@"
