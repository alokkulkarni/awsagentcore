#!/usr/bin/env bash
# =============================================================================
# enable_ai_agent_logging.sh
# =============================================================================
# Sends the Connect assistant's AI agent event logs (each turn's model input and
# output, tool calls and their results, hand-offs) to CloudWatch Logs, as AWS
# describes in "Monitor AI agents using CloudWatch". Today nothing is delivered,
# so the only record of what ARIA did is her traces (qconnect ListSpans).
#
# It covers every AI agent in the assistant (ARIA v2, the live ARIA, the Money Hub
# hand-offs, agent assist). It only ADDS logging; it changes no agent or flow.
#
# Safe by design: it creates only what's missing, and never replaces anything.
#   log group        /aws/vendedlogs/connect/ai-agents/<assistant id>   (new: retention 30 days, tagged)
#   delivery source  aria-assistant-event-logs       (logType EVENT_LOGS, the assistant; tagged)
#   destination      aria-assistant-event-logs-cwl   (that log group, JSON; tagged)
#   delivery         source → destination
# - An existing log group is used as it is (its retention isn't changed).
# - An existing source or destination is reused only if it's the same thing (same
#   assistant and log type; same log group). If a name is taken by something else, it
#   stops. If the assistant already has an EVENT_LOGS source under another name, it says
#   so and stops: logging is already on.
# - DRY RUN unless --apply.
#
# Usage:  ./ai-agent/enable_ai_agent_logging.sh [--apply] [--retention-days N] [--region R]
# =============================================================================
set -euo pipefail

REGION="${AWS_REGION:-eu-west-2}"
ACCOUNT_ID="395402194296"
ASSISTANT_ID="e6991ed4-e11c-4194-8d20-13889a36bd15"
RETENTION=30
TAG="project=connect-bot-flow-modular"
APPLY=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --apply)          APPLY=true; shift ;;
        --retention-days) RETENTION="$2"; shift 2 ;;
        --region)         REGION="$2"; shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done
die() { echo "STOPPED: $*" >&2; exit 1; }
CALLER=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) || die "sign in with the AWS CLI first."
[[ "$CALLER" == "$ACCOUNT_ID" ]] || die "signed in to ${CALLER}, but the target is ${ACCOUNT_ID}."
$APPLY || echo "DRY RUN: nothing will change. Add --apply to do it."
run() { if $APPLY; then "$@"; else echo "  [would run] $*" | cut -c1-170; fi; }
L() { aws logs "$@" --region "$REGION"; }
# Look-ups use --output json: with --output text the CLI applies --query to each page
# separately, so "| [0]" on a 3-page answer prints "None" three times. JSON applies it
# to the whole answer. jtext prints the result as text ("" for null or an empty list).
jtext() { python3 -c 'import json,sys
v = json.load(sys.stdin)
print("" if v is None else "\t".join(map(str, v)) if isinstance(v, list) else v)'; }

ASSISTANT_ARN="arn:aws:wisdom:${REGION}:${ACCOUNT_ID}:assistant/${ASSISTANT_ID}"
LOG_GROUP="/aws/vendedlogs/connect/ai-agents/${ASSISTANT_ID}"
LOG_GROUP_ARN="arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:${LOG_GROUP}"   # as AWS's CLI example
SOURCE="aria-assistant-event-logs"
DESTINATION="aria-assistant-event-logs-cwl"
DEST_ARN="arn:aws:logs:${REGION}:${ACCOUNT_ID}:delivery-destination:${DESTINATION}"

# ── 0. Checks (read only) ────────────────────────────────────────────────────
echo "== 0. Checks"
OTHER=$(L describe-delivery-sources --query "deliverySources[?logType=='EVENT_LOGS' && contains(resourceArns, '${ASSISTANT_ARN}') && name!='${SOURCE}'].name" --output json | jtext)
[[ -z "$OTHER" ]] || die "the assistant already sends EVENT_LOGS through delivery source '${OTHER}'. Logging is on; nothing to do."
SRC_NOW=$(L describe-delivery-sources --query "deliverySources[?name=='${SOURCE}'] | [0].[logType, resourceArns[0]]" --output json | jtext)
if [[ -n "$SRC_NOW" ]]; then
    [[ "$SRC_NOW" == "EVENT_LOGS"$'\t'"${ASSISTANT_ARN}" ]] || die "a delivery source named ${SOURCE} exists for something else (${SRC_NOW}). Not replacing it."
    SOURCE_EXISTS=true; echo "  delivery source ${SOURCE}: exists, same assistant and log type, will reuse"
else
    SOURCE_EXISTS=false; echo "  delivery source ${SOURCE}: will be created"
fi
DST_NOW=$(L describe-delivery-destinations --query "deliveryDestinations[?name=='${DESTINATION}'] | [0].deliveryDestinationConfiguration.destinationResourceArn" --output json | jtext)
if [[ -n "$DST_NOW" ]]; then
    [[ "${DST_NOW%:\*}" == "$LOG_GROUP_ARN" ]] || die "a delivery destination named ${DESTINATION} exists for ${DST_NOW}. Not replacing it."
    DEST_EXISTS=true; echo "  delivery destination ${DESTINATION}: exists, same log group, will reuse"
else
    DEST_EXISTS=false; echo "  delivery destination ${DESTINATION}: will be created"
fi

# ── 1. Log group ─────────────────────────────────────────────────────────────
echo "== 1. Log group ${LOG_GROUP}"
if L describe-log-groups --log-group-name-prefix "$LOG_GROUP" \
        --query "logGroups[?logGroupName=='${LOG_GROUP}'] | length(@)" --output json | jtext | grep -qx 1; then
    echo "  exists: used as it is (retention unchanged)"
else
    run aws logs create-log-group --region "$REGION" --log-group-name "$LOG_GROUP" --tags "$TAG"
    run aws logs put-retention-policy --region "$REGION" --log-group-name "$LOG_GROUP" --retention-in-days "$RETENTION"
fi

# ── 2. Delivery source and destination (created only if missing) ─────────────
echo "== 2. Delivery source and destination"
$SOURCE_EXISTS || run aws logs put-delivery-source --region "$REGION" --name "$SOURCE" \
    --resource-arn "$ASSISTANT_ARN" --log-type EVENT_LOGS --tags "$TAG"
$DEST_EXISTS || run aws logs put-delivery-destination --region "$REGION" --name "$DESTINATION" --output-format json \
    --delivery-destination-configuration "destinationResourceArn=${LOG_GROUP_ARN}" --tags "$TAG"
$SOURCE_EXISTS && $DEST_EXISTS && echo "  both exist already"

# ── 3. Delivery ──────────────────────────────────────────────────────────────
echo "== 3. Delivery"
EXISTING=$(L describe-deliveries --query "deliveries[?deliverySourceName=='${SOURCE}'].id | [0]" --output json | jtext)
if [[ -n "$EXISTING" ]]; then
    echo "  already delivering (${EXISTING})"
else
    run aws logs create-delivery --region "$REGION" --delivery-source-name "$SOURCE" --delivery-destination-arn "$DEST_ARN" --tags "$TAG"
fi

cat <<NEXT

AI agent event logs: ${LOG_GROUP}
Find one contact's turns, for example in CloudWatch Logs Insights on that group:
  fields @timestamp, @message | filter @message like /<contact id or session id>/ | sort @timestamp asc
NEXT
