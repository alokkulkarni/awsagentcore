#!/usr/bin/env bash
# =============================================================================
#  deploy_webrtc_api.sh — WebRTC Contact API: local / Docker / Lambda deploy
# =============================================================================
#
#  USAGE
#    ./scripts/deploy_webrtc_api.sh local    — run locally with uvicorn
#    ./scripts/deploy_webrtc_api.sh docker   — build & run Docker container
#    ./scripts/deploy_webrtc_api.sh lambda   — package & deploy to AWS Lambda
#                                              (with Function URL, IAM roles)
#    ./scripts/deploy_webrtc_api.sh teardown — remove Lambda + IAM resources
#
#  PREREQUISITES
#    local:   pip install -r requirements-webrtc.txt   (Python 3.12+)
#    docker:  Docker Desktop / Docker Engine
#    lambda:  aws CLI v2, Python 3.12+, zip
#
#  AUTH MODEL
#    • local:   DEV_MODE=true — SigV4 verification bypassed (dev only)
#    • docker:  DEV_MODE=true by default; set false + pass temp creds for
#               end-to-end SigV4 testing against a real Connect instance
#    • lambda:  Lambda Function URL with authType=AWS_IAM — SigV4 enforced
#               by AWS infrastructure; application reads verified identity
#
#  REQUIRED ENV VARS (all modes except --help)
#    CONNECT_INSTANCE_ID      Amazon Connect instance ID (UUID)
#    CONNECT_CONTACT_FLOW_ID  Inbound WebRTC contact flow ID (UUID)
#
#  OPTIONAL ENV VARS
#    AWS_REGION               (default: eu-west-2)
#    ALLOWED_ORIGINS          Comma-separated CORS origins (default: *)
#    ALLOWED_PRINCIPAL_ARNS   Comma-separated IAM ARN patterns to allowlist
#    LOG_LEVEL                DEBUG|INFO|WARNING|ERROR (default: INFO)
#
#  LAMBDA-SPECIFIC ENV VARS
#    LAMBDA_FUNCTION_NAME     (default: aria-webrtc-api)
#    LAMBDA_ROLE_NAME         Execution role name (default: aria-webrtc-api-exec-role)
#    LAMBDA_CLIENT_ROLE_NAME  Client role name (default: aria-webrtc-client-role)
#    LAMBDA_MEMORY_MB         (default: 256)
#    LAMBDA_TIMEOUT_S         (default: 10)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

header() { echo -e "\n${BOLD}${BLUE}══ $* ══${NC}"; }
step()   { echo -e "${CYAN}  ▶ $*${NC}"; }
ok()     { echo -e "${GREEN}  ✔ $*${NC}"; }
warn()   { echo -e "${YELLOW}  ⚠ $*${NC}"; }
die()    { echo -e "${RED}  ✖ $*${NC}" >&2; exit 1; }

# ── Defaults ──────────────────────────────────────────────────────────────────
AWS_REGION="${AWS_REGION:-eu-west-2}"
LAMBDA_FUNCTION_NAME="${LAMBDA_FUNCTION_NAME:-aria-webrtc-api}"
LAMBDA_ROLE_NAME="${LAMBDA_ROLE_NAME:-aria-webrtc-api-exec-role}"
LAMBDA_CLIENT_ROLE_NAME="${LAMBDA_CLIENT_ROLE_NAME:-aria-webrtc-client-role}"
LAMBDA_MEMORY_MB="${LAMBDA_MEMORY_MB:-256}"
LAMBDA_TIMEOUT_S="${LAMBDA_TIMEOUT_S:-10}"
ALLOWED_ORIGINS="${ALLOWED_ORIGINS:-*}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"
PORT="${PORT:-8080}"
IMAGE_NAME="aria-webrtc-api"

# ── Validate required env vars ────────────────────────────────────────────────
require_connect_env() {
    local missing=()
    [[ -z "${CONNECT_INSTANCE_ID:-}" ]]     && missing+=("CONNECT_INSTANCE_ID")
    [[ -z "${CONNECT_CONTACT_FLOW_ID:-}" ]] && missing+=("CONNECT_CONTACT_FLOW_ID")
    if [[ ${#missing[@]} -gt 0 ]]; then
        die "Required environment variables not set: ${missing[*]}"
    fi
}

# =============================================================================
#  LOCAL MODE — uvicorn with DEV_MODE=true
# =============================================================================
cmd_local() {
    header "WebRTC API — Local (uvicorn, DEV_MODE)"
    require_connect_env

    step "Checking requirements"
    python3 -c "import fastapi, uvicorn, boto3, pydantic" 2>/dev/null || {
        warn "Missing packages — installing requirements-webrtc.txt"
        pip install -q -r "${PROJECT_ROOT}/requirements-webrtc.txt"
    }

    ok "Starting uvicorn on http://localhost:${PORT}"
    warn "DEV_MODE=true — SigV4 auth bypassed (local dev only)"
    echo ""
    echo "  Endpoints:"
    echo "    GET  http://localhost:${PORT}/health"
    echo "    POST http://localhost:${PORT}/webrtc/start-contact"
    echo "    POST http://localhost:${PORT}/webrtc/participant-connection"
    echo "    DEL  http://localhost:${PORT}/webrtc/end-contact/{id}"
    echo ""

    cd "${PROJECT_ROOT}"
    DEV_MODE=true \
    CONNECT_INSTANCE_ID="${CONNECT_INSTANCE_ID}" \
    CONNECT_CONTACT_FLOW_ID="${CONNECT_CONTACT_FLOW_ID}" \
    AWS_REGION="${AWS_REGION}" \
    ALLOWED_ORIGINS="${ALLOWED_ORIGINS}" \
    LOG_LEVEL="${LOG_LEVEL}" \
    uvicorn api.webrtc.app:app \
        --host 0.0.0.0 \
        --port "${PORT}" \
        --reload \
        --log-level "$(echo "${LOG_LEVEL}" | tr '[:upper:]' '[:lower:]')"
}

# =============================================================================
#  DOCKER MODE — build image and run container
# =============================================================================
cmd_docker() {
    header "WebRTC API — Docker"
    require_connect_env
    command -v docker >/dev/null 2>&1 || die "Docker not found. Install Docker Desktop."

    # ── Build ─────────────────────────────────────────────────────────────────
    step "Building Docker image: ${IMAGE_NAME}"
    docker build \
        -f "${PROJECT_ROOT}/api/webrtc/Dockerfile" \
        -t "${IMAGE_NAME}:latest" \
        "${PROJECT_ROOT}"
    ok "Image built: ${IMAGE_NAME}:latest"

    # ── Run ───────────────────────────────────────────────────────────────────
    step "Starting container on port ${PORT}"
    warn "DEV_MODE=true — SigV4 auth bypassed (local dev only)"
    echo ""
    echo "  To test with real SigV4 (end-to-end):"
    echo "    Set DEV_MODE=false and pass AWS_ACCESS_KEY_ID / SECRET / SESSION_TOKEN"
    echo "    that have connect:StartWebRTCContact permission on your instance."
    echo ""

    # Pass through AWS credentials from host env (for local SigV4 testing)
    local aws_env_flags=""
    [[ -n "${AWS_ACCESS_KEY_ID:-}"     ]] && aws_env_flags+="-e AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID} "
    [[ -n "${AWS_SECRET_ACCESS_KEY:-}" ]] && aws_env_flags+="-e AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY} "
    [[ -n "${AWS_SESSION_TOKEN:-}"     ]] && aws_env_flags+="-e AWS_SESSION_TOKEN=${AWS_SESSION_TOKEN} "

    docker run --rm -it \
        -p "${PORT}:8080" \
        -e DEV_MODE="${DEV_MODE:-true}" \
        -e CONNECT_INSTANCE_ID="${CONNECT_INSTANCE_ID}" \
        -e CONNECT_CONTACT_FLOW_ID="${CONNECT_CONTACT_FLOW_ID}" \
        -e AWS_REGION="${AWS_REGION}" \
        -e ALLOWED_ORIGINS="${ALLOWED_ORIGINS}" \
        -e LOG_LEVEL="${LOG_LEVEL}" \
        ${aws_env_flags} \
        "${IMAGE_NAME}:latest"
}

# =============================================================================
#  LAMBDA MODE — package, deploy, configure Function URL + IAM
# =============================================================================
cmd_lambda() {
    header "WebRTC API — Lambda Deploy"
    require_connect_env
    command -v aws  >/dev/null 2>&1 || die "aws CLI not found."
    command -v zip  >/dev/null 2>&1 || die "zip not found."
    command -v pip  >/dev/null 2>&1 || die "pip not found."
    command -v python3 >/dev/null 2>&1 || die "python3 not found."

    local account_id
    account_id=$(aws sts get-caller-identity --query Account --output text)
    ok "AWS account: ${account_id}  region: ${AWS_REGION}"

    # ── Step 1: Build deployment zip ─────────────────────────────────────────
    header "Building Lambda deployment zip"
    local build_dir="${PROJECT_ROOT}/.lambda-build"
    local zip_path="${PROJECT_ROOT}/.lambda-build/aria-webrtc-api.zip"
    rm -rf "${build_dir}" && mkdir -p "${build_dir}/package"

    step "Installing dependencies into package/"
    pip install -q \
        --target "${build_dir}/package" \
        --requirement "${PROJECT_ROOT}/requirements-webrtc.txt"

    step "Copying api/ package"
    cp -r "${PROJECT_ROOT}/api" "${build_dir}/package/"

    step "Creating zip archive"
    cd "${build_dir}/package"
    zip -r9 "${zip_path}" . -x "*.pyc" -x "*/__pycache__/*" -x "*.dist-info/*" > /dev/null
    cd "${PROJECT_ROOT}"
    ok "Zip ready: ${zip_path} ($(du -sh "${zip_path}" | cut -f1))"

    # ── Step 2: Execution role ────────────────────────────────────────────────
    header "Execution role: ${LAMBDA_ROLE_NAME}"
    local exec_role_arn
    exec_role_arn=$(aws iam get-role \
        --role-name "${LAMBDA_ROLE_NAME}" \
        --query "Role.Arn" --output text 2>/dev/null || true)

    if [[ -z "$exec_role_arn" || "$exec_role_arn" == "None" ]]; then
        step "Creating execution role"
        local trust_doc
        trust_doc=$(python3 -c "
import json
print(json.dumps({
    'Version': '2012-10-17',
    'Statement': [{
        'Effect': 'Allow',
        'Principal': {'Service': 'lambda.amazonaws.com'},
        'Action': 'sts:AssumeRole'
    }]
}))
")
        exec_role_arn=$(aws iam create-role \
            --role-name "${LAMBDA_ROLE_NAME}" \
            --assume-role-policy-document "${trust_doc}" \
            --query "Role.Arn" --output text)
        ok "Role created: ${exec_role_arn}"
    else
        ok "Role exists: ${exec_role_arn}"
    fi

    step "Attaching AWSLambdaBasicExecutionRole"
    aws iam attach-role-policy \
        --role-name "${LAMBDA_ROLE_NAME}" \
        --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" \
        2>/dev/null || true

    step "Attaching inline Connect policy"
    local connect_policy
    connect_policy=$(python3 -c "
import json
print(json.dumps({
    'Version': '2012-10-17',
    'Statement': [
        {
            'Sid': 'ConnectWebRTCContacts',
            'Effect': 'Allow',
            'Action': ['connect:StartWebRTCContact','connect:StopContact','connect:GetContactAttributes'],
            'Resource': 'arn:aws:connect:${AWS_REGION}:${account_id}:instance/${CONNECT_INSTANCE_ID}/contact/*'
        },
        {
            'Sid': 'ConnectInstanceDescribe',
            'Effect': 'Allow',
            'Action': ['connect:DescribeInstance'],
            'Resource': 'arn:aws:connect:${AWS_REGION}:${account_id}:instance/${CONNECT_INSTANCE_ID}'
        }
    ]
}))
")
    aws iam put-role-policy \
        --role-name "${LAMBDA_ROLE_NAME}" \
        --policy-name "ConnectWebRTCContacts" \
        --policy-document "${connect_policy}"
    ok "Connect policy attached"

    # Brief wait for role to propagate
    step "Waiting 10s for IAM role propagation"
    sleep 10

    # ── Step 3: Create or update Lambda function ──────────────────────────────
    header "Lambda function: ${LAMBDA_FUNCTION_NAME}"
    local function_arn
    function_arn=$(aws lambda get-function \
        --function-name "${LAMBDA_FUNCTION_NAME}" \
        --query "Configuration.FunctionArn" --output text 2>/dev/null || true)

    local env_vars
    env_vars="Variables={\
CONNECT_INSTANCE_ID=${CONNECT_INSTANCE_ID},\
CONNECT_CONTACT_FLOW_ID=${CONNECT_CONTACT_FLOW_ID},\
AWS_REGION_OVERRIDE=${AWS_REGION},\
ALLOWED_ORIGINS=${ALLOWED_ORIGINS},\
LOG_LEVEL=${LOG_LEVEL},\
DEV_MODE=false\
$([ -n "${ALLOWED_PRINCIPAL_ARNS:-}" ] && echo ",ALLOWED_PRINCIPAL_ARNS=${ALLOWED_PRINCIPAL_ARNS}")}"

    if [[ -z "$function_arn" || "$function_arn" == "None" ]]; then
        step "Creating Lambda function (arm64)"
        function_arn=$(aws lambda create-function \
            --function-name "${LAMBDA_FUNCTION_NAME}" \
            --runtime python3.12 \
            --architectures arm64 \
            --handler "api.webrtc.lambda_handler.handler" \
            --role "${exec_role_arn}" \
            --zip-file "fileb://${zip_path}" \
            --memory-size "${LAMBDA_MEMORY_MB}" \
            --timeout "${LAMBDA_TIMEOUT_S}" \
            --environment "${env_vars}" \
            --region "${AWS_REGION}" \
            --query "FunctionArn" --output text)
        ok "Function created: ${function_arn}"

        step "Waiting for function to become Active"
        aws lambda wait function-active \
            --function-name "${LAMBDA_FUNCTION_NAME}" \
            --region "${AWS_REGION}"
        ok "Function Active"
    else
        step "Updating function code"
        aws lambda update-function-code \
            --function-name "${LAMBDA_FUNCTION_NAME}" \
            --zip-file "fileb://${zip_path}" \
            --architectures arm64 \
            --region "${AWS_REGION}" \
            --query "FunctionArn" --output text > /dev/null
        aws lambda wait function-updated \
            --function-name "${LAMBDA_FUNCTION_NAME}" \
            --region "${AWS_REGION}"

        step "Updating function configuration"
        aws lambda update-function-configuration \
            --function-name "${LAMBDA_FUNCTION_NAME}" \
            --memory-size "${LAMBDA_MEMORY_MB}" \
            --timeout "${LAMBDA_TIMEOUT_S}" \
            --environment "${env_vars}" \
            --region "${AWS_REGION}" > /dev/null
        aws lambda wait function-updated \
            --function-name "${LAMBDA_FUNCTION_NAME}" \
            --region "${AWS_REGION}"
        ok "Function updated: ${function_arn}"
    fi

    # ── Step 4: Function URL with AWS_IAM auth ────────────────────────────────
    header "Lambda Function URL (authType=AWS_IAM)"
    local function_url
    function_url=$(aws lambda get-function-url-config \
        --function-name "${LAMBDA_FUNCTION_NAME}" \
        --region "${AWS_REGION}" \
        --query "FunctionUrl" --output text 2>/dev/null || true)

    local cors_config
    cors_config=$(python3 -c "
import json
origins = '${ALLOWED_ORIGINS}'.split(',')
print('AllowOrigins=' + json.dumps(origins) +
      ',AllowMethods=[\"GET\",\"POST\",\"DELETE\",\"OPTIONS\"]' +
      ',AllowHeaders=[\"*\"]' +
      ',AllowCredentials=true' +
      ',MaxAge=300')
")

    if [[ -z "$function_url" || "$function_url" == "None" ]]; then
        step "Creating Function URL with AWS_IAM auth"
        function_url=$(aws lambda create-function-url-config \
            --function-name "${LAMBDA_FUNCTION_NAME}" \
            --auth-type AWS_IAM \
            --cors "AllowOrigins=[\"${ALLOWED_ORIGINS}\"],AllowMethods=[\"GET\",\"POST\",\"DELETE\",\"OPTIONS\"],AllowHeaders=[\"*\"],AllowCredentials=true,MaxAge=300" \
            --region "${AWS_REGION}" \
            --query "FunctionUrl" --output text)
        ok "Function URL created: ${function_url}"
    else
        step "Function URL already exists: ${function_url}"
        aws lambda update-function-url-config \
            --function-name "${LAMBDA_FUNCTION_NAME}" \
            --auth-type AWS_IAM \
            --cors "AllowOrigins=[\"${ALLOWED_ORIGINS}\"],AllowMethods=[\"GET\",\"POST\",\"DELETE\",\"OPTIONS\"],AllowHeaders=[\"*\"],AllowCredentials=true,MaxAge=300" \
            --region "${AWS_REGION}" > /dev/null
        ok "Function URL updated"
    fi

    # ── Step 5: Client IAM role ───────────────────────────────────────────────
    header "Client role: ${LAMBDA_CLIENT_ROLE_NAME}"
    local client_role_arn
    client_role_arn=$(aws iam get-role \
        --role-name "${LAMBDA_CLIENT_ROLE_NAME}" \
        --query "Role.Arn" --output text 2>/dev/null || true)

    if [[ -z "$client_role_arn" || "$client_role_arn" == "None" ]]; then
        step "Creating client role (trust: Cognito Identity Pool)"
        warn "Update the trust policy in scripts/iam/webrtc_client_trust_policy.json"
        warn "with your OIDC provider / Cognito pool details, then re-run."
        local stub_trust
        stub_trust=$(python3 -c "
import json
print(json.dumps({
    'Version': '2012-10-17',
    'Statement': [{
        'Effect': 'Allow',
        'Principal': {'Federated': 'cognito-identity.amazonaws.com'},
        'Action': 'sts:AssumeRoleWithWebIdentity',
        'Condition': {
            'StringEquals': {'cognito-identity.amazonaws.com:aud': 'REPLACE_WITH_IDENTITY_POOL_ID'},
            'ForAnyValue:StringLike': {'cognito-identity.amazonaws.com:amr': 'authenticated'}
        }
    }]
}))
")
        client_role_arn=$(aws iam create-role \
            --role-name "${LAMBDA_CLIENT_ROLE_NAME}" \
            --assume-role-policy-document "${stub_trust}" \
            --query "Role.Arn" --output text)
        ok "Client role created (stub trust policy): ${client_role_arn}"
    else
        ok "Client role exists: ${client_role_arn}"
    fi

    step "Granting client role permission to invoke Function URL"
    aws lambda add-permission \
        --function-name "${LAMBDA_FUNCTION_NAME}" \
        --statement-id "AllowClientRoleInvoke" \
        --action "lambda:InvokeFunctionUrl" \
        --principal "${client_role_arn}" \
        --function-url-auth-type "AWS_IAM" \
        --region "${AWS_REGION}" \
        2>/dev/null && ok "Permission granted" \
        || warn "Permission already exists (or failed — check manually)"

    step "Attaching inline policy to client role"
    local client_policy
    client_policy=$(python3 -c "
import json
print(json.dumps({
    'Version': '2012-10-17',
    'Statement': [{
        'Sid': 'InvokeWebRTCLambdaFunctionURL',
        'Effect': 'Allow',
        'Action': ['lambda:InvokeFunctionUrl'],
        'Resource': 'arn:aws:lambda:${AWS_REGION}:${account_id}:function:${LAMBDA_FUNCTION_NAME}',
        'Condition': {'StringEquals': {'lambda:FunctionUrlAuthType': 'AWS_IAM'}}
    }]
}))
")
    aws iam put-role-policy \
        --role-name "${LAMBDA_CLIENT_ROLE_NAME}" \
        --policy-name "InvokeWebRTCFunctionURL" \
        --policy-document "${client_policy}"
    ok "Client role policy attached"

    # ── Step 6: Cleanup build artifacts ──────────────────────────────────────
    rm -rf "${build_dir}"

    # ── Summary ───────────────────────────────────────────────────────────────
    echo ""
    echo -e "${BOLD}${GREEN}  ✔ Lambda deployment complete${NC}"
    echo ""
    echo "  ┌──────────────────────────────────────────────────────────────┐"
    printf "  │  %-30s %-30s │\n" "Function:"   "${LAMBDA_FUNCTION_NAME}"
    printf "  │  %-30s %-30s │\n" "Function URL:" "${function_url}"
    printf "  │  %-30s %-30s │\n" "Auth:"        "AWS_IAM (SigV4)"
    printf "  │  %-30s %-30s │\n" "Exec role:"   "${LAMBDA_ROLE_NAME}"
    printf "  │  %-30s %-30s │\n" "Client role:" "${LAMBDA_CLIENT_ROLE_NAME}"
    echo "  └──────────────────────────────────────────────────────────────┘"
    echo ""
    echo "  Next steps:"
    echo "    1. Update scripts/iam/webrtc_client_trust_policy.json with your"
    echo "       Cognito User Pool / OIDC provider details."
    echo "    2. Clients call sts:AssumeRoleWithWebIdentity with an ID token"
    echo "       to get temporary credentials."
    echo "    3. Sign requests with SigV4 (service=lambda) using those creds."
    echo "    4. Call: POST ${function_url}webrtc/start-contact"
    echo ""
    echo "  Health check (no auth required):"
    echo "    curl ${function_url}health"
    echo ""
}

# =============================================================================
#  TEARDOWN — remove Lambda + IAM resources
# =============================================================================
cmd_teardown() {
    header "WebRTC API — Teardown"
    command -v aws >/dev/null 2>&1 || die "aws CLI not found."

    echo -e "${RED}${BOLD}  This will delete the Lambda function, Function URL, and IAM roles.${NC}"
    printf "${BOLD}  ? Are you sure? [y/N]: ${NC}"
    read -r confirm
    [[ "${confirm,,}" == "y" ]] || { echo "  Cancelled."; exit 0; }

    step "Deleting Lambda function: ${LAMBDA_FUNCTION_NAME}"
    aws lambda delete-function \
        --function-name "${LAMBDA_FUNCTION_NAME}" \
        --region "${AWS_REGION}" 2>/dev/null \
        && ok "Function deleted" || warn "Function not found"

    step "Detaching / deleting execution role: ${LAMBDA_ROLE_NAME}"
    aws iam detach-role-policy \
        --role-name "${LAMBDA_ROLE_NAME}" \
        --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" \
        2>/dev/null || true
    aws iam delete-role-policy \
        --role-name "${LAMBDA_ROLE_NAME}" \
        --policy-name "ConnectWebRTCContacts" 2>/dev/null || true
    aws iam delete-role \
        --role-name "${LAMBDA_ROLE_NAME}" 2>/dev/null \
        && ok "Exec role deleted" || warn "Exec role not found"

    step "Deleting client role: ${LAMBDA_CLIENT_ROLE_NAME}"
    aws iam delete-role-policy \
        --role-name "${LAMBDA_CLIENT_ROLE_NAME}" \
        --policy-name "InvokeWebRTCFunctionURL" 2>/dev/null || true
    aws iam delete-role \
        --role-name "${LAMBDA_CLIENT_ROLE_NAME}" 2>/dev/null \
        && ok "Client role deleted" || warn "Client role not found"

    ok "Teardown complete"
}

# =============================================================================
#  Entrypoint
# =============================================================================
usage() {
    echo ""
    echo "  Usage: $0 <command>"
    echo ""
    echo "  Commands:"
    echo "    local    — run locally with uvicorn (DEV_MODE, no SigV4)"
    echo "    docker   — build Docker image and run container"
    echo "    lambda   — package and deploy to AWS Lambda + Function URL"
    echo "    teardown — delete Lambda function and IAM roles"
    echo ""
    echo "  Required env vars (all commands):"
    echo "    CONNECT_INSTANCE_ID      Amazon Connect instance ID"
    echo "    CONNECT_CONTACT_FLOW_ID  Inbound WebRTC contact flow ID"
    echo ""
    echo "  See script header for full options."
    echo ""
}

case "${1:-}" in
    local)    cmd_local    ;;
    docker)   cmd_docker   ;;
    lambda)   cmd_lambda   ;;
    teardown) cmd_teardown ;;
    *)        usage; exit 1 ;;
esac
