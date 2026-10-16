#!/usr/bin/env bash
# =============================================================================
# deploy_agent.sh
# =============================================================================
# Builds the Strands Money Hub agent and deploys it to AgentCore Runtime
# (README step 3).
#
# YOU run this script. It makes changes in your AWS account:
#   1. ECR repository aria-money-hub-agent (scan on push)
#   2. IAM role aria-money-hub-agent-runtime-role: trusted by AgentCore only
#      (this account), allowed to pull its image, write logs and traces, call
#      Bedrock models, and read and write the Money Hub table
#   3. An ARM64 container image, built with docker buildx and pushed
#   4. AgentCore Runtime aria_money_hub_agent (HTTP protocol, IAM-only access),
#      created or updated to the new image, and waited on until READY
#   5. A test turn for James, and the runtime ARN for the bridge (step 4)
#
# Usage:
#   ./connect-money-hub/scripts/deploy_agent.sh [--region R] [--account-id A] [--model MODEL_ID] [--dry-run]
#
# Requirements: Docker with buildx (ARM64 builds), AWS CLI v2.27+, python3.
# Run deploy_money_hub.sh first: the agent uses its table and page address.
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; RESET='\033[0m'
ok()     { echo -e "${GREEN}[ OK ] $*${RESET}"; }
warn()   { echo -e "${YELLOW}[WARN] $*${RESET}"; }
step()   { echo -e "${CYAN}[....] $*${RESET}"; }
die()    { echo -e "${RED}[FAIL] $*${RESET}" >&2; exit 1; }
header() { echo -e "\n${CYAN}== $* ==${RESET}"; }

REGION="${AWS_REGION:-eu-west-2}"
ACCOUNT_ID="${AWS_ACCOUNT_ID:-395402194296}"
MODEL_ID="eu.anthropic.claude-haiku-4-5-20251001-v1:0"
DRY_RUN=false
REPO="aria-money-hub-agent"
ROLE_NAME="aria-money-hub-agent-runtime-role"
RUNTIME_NAME="aria_money_hub_agent"        # runtime names allow letters, digits and underscores only
TABLE_NAME="aria-money-hub"
API_FUNCTION="aria-money-hub-api"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="${SCRIPT_DIR}/.."

while [[ $# -gt 0 ]]; do
    case "$1" in
        --region)     REGION="$2"; shift 2 ;;
        --account-id) ACCOUNT_ID="$2"; shift 2 ;;
        --model)      MODEL_ID="$2"; shift 2 ;;
        --dry-run)    DRY_RUN=true; shift ;;
        --help|-h)    sed -n '/^# Usage:/,/^# Requirements:/p' "$0" | sed -E 's/^# ?//'; exit 0 ;;
        *) die "Unknown argument: $1" ;;
    esac
done

for tool in aws python3 docker; do command -v "$tool" >/dev/null || die "${tool} not found on PATH."; done
docker buildx version >/dev/null 2>&1 || die "docker buildx is needed for ARM64 builds. Install or enable it."
aws bedrock-agentcore-control help >/dev/null 2>&1 || die "Your AWS CLI has no bedrock-agentcore-control. Update to v2.27+."
CALLER=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) || die "Sign in with the AWS CLI first."
[[ "$CALLER" == "$ACCOUNT_ID" ]] || die "Signed in to ${CALLER}, but the target is ${ACCOUNT_ID}."
ok "Signed in to ${ACCOUNT_ID}; Docker buildx found."

if $DRY_RUN; then warn "DRY-RUN: no changes."; run() { echo "  [dry-run] $*"; }; else run() { "$@"; }; fi
first_value() { tr -s '[:space:]' '\n' | grep -v -e '^None$' -e '^$' | head -n 1 || true; }
BUILD="$(mktemp -d)"; trap 'rm -rf "$BUILD"' EXIT
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
IMAGE="${REGISTRY}/${REPO}"
TAG="v$(date +%Y%m%d%H%M%S)"
PAGE_URL=$({ aws lambda get-function-configuration --function-name "$API_FUNCTION" --region "$REGION" \
    --query Environment.Variables.PUBLIC_BASE_URL --output text 2>/dev/null || true; } | first_value)
[[ -n "$PAGE_URL" ]] || warn "No Money Hub page address found: run deploy_money_hub.sh first, or links will be blank."

header "Step 1 - ECR repository ${REPO}"
aws ecr describe-repositories --repository-names "$REPO" --region "$REGION" >/dev/null 2>&1 || \
    run aws ecr create-repository --repository-name "$REPO" --region "$REGION" \
        --image-scanning-configuration scanOnPush=true --query repository.repositoryUri --output text >/dev/null
ok "Repository ready."

header "Step 2 - Runtime role ${ROLE_NAME}"
cat > "$BUILD/trust.json" <<TRUST
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"bedrock-agentcore.amazonaws.com"},
 "Action":"sts:AssumeRole","Condition":{"StringEquals":{"aws:SourceAccount":"${ACCOUNT_ID}"},
 "ArnLike":{"aws:SourceArn":"arn:aws:bedrock-agentcore:${REGION}:${ACCOUNT_ID}:*"}}}]}
TRUST
if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
    run aws iam update-assume-role-policy --role-name "$ROLE_NAME" --policy-document "file://$BUILD/trust.json"
else
    run aws iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document "file://$BUILD/trust.json" >/dev/null
    $DRY_RUN || sleep 12
fi
cat > "$BUILD/policy.json" <<POLICY
{"Version":"2012-10-17","Statement":[
 {"Sid":"PullImage","Effect":"Allow","Action":["ecr:BatchGetImage","ecr:GetDownloadUrlForLayer"],
  "Resource":"arn:aws:ecr:${REGION}:${ACCOUNT_ID}:repository/${REPO}"},
 {"Sid":"EcrToken","Effect":"Allow","Action":"ecr:GetAuthorizationToken","Resource":"*"},
 {"Sid":"Logs","Effect":"Allow","Action":["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents",
  "logs:DescribeLogStreams","logs:DescribeLogGroups"],
  "Resource":["arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:/aws/bedrock-agentcore/runtimes/*",
              "arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*",
              "arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:*"]},
 {"Sid":"Traces","Effect":"Allow","Action":["xray:PutTraceSegments","xray:PutTelemetryRecords",
  "xray:GetSamplingRules","xray:GetSamplingTargets"],"Resource":"*"},
 {"Sid":"Metrics","Effect":"Allow","Action":"cloudwatch:PutMetricData","Resource":"*",
  "Condition":{"StringEquals":{"cloudwatch:namespace":"bedrock-agentcore"}}},
 {"Sid":"Models","Effect":"Allow","Action":["bedrock:InvokeModel","bedrock:InvokeModelWithResponseStream"],
  "Resource":["arn:aws:bedrock:*::foundation-model/*","arn:aws:bedrock:*:${ACCOUNT_ID}:inference-profile/*"]},
 {"Sid":"WorkloadIdentity","Effect":"Allow","Action":["bedrock-agentcore:GetWorkloadAccessToken",
  "bedrock-agentcore:GetWorkloadAccessTokenForJWT","bedrock-agentcore:GetWorkloadAccessTokenForUserId"],
  "Resource":["arn:aws:bedrock-agentcore:${REGION}:${ACCOUNT_ID}:workload-identity-directory/default",
              "arn:aws:bedrock-agentcore:${REGION}:${ACCOUNT_ID}:workload-identity-directory/default/workload-identity/*"]},
 {"Sid":"MoneyHubTable","Effect":"Allow","Action":["dynamodb:GetItem","dynamodb:PutItem"],
  "Resource":"arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${TABLE_NAME}"}]}
POLICY
run aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name MoneyHubAgentRuntime --policy-document "file://$BUILD/policy.json"
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
ok "Role ready (only AgentCore in this account can use it)."

header "Step 3 - Build and push the ARM64 image (${TAG})"
mkdir -p "$BUILD/ctx"
cp "$ROOT"/agent/{main.py,money_tools.py,prompt.py,history.py,requirements.txt,Dockerfile} "$BUILD/ctx/"
cp -R "$ROOT/moneyhub" "$BUILD/ctx/"
find "$BUILD/ctx" -name '__pycache__' -prune -exec rm -rf {} +
if $DRY_RUN; then echo "  [dry-run] docker buildx build --platform linux/arm64 -t ${IMAGE}:${TAG} --push"; else
    aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY" >/dev/null
    docker buildx build --platform linux/arm64 -t "${IMAGE}:${TAG}" -t "${IMAGE}:latest" --push "$BUILD/ctx" \
        || die "The image did not build. Check Docker is running and can build linux/arm64."
fi
ok "Pushed ${IMAGE}:${TAG}"

header "Step 4 - AgentCore Runtime ${RUNTIME_NAME}"
python3 -c 'import json,sys; print(json.dumps({"MODEL_ID":sys.argv[1],"MONEY_HUB_TABLE":sys.argv[2],"PUBLIC_BASE_URL":sys.argv[3]}))' \
    "$MODEL_ID" "$TABLE_NAME" "$PAGE_URL" > "$BUILD/env.json"
ARTIFACT="{\"containerConfiguration\":{\"containerUri\":\"${IMAGE}:${TAG}\"}}"
RUNTIME_ID=$({ aws bedrock-agentcore-control list-agent-runtimes --region "$REGION" \
    --query "agentRuntimes[?agentRuntimeName=='${RUNTIME_NAME}'].agentRuntimeId" --output text || true; } | first_value)
if [[ -n "$RUNTIME_ID" ]]; then
    step "Updating ${RUNTIME_ID} to the new image..."
    run aws bedrock-agentcore-control update-agent-runtime --region "$REGION" --agent-runtime-id "$RUNTIME_ID" \
        --agent-runtime-artifact "$ARTIFACT" --role-arn "$ROLE_ARN" --network-configuration '{"networkMode":"PUBLIC"}' \
        --protocol-configuration '{"serverProtocol":"HTTP"}' --environment-variables "file://$BUILD/env.json" >/dev/null
elif $DRY_RUN; then
    echo "  [dry-run] create-agent-runtime ${RUNTIME_NAME}"; RUNTIME_ID="dryrun"
else
    RUNTIME_ID=$(aws bedrock-agentcore-control create-agent-runtime --region "$REGION" --agent-runtime-name "$RUNTIME_NAME" \
        --description "Money Hub: spending insights and savings goals for ARIA (Strands)" \
        --agent-runtime-artifact "$ARTIFACT" --role-arn "$ROLE_ARN" --network-configuration '{"networkMode":"PUBLIC"}' \
        --protocol-configuration '{"serverProtocol":"HTTP"}' --environment-variables "file://$BUILD/env.json" \
        --query agentRuntimeId --output text)
fi
if ! $DRY_RUN; then
    step "Waiting for READY..."
    status=""
    for _ in $(seq 1 60); do
        status=$(aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id "$RUNTIME_ID" --region "$REGION" \
            --query status --output text)
        [[ "$status" == "READY" ]] && break
        [[ "$status" == *FAILED* ]] && die "The runtime failed (${status}). See get-agent-runtime and its CloudWatch logs."
        sleep 5
    done
    [[ "$status" == "READY" ]] || die "Still ${status} after five minutes."
fi
RUNTIME_ARN=$({ aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id "$RUNTIME_ID" --region "$REGION" \
    --query agentRuntimeArn --output text 2>/dev/null || true; } | first_value)
ok "Runtime READY: ${RUNTIME_ARN:-$RUNTIME_ID}"

header "Step 5 - Test turn"
if $DRY_RUN; then warn "Skipped in dry-run."; else
    echo '{"customerId":"CUST-001","channel":"CHAT","firstName":"James","history":[],"input":"What are my regular payments?"}' > "$BUILD/payload.json"
    aws bedrock-agentcore invoke-agent-runtime --region "$REGION" --agent-runtime-arn "$RUNTIME_ARN" --qualifier DEFAULT \
        --runtime-session-id "deploytest-$(date +%s)-money-hub-agent-check" --cli-binary-format raw-in-base64-out \
        --payload "file://$BUILD/payload.json" "$BUILD/out.json" >/dev/null || die "The test turn failed. See the runtime's CloudWatch logs."
    python3 - "$BUILD/out.json" <<'PY' || die "The agent did not answer as expected."
import json, sys
out = json.load(open(sys.argv[1]))
assert out.get("reply"), out
print("  Agent:", out["reply"][:300].replace("\n", " "))
print("  Tools:", [t["name"] for t in out.get("tools", [])])
PY
    ok "The agent answers."
fi

header "Done"
cat <<SUMMARY

  Runtime ARN (the bridge needs it; deploy_bridge.sh finds it by name):
    ${RUNTIME_ARN:-dry-run}

  Next: ./connect-money-hub/scripts/deploy_bridge.sh   (README step 4)
SUMMARY
