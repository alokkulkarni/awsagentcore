#!/usr/bin/env bash
set -euo pipefail

# This script uses associative arrays (declare -A), which require bash 4+.
# macOS ships bash 3.2 as /bin/bash (Apple has frozen it there since 2007 for
# GPLv3 licensing reasons), so `env bash` resolves to the wrong interpreter on
# most Macs unless a newer bash is first on PATH. Under bash 3.2 this script
# fails with a cryptic "unbound variable" error instead of a useful message.
if [[ -z "${BASH_VERSINFO:-}" || "${BASH_VERSINFO[0]}" -lt 4 ]]; then
  echo "ERROR: this script requires bash 4 or newer (found: ${BASH_VERSION:-unknown})." >&2
  echo "On macOS, install a modern bash via Homebrew and re-run with it explicitly:" >&2
  echo "    brew install bash" >&2
  echo "    /opt/homebrew/bin/bash $0 $*" >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$ROOT_DIR/.build"
STATE_FILE="$ROOT_DIR/.deploy-state.json"

# ==========================================
# CONFIGURATION - Edit these values
# ==========================================
PROJECT_NAME="connect-analytics"
AWS_REGION="${AWS_REGION:-$(aws configure get region 2>/dev/null || true)}"
AWS_REGION="${AWS_REGION:-us-east-1}"
CONNECT_INSTANCE_ID="${CONNECT_INSTANCE_ID:-}"
BEDROCK_MODEL_ID="${BEDROCK_MODEL_ID:-us.anthropic.claude-sonnet-4-5}"
STACK_SUFFIX="${STACK_SUFFIX:-$(date +%Y%m%d)}"

# Derived names
LAMBDA_ROLE_NAME="${PROJECT_NAME}-lambda-tools-role"
AGENT_ROLE_NAME="${PROJECT_NAME}-agent-role"
GATEWAY_ROLE_NAME="${PROJECT_NAME}-gateway-role"
LAMBDA_POLICY_NAME="${PROJECT_NAME}-lambda-tools-policy"
AGENT_POLICY_NAME="${PROJECT_NAME}-agent-policy"
GATEWAY_POLICY_NAME="${PROJECT_NAME}-gateway-policy"
FRONTEND_BUCKET="${PROJECT_NAME}-frontend-${STACK_SUFFIX}"
DISTRIBUTION_COMMENT="${PROJECT_NAME}-distribution"

# Tool Lambda names
TOOL_NAMES=("realtime-metrics" "historical-metrics" "agent-states" "search-contacts" "contact-detail" "transcript" "keyword-search" "recording-url" "contact-flow-events")

declare -A TOOL_DIRS=(
  ["realtime-metrics"]="realtime_metrics"
  ["historical-metrics"]="historical_metrics"
  ["agent-states"]="agent_states"
  ["search-contacts"]="search_contacts"
  ["contact-detail"]="contact_detail"
  ["transcript"]="transcript"
  ["keyword-search"]="keyword_search"
  ["recording-url"]="recording_url"
  ["contact-flow-events"]="contact_flow_events"
)

declare -A TOOL_FUNCTIONS=(
  ["realtime-metrics"]="get_realtime_metrics"
  ["historical-metrics"]="get_historical_metrics"
  ["agent-states"]="get_agent_states"
  ["search-contacts"]="search_contacts"
  ["contact-detail"]="get_contact_detail"
  ["transcript"]="get_transcript"
  ["keyword-search"]="keyword_search"
  ["recording-url"]="get_recording_url"
  ["contact-flow-events"]="contact_flow_events"
)

declare -A TOOL_SCHEMA_TO_KEY=(
  ["get_realtime_metrics"]="realtime-metrics"
  ["get_historical_metrics"]="historical-metrics"
  ["get_agent_states"]="agent-states"
  ["search_contacts"]="search-contacts"
  ["get_contact_detail"]="contact-detail"
  ["get_transcript"]="transcript"
  ["keyword_search"]="keyword-search"
  ["get_recording_url"]="recording-url"
  ["contact_flow_events"]="contact-flow-events"
)

ACCOUNT_ID=""

log() { printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$1"; }
warn() { printf '\n[WARN] %s\n' "$1" >&2; }
die() { printf '\n[ERROR] %s\n' "$1" >&2; exit 1; }

ensure_build_dir() {
  mkdir -p "$BUILD_DIR"
}

cleanup_build_dir() {
  rm -rf "$BUILD_DIR"
}

state_init() {
  cat > "$STATE_FILE" <<EOF
{
  "project_name": "$PROJECT_NAME",
  "region": "$AWS_REGION",
  "lambda_role_arn": "",
  "agent_role_arn": "",
  "gateway_role_arn": "",
  "lambda_policy_arn": "",
  "agent_policy_arn": "",
  "gateway_policy_arn": "",
  "tool_lambdas": {},
  "tool_lambda_names": {},
  "agentcore_mode": "gateway",
  "agentcore_gateway_id": "",
  "agentcore_gateway_endpoint": "",
  "agent_lambda_arn": "",
  "agent_lambda_name": "",
  "api_gateway_id": "",
  "api_gateway_url": "",
  "api_gateway_invoke_url_root": "",
  "cognito_user_pool_id": "",
  "cognito_client_id": "",
  "frontend_bucket": "$FRONTEND_BUCKET",
  "cloudfront_distribution_id": "",
  "cloudfront_url": ""
}
EOF
}

ensure_state_file() {
  [[ -f "$STATE_FILE" ]] || state_init
}

state_set_string() {
  local key="$1"
  local value="$2"
  ensure_state_file
  jq --arg value "$value" ".$key = \$value" "$STATE_FILE" > "$STATE_FILE.next"
  mv "$STATE_FILE.next" "$STATE_FILE"
}

state_set_json() {
  local key="$1"
  local value_json="$2"
  ensure_state_file
  jq --argjson value "$value_json" ".$key = \$value" "$STATE_FILE" > "$STATE_FILE.next"
  mv "$STATE_FILE.next" "$STATE_FILE"
}

state_map_set() {
  local key="$1"
  local subkey="$2"
  local value="$3"
  ensure_state_file
  jq --arg subkey "$subkey" --arg value "$value" ".$key[\$subkey] = \$value" "$STATE_FILE" > "$STATE_FILE.next"
  mv "$STATE_FILE.next" "$STATE_FILE"
}

state_get() {
  if [[ ! -f "$STATE_FILE" ]]; then
    return 0
  fi
  if [[ "$#" -eq 1 ]]; then
    jq -r "$1 // empty" "$STATE_FILE"
    return 0
  fi
  jq -r "$@" "$STATE_FILE"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

validate_prerequisites() {
  log "Validating prerequisites"
  require_command aws
  require_command jq
  require_command zip
  require_command python3
  require_command pip3
  require_command npm

  aws sts get-caller-identity >/dev/null 2>&1 || die "AWS CLI is not configured with valid credentials."
  ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"

  if [[ -z "$CONNECT_INSTANCE_ID" ]]; then
    die "CONNECT_INSTANCE_ID must be exported before running cloud deployment."
  fi
}

validate_local_prerequisites() {
  log "Validating local prerequisites"
  require_command docker
}

sleep_for_iam() {
  sleep 10
}

role_arn_for() {
  aws iam get-role --role-name "$1" --query 'Role.Arn' --output text 2>/dev/null || true
}

managed_policy_arn_for() {
  aws iam list-policies --scope Local --query "Policies[?PolicyName=='$1'].Arn | [0]" --output text 2>/dev/null || true
}

create_or_update_role() {
  local role_name="$1"
  local trust_policy_file="$2"
  local existing_arn
  existing_arn="$(role_arn_for "$role_name")"

  if [[ -z "$existing_arn" || "$existing_arn" == "None" ]]; then
    aws iam create-role --role-name "$role_name" --assume-role-policy-document "file://$trust_policy_file" >/dev/null
  else
    aws iam update-assume-role-policy --role-name "$role_name" --policy-document "file://$trust_policy_file" >/dev/null
  fi

  sleep_for_iam
  role_arn_for "$role_name"
}

create_or_update_managed_policy() {
  local policy_name="$1"
  local policy_file="$2"
  local policy_arn
  policy_arn="$(managed_policy_arn_for "$policy_name")"

  if [[ -z "$policy_arn" || "$policy_arn" == "None" ]]; then
    policy_arn="$(aws iam create-policy --policy-name "$policy_name" --policy-document "file://$policy_file" --query 'Policy.Arn' --output text)"
  else
    local versions
    versions="$(aws iam list-policy-versions --policy-arn "$policy_arn" --query 'Versions[?IsDefaultVersion==`false`].VersionId' --output text || true)"
    local count
    count="$(aws iam list-policy-versions --policy-arn "$policy_arn" --query 'length(Versions)' --output text)"
    if [[ "$count" -ge 5 && -n "$versions" ]]; then
      local oldest
      oldest="$(aws iam list-policy-versions --policy-arn "$policy_arn" --query 'Versions[?IsDefaultVersion==`false`]|sort_by(@,&CreateDate)[0].VersionId' --output text)"
      [[ -n "$oldest" && "$oldest" != "None" ]] && aws iam delete-policy-version --policy-arn "$policy_arn" --version-id "$oldest" >/dev/null || true
    fi
    aws iam create-policy-version --policy-arn "$policy_arn" --policy-document "file://$policy_file" --set-as-default >/dev/null
  fi

  echo "$policy_arn"
}

attach_policy_to_role() {
  local role_name="$1"
  local policy_arn="$2"
  aws iam attach-role-policy --role-name "$role_name" --policy-arn "$policy_arn" >/dev/null || true
}

detach_policy_from_role() {
  local role_name="$1"
  local policy_arn="$2"
  [[ -n "$policy_arn" ]] || return 0
  aws iam detach-role-policy --role-name "$role_name" --policy-arn "$policy_arn" >/dev/null 2>&1 || true
}

build_gateway_invoke_policy() {
  ensure_build_dir
  local tool_arns_json
  tool_arns_json="$(jq -c '[.tool_lambdas[] | select(length > 0)]' "$STATE_FILE")"
  jq -n --argjson arns "$tool_arns_json" '{
    Version: "2012-10-17",
    Statement: [
      {
        Sid: "InvokeToolFunctions",
        Effect: "Allow",
        Action: ["lambda:InvokeFunction"],
        Resource: $arns
      }
    ]
  }' > "$BUILD_DIR/gateway-invoke-policy.json"
}

deploy_iam_roles() {
  log "Creating IAM roles"
  ensure_state_file
  local lambda_role_arn agent_role_arn gateway_role_arn
  lambda_role_arn="$(create_or_update_role "$LAMBDA_ROLE_NAME" "$ROOT_DIR/infrastructure/iam/lambda-tools-trust.json")"
  agent_role_arn="$(create_or_update_role "$AGENT_ROLE_NAME" "$ROOT_DIR/infrastructure/iam/agent-lambda-trust.json")"
  gateway_role_arn="$(create_or_update_role "$GATEWAY_ROLE_NAME" "$ROOT_DIR/infrastructure/iam/agentcore-gateway-policy.json")"

  state_set_string "lambda_role_arn" "$lambda_role_arn"
  state_set_string "agent_role_arn" "$agent_role_arn"
  state_set_string "gateway_role_arn" "$gateway_role_arn"
}

deploy_iam_policies() {
  log "Creating IAM policies"
  ensure_state_file
  local lambda_policy_arn agent_policy_arn
  lambda_policy_arn="$(create_or_update_managed_policy "$LAMBDA_POLICY_NAME" "$ROOT_DIR/infrastructure/iam/lambda-tools-policy.json")"
  agent_policy_arn="$(create_or_update_managed_policy "$AGENT_POLICY_NAME" "$ROOT_DIR/infrastructure/iam/agent-lambda-policy.json")"

  attach_policy_to_role "$LAMBDA_ROLE_NAME" "$lambda_policy_arn"
  attach_policy_to_role "$AGENT_ROLE_NAME" "$agent_policy_arn"

  state_set_string "lambda_policy_arn" "$lambda_policy_arn"
  state_set_string "agent_policy_arn" "$agent_policy_arn"
}

tool_lambda_name() {
  local tool_key="$1"
  echo "${PROJECT_NAME}-${tool_key}-${STACK_SUFFIX}"
}

package_tool_lambda() {
  local tool_key="$1"
  local tool_dir="$ROOT_DIR/tools/${TOOL_DIRS[$tool_key]}"
  local package_dir="$BUILD_DIR/$tool_key/package"
  local zip_path="$BUILD_DIR/$tool_key/${tool_key}.zip"

  rm -rf "$BUILD_DIR/$tool_key"
  mkdir -p "$package_dir/shared"
  python3 -m pip install --quiet -r "$tool_dir/requirements.txt" -t "$package_dir"
  cp "$tool_dir/handler.py" "$package_dir/handler.py"
  cp "$ROOT_DIR/tools/shared/connect_utils.py" "$package_dir/shared/connect_utils.py"
  (cd "$package_dir" && zip -qr "$zip_path" .)
  echo "$zip_path"
}

create_or_update_lambda() {
  local function_name="$1"
  local role_arn="$2"
  local zip_path="$3"
  local handler_name="$4"
  local env_json="$5"

  if aws lambda get-function --function-name "$function_name" >/dev/null 2>&1; then
    aws lambda update-function-code --function-name "$function_name" --zip-file "fileb://$zip_path" >/dev/null
    aws lambda update-function-configuration --function-name "$function_name" --role "$role_arn" --runtime python3.12 --handler "$handler_name" --timeout 180 --memory-size 1024 --environment "$env_json" >/dev/null
  else
    aws lambda create-function --function-name "$function_name" --runtime python3.12 --handler "$handler_name" --role "$role_arn" --timeout 180 --memory-size 1024 --zip-file "fileb://$zip_path" --environment "$env_json" >/dev/null
  fi

  aws lambda wait function-active-v2 --function-name "$function_name"
  aws lambda get-function --function-name "$function_name" --query 'Configuration.FunctionArn' --output text
}

deploy_lambda_tools() {
  log "Packaging and deploying tool Lambdas"
  ensure_state_file
  local lambda_role_arn
  lambda_role_arn="$(state_get '.lambda_role_arn')"
  [[ -n "$lambda_role_arn" ]] || die "Lambda tools role ARN missing from state."

  for tool_key in "${TOOL_NAMES[@]}"; do
    log "Deploying tool Lambda: $tool_key"
    local function_name zip_path env_json function_arn
    function_name="$(tool_lambda_name "$tool_key")"
    zip_path="$(package_tool_lambda "$tool_key")"
    env_json="Variables={CONNECT_INSTANCE_ID=$CONNECT_INSTANCE_ID,AWS_REGION=$AWS_REGION}"
    function_arn="$(create_or_update_lambda "$function_name" "$lambda_role_arn" "$zip_path" "handler.lambda_handler" "$env_json")"
    state_map_set "tool_lambdas" "$tool_key" "$function_arn"
    state_map_set "tool_lambda_names" "$tool_key" "$function_name"
  done
}

detect_agentcore_cli() {
  aws bedrock-agentcore-control help >/dev/null 2>&1
}

detect_gateway_target_command() {
  local help_text
  help_text="$(aws bedrock-agentcore-control help 2>&1 || true)"
  if grep -q "create-gateway-target" <<< "$help_text"; then
    echo "create-gateway-target"
    return 0
  fi
  if grep -q "create-target" <<< "$help_text"; then
    echo "create-target"
    return 0
  fi
  echo ""
}

wait_for_gateway_active() {
  local gateway_id="$1"
  if ! aws bedrock-agentcore-control get-gateway --gateway-id "$gateway_id" >/dev/null 2>&1; then
    return 0
  fi
  local attempts=0
  while (( attempts < 40 )); do
    local status
    status="$(aws bedrock-agentcore-control get-gateway --gateway-id "$gateway_id" --query 'gateway.status // status' --output text 2>/dev/null || echo 'UNKNOWN')"
    [[ "$status" == "ACTIVE" ]] && return 0
    sleep 15
    attempts=$((attempts + 1))
  done
  warn "Gateway did not report ACTIVE within the expected window."
}

register_gateway_tool() {
  local target_command="$1"
  local gateway_id="$2"
  local tool_name="$3"
  local lambda_arn="$4"
  local schema_json="$5"

  if [[ "$target_command" == "create-gateway-target" ]]; then
    aws bedrock-agentcore-control create-gateway-target \
      --gateway-id "$gateway_id" \
      --name "$tool_name" \
      --target-configuration "lambdaArn=$lambda_arn" \
      --tool-schema "$schema_json" >/dev/null
    return 0
  fi

  if [[ "$target_command" == "create-target" ]]; then
    aws bedrock-agentcore-control create-target \
      --gateway-id "$gateway_id" \
      --name "$tool_name" \
      --target-configuration "lambdaArn=$lambda_arn" \
      --tool-schema "$schema_json" >/dev/null
    return 0
  fi

  return 1
}

deploy_gateway_policy() {
  log "Creating AgentCore Gateway invoke policy"
  build_gateway_invoke_policy
  local gateway_policy_arn
  gateway_policy_arn="$(create_or_update_managed_policy "$GATEWAY_POLICY_NAME" "$BUILD_DIR/gateway-invoke-policy.json")"
  attach_policy_to_role "$GATEWAY_ROLE_NAME" "$gateway_policy_arn"
  state_set_string "gateway_policy_arn" "$gateway_policy_arn"
}

deploy_agentcore_gateway() {
  log "Deploying AgentCore gateway"
  ensure_state_file
  deploy_gateway_policy

  if ! detect_agentcore_cli; then
    warn "AWS CLI does not expose bedrock-agentcore-control. Falling back to direct Lambda invocation mode."
    state_set_string "agentcore_mode" "direct"
    state_set_string "agentcore_gateway_id" ""
    state_set_string "agentcore_gateway_endpoint" ""
    return 0
  fi

  local target_command gateway_role_arn gateway_name create_response gateway_id endpoint
  target_command="$(detect_gateway_target_command)"
  if [[ -z "$target_command" ]]; then
    warn "AgentCore gateway target registration command is unavailable in this AWS CLI build. Falling back to direct Lambda invocation mode."
    state_set_string "agentcore_mode" "direct"
    state_set_string "agentcore_gateway_id" ""
    state_set_string "agentcore_gateway_endpoint" ""
    return 0
  fi

  gateway_role_arn="$(state_get '.gateway_role_arn')"
  gateway_name="${PROJECT_NAME}-gateway-${STACK_SUFFIX}"
  create_response="$(aws bedrock-agentcore-control create-gateway --name "$gateway_name" --role-arn "$gateway_role_arn" --output json)"
  gateway_id="$(jq -r '.gateway.gatewayId // .gatewayId // empty' <<< "$create_response")"
  endpoint="$(jq -r '.gateway.endpoint // .endpoint // empty' <<< "$create_response")"

  if [[ -z "$gateway_id" ]]; then
    warn "Gateway creation response could not be parsed. Falling back to direct Lambda invocation mode."
    state_set_string "agentcore_mode" "direct"
    return 0
  fi

  wait_for_gateway_active "$gateway_id"

  while IFS= read -r tool_name; do
    local tool_key lambda_arn schema_json
    tool_key="${TOOL_SCHEMA_TO_KEY[$tool_name]}"
    lambda_arn="$(state_get --arg key "$tool_key" '.tool_lambdas[$key]')"
    schema_json="$(jq -c --arg name "$tool_name" '.tools[] | select(.name == $name)' "$ROOT_DIR/infrastructure/gateway/tool-schemas.json")"
    register_gateway_tool "$target_command" "$gateway_id" "$tool_name" "$lambda_arn" "$schema_json" || {
      warn "Tool registration failed for $tool_name. Falling back to direct Lambda invocation mode."
      state_set_string "agentcore_mode" "direct"
      state_set_string "agentcore_gateway_id" ""
      state_set_string "agentcore_gateway_endpoint" ""
      return 0
    }
  done < <(jq -r '.tools[].name' "$ROOT_DIR/infrastructure/gateway/tool-schemas.json")

  state_set_string "agentcore_mode" "gateway"
  state_set_string "agentcore_gateway_id" "$gateway_id"
  state_set_string "agentcore_gateway_endpoint" "$endpoint"
}

package_agent_lambda() {
  local package_dir="$BUILD_DIR/agent/package"
  local zip_path="$BUILD_DIR/agent/agent.zip"

  rm -rf "$BUILD_DIR/agent"
  mkdir -p "$package_dir"
  python3 -m pip install --quiet -r "$ROOT_DIR/agent/requirements.txt" -t "$package_dir"
  cp "$ROOT_DIR/agent/agent_core.py" "$package_dir/agent_core.py"
  cp "$ROOT_DIR/agent/handler.py" "$package_dir/handler.py"
  cp "$ROOT_DIR/agent/local_server.py" "$package_dir/local_server.py"
  (cd "$package_dir" && zip -qr "$zip_path" .)
  echo "$zip_path"
}

deploy_agent_lambda() {
  log "Deploying Strands agent Lambda"
  ensure_state_file
  local agent_role_arn function_name zip_path gateway_endpoint direct_tool_json function_arn
  agent_role_arn="$(state_get '.agent_role_arn')"
  function_name="${PROJECT_NAME}-agent-${STACK_SUFFIX}"
  zip_path="$(package_agent_lambda)"
  gateway_endpoint="$(state_get '.agentcore_gateway_endpoint')"
  direct_tool_json="$(jq -n \
    --arg realtime "$(state_get --arg key 'realtime-metrics' '.tool_lambda_names[$key] // empty')" \
    --arg historical "$(state_get --arg key 'historical-metrics' '.tool_lambda_names[$key] // empty')" \
    --arg states "$(state_get --arg key 'agent-states' '.tool_lambda_names[$key] // empty')" \
    --arg search "$(state_get --arg key 'search-contacts' '.tool_lambda_names[$key] // empty')" \
    --arg detail "$(state_get --arg key 'contact-detail' '.tool_lambda_names[$key] // empty')" \
    --arg transcript "$(state_get --arg key 'transcript' '.tool_lambda_names[$key] // empty')" \
    --arg keyword "$(state_get --arg key 'keyword-search' '.tool_lambda_names[$key] // empty')" \
    --arg recording "$(state_get --arg key 'recording-url' '.tool_lambda_names[$key] // empty')" \
    --arg flow_events "$(state_get --arg key 'contact-flow-events' '.tool_lambda_names[$key] // empty')" \
    '{
      get_realtime_metrics: $realtime,
      get_historical_metrics: $historical,
      get_agent_states: $states,
      search_contacts: $search,
      get_contact_detail: $detail,
      get_transcript: $transcript,
      keyword_search: $keyword,
      get_recording_url: $recording,
      contact_flow_events: $flow_events
    }' | jq -c '.')"

  jq -n \
    --arg gateway_endpoint "$gateway_endpoint" \
    --arg connect_instance_id "$CONNECT_INSTANCE_ID" \
    --arg bedrock_model_id "$BEDROCK_MODEL_ID" \
    --arg aws_region "$AWS_REGION" \
    --arg direct_tool_lambdas "$direct_tool_json" \
    '{
      Variables: {
        AGENTCORE_GATEWAY_ENDPOINT: $gateway_endpoint,
        CONNECT_INSTANCE_ID: $connect_instance_id,
        BEDROCK_MODEL_ID: $bedrock_model_id,
        AWS_REGION: $aws_region,
        DIRECT_TOOL_LAMBDAS: $direct_tool_lambdas
      }
    }' > "$BUILD_DIR/agent-environment.json"

  function_arn="$(create_or_update_lambda "$function_name" "$agent_role_arn" "$zip_path" "handler.lambda_handler" "file://$BUILD_DIR/agent-environment.json")"

  state_set_string "agent_lambda_name" "$function_name"
  state_set_string "agent_lambda_arn" "$function_arn"
}

ensure_api_resource() {
  local rest_api_id="$1"
  local parent_id="$2"
  local path_part="$3"
  local full_path="$4"
  local existing_id
  existing_id="$(aws apigateway get-resources --rest-api-id "$rest_api_id" --query "items[?path=='$full_path'].id | [0]" --output text)"
  if [[ -n "$existing_id" && "$existing_id" != "None" ]]; then
    echo "$existing_id"
    return 0
  fi
  aws apigateway create-resource --rest-api-id "$rest_api_id" --parent-id "$parent_id" --path-part "$path_part" --query 'id' --output text
}

configure_api_method() {
  local rest_api_id="$1"
  local resource_id="$2"
  local http_method="$3"
  local lambda_arn="$4"

  aws apigateway put-method --rest-api-id "$rest_api_id" --resource-id "$resource_id" --http-method "$http_method" --authorization-type NONE >/dev/null 2>&1 || true
  aws apigateway put-integration --rest-api-id "$rest_api_id" --resource-id "$resource_id" --http-method "$http_method" --type AWS_PROXY --integration-http-method POST --uri "arn:aws:apigateway:${AWS_REGION}:lambda:path/2015-03-31/functions/${lambda_arn}/invocations" >/dev/null
}

configure_options_method() {
  local rest_api_id="$1"
  local resource_id="$2"
  aws apigateway put-method --rest-api-id "$rest_api_id" --resource-id "$resource_id" --http-method OPTIONS --authorization-type NONE >/dev/null 2>&1 || true
  aws apigateway put-integration --rest-api-id "$rest_api_id" --resource-id "$resource_id" --http-method OPTIONS --type MOCK --request-templates '{"application/json":"{\"statusCode\": 200}"}' >/dev/null 2>&1 || true
  aws apigateway put-method-response --rest-api-id "$rest_api_id" --resource-id "$resource_id" --http-method OPTIONS --status-code 200 --response-parameters 'method.response.header.Access-Control-Allow-Headers=true,method.response.header.Access-Control-Allow-Methods=true,method.response.header.Access-Control-Allow-Origin=true' >/dev/null 2>&1 || true
  aws apigateway put-integration-response --rest-api-id "$rest_api_id" --resource-id "$resource_id" --http-method OPTIONS --status-code 200 --response-parameters 'method.response.header.Access-Control-Allow-Headers="Content-Type,Authorization",method.response.header.Access-Control-Allow-Methods="GET,POST,OPTIONS",method.response.header.Access-Control-Allow-Origin="*"' >/dev/null 2>&1 || true
}

deploy_api_gateway() {
  log "Deploying API Gateway"
  ensure_state_file
  local api_name rest_api_id lambda_arn root_id api_id query_id health_id metrics_id invoke_root
  api_name="${PROJECT_NAME}-api-${STACK_SUFFIX}"
  rest_api_id="$(state_get '.api_gateway_id')"
  lambda_arn="$(state_get '.agent_lambda_arn')"

  if [[ -z "$rest_api_id" ]]; then
    rest_api_id="$(aws apigateway create-rest-api --name "$api_name" --endpoint-configuration types=REGIONAL --query 'id' --output text)"
  fi

  root_id="$(aws apigateway get-resources --rest-api-id "$rest_api_id" --query "items[?path=='/'].id | [0]" --output text)"
  api_id="$(ensure_api_resource "$rest_api_id" "$root_id" "api" "/api")"
  query_id="$(ensure_api_resource "$rest_api_id" "$api_id" "query" "/api/query")"
  health_id="$(ensure_api_resource "$rest_api_id" "$api_id" "health" "/api/health")"
  metrics_id="$(ensure_api_resource "$rest_api_id" "$api_id" "metrics" "/api/metrics")"

  configure_api_method "$rest_api_id" "$query_id" POST "$lambda_arn"
  configure_api_method "$rest_api_id" "$health_id" GET "$lambda_arn"
  configure_api_method "$rest_api_id" "$metrics_id" GET "$lambda_arn"
  configure_options_method "$rest_api_id" "$query_id"
  configure_options_method "$rest_api_id" "$health_id"
  configure_options_method "$rest_api_id" "$metrics_id"

  aws lambda add-permission --function-name "$lambda_arn" --statement-id "apigateway-${STACK_SUFFIX}" --action lambda:InvokeFunction --principal apigateway.amazonaws.com --source-arn "arn:aws:execute-api:${AWS_REGION}:${ACCOUNT_ID}:${rest_api_id}/*/*/*" >/dev/null 2>&1 || true
  aws apigateway create-deployment --rest-api-id "$rest_api_id" --stage-name prod >/dev/null

  invoke_root="https://${rest_api_id}.execute-api.${AWS_REGION}.amazonaws.com/prod"
  state_set_string "api_gateway_id" "$rest_api_id"
  state_set_string "api_gateway_invoke_url_root" "$invoke_root"
  state_set_string "api_gateway_url" "$invoke_root/api"
}

deploy_cognito() {
  log "Deploying Cognito"
  ensure_state_file
  local pool_name client_name user_pool_id client_id
  pool_name="${PROJECT_NAME}-users-${STACK_SUFFIX}"
  client_name="${PROJECT_NAME}-frontend-${STACK_SUFFIX}"

  user_pool_id="$(aws cognito-idp list-user-pools --max-results 60 --query "UserPools[?Name=='$pool_name'].Id | [0]" --output text)"
  if [[ -z "$user_pool_id" || "$user_pool_id" == "None" ]]; then
    user_pool_id="$(aws cognito-idp create-user-pool --pool-name "$pool_name" --auto-verified-attributes email --username-attributes email --query 'UserPool.Id' --output text)"
  fi

  client_id="$(aws cognito-idp list-user-pool-clients --user-pool-id "$user_pool_id" --max-results 60 --query "UserPoolClients[?ClientName=='$client_name'].ClientId | [0]" --output text)"
  if [[ -z "$client_id" || "$client_id" == "None" ]]; then
    client_id="$(aws cognito-idp create-user-pool-client --user-pool-id "$user_pool_id" --client-name "$client_name" --generate-secret false --explicit-auth-flows ALLOW_USER_PASSWORD_AUTH ALLOW_REFRESH_TOKEN_AUTH ALLOW_USER_SRP_AUTH --query 'UserPoolClient.ClientId' --output text)"
  fi

  state_set_string "cognito_user_pool_id" "$user_pool_id"
  state_set_string "cognito_client_id" "$client_id"
}

create_bucket_if_needed() {
  local bucket_name="$1"
  if aws s3api head-bucket --bucket "$bucket_name" >/dev/null 2>&1; then
    return 0
  fi
  if [[ "$AWS_REGION" == "us-east-1" ]]; then
    aws s3api create-bucket --bucket "$bucket_name" >/dev/null
  else
    aws s3api create-bucket --bucket "$bucket_name" --create-bucket-configuration "LocationConstraint=$AWS_REGION" >/dev/null
  fi
}

configure_website_bucket() {
  local bucket_name="$1"
  aws s3 website "s3://$bucket_name" --index-document index.html --error-document index.html >/dev/null
  aws s3api put-public-access-block --bucket "$bucket_name" --public-access-block-configuration BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false >/dev/null
  cat > "$BUILD_DIR/frontend-bucket-policy.json" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadForWebsite",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::$bucket_name/*"
    }
  ]
}
EOF
  aws s3api put-bucket-policy --bucket "$bucket_name" --policy "file://$BUILD_DIR/frontend-bucket-policy.json" >/dev/null
}

write_frontend_env() {
  cat > "$ROOT_DIR/frontend/.env.production" <<EOF
VITE_API_URL=/api
VITE_ENVIRONMENT=cloud
VITE_COGNITO_USER_POOL_ID=$(state_get '.cognito_user_pool_id')
VITE_COGNITO_CLIENT_ID=$(state_get '.cognito_client_id')
VITE_AWS_REGION=$AWS_REGION
EOF
}

build_cloudfront_config() {
  local bucket_name="$1"
  local api_root="$2"
  local bucket_domain api_domain api_origin_path
  bucket_domain="${bucket_name}.s3-website-${AWS_REGION}.amazonaws.com"
  api_domain="$(sed -E 's#https?://([^/]+)/?.*#\1#' <<< "$api_root")"
  api_origin_path="$(sed -E 's#https?://[^/]+(.*)#\1#' <<< "$api_root")"

  jq -n \
    --arg caller_reference "${PROJECT_NAME}-${STACK_SUFFIX}-$(date +%s)" \
    --arg comment "$DISTRIBUTION_COMMENT" \
    --arg bucket_domain "$bucket_domain" \
    --arg api_domain "$api_domain" \
    --arg api_origin_path "$api_origin_path" \
    '{
      CallerReference: $caller_reference,
      Comment: $comment,
      Enabled: true,
      DefaultRootObject: "index.html",
      Origins: {
        Quantity: 2,
        Items: [
          {
            Id: "s3-origin",
            DomainName: $bucket_domain,
            CustomOriginConfig: {
              HTTPPort: 80,
              HTTPSPort: 443,
              OriginProtocolPolicy: "http-only",
              OriginSslProtocols: {Quantity: 1, Items: ["TLSv1.2"]}
            }
          },
          {
            Id: "api-origin",
            DomainName: $api_domain,
            OriginPath: $api_origin_path,
            CustomOriginConfig: {
              HTTPPort: 80,
              HTTPSPort: 443,
              OriginProtocolPolicy: "https-only",
              OriginSslProtocols: {Quantity: 1, Items: ["TLSv1.2"]}
            }
          }
        ]
      },
      DefaultCacheBehavior: {
        TargetOriginId: "s3-origin",
        ViewerProtocolPolicy: "redirect-to-https",
        AllowedMethods: {
          Quantity: 2,
          Items: ["GET", "HEAD"],
          CachedMethods: {Quantity: 2, Items: ["GET", "HEAD"]}
        },
        Compress: true,
        ForwardedValues: {QueryString: false, Cookies: {Forward: "none"}},
        MinTTL: 0
      },
      CacheBehaviors: {
        Quantity: 1,
        Items: [
          {
            PathPattern: "api/*",
            TargetOriginId: "api-origin",
            ViewerProtocolPolicy: "redirect-to-https",
            AllowedMethods: {
              Quantity: 7,
              Items: ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"],
              CachedMethods: {Quantity: 2, Items: ["GET", "HEAD"]}
            },
            Compress: true,
            ForwardedValues: {
              QueryString: true,
              Headers: {Quantity: 3, Items: ["Authorization", "Content-Type", "Origin"]},
              Cookies: {Forward: "all"}
            },
            MinTTL: 0,
            DefaultTTL: 0,
            MaxTTL: 0
          }
        ]
      },
      CustomErrorResponses: {
        Quantity: 2,
        Items: [
          {ErrorCode: 403, ResponsePagePath: "/index.html", ResponseCode: "200", ErrorCachingMinTTL: 0},
          {ErrorCode: 404, ResponsePagePath: "/index.html", ResponseCode: "200", ErrorCachingMinTTL: 0}
        ]
      },
      PriceClass: "PriceClass_100",
      ViewerCertificate: {CloudFrontDefaultCertificate: true},
      Restrictions: {GeoRestriction: {RestrictionType: "none", Quantity: 0}}
    }' > "$BUILD_DIR/cloudfront-distribution.json"
}

wait_for_distribution() {
  local distribution_id="$1"
  local attempts=0
  while (( attempts < 60 )); do
    local status
    status="$(aws cloudfront get-distribution --id "$distribution_id" --query 'Distribution.Status' --output text 2>/dev/null || echo 'Unknown')"
    [[ "$status" == "Deployed" ]] && return 0
    sleep 20
    attempts=$((attempts + 1))
  done
  warn "CloudFront distribution $distribution_id did not reach Deployed in the expected window."
}

deploy_frontend() {
  log "Building and deploying frontend"
  ensure_state_file
  create_bucket_if_needed "$FRONTEND_BUCKET"
  configure_website_bucket "$FRONTEND_BUCKET"
  write_frontend_env

  (cd "$ROOT_DIR/frontend" && npm install && npm run build)
  aws s3 sync "$ROOT_DIR/frontend/dist" "s3://$FRONTEND_BUCKET" --delete >/dev/null

  local distribution_id distribution_domain api_root create_output
  distribution_id="$(state_get '.cloudfront_distribution_id')"
  api_root="$(state_get '.api_gateway_invoke_url_root')"

  if [[ -n "$distribution_id" ]]; then
    aws cloudfront create-invalidation --distribution-id "$distribution_id" --paths '/*' >/dev/null || true
    wait_for_distribution "$distribution_id"
    state_set_string "cloudfront_url" "https://$(aws cloudfront get-distribution --id "$distribution_id" --query 'Distribution.DomainName' --output text)"
    return 0
  fi

  build_cloudfront_config "$FRONTEND_BUCKET" "$api_root"
  create_output="$(aws cloudfront create-distribution --distribution-config "file://$BUILD_DIR/cloudfront-distribution.json")"
  distribution_id="$(jq -r '.Distribution.Id' <<< "$create_output")"
  distribution_domain="$(jq -r '.Distribution.DomainName' <<< "$create_output")"

  wait_for_distribution "$distribution_id"
  state_set_string "frontend_bucket" "$FRONTEND_BUCKET"
  state_set_string "cloudfront_distribution_id" "$distribution_id"
  state_set_string "cloudfront_url" "https://$distribution_domain"
}

print_summary() {
  cat <<EOF

================================================
Deployment complete
================================================
Region: $AWS_REGION
Connect Instance: $CONNECT_INSTANCE_ID
Mode: $(state_get '.agentcore_mode')
AgentCore Gateway Endpoint: $(state_get '.agentcore_gateway_endpoint')
Agent Lambda: $(state_get '.agent_lambda_arn')
API URL: $(state_get '.api_gateway_url')
Cognito User Pool: $(state_get '.cognito_user_pool_id')
Cognito App Client: $(state_get '.cognito_client_id')
Frontend Bucket: $(state_get '.frontend_bucket')
CloudFront URL: $(state_get '.cloudfront_url')
State file: $STATE_FILE

Next steps:
1. Open the CloudFront URL.
2. Create users in the Cognito pool if you want cloud auth.
3. Ask questions such as "How many agents are busy right now?"
================================================
EOF
}

disable_and_delete_distribution() {
  local distribution_id="$1"
  [[ -n "$distribution_id" ]] || return 0
  aws cloudfront get-distribution-config --id "$distribution_id" > "$BUILD_DIR/distribution-config.json" 2>/dev/null || return 0
  local etag
  etag="$(jq -r '.ETag' "$BUILD_DIR/distribution-config.json")"
  jq '.DistributionConfig.Enabled = false | .DistributionConfig' "$BUILD_DIR/distribution-config.json" > "$BUILD_DIR/distribution-update.json"
  aws cloudfront update-distribution --id "$distribution_id" --if-match "$etag" --distribution-config "file://$BUILD_DIR/distribution-update.json" >/dev/null 2>&1 || true
  wait_for_distribution "$distribution_id"
  aws cloudfront get-distribution-config --id "$distribution_id" > "$BUILD_DIR/distribution-config.json" 2>/dev/null || return 0
  etag="$(jq -r '.ETag' "$BUILD_DIR/distribution-config.json")"
  aws cloudfront delete-distribution --id "$distribution_id" --if-match "$etag" >/dev/null 2>&1 || true
}

teardown_frontend() {
  log "Tearing down frontend resources"
  local distribution_id bucket_name
  distribution_id="$(state_get '.cloudfront_distribution_id')"
  bucket_name="$(state_get '.frontend_bucket')"
  disable_and_delete_distribution "$distribution_id"
  if [[ -n "$bucket_name" ]]; then
    aws s3 rm "s3://$bucket_name" --recursive >/dev/null 2>&1 || true
    aws s3api delete-bucket-policy --bucket "$bucket_name" >/dev/null 2>&1 || true
    aws s3api delete-bucket --bucket "$bucket_name" >/dev/null 2>&1 || true
  fi
}

teardown_cognito() {
  log "Tearing down Cognito"
  local pool_id
  pool_id="$(state_get '.cognito_user_pool_id')"
  [[ -n "$pool_id" ]] && aws cognito-idp delete-user-pool --user-pool-id "$pool_id" >/dev/null 2>&1 || true
}

teardown_api_gateway() {
  log "Tearing down API Gateway"
  local api_id
  api_id="$(state_get '.api_gateway_id')"
  [[ -n "$api_id" ]] && aws apigateway delete-rest-api --rest-api-id "$api_id" >/dev/null 2>&1 || true
}

teardown_agent_lambda() {
  log "Deleting agent Lambda"
  local function_name
  function_name="$(state_get '.agent_lambda_name')"
  [[ -n "$function_name" ]] && aws lambda delete-function --function-name "$function_name" >/dev/null 2>&1 || true
}

teardown_agentcore_gateway() {
  log "Deleting AgentCore gateway"
  local gateway_id mode
  gateway_id="$(state_get '.agentcore_gateway_id')"
  mode="$(state_get '.agentcore_mode')"
  if [[ "$mode" == "gateway" && -n "$gateway_id" ]]; then
    aws bedrock-agentcore-control delete-gateway --gateway-id "$gateway_id" >/dev/null 2>&1 || true
  fi
}

teardown_lambda_tools() {
  log "Deleting tool Lambdas"
  for tool_key in "${TOOL_NAMES[@]}"; do
    local function_name
    function_name="$(state_get --arg key "$tool_key" '.tool_lambda_names[$key]')"
    [[ -n "$function_name" ]] && aws lambda delete-function --function-name "$function_name" >/dev/null 2>&1 || true
  done
}

teardown_iam_policies() {
  log "Deleting IAM policies"
  local lambda_policy_arn agent_policy_arn gateway_policy_arn
  lambda_policy_arn="$(state_get '.lambda_policy_arn')"
  agent_policy_arn="$(state_get '.agent_policy_arn')"
  gateway_policy_arn="$(state_get '.gateway_policy_arn')"

  detach_policy_from_role "$LAMBDA_ROLE_NAME" "$lambda_policy_arn"
  detach_policy_from_role "$AGENT_ROLE_NAME" "$agent_policy_arn"
  detach_policy_from_role "$GATEWAY_ROLE_NAME" "$gateway_policy_arn"

  [[ -n "$lambda_policy_arn" ]] && aws iam delete-policy --policy-arn "$lambda_policy_arn" >/dev/null 2>&1 || true
  [[ -n "$agent_policy_arn" ]] && aws iam delete-policy --policy-arn "$agent_policy_arn" >/dev/null 2>&1 || true
  [[ -n "$gateway_policy_arn" ]] && aws iam delete-policy --policy-arn "$gateway_policy_arn" >/dev/null 2>&1 || true
}

teardown_iam_roles() {
  log "Deleting IAM roles"
  aws iam delete-role --role-name "$LAMBDA_ROLE_NAME" >/dev/null 2>&1 || true
  aws iam delete-role --role-name "$AGENT_ROLE_NAME" >/dev/null 2>&1 || true
  aws iam delete-role --role-name "$GATEWAY_ROLE_NAME" >/dev/null 2>&1 || true
}

delete_log_groups() {
  log "Deleting CloudWatch log groups"
  local agent_lambda_name
  agent_lambda_name="$(state_get '.agent_lambda_name')"
  [[ -n "$agent_lambda_name" ]] && aws logs delete-log-group --log-group-name "/aws/lambda/$agent_lambda_name" >/dev/null 2>&1 || true
  for tool_key in "${TOOL_NAMES[@]}"; do
    local function_name
    function_name="$(state_get --arg key "$tool_key" '.tool_lambda_names[$key]')"
    [[ -n "$function_name" ]] && aws logs delete-log-group --log-group-name "/aws/lambda/$function_name" >/dev/null 2>&1 || true
  done
}

deploy() {
  validate_prerequisites
  ensure_build_dir
  state_init
  deploy_iam_roles
  deploy_iam_policies
  deploy_lambda_tools
  deploy_agentcore_gateway
  deploy_agent_lambda
  deploy_api_gateway
  deploy_cognito
  deploy_frontend
  print_summary
  cleanup_build_dir
}

teardown() {
  validate_prerequisites
  ensure_build_dir
  if [[ ! -f "$STATE_FILE" ]]; then
    warn "State file not found at $STATE_FILE. Proceeding with best-effort teardown using derived names only."
    state_init
  fi
  teardown_frontend
  teardown_cognito
  teardown_api_gateway
  teardown_agent_lambda
  teardown_agentcore_gateway
  teardown_lambda_tools
  teardown_iam_policies
  teardown_iam_roles
  teardown_eventbridge
  delete_log_groups
  rm -f "$STATE_FILE"
  cleanup_build_dir
  echo "Teardown complete."
}

# ── EventBridge + SQS setup/teardown ────────────────────────────────────────

EVENTBRIDGE_RULE_NAME="${PROJECT_NAME}-bot-contact-events"
SQS_QUEUE_NAME="${PROJECT_NAME}-bot-contact-events"

setup_eventbridge() {
  # Only needs AWS CLI configured — prompt for CONNECT_INSTANCE_ID if not exported
  if ! command -v aws &>/dev/null; then
    die "AWS CLI is not installed or not in PATH."
  fi
  if ! aws sts get-caller-identity &>/dev/null; then
    die "AWS credentials are not configured. Run 'aws configure' or export AWS_PROFILE/AWS_ACCESS_KEY_ID."
  fi

  if [[ -z "${CONNECT_INSTANCE_ID:-}" ]]; then
    echo ""
    read -r -p "Amazon Connect Instance ID: " instance_id
    if [[ -z "$instance_id" ]]; then
      die "CONNECT_INSTANCE_ID is required. Aborting."
    fi
    export CONNECT_INSTANCE_ID="$instance_id"
  fi

  log "Setting up EventBridge rule + SQS queue for live bot contact events…"

  ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
  local queue_url queue_arn rule_arn

  # 1. Create SQS standard queue (idempotent)
  queue_url="$(aws sqs create-queue \
    --queue-name "$SQS_QUEUE_NAME" \
    --attributes '{"MessageRetentionPeriod":"3600","VisibilityTimeout":"30"}' \
    --query QueueUrl --output text 2>/dev/null || \
    aws sqs get-queue-url --queue-name "$SQS_QUEUE_NAME" --query QueueUrl --output text)"
  log "SQS queue: $queue_url"

  # Ensure retention is set to 1 hour (idempotent — updates existing queue too)
  aws sqs set-queue-attributes \
    --queue-url "$queue_url" \
    --attributes '{"MessageRetentionPeriod":"3600"}' >/dev/null 2>&1 || true

  queue_arn="$(aws sqs get-queue-attributes \
    --queue-url "$queue_url" \
    --attribute-names QueueArn \
    --query 'Attributes.QueueArn' --output text)"

  # 2. Grant EventBridge permission to send to the queue
  # Build the policy JSON in a temp file, then use jq to embed it as a properly
  # escaped string inside the --cli-input-json payload (avoids shell quoting issues).
  local policy_file
  policy_file="$(mktemp /tmp/eb-sqs-policy.XXXXXX.json)"
  cat > "$policy_file" <<POLICY
{"Version":"2012-10-17","Id":"${SQS_QUEUE_NAME}-eb-policy","Statement":[{"Sid":"AllowEventBridge","Effect":"Allow","Principal":{"Service":"events.amazonaws.com"},"Action":"sqs:SendMessage","Resource":"${queue_arn}","Condition":{"ArnEquals":{"aws:SourceArn":"arn:aws:events:${AWS_REGION}:${ACCOUNT_ID}:rule/${EVENTBRIDGE_RULE_NAME}"}}}]}
POLICY
  aws sqs set-queue-attributes \
    --cli-input-json "$(jq -n \
        --arg url    "$queue_url" \
        --arg policy "$(cat "$policy_file")" \
        '{QueueUrl: $url, Attributes: {Policy: $policy}}')" >/dev/null
  rm -f "$policy_file"
  log "SQS queue policy set (allows EventBridge to send)"

  # 3. Create (or update) the EventBridge rule — captures ALL Connect contact + agent events
  rule_arn="$(aws events put-rule \
    --name "$EVENTBRIDGE_RULE_NAME" \
    --event-pattern '{"source":["aws.connect"],"detail-type":["Amazon Connect Contact Event","Amazon Connect Agent Event"]}' \
    --state ENABLED \
    --description "Forwards Amazon Connect contact + agent events to SQS for live activity tracking" \
    --query RuleArn --output text)"
  log "EventBridge rule: $rule_arn"

  # 4. Add SQS as the rule target
  aws events put-targets \
    --rule "$EVENTBRIDGE_RULE_NAME" \
    --targets "[{\"Id\":\"connect-bot-sqs\",\"Arn\":\"${queue_arn}\"}]" >/dev/null
  log "EventBridge target set to SQS queue"

  # Persist to state file
  [[ -f "$STATE_FILE" ]] || state_init
  state_set_string 'bot_events_queue_url' "$queue_url"
  state_set_string 'bot_events_queue_arn' "$queue_arn"
  state_set_string 'eventbridge_rule_name' "$EVENTBRIDGE_RULE_NAME"

  echo ""
  echo "═══════════════════════════════════════════════════════"
  echo "  EventBridge + SQS setup complete"
  echo "  Queue URL : $queue_url"
  echo ""
  echo "  If Docker is already running, activate the listener"
  echo "  immediately (no restart needed):"
  echo ""
  echo "    curl -s -X PUT http://localhost:8100/api/eventbridge/configure \\"
  echo "         -H 'Content-Type: application/json' \\"
  echo "         -d '{\"queue_url\": \"$queue_url\"}'"
  echo ""
  echo "  On next Docker start the queue URL is read automatically"
  echo "  from the state file — no extra env var needed."
  echo "═══════════════════════════════════════════════════════"
}

teardown_eventbridge() {
  local queue_url rule_name
  queue_url="$(state_get '.bot_events_queue_url' 2>/dev/null || echo '')"
  rule_name="$(state_get '.eventbridge_rule_name' 2>/dev/null || echo "$EVENTBRIDGE_RULE_NAME")"

  if [[ -n "$rule_name" ]]; then
    log "Removing EventBridge rule targets…"
    aws events remove-targets --rule "$rule_name" --ids "connect-bot-sqs" >/dev/null 2>&1 || true
    log "Deleting EventBridge rule $rule_name…"
    aws events delete-rule --name "$rule_name" >/dev/null 2>&1 || true
  fi

  if [[ -n "$queue_url" ]]; then
    log "Deleting SQS queue $queue_url…"
    aws sqs delete-queue --queue-url "$queue_url" >/dev/null 2>&1 || true
  else
    # Best-effort by name
    local q
    q="$(aws sqs get-queue-url --queue-name "$SQS_QUEUE_NAME" --query QueueUrl --output text 2>/dev/null || echo '')"
    [[ -n "$q" ]] && aws sqs delete-queue --queue-url "$q" >/dev/null 2>&1 || true
  fi
  log "EventBridge + SQS teardown complete"
}


local_start() {
  validate_local_prerequisites

  # Ensure state file exists so the Docker volume mount doesn't fail
  [[ -f "$STATE_FILE" ]] || echo '{}' > "$STATE_FILE"

  # ── Load saved config from state file ───────────────────────────────────────
  local saved_mock saved_profile saved_region saved_instance saved_alias saved_queue
  saved_mock="$(state_get '.local_mock_mode // ""' 2>/dev/null || echo '')"
  saved_profile="$(state_get '.local_aws_profile // ""' 2>/dev/null || echo '')"
  saved_region="$(state_get '.local_aws_region // ""' 2>/dev/null || echo '')"
  saved_instance="$(state_get '.connect_instance_id // ""' 2>/dev/null || echo '')"
  saved_alias="$(state_get '.connect_alias // ""' 2>/dev/null || echo '')"
  saved_queue="$(state_get '.bot_events_queue_url // ""' 2>/dev/null || echo '')"

  # If a complete saved config exists and nothing was pre-exported, offer to reuse it
  local has_saved=false
  if [[ -n "$saved_instance" && -n "$saved_mock" ]]; then
    has_saved=true
  fi

  echo ""
  echo "┌─────────────────────────────────────────────────┐"
  echo "│       Amazon Connect Analytics Agent — Local     │"
  echo "└─────────────────────────────────────────────────┘"
  echo ""

  if $has_saved; then
    echo "  Saved config found in state file:"
    echo "    Mode    : $( [[ "$saved_mock" == "true" ]] && echo "Mock" || echo "Real AWS" )"
    [[ "$saved_mock" != "true" ]] && echo "    Profile : ${saved_profile}"
    [[ "$saved_mock" != "true" ]] && echo "    Region  : ${saved_region}"
    [[ "$saved_mock" != "true" ]] && echo "    Instance: ${saved_instance}"
    [[ -n "$saved_alias" ]]       && echo "    Alias   : ${saved_alias}"
    [[ -n "$saved_queue" ]]       && echo "    SQS     : ${saved_queue}"
    echo ""
    read -r -p "  Use saved config? [Y/n]: " use_saved
    use_saved="${use_saved:-Y}"
    if [[ "${use_saved,,}" == "y" || "${use_saved,,}" == "yes" ]]; then
      export MOCK_MODE="$saved_mock"
      export AWS_PROFILE="${saved_profile:-default}"
      export AWS_REGION="${saved_region:-eu-west-2}"
      export CONNECT_INSTANCE_ID="${saved_instance:-}"
      export CONNECT_ALIAS="${saved_alias:-}"
      export BOT_EVENTS_QUEUE_URL="${saved_queue:-}"
      _launch_docker
      return
    fi
  fi

  echo "How would you like to run locally?"
  echo ""
  echo "  1) Mock mode      — no AWS needed, returns realistic fake data"
  echo "  2) Real AWS data  — uses your local ~/.aws credentials to query"
  echo "                      a real Amazon Connect instance"
  echo ""
  read -r -p "Enter choice [1/2] (default: 1): " mode_choice
  mode_choice="${mode_choice:-1}"

  case "$mode_choice" in
    2)
      export MOCK_MODE=false

      if [[ ! -d "${HOME}/.aws" ]]; then
        echo "⚠  ~/.aws directory not found. Run 'aws configure' first."
        exit 1
      fi

      local default_profile="${AWS_PROFILE:-${saved_profile:-default}}"
      read -r -p "AWS profile to use [${default_profile}]: " chosen_profile
      export AWS_PROFILE="${chosen_profile:-$default_profile}"

      local default_instance="${CONNECT_INSTANCE_ID:-$saved_instance}"
      if [[ -z "$default_instance" ]]; then
        read -r -p "Amazon Connect Instance ID: " instance_id
        [[ -z "$instance_id" ]] && { echo "⚠  Required. Aborting."; exit 1; }
        export CONNECT_INSTANCE_ID="$instance_id"
      else
        read -r -p "Amazon Connect Instance ID [${default_instance}]: " instance_id
        export CONNECT_INSTANCE_ID="${instance_id:-$default_instance}"
      fi

      local default_alias="${CONNECT_ALIAS:-$saved_alias}"
      read -r -p "Connect instance alias [${default_alias:-leave blank}]: " connect_alias
      export CONNECT_ALIAS="${connect_alias:-$default_alias}"

      local default_queue="${BOT_EVENTS_QUEUE_URL:-$saved_queue}"
      if [[ -n "$default_queue" ]]; then
        read -r -p "SQS queue URL [${default_queue}]: " bot_queue_url
        export BOT_EVENTS_QUEUE_URL="${bot_queue_url:-$default_queue}"
      else
        echo "  (Optional) EventBridge SQS queue URL — run ./deploy.sh setup-eventbridge first"
        read -r -p "BOT_EVENTS_QUEUE_URL [leave blank to skip]: " bot_queue_url
        export BOT_EVENTS_QUEUE_URL="${bot_queue_url:-}"
      fi

      local default_region="${AWS_REGION:-${saved_region:-eu-west-2}}"
      read -r -p "AWS region [${default_region}]: " chosen_region
      export AWS_REGION="${chosen_region:-$default_region}"

      # ── Persist all params to state file so next run skips prompts ──────────
      state_set_string 'local_mock_mode'    'false'
      state_set_string 'local_aws_profile'  "$AWS_PROFILE"
      state_set_string 'local_aws_region'   "$AWS_REGION"
      state_set_string 'connect_instance_id' "$CONNECT_INSTANCE_ID"
      state_set_string 'connect_alias'      "$CONNECT_ALIAS"
      [[ -n "$BOT_EVENTS_QUEUE_URL" ]] && state_set_string 'bot_events_queue_url' "$BOT_EVENTS_QUEUE_URL"

      echo ""
      echo "✔  Real AWS mode — config saved to state file (next run will skip these prompts)"
      echo "   Profile : ${AWS_PROFILE}  |  Region: ${AWS_REGION}"
      echo "   Instance: ${CONNECT_INSTANCE_ID}"
      [[ -n "$CONNECT_ALIAS" ]]          && echo "   Alias   : ${CONNECT_ALIAS}"
      [[ -n "$BOT_EVENTS_QUEUE_URL" ]]   && echo "   SQS     : ${BOT_EVENTS_QUEUE_URL}"
      ;;
    *)
      export MOCK_MODE=true
      state_set_string 'local_mock_mode' 'true'
      echo "✔  Mock mode — no AWS credentials required"
      ;;
  esac

  echo ""
  _launch_docker
}

# Restart/rebuild containers using saved state — no prompts.
local_update() {
  validate_local_prerequisites

  [[ -f "$STATE_FILE" ]] || { echo "[ERROR] No state file found. Run ./deploy.sh local first."; exit 1; }

  local saved_mock saved_profile saved_region saved_instance saved_alias saved_queue
  saved_mock="$(state_get '.local_mock_mode // "true"' 2>/dev/null || echo 'true')"
  saved_profile="$(state_get '.local_aws_profile // "default"' 2>/dev/null || echo 'default')"
  saved_region="$(state_get '.local_aws_region // "eu-west-2"' 2>/dev/null || echo 'eu-west-2')"
  saved_instance="$(state_get '.connect_instance_id // ""' 2>/dev/null || echo '')"
  saved_alias="$(state_get '.connect_alias // ""' 2>/dev/null || echo '')"
  saved_queue="$(state_get '.bot_events_queue_url // ""' 2>/dev/null || echo '')"

  echo ""
  echo "Updating containers from saved config (no prompts)…"
  echo "  Mode    : $( [[ "$saved_mock" == "true" ]] && echo "Mock" || echo "Real AWS" )"
  [[ "$saved_mock" != "true" ]] && echo "  Profile : ${saved_profile}  |  Region: ${saved_region}"
  [[ "$saved_mock" != "true" ]] && echo "  Instance: ${saved_instance}"
  [[ -n "$saved_alias" ]]       && echo "  Alias   : ${saved_alias}"
  [[ -n "$saved_queue" ]]       && echo "  SQS     : ${saved_queue}"
  echo ""

  MOCK_MODE="$saved_mock" \
  AWS_PROFILE="${saved_profile}" \
  AWS_REGION="${saved_region}" \
  CONNECT_INSTANCE_ID="${saved_instance}" \
  CONNECT_ALIAS="${saved_alias}" \
  BOT_EVENTS_QUEUE_URL="${saved_queue}" \
    docker compose -f "$ROOT_DIR/docker/docker-compose.yml" up --build -d

  echo ""
  echo "================================================"
  echo "Containers updated and restarted!"
  echo "Frontend : http://localhost:5274"
  echo "Agent API: http://localhost:8100"
  echo "================================================"
}

_launch_docker() {
  echo "Starting Docker containers..."
  MOCK_MODE="${MOCK_MODE:-false}" \
  AWS_PROFILE="${AWS_PROFILE:-default}" \
  AWS_REGION="${AWS_REGION:-eu-west-2}" \
  CONNECT_INSTANCE_ID="${CONNECT_INSTANCE_ID:-}" \
  CONNECT_ALIAS="${CONNECT_ALIAS:-}" \
  BOT_EVENTS_QUEUE_URL="${BOT_EVENTS_QUEUE_URL:-}" \
    docker compose -f "$ROOT_DIR/docker/docker-compose.yml" up --build -d

  echo ""
  echo "================================================"
  echo "Local environment started!"
  echo "Frontend : http://localhost:5274"
  echo "Agent API: http://localhost:8100"
  if [[ "${MOCK_MODE:-false}" == "true" ]]; then
    echo "Mode: MOCK — realistic fake responses"
  else
    echo "Mode: REAL — querying live Amazon Connect (profile: ${AWS_PROFILE})"
  fi
  echo "================================================"
  docker compose -f "$ROOT_DIR/docker/docker-compose.yml" logs -f
}

local_stop() {
  validate_local_prerequisites
  docker compose -f "$ROOT_DIR/docker/docker-compose.yml" down --remove-orphans
  echo "Local environment stopped."
}

main() {
  local mode="${1:-}"
  case "$mode" in
    deploy)
      deploy
      ;;
    teardown)
      teardown
      ;;
    local)
      local_start
      ;;
    local-stop)
      local_stop
      ;;
    update|local-update)
      local_update
      ;;
    setup-eventbridge)
      setup_eventbridge
      ;;
    teardown-eventbridge)
      teardown_eventbridge
      ;;
    *)
      cat <<EOF
Usage: ./deploy.sh <mode>

Modes:
  local                Start local Docker environment (prompts once, saves config)
  update               Rebuild + restart containers using saved config — no prompts
  local-stop           Stop local Docker environment
  setup-eventbridge    Create EventBridge rule + SQS queue for live bot tracking
  teardown-eventbridge Remove the EventBridge rule and SQS queue
  deploy               Full cloud deployment (Lambdas, AgentCore, CloudFront)
  teardown             Complete teardown of all cloud resources

Tip: Run './deploy.sh local' once to enter your config.
     From then on, use './deploy.sh update' to rebuild after code changes.
EOF
      exit 1
      ;;
  esac
}

main "$@"
