#!/usr/bin/env bash
# =============================================================================
# create_agent.sh
# =============================================================================
# Creates ARIA v2 in Amazon Connect as NEW resources, and never overwrites anything.
#
#   1. a NEW AI prompt "ARIA-Banking-Orchestration-Prompt-v2" from
#      prompt/aria-orchestration-prompt-v2.yaml, and its first version
#   2. a NEW AI agent "aria-conversation-agent-v2" from agent/aria-conversation-agent-v2.json
#      (live v38's tools minus QueryAssistant, the Money Hub collaborator, guardrail v3),
#      pointing at that prompt version, and its first version
#   3. links the NEW agent (and its version) to the same security profiles as the live
#      ARIA (Admin, Agent, ARIA AI agent collaborators). This adds the agent to those
#      profiles; it doesn't change what the profiles allow.
#
# Safe by design:
#   - CREATE ONLY by default. If a prompt or agent with either name already exists, it
#     stops before changing anything.
#   - Everything it creates is tagged project=connect-bot-flow-modular.
#   - --update publishes a new version of ARIA v2 after you change it, and only touches a
#     prompt and agent that carry that tag. Anything else with those names is refused.
#   - It never writes to the live ARIA (my-conversation-agent) or its prompt: it only reads
#     the live ARIA's security-profile list, and it stops if an ID ever matches them.
#   - If an earlier run created the prompt (tagged) but stopped before the agent, it
#     picks up from there: it reuses that prompt rather than stopping or duplicating it.
#   - DRY RUN unless --apply.
#
# The agent calls go through qconnect_agent.py with the deploy venv's boto3, because the
# AWS CLI's model can lag the API (CLI 2.35 rejects multiAgentConfigurations). Set
# ARIA_PY to use another python whose botocore is recent enough.
#
# Usage:
#   ./ai-agent/create_agent.sh                    # dry run: checks, and shows what it would create
#   ./ai-agent/create_agent.sh --apply            # creates ARIA v2
#   ./ai-agent/create_agent.sh --update           # dry run of updating ARIA v2 (after you change it)
#   ./ai-agent/create_agent.sh --update --apply   # publishes a new ARIA v2 version
# Requirements: AWS CLI v2 (qconnect, connect), python3, and ~/.venvs/aria-deploy with boto3.
# =============================================================================
set -euo pipefail

REGION="${AWS_REGION:-eu-west-2}"
ACCOUNT_ID="395402194296"
INSTANCE_ID="f969d4b4-f716-4974-a325-bb7899f2f293"
ASSISTANT_ID="e6991ed4-e11c-4194-8d20-13889a36bd15"
LIVE_ARIA_ID="68179bd0-78d7-4298-8696-b3817a93b6c2"            # my-conversation-agent: read only, never written
LIVE_PROMPT_ID="37cae8d9-1d2c-49d1-8b1a-771f22f6ab7c"          # ARIA-Banking-Ochestration-Prompt: never written
TAG_KEY="project"; TAG_VALUE="connect-bot-flow-modular"
APPLY=false; UPDATE=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --apply)  APPLY=true; shift ;;
        --update) UPDATE=true; shift ;;
        --region) REGION="$2"; shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

HERE="$(cd "$(dirname "$0")" && pwd)"
BUILD="$(mktemp -d)"; trap 'rm -rf "$BUILD"' EXIT
die() { echo "STOPPED: $*" >&2; exit 1; }
CALLER=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) || die "sign in with the AWS CLI first."
[[ "$CALLER" == "$ACCOUNT_ID" ]] || die "signed in to ${CALLER}, but the target is ${ACCOUNT_ID}."
$APPLY || echo "DRY RUN: nothing will change. Add --apply to do it."
PY_AGENT="${ARIA_PY:-$HOME/.venvs/aria-deploy/bin/python3}"
[[ -x "$PY_AGENT" ]] || die "no ${PY_AGENT}. Create it: python3 -m venv ~/.venvs/aria-deploy && ~/.venvs/aria-deploy/bin/pip install boto3"
# Look-ups use --output json: with --output text the CLI applies --query to each page
# separately. jtext prints the result as text ("" for null or an empty list).
jtext() { python3 -c 'import json,sys
v = json.load(sys.stdin)
print("" if v is None else "\n".join(map(str, v)) if isinstance(v, list) else v)'; }
$UPDATE && echo "MODE: update ARIA v2 (only resources tagged ${TAG_KEY}=${TAG_VALUE})" \
        || echo "MODE: create ARIA v2 as new resources (stops if either name exists)"
q() { aws qconnect "$@" --assistant-id "$ASSISTANT_ID" --region "$REGION"; }

python3 "$HERE/build_agent.py" >/dev/null                     # the files must match the builder
python3 - "$HERE" "$BUILD" <<'PY'
import json, sys
here, build = sys.argv[1], sys.argv[2]
agent = json.load(open(f"{here}/agent/aria-conversation-agent-v2.json"))
text = open(f"{here}/{agent['prompt']['file']}").read()
json.dump({"textFullAIPromptEditTemplateConfiguration": {"text": text}}, open(f"{build}/template.json", "w"))
json.dump(agent["configuration"], open(f"{build}/configuration.json", "w"))
for key in ("name", "modelId", "apiFormat", "type", "templateType"):
    open(f"{build}/prompt.{key}", "w").write(agent["prompt"][key])
open(f"{build}/agent.name", "w").write(agent["name"])
open(f"{build}/agent.description", "w").write(agent["description"])
PY
PROMPT_NAME=$(cat "$BUILD/prompt.name"); AGENT_NAME=$(cat "$BUILD/agent.name")

# ── 0. Pre-flight: what already exists (read only) ──────────────────────────
echo "== 0. Checks"
find_id() {   # $1 = prompts|agents, $2 = name → every ID with that exact name, one per line
    if [[ "$1" == prompts ]]; then
        q list-ai-prompts --query "aiPromptSummaries[?name=='$2'].aiPromptId" --output json
    else
        q list-ai-agents --query "aiAgentSummaries[?name=='$2'].aiAgentId" --output json
    fi | jtext | grep -v '^$' || true
}
tagged() {    # $1 = prompt|agent, $2 = id → succeeds only if it carries our tag
    local value
    if [[ "$1" == prompt ]]; then
        value=$(q get-ai-prompt --ai-prompt-id "$2" --query "aiPrompt.tags.${TAG_KEY}" --output text 2>/dev/null || true)
    else
        value=$(q get-ai-agent --ai-agent-id "$2" --query "aiAgent.tags.${TAG_KEY}" --output text 2>/dev/null || true)
    fi
    [[ "$value" == "$TAG_VALUE" ]]
}
PROMPT_IDS=$(find_id prompts "$PROMPT_NAME"); AGENT_IDS=$(find_id agents "$AGENT_NAME")
[[ $(grep -c . <<<"$PROMPT_IDS" || true) -le 1 ]] || die "more than one prompt is named ${PROMPT_NAME}; resolve that by hand."
[[ $(grep -c . <<<"$AGENT_IDS" || true) -le 1 ]] || die "more than one agent is named ${AGENT_NAME}; resolve that by hand."
PROMPT_ID="$PROMPT_IDS"; AGENT_ID="$AGENT_IDS"
for id in "$PROMPT_ID" "$AGENT_ID"; do
    [[ -z "$id" || ( "$id" != "$LIVE_PROMPT_ID" && "$id" != "$LIVE_ARIA_ID" ) ]] || die "${id} is the live ARIA or its prompt."
done
if $UPDATE; then
    [[ -n "$PROMPT_ID" && -n "$AGENT_ID" ]] || die "--update needs ARIA v2 to exist already. Run without --update to create it."
    tagged prompt "$PROMPT_ID" || die "prompt ${PROMPT_ID} (${PROMPT_NAME}) isn't tagged ${TAG_KEY}=${TAG_VALUE}: not ours, not touching it."
    tagged agent "$AGENT_ID"   || die "agent ${AGENT_ID} (${AGENT_NAME}) isn't tagged ${TAG_KEY}=${TAG_VALUE}: not ours, not touching it."
    echo "  ${PROMPT_NAME} = ${PROMPT_ID} and ${AGENT_NAME} = ${AGENT_ID}: ours (tagged), will publish new versions"
else
    [[ -z "$AGENT_ID" ]]  || die "an agent named ${AGENT_NAME} already exists (${AGENT_ID}). Nothing changed. To publish a new version of ARIA v2, use --update."
    RESUME=false
    if [[ -n "$PROMPT_ID" ]]; then
        tagged prompt "$PROMPT_ID" || die "a prompt named ${PROMPT_NAME} already exists (${PROMPT_ID}) and isn't ours (no ${TAG_KEY}=${TAG_VALUE} tag). Nothing changed."
        RESUME=true
        echo "  ${PROMPT_NAME} = ${PROMPT_ID} is ours (tagged) from a run that stopped before the agent: reusing it"
        echo "  no agent named ${AGENT_NAME}: it will be created new"
    else
        echo "  no prompt named ${PROMPT_NAME}, no agent named ${AGENT_NAME}: both will be created new"
    fi
fi
"$PY_AGENT" "$HERE/qconnect_agent.py" check "$BUILD/configuration.json" --name "$AGENT_NAME" \
    --description "$(cat "$BUILD/agent.description")" --tag "${TAG_KEY}=${TAG_VALUE}" | sed 's/^/  agent request: /' \
    || die "the agent configuration doesn't pass boto3's checks (above). Nothing changed."
echo "  the live ARIA (${LIVE_ARIA_ID}) and its prompt (${LIVE_PROMPT_ID}) are read only here"

# ── 1. Prompt ────────────────────────────────────────────────────────────────
echo "== 1. AI prompt ${PROMPT_NAME}"
if ! $UPDATE && ${RESUME:-false}; then
    # Our prompt from the interrupted run: use its latest version if it matches this build;
    # otherwise update it (it's ours) and publish a new version.
    LATEST=$(q list-ai-prompt-versions --ai-prompt-id "$PROMPT_ID" \
        --query "max_by(aiPromptVersionSummaries, &versionNumber).versionNumber" --output json | jtext)
    SAME=false
    if [[ -n "$LATEST" ]]; then
        q get-ai-prompt --ai-prompt-id "${PROMPT_ID}:${LATEST}" --output json \
            | python3 -c 'import json,sys
live = json.load(sys.stdin)["aiPrompt"]["templateConfiguration"]["textFullAIPromptEditTemplateConfiguration"]["text"]
sys.exit(0 if live == json.load(open(sys.argv[1]))["textFullAIPromptEditTemplateConfiguration"]["text"] else 1)' \
            "$BUILD/template.json" && SAME=true
    fi
    if $SAME; then
        PROMPT_VERSION="$LATEST"; echo "  reusing ${PROMPT_ID} version ${PROMPT_VERSION} (same text as this build)"
    elif $APPLY; then
        q update-ai-prompt --ai-prompt-id "$PROMPT_ID" --visibility-status PUBLISHED \
            --template-configuration "file://$BUILD/template.json" >/dev/null
        PROMPT_VERSION=$(q create-ai-prompt-version --ai-prompt-id "$PROMPT_ID" --query versionNumber --output text)
        echo "  updated ${PROMPT_ID} (ours) to this build and published version ${PROMPT_VERSION}"
    else
        echo "  [would] update ${PROMPT_ID} (ours) to this build and publish a new version"; PROMPT_VERSION="<new version>"
    fi
elif $APPLY; then
    if $UPDATE; then
        q update-ai-prompt --ai-prompt-id "$PROMPT_ID" --visibility-status PUBLISHED \
            --template-configuration "file://$BUILD/template.json" >/dev/null
        echo "  updated ${PROMPT_ID} (ours)"
    else
        PROMPT_ID=$(q create-ai-prompt --name "$PROMPT_NAME" --type "$(cat "$BUILD/prompt.type")" \
            --template-type "$(cat "$BUILD/prompt.templateType")" --model-id "$(cat "$BUILD/prompt.modelId")" \
            --api-format "$(cat "$BUILD/prompt.apiFormat")" --visibility-status PUBLISHED \
            --template-configuration "file://$BUILD/template.json" --tags "${TAG_KEY}=${TAG_VALUE}" \
            --query aiPrompt.aiPromptId --output text)
        echo "  created ${PROMPT_ID}"
    fi
    PROMPT_VERSION=$(q create-ai-prompt-version --ai-prompt-id "$PROMPT_ID" --query versionNumber --output text)
    echo "  published version ${PROMPT_VERSION}"
else
    $UPDATE && echo "  [would] update ${PROMPT_ID} and publish a new version" \
            || echo "  [would] create a new prompt (model $(cat "$BUILD/prompt.modelId"), tagged ${TAG_KEY}=${TAG_VALUE}) and publish version 1"
    PROMPT_ID="${PROMPT_ID:-<new prompt>}"; PROMPT_VERSION="<new version>"
fi

# ── 2. Agent ─────────────────────────────────────────────────────────────────
echo "== 2. AI agent ${AGENT_NAME}"
python3 - "$BUILD" "${PROMPT_ID}:${PROMPT_VERSION}" <<'PY'
import sys
build, prompt = sys.argv[1], sys.argv[2]
text = open(f"{build}/configuration.json").read()
assert text.count("${PROMPT_ID_V2}") == 1, "the agent configuration must name the prompt once"
open(f"{build}/agent-config.json", "w").write(text.replace("${PROMPT_ID_V2}", prompt))
PY
if $APPLY; then
    if $UPDATE; then
        "$PY_AGENT" "$HERE/qconnect_agent.py" update "$BUILD/agent-config.json" \
            --assistant-id "$ASSISTANT_ID" --region "$REGION" --agent-id "$AGENT_ID"
        echo "  updated ${AGENT_ID} (ours)"
    else
        AGENT_ID=$("$PY_AGENT" "$HERE/qconnect_agent.py" create "$BUILD/agent-config.json" \
            --assistant-id "$ASSISTANT_ID" --region "$REGION" --name "$AGENT_NAME" \
            --description "$(cat "$BUILD/agent.description")" --tag "${TAG_KEY}=${TAG_VALUE}")
        echo "  created ${AGENT_ID}"
    fi
    [[ "$AGENT_ID" != "$LIVE_ARIA_ID" ]] || die "refusing to version the live ARIA."
    AGENT_VERSION=$(q create-ai-agent-version --ai-agent-id "$AGENT_ID" --query versionNumber --output text)
    echo "  published version ${AGENT_VERSION}"
else
    $UPDATE && echo "  [would] update ${AGENT_ID} with prompt ${PROMPT_ID}:${PROMPT_VERSION} and publish a new version" \
            || echo "  [would] create a new orchestration agent (21 tools, Money Hub collaborator, guardrail v3, tagged) with prompt ${PROMPT_ID}:${PROMPT_VERSION}, and publish version 1"
    AGENT_ID="${AGENT_ID:-<new agent>}"; AGENT_VERSION="<new version>"
fi

# ── 3. Security profiles (the live ARIA's list, read only) ───────────────────
echo "== 3. Security profiles"
BASE="arn:aws:wisdom:${REGION}:${ACCOUNT_ID}:ai-agent/${ASSISTANT_ID}"
PROFILES=$(aws connect list-entity-security-profiles --instance-id "$INSTANCE_ID" --region "$REGION" \
    --entity-type AI_AGENT --entity-arn "${BASE}/${LIVE_ARIA_ID}" --query 'SecurityProfiles[].Id' --output json | jtext | tr '\n' ' ')
echo "  the live ARIA has: ${PROFILES} (adding ARIA v2 to these; their permissions don't change)"
for arn in "${BASE}/${AGENT_ID}" "${BASE}/${AGENT_ID}:${AGENT_VERSION}"; do
    [[ "$arn" != "${BASE}/${LIVE_ARIA_ID}"* ]] || die "refusing to link profiles to the live ARIA."
    for pid in $PROFILES; do
        if $APPLY; then
            aws connect associate-security-profiles --instance-id "$INSTANCE_ID" --region "$REGION" \
                --entity-type AI_AGENT --entity-arn "$arn" --security-profiles "Id=${pid}" >/dev/null
        else
            echo "  [would] link ${pid} to ${arn##*/}"
        fi
    done
done
$APPLY && echo "  linked $(wc -w <<<"$PROFILES" | tr -d ' ') profiles to ${AGENT_ID} and version ${AGENT_VERSION}"

cat <<NEXT

ARIA v2: ${BASE}/${AGENT_ID}:${AGENT_VERSION}
Next: put that ARN in connect-bot-flow-modular/config.json as "aria", then run
  python3 connect-bot-flow-modular/build_flows.py --config connect-bot-flow-modular/config.json
The live flow and my-conversation-agent are unchanged.
NEXT
