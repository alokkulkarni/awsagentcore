#!/usr/bin/env bash
# =============================================================================
# keep_bridge_warm.sh
# =============================================================================
# Keeps the Money Hub A2A bridge Lambda warm, so the first hand-off from ARIA in
# a call doesn't wait for a cold start (19 Oct: 0.39 s to start the Lambda, plus
# creating its AWS clients and reading the API key on that first request).
#
# YOU run this script. It creates, in your AWS account, only what's missing:
#   1. IAM role aria-money-hub-bridge-warmer: trusted by EventBridge Scheduler in
#      this account only, allowed to invoke the bridge Lambda and nothing else
#   2. EventBridge Scheduler schedule aria-money-hub-bridge-warm: every 5 minutes,
#      invokes the bridge with {"warm": true}. The bridge answers that at once:
#      it readies its clients and key and never touches a session (a2a_bridge.py)
#
# It never changes anything that already exists: a role or schedule with these
# names is left as it is. Cost: about 8,600 tiny invocations a month.
#
# Why not provisioned concurrency: it needs a Lambda alias, and the alias gets a
# different Function URL, so Connect's A2A application would have to be changed
# too. A schedule needs no change anywhere else.
#
# Usage:
#   ./connect-money-hub/scripts/keep_bridge_warm.sh            # dry run
#   ./connect-money-hub/scripts/keep_bridge_warm.sh --apply
#   ./connect-money-hub/scripts/keep_bridge_warm.sh --remove --apply   # deletes the schedule and the role
# Requirements: AWS CLI v2.
# =============================================================================
set -euo pipefail

REGION="${AWS_REGION:-eu-west-2}"
ACCOUNT_ID="395402194296"
FUNCTION_NAME="aria-money-hub-bridge"
ROLE_NAME="aria-money-hub-bridge-warmer"
SCHEDULE_NAME="aria-money-hub-bridge-warm"
RATE="rate(5 minutes)"
APPLY=false; REMOVE=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --apply)  APPLY=true; shift ;;
        --remove) REMOVE=true; shift ;;
        --region) REGION="$2"; shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done
die() { echo "STOPPED: $*" >&2; exit 1; }
CALLER=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) || die "sign in with the AWS CLI first."
[[ "$CALLER" == "$ACCOUNT_ID" ]] || die "signed in to ${CALLER}, but the target is ${ACCOUNT_ID}."
$APPLY || echo "DRY RUN: nothing will change. Add --apply to do it."
run() { if $APPLY; then "$@"; else echo "  [would run] $*" | cut -c1-180; fi; }

FUNCTION_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNCTION_NAME}"
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" >/dev/null 2>&1 \
    || die "the bridge Lambda ${FUNCTION_NAME} isn't in ${REGION}. Run deploy_bridge.sh first."
role_exists()     { aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; }
schedule_exists() { aws scheduler get-schedule --name "$SCHEDULE_NAME" --region "$REGION" >/dev/null 2>&1; }

if $REMOVE; then
    echo "== Removing the keep-warm schedule and its role (nothing else)"
    schedule_exists && run aws scheduler delete-schedule --name "$SCHEDULE_NAME" --region "$REGION" \
        || echo "  no schedule ${SCHEDULE_NAME}"
    if role_exists; then
        run aws iam delete-role-policy --role-name "$ROLE_NAME" --policy-name invoke-bridge
        run aws iam delete-role --role-name "$ROLE_NAME"
    else
        echo "  no role ${ROLE_NAME}"
    fi
    exit 0
fi

# ── 1. Role ──────────────────────────────────────────────────────────────────
echo "== 1. Role ${ROLE_NAME}"
if role_exists; then
    echo "  exists: used as it is"
else
    TRUST=$(cat <<JSON
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"scheduler.amazonaws.com"},
 "Action":"sts:AssumeRole","Condition":{"StringEquals":{"aws:SourceAccount":"${ACCOUNT_ID}"}}}]}
JSON
)
    POLICY=$(cat <<JSON
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"lambda:InvokeFunction","Resource":"${FUNCTION_ARN}"}]}
JSON
)
    run aws iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document "$TRUST" \
        --description "EventBridge Scheduler: keep the Money Hub A2A bridge warm" \
        --tags Key=project,Value=connect-money-hub
    run aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name invoke-bridge --policy-document "$POLICY"
    $APPLY && { echo "  waiting 10 s for the new role to reach Scheduler"; sleep 10; }
fi

# ── 2. Schedule ──────────────────────────────────────────────────────────────
echo "== 2. Schedule ${SCHEDULE_NAME} (${RATE})"
if schedule_exists; then
    echo "  exists: used as it is"
else
    TARGET=$(cat <<JSON
{"Arn":"${FUNCTION_ARN}","RoleArn":"${ROLE_ARN}","Input":"{\"warm\": true}","RetryPolicy":{"MaximumRetryAttempts":0}}
JSON
)
    run aws scheduler create-schedule --name "$SCHEDULE_NAME" --region "$REGION" \
        --schedule-expression "$RATE" --flexible-time-window Mode=OFF --state ENABLED \
        --description "Keeps the Money Hub A2A bridge warm (connect-money-hub/scripts/keep_bridge_warm.sh)" \
        --target "$TARGET"
fi

cat <<NEXT

Check it in a few minutes: the bridge's log shows an invocation every 5 minutes, each a few milliseconds.
  aws logs tail /aws/lambda/${FUNCTION_NAME} --since 15m --region ${REGION} | grep REPORT
NEXT
