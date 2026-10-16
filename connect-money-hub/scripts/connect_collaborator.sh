#!/usr/bin/env bash
# =============================================================================
# connect_collaborator.sh
# =============================================================================
# Makes the Money Hub agent a collaborator of ARIA, reachable on calls and
# chats (README step 5). There is no console screen for this: it is API-only.
#
# DRY RUN BY DEFAULT: it shows what it would do. Add --apply to do it.
#
# With --apply it changes your AWS account:
#   1. AppIntegrations application aria-money-hub, type A2A_SERVER: the bridge's
#      address and the API key secret
#   2. Associates that application with your Connect instance
#   3. ARIA (my-conversation-agent): adds the Money Hub as a collaborator that
#      talks to the customer (text; Connect speaks it in ARIA's voice), keeping
#      everything else. A backup of ARIA's configuration is saved first
#   4. A security profile "ARIA AI agent collaborators" that allows the
#      application (THIRD_PARTY) and Access Contact Control Panel, associated
#      with ARIA's unversioned and new versioned ARN
#   5. Publishes a new ARIA version and prints its number. You then point
#      conversation bot flow at it (README step 6)
#
# ARIA's prompt and guardrail versions are set here too: by default the newest
# published version of each (the console's agent "Save" doesn't reach the
# configuration this script reads, so don't rely on it). --prompt-version N and
# --guardrail-version N choose others; --keep-versions leaves them as they are.
#
# --check only reads: it confirms ARIA (and a version, with --version N) is linked
# to the collaborators profile and that the profile allows the application.
# Saving ARIA in the AI agent designer can replace its security profiles, which
# stops the hand-over (Connect refuses it and the chat ends); run --check after.
#
# Usage:
#   ./connect-money-hub/scripts/connect_collaborator.sh [--apply] [--remove] [--check [--version N]] [--region R]
#       [--prompt-version N] [--guardrail-version N] [--keep-versions]
#       [--account-id A] [--instance-id ID] [--assistant-id ID] [--aria-agent-id ID]
#
# Requirements: AWS CLI v2.27+ (qconnect, appintegrations), python3.
# Your instance must be on the Connect Customer tier; otherwise step 3 fails, saying so.
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; RESET='\033[0m'
ok()     { echo -e "${GREEN}[ OK ] $*${RESET}"; }
warn()   { echo -e "${YELLOW}[WARN] $*${RESET}"; }
die()    { echo -e "${RED}[FAIL] $*${RESET}" >&2; exit 1; }
header() { echo -e "\n${CYAN}== $* ==${RESET}"; }

REGION="${AWS_REGION:-eu-west-2}"
ACCOUNT_ID="${AWS_ACCOUNT_ID:-395402194296}"
INSTANCE_ID="f969d4b4-f716-4974-a325-bb7899f2f293"
ASSISTANT_ID="e6991ed4-e11c-4194-8d20-13889a36bd15"
ARIA_ID="68179bd0-78d7-4298-8696-b3817a93b6c2"
APPLY=false
REMOVE=false
CHECK=false
CHECK_VERSION=""
PROMPT_VERSION=""
GUARDRAIL_VERSION=""
KEEP_VERSIONS=false
APP_NAME="aria-money-hub"
PROFILE_NAME="ARIA AI agent collaborators"
SECRET_NAME="aria-money-hub/a2a-api-key"
BRIDGE_FUNCTION="aria-money-hub-bridge"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --apply)         APPLY=true; shift ;;
        --remove)        REMOVE=true; shift ;;
        --check)         CHECK=true; shift ;;
        --version)       CHECK_VERSION="$2"; shift 2 ;;
        --prompt-version)    PROMPT_VERSION="$2"; shift 2 ;;
        --guardrail-version) GUARDRAIL_VERSION="$2"; shift 2 ;;
        --keep-versions)     KEEP_VERSIONS=true; shift ;;
        --region)        REGION="$2"; shift 2 ;;
        --account-id)    ACCOUNT_ID="$2"; shift 2 ;;
        --instance-id)   INSTANCE_ID="$2"; shift 2 ;;
        --assistant-id)  ASSISTANT_ID="$2"; shift 2 ;;
        --aria-agent-id) ARIA_ID="$2"; shift 2 ;;
        --help|-h)       sed -n '/^# Usage:/,/^# Requirements:/p' "$0" | sed -E 's/^# ?//'; exit 0 ;;
        *) die "Unknown argument: $1" ;;
    esac
done

for tool in aws python3; do command -v "$tool" >/dev/null || die "${tool} not found on PATH."; done
# External A2A collaborators are new: older CLIs lack these two options (2.35.11 did). Check before changing anything.
cli_ok() {
    "$1" appintegrations create-application help 2>/dev/null | col -b | grep -q -- "--auth-config" \
        && "$1" connect update-security-profile help 2>/dev/null | col -b | grep -q -- "--allowed-ai-agents"
}
if ! cli_ok aws; then
    # A common cause: the installer put a newer CLI somewhere later on PATH (for example ~/.local/bin).
    # If there is one, use it for the whole of this script.
    NEWER=""
    for other in $(which -a aws | awk '!seen[$0]++' | tail -n +2) "$HOME/.local/bin/aws" /usr/local/aws-cli/aws; do
        if [[ -x "$other" ]] && cli_ok "$other"; then NEWER="$other"; break; fi
    done
    [[ -n "$NEWER" ]] || die "Your AWS CLI ($(aws --version 2>&1 | cut -d' ' -f1)) is too old for A2A collaborators: it lacks\n" \
        "  appintegrations create-application --auth-config and connect update-security-profile --allowed-ai-agents.\n" \
        "  Update it (macOS: brew upgrade awscli, or the AWS installer), then run this again."
    warn "Terminal's first AWS CLI ($(command -v aws), $(aws --version 2>&1 | cut -d' ' -f1)) is too old;"
    warn "  using ${NEWER} ($("$NEWER" --version 2>&1 | cut -d' ' -f1)) for this script."
    aws() { command "$NEWER" "$@"; }
fi
CALLER=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) || die "Sign in with the AWS CLI first."
[[ "$CALLER" == "$ACCOUNT_ID" ]] || die "Signed in to ${CALLER}, but the target is ${ACCOUNT_ID}."
if $APPLY; then run() { "$@"; }; else warn "DRY RUN: nothing will change. Add --apply to do it."; run() { echo "  [would run] $*" >&2; }; fi
first_value() { tr -s '[:space:]' '\n' | grep -v -e '^None$' -e '^$' | head -n 1 || true; }
BUILD="$(mktemp -d)"; trap 'rm -rf "$BUILD"' EXIT
INSTANCE_ARN="arn:aws:connect:${REGION}:${ACCOUNT_ID}:instance/${INSTANCE_ID}"
ARIA_ARN="arn:aws:wisdom:${REGION}:${ACCOUNT_ID}:ai-agent/${ASSISTANT_ID}/${ARIA_ID}"

# ARIA (and, if given, one version) must be linked to the collaborators profile, and the profile must allow
# the application; otherwise Connect refuses the hand-over before it reaches the bridge.
verify_links() {
    local version="$1" profile_id app_arn arn missing=0
    profile_id=$({ aws connect list-security-profiles --instance-id "$INSTANCE_ID" --region "$REGION" \
        --query "SecurityProfileSummaryList[?Name=='${PROFILE_NAME}'].Id" --output text 2>/dev/null || true; } | first_value)
    app_arn=$({ aws appintegrations list-applications --region "$REGION" --query "Applications[?Name=='${APP_NAME}'].Arn" \
        --output text 2>/dev/null || true; } | first_value)
    [[ -n "$profile_id" && -n "$app_arn" ]] || { warn "No '${PROFILE_NAME}' profile or ${APP_NAME} application yet."; return 1; }
    aws connect list-security-profile-ai-agents --instance-id "$INSTANCE_ID" --region "$REGION" \
        --security-profile-id "$profile_id" --query 'AllowedAIAgents[].Arn' --output text | tr '\t' '\n' | grep -qx "$app_arn" \
        && ok "The profile allows the ${APP_NAME} application." \
        || { warn "The profile does not allow the ${APP_NAME} application."; missing=1; }
    # Every profile ARIA has (Admin and Agent carry its banking tools) plus ours; a version must carry them all.
    local wanted have pid
    wanted=$( { aws connect list-entity-security-profiles --instance-id "$INSTANCE_ID" --region "$REGION" --entity-type AI_AGENT \
        --entity-arn "$ARIA_ARN" --query 'SecurityProfiles[].Id' --output text; echo "$profile_id"; } | tr -s '[:space:]' '\n' | sort -u)
    for arn in "$ARIA_ARN" ${version:+"${ARIA_ARN}:${version}"}; do
        have=$(aws connect list-entity-security-profiles --instance-id "$INSTANCE_ID" --region "$REGION" --entity-type AI_AGENT \
            --entity-arn "$arn" --query 'SecurityProfiles[].Id' --output text | tr -s '[:space:]' '\n')
        for pid in $wanted; do
            if grep -qx "$pid" <<<"$have"; then continue; fi
            warn "NOT linked: profile ${pid} on ${arn##*/}. Fix:"
            echo "    aws connect associate-security-profiles --instance-id ${INSTANCE_ID} --region ${REGION} --entity-type AI_AGENT --entity-arn ${arn} --security-profiles Id=${pid}"
            missing=1
        done
        [[ $missing == 1 ]] || ok "Linked: ${arn##*/} ($(wc -w <<<"$wanted" | tr -d ' ') profiles, including '${PROFILE_NAME}')"
    done
    return $missing
}

if $CHECK; then
    header "Check ARIA's link to '${PROFILE_NAME}'${CHECK_VERSION:+ (version ${CHECK_VERSION})}"
    if verify_links "$CHECK_VERSION"; then ok "ARIA may hand over to the Money Hub agent."; exit 0; fi
    die "ARIA's tools and the hand-over can fail until the links above are fixed (run the commands shown)."
fi

URL=$({ aws lambda get-function-url-config --function-name "$BRIDGE_FUNCTION" --region "$REGION" --query FunctionUrl --output text 2>/dev/null || true; } | first_value)
SECRET_ARN=$({ aws secretsmanager describe-secret --secret-id "$SECRET_NAME" --region "$REGION" --query ARN --output text 2>/dev/null || true; } | first_value)
[[ -n "$URL" && -n "$SECRET_ARN" ]] || die "The bridge isn't deployed (no Function URL or secret). Run deploy_bridge.sh first."
ok "Bridge: ${URL}"

header "Step 1 - A2A application ${APP_NAME}"
APP_ID=$({ aws appintegrations list-applications --region "$REGION" --query "Applications[?Name=='${APP_NAME}'].Id" --output text 2>/dev/null || true; } | first_value)
APP_ARN=$({ aws appintegrations list-applications --region "$REGION" --query "Applications[?Name=='${APP_NAME}'].Arn" --output text 2>/dev/null || true; } | first_value)
if [[ -n "$APP_ID" ]]; then ok "Application exists: ${APP_ID}"; elif $REMOVE; then warn "No application to use."; else
    if $APPLY; then
        read -r APP_ID APP_ARN < <(aws appintegrations create-application --region "$REGION" --name "$APP_NAME" \
            --namespace "$APP_NAME" --description "ARIA Money Hub (Strands on AgentCore, via A2A bridge)" \
            --application-source-config "{\"ExternalUrlConfig\":{\"AccessUrl\":\"${URL}\"}}" \
            --application-type A2A_SERVER \
            --auth-config "{\"AuthType\":\"API_KEY\",\"CredentialProviderIdentifier\":\"${SECRET_ARN}\"}" \
            --query '[Id,Arn]' --output text)
        ok "Application created: ${APP_ID}"
    else
        echo "  [would run] appintegrations create-application --name ${APP_NAME} --application-type A2A_SERVER --access-url ${URL}"
        APP_ID="(new-application-id)"; APP_ARN="(new-application-arn)"
    fi
fi

header "Step 2 - Associate it with the Connect instance"
if ! $REMOVE; then
    linked=$({ aws connect list-integration-associations --instance-id "$INSTANCE_ID" --region "$REGION" \
        --integration-type APPLICATION --query "IntegrationAssociationSummaryList[?IntegrationArn=='${APP_ARN}'].IntegrationAssociationId" \
        --output text 2>/dev/null || true; } | first_value)
    if [[ -n "$linked" ]]; then ok "Already associated."; else
        run aws connect create-integration-association --instance-id "$INSTANCE_ID" --region "$REGION" \
            --integration-type APPLICATION --integration-arn "$APP_ARN" >/dev/null
        if $APPLY; then ok "Associated."; fi
    fi
fi

header "Step 3 - ARIA's collaborators"
aws qconnect get-ai-agent --assistant-id "$ASSISTANT_ID" --ai-agent-id "$ARIA_ID" --region "$REGION" > "$BUILD/aria.json"
mkdir -p "$SCRIPT_DIR/backups"
cp "$BUILD/aria.json" "$SCRIPT_DIR/backups/aria-before-money-hub-$(date +%Y%m%d%H%M%S).json"
read -r CUR_PROMPT CUR_GUARDRAIL < <(python3 -c 'import json,sys
o = json.load(open(sys.argv[1]))["aiAgent"]["configuration"]["orchestrationAIAgentConfiguration"]
print(o.get("orchestrationAIPromptId") or "-", o.get("orchestrationAIGuardrailId") or "-")' "$BUILD/aria.json")
newest() {   # newest published version number of a prompt or guardrail
    aws qconnect "list-ai-$1-versions" --assistant-id "$ASSISTANT_ID" --region "$REGION" "--ai-$1-id" "$2" \
        --query "ai$3VersionSummaries[].versionNumber" --output text | tr -s '[:space:]' '\n' | grep -E '^[0-9]+$' | sort -n | tail -n 1
}
if ! $KEEP_VERSIONS; then
    [[ -n "$PROMPT_VERSION" || "$CUR_PROMPT" == "-" ]] || PROMPT_VERSION=$(newest prompt "${CUR_PROMPT%%:*}" Prompt)
    [[ -n "$GUARDRAIL_VERSION" || "$CUR_GUARDRAIL" == "-" ]] || GUARDRAIL_VERSION=$(newest guardrail "${CUR_GUARDRAIL%%:*}" Guardrail)
fi
echo "  Prompt version:    ${CUR_PROMPT##*:} -> ${PROMPT_VERSION:-${CUR_PROMPT##*:}}"
[[ "$CUR_GUARDRAIL" == "-" ]] || echo "  Guardrail version: ${CUR_GUARDRAIL##*:} -> ${GUARDRAIL_VERSION:-${CUR_GUARDRAIL##*:}}"
python3 "$SCRIPT_DIR/collaborator.py" "$($REMOVE && echo remove || echo add)" "$APP_ID" \
    --prompt-version "$PROMPT_VERSION" --guardrail-version "$GUARDRAIL_VERSION" < "$BUILD/aria.json" > "$BUILD/config.json"
python3 - "$BUILD/aria.json" "$BUILD/config.json" <<'PY'
import json, sys
before = json.load(open(sys.argv[1]))["aiAgent"]["configuration"]["orchestrationAIAgentConfiguration"].get("multiAgentConfigurations") or []
after = json.load(open(sys.argv[2]))["orchestrationAIAgentConfiguration"].get("multiAgentConfigurations") or []
print(f"  Collaborators before: {len(before)}  after: {len(after)}")
PY
if $APPLY; then
    aws qconnect update-ai-agent --assistant-id "$ASSISTANT_ID" --ai-agent-id "$ARIA_ID" --region "$REGION" \
        --visibility-status PUBLISHED --configuration "file://$BUILD/config.json" >/dev/null \
        || die "ARIA could not be updated. If the message mentions the tier, your instance must be on Connect Customer."
    ok "ARIA updated (backup in scripts/backups/)."
else
    echo "  [would run] qconnect update-ai-agent (my-conversation-agent) with the configuration above"
fi

header "Step 4 - Security profile '${PROFILE_NAME}'"
if ! $REMOVE; then
    PROFILE_ID=$({ aws connect list-security-profiles --instance-id "$INSTANCE_ID" --region "$REGION" \
        --query "SecurityProfileSummaryList[?Name=='${PROFILE_NAME}'].Id" --output text 2>/dev/null || true; } | first_value)
    if [[ -z "$PROFILE_ID" ]]; then
        if $APPLY; then
            PROFILE_ID=$(aws connect create-security-profile --instance-id "$INSTANCE_ID" --region "$REGION" \
                --security-profile-name "$PROFILE_NAME" --description "Lets ARIA bring in external A2A collaborators" \
                --permissions BasicAgentAccess --query SecurityProfileId --output text)
        else echo "  [would run] connect create-security-profile ${PROFILE_NAME} (Access Contact Control Panel)"; PROFILE_ID="(new)"; fi
    fi
    run aws connect update-security-profile --instance-id "$INSTANCE_ID" --region "$REGION" --security-profile-id "$PROFILE_ID" \
        --permissions BasicAgentAccess --allowed-ai-agents "[{\"Arn\":\"${APP_ARN}\",\"Type\":\"THIRD_PARTY\"}]" >/dev/null
    run aws connect associate-security-profiles --instance-id "$INSTANCE_ID" --region "$REGION" \
        --entity-arn "$ARIA_ARN" --entity-type AI_AGENT --security-profiles "Id=${PROFILE_ID}" >/dev/null
    if $APPLY; then ok "Profile allows the application and contact context; associated with ARIA."; fi
fi

header "Step 5 - Publish a new ARIA version"
if $APPLY; then
    VERSION=$(aws qconnect create-ai-agent-version --assistant-id "$ASSISTANT_ID" --ai-agent-id "$ARIA_ID" --region "$REGION" \
        --query versionNumber --output text)
    if ! $REMOVE; then
        # A version published through the API gets no profiles of its own: copy all of ARIA's (Admin and Agent
        # carry its banking tools; without them every tool call fails and the flow hangs up), plus ours.
        for pid in $( { aws connect list-entity-security-profiles --instance-id "$INSTANCE_ID" --region "$REGION" \
                --entity-type AI_AGENT --entity-arn "$ARIA_ARN" --query 'SecurityProfiles[].Id' --output text; \
                echo "$PROFILE_ID"; } | tr -s '[:space:]' '\n' | sort -u); do
            aws connect associate-security-profiles --instance-id "$INSTANCE_ID" --region "$REGION" \
                --entity-arn "${ARIA_ARN}:${VERSION}" --entity-type AI_AGENT --security-profiles "Id=${pid}" >/dev/null
        done
    fi
    ok "Published ARIA version ${VERSION}."
    $REMOVE || verify_links "$VERSION" || die "ARIA was published but is missing profiles; run the commands above."
else
    echo "  [would run] qconnect create-ai-agent-version, then associate the profile with the versioned ARN"
    VERSION="(new version)"
fi

header "Done"
cat <<SUMMARY

  ARIA version to use: ${VERSION}
  Next (README step 6): in conversation bot flow, point both places at version ${VERSION}:
    - the Connect assistant block that names my-conversation-agent
    - the Get customer input block's session attribute x-amz-lex:q-in-connect:ai-agent-arn
  Then Save and Publish.
SUMMARY
