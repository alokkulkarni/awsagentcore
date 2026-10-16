#!/usr/bin/env bash
# =============================================================================
# deploy_bridge.sh
# =============================================================================
# Deploys the Connect A2A bridge that lets ARIA hand a call or chat to the Money
# Hub agent (README step 4).
#
# YOU run this script. It makes changes in your AWS account:
#   1. A customer managed KMS key (alias/aria-money-hub-a2a). Connect can decrypt
#      with it only through Secrets Manager: Connect can't read a secret
#      encrypted with the default aws/secretsmanager key
#   2. Secret aria-money-hub/a2a-api-key: the API key Connect presents, made by
#      this script, encrypted with that key, readable by your Connect instance
#      only. The script never reads it back
#   3. IAM role for the bridge: read that secret, read contact attributes,
#      invoke the Money Hub agent runtime, use the Money Hub table
#   4. Lambda aria-money-hub-bridge with a public Function URL (HTTPS). The
#      Lambda checks the key on every request
#   5. Tests: the agent card, a refused request, and (on the first run, while
#      the new key is still on hand) a full session start
#
# Usage:
#   ./connect-money-hub/scripts/deploy_bridge.sh [--region R] [--account-id A] [--instance-id ID]
#                                                [--mode sync|poll] [--dry-run]
#
# Requirements: AWS CLI v2.27+, python3, zip, curl. Run deploy_agent.sh first.
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
INSTANCE_ID="${INSTANCE_ID:-f969d4b4-f716-4974-a325-bb7899f2f293}"
MODE="sync"
DRY_RUN=false
KEY_ALIAS="alias/aria-money-hub-a2a"
SECRET_NAME="aria-money-hub/a2a-api-key"
ROLE_NAME="aria-money-hub-bridge-role"
FUNCTION_NAME="aria-money-hub-bridge"
RUNTIME_NAME="aria_money_hub_agent"
TABLE_NAME="aria-money-hub"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="${SCRIPT_DIR}/.."

while [[ $# -gt 0 ]]; do
    case "$1" in
        --region)      REGION="$2"; shift 2 ;;
        --account-id)  ACCOUNT_ID="$2"; shift 2 ;;
        --instance-id) INSTANCE_ID="$2"; shift 2 ;;
        --mode)        MODE="$2"; shift 2 ;;
        --dry-run)     DRY_RUN=true; shift ;;
        --help|-h)     sed -n '/^# Usage:/,/^# Requirements:/p' "$0" | sed -E 's/^# ?//'; exit 0 ;;
        *) die "Unknown argument: $1" ;;
    esac
done
[[ "$MODE" == "sync" || "$MODE" == "poll" ]] || die "--mode must be sync or poll."
[[ "$INSTANCE_ID" =~ ^[0-9a-f-]{36}$ ]] || die "--instance-id is not a Connect instance ID."

for tool in aws zip python3 curl; do command -v "$tool" >/dev/null || die "${tool} not found on PATH."; done
CALLER=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) || die "Sign in with the AWS CLI first."
[[ "$CALLER" == "$ACCOUNT_ID" ]] || die "Signed in to ${CALLER}, but the target is ${ACCOUNT_ID}."
ok "Signed in to ${ACCOUNT_ID}"

if $DRY_RUN; then warn "DRY-RUN: no changes."; run() { echo "  [dry-run] $*" >&2; }; else run() { "$@"; }; fi
first_value() { tr -s '[:space:]' '\n' | grep -v -e '^None$' -e '^$' | head -n 1 || true; }
BUILD="$(mktemp -d)"; trap 'rm -rf "$BUILD"' EXIT
INSTANCE_ARN="arn:aws:connect:${REGION}:${ACCOUNT_ID}:instance/${INSTANCE_ID}"
FUNCTION_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNCTION_NAME}"
NEW_KEY_FILE=""

RUNTIME_ARN=$({ aws bedrock-agentcore-control list-agent-runtimes --region "$REGION" \
    --query "agentRuntimes[?agentRuntimeName=='${RUNTIME_NAME}'].agentRuntimeArn" --output text || true; } | first_value)
[[ -n "$RUNTIME_ARN" ]] || $DRY_RUN || die "Runtime ${RUNTIME_NAME} not found. Run deploy_agent.sh first."
ok "Agent runtime: ${RUNTIME_ARN:-dry-run}"

header "Step 1 - KMS key ${KEY_ALIAS}"
KEY_ARN=$({ aws kms describe-key --key-id "$KEY_ALIAS" --region "$REGION" --query KeyMetadata.Arn --output text 2>/dev/null || true; } | first_value)
if [[ -n "$KEY_ARN" ]]; then ok "Key exists."; else
    cat > "$BUILD/key-policy.json" <<KEYPOLICY
{"Version":"2012-10-17","Statement":[
 {"Sid":"AccountAdministers","Effect":"Allow","Principal":{"AWS":"arn:aws:iam::${ACCOUNT_ID}:root"},"Action":"kms:*","Resource":"*"},
 {"Sid":"AllowConnectToDecryptSecret","Effect":"Allow","Principal":{"Service":"connect.amazonaws.com"},"Action":"kms:Decrypt",
  "Resource":"*","Condition":{"StringEquals":{"kms:ViaService":"secretsmanager.${REGION}.amazonaws.com"}}}]}
KEYPOLICY
    if $DRY_RUN; then echo "  [dry-run] kms create-key + alias"; KEY_ARN="dryrun-key"; else
        KEY_ARN=$(aws kms create-key --region "$REGION" --description "ARIA Money Hub A2A API key (Connect may decrypt via Secrets Manager)" \
            --policy "file://$BUILD/key-policy.json" --query KeyMetadata.Arn --output text)
        aws kms create-alias --region "$REGION" --alias-name "$KEY_ALIAS" --target-key-id "$KEY_ARN"
    fi
    ok "Key created."
fi

header "Step 2 - Secret ${SECRET_NAME}"
SECRET_ARN=$({ aws secretsmanager describe-secret --secret-id "$SECRET_NAME" --region "$REGION" --query ARN --output text 2>/dev/null || true; } | first_value)
if [[ -n "$SECRET_ARN" ]]; then
    ok "Secret exists (kept as it is; this script never reads it)."
else
    NEW_KEY_FILE="$BUILD/a2a-key"
    (umask 077; python3 -c 'import secrets; print(secrets.token_urlsafe(48), end="")' > "$NEW_KEY_FILE")
    if $DRY_RUN; then echo "  [dry-run] create-secret ${SECRET_NAME}"; SECRET_ARN="dryrun-secret"; else
        SECRET_ARN=$(aws secretsmanager create-secret --region "$REGION" --name "$SECRET_NAME" --kms-key-id "$KEY_ARN" \
            --description "API key Connect presents to the Money Hub A2A bridge" \
            --secret-string "file://$NEW_KEY_FILE" --query ARN --output text)
    fi
    ok "Secret created, encrypted with ${KEY_ALIAS}."
fi
cat > "$BUILD/secret-policy.json" <<SECRETPOLICY
{"Version":"2012-10-17","Statement":[{"Sid":"AllowConnectToRetrieveSecret","Effect":"Allow",
 "Principal":{"Service":"connect.amazonaws.com"},"Action":"secretsmanager:GetSecretValue","Resource":"*",
 "Condition":{"StringEquals":{"aws:SourceAccount":"${ACCOUNT_ID}"},"ArnEquals":{"aws:SourceArn":"${INSTANCE_ARN}"}}}]}
SECRETPOLICY
run aws secretsmanager put-resource-policy --region "$REGION" --secret-id "$SECRET_NAME" \
    --resource-policy "file://$BUILD/secret-policy.json" --block-public-policy >/dev/null
ok "Only your Connect instance can read it."

header "Step 3 - Bridge role ${ROLE_NAME}"
if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
    run aws iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document \
        '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
    run aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
    $DRY_RUN || sleep 12
fi
cat > "$BUILD/policy.json" <<POLICY
{"Version":"2012-10-17","Statement":[
 {"Sid":"ReadTheApiKey","Effect":"Allow","Action":"secretsmanager:GetSecretValue","Resource":"${SECRET_ARN}"},
 {"Sid":"DecryptTheApiKey","Effect":"Allow","Action":"kms:Decrypt","Resource":"${KEY_ARN}",
  "Condition":{"StringEquals":{"kms:ViaService":"secretsmanager.${REGION}.amazonaws.com"}}},
 {"Sid":"WhoIsTheCustomer","Effect":"Allow","Action":"connect:GetContactAttributes",
  "Resource":"${INSTANCE_ARN}/contact/*"},
 {"Sid":"CallTheAgent","Effect":"Allow","Action":"bedrock-agentcore:InvokeAgentRuntime",
  "Resource":["${RUNTIME_ARN:-*}","${RUNTIME_ARN:-*}/*"]},
 {"Sid":"Sessions","Effect":"Allow","Action":["dynamodb:GetItem","dynamodb:PutItem"],
  "Resource":"arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${TABLE_NAME}"},
 {"Sid":"PollModeSelfInvoke","Effect":"Allow","Action":"lambda:InvokeFunction","Resource":"${FUNCTION_ARN}"}]}
POLICY
run aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name MoneyHubBridge --policy-document "file://$BUILD/policy.json"
ok "Role ready."

header "Step 4 - Lambda ${FUNCTION_NAME} and its Function URL"
mkdir -p "$BUILD/pkg"
cp "$ROOT"/bridge/*.py "$BUILD/pkg/"; cp -R "$ROOT/moneyhub" "$BUILD/pkg/"
find "$BUILD/pkg" -name '__pycache__' -prune -exec rm -rf {} +
(cd "$BUILD/pkg" && zip -qr "$BUILD/bridge.zip" .)
python3 -c 'import json,sys; print(json.dumps({"Variables":{"MONEY_HUB_TABLE":sys.argv[1],"AGENT_RUNTIME_ARN":sys.argv[2],"API_KEY_SECRET_ID":sys.argv[3],"CONNECT_INSTANCE_ID":sys.argv[4],"BRIDGE_MODE":sys.argv[5]}}))' \
    "$TABLE_NAME" "${RUNTIME_ARN:-}" "$SECRET_NAME" "$INSTANCE_ID" "$MODE" > "$BUILD/env.json"
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" >/dev/null 2>&1; then
    run aws lambda update-function-code --function-name "$FUNCTION_NAME" --region "$REGION" --zip-file "fileb://$BUILD/bridge.zip" >/dev/null
    $DRY_RUN || aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
    run aws lambda update-function-configuration --function-name "$FUNCTION_NAME" --region "$REGION" --timeout 60 \
        --memory-size 512 --environment "file://$BUILD/env.json" >/dev/null
else
    run aws lambda create-function --function-name "$FUNCTION_NAME" --region "$REGION" --runtime python3.12 \
        --role "arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}" --handler a2a_bridge.lambda_handler --timeout 60 \
        --memory-size 512 --zip-file "fileb://$BUILD/bridge.zip" --environment "file://$BUILD/env.json" >/dev/null
fi
$DRY_RUN || aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
URL=$({ aws lambda get-function-url-config --function-name "$FUNCTION_NAME" --region "$REGION" --query FunctionUrl --output text 2>/dev/null || true; } | first_value)
if [[ -z "$URL" ]]; then
    if $DRY_RUN; then URL="https://dryrun.lambda-url.${REGION}.on.aws/"; echo "  [dry-run] create-function-url-config"; else
        URL=$(aws lambda create-function-url-config --function-name "$FUNCTION_NAME" --region "$REGION" --auth-type NONE \
            --query FunctionUrl --output text); fi
fi
# The URL is public; the Lambda itself refuses any request without Connect's key.
run aws lambda add-permission --function-name "$FUNCTION_NAME" --region "$REGION" --statement-id FunctionUrlPublic \
    --action lambda:InvokeFunctionUrl --principal "*" --function-url-auth-type NONE >/dev/null 2>&1 || true
run aws lambda add-permission --function-name "$FUNCTION_NAME" --region "$REGION" --statement-id FunctionUrlInvoke \
    --action lambda:InvokeFunction --principal "*" --invoked-via-function-url >/dev/null 2>&1 || true
ok "Bridge address: ${URL}"

header "Step 5 - Tests"
if $DRY_RUN; then warn "Skipped in dry-run."; else
    code=""
    for _ in 1 2 3 4 5; do code=$(curl -s -o /dev/null -w '%{http_code}' "${URL}.well-known/agent-card.json" || true)
        [[ "$code" == "200" ]] && break; sleep 3; done
    [[ "$code" == "200" ]] || die "The agent card did not load (HTTP ${code}). If 403, check the Function URL permissions."
    ok "The agent card loads."
    # 401 means the bridge read its key and refused ours. 503 means it couldn't read the key yet: a new role's
    # permissions can take a minute or two to reach every AWS endpoint, so keep trying for up to two minutes.
    code=""
    for attempt in $(seq 1 12); do
        code=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'content-type: application/json' -d '{}' "$URL" || true)
        [[ "$code" == "503" ]] || break
        [[ "$attempt" == "1" ]] && step "The bridge can't read its key yet (new permissions take a minute or two). Waiting..."
        sleep 10
    done
    [[ "$code" == "401" ]] || die "A request without the key got HTTP ${code}; expected 401. If 503: in CloudWatch, /aws/lambda/${FUNCTION_NAME} names the error (secretsmanager:GetSecretValue or kms:Decrypt)."
    ok "A request without the key is refused (so the bridge can read its key)."
    if [[ -n "$NEW_KEY_FILE" ]]; then
        python3 - "$URL" "$NEW_KEY_FILE" <<'PY' || die "A session start with the right key failed."
import json, sys, urllib.request
url, key = sys.argv[1], open(sys.argv[2]).read()
body = {"jsonrpc": "2.0", "method": "SendMessage", "id": "deploy-1", "params": {"message": {
    "messageId": "m-1", "contextId": "deploy-test", "role": "ROLE_USER", "metadata": {
        "https://docs.aws.amazon.com/connect/a2a/ext/v1/eventType": "INIT_SESSION"},
    "parts": [{"data": {"initSession": {"contactArn": "", "supportedFinishTypes": ["COMPLETE", "ESCALATE"]}},
               "mediaType": "application/json"}]}}}
req = urllib.request.Request(url, json.dumps(body).encode(), {"content-type": "application/json",
                             "authorization": f"Bearer {key}"})
reply = json.load(urllib.request.urlopen(req, timeout=30))
assert reply["result"]["message"]["parts"][0]["data"]["initSessionResponse"]["statusCode"] == "200", reply
PY
        ok "A session start with the right key is accepted."
    else
        warn "The key was made on an earlier run and is never read back, so the keyed test is skipped."
    fi
fi
[[ -n "$NEW_KEY_FILE" ]] && rm -f "$NEW_KEY_FILE"

header "Done"
cat <<SUMMARY

  Bridge address (the A2A AccessUrl) : ${URL}
  API key secret                     : ${SECRET_ARN}
  Mode                               : ${MODE}

  Next: ./connect-money-hub/scripts/connect_collaborator.sh   (README step 5; dry run first)
SUMMARY
