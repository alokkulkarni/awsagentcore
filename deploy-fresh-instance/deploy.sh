#!/usr/bin/env bash
# =============================================================================
# deploy-fresh-instance/deploy.sh
#
# Builds the whole ARIA system in a NEW AWS account, on a NEW Amazon Connect instance, in dependency order:
# the instance and its queues, Q in Connect (assistant, knowledge base, guardrail), the Lex bot, the MCP gateway and
# its tools (the branch finder, appointment and queue-status tools too), the core Lambdas, every contact flow and module,
# Money Hub (page, agent, A2A bridge, collaborator), card disputes, the mortgage Live Sync backend and reference page,
# the agentic CX designer apps (mortgage and card dispute assistants), ARIA v2 and the advisers' AI agents, the screen
# pop and agent assist, the banking app, and a final read-back.
#
# Interactive: every step says what it makes and why, shows the command, and asks before running it. Its output
# follows straight away. IDs go to state/<alias>.env, so you can stop at any point and carry on later.
# A few values only a console can give you (today's and the new designer's API keys, each designer app's Touchpoint
# keys, your Tavus keys for the video avatar): the script stops, tells you exactly where to click, and checks what you
# paste.
#
# Usage:
#   ./deploy.sh --config my.env                 run every step, asking before each
#   ./deploy.sh --config my.env --from flows-fill   carry on from a step
#   ./deploy.sh --config my.env --only aria-agent   run one step again (also one marked done)
#   ./deploy.sh --config my.env --list          the steps, in order, with what's done
#   ./deploy.sh --config my.env --yes           don't ask before each step (console pauses still ask)
#   ./deploy.sh --config old.env capture-acxd   capture the designer apps from TODAY's workspace on their own
#                                               (designer-access does it too when templates/acxd is missing)
#
# Requirements: bash 4+ (macOS: brew install bash), AWS CLI 2.38+, Python 3 with a current boto3, node 20+, npm,
# AWS SAM CLI, docker with buildx, jq, zip, curl, openssl, and checkouts of connect-livesync-mortgage and
# branchtransfercalldesign (ARIA's branch and appointment tools).
# Sign in to the NEW account first (AWS_PROFILE in your config). It refuses the account today's system runs in.
# =============================================================================
set -Eeuo pipefail          # -E: the error trap applies inside step functions too

if (( BASH_VERSINFO[0] < 4 )); then
    echo "This needs bash 4 or later (macOS ships 3.2). Install it with: brew install bash" >&2
    echo "Then run: \$(brew --prefix)/bin/bash $0 $*" >&2
    exit 1
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PY="${PYTHON:-python3}"
# shellcheck source=lib/ui.sh
source "$HERE/lib/ui.sh"

CONFIG=""; FROM=""; ONLY=""; LIST=false; COMMAND="deploy"
# shellcheck disable=SC2034  # ASSUME_YES is read by lib/ui.sh
while [[ $# -gt 0 ]]; do
    case "$1" in
        --config) CONFIG="$2"; shift 2 ;;
        --from)   FROM="$2"; shift 2 ;;
        --only)   ONLY="$2"; shift 2 ;;
        --list)   LIST=true; shift ;;
        --yes)    ASSUME_YES=true; shift ;;
        capture-acxd) COMMAND="capture"; shift ;;
        -h|--help) sed -n '/^# Usage:/,/^# Requirements:/p' "$0" | sed -E 's/^# ?//'; exit 0 ;;
        *) die "Unknown argument: $1 (see --help)" ;;
    esac
done
[[ -n "$CONFIG" && -f "$CONFIG" ]] || die "Give your settings with --config FILE (copy config.example.env)."
CONFIG="$(cd "$(dirname "$CONFIG")" && pwd)/$(basename "$CONFIG")"
# shellcheck disable=SC1090
source "$CONFIG"
: "${INSTANCE_ALIAS:?INSTANCE_ALIAS must be set in your config}" "${REGION:?REGION must be set in your config}"
[[ -n "${AWS_PROFILE:-}" ]] && export AWS_PROFILE
export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"
MORTGAGE_REPO="${MORTGAGE_REPO:-$HOME/Downloads/connect-livesync-mortgage}"
BRANCH_REPO="${BRANCH_REPO:-$HOME/Documents/Development/branchtransfercalldesign}"
STATE="$HERE/state/${INSTANCE_ALIAS}.env"
LOG="$HERE/state/${INSTANCE_ALIAS}.log"
mkdir -p "$HERE/state"; chmod 700 "$HERE/state"

st()  { "$PY" "$HERE/py/state.py" "$STATE" "$@"; }
v()   { st get "$1"; }
# needs KEY...: stop before running anything if a step's inputs aren't known yet (a failure inside "$(...)" in an
# argument wouldn't stop the command it feeds).
needs() { local k; for k in "$@"; do st has "$k" || die "$k isn't known yet: run the step that makes it first (--list)."; done; }
py()  { local helper="$1" command="$2"; shift 2; "$PY" "$HERE/py/${helper}.py" "$command" --state "$STATE" "$@"; }

# ── capture-acxd: against TODAY's workspace, read only ───────────────────────
# On its own (capture-acxd) or from designer-access when templates/acxd is missing. Uses the designer's API key only,
# so which AWS account you're signed in to doesn't matter.
capture_acxd() {
    echo "${BOLD}Capture the agentic CX designer apps from today's workspace (reads only)${RESET}"
    about "Writes every flow, Data request, knowledge base, guardrail, Live Sync script and application in the" \
          "workspace to templates/acxd, so the new account's designer can be rebuilt from them. Secret values are" \
          "never read; only their names."
    console "today's designer API key" \
        "1. Open today's Connect admin website → Agentic CX designer → your workspace (ariaworkspace)." \
        "2. Settings → Programmatic users → your user (or Create) → API keys → Create key. Copy it." \
        "3. The workspace ID is in Settings → Workspace (or the address bar after /workspaces/)."
    secret OLD_KEY "Today's designer API key (acxd_...)"
    ask OLD_WORKSPACE "Today's workspace ID" "55c49fa0-22f3-4dd3-823d-e353f4aee139"
    ask OLD_REGION "Its region" "eu-west-2"
    (cd "$HERE/acxd" && { [[ -d node_modules/amazon-connect-acxd-sdk ]] || npm install --no-audit --no-fund; } &&
        ACXD_API_KEY="$OLD_KEY" ACXD_WORKSPACE_ID="$OLD_WORKSPACE" ACXD_REGION="$OLD_REGION" node capture.mjs)
    [[ -f "$HERE/templates/acxd/index.json" ]] || die "The capture didn't write templates/acxd/index.json (see above)."
    ok "Captured to templates/acxd. Commit it so the next fresh deploy can use it (no secret values are in it)."
}
if [[ "$COMMAND" == "capture" ]]; then
    capture_acxd
    exit 0
fi

# The run's settings, kept with its IDs.
st set REGION "$REGION"; st set INSTANCE_ALIAS "$INSTANCE_ALIAS"; st set MORTGAGE_REPO "$MORTGAGE_REPO"
st set BRANCH_REPO "$BRANCH_REPO"
for k in ACXD_MORTGAGE_APP_NAME ACXD_DISPUTE_APP_NAME ARIA_MODEL_ID AGENT_ASSIST_MODEL_ID BRIEFING_MODEL_ID; do
    [[ -n "${!k:-}" ]] && st set "$k" "${!k}"
done

# ── The steps, in order ──────────────────────────────────────────────────────
# id | phase | title. Each has a function step_<id with - as _>.
STEPS=(
  "preflight|0 Preflight|The right account, nothing in the way, and every tool the scripts need"
  "instance|1 Connect instance|The Amazon Connect instance, its settings and storage"
  "queues|1 Connect instance|Queues, hours and routing"
  "admin-user|1 Connect instance|The admin who signs in to the Connect admin website"
  "assistant|2 Q in Connect|ARIA's Q in Connect assistant (domain)"
  "knowledge-base|2 Q in Connect|The bank's knowledge base (Bedrock, S3 Vectors) on the assistant"
  "guardrail|2 Q in Connect|ARIA's guardrail"
  "ai-logging|2 Q in Connect|AI agent event logs to CloudWatch"
  "lex-bot|3 Lex|The bot that hands every customer turn to ARIA"
  "gateway|4 Tools and core Lambdas|The MCP gateway and ARIA's banking tools (AgentCore)"
  "mock-data|4 Tools and core Lambdas|The demo's sample customers in the tools"
  "mcp-app|4 Tools and core Lambdas|The gateway registered with Connect as an MCP server"
  "injector|4 Tools and core Lambdas|The session injector (who the customer is, for ARIA)"
  "handback-recovery|4 Tools and core Lambdas|Hand-back recovery (chats Connect loses on the way back)"
  "routing|4 Tools and core Lambdas|Routing lookup (which queue an escalation goes to)"
  "branch-tools|4 Tools and core Lambdas|Branch finder, appointment and queue-status tools (on the gateway)"
  "flow-shells|5 Flows|Every contact flow and module, as placeholders (for their IDs)"
  "money-hub|6 Money Hub, disputes, mortgage|Money Hub: its page, API and tools"
  "money-hub-agent|6 Money Hub, disputes, mortgage|The Money Hub agent (Strands on AgentCore Runtime)"
  "money-hub-bridge|6 Money Hub, disputes, mortgage|The A2A bridge Connect talks to"
  "bridge-warmer|6 Money Hub, disputes, mortgage|Keep the bridge warm (every 5 minutes)"
  "money-hub-a2a|6 Money Hub, disputes, mortgage|Money Hub registered with Connect as ARIA's collaborator"
  "card-dispute|6 Money Hub, disputes, mortgage|The card dispute service, its tools and pages"
  "dispute-pages|6 Money Hub, disputes, mortgage|CloudFront in front of the dispute pages"
  "mortgage-backend|6 Money Hub, disputes, mortgage|The mortgage Live Sync backend (connect-livesync-mortgage)"
  "mortgage-web|6 Money Hub, disputes, mortgage|The mortgage reference page and CX simulation (CloudFront)"
  "tool-grants|6 Money Hub, disputes, mortgage|Admin and Agent may use every gateway tool"
  "agent-assist-lambda|6 Money Hub, disputes, mortgage|The advisers' agent-assist injector (screen pop data)"
  "web-urls|6 Money Hub, disputes, mortgage|The web addresses made so far"
  "designer-access|7 Agentic CX designer|Access to the new account's designer workspace"
  "designer-apps|7 Agentic CX designer|The mortgage and card dispute assistants, built and deployed"
  "touchpoint-keys|7 Agentic CX designer|Each designer app's Touchpoint keys (for Live Sync on web pages)"
  "aria-agent|8 AI agents|ARIA v2 (the orchestrator customers talk to)"
  "assist-agents|8 AI agents|The advisers' agent-assist and briefing agents"
  "flows-fill|9 Flows|Every flow and module's real content, published"
  "phone|10 Front doors|Optional: a phone number for ARIA"
  "banking-app|10 Front doors|The banking app (the demo's front door)"
  "origins|10 Front doors|Approved web origins for in-app calls and chat"
  "smoke|10 Front doors|Read everything back"
)

# ── Phase 0 ──────────────────────────────────────────────────────────────────
step_preflight() {
    about "Refuses the account today's system runs in, and (on a first run) any account that already has aria-* or" \
          "mortgage-livesync-* resources: every script uses fixed names and would quietly reuse them." \
          "Then checks the AWS CLI, boto3, node, npm, SAM, docker buildx, jq, zip, curl, openssl and MORTGAGE_REPO."
    will "python3 py/preflight.py check"
    go || return 0
    py preflight check
}

# ── Phase 1 ──────────────────────────────────────────────────────────────────
step_instance() {
    about "Creates instance '${INSTANCE_ALIAS}' (Connect-managed users, inbound and outbound calls), waits until it's" \
          "ACTIVE, turns on flow logs, Contact Lens, multi-party calls and chats, enhanced monitoring and message" \
          "streaming, and stores chat transcripts and call recordings in a new S3 bucket. Takes a few minutes."
    will "python3 py/connect_setup.py instance"
    go || return 0
    py connect_setup instance
}
step_queues() {
    about "Every new instance has Basic Hours, BasicQueue and the Basic Routing Profile. This adds today's other" \
          "queues by name (Mortgage Advisors, Credit Cards, Fraud...), so escalations and the flows map onto them," \
          "and puts every queue in the Basic Routing Profile for voice and chat."
    will "python3 py/connect_setup.py queues"
    go || return 0
    py connect_setup queues
}
step_admin_user() {
    about "Makes the first user who can sign in to the Connect admin website (Admin and Agent security profiles)." \
          "You'll need it for the designer console pauses later."
    will "python3 py/connect_setup.py admin-user   (username and password from what you type)"
    go || return 0
    local user pass
    ask user "Admin username" "admin"
    secret pass "Password (8-64 characters, upper and lower case and a number)"
    printf '%s\n%s\n' "$user" "$pass" | py connect_setup admin-user
}

# ── Phase 2 ──────────────────────────────────────────────────────────────────
step_assistant() {
    about "Creates the Q in Connect assistant ARIA runs in (type AGENT) and makes it the instance's domain."
    will "python3 py/qconnect_setup.py assistant"
    go || return 0
    py qconnect_setup assistant
}
step_knowledge_base() {
    about "Uploads knowledgebase/meridian-bank to S3, makes a Bedrock knowledge base on S3 Vectors (Titan text" \
          "embeddings v2, 1024 dimensions, as today's), indexes the documents, and associates it with the assistant." \
          "ARIA's Retrieve tool searches it. Needs Bedrock access to Titan text embeddings v2 in this account."
    will "python3 py/qconnect_setup.py knowledge-base"
    go || return 0
    py qconnect_setup knowledge-base
}
step_guardrail() {
    about "ARIA's guardrail (content and word filters, blocked messages) from" \
          "connect-bot-flow-modular/ai-agent/reference/aria-guardrail-v3.json, published."
    will "python3 py/qconnect_setup.py guardrail"
    go || return 0
    py qconnect_setup guardrail
}
step_ai_logging() {
    about "Sends the assistant's AI agent event logs (each turn's model input and output) to CloudWatch Logs, kept" \
          "30 days. This is how you see why ARIA did what she did."
    will "python3 py/qconnect_setup.py logging"
    go || return 0
    py qconnect_setup logging
}

# ── Phase 3 ──────────────────────────────────────────────────────────────────
step_lex_bot() {
    about "A Lex bot with the AMAZON.QInConnectIntent pointing at the assistant (en_GB, 300 s idle), built and" \
          "versioned behind a 'production' alias and associated with the instance. ARIA's main flow talks to it."
    will "python3 py/lexbot.py bot"
    go || return 0
    py lexbot bot
}

# ── Phase 4 ──────────────────────────────────────────────────────────────────
step_gateway() {
    about "scripts/deploy_mcp_gateway.sh: the 10 banking tool Lambdas, the transcript table, and the AgentCore MCP" \
          "gateway with Connect's identity (CUSTOM_JWT, bound to this instance). It also always makes three older" \
          "support Lambdas nothing uses now; they're harmless. Takes several minutes."
    will "AWS_ACCOUNT_ID=$(v ACCOUNT_ID) scripts/deploy_mcp_gateway.sh deploy --env prod --instance-id $(v INSTANCE_ID) --assistant-id $(v ASSISTANT_ID) --region $REGION" \
         "python3 py/integrations.py gateway"
    go || return 0
    needs ACCOUNT_ID ASSISTANT_ID INSTANCE_ID
    AWS_ACCOUNT_ID="$(v ACCOUNT_ID)" bash "$ROOT/scripts/deploy_mcp_gateway.sh" deploy --env prod \
        --instance-id "$(v INSTANCE_ID)" --assistant-id "$(v ASSISTANT_ID)" --region "$REGION"
    py integrations gateway
}
step_mock_data() {
    about "Turns on the demo's sample customers in the auth, account and customer tools (MOCK_DATA=true). The" \
          "gateway script never sets it; without it those tools answer 'No data source configured'."
    will "python3 py/integrations.py mock-data"
    go || return 0
    py integrations mock-data
}
step_mcp_app() {
    about "Registers the gateway with Connect as an MCP server (AppIntegrations MCP_SERVER) and associates it with" \
          "the instance, so AI agents can use its tools."
    will "python3 py/integrations.py mcp-app"
    go || return 0
    py integrations mcp-app
}
step_injector() {
    about "scripts/deploy_session_injector_qconnect.sh (the Lambda the main flow calls to tell ARIA who the" \
          "customer is), then its full package with the bank's sample data (scripts/build_injector_zip.sh: the deploy" \
          "script alone leaves the products out), then allows the instance to call it."
    will "scripts/deploy_session_injector_qconnect.sh --assistant-id $(v ASSISTANT_ID) --instance-id $(v INSTANCE_ID) --cli-match-loa ${CLI_MATCH_LOA:-3}" \
         "python3 py/lambdas.py injector-code" "python3 py/connect_setup.py associate aria-session-injector-qconnect"
    go || return 0
    needs ASSISTANT_ID INSTANCE_ID
    bash "$ROOT/scripts/deploy_session_injector_qconnect.sh" --assistant-id "$(v ASSISTANT_ID)" \
        --instance-id "$(v INSTANCE_ID)" --cli-match-loa "${CLI_MATCH_LOA:-3}"
    py lambdas injector-code
    py connect_setup associate aria-session-injector-qconnect
}
step_handback_recovery() {
    about "scripts/deploy_handback_recovery.sh --apply: the Lambda the main flow calls when Connect loses a chat on" \
          "its way back to ARIA. It associates itself with the instance."
    will "AWS_ACCOUNT_ID=… INSTANCE_ID=… ASSISTANT_ID=… scripts/deploy_handback_recovery.sh --apply --region $REGION"
    go || return 0
    needs ACCOUNT_ID ASSISTANT_ID INSTANCE_ID
    AWS_ACCOUNT_ID="$(v ACCOUNT_ID)" INSTANCE_ID="$(v INSTANCE_ID)" ASSISTANT_ID="$(v ASSISTANT_ID)" \
        bash "$ROOT/scripts/deploy_handback_recovery.sh" --apply --region "$REGION"
}
step_routing() {
    about "scripts/deploy_routing_lambda.sh: the routing table and the Lambda 'ARIA human handover' calls to pick a" \
          "queue. The table is seeded with today's queue IDs; this step swaps each for the new queue with the same" \
          "name, then allows the instance to call the Lambda."
    will "scripts/deploy_routing_lambda.sh deploy --instance-id $(v INSTANCE_ID) --region $REGION" \
         "python3 py/lambdas.py routing-queues" "python3 py/connect_setup.py associate aria-routing-lookup"
    go || return 0
    needs INSTANCE_ID
    ROUTING_STATE_FILE="$HERE/state/${INSTANCE_ALIAS}-routing.json" CONNECT_INSTANCE_ID="$(v INSTANCE_ID)" \
        bash "$ROOT/scripts/deploy_routing_lambda.sh" deploy --instance-id "$(v INSTANCE_ID)" --region "$REGION"
    py lambdas routing-queues
    py connect_setup associate aria-routing-lookup
}

step_branch_tools() {
    about "From branchtransfercalldesign (${BRANCH_REPO}): the tables branches (seeded with its sample branches) and" \
          "branch-appointments, a role and Lambda for each tool, and each as a target on the gateway: branch-info" \
          "(find_branches, get_branch_details, get_current_time), branch-appointments (get_appointment_slots," \
          "book_branch_appointment) and queue-status (get_queue_status, which the advisers' agent-assist agent uses;" \
          "it reads the routing table). Then asks find_branches for Leeds. Its Teams transfer pieces aren't made."
    will "python3 py/branch_tools.py tools"
    go || return 0
    needs GATEWAY_ID INSTANCE_ID BRANCH_REPO
    py branch_tools tools
}

# ── Phase 5 ──────────────────────────────────────────────────────────────────
step_flow_shells() {
    about "The flows transfer to each other in a circle (ARIA → card dispute → ARIA; human handover → agent assist →" \
          "screen pop), so each is first made as a placeholder to get its ID: ARIA's main flow, human handover," \
          "agent assist, screen pop, card dispute, Mortgage Live Sync handover and entry, and the three modules." \
          "Their real content goes in at the 'flows-fill' step, once everything they name exists."
    will "python3 py/flows.py shells"
    go || return 0
    py flows shells
}

# ── Phase 6 ──────────────────────────────────────────────────────────────────
step_money_hub() {
    about "connect-money-hub/scripts/deploy_money_hub.sh: the Money Hub table, its page and API, and its two tools" \
          "on the gateway. The video avatar (Tavus) needs your Tavus keys; without them calls are voice only."
    will "connect-money-hub/scripts/deploy_money_hub.sh --region $REGION --account-id $(v ACCOUNT_ID) --instance-id $(v INSTANCE_ID) --contact-flow-id $(v FLOW_MAIN) --assistant-id $(v ASSISTANT_ID) [--no-avatar]"
    go || return 0
    needs ACCOUNT_ID ASSISTANT_ID FLOW_MAIN INSTANCE_ID
    local avatar=(--no-avatar)
    if [[ -f "$ROOT/connect-money-hub/.env" ]]; then
        yesno "Use the Tavus keys in connect-money-hub/.env for the video avatar?" && avatar=()
    elif yesno "Set up the video avatar now (needs your Tavus API key, face ID and PAL ID)?"; then
        console "your Tavus keys" "1. Sign in at platform.tavus.io." \
            "2. API keys → copy your key; Replicas/Faces → the face ID; PALs → the PAL ID."
        local key face pal
        secret key "Tavus API key"; ask face "Tavus face ID"; ask pal "Tavus PAL ID"
        (umask 077; printf 'TAVUS_API_KEY=%s\nTAVUS_FACE_ID=%s\nTAVUS_PAL_ID=%s\n' "$key" "$face" "$pal" > "$ROOT/connect-money-hub/.env")
        avatar=()
    fi
    bash "$ROOT/connect-money-hub/scripts/deploy_money_hub.sh" --region "$REGION" --account-id "$(v ACCOUNT_ID)" \
        --instance-id "$(v INSTANCE_ID)" --contact-flow-id "$(v FLOW_MAIN)" --assistant-id "$(v ASSISTANT_ID)" "${avatar[@]}"
}
step_money_hub_agent() {
    about "connect-money-hub/scripts/deploy_agent.sh: builds the Money Hub agent's ARM64 image (docker buildx)," \
          "pushes it to ECR and runs it on AgentCore Runtime. Takes several minutes."
    will "connect-money-hub/scripts/deploy_agent.sh --region $REGION --account-id $(v ACCOUNT_ID)"
    go || return 0
    needs ACCOUNT_ID
    bash "$ROOT/connect-money-hub/scripts/deploy_agent.sh" --region "$REGION" --account-id "$(v ACCOUNT_ID)"
}
step_money_hub_bridge() {
    about "connect-money-hub/scripts/deploy_bridge.sh: the A2A bridge Lambda (public Function URL that checks an" \
          "API key only this instance may read) between Connect and the Money Hub agent."
    will "connect-money-hub/scripts/deploy_bridge.sh --region $REGION --account-id $(v ACCOUNT_ID) --instance-id $(v INSTANCE_ID)"
    go || return 0
    needs ACCOUNT_ID INSTANCE_ID
    bash "$ROOT/connect-money-hub/scripts/deploy_bridge.sh" --region "$REGION" --account-id "$(v ACCOUNT_ID)" \
        --instance-id "$(v INSTANCE_ID)"
}
step_bridge_warmer() {
    about "connect-money-hub/scripts/keep_bridge_warm.sh --apply: an EventBridge schedule that wakes the bridge" \
          "every 5 minutes, so the first Money Hub turn isn't slow."
    will "AWS_ACCOUNT_ID=$(v ACCOUNT_ID) connect-money-hub/scripts/keep_bridge_warm.sh --apply --region $REGION"
    go || return 0
    needs ACCOUNT_ID
    AWS_ACCOUNT_ID="$(v ACCOUNT_ID)" bash "$ROOT/connect-money-hub/scripts/keep_bridge_warm.sh" --apply --region "$REGION"
}
step_money_hub_a2a() {
    about "Registers the bridge with Connect as an A2A server (its API key from the bridge's own secret), associates" \
          "it, and makes the 'ARIA AI agent collaborators' security profile that lets ARIA hand over to it." \
          "If Connect refuses with a plan or tier message, the instance needs the AI agents plan that allows" \
          "external agents: turn it on in the Amazon Connect console (instance → AI agents) and run this step again."
    will "python3 py/integrations.py a2a-app"
    go || return 0
    py integrations a2a-app
}
step_card_dispute() {
    about "connect-card-dispute/scripts/deploy_card_dispute.sh: the dispute table, Lambda (allowed on the instance)," \
          "its key in Secrets Manager, its pages API, and five tools on the gateway."
    will "connect-card-dispute/scripts/deploy_card_dispute.sh --region $REGION --account-id $(v ACCOUNT_ID) --instance-id $(v INSTANCE_ID)"
    go || return 0
    needs ACCOUNT_ID INSTANCE_ID
    bash "$ROOT/connect-card-dispute/scripts/deploy_card_dispute.sh" --region "$REGION" \
        --account-id "$(v ACCOUNT_ID)" --instance-id "$(v INSTANCE_ID)"
}
step_dispute_pages() {
    about "connect-card-dispute/scripts/deploy_pages_cloudfront.sh: CloudFront in front of the dispute pages (the" \
          "texted and chat dispute links use it). Takes up to 15 minutes to spread."
    will "connect-card-dispute/scripts/deploy_pages_cloudfront.sh --region $REGION" \
         "connect-card-dispute/scripts/deploy_card_dispute.sh … (again, so the Lambda uses the CloudFront address)"
    go || return 0
    needs ACCOUNT_ID INSTANCE_ID
    bash "$ROOT/connect-card-dispute/scripts/deploy_pages_cloudfront.sh" --region "$REGION"
    bash "$ROOT/connect-card-dispute/scripts/deploy_card_dispute.sh" --region "$REGION" \
        --account-id "$(v ACCOUNT_ID)" --instance-id "$(v INSTANCE_ID)"
}
step_mortgage_backend() {
    about "connect-livesync-mortgage/scripts/deploy-backend.sh (in ${MORTGAGE_REPO}): its tests, then the SAM stack" \
          "mortgage-livesync-api (Lambdas, API, WAF, state table, agent token), with this instance and the" \
          "'Mortgage Live Sync entry' flow for its reference page. Then reads the stack's outputs."
    will "(cd ${MORTGAGE_REPO} && CONNECT_INSTANCE_ID=$(v INSTANCE_ID) WEB_CONTACT_FLOW_ID=$(v FLOW_MORTGAGE_ENTRY) scripts/deploy-backend.sh)" \
         "python3 py/outputs.py mortgage"
    go || return 0
    needs FLOW_MORTGAGE_ENTRY INSTANCE_ID
    # env: a word made by expansion isn't an assignment to bash, so the optional phone number goes through env.
    (cd "$MORTGAGE_REPO" && env STACK_NAME=mortgage-livesync-api CONNECT_INSTANCE_ID="$(v INSTANCE_ID)" \
        WEB_CONTACT_FLOW_ID="$(v FLOW_MORTGAGE_ENTRY)" ${HELP_PHONE_NUMBER:+HELP_PHONE_NUMBER="$HELP_PHONE_NUMBER"} \
        bash scripts/deploy-backend.sh)
    py outputs mortgage
}
step_mortgage_web() {
    about "connect-livesync-mortgage/scripts/deploy-web.sh (in ${MORTGAGE_REPO}): the reference page and the CX" \
          "simulation in a private S3 bucket behind CloudFront, with /api passed to the backend, then its live checks." \
          "The first CloudFront build takes 5-10 minutes."
    will "(cd ${MORTGAGE_REPO} && STACK_NAME=mortgage-livesync-api WEB_STACK_NAME=mortgage-livesync-web scripts/deploy-web.sh)" \
         "python3 py/outputs.py mortgage-web"
    go || return 0
    needs MORTGAGE_ENDPOINT_URL
    (cd "$MORTGAGE_REPO" && env STACK_NAME=mortgage-livesync-api WEB_STACK_NAME=mortgage-livesync-web bash scripts/deploy-web.sh)
    py outputs mortgage-web
}
step_tool_grants() {
    about "Lets the Admin and Agent security profiles use every tool on the gateway (now that the branch tools, Money" \
          "Hub and the dispute service have added theirs). ARIA's tool calls run with these profiles and fail" \
          "without them."
    will "python3 py/integrations.py tool-grants"
    go || return 0
    py integrations tool-grants
}
step_agent_assist_lambda() {
    about "connect-agent-assist/scripts/deploy_agent_assist.sh: the Lambda the screen pop and agent-assist flows" \
          "call (the adviser's view of ARIA's summary, the dispute and the mortgage application). It finds the" \
          "dispute and mortgage Lambdas made above, and associates itself with the instance."
    will "connect-agent-assist/scripts/deploy_agent_assist.sh --region $REGION --account-id $(v ACCOUNT_ID) --instance-id $(v INSTANCE_ID) --assistant-id $(v ASSISTANT_ID)"
    go || return 0
    needs ACCOUNT_ID ASSISTANT_ID INSTANCE_ID
    bash "$ROOT/connect-agent-assist/scripts/deploy_agent_assist.sh" --region "$REGION" --account-id "$(v ACCOUNT_ID)" \
        --instance-id "$(v INSTANCE_ID)" --assistant-id "$(v ASSISTANT_ID)"
}
step_web_urls() {
    about "Reads back the addresses made so far (Money Hub page, dispute pages and its designer Data request" \
          "address), for the steps that need them."
    will "python3 py/outputs.py web"
    go || return 0
    py outputs web
}

# ── Phase 7 ──────────────────────────────────────────────────────────────────
step_designer_access() {
    about "The designer's SDK only accepts an API key, and the first key can only come from its console." \
          "This stores it as the mortgage stack's designer access secret, then runs that stack's sync, which writes" \
          "mortgage_api_key into the workspace."
    [[ -f "$HERE/templates/acxd/index.json" ]] ||
        about "templates/acxd isn't there yet, so first it captures the designer apps from TODAY's workspace (reads" \
              "only; it asks for today's designer API key)."
    will "python3 py/designer.py store-access   (key and workspace ID from what you paste)"
    go || return 0
    needs CONNECT_URL ADMIN_USER MORTGAGE_ACXD_ACCESS_SECRET MORTGAGE_ACXD_SYNC_FUNCTION
    [[ -f "$HERE/templates/acxd/index.json" ]] || capture_acxd
    console "the NEW account's designer API key" \
        "1. Sign in at $(v CONNECT_URL) as $(v ADMIN_USER)." \
        "2. Open Agentic CX designer. If it asks, create a workspace (any name, e.g. ${INSTANCE_ALIAS})." \
        "3. Settings → Programmatic users → Create → give it the workspace admin role → API keys → Create key." \
        "4. Copy the key (it starts acxd_). The workspace ID is in Settings → Workspace."
    local key workspace
    secret key "Designer API key (acxd_...)"
    ask workspace "Workspace ID"
    printf '%s\n%s\n' "$key" "$workspace" | py designer store-access
}
step_designer_apps() {
    about "Rebuilds the captured designer apps in the new workspace (templates/acxd: secrets, context variables," \
          "Data requests pointed at this account's services, guardrails, knowledge bases, Live Sync scripts, flows," \
          "applications), builds and deploys each to development and production, and records their alias codes." \
          "Create-only and resumable: a re-run carries on where it stopped."
    will "python3 py/designer.py create   (runs acxd/create.mjs)"
    go || return 0
    py designer create
}
step_touchpoint_keys() {
    about "Live Sync on a web page (the mortgage form, the dispute form) needs each designer app's Touchpoint" \
          "deployment key and API key. No API returns them, so they come from the designer console." \
          "They're stored in Secrets Manager; the dispute service is then redeployed to pick its up."
    will "python3 py/secrets_store.py put $(v MORTGAGE_TOUCHPOINT_SECRET)" \
         "python3 py/secrets_store.py put aria-card-dispute/touchpoint" \
         "connect-card-dispute/scripts/deploy_card_dispute.sh … (again)"
    go || return 0
    needs ACCOUNT_ID INSTANCE_ID MORTGAGE_TOUCHPOINT_SECRET
    local app secret_name dkey akey
    for app in "Mortgage application|$(v MORTGAGE_TOUCHPOINT_SECRET)" "Card dispute|aria-card-dispute/touchpoint"; do
        secret_name="${app#*|}"
        console "Touchpoint keys for '${app%%|*}'" \
            "1. In the designer: Applications → ${app%%|*} → Deploy (Production) → Touchpoint / Live Sync." \
            "2. Copy the deployment key and the API key shown there."
        secret dkey "Deployment key"; secret akey "API key"
        printf '%s\n%s\n' "$dkey" "$akey" \
            | "$PY" -c 'import json,sys; d,a=[l.rstrip("\n") for l in sys.stdin]; print(json.dumps({"deploymentKey": d, "apiKey": a}))' \
            | py secrets_store put "$secret_name"
    done
    bash "$ROOT/connect-card-dispute/scripts/deploy_card_dispute.sh" --region "$REGION" \
        --account-id "$(v ACCOUNT_ID)" --instance-id "$(v INSTANCE_ID)"
}

# ── Phase 8 ──────────────────────────────────────────────────────────────────
step_aria_agent() {
    about "ARIA v2: her prompt (connect-bot-flow-modular/ai-agent) and agent with her 23 gateway tools (banking," \
          "branches and appointments), Retrieve on the knowledge base, the guardrail and the Money Hub collaborator," \
          "all moved onto this instance; published and linked to Admin, Agent and the collaborators profile. A tool" \
          "the gateway doesn't have would be left out with a warning (none, once branch-tools has run)."
    will "python3 py/agents.py aria"
    go || return 0
    py agents aria
}
step_assist_agents() {
    about "The advisers' agent-assist and briefing agents (connect-agent-assist prompts), with their gateway tools" \
          "(agent assist's include the branch, appointment and queue-status tools)."
    will "python3 py/agents.py agent-assist" "python3 py/agents.py briefing"
    go || return 0
    py agents agent-assist
    py agents briefing
}

# ── Phase 9 ──────────────────────────────────────────────────────────────────
step_flows_fill() {
    about "Puts each flow's real content in: the repo's committed flows and modules (and the two captured from" \
          "today's instance) with every old ID swapped for this instance's, and the card dispute flow built with" \
          "this instance's IDs. Anything still carrying an old ID is refused before it's sent. Connect checks every" \
          "reference on the way in. What was sent is kept in state/${INSTANCE_ALIAS}-flows/."
    will "python3 py/flows.py fill"
    go || return 0
    py flows fill
}

# ── Phase 10 ─────────────────────────────────────────────────────────────────
step_phone() {
    about "Optional (monthly cost): claims a UK number and points it at ARIA's main flow. If you claim one, the" \
          "mortgage backend is redeployed so its 'Get help by phone' panel shows it."
    will "python3 py/connect_setup.py phone   (asks first)"
    go || return 0
    py connect_setup phone
    local number; number="$(v PHONE_NUMBER)"
    if [[ -n "$number" ]]; then
        local local_number="0${number#+44}"
        (cd "$MORTGAGE_REPO" && STACK_NAME=mortgage-livesync-api HELP_PHONE_NUMBER="$local_number" bash scripts/deploy-backend.sh)
    fi
}
step_banking_app() {
    about "connect-banking-app/scripts/deploy_banking_app.sh: the banking app (Lambda, API, its role), pointed at" \
          "ARIA's main flow and this assistant, with its origin approved for in-app calls. Last, because it reads" \
          "the Money Hub, dispute and mortgage services as they are now. It prints the demo link."
    will "ASSISTANT_ID=$(v ASSISTANT_ID) connect-banking-app/scripts/deploy_banking_app.sh --region $REGION --account-id $(v ACCOUNT_ID) --instance-id $(v INSTANCE_ID) --contact-flow-id $(v FLOW_MAIN) --assistant-id $(v ASSISTANT_ID) --approve-origin --flow-view ${FLOW_VIEW:-off}" \
         "python3 py/outputs.py web"
    go || return 0
    needs ACCOUNT_ID ASSISTANT_ID FLOW_MAIN INSTANCE_ID
    bash "$ROOT/connect-banking-app/scripts/deploy_banking_app.sh" --region "$REGION" --account-id "$(v ACCOUNT_ID)" \
        --instance-id "$(v INSTANCE_ID)" --contact-flow-id "$(v FLOW_MAIN)" --assistant-id "$(v ASSISTANT_ID)" \
        --approve-origin --flow-view "${FLOW_VIEW:-off}"
    py outputs web
}
step_origins() {
    about "Approves the Money Hub page, the dispute pages and the mortgage reference page as origins for in-app" \
          "calls and chat (the banking app approved its own)."
    will "python3 py/connect_setup.py origin $(v MONEY_HUB_URL) $(v DISPUTE_PAGES_URL) $(v MORTGAGE_WEB_URL)"
    go || return 0
    needs MONEY_HUB_URL DISPUTE_PAGES_URL MORTGAGE_WEB_URL
    py connect_setup origin "$(v MONEY_HUB_URL)" "$(v DISPUTE_PAGES_URL)" "$(v MORTGAGE_WEB_URL)"
}
step_smoke() {
    about "Reads everything back (instance, flows, Lambdas and bot on the instance, knowledge base, AI agents," \
          "integrations, designer apps, web pages) and prints what's OK or missing. Changes nothing."
    will "python3 py/smoke.py check"
    go || return 0
    py smoke check
    echo
    echo "${BOLD}Where to start${RESET}"
    echo "  Connect admin:  $(v CONNECT_URL)  (user $(v ADMIN_USER))"
    echo "  Banking app:    $(v BANKING_APP_URL)  (open it from the demo link the banking-app step printed; it's also in ${LOG})"
    echo "  Money Hub page: $(v MONEY_HUB_URL)"
    echo "  Mortgage page:  $(v MORTGAGE_WEB_URL)  (reference page; the simulation is at demo/)"
    [[ -n "$(v PHONE_NUMBER)" ]] && echo "  Phone:          $(v PHONE_NUMBER)"
    echo "  Every ID:       $STATE"
}

# ── Running them ─────────────────────────────────────────────────────────────
TOTAL=${#STEPS[@]}
if $LIST; then
    i=0
    for entry in "${STEPS[@]}"; do
        i=$((i + 1)); IFS='|' read -r id phase title <<<"$entry"
        st has "DONE_${id//-/_}" 2>/dev/null && mark="${GREEN}done${RESET}" || mark="    "
        printf '  %2d  %-20s %s  %s%s%s\n' "$i" "$id" "$mark" "$DIM" "$title" "$RESET"
    done
    exit 0
fi

touch "$LOG"; chmod 600 "$LOG"
exec > >(tee -a "$LOG") 2>&1
echo "${BOLD}deploy-fresh-instance · ${INSTANCE_ALIAS} · ${REGION} · $(date '+%Y-%m-%d %H:%M')${RESET}"
echo "State: $STATE · Log: $LOG"

started=false; [[ -z "$FROM" ]] && started=true
found_from=false; found_only=false
i=0
for entry in "${STEPS[@]}"; do
    i=$((i + 1)); IFS='|' read -r id phase title <<<"$entry"
    [[ "$id" == "$FROM" ]] && { started=true; found_from=true; }
    if [[ -n "$ONLY" ]]; then [[ "$id" == "$ONLY" ]] || continue; found_only=true
    elif ! $started; then continue; fi
    # shellcheck disable=SC2034  # read by lib/ui.sh (the quit message)
    CURRENT_STEP="$id"
    banner "$i" "$TOTAL" "$phase" "$title"
    done_key="DONE_${id//-/_}"
    if [[ -z "$ONLY" ]] && st has "$done_key"; then
        echo "${GREEN}  Already done.${RESET} ${DIM}(--only $id runs it again)${RESET}"
        continue
    fi
    trap 'echo; echo "${RED}Step '"$id"' stopped with an error (above). Fix it, then: ./deploy.sh --config '"$CONFIG"' --from '"$id"'${RESET}"' ERR
    SKIPPED=false
    "step_${id//-/_}"          # a plain call, so any failing command inside stops the run (set -e)
    if ! $SKIPPED; then
        st set "$done_key" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        ok "Step $id done."
    fi
    trap - ERR
done
[[ -z "$FROM" || "$found_from" == true ]] || die "No step called '$FROM' (see --list)."
[[ -z "$ONLY" || "$found_only" == true ]] || die "No step called '$ONLY' (see --list)."
