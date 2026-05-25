# Connect Analytics Agent Runbook

This runbook covers local operation, cloud deployment, validation, update, and teardown for `connect-analytics-agent` using the exact resource naming patterns defined in `connect-analytics-agent/deploy.sh`.

## 1. Pre-deployment checklist

Run from the repository root unless noted otherwise.

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/connect-analytics-agent
command -v aws
command -v jq
command -v zip
command -v python3
command -v pip3
command -v npm
aws sts get-caller-identity
```

Verify core environment variables:

```bash
export AWS_REGION="us-east-1"
export CONNECT_INSTANCE_ID="<your-connect-instance-id>"
export STACK_SUFFIX="prod"
export BEDROCK_MODEL_ID="us.anthropic.claude-sonnet-4-5"

printf 'AWS_REGION=%s\nCONNECT_INSTANCE_ID=%s\nSTACK_SUFFIX=%s\nBEDROCK_MODEL_ID=%s\n' \
  "$AWS_REGION" "$CONNECT_INSTANCE_ID" "$STACK_SUFFIX" "$BEDROCK_MODEL_ID"
```

Recommended checks:

```bash
aws connect list-instances --query "InstanceSummaryList[?Id=='${CONNECT_INSTANCE_ID}']" --output table
aws bedrock list-foundation-models --region "$AWS_REGION" --by-provider anthropic --output table
```

## 2. Local Docker deployment

Start local mode:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/connect-analytics-agent
./deploy.sh local
```

Notes:
- `./deploy.sh local` launches the local Docker stack from `docker/docker-compose.yml`
- Default mode is `MOCK_MODE=true`
- The script saves local selections into `.deploy-state.json`
- Frontend: `http://localhost:5274`
- Agent API: `http://localhost:8100`

Rebuild containers without prompts:

```bash
./deploy.sh update
```

Stop local mode:

```bash
./deploy.sh local-stop
```

## 3. Cloud deployment

Export the deployment variables exactly as expected by `deploy.sh`:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/connect-analytics-agent
export CONNECT_INSTANCE_ID="<your-connect-instance-id>"
export AWS_REGION="us-east-1"
export STACK_SUFFIX="prod"
export BEDROCK_MODEL_ID="us.anthropic.claude-sonnet-4-5"
./deploy.sh deploy
```

What `./deploy.sh deploy` creates:
- IAM roles × 3
  - `connect-analytics-lambda-tools-role`
  - `connect-analytics-agent-role`
  - `connect-analytics-gateway-role`
- Lambda tools × 9
  - `connect-analytics-realtime-metrics-${STACK_SUFFIX}`
  - `connect-analytics-historical-metrics-${STACK_SUFFIX}`
  - `connect-analytics-agent-states-${STACK_SUFFIX}`
  - `connect-analytics-search-contacts-${STACK_SUFFIX}`
  - `connect-analytics-contact-detail-${STACK_SUFFIX}`
  - `connect-analytics-transcript-${STACK_SUFFIX}`
  - `connect-analytics-keyword-search-${STACK_SUFFIX}`
  - `connect-analytics-recording-url-${STACK_SUFFIX}`
  - `connect-analytics-contact-flow-events-${STACK_SUFFIX}`
- AgentCore Gateway: `connect-analytics-gateway-${STACK_SUFFIX}`
- Agent Lambda: `connect-analytics-agent-${STACK_SUFFIX}`
- API Gateway: `connect-analytics-api-${STACK_SUFFIX}`
- Cognito user pool: `connect-analytics-users-${STACK_SUFFIX}`
- Cognito app client: `connect-analytics-frontend-${STACK_SUFFIX}`
- S3 website bucket: `connect-analytics-frontend-${STACK_SUFFIX}`
- CloudFront distribution for the React dashboard

Expected duration: 10-20 minutes.

## 4. EventBridge setup (optional)

Create the EventBridge rule and SQS queue:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/connect-analytics-agent
export CONNECT_INSTANCE_ID="${CONNECT_INSTANCE_ID}"
./deploy.sh setup-eventbridge
```

Verify the queue recorded in the deploy state file:

```bash
QUEUE_URL=$(jq -r '.bot_events_queue_url' .deploy-state.json)
echo "$QUEUE_URL"
aws sqs get-queue-attributes \
  --queue-url "$QUEUE_URL" \
  --attribute-names QueueArn ApproximateNumberOfMessages \
  --output table
```

Expected queue name pattern: `connect-analytics-bot-contact-events`.

## 5. Verify all 9 Lambda tools

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/connect-analytics-agent
for tool in \
  realtime-metrics historical-metrics agent-states search-contacts \
  contact-detail transcript keyword-search recording-url contact-flow-events
  do
    aws lambda get-function \
      --function-name "connect-analytics-${tool}-${STACK_SUFFIX}" \
      --query 'Configuration.[FunctionName,Runtime,State,LastModified]' \
      --output table
  done
```

## 6. Test individual Lambda tools

### Realtime metrics tool

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/connect-analytics-agent
aws lambda invoke \
  --function-name "connect-analytics-realtime-metrics-${STACK_SUFFIX}" \
  --cli-binary-format raw-in-base64-out \
  --payload "$(jq -cn --arg instance "$CONNECT_INSTANCE_ID" '{actionGroup:"ConnectAnalyticsTools",function:"get_realtime_metrics",parameters:[{name:"instance_id",type:"string",value:$instance}]}')" \
  realtime-metrics-response.json && cat realtime-metrics-response.json
```

### Search contacts tool

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/connect-analytics-agent
aws lambda invoke \
  --function-name "connect-analytics-search-contacts-${STACK_SUFFIX}" \
  --cli-binary-format raw-in-base64-out \
  --payload "$(jq -cn \
    --arg instance "$CONNECT_INSTANCE_ID" \
    --arg start "2026-05-25T00:00:00Z" \
    --arg end "2026-05-25T23:59:59Z" \
    '{actionGroup:"ConnectAnalyticsTools",function:"search_contacts",parameters:[{name:"instance_id",type:"string",value:$instance},{name:"start_time",type:"string",value:$start},{name:"end_time",type:"string",value:$end},{name:"max_results",type:"string",value:"10"}]}')" \
  search-contacts-response.json && cat search-contacts-response.json
```

## 7. Test the agent Lambda

Invoke the deployed agent Lambda with the query `How many agents are available?`:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/connect-analytics-agent
REQUEST_BODY=$(jq -cn '{message:"How many agents are available?"}')
LAMBDA_EVENT=$(jq -cn --arg body "$REQUEST_BODY" '{httpMethod:"POST",path:"/api/query",body:$body}')
aws lambda invoke \
  --function-name "connect-analytics-agent-${STACK_SUFFIX}" \
  --cli-binary-format raw-in-base64-out \
  --payload "$LAMBDA_EVENT" \
  agent-response.json && cat agent-response.json
```

## 8. Verify the React dashboard

Get the CloudFront URL from the deploy state file and verify reachability:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/connect-analytics-agent
CLOUDFRONT_URL=$(jq -r '.cloudfront_url' .deploy-state.json)
echo "$CLOUDFRONT_URL"
curl -I "$CLOUDFRONT_URL"
```

Open the URL in a browser after `curl` returns `200`, `301`, or `302`.

## 9. Update a single Lambda tool

Example: rebuild and update only `search-contacts` without a full redeploy.

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/connect-analytics-agent
TOOL_KEY="search-contacts"
TOOL_DIR="search_contacts"
rm -rf ".build/${TOOL_KEY}"
mkdir -p ".build/${TOOL_KEY}/package/shared"
python3 -m pip install --quiet -r "tools/${TOOL_DIR}/requirements.txt" -t ".build/${TOOL_KEY}/package"
cp "tools/${TOOL_DIR}/handler.py" ".build/${TOOL_KEY}/package/handler.py"
cp "tools/shared/connect_utils.py" ".build/${TOOL_KEY}/package/shared/connect_utils.py"
(cd ".build/${TOOL_KEY}/package" && zip -qr "../${TOOL_KEY}.zip" .)
aws lambda update-function-code \
  --function-name "connect-analytics-${TOOL_KEY}-${STACK_SUFFIX}" \
  --zip-file "fileb://.build/${TOOL_KEY}/${TOOL_KEY}.zip"
aws lambda wait function-active-v2 --function-name "connect-analytics-${TOOL_KEY}-${STACK_SUFFIX}"
```

If a tool schema changed, do not stop here; rerun `./deploy.sh deploy` so the gateway registration step re-applies the schema.

## 10. Smoke tests

Query the deployed API:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/connect-analytics-agent
API_URL=$(jq -r '.api_gateway_url' .deploy-state.json)
curl -s "$API_URL/health" | jq .
curl -s "$API_URL/metrics" | jq .
curl -s -X POST "$API_URL/query" \
  -H 'Content-Type: application/json' \
  -d '{"message":"How many agents are available?"}' | jq .
```

Check for HTTP 200 responses:

```bash
curl -s -o /dev/null -w '%{http_code}\n' "$API_URL/health"
curl -s -o /dev/null -w '%{http_code}\n' "$API_URL/metrics"
```

Review CloudWatch logs for errors:

```bash
aws logs tail "/aws/lambda/connect-analytics-agent-${STACK_SUFFIX}" --since 15m --format short
aws logs tail "/aws/lambda/connect-analytics-realtime-metrics-${STACK_SUFFIX}" --since 15m --format short
```

## 11. EventBridge teardown

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/connect-analytics-agent
./deploy.sh teardown-eventbridge
```

This removes the `connect-analytics-bot-contact-events` EventBridge target/rule and deletes the SQS queue.

## 12. Full teardown

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/connect-analytics-agent
export CONNECT_INSTANCE_ID="<your-connect-instance-id>"
export AWS_REGION="us-east-1"
export STACK_SUFFIX="prod"
./deploy.sh teardown
```

`./deploy.sh teardown` removes:
- CloudFront distribution
- S3 frontend bucket and objects
- Cognito user pool and app client
- API Gateway
- `connect-analytics-agent-${STACK_SUFFIX}`
- AgentCore Gateway
- All 9 tool Lambdas
- Managed IAM policies and IAM roles
- EventBridge rule and SQS queue when present in state
- CloudWatch log groups for the agent and tool Lambdas
- `.deploy-state.json`

## 13. Troubleshooting

### Tool returns empty data
- Symptom: Lambda returns success but no queue/contact/transcript data.
- Checks:

```bash
aws logs tail "/aws/lambda/connect-analytics-search-contacts-${STACK_SUFFIX}" --since 15m --format short
aws connect list-instances --query "InstanceSummaryList[?Id=='${CONNECT_INSTANCE_ID}']" --output table
```

- Likely causes: wrong `CONNECT_INSTANCE_ID`, missing Connect permissions, Contact Lens not enabled, or no data in the requested window.

### Agent Lambda timeout
- Symptom: API query hangs or Lambda times out.
- Checks:

```bash
aws logs tail "/aws/lambda/connect-analytics-agent-${STACK_SUFFIX}" --since 15m --format short
aws lambda get-function-configuration --function-name "connect-analytics-agent-${STACK_SUFFIX}" --query '[Timeout,MemorySize,Environment.Variables.AGENTCORE_GATEWAY_ENDPOINT]' --output table
```

- Response: confirm tool Lambda health, reduce query scope, and verify Gateway/direct fallback configuration.

### Gateway registration error
- Symptom: deploy warns and switches to direct mode.
- Checks:

```bash
jq -r '.agentcore_mode,.agentcore_gateway_endpoint' .deploy-state.json
aws bedrock-agentcore-control help
```

- Response: if AgentCore commands are unavailable, operate in direct mode and redeploy later with a compatible AWS CLI.

### Frontend CORS error
- Symptom: browser can load CloudFront but API calls fail.
- Checks:

```bash
API_URL=$(jq -r '.api_gateway_url' .deploy-state.json)
curl -i "$API_URL/health"
```

- Response: verify API Gateway deployment, CloudFront cache state, and allowed frontend origin settings.

### `search-contacts` pagination
- Symptom: first page succeeds but full result set is incomplete.
- Checks:

```bash
cat search-contacts-response.json
```

- Response: inspect `next_token` in the tool response and re-invoke with the returned token until it is empty.
