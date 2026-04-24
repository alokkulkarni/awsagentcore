#!/usr/bin/env bash
# =============================================================================
# generate-rsa-keypair.sh
#
# Generates a 2048-bit RSA key pair, stores the private key in AWS Secrets
# Manager (encrypted with a KMS CMK), and prints the public key PEM for
# pasting into Amazon Connect Security Profiles > Security Keys.
#
# Usage:
#   ./generate-rsa-keypair.sh [OPTIONS]
#
# Options:
#   --region          AWS region (default: from AWS_DEFAULT_REGION or aws configure)
#   --environment     Short label used in resource names (default: prod)
#   --kms-key-alias   KMS key alias to use/create (default: alias/dtmf-secure-capture-<env>)
#   --secret-name     Secrets Manager secret name (default: dtmf-secure-capture/private-key-<env>)
#   --rotate          Rotate an existing secret — generates new keys and updates secret
#   --teardown        Delete the Secrets Manager secret (schedules 7-day recovery window)
#   -h, --help        Show this help message
#
# Prerequisites:
#   - openssl (1.1.1 or later)
#   - aws CLI v2, configured with credentials that have:
#       kms:CreateKey, kms:CreateAlias, kms:DescribeKey
#       secretsmanager:CreateSecret, secretsmanager:PutSecretValue,
#       secretsmanager:DeleteSecret, secretsmanager:DescribeSecret
#
# After running this script:
#   1. Copy the public key PEM printed to stdout
#   2. In the Amazon Connect console → Security Profiles → Security Keys → Add key
#      Paste the public key and save — note the Key ID returned.
#   3. Deploy the CloudFormation stack, passing:
#        PrivateKeySecretArn = <printed by this script>
#        ConnectEncryptionKeyId = <Key ID from Connect console, step 2>
# =============================================================================

set -euo pipefail

# ── Defaults ─────────────────────────────────────────────────────────────────
ENVIRONMENT="prod"
KMS_KEY_ALIAS=""
SECRET_NAME=""
AWS_REGION="${AWS_DEFAULT_REGION:-}"
MODE="generate"          # generate | rotate | teardown
TEMP_DIR=""

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; }
die()     { error "$*"; exit 1; }
heading() { echo -e "\n${BOLD}${CYAN}=== $* ===${RESET}"; }

# ── Cleanup ───────────────────────────────────────────────────────────────────
cleanup() {
    if [[ -n "${TEMP_DIR}" && -d "${TEMP_DIR}" ]]; then
        rm -rf "${TEMP_DIR}"
    fi
}
trap cleanup EXIT

# ── Help ──────────────────────────────────────────────────────────────────────
usage() {
    sed -n '/^# Usage:/,/^# After running/{ /^# After running/d; p }' "$0" \
        | sed 's/^# \?//'
    exit 0
}

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --region)          AWS_REGION="$2";       shift 2 ;;
        --environment)     ENVIRONMENT="$2";      shift 2 ;;
        --kms-key-alias)   KMS_KEY_ALIAS="$2";    shift 2 ;;
        --secret-name)     SECRET_NAME="$2";      shift 2 ;;
        --rotate)          MODE="rotate";          shift ;;
        --teardown)        MODE="teardown";        shift ;;
        -h|--help)         usage ;;
        *) die "Unknown option: $1. Run with --help for usage." ;;
    esac
done

# ── Apply defaults after arg parse ───────────────────────────────────────────
[[ -z "${KMS_KEY_ALIAS}" ]] && KMS_KEY_ALIAS="alias/dtmf-secure-capture-${ENVIRONMENT}"
[[ -z "${SECRET_NAME}" ]]   && SECRET_NAME="dtmf-secure-capture/private-key-${ENVIRONMENT}"

# ── Region resolution ─────────────────────────────────────────────────────────
if [[ -z "${AWS_REGION}" ]]; then
    AWS_REGION="$(aws configure get region 2>/dev/null || true)"
fi
[[ -z "${AWS_REGION}" ]] && die "AWS region is not set. Pass --region or configure AWS_DEFAULT_REGION."

AWS_REGION_ARGS="--region ${AWS_REGION}"

# ── Prerequisite checks ───────────────────────────────────────────────────────
check_prerequisites() {
    heading "Checking prerequisites"

    if ! command -v openssl &>/dev/null; then
        die "openssl is not installed. Install it with: brew install openssl (macOS) or apt-get install openssl (Linux)"
    fi
    OPENSSL_VERSION="$(openssl version 2>&1)"
    success "openssl found: ${OPENSSL_VERSION}"

    if ! command -v aws &>/dev/null; then
        die "AWS CLI v2 is not installed. See https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html"
    fi
    AWS_CLI_VERSION="$(aws --version 2>&1)"
    success "aws CLI found: ${AWS_CLI_VERSION}"

    # Verify credentials are working
    CALLER_IDENTITY="$(aws sts get-caller-identity ${AWS_REGION_ARGS} 2>&1)" \
        || die "AWS credentials not configured or invalid:\n${CALLER_IDENTITY}"
    AWS_ACCOUNT_ID="$(echo "${CALLER_IDENTITY}" | python3 -c "import sys,json; print(json.load(sys.stdin)['Account'])")"
    AWS_CALLER_ARN="$(echo "${CALLER_IDENTITY}" | python3 -c "import sys,json; print(json.load(sys.stdin)['Arn'])")"
    success "Authenticated as: ${AWS_CALLER_ARN}"
    success "Account ID: ${AWS_ACCOUNT_ID} | Region: ${AWS_REGION}"
}

# ── KMS key resolution / creation ────────────────────────────────────────────
ensure_kms_key() {
    heading "Resolving KMS key: ${KMS_KEY_ALIAS}"

    KMS_KEY_ID=""
    if aws kms describe-key ${AWS_REGION_ARGS} \
            --key-id "${KMS_KEY_ALIAS}" \
            --query "KeyMetadata.KeyId" \
            --output text 2>/dev/null | grep -qv "^None"; then
        KMS_KEY_ID="$(aws kms describe-key ${AWS_REGION_ARGS} \
            --key-id "${KMS_KEY_ALIAS}" \
            --query "KeyMetadata.KeyId" \
            --output text 2>/dev/null)"
        success "Using existing KMS key: ${KMS_KEY_ID} (${KMS_KEY_ALIAS})"
    else
        info "KMS alias not found — creating a new CMK…"
        KMS_KEY_ID="$(aws kms create-key ${AWS_REGION_ARGS} \
            --description "CMK for Secure DTMF Capture RSA private key — ${ENVIRONMENT}" \
            --key-usage ENCRYPT_DECRYPT \
            --key-spec SYMMETRIC_DEFAULT \
            --enable-key-rotation \
            --query "KeyMetadata.KeyId" \
            --output text)"
        success "Created KMS key: ${KMS_KEY_ID}"

        aws kms create-alias ${AWS_REGION_ARGS} \
            --alias-name "${KMS_KEY_ALIAS}" \
            --target-key-id "${KMS_KEY_ID}"
        success "Created alias: ${KMS_KEY_ALIAS} → ${KMS_KEY_ID}"
    fi

    KMS_KEY_ARN="$(aws kms describe-key ${AWS_REGION_ARGS} \
        --key-id "${KMS_KEY_ID}" \
        --query "KeyMetadata.Arn" \
        --output text)"
}

# ── RSA key pair generation ───────────────────────────────────────────────────
generate_keypair() {
    heading "Generating RSA-2048 key pair"

    TEMP_DIR="$(mktemp -d)"
    PRIVATE_KEY_FILE="${TEMP_DIR}/private_key.pem"
    PUBLIC_KEY_FILE="${TEMP_DIR}/public_key.pem"

    openssl genrsa -out "${PRIVATE_KEY_FILE}" 2048 2>/dev/null
    openssl rsa -in "${PRIVATE_KEY_FILE}" -pubout -out "${PUBLIC_KEY_FILE}" 2>/dev/null
    success "RSA-2048 key pair generated (temporary files in ${TEMP_DIR})"

    PRIVATE_KEY_PEM="$(cat "${PRIVATE_KEY_FILE}")"
    PUBLIC_KEY_PEM="$(cat "${PUBLIC_KEY_FILE}")"
}

# ── Store private key in Secrets Manager ─────────────────────────────────────
store_secret() {
    local operation="$1"   # create | update

    heading "Storing private key in Secrets Manager: ${SECRET_NAME}"

    local secret_value
    secret_value="$(python3 -c "
import json, sys
pem = open('${TEMP_DIR}/private_key.pem').read()
print(json.dumps({'private_key_pem': pem, 'environment': '${ENVIRONMENT}'}))
")"

    if [[ "${operation}" == "create" ]]; then
        SECRET_ARN="$(aws secretsmanager create-secret ${AWS_REGION_ARGS} \
            --name "${SECRET_NAME}" \
            --description "RSA-2048 private key for Secure DTMF Capture — ${ENVIRONMENT}" \
            --kms-key-id "${KMS_KEY_ARN}" \
            --secret-string "${secret_value}" \
            --query "ARN" \
            --output text)"
        success "Secret created: ${SECRET_ARN}"
    else
        # Rotation — update existing secret value
        SECRET_ARN="$(aws secretsmanager describe-secret ${AWS_REGION_ARGS} \
            --secret-id "${SECRET_NAME}" \
            --query "ARN" \
            --output text 2>/dev/null)" \
            || die "Secret '${SECRET_NAME}' not found. Run without --rotate to create it first."

        aws secretsmanager put-secret-value ${AWS_REGION_ARGS} \
            --secret-id "${SECRET_NAME}" \
            --secret-string "${secret_value}" \
            --version-stages AWSCURRENT \
            >/dev/null
        success "Secret updated (rotated): ${SECRET_ARN}"
    fi
}

# ── Check if secret already exists ───────────────────────────────────────────
secret_exists() {
    aws secretsmanager describe-secret ${AWS_REGION_ARGS} \
        --secret-id "${SECRET_NAME}" \
        --query "ARN" \
        --output text 2>/dev/null | grep -q "arn:aws"
}

# ── Print public key and summary ──────────────────────────────────────────────
print_summary() {
    echo ""
    echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════════${RESET}"
    echo -e "${BOLD}${GREEN}  RSA PUBLIC KEY — paste this into Amazon Connect${RESET}"
    echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════════${RESET}"
    echo ""
    echo "${PUBLIC_KEY_PEM}"
    echo ""
    echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════════${RESET}"
    echo ""

    echo -e "${BOLD}Next Steps:${RESET}"
    echo ""
    echo -e "  ${BOLD}1.${RESET} Copy the public key PEM above."
    echo ""
    echo -e "  ${BOLD}2.${RESET} In the ${CYAN}Amazon Connect console${RESET}:"
    echo -e "       Console → Your instance → Security Profiles → Security Keys"
    echo -e "       Click ${BOLD}Add key${RESET}, paste the public key, and click ${BOLD}Save${RESET}."
    echo -e "       Note the ${BOLD}Key ID${RESET} that Connect displays — you will need it next."
    echo ""
    echo -e "  ${BOLD}3.${RESET} Deploy the CloudFormation stack with these parameters:"
    echo ""
    echo -e "       ${CYAN}PrivateKeySecretArn${RESET}  = ${BOLD}${SECRET_ARN}${RESET}"
    echo -e "       ${CYAN}ConnectEncryptionKeyId${RESET} = <Key ID from Connect, step 2>"
    echo ""
    echo -e "  ${BOLD}4.${RESET} After the stack is CREATE_COMPLETE, run:"
    echo -e "       ${BOLD}./scripts/deploy_dtmf_lambda.sh deploy${RESET}"
    echo -e "       to upload the real Lambda code and agent panel HTML."
    echo ""
    echo -e "  ${BOLD}5.${RESET} Import the contact flow templates from ${CYAN}marketplace/contact-flows/${RESET}"
    echo -e "       and configure the Lambda ARNs from CFN Outputs."
    echo ""

    echo -e "${BOLD}Resource Summary:${RESET}"
    echo -e "  KMS Key ARN     : ${KMS_KEY_ARN}"
    echo -e "  Secret Name     : ${SECRET_NAME}"
    echo -e "  Secret ARN      : ${SECRET_ARN}"
    echo -e "  AWS Region      : ${AWS_REGION}"
    echo -e "  Environment     : ${ENVIRONMENT}"
    echo ""
}

# ── Teardown mode ─────────────────────────────────────────────────────────────
do_teardown() {
    heading "Teardown — deleting Secrets Manager secret"

    warn "This will schedule deletion of '${SECRET_NAME}' with a 7-day recovery window."
    warn "The KMS key alias '${KMS_KEY_ALIAS}' will NOT be deleted (manual step)."
    echo -n "Type 'DELETE' to confirm: "
    read -r confirmation
    [[ "${confirmation}" == "DELETE" ]] || die "Aborted — confirmation not received."

    aws secretsmanager delete-secret ${AWS_REGION_ARGS} \
        --secret-id "${SECRET_NAME}" \
        --recovery-window-in-days 7 \
        >/dev/null
    success "Secret '${SECRET_NAME}' scheduled for deletion in 7 days."
    info "To immediately destroy (no recovery): add --force-delete-without-recovery to the aws command above."
    info "KMS key alias '${KMS_KEY_ALIAS}' retained — delete manually if no longer needed:"
    info "  aws kms delete-alias --alias-name '${KMS_KEY_ALIAS}' --region ${AWS_REGION}"
    info "  aws kms schedule-key-deletion --key-id '${KMS_KEY_ID}' --pending-window-in-days 7 --region ${AWS_REGION}"
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
    echo -e "${BOLD}Secure DTMF Capture — RSA Key Pair Generator${RESET}"
    echo -e "Mode: ${CYAN}${MODE}${RESET} | Environment: ${CYAN}${ENVIRONMENT}${RESET} | Region: ${CYAN}${AWS_REGION:-<auto>}${RESET}"
    echo ""

    check_prerequisites

    case "${MODE}" in
        teardown)
            ensure_kms_key
            do_teardown
            ;;

        rotate)
            ensure_kms_key
            generate_keypair

            if ! secret_exists; then
                die "Secret '${SECRET_NAME}' does not exist. Run without --rotate to create it first."
            fi

            warn "Key rotation will replace the private key in Secrets Manager."
            warn "You MUST also update the public key in Amazon Connect Security Keys after rotation."
            echo -n "Continue? [y/N]: "
            read -r confirm
            [[ "${confirm,,}" == "y" ]] || die "Rotation aborted."

            store_secret "update"
            echo ""
            success "Key rotation complete."
            warn "IMPORTANT: You must now upload the new public key to Amazon Connect:"
            warn "  Console → Security Profiles → Security Keys → Add key (and remove the old key)"
            print_summary
            ;;

        generate)
            ensure_kms_key

            if secret_exists; then
                warn "A secret named '${SECRET_NAME}' already exists."
                warn "Use --rotate to replace the key, or --teardown to delete it first."
                die "Aborting to avoid overwriting an existing secret."
            fi

            generate_keypair
            store_secret "create"
            print_summary
            ;;

        *)
            die "Unknown mode: ${MODE}"
            ;;
    esac
}

main "$@"
