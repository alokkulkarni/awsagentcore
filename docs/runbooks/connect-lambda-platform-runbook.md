# Connect Lambda Platform Runbook

This runbook covers deployment, verification, update, rollback, and teardown for the Connect Lambda Platform resources defined under `scripts/` in `awsagentcore`.

## 1. Pre-deployment checklist

Run from the repository root:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
command -v aws
command -v python3
command -v zip
aws sts get-caller-identity
```

Required state and variables:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
export AWS_REGION="${AWS_REGION:-eu-west-2}"
export AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
export CONNECT_INSTANCE_ID="<your-connect-instance-id>"
export CONNECT_ASSISTANT_ID="<your-q-connect-assistant-id>"
export CONNECT_CONTACT_FLOW_ID="<your-connect-contact-flow-id>"
export CONNECT_QUEUE_ID="<your-connect-queue-id-or-arn>"
export CHAT_WIDGET_URL="https://app.example.com/chat"
export SMS_ORIGINATION_NUMBER="+441234567890"
export SOURCE_PHONE_NUMBER="+441234567890"
export ENV="${ENV:-prod}"
```

Confirm before deployment:

- ARIA AgentCore already deployed
- `scripts/.deploy-state.json` exists and contains the latest AgentCore runtime data
- Amazon Q in Connect is enabled if you will deploy `aria-session-injector-qconnect` or `aria-banking-session-injector-${ENV}`
- `deploy_routing_lambda.sh` is run before `deploy_callback_lambda.sh`
- `deploy_mcp_gateway.sh` is run before channel-transfer testing because it creates `aria-transcript-store`

## 2. Get `AGENTCORE_ENDPOINT` from ARIA deploy state

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
AGENTCORE_ENDPOINT=$(python3 -c "import json; s=json.load(open('scripts/.deploy-state.json')); print(s.get('agentcore_chat_url',''))")
echo "AgentCore endpoint: $AGENTCORE_ENDPOINT"
```

If the value is empty, do not deploy or update `aria-lex-fulfillment` until the ARIA AgentCore stack has been redeployed successfully.

## 3. Deploy resources in order

### 3.1 MCP gateway + env-scoped support Lambdas

This single command deploys:

- `aria-banking-mcp-gateway-${ENV}`
- `aria-banking-session-injector-${ENV}`
- `aria-banking-chat-to-voice-transfer-${ENV}`
- `aria-banking-voice-to-chat-transfer-${ENV}`
- domain Lambdas such as `aria-banking-mcp-auth-${ENV}` and `aria-banking-mcp-customer-${ENV}`

Deploy:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
./scripts/deploy_mcp_gateway.sh deploy \
  --env "$ENV" \
  --region "$AWS_REGION" \
  --instance-id "$CONNECT_INSTANCE_ID" \
  --assistant-id "$CONNECT_ASSISTANT_ID" \
  --flow-id "$CONNECT_CONTACT_FLOW_ID" \
  --queue-id "$CONNECT_QUEUE_ID" \
  --chat-widget-url "$CHAT_WIDGET_URL" \
  --sms-number "$SMS_ORIGINATION_NUMBER" \
  --source-phone "$SOURCE_PHONE_NUMBER"
```

Optional additions supported by the script:

```bash
--instance-url "https://<connect-alias>.my.connect.aws" \
--crm-endpoint "https://crm.internal/api"
```

✓ Verify deployed support Lambdas:

```bash
for fn in \
  "aria-banking-session-injector-${ENV}" \
  "aria-banking-chat-to-voice-transfer-${ENV}" \
  "aria-banking-voice-to-chat-transfer-${ENV}" \
  "aria-banking-mcp-auth-${ENV}"; do
  aws lambda get-function \
    --function-name "$fn" \
    --query 'Configuration.[FunctionName,Runtime,State,LastModified]' \
    --output table
 done
```

✓ Verify MCP gateway exists:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
python3 - <<'PY'
import boto3, os, sys
region = os.environ.get("AWS_REGION", "eu-west-2")
env = os.environ.get("ENV", "prod")
name = f"aria-banking-mcp-gateway-{env}"
client = boto3.client("bedrock-agentcore-control", region_name=region)
for page in client.get_paginator("list_gateways").paginate():
    for item in page.get("items", []):
        if item.get("name") == name:
            print({"gatewayName": name, "gatewayId": item.get("gatewayId")})
            raise SystemExit(0)
raise SystemExit(f"Gateway not found: {name}")
PY
```

Grant Connect permission to the support Lambdas if required by your contact flows:

```bash
aws lambda add-permission \
  --function-name "aria-banking-session-injector-${ENV}" \
  --statement-id "ConnectInvokeSessionInjector${ENV}" \
  --action lambda:InvokeFunction \
  --principal connect.amazonaws.com \
  --source-account "$AWS_ACCOUNT_ID" \
  --source-arn "arn:aws:connect:${AWS_REGION}:${AWS_ACCOUNT_ID}:instance/${CONNECT_INSTANCE_ID}" \
  --region "$AWS_REGION" 2>/dev/null || true

aws lambda add-permission \
  --function-name "aria-banking-chat-to-voice-transfer-${ENV}" \
  --statement-id "ConnectInvokeChatToVoice${ENV}" \
  --action lambda:InvokeFunction \
  --principal connect.amazonaws.com \
  --source-account "$AWS_ACCOUNT_ID" \
  --source-arn "arn:aws:connect:${AWS_REGION}:${AWS_ACCOUNT_ID}:instance/${CONNECT_INSTANCE_ID}" \
  --region "$AWS_REGION" 2>/dev/null || true

aws lambda add-permission \
  --function-name "aria-banking-voice-to-chat-transfer-${ENV}" \
  --statement-id "ConnectInvokeVoiceToChat${ENV}" \
  --action lambda:InvokeFunction \
  --principal connect.amazonaws.com \
  --source-account "$AWS_ACCOUNT_ID" \
  --source-arn "arn:aws:connect:${AWS_REGION}:${AWS_ACCOUNT_ID}:instance/${CONNECT_INSTANCE_ID}" \
  --region "$AWS_REGION" 2>/dev/null || true
```

Test a representative MCP tool Lambda:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
aws lambda invoke \
  --function-name "aria-banking-mcp-auth-${ENV}" \
  --cli-binary-format raw-in-base64-out \
  --payload '{"params":{"name":"auth___verify_customer_identity","arguments":{"customer_id":"CUST-001"}}}' \
  connect-lambda-platform-mcp-auth-response.json && cat connect-lambda-platform-mcp-auth-response.json
```

### 3.2 Routing lookup

Deploy `aria-routing-lookup` (role: `aria-routing-lookup-role`):

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
./scripts/deploy_routing_lambda.sh deploy --instance-id "$CONNECT_INSTANCE_ID"
```

✓ Verify:

```bash
aws lambda get-function \
  --function-name "aria-routing-lookup:prod" \
  --query 'Configuration.[FunctionName,Runtime,State,Timeout,LastModified]' \
  --output table
```

Grant Connect permission (matches the script's alias-based permission model):

```bash
aws lambda add-permission \
  --function-name "arn:aws:lambda:${AWS_REGION}:${AWS_ACCOUNT_ID}:function:aria-routing-lookup:prod" \
  --statement-id "ConnectInvoke" \
  --action lambda:InvokeFunction \
  --principal connect.amazonaws.com \
  --source-account "$AWS_ACCOUNT_ID" \
  --source-arn "arn:aws:connect:${AWS_REGION}:${AWS_ACCOUNT_ID}:instance/${CONNECT_INSTANCE_ID}" \
  --region "$AWS_REGION" 2>/dev/null || true
```

Test invocation:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
aws lambda invoke \
  --function-name "aria-routing-lookup:prod" \
  --cli-binary-format raw-in-base64-out \
  --payload '{"Details":{"ContactData":{"ContactId":"rtg-001","Attributes":{"topicCategory":"mortgage","conversationSummary":"Customer wants mortgage advice","customerIntent":"discuss fixed-rate options","escalationReason":"complex query"}}}}' \
  connect-lambda-platform-routing-response.json && cat connect-lambda-platform-routing-response.json
```

### 3.3 Callback scheduler

Deploy `aria-callback-scheduler` (role: `aria-callback-scheduler-role`):

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
./scripts/deploy_callback_lambda.sh deploy --instance-id "$CONNECT_INSTANCE_ID"
./scripts/deploy_callback_lambda.sh update-queues
```

✓ Verify:

```bash
aws lambda get-function \
  --function-name "aria-callback-scheduler:prod" \
  --query 'Configuration.[FunctionName,Runtime,State,Timeout,LastModified]' \
  --output table
```

Grant Connect permission:

```bash
aws lambda add-permission \
  --function-name "aria-callback-scheduler:prod" \
  --statement-id "ConnectInvoke-callback-scheduler" \
  --action lambda:InvokeFunction \
  --principal connect.amazonaws.com \
  --source-account "$AWS_ACCOUNT_ID" \
  --source-arn "arn:aws:connect:${AWS_REGION}:${AWS_ACCOUNT_ID}:instance/${CONNECT_INSTANCE_ID}" \
  --region "$AWS_REGION" 2>/dev/null || true
```

Test invocation:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
aws lambda invoke \
  --function-name "aria-callback-scheduler:prod" \
  --cli-binary-format raw-in-base64-out \
  --payload '{"Details":{"ContactData":{"ContactId":"cb-001","Attributes":{"topicCategory":"credit_card","callbackReason":"customer_request","conversationSummary":"Customer requested a callback","customerIntent":"replace damaged card","escalationReason":"out_of_hours"}}}}' \
  connect-lambda-platform-callback-response.json && cat connect-lambda-platform-callback-response.json
```

### 3.4 WebRTC API

Deploy `aria-webrtc-api` (roles: `aria-webrtc-api-exec-role`, `aria-webrtc-client-role`):

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
CONNECT_INSTANCE_ID="$CONNECT_INSTANCE_ID" \
CONNECT_CONTACT_FLOW_ID="$CONNECT_CONTACT_FLOW_ID" \
AWS_REGION="$AWS_REGION" \
ALLOWED_ORIGINS="${ALLOWED_ORIGINS:-*}" \
./scripts/deploy_webrtc_api.sh lambda
```

✓ Verify Lambda and Function URL:

```bash
aws lambda get-function \
  --function-name "aria-webrtc-api" \
  --query 'Configuration.[FunctionName,Runtime,Architectures,State,LastModified]' \
  --output table
aws lambda get-function-url-config \
  --function-name "aria-webrtc-api" \
  --query '[FunctionUrl,AuthType]' \
  --output table
```

Grant client-role Function URL permission (this is the script's actual access model; Connect does not invoke this Lambda directly):

```bash
CLIENT_ROLE_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:role/aria-webrtc-client-role"
aws lambda add-permission \
  --function-name "aria-webrtc-api" \
  --statement-id "AllowClientRoleInvoke" \
  --action lambda:InvokeFunctionUrl \
  --principal "$CLIENT_ROLE_ARN" \
  --function-url-auth-type AWS_IAM \
  --region "$AWS_REGION" 2>/dev/null || true
```

Test health endpoint:

```bash
WEBRTC_FUNCTION_URL=$(aws lambda get-function-url-config --function-name aria-webrtc-api --query 'FunctionUrl' --output text)
curl -s "${WEBRTC_FUNCTION_URL}health"
```

Test a signed `start-contact` request:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
export WEBRTC_FUNCTION_URL=$(aws lambda get-function-url-config --function-name aria-webrtc-api --query 'FunctionUrl' --output text)
python3 - <<'PY'
import json, os, urllib.request
import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

url = os.environ['WEBRTC_FUNCTION_URL'] + 'webrtc/start-contact'
payload = json.dumps({
    'display_name': 'Runbook WebRTC Test',
    'attributes': {'channel': 'webrtc', 'customerId': 'CUST-001'},
    'description': 'Connect Lambda Platform runbook smoke test'
}).encode('utf-8')
creds = boto3.Session().get_credentials().get_frozen_credentials()
request = AWSRequest(method='POST', url=url, data=payload, headers={'Content-Type': 'application/json'})
SigV4Auth(creds, 'lambda', os.environ.get('AWS_REGION', 'eu-west-2')).add_auth(request)
http_request = urllib.request.Request(url, data=payload, headers=dict(request.headers), method='POST')
with urllib.request.urlopen(http_request, timeout=30) as response:
    print(response.read().decode('utf-8'))
PY
```

### 3.5 Meeting ID capture

Deploy `aria-meeting-id-capture` (role: `aria-meeting-id-capture-role`):

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
./scripts/deploy_meeting_id_lambda.sh deploy --instance-id "$CONNECT_INSTANCE_ID"
```

✓ Verify:

```bash
aws lambda get-function \
  --function-name "aria-meeting-id-capture:prod" \
  --query 'Configuration.[FunctionName,Runtime,State,Timeout,LastModified]' \
  --output table
```

Grant Connect permission:

```bash
aws lambda add-permission \
  --function-name "aria-meeting-id-capture:prod" \
  --statement-id "ConnectInvokeMeetingIdCapture" \
  --action lambda:InvokeFunction \
  --principal connect.amazonaws.com \
  --source-account "$AWS_ACCOUNT_ID" \
  --source-arn "arn:aws:connect:${AWS_REGION}:${AWS_ACCOUNT_ID}:instance/${CONNECT_INSTANCE_ID}" \
  --region "$AWS_REGION" 2>/dev/null || true
```

Test invocation:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
aws lambda invoke \
  --function-name "aria-meeting-id-capture:prod" \
  --cli-binary-format raw-in-base64-out \
  --payload '{"Details":{"Parameters":{"storedCustomerInput":"123456"},"ContactData":{"ContactId":"mid-001"}}}' \
  connect-lambda-platform-meeting-id-response.json && cat connect-lambda-platform-meeting-id-response.json
```

### 3.6 Standalone Q in Connect session injector

Use this only when you need the separately named alias-managed function `aria-session-injector-qconnect`. `deploy_mcp_gateway.sh` already deploys the env-scoped variant `aria-banking-session-injector-${ENV}`.

Deploy (role: `aria-lambda-session-injector-qconnect-role`):

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
./scripts/deploy_session_injector_qconnect.sh \
  --assistant-id "$CONNECT_ASSISTANT_ID" \
  --region "$AWS_REGION" \
  --account-id "$AWS_ACCOUNT_ID" \
  --instance-id "$CONNECT_INSTANCE_ID"
```

Optional additions supported by the script:

```bash
--memory-table "${MEMORY_TABLE_NAME}" \
--crm-endpoint "${CRM_API_ENDPOINT}" \
--dry-run
```

✓ Verify:

```bash
aws lambda get-function \
  --function-name "aria-session-injector-qconnect:prod" \
  --query 'Configuration.[FunctionName,Runtime,State,Timeout,LastModified]' \
  --output table
aws lambda get-alias \
  --function-name "aria-session-injector-qconnect" \
  --name prod \
  --query '[Name,FunctionVersion,AliasArn]' \
  --output table
```

Grant Connect permission exactly as the script does:

```bash
aws lambda add-permission \
  --function-name "arn:aws:lambda:${AWS_REGION}:${AWS_ACCOUNT_ID}:function:aria-session-injector-qconnect:prod" \
  --statement-id "ConnectInvokeProduction" \
  --action lambda:InvokeFunction \
  --principal connect.amazonaws.com \
  --source-account "$AWS_ACCOUNT_ID" \
  --region "$AWS_REGION" 2>/dev/null || true

aws lambda add-permission \
  --function-name "aria-session-injector-qconnect" \
  --statement-id "ConnectInvoke" \
  --action lambda:InvokeFunction \
  --principal connect.amazonaws.com \
  --source-account "$AWS_ACCOUNT_ID" \
  --region "$AWS_REGION" 2>/dev/null || true
```

Test invocation:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
SESSION_INJECTOR_PAYLOAD=$(cat <<JSON
{"Details":{"ContactData":{"ContactId":"inj-001","Channel":"VOICE","InstanceARN":"arn:aws:connect:${AWS_REGION}:${AWS_ACCOUNT_ID}:instance/${CONNECT_INSTANCE_ID}","CustomerEndpoint":{"Address":"+447765309252","Type":"TELEPHONE_NUMBER"},"Attributes":{}},"Parameters":{}}}
JSON
)
aws lambda invoke \
  --function-name "aria-session-injector-qconnect:prod" \
  --cli-binary-format raw-in-base64-out \
  --payload "$SESSION_INJECTOR_PAYLOAD" \
  connect-lambda-platform-session-injector-response.json && cat connect-lambda-platform-session-injector-response.json
```

### 3.7 Fulfillment bridge (and note on `aria-session-injector`)

`aria-lex-fulfillment` and `aria-session-injector` are created inside the full-stack script, not by standalone deployment scripts.

Deploy command from the actual script:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
./scripts/deploy.sh deploy
```

✓ Verify the two master-script Lambdas:

```bash
for fn in aria-lex-fulfillment aria-session-injector; do
  aws lambda get-function \
    --function-name "$fn" \
    --query 'Configuration.[FunctionName,Runtime,State,LastModified]' \
    --output table
 done
```

Grant Lex permission for the fulfillment Lambda exactly as the script does:

```bash
aws lambda add-permission \
  --function-name "aria-lex-fulfillment" \
  --statement-id "LexV2Invoke" \
  --action lambda:InvokeFunction \
  --principal lexv2.amazonaws.com \
  --source-account "$AWS_ACCOUNT_ID" \
  --region "$AWS_REGION" 2>/dev/null || true
```

Grant Connect permission for the master-script session injector exactly as the script does:

```bash
aws lambda add-permission \
  --function-name "aria-session-injector" \
  --statement-id "ConnectInvoke" \
  --action lambda:InvokeFunction \
  --principal connect.amazonaws.com \
  --source-account "$AWS_ACCOUNT_ID" \
  --region "$AWS_REGION" 2>/dev/null || true
```

Test `aria-lex-fulfillment` with a realistic Lex V2 event:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
aws lambda invoke \
  --function-name "aria-lex-fulfillment" \
  --cli-binary-format raw-in-base64-out \
  --payload '{"sessionState":{"sessionAttributes":{"customerId":"CUST-001","authStatus":"authenticated","preferredName":"James","productSummary":"James has a current account ending 4821.","channel":"voice","locale":"en-GB"},"intent":{"name":"ARIAQuery","state":"InProgress"},"dialogAction":{"type":"Delegate"}},"inputTranscript":"What is my balance?","requestAttributes":{"ContactId":"lex-001"},"bot":{"id":"bot-id","aliasId":"alias-id"}}' \
  connect-lambda-platform-fulfillment-response.json && cat connect-lambda-platform-fulfillment-response.json
```

## 4. Verify all deployed Lambdas

Core/support Lambdas:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
for fn in \
  aria-routing-lookup \
  aria-callback-scheduler \
  aria-webrtc-api \
  aria-meeting-id-capture \
  aria-session-injector-qconnect \
  aria-lex-fulfillment \
  aria-session-injector \
  "aria-banking-session-injector-${ENV}" \
  "aria-banking-chat-to-voice-transfer-${ENV}" \
  "aria-banking-voice-to-chat-transfer-${ENV}"; do
  STATUS=$(aws lambda get-function --function-name "$fn" \
    --query 'Configuration.State' --output text 2>/dev/null || echo 'NOT FOUND')
  printf '%-45s %s\n' "$fn" "$STATUS"
 done
```

Gateway domain Lambdas (DTMF intentionally excluded here):

```bash
for domain in account auth customer escalation knowledge pii mortgage debit-card credit-card products; do
  fn="aria-banking-mcp-${domain}-${ENV}"
  STATUS=$(aws lambda get-function --function-name "$fn" \
    --query 'Configuration.State' --output text 2>/dev/null || echo 'NOT FOUND')
  printf '%-45s %s\n' "$fn" "$STATUS"
 done
```

Gateway resource:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
python3 - <<'PY'
import boto3, os
region = os.environ.get('AWS_REGION', 'eu-west-2')
env = os.environ.get('ENV', 'prod')
name = f'aria-banking-mcp-gateway-{env}'
client = boto3.client('bedrock-agentcore-control', region_name=region)
found = False
for page in client.get_paginator('list_gateways').paginate():
    for item in page.get('items', []):
        if item.get('name') == name:
            print(item)
            found = True
if not found:
    raise SystemExit(f'Gateway not found: {name}')
PY
```

## 5. Update a single Lambda without a full redeploy

For standalone Python-file Lambdas, package and update directly:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
mkdir -p .artifacts
FUNCTION_NAME="aria-routing-lookup"
SOURCE_FILE="scripts/lambdas/aria_routing_lookup.py"
ZIP_PATH=".artifacts/${FUNCTION_NAME}.zip"
(cd scripts/lambdas && zip -q "../../${ZIP_PATH}" "$(basename "$SOURCE_FILE")")
aws lambda update-function-code \
  --function-name "$FUNCTION_NAME" \
  --zip-file "fileb://${ZIP_PATH}" \
  --region "$AWS_REGION"
aws lambda wait function-updated \
  --function-name "$FUNCTION_NAME" \
  --region "$AWS_REGION"
rm -f "$ZIP_PATH"
```

Notes:

- For alias-managed Lambdas, rerun the original deploy script if you want a new published version and `prod` alias update.
- For `aria-webrtc-api`, rerun `./scripts/deploy_webrtc_api.sh lambda` because the package contains the full `api/webrtc` app.
- For MCP gateway Lambdas, use the script’s supported refresh path:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
./scripts/deploy_mcp_gateway.sh update-lambdas --env "$ENV" --region "$AWS_REGION"
```

## 6. Update `AGENTCORE_ENDPOINT` after ARIA redeploy

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
AGENTCORE_ENDPOINT=$(python3 -c "import json; s=json.load(open('scripts/.deploy-state.json')); print(s.get('agentcore_chat_url',''))")
aws lambda update-function-configuration \
  --function-name "aria-lex-fulfillment" \
  --environment "Variables={AGENTCORE_ENDPOINT=${AGENTCORE_ENDPOINT},AWS_REGION=${AWS_REGION},CONNECT_INSTANCE_ID=${CONNECT_INSTANCE_ID}}" \
  --region "$AWS_REGION"
aws lambda wait function-updated \
  --function-name "aria-lex-fulfillment" \
  --region "$AWS_REGION"
```

Re-run the fulfillment smoke test from section 3.7 immediately afterward.

## 7. View logs

```bash
aws logs tail /aws/lambda/aria-routing-lookup --follow
aws logs tail /aws/lambda/aria-callback-scheduler --follow
aws logs tail /aws/lambda/aria-webrtc-api --follow
aws logs tail /aws/lambda/aria-meeting-id-capture --follow
aws logs tail /aws/lambda/aria-session-injector-qconnect --follow
aws logs tail /aws/lambda/aria-lex-fulfillment --follow
aws logs tail "/aws/lambda/aria-banking-session-injector-${ENV}" --follow
aws logs tail "/aws/lambda/aria-banking-chat-to-voice-transfer-${ENV}" --follow
aws logs tail "/aws/lambda/aria-banking-voice-to-chat-transfer-${ENV}" --follow
```

## 8. Test channel transfers

### Chat to voice (`aria-banking-chat-to-voice-transfer-${ENV}`)

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
aws lambda invoke \
  --function-name "aria-banking-chat-to-voice-transfer-${ENV}" \
  --cli-binary-format raw-in-base64-out \
  --payload '{"Details":{"Parameters":{"contactId":"chat-123","customerId":"CUST-001","authStatus":"authenticated","locale":"en-GB","customerPhone":"+447765309252","agentId":"agent-456","transferMode":"aria"},"ContactData":{"ContactId":"chat-123"}}}' \
  connect-lambda-platform-chat-to-voice-response.json && cat connect-lambda-platform-chat-to-voice-response.json
```

### Voice to chat (`aria-banking-voice-to-chat-transfer-${ENV}`)

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
aws lambda invoke \
  --function-name "aria-banking-voice-to-chat-transfer-${ENV}" \
  --cli-binary-format raw-in-base64-out \
  --payload '{"Details":{"Parameters":{"contactId":"voice-123","customerId":"CUST-001","authStatus":"authenticated","locale":"en-GB","customerPhone":"+447765309252","agentId":"agent-456","transferMode":"aria"},"ContactData":{"ContactId":"voice-123"}}}' \
  connect-lambda-platform-voice-to-chat-response.json && cat connect-lambda-platform-voice-to-chat-response.json
```

## 9. Teardown individual functions

Scripted teardown paths:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
./scripts/deploy_meeting_id_lambda.sh teardown
./scripts/deploy_webrtc_api.sh teardown
./scripts/deploy_callback_lambda.sh teardown
./scripts/deploy_routing_lambda.sh teardown
./scripts/deploy_mcp_gateway.sh teardown --env "$ENV" --region "$AWS_REGION"
```

Manual teardown for `aria-session-injector-qconnect` (no script-supported teardown):

```bash
aws lambda delete-function --function-name "aria-session-injector-qconnect" --region "$AWS_REGION"
aws iam delete-role-policy --role-name "aria-lambda-session-injector-qconnect-role" --policy-name "SessionInjectorQConnectPolicy" 2>/dev/null || true
aws iam detach-role-policy --role-name "aria-lambda-session-injector-qconnect-role" --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" 2>/dev/null || true
aws iam delete-role --role-name "aria-lambda-session-injector-qconnect-role" 2>/dev/null || true
```

Manual teardown for a single master-script Lambda if full `deploy.sh teardown` is not desired:

```bash
aws lambda delete-function --function-name "aria-lex-fulfillment" --region "$AWS_REGION"
aws lambda delete-function --function-name "aria-session-injector" --region "$AWS_REGION"
```

## 10. Full platform teardown

Run in reverse order:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
# 1. Standalone Q in Connect injector (manual)
aws lambda delete-function --function-name "aria-session-injector-qconnect" --region "$AWS_REGION" 2>/dev/null || true

# 2. Meeting ID capture
./scripts/deploy_meeting_id_lambda.sh teardown

# 3. WebRTC API
./scripts/deploy_webrtc_api.sh teardown

# 4. Callback scheduler
./scripts/deploy_callback_lambda.sh teardown

# 5. Routing lookup
./scripts/deploy_routing_lambda.sh teardown

# 6. MCP gateway + env-scoped support/domain Lambdas
./scripts/deploy_mcp_gateway.sh teardown --env "$ENV" --region "$AWS_REGION"

# 7. Master-script fulfillment/session-injector and remaining AgentCore resources
./scripts/deploy.sh teardown
```

## 11. Troubleshooting

### Connect cannot invoke Lambda

```bash
aws lambda get-policy --function-name "aria-routing-lookup:prod" --region "$AWS_REGION"
aws lambda get-policy --function-name "aria-callback-scheduler:prod" --region "$AWS_REGION"
aws lambda get-policy --function-name "aria-meeting-id-capture:prod" --region "$AWS_REGION"
aws lambda get-policy --function-name "aria-session-injector-qconnect:prod" --region "$AWS_REGION"
```

If the policy is missing, re-run the matching `aws lambda add-permission` command from section 3.

### Session injector is not enriching attributes

- Confirm Amazon Q in Connect is enabled
- Ensure the Lambda is placed **after** the Connect assistant block
- Check that `ASSISTANT_ID` is set
- Verify the execution role includes `qconnect:UpdateSessionData` / `wisdom:UpdateSessionData`
- Review logs:

```bash
aws logs tail /aws/lambda/aria-session-injector-qconnect --since 30m --format short
aws logs tail "/aws/lambda/aria-banking-session-injector-${ENV}" --since 30m --format short
```

### Fulfillment Lambda returns 500 or repeated retry errors

- Re-read `AGENTCORE_ENDPOINT` from `scripts/.deploy-state.json`
- Update `aria-lex-fulfillment` using section 6
- Confirm the Lambda policy `AgentCoreInvoke` still matches the current runtime ARN
- Tail logs:

```bash
aws logs tail /aws/lambda/aria-lex-fulfillment --since 30m --format short
```

### WebRTC API requests fail or disconnect

- Confirm the Function URL exists and is `AWS_IAM`
- Confirm the client role trust policy no longer contains `REPLACE_WITH_IDENTITY_POOL_ID`
- Re-test the unsigned health endpoint and the signed `start-contact` request
- If browsers are blocked, review `ALLOWED_ORIGINS` and CORS settings

### Callback scheduling fails

- Confirm `aria-routing-config` exists:

```bash
aws dynamodb describe-table --table-name aria-routing-config --region "$AWS_REGION" --query 'Table.TableName' --output text
```

- Confirm callback queue placeholder values were replaced:

```bash
aws dynamodb scan --table-name aria-routing-config --region "$AWS_REGION" --projection-expression 'topicCategory,callbackQueueId,callbackQueueName'
```

- Re-run `./scripts/deploy_callback_lambda.sh update-queues` if placeholders remain

### Routing lookup returns the wrong queue

- Inspect the `aria-routing-config` row for the `topicCategory`
- Confirm `queueId`, `queueName`, `proficiencyLevel`, and `proficiencySkill` values are correct
- Re-test the Lambda directly with the payload from section 3.2

### Channel transfer fails

- Confirm `aria-transcript-store` exists
- Confirm the env-scoped support Lambdas were deployed by `deploy_mcp_gateway.sh`
- Verify `CONNECT_CONTACT_FLOW_ID`, `CONNECT_QUEUE_ID`, `SMS_ORIGINATION_NUMBER`, `SOURCE_PHONE_NUMBER`, and `CHAT_WIDGET_URL`
- Tail logs for the two transfer Lambdas and retry the tests from section 8
