#!/usr/bin/env bash
# =============================================================================
# attach_disputes_collaborator.sh
# =============================================================================
# Adds the disputes agent to ARIA as a collaborator that talks to the customer
# (an agent-to-agent "handoff"), and publishes a new version of ARIA.
#
# Why a script: Connect has no console screen for collaborators. They can only
# be set through the API.
#
# YOU run this script. It makes changes in your AWS account:
#   1. Reads ARIA's AI agent as it is now and saves that to a backup file
#   2. Adds (or refreshes) one collaborator entry, leaving the prompt, tools and
#      everything else about ARIA exactly as they were
#   3. Publishes a new version of ARIA
#
# It does NOT change any contact flow. A new agent version is not live until
# "conversation bot flow" names it; the steps are printed at the end.
#
# Safe to run again: the collaborator is replaced, never added twice.
#
# Usage:
#   ./connect-card-dispute/scripts/attach_disputes_collaborator.sh --collaborator-agent-id ID [OPTIONS]
#
# Options:
#   --collaborator-agent-id ID  The disputes agent's ID (required unless --remove).
#                               It is the last part of the agent's ARN, shown on
#                               its page in AI agent designer
#   --remove                    Take the disputes collaborator off ARIA instead
#   --region        REGION      AWS region              (default: eu-west-2)
#   --assistant-id  ID          Connect assistant ID    (default: e6991ed4-e11c-4194-8d20-13889a36bd15)
#   --aria-agent-id ID          ARIA's AI agent ID      (default: 68179bd0-78d7-4298-8696-b3817a93b6c2)
#   --dry-run                   Show the change without making it
#   --help                      Show this help text
#
# Requirements:
#   - A recent AWS CLI v2 (one that knows multiAgentConfigurations on qconnect)
#   - python3 (standard library only)
#   - Your Connect instance on the "Connect Customer" tier
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

die()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; exit 1; }
warn()  { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
step()  { echo -e "${CYAN}[....] $*${RESET}"; }
ok()    { echo -e "${GREEN}[ OK ] $*${RESET}"; }
header(){ echo -e "\n${BOLD}━━━ $* ━━━${RESET}"; }

REGION="${AWS_REGION:-eu-west-2}"
ASSISTANT_ID="e6991ed4-e11c-4194-8d20-13889a36bd15"
ARIA_AGENT_ID="68179bd0-78d7-4298-8696-b3817a93b6c2"
COLLABORATOR_ID=""
REMOVE=false
DRY_RUN=false

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="${SCRIPT_DIR}/../backups"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --collaborator-agent-id) COLLABORATOR_ID="$2"; shift 2 ;;
        --remove)                REMOVE=true; shift ;;
        --region)                REGION="$2";        shift 2 ;;
        --assistant-id)          ASSISTANT_ID="$2";  shift 2 ;;
        --aria-agent-id)         ARIA_AGENT_ID="$2"; shift 2 ;;
        --dry-run)               DRY_RUN=true; shift ;;
        --help|-h)
            sed -n '/^# Usage:/,/^# Requirements:/p' "$0" | sed -E 's/^# ?//'
            exit 0
            ;;
        *) die "Unknown argument: $1. Run with --help for usage." ;;
    esac
done

UUID='^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
command -v aws     >/dev/null 2>&1 || die "AWS CLI not found."
command -v python3 >/dev/null 2>&1 || die "python3 not found."
[[ "$ARIA_AGENT_ID" =~ $UUID ]] || die "--aria-agent-id is not an agent ID."
if ! $REMOVE; then
    [[ -n "$COLLABORATOR_ID" ]] || die "--collaborator-agent-id is required. It is the disputes agent's ID."
    [[ "$COLLABORATOR_ID" =~ $UUID ]] || die "--collaborator-agent-id is not an agent ID (it looks like 1a2b3c4d-....)."
    [[ "$COLLABORATOR_ID" != "$ARIA_AGENT_ID" ]] || die "The collaborator cannot be ARIA itself."
fi

BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT

# =============================================================================
# Step 1 — Read ARIA as it is
# =============================================================================
header "Step 1 — Reading ARIA's AI agent"

aws qconnect get-ai-agent --region "$REGION" --assistant-id "$ASSISTANT_ID" --ai-agent-id "$ARIA_AGENT_ID" \
    --output json > "${BUILD_DIR}/aria.json" \
    || die "Could not read ARIA's AI agent. Sign in with the AWS CLI and check the IDs."
ok "Read '$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["aiAgent"]["name"])' "${BUILD_DIR}/aria.json")'"

if ! $REMOVE; then
    aws qconnect get-ai-agent --region "$REGION" --assistant-id "$ASSISTANT_ID" --ai-agent-id "$COLLABORATOR_ID" \
        --output json > "${BUILD_DIR}/collaborator.json" \
        || die "No AI agent with ID ${COLLABORATOR_ID} in this assistant."
fi

# =============================================================================
# Step 2 — Work out the change
# =============================================================================
header "Step 2 — The change"

# The logic is in collaborator_config.py, which has unit tests. It checks the
# disputes agent can hand a conversation back, and changes ARIA in one place only.
python3 "${SCRIPT_DIR}/collaborator_config.py" "$BUILD_DIR" "$COLLABORATOR_ID" "$REMOVE" \
    || die "The collaborator cannot be attached (see above). Nothing was changed."

if [[ "$(cat "${BUILD_DIR}/changed")" == "no" ]]; then
    ok "Nothing to change: ARIA already has exactly this collaborator."
    exit 0
fi
if $DRY_RUN; then
    warn "DRY-RUN — nothing changed. Run again without --dry-run to apply."
    exit 0
fi

mkdir -p "$BACKUP_DIR"
BACKUP_FILE="${BACKUP_DIR}/aria-agent-$(date +%Y%m%d-%H%M%S).json"
cp "${BUILD_DIR}/backup.json" "$BACKUP_FILE"
ok "ARIA's configuration before the change saved to ${BACKUP_FILE}"

# =============================================================================
# Step 3 — Apply and publish
# =============================================================================
header "Step 3 — Updating ARIA and publishing a version"

step "Updating the AI agent..."
if ! aws qconnect update-ai-agent --region "$REGION" --assistant-id "$ASSISTANT_ID" --ai-agent-id "$ARIA_AGENT_ID" \
        --visibility-status PUBLISHED --configuration "file://${BUILD_DIR}/configuration.json" \
        --query "aiAgent.name" --output text > /dev/null 2> "${BUILD_DIR}/error.txt"; then
    cat "${BUILD_DIR}/error.txt" >&2
    if grep -qi "Unknown parameter\|multiAgentConfigurations" "${BUILD_DIR}/error.txt"; then
        die "Your AWS CLI does not know about collaborators yet. Update the AWS CLI and run this again."
    fi
    die "Connect refused the update. If it mentions the instance tier, agent-to-agent collaboration needs the 'Connect Customer' tier. Nothing was published; ARIA is unchanged for callers."
fi
ok "AI agent updated."

step "Publishing a new version..."
VERSION=$(aws qconnect create-ai-agent-version --region "$REGION" --assistant-id "$ASSISTANT_ID" \
    --ai-agent-id "$ARIA_AGENT_ID" --query "versionNumber" --output text) \
    || die "The agent was updated but a version could not be published. Publish it from AI agent designer."
ok "Published ARIA version ${VERSION}"

header "Done"
cat <<SUMMARY

  ARIA version ${VERSION} $($REMOVE && echo "no longer has" || echo "now has") the disputes agent as a collaborator.

$(printf "${YELLOW}")It is not live yet. Callers get it only when the bot flow names version ${VERSION}:$(printf "${RESET}")

  Routing → Flows → conversation bot flow
    1. First Connect assistant block: choose version ${VERSION} of my-conversation-agent.
    2. Second Connect assistant block (just before Get customer input): the same.
    3. Get customer input block → Session attributes →
       x-amz-lex:q-in-connect:ai-agent-arn: change the number at the end to ${VERSION}.
    4. Save, then Publish.

  To undo: point the flow back at the previous version. To take the collaborator
  off ARIA altogether, run this script with --remove.

SUMMARY
