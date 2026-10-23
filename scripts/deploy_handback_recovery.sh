#!/usr/bin/env bash
# =============================================================================
# deploy_handback_recovery.sh
# =============================================================================
# Deploys aria-handback-recovery (scripts/lambdas/handback_recovery.py): on a CHAT,
# Amazon Connect loses ARIA's hand-back while she has a collaborator (Get customer
# input fails with a NullPointerException), so the flow never transfers. This
# Lambda reads her decision back from her trace and tells the flow where to go.
#
# DRY RUN BY DEFAULT: it shows what it would do. Add --apply to do it.
#
# With --apply it:
#   1. creates (or updates) the IAM role aria-handback-recovery-role:
#      logs, wisdom:ListSpans on ARIA's assistant, connect:UpdateContactAttributes
#      and connect:DescribeContact on the Connect instance
#   2. creates (or updates the code of) the Lambda aria-handback-recovery
#   3. lets the Connect instance invoke it, and adds it to the instance's
#      Lambda list so the flow designer offers it
#
# Then add it to conversation bot flow (see the steps this script prints).
#
# Usage:  ./scripts/deploy_handback_recovery.sh [--apply] [--region R]
# =============================================================================
set -euo pipefail

REGION="${AWS_REGION:-eu-west-2}"
# Override all three for another account or instance (deploy-fresh-instance sets them).
ACCOUNT_ID="${AWS_ACCOUNT_ID:-395402194296}"
INSTANCE_ID="${INSTANCE_ID:-f969d4b4-f716-4974-a325-bb7899f2f293}"
ASSISTANT_ID="${ASSISTANT_ID:-e6991ed4-e11c-4194-8d20-13889a36bd15}"
FUNCTION="aria-handback-recovery"
ROLE="aria-handback-recovery-role"
APPLY=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --apply)  APPLY=true; shift ;;
        --region) REGION="$2"; shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$(mktemp -d)"; trap 'rm -rf "$BUILD"' EXIT
INSTANCE_ARN="arn:aws:connect:${REGION}:${ACCOUNT_ID}:instance/${INSTANCE_ID}"
say() { echo "  $*"; }
run() { if $APPLY; then "$@"; else echo "  [would run] $*" | cut -c1-160; fi; }

CALLER=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) || { echo "Sign in with the AWS CLI first." >&2; exit 1; }
[[ "$CALLER" == "$ACCOUNT_ID" ]] || { echo "Signed in to ${CALLER}, but the target is ${ACCOUNT_ID}." >&2; exit 1; }
$APPLY || echo "DRY RUN: nothing will change. Add --apply to do it."

# ── 1. Role ──────────────────────────────────────────────────────────────────
echo "== 1. IAM role ${ROLE}"
cat > "$BUILD/trust.json" <<JSON
{"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"},
  "Action": "sts:AssumeRole"}]}
JSON
cat > "$BUILD/policy.json" <<JSON
{"Version": "2012-10-17", "Statement": [
  {"Sid": "Logs", "Effect": "Allow", "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
   "Resource": "arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:/aws/lambda/${FUNCTION}:*"},
  {"Sid": "ReadAriasTrace", "Effect": "Allow", "Action": ["wisdom:ListSpans"],
   "Resource": ["arn:aws:wisdom:${REGION}:${ACCOUNT_ID}:assistant/${ASSISTANT_ID}",
                "arn:aws:wisdom:${REGION}:${ACCOUNT_ID}:session/${ASSISTANT_ID}/*"]},
  {"Sid": "SetTheHandOverAttributes", "Effect": "Allow",
   "Action": ["connect:UpdateContactAttributes", "connect:DescribeContact"],
   "Resource": ["${INSTANCE_ARN}", "${INSTANCE_ARN}/contact/*"]}
]}
JSON
if aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
    say "Role exists; its policy is set to the one above."
else
    run aws iam create-role --role-name "$ROLE" --assume-role-policy-document "file://$BUILD/trust.json" --output text --query Role.Arn
    $APPLY && sleep 10                                   # a new role takes a moment before Lambda can use it
fi
run aws iam put-role-policy --role-name "$ROLE" --policy-name handback-recovery --policy-document "file://$BUILD/policy.json"

# ── 2. Function ──────────────────────────────────────────────────────────────
echo "== 2. Lambda ${FUNCTION}"
cp "$ROOT/scripts/lambdas/handback_recovery.py" "$BUILD/"
(cd "$BUILD" && zip -q fn.zip handback_recovery.py)
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE}"
if aws lambda get-function --function-name "$FUNCTION" --region "$REGION" >/dev/null 2>&1; then
    run aws lambda update-function-code --function-name "$FUNCTION" --region "$REGION" --zip-file "fileb://$BUILD/fn.zip" \
        --query LastModified --output text
else
    run aws lambda create-function --function-name "$FUNCTION" --region "$REGION" --runtime python3.12 \
        --handler handback_recovery.lambda_handler --role "$ROLE_ARN" --timeout 8 --memory-size 256 \
        --environment "Variables={WAIT_SECONDS=5,MAX_AGE_SECONDS=90}" \
        --zip-file "fileb://$BUILD/fn.zip" --query FunctionArn --output text
fi
FUNCTION_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNCTION}"

# ── 3. Let Connect call it ───────────────────────────────────────────────────
echo "== 3. Connect may invoke it"
if $APPLY; then aws lambda wait function-active-v2 --function-name "$FUNCTION" --region "$REGION"; fi
if aws lambda get-policy --function-name "$FUNCTION" --region "$REGION" 2>/dev/null | grep -q connect-invoke; then
    say "Permission already there."
else
    run aws lambda add-permission --function-name "$FUNCTION" --region "$REGION" --statement-id connect-invoke \
        --action lambda:InvokeFunction --principal connect.amazonaws.com --source-account "$ACCOUNT_ID" \
        --source-arn "$INSTANCE_ARN" --output text --query Statement
fi
run aws connect associate-lambda-function --instance-id "$INSTANCE_ID" --region "$REGION" --function-arn "$FUNCTION_ARN"

cat <<NEXT

Next, in conversation bot flow (docs: connect-money-hub/docs/collaborator-setup.md,
"When Connect loses a chat hand-back"):
  Get customer input (ARIA) → Error  →  Invoke AWS Lambda function: ${FUNCTION}
  then Check contact attributes on External / route:
    card_dispute → the existing Transfer to flow "Card dispute assistant"
    escalate     → the existing Transfer to flow for escalations
    end          → Disconnect
    No match / Error → the Loop block Error used to go to
NEXT
