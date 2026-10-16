#!/usr/bin/env bash
# =============================================================================
# deploy_money_hub.sh
# =============================================================================
# Deploys the Money Hub data service and page (README step 2).
#
# YOU run this script. It makes changes in your AWS account:
#   1. DynamoDB table aria-money-hub (categories, goals, links, bridge sessions)
#   2. IAM role for the page Lambda: read and write that one table
#   3. Lambda aria-money-hub-api (the page, its data, two read-only tools)
#   4. HTTP API in front of it, for the page
#   5. Gateway target aria-money-hub on the ARIA MCP gateway (read-only tools
#      for agent assist), unless --skip-gateway
#   6. Tests, and a demo link to James's Money Hub
#
# It changes no AI agent, prompt or contact flow. Safe to run again.
#
# Usage:
#   ./connect-money-hub/scripts/deploy_money_hub.sh [--region R] [--account-id A] [--env prod]
#                                                   [--skip-gateway] [--dry-run]
#
# Requirements: AWS CLI v2.27+, python3, zip, curl.
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
ENV_NAME="${ARIA_ENV:-prod}"
DO_GATEWAY=true
DRY_RUN=false

TABLE_NAME="aria-money-hub"
FUNCTION_NAME="aria-money-hub-api"
ROLE_NAME="aria-money-hub-api-role"
API_NAME="aria-money-hub-pages"
TARGET_NAME="aria-money-hub"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="${SCRIPT_DIR}/.."

while [[ $# -gt 0 ]]; do
    case "$1" in
        --region)       REGION="$2"; shift 2 ;;
        --account-id)   ACCOUNT_ID="$2"; shift 2 ;;
        --env)          ENV_NAME="$2"; shift 2 ;;
        --skip-gateway) DO_GATEWAY=false; shift ;;
        --dry-run)      DRY_RUN=true; shift ;;
        --help|-h)      sed -n '/^# Usage:/,/^# Requirements:/p' "$0" | sed -E 's/^# ?//'; exit 0 ;;
        *) die "Unknown argument: $1" ;;
    esac
done
GATEWAY_NAME="aria-banking-mcp-gateway-${ENV_NAME}"
GATEWAY_ROLE_NAME="aria-banking-mcp-gateway-role-${ENV_NAME}"

for tool in aws zip python3 curl; do command -v "$tool" >/dev/null || die "${tool} not found on PATH."; done
step "Checking AWS credentials..."
CALLER=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) || die "Sign in with the AWS CLI first."
[[ "$CALLER" == "$ACCOUNT_ID" ]] || die "Signed in to ${CALLER}, but the target is ${ACCOUNT_ID}. Use --account-id."
ok "Signed in to ${ACCOUNT_ID}"

if $DRY_RUN; then warn "DRY-RUN: no changes."; run() { echo "  [dry-run] $*"; }; else run() { "$@"; }; fi
first_value() { tr -s '[:space:]' '\n' | grep -v -e '^None$' -e '^$' | head -n 1 || true; }
BUILD="$(mktemp -d)"; trap 'rm -rf "$BUILD"' EXIT
LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNCTION_NAME}"
TABLE_ARN="arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${TABLE_NAME}"

header "Step 1 - DynamoDB table ${TABLE_NAME}"
if aws dynamodb describe-table --table-name "$TABLE_NAME" --region "$REGION" >/dev/null 2>&1; then
    ok "Table exists."
else
    run aws dynamodb create-table --table-name "$TABLE_NAME" --region "$REGION" \
        --attribute-definitions AttributeName=pk,AttributeType=S --key-schema AttributeName=pk,KeyType=HASH \
        --billing-mode PAY_PER_REQUEST --query TableDescription.TableName --output text >/dev/null
    $DRY_RUN || aws dynamodb wait table-exists --table-name "$TABLE_NAME" --region "$REGION"
    ok "Table created."
fi
ttl=$({ aws dynamodb describe-time-to-live --table-name "$TABLE_NAME" --region "$REGION" \
    --query TimeToLiveDescription.TimeToLiveStatus --output text 2>/dev/null || true; } | first_value)
[[ "$ttl" == "ENABLED" || "$ttl" == "ENABLING" ]] || run aws dynamodb update-time-to-live --table-name "$TABLE_NAME" \
    --region "$REGION" --time-to-live-specification "Enabled=true,AttributeName=ttl" >/dev/null
ok "Time-to-live on (links and sessions clear themselves)."

header "Step 2 - IAM role ${ROLE_NAME}"
if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
    run aws iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document \
        '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
    run aws iam attach-role-policy --role-name "$ROLE_NAME" \
        --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
    $DRY_RUN || sleep 12
fi
cat > "$BUILD/policy.json" <<POLICY
{"Version":"2012-10-17","Statement":[{"Sid":"MoneyHubTable","Effect":"Allow","Action":["dynamodb:GetItem","dynamodb:PutItem"],"Resource":"${TABLE_ARN}"}]}
POLICY
run aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name MoneyHubApi --policy-document "file://$BUILD/policy.json"
ok "Role ready: read and write single items in one table."

header "Step 3 - Lambda ${FUNCTION_NAME}"
mkdir -p "$BUILD/pkg/web"
cp -R "$ROOT/moneyhub" "$BUILD/pkg/"; cp "$ROOT/api/money_api.py" "$BUILD/pkg/"; cp "$ROOT"/web/* "$BUILD/pkg/web/"
find "$BUILD/pkg" -name '__pycache__' -prune -exec rm -rf {} +
(cd "$BUILD/pkg" && zip -qr "$BUILD/api.zip" .)
write_env() { python3 -c 'import json,sys; v={"MONEY_HUB_TABLE":sys.argv[1]}; sys.argv[2] and v.update(PUBLIC_BASE_URL=sys.argv[2]); print(json.dumps({"Variables":v}))' \
    "$TABLE_NAME" "$1" > "$BUILD/env.json"; }
write_env ""
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" >/dev/null 2>&1; then
    run aws lambda update-function-code --function-name "$FUNCTION_NAME" --region "$REGION" \
        --zip-file "fileb://$BUILD/api.zip" --query FunctionName --output text >/dev/null
else
    run aws lambda create-function --function-name "$FUNCTION_NAME" --region "$REGION" --runtime python3.12 \
        --role "arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}" --handler money_api.lambda_handler --timeout 10 \
        --memory-size 512 --zip-file "fileb://$BUILD/api.zip" --environment "file://$BUILD/env.json" \
        --query FunctionName --output text >/dev/null
fi
$DRY_RUN || aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
ok "Code deployed."

header "Step 4 - HTTP API ${API_NAME}"
API_ID=$({ aws apigatewayv2 get-apis --region "$REGION" --query "Items[?Name=='${API_NAME}'].ApiId" --output text || true; } | first_value)
if [[ -z "$API_ID" ]]; then
    if $DRY_RUN; then API_ID="dryrunapi"; echo "  [dry-run] create-api ${API_NAME}"; else
        API_ID=$(aws apigatewayv2 create-api --name "$API_NAME" --protocol-type HTTP --target "$LAMBDA_ARN" \
            --region "$REGION" --query ApiId --output text); fi
fi
PAGE_URL="https://${API_ID}.execute-api.${REGION}.amazonaws.com"
run aws lambda add-permission --function-name "$FUNCTION_NAME" --region "$REGION" --statement-id PagesApiInvoke \
    --action lambda:InvokeFunction --principal apigateway.amazonaws.com \
    --source-arn "arn:aws:execute-api:${REGION}:${ACCOUNT_ID}:${API_ID}/*" >/dev/null 2>&1 || true
run aws apigatewayv2 update-stage --api-id "$API_ID" --stage-name '$default' --region "$REGION" \
    --default-route-settings "ThrottlingBurstLimit=40,ThrottlingRateLimit=20" >/dev/null
write_env "$PAGE_URL"
run aws lambda update-function-configuration --function-name "$FUNCTION_NAME" --region "$REGION" \
    --environment "file://$BUILD/env.json" --query FunctionName --output text >/dev/null
$DRY_RUN || aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
ok "Page address: ${PAGE_URL}/"

header "Step 5 - Gateway target ${TARGET_NAME} (read-only tools for agent assist)"
if ! $DO_GATEWAY; then warn "Skipped (--skip-gateway)."; else
    GATEWAY_ID=$({ aws bedrock-agentcore-control list-gateways --region "$REGION" \
        --query "items[?name=='${GATEWAY_NAME}'].gatewayId" --output text || true; } | first_value)
    [[ -n "$GATEWAY_ID" ]] || die "Gateway ${GATEWAY_NAME} not found. Run with --skip-gateway to leave it out."
    echo "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"lambda:InvokeFunction\",\"Resource\":[\"${LAMBDA_ARN}\",\"${LAMBDA_ARN}:*\"]}]}" > "$BUILD/gw.json"
    run aws iam put-role-policy --role-name "$GATEWAY_ROLE_NAME" --policy-name invoke-money-hub-tools \
        --policy-document "file://$BUILD/gw.json"
    LAMBDA_ARN="$LAMBDA_ARN" python3 -c 'import json,os,sys; print(json.dumps({"mcp":{"lambda":{"lambdaArn":os.environ["LAMBDA_ARN"],"toolSchema":{"inlinePayload":json.load(open(sys.argv[1]))}}}}))' \
        "$SCRIPT_DIR/tool_schemas.json" > "$BUILD/target.json"
    echo '[{"credentialProviderType":"GATEWAY_IAM_ROLE"}]' > "$BUILD/creds.json"
    TARGET_ID=$({ aws bedrock-agentcore-control list-gateway-targets --gateway-identifier "$GATEWAY_ID" --region "$REGION" \
        --query "items[?name=='${TARGET_NAME}'].targetId" --output text || true; } | first_value)
    if [[ -n "$TARGET_ID" ]]; then
        run aws bedrock-agentcore-control update-gateway-target --region "$REGION" --gateway-identifier "$GATEWAY_ID" \
            --target-id "$TARGET_ID" --name "$TARGET_NAME" --target-configuration "file://$BUILD/target.json" \
            --credential-provider-configurations "file://$BUILD/creds.json" >/dev/null
    else
        $DRY_RUN || sleep 10
        run aws bedrock-agentcore-control create-gateway-target --region "$REGION" --gateway-identifier "$GATEWAY_ID" \
            --name "$TARGET_NAME" --description "Money Hub read-only facts" --target-configuration "file://$BUILD/target.json" \
            --credential-provider-configurations "file://$BUILD/creds.json" >/dev/null
    fi
    ok "Gateway target ${TARGET_NAME} set (tools: get_money_hub_summary, get_money_hub_forecast)."
fi

header "Step 6 - Tests"
if $DRY_RUN; then warn "Skipped in dry-run."; else
    code=""
    for _ in 1 2 3 4 5 6; do code=$(curl -s -o "$BUILD/page.html" -w '%{http_code}' "${PAGE_URL}/" || true)
        [[ "$code" == "200" ]] && break; sleep 3; done
    [[ "$code" == "200" ]] && grep -q "Money Hub" "$BUILD/page.html" || die "The page did not load (HTTP ${code})."
    ok "The page loads."
    echo '{"operation":"mint_link","customerId":"CUST-001"}' > "$BUILD/mint.json"
    aws lambda invoke --function-name "$FUNCTION_NAME" --region "$REGION" --cli-binary-format raw-in-base64-out \
        --payload "file://$BUILD/mint.json" "$BUILD/link.json" >/dev/null
    DEMO_LINK=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("link",""))' "$BUILD/link.json")
    [[ "$DEMO_LINK" == https://* ]] || die "Could not make a demo link: $(cat "$BUILD/link.json")"
    ok "A link works for 24 hours."
fi

header "Done"
cat <<SUMMARY

  Money Hub page : ${PAGE_URL}/
  Demo link (James, CUST-001, works 24 hours; run again for a new one):
    ${DEMO_LINK:-run without --dry-run}

  Next: ./connect-money-hub/scripts/deploy_agent.sh   (README step 3)
SUMMARY
