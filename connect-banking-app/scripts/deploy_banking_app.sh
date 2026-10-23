#!/usr/bin/env bash
# =============================================================================
# deploy_banking_app.sh
# =============================================================================
# Deploys the internet banking app (Nationwide Building Society branded demo):
# one Lambda and an HTTP API serving the app and its API.
#
# YOU run this script. It makes these changes in your AWS account:
#   1. IAM role aria-banking-app-role: read and write the Money Hub table; start
#      chats and calls in the conversation bot flow and read their transcripts;
#      read the face's Tavus key and the mortgage and dispute Live Sync keys;
#      tell a contact and ARIA's session which page the customer moved to;
#      invoke the mortgage and dispute Lambdas
#   2. Lambda aria-banking-app (the app, and the Money Hub, mortgage and dispute
#      code it reuses, packaged from their folders unchanged)
#   3. HTTP API aria-banking-app-pages in front of it
#   4. SSM parameter /aria-banking-app/flow-view (only if it doesn't exist; never
#      overwritten): turns the demo's "how it works" view on or off at run time
#   5. Tests, and a demo link to James's internet banking. The app is the customer's
#      signed-in session, so the link is verified (Level 2): every page starts a
#      contact that arrives verified, with that page's context, and ARIA doesn't
#      ask the customer to prove who they are again.
#
# It changes no flow, AI agent, prompt or ACXD application, and none of the
# Money Hub, mortgage or dispute deployments: it only reads their settings.
# Safe to run again.
#
# Usage:
#   ./connect-banking-app/scripts/deploy_banking_app.sh [--region R] [--account-id A]
#        [--instance-id ID] [--contact-flow-id ID] [--assistant-id ID] [--unverified-demo] [--approve-origin]
#        [--flow-view on|off] [--dry-run]
#
#   --unverified-demo a demo link that is NOT verified, so ARIA checks who the
#                     customer is: for testing ARIA's own ID check only.
#                     (Anyone holding the usual, verified link is treated as
#                     James, signed in: it's sample data only.)
#   --approve-origin  also adds the app's address to the Connect instance's
#                     approved origins (needed for chat and calls; otherwise the
#                     script prints the command for you to run).
#   --flow-view       the "how it works" view's setting when it is first made
#                     (default on). An existing setting is never changed: turn
#                     it on or off at any time, without a redeploy, with
#                     aws ssm put-parameter --name /aria-banking-app/flow-view --value off --overwrite
#
# Requirements: AWS CLI v2.27+, python3, zip, curl; Node.js 18+ and npm (the
# call, face and Live Sync scripts: scripts/build_vendor.sh).
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
INSTANCE_ID="f969d4b4-f716-4974-a325-bb7899f2f293"
ASSISTANT_ID="${ASSISTANT_ID:-e6991ed4-e11c-4194-8d20-13889a36bd15}"   # Amazon Q in Connect assistant behind ARIA (call transcripts)
CONTACT_FLOW_ID="f6d6545f-c9ae-4ca4-a4d8-6fdc8ba0494f"      # conversation bot flow (its Point B passes mortgage calls on)
DRY_RUN=false
VERIFIED_DEMO=true        # the app stands for signed-in internet banking
APPROVE_ORIGIN=false
FLOW_VIEW_PARAMETER="/aria-banking-app/flow-view"           # "how it works", for demos (bankapp/flowview.py)
FLOW_VIEW_FIRST="on"

TABLE_NAME="aria-money-hub"                                 # the Money Hub's own table: one set of figures and goals
FUNCTION_NAME="aria-banking-app"
ROLE_NAME="aria-banking-app-role"
API_NAME="aria-banking-app-pages"
TAVUS_SECRET_NAME="aria-money-hub/tavus-api-key"            # made by connect-money-hub/scripts/deploy_money_hub.sh
MORTGAGE_STACK="mortgage-livesync-api"
DISPUTE_FUNCTION="aria-card-dispute"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP="${SCRIPT_DIR}/.."
ROOT="${APP}/.."

while [[ $# -gt 0 ]]; do
    case "$1" in
        --region)          REGION="$2"; shift 2 ;;
        --account-id)      ACCOUNT_ID="$2"; shift 2 ;;
        --instance-id)     INSTANCE_ID="$2"; shift 2 ;;
        --contact-flow-id) CONTACT_FLOW_ID="$2"; shift 2 ;;
        --assistant-id)    ASSISTANT_ID="$2"; shift 2 ;;
        --unverified-demo) VERIFIED_DEMO=false; shift ;;
        --verified-demo)   VERIFIED_DEMO=true; shift ;;      # the default; kept so older commands still work
        --approve-origin)  APPROVE_ORIGIN=true; shift ;;
        --flow-view)       [[ "${2:-}" == "on" || "${2:-}" == "off" ]] || die "--flow-view takes on or off."; FLOW_VIEW_FIRST="$2"; shift 2 ;;
        --dry-run)         DRY_RUN=true; shift ;;
        --help|-h)         sed -n '/^# Usage:/,/^# Requirements:/p' "$0" | sed -E 's/^# ?//'; exit 0 ;;
        *) die "Unknown argument: $1" ;;
    esac
done

for tool in aws zip python3 curl; do command -v "$tool" >/dev/null || die "${tool} not found on PATH."; done
for folder in connect-money-hub/moneyhub connect-money-hub/api connect-card-dispute/lambda; do
    [[ -d "$ROOT/$folder" ]] || die "Missing $folder: this app packages it from its own folder."
done
step "Checking AWS credentials..."
CALLER=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) || die "Sign in with the AWS CLI first."
[[ "$CALLER" == "$ACCOUNT_ID" ]] || die "Signed in to ${CALLER}, but the target is ${ACCOUNT_ID}. Use --account-id."
ok "Signed in to ${ACCOUNT_ID}"

if $DRY_RUN; then warn "DRY-RUN: no changes."; run() { echo "  [dry-run] $*" >&2; }; else run() { "$@"; }; fi
first_value() { tr -s '[:space:]' '\n' | grep -v -e '^None$' -e '^$' | head -n 1 || true; }
BUILD="$(mktemp -d)"; trap 'rm -rf "$BUILD"' EXIT
LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNCTION_NAME}"
INSTANCE_ARN="arn:aws:connect:${REGION}:${ACCOUNT_ID}:instance/${INSTANCE_ID}"

header "Step 0 - What the app reuses (read only)"
# The face: the Money Hub's Tavus key and settings (connect-money-hub/.env), read as data, never run.
env_value() { python3 - "$ROOT/connect-money-hub/.env" "$1" <<'PY'
import sys
from pathlib import Path
path, wanted = Path(sys.argv[1]), sys.argv[2]
for line in (path.read_text(encoding="utf-8").splitlines() if path.is_file() else []):
    key, sep, value = line.strip().partition("=")
    if sep and key.strip() == wanted:
        print(value.strip().strip('"').strip("'"))
        break
PY
}
TAVUS_FACE_ID=""; TAVUS_PAL_ID=""; TAVUS_SECRET_ID=""; TAVUS_SECRET_ARN=""
TAVUS_SECRET_ARN=$({ aws secretsmanager describe-secret --secret-id "$TAVUS_SECRET_NAME" --region "$REGION" --query ARN --output text 2>/dev/null || true; } | first_value)
if [[ -n "$TAVUS_SECRET_ARN" && -n "$(env_value TAVUS_FACE_ID)" && -n "$(env_value TAVUS_PAL_ID)" ]]; then
    TAVUS_FACE_ID="$(env_value TAVUS_FACE_ID)"; TAVUS_PAL_ID="$(env_value TAVUS_PAL_ID)"; TAVUS_SECRET_ID="$TAVUS_SECRET_NAME"
    ok "Face on calls: Tavus face ${TAVUS_FACE_ID} (key from the Money Hub's ${TAVUS_SECRET_NAME})."
else
    warn "Face off: run connect-money-hub/scripts/deploy_money_hub.sh with the Tavus settings first. Calls are voice only."
fi
# The mortgage service: its main Lambda (the IAM door), its Live Sync keys and their KMS key, its help number.
stack_value() {   # one output or parameter of the mortgage stack, or nothing
    { aws cloudformation describe-stacks --stack-name "$MORTGAGE_STACK" --region "$REGION" \
        --query "Stacks[0].$1[?$2=='$3'].$4" --output text 2>/dev/null || true; } | first_value
}
MORTGAGE_FUNCTION=$(stack_value Outputs OutputKey FunctionName OutputValue)
MORTGAGE_TP_SECRET=$(stack_value Outputs OutputKey TouchpointSecretName OutputValue)
MORTGAGE_KEY_ARN=$(stack_value Outputs OutputKey StateKeyArn OutputValue)
if [[ -n "$MORTGAGE_FUNCTION" && -n "$MORTGAGE_TP_SECRET" ]]; then
    HELP_PHONE=$(stack_value Parameters ParameterKey HelpPhoneNumber ParameterValue)
    MORTGAGE_TP_ARN=$({ aws secretsmanager describe-secret --secret-id "$MORTGAGE_TP_SECRET" --region "$REGION" --query ARN --output text 2>/dev/null || true; } | first_value)
    ok "Mortgage: ${MORTGAGE_FUNCTION}, Live Sync keys ${MORTGAGE_TP_SECRET}${HELP_PHONE:+, help number ${HELP_PHONE}}."
else
    warn "No ${MORTGAGE_STACK} stack: the mortgage form works by hand, without the assistant filling it or help codes."
    MORTGAGE_FUNCTION=""; MORTGAGE_TP_SECRET=""; MORTGAGE_KEY_ARN=""; MORTGAGE_TP_ARN=""; HELP_PHONE=""
fi
# The dispute service: its Lambda, its Live Sync keys and its pages' address (where its form links point).
read -r DISPUTE_TP_SECRET DISPUTE_PAGES_URL DISPUTE_TABLE < <(aws lambda get-function-configuration --function-name "$DISPUTE_FUNCTION" --region "$REGION" \
    --query "[Environment.Variables.TOUCHPOINT_SECRET_ID, Environment.Variables.PUBLIC_BASE_URL, Environment.Variables.DISPUTE_TABLE_NAME]" --output text 2>/dev/null || echo "None None None")
if [[ "${DISPUTE_TP_SECRET:-None}" != "None" ]]; then
    DISPUTE_TP_ARN=$({ aws secretsmanager describe-secret --secret-id "$DISPUTE_TP_SECRET" --region "$REGION" --query ARN --output text 2>/dev/null || true; } | first_value)
    [[ "$DISPUTE_PAGES_URL" != "None" ]] || DISPUTE_PAGES_URL=""
    [[ "$DISPUTE_TABLE" != "None" ]] || DISPUTE_TABLE=""
    ok "Disputes: ${DISPUTE_FUNCTION}, Live Sync keys ${DISPUTE_TP_SECRET}, table ${DISPUTE_TABLE:-?}, form links from ${DISPUTE_PAGES_URL:-?}."
else
    warn "No ${DISPUTE_FUNCTION} Lambda: dispute forms can't open in the app (ARIA and the dispute assistant still help)."
    DISPUTE_FUNCTION=""; DISPUTE_TP_SECRET=""; DISPUTE_TP_ARN=""; DISPUTE_PAGES_URL=""; DISPUTE_TABLE=""
fi

header "Step 1 - IAM role ${ROLE_NAME}"
if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
    run aws iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document \
        '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
    run aws iam attach-role-policy --role-name "$ROLE_NAME" \
        --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
    $DRY_RUN || sleep 12
fi
SECRETS=$(python3 -c 'import json,sys; print(json.dumps([a for a in sys.argv[1:] if a]))' "$TAVUS_SECRET_ARN" "${MORTGAGE_TP_ARN:-}" "${DISPUTE_TP_ARN:-}")
FUNCTIONS=$(python3 -c 'import json,sys; r,a=sys.argv[1],sys.argv[2]; print(json.dumps([f"arn:aws:lambda:{r}:{a}:function:{n}" for n in sys.argv[3:] if n]))' \
    "$REGION" "$ACCOUNT_ID" "$MORTGAGE_FUNCTION" "$DISPUTE_FUNCTION")
python3 - "$BUILD/policy.json" <<PY
import json, sys
statements = [
    {"Sid": "MoneyHubTable", "Effect": "Allow", "Action": ["dynamodb:GetItem", "dynamodb:PutItem"],
     "Resource": "arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${TABLE_NAME}"},
    {"Sid": "StartContactsFromTheApp", "Effect": "Allow", "Action": ["connect:StartWebRTCContact", "connect:StartChatContact"],
     "Resource": ["${INSTANCE_ARN}", "${INSTANCE_ARN}/contact-flow/${CONTACT_FLOW_ID}", "${INSTANCE_ARN}/contact/*"]},
    {"Sid": "ReadCallTranscripts", "Effect": "Allow", "Action": ["connect:DescribeContact", "connect:GetContactAttributes"],
     "Resource": "${INSTANCE_ARN}/contact/*"},
    {"Sid": "ReadCallTranscriptMessages", "Effect": "Allow", "Action": "wisdom:ListMessages",
     "Resource": "arn:aws:wisdom:${REGION}:${ACCOUNT_ID}:session/${ASSISTANT_ID}/*"},
    # Moving page during a conversation: where the customer is, on the contact and in ARIA's session (as the session
    # injector does at the start).
    {"Sid": "TellTheContactWhereTheCustomerIs", "Effect": "Allow", "Action": "connect:UpdateContactAttributes",
     "Resource": "${INSTANCE_ARN}/contact/*"},
    {"Sid": "TellAriaWhereTheCustomerIs", "Effect": "Allow",
     "Action": ["qconnect:UpdateSessionData", "wisdom:UpdateSessionData"],
     "Resource": ["arn:aws:wisdom:${REGION}:${ACCOUNT_ID}:assistant/${ASSISTANT_ID}",
                  "arn:aws:wisdom:${REGION}:${ACCOUNT_ID}:session/${ASSISTANT_ID}/*"]},
    {"Sid": "ReadTheFlowViewSetting", "Effect": "Allow", "Action": "ssm:GetParameter",
     "Resource": "arn:aws:ssm:${REGION}:${ACCOUNT_ID}:parameter${FLOW_VIEW_PARAMETER}"},
]
secrets, functions = json.loads('${SECRETS}'), json.loads('${FUNCTIONS}')
if secrets:
    statements.append({"Sid": "ReadTheFaceAndLiveSyncKeys", "Effect": "Allow", "Action": "secretsmanager:GetSecretValue", "Resource": secrets})
if "${MORTGAGE_KEY_ARN:-}":
    statements.append({"Sid": "DecryptTheMortgageLiveSyncKeys", "Effect": "Allow", "Action": "kms:Decrypt", "Resource": "${MORTGAGE_KEY_ARN:-}",
                       "Condition": {"StringEquals": {"kms:ViaService": "secretsmanager.${REGION}.amazonaws.com"}}})
if functions:
    statements.append({"Sid": "MortgageAndDisputeServices", "Effect": "Allow", "Action": "lambda:InvokeFunction", "Resource": functions})
if "${DISPUTE_TABLE:-}":
    # The customer's disputes, and opening a dispute's form joined to the app's own conversation (the dispute
    # service's own code on its own table: it makes a form link and opens it, as the texted link would).
    statements.append({"Sid": "DisputeTable", "Effect": "Allow", "Action": ["dynamodb:GetItem", "dynamodb:PutItem"],
                       "Resource": "arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${DISPUTE_TABLE:-}"})
open(sys.argv[1], "w").write(json.dumps({"Version": "2012-10-17", "Statement": statements}))
PY
run aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name BankingApp --policy-document "file://$BUILD/policy.json"
ok "Role ready."

header "Step 1b - The demo's \"how it works\" view: SSM parameter ${FLOW_VIEW_PARAMETER}"
FLOW_VIEW=$({ aws ssm get-parameter --name "$FLOW_VIEW_PARAMETER" --region "$REGION" --query Parameter.Value --output text 2>/dev/null || true; } | first_value)
if [[ -n "$FLOW_VIEW" ]]; then
    ok "Already set to '${FLOW_VIEW}': left as it is."
else
    run aws ssm put-parameter --name "$FLOW_VIEW_PARAMETER" --region "$REGION" --type String --value "$FLOW_VIEW_FIRST" \
        --description "Banking app demo: show the 'how it works' view (on or off). Read at run time; no redeploy." \
        --tags Key=app,Value=aria-banking-app >/dev/null
    FLOW_VIEW="$FLOW_VIEW_FIRST"
    ok "Created, set to '${FLOW_VIEW}'."
fi

header "Step 2 - Lambda ${FUNCTION_NAME}"
step "Building the call, face and Live Sync scripts..."
"$SCRIPT_DIR/build_vendor.sh" || die "Could not build the vendor scripts. Install Node.js 18+."
mkdir -p "$BUILD/pkg"
cp "$APP/api/banking_api.py" "$BUILD/pkg/"
cp -R "$APP/bankapp" "$BUILD/pkg/"
cp "$ROOT/connect-money-hub/api/money_api.py" "$BUILD/pkg/"          # unchanged: the Money Hub's own API code
cp -R "$ROOT/connect-money-hub/moneyhub" "$BUILD/pkg/"
for f in dispute_model.py dispute_service.py dispute_store.py; do                # unchanged: the dispute service's own code
    cp "$ROOT/connect-card-dispute/lambda/$f" "$BUILD/pkg/"
done
(cd "$APP" && find web -path web/vendor-src -prune -o -type f -print | while read -r f; do mkdir -p "$BUILD/pkg/$(dirname "$f")"; cp "$f" "$BUILD/pkg/$f"; done)
find "$BUILD/pkg" -name '__pycache__' -prune -exec rm -rf {} +
(cd "$BUILD/pkg" && zip -qr "$BUILD/app.zip" .)
write_env() { python3 - "$BUILD/env.json" "$1" <<PY
import json, sys
values = {"MONEY_HUB_TABLE": "${TABLE_NAME}", "CONNECT_INSTANCE_ID": "${INSTANCE_ID}", "CONTACT_FLOW_ID": "${CONTACT_FLOW_ID}",
          "QCONNECT_ASSISTANT_ID": "${ASSISTANT_ID}", "TAVUS_FACE_ID": "${TAVUS_FACE_ID}", "TAVUS_PAL_ID": "${TAVUS_PAL_ID}",
          "TAVUS_SECRET_ID": "${TAVUS_SECRET_ID}", "MORTGAGE_FUNCTION_NAME": "${MORTGAGE_FUNCTION}",
          "MORTGAGE_TOUCHPOINT_SECRET": "${MORTGAGE_TP_SECRET}", "HELP_PHONE_NUMBER": "${HELP_PHONE}",
          "DISPUTE_FUNCTION_NAME": "${DISPUTE_FUNCTION}", "DISPUTE_TOUCHPOINT_SECRET": "${DISPUTE_TP_SECRET}",
          "DISPUTE_PAGES_URL": "${DISPUTE_PAGES_URL}", "DISPUTE_TABLE_NAME": "${DISPUTE_TABLE}", "FLOW_VIEW_PARAMETER": "${FLOW_VIEW_PARAMETER}",
          "PUBLIC_BASE_URL": sys.argv[2]}
open(sys.argv[1], "w").write(json.dumps({"Variables": {k: v for k, v in values.items() if v}}))
PY
}
write_env ""
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" >/dev/null 2>&1; then
    run aws lambda update-function-code --function-name "$FUNCTION_NAME" --region "$REGION" \
        --zip-file "fileb://$BUILD/app.zip" --query FunctionName --output text >/dev/null
else
    run aws lambda create-function --function-name "$FUNCTION_NAME" --region "$REGION" --runtime python3.12 \
        --role "arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}" --handler banking_api.lambda_handler --timeout 15 \
        --memory-size 512 --zip-file "fileb://$BUILD/app.zip" --environment "file://$BUILD/env.json" \
        --query FunctionName --output text >/dev/null
fi
$DRY_RUN || aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
ok "Code deployed ($(du -h "$BUILD/app.zip" | cut -f1))."

header "Step 3 - HTTP API ${API_NAME}"
API_ID=$({ aws apigatewayv2 get-apis --region "$REGION" --query "Items[?Name=='${API_NAME}'].ApiId" --output text || true; } | first_value)
if [[ -z "$API_ID" ]]; then
    if $DRY_RUN; then API_ID="dryrunapi"; echo "  [dry-run] create-api ${API_NAME}"; else
        API_ID=$(aws apigatewayv2 create-api --name "$API_NAME" --protocol-type HTTP --target "$LAMBDA_ARN" \
            --region "$REGION" --query ApiId --output text); fi
fi
APP_URL="https://${API_ID}.execute-api.${REGION}.amazonaws.com"
run aws lambda add-permission --function-name "$FUNCTION_NAME" --region "$REGION" --statement-id PagesApiInvoke \
    --action lambda:InvokeFunction --principal apigateway.amazonaws.com \
    --source-arn "arn:aws:execute-api:${REGION}:${ACCOUNT_ID}:${API_ID}/*" >/dev/null 2>&1 || true
run aws apigatewayv2 update-stage --api-id "$API_ID" --stage-name '$default' --region "$REGION" \
    --default-route-settings "ThrottlingBurstLimit=60,ThrottlingRateLimit=30" >/dev/null
write_env "$APP_URL"
run aws lambda update-function-configuration --function-name "$FUNCTION_NAME" --region "$REGION" \
    --environment "file://$BUILD/env.json" --query FunctionName --output text >/dev/null
$DRY_RUN || aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
ok "The app is at ${APP_URL}/"
APPROVED=$({ aws connect list-approved-origins --instance-id "$INSTANCE_ID" --region "$REGION" --output text 2>/dev/null || true; } | tr '\t' '\n' | grep -cx "$APP_URL" || true)
if [[ "$APPROVED" == "0" ]]; then
    if $APPROVE_ORIGIN; then
        run aws connect associate-approved-origin --instance-id "$INSTANCE_ID" --region "$REGION" --origin "$APP_URL"
        ok "Added ${APP_URL} to the Connect instance's approved origins."
    else
        warn "Chat and calls need the app's address in the Connect instance's approved origins. Run:"
        echo "    aws connect associate-approved-origin --instance-id ${INSTANCE_ID} --region ${REGION} --origin ${APP_URL}"
    fi
else
    ok "The app's address is already an approved origin."
fi

header "Step 5 - Tests"
DEMO_LINK=""
if $DRY_RUN; then warn "Skipped in dry-run."; else
    code=""
    for _ in 1 2 3 4 5 6; do code=$(curl -s -o "$BUILD/page.html" -w '%{http_code}' "${APP_URL}/" || true)
        [[ "$code" == "200" ]] && break; sleep 3; done
    [[ "$code" == "200" ]] && grep -q "Nationwide" "$BUILD/page.html" || die "The app did not load (HTTP ${code})."
    ok "The app loads."
    code=$(curl -s -o /dev/null -w '%{http_code}' "${APP_URL}/vendor/touchpoint/index.js" || true)
    [[ "$code" == "200" ]] && ok "The Touchpoint SDK is served by the app." || warn "The Touchpoint SDK isn't served (HTTP ${code})."
    DEMO_LOA=""; ! $VERIFIED_DEMO || DEMO_LOA="2"
    echo "{\"operation\":\"mint_link\",\"customerId\":\"CUST-001\",\"loa\":\"${DEMO_LOA}\",\"neverExpires\":true}" > "$BUILD/mint.json"
    aws lambda invoke --function-name "$FUNCTION_NAME" --region "$REGION" --cli-binary-format raw-in-base64-out \
        --payload "file://$BUILD/mint.json" "$BUILD/link.json" >/dev/null
    DEMO_LINK=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("link",""))' "$BUILD/link.json")
    [[ "$DEMO_LINK" == https://* ]] || die "Could not make a demo link: $(cat "$BUILD/link.json")"
    ok "A demo link is ready (it never expires)."
fi

header "Done"
cat <<SUMMARY

  Internet banking : ${APP_URL}/
  Demo link (James, CUST-001, sample data; never expires; run again for another):
    ${DEMO_LINK:-run without --dry-run}
  Signed in (verified, Level 2): $($VERIFIED_DEMO && echo "yes: every page starts a verified contact with its context" || echo "no (--unverified-demo): ARIA will check who the customer is")
  Face on calls: $([[ -n "$TAVUS_SECRET_ID" ]] && echo "on (Tavus face ${TAVUS_FACE_ID})" || echo "off (voice only)")
  Mortgage form filled by its assistant: $([[ -n "$MORTGAGE_FUNCTION" ]] && echo "yes (Live Sync keys ${MORTGAGE_TP_SECRET})" || echo "no")
  Dispute form opens in the app: $([[ -n "$DISPUTE_FUNCTION" ]] && echo "yes (links from ${DISPUTE_PAGES_URL})" || echo "no")
  "How it works" view (demos): ${FLOW_VIEW:-on}. Switch it, no redeploy (shows within 30 seconds; reload the page):
    aws ssm put-parameter --name ${FLOW_VIEW_PARAMETER} --region ${REGION} --overwrite --value off   # or on

  If the mortgage or dispute ACXD application limits which websites may use its Live Sync keys,
  add ${APP_URL} there too (agentic CX designer, the application's Touchpoint settings).
SUMMARY
