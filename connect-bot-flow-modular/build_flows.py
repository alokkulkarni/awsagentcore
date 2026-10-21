#!/usr/bin/env python3
"""
build_flows.py
==============
Writes the modular "conversation bot flow": one main flow and three flow modules, in Amazon Connect Flow Language
(Version 2019-10-30), ready to import. The business logic is the live flow's, block for block (tests/ prove it
against reference/conversation-bot-flow-live.json); only the structure changes:

    flows/aria-conversation-bot-flow.json      main flow (type: Inbound contact flow)
    modules/aria-contact-setup.json            channel recording/analytics, voice, language
    modules/aria-customer-context.json         session injector → the customer's context on the contact
    modules/aria-decide-handback.json          everything that decides where ARIA's hand-back goes → handbackRoute

Standards: every flow and module switches flow logging on as its first block (logging also carries into any flow
the contact moves to), recording and Contact Lens analytics are set once per contact in Contact setup, and every
block that can fail has an error branch. ARIA's own reasoning and tool calls are in her traces and, once enabled,
in the AI agent event logs (ai-agent/enable_ai_agent_logging.sh).

ARIA is ARIA v2 (ai-agent/), created fresh by ai-agent/create_agent.sh: its version ARN goes in config.json as
"aria". Agent assist for human advisers is not set here: the "ARIA agent assist" flow sets my-agent-assistant-agent
on every route to a person (human handover → agent assist), so the Connect assistant block here only connects
ARIA's session.

Modules can't read the calling flow's Lex or External attributes, so the main flow copies ARIA's hand-back fields
into contact attributes (lex*) before the decision module, and the module answers with one contact attribute,
handbackRoute: card_dispute | mortgage_livesync | mortgage_form | human | retry | end. The main flow has one Transfer
block per destination.

Two ways in besides a new contact (added 20 Oct 2026):
  - Back from the card dispute assistant (entry=returned): the customer finished the dispute and wants something
    else. ARIA carries on: the flow skips Contact setup (already done) and her Connect assistant block when she has
    already had a session on this contact (ariaStarted), runs Customer context again (the injector gives her the customer's next question as the
    known contact reason) and goes straight back to her.
  - The internet banking app's mortgage form (appPage=mortgage) now starts with ARIA. When she hands over for a
    mortgage application, the decision module sends it to the mortgage assistant joined to that form
    (entry=web_widget, handbackRoute=mortgage_form), on chat and on calls, as the form's own Point B does.

The main flow names each module by ${MODULE_ARN_...} and ARIA by ${ARIA_AGENT_V2_ARN}. Import the modules and
create ARIA v2 first, write their ARNs into config.json and run:  python3 build_flows.py --config config.json

    python3 build_flows.py                      # writes the files with module placeholders
    python3 build_flows.py --config config.json # writes them with your module ARNs filled in
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ── The resources the live flow uses (unchanged) ─────────────────────────────────────────────────────────────────
INSTANCE = "arn:aws:connect:eu-west-2:395402194296:instance/f969d4b4-f716-4974-a325-bb7899f2f293"
FLOW_MORTGAGE_LIVE_SYNC = f"{INSTANCE}/contact-flow/6788a011-92c9-4616-ac94-1d103811da95"   # Mortgage Live Sync handover
FLOW_CARD_DISPUTE = f"{INSTANCE}/contact-flow/6395dd02-3215-4db1-af9f-c98412eec2f1"         # Card dispute assistant
FLOW_HUMAN_HANDOVER = f"{INSTANCE}/contact-flow/0978883b-6892-41ab-81f4-528e0e0cc9bf"       # ARIA human handover
LAMBDA_SESSION_INJECTOR = "arn:aws:lambda:eu-west-2:395402194296:function:aria-session-injector-qconnect"
LAMBDA_HANDBACK_RECOVERY = "arn:aws:lambda:eu-west-2:395402194296:function:aria-handback-recovery"
LEX_BOT_ALIAS = "arn:aws:lex:eu-west-2:395402194296:bot-alias/5CE3XMSSPB/PAKRDSHDKA"
ASSISTANT = "arn:aws:wisdom:eu-west-2:395402194296:assistant/e6991ed4-e11c-4194-8d20-13889a36bd15"
# ARIA for chats and calls (the Lex block's ai-agent-arn): ARIA v2 from ai-agent/, once create_agent.sh has made it.
# (To compare with live, config.json's "aria" can name my-conversation-agent:38, which has the same tools bar
# QueryAssistant. Not v37: the card Lambdas now need customer_id on blocks, which v37 doesn't send.)
ARIA_VERSION = "${ARIA_AGENT_V2_ARN}"

MODULE_TOKENS = {
    "contact_setup": "${MODULE_ARN_AriaContactSetup}",
    "customer_context": "${MODULE_ARN_AriaCustomerContext}",
    "decide_handback": "${MODULE_ARN_AriaDecideHandback}",
}
LOGGING = "enableLogging"

# ARIA's hand-back fields, copied out of Lex for the decision module (contact attribute ← Lex session attribute)
HANDBACK_FIELDS = {
    "lexTool": "Tool", "lexNextStep": "nextStep", "lexHandoverSummary": "handoverSummary",
    "lexBuyerType": "buyerType", "lexScreenCode": "screenCode", "lexTopicCategory": "topicCategory",
    "lexEscalationReason": "escalationReason", "lexCustomerIntent": "customerIntent",
    "lexConversationSummary": "conversationSummary",
}

# The session injector's results, as the live flow saves them
INJECTOR_ATTRIBUTES = {k: f"$.External.{k}" for k in (
    "sessionId", "customerId", "authStatus", "channel", "preferredName", "productSummary", "productContext",
    "vulnerabilityContext", "priorSummary", "priorChannel", "priorContactId", "priorTranscript", "locale",
    "dateTime", "instanceId")}
INJECTOR_ATTRIBUTES["customerPhone"] = "$.CustomerEndpoint.Address"


# ── Small builders ───────────────────────────────────────────────────────────────────────────────────────────────
def action(identifier, type_, parameters=None, next_action=None, errors=None, conditions=None):
    transitions = {}
    if next_action:
        transitions["NextAction"] = next_action
    if conditions:
        transitions["Conditions"] = [{"NextAction": target, "Condition": {"Operator": "Equals", "Operands": [value]}}
                                     for value, target in conditions]
    if errors:
        transitions["Errors"] = [{"NextAction": target, "ErrorType": kind} for kind, target in errors]
    return {"Identifier": identifier, "Type": type_, "Parameters": parameters or {}, "Transitions": transitions}


def compare(identifier, value, conditions, otherwise):
    return action(identifier, "Compare", {"ComparisonValue": value}, otherwise,
                  [("NoMatchingCondition", otherwise)], conditions)


def set_attributes(identifier, attributes, next_action, on_error):
    return action(identifier, "UpdateContactAttributes", {"Attributes": attributes, "TargetContact": "Current"},
                  next_action, [("NoMatchingError", on_error)])


def transfer(identifier, flow_arn, after):
    return action(identifier, "TransferToFlow", {"ContactFlowId": flow_arn}, after, [("NoMatchingError", after)])


def lambda_call(identifier, arn, next_action, on_error, inputs=None):
    parameters = {"LambdaFunctionARN": arn, "InvocationTimeLimitSeconds": "8", "InvocationType": "SYNCHRONOUS",
                  "ResponseValidation": {"ResponseType": "STRING_MAP"}}
    if inputs:
        parameters["LambdaInvocationAttributes"] = inputs
    return action(identifier, "InvokeLambdaFunction", parameters, next_action, [("NoMatchingError", on_error)])


def logging_on(next_action: str) -> dict:
    """First block of every flow and module: flow logs for everything after it."""
    return action(LOGGING, "UpdateFlowLoggingBehavior", {"FlowLoggingBehavior": "Enabled"}, next_action)


def module_call(identifier, token, next_action, on_error):
    return action(identifier, "InvokeFlowModule", {"FlowModuleId": token}, next_action, [("NoMatchingError", on_error)])


def flow(actions, start, layout, fragments=None):
    """A Flow Language document. layout: {identifier: (column, row)} → positions 260px / 160px apart.

    fragments: {block: its hidden UpdateContactData}. The designer's "Connect assistant" block is
    CreateWisdomSession + an UpdateContactData that saves the session ARN, and "Set voice" is
    UpdateContactTextToSpeechVoice + one that sets the language. The metadata must tie the pair
    together (children, fragments.SetContactData, the same position), as the live flow's does;
    otherwise the designer shows the second half as a "Set contact attributes" block with no
    attributes, and won't publish it.
    """
    fragments = fragments or {}
    positions = {i: {"position": {"x": 260 * c, "y": 160 * r}} for i, (c, r) in layout.items()}
    for parent, child in fragments.items():
        positions[child] = {"position": dict(positions[parent]["position"]), "dynamicParams": []}
        positions[parent].update({"children": [child], "fragments": {"SetContactData": child}})
    missing = [a["Identifier"] for a in actions if a["Identifier"] not in positions]
    if missing:
        raise ValueError(f"no layout for {missing}")
    return {"Version": "2019-10-30", "StartAction": start,
            "Metadata": {"entryPointPosition": {"x": -220, "y": 0}, "ActionMetadata": positions},
            "Actions": actions}


# ── Module: ARIA - Contact setup ─────────────────────────────────────────────────────────────────────────────────
def contact_setup() -> dict:
    voice = {"VoiceBehavior": {
        "VoiceRecordingBehavior": {"RecordedParticipants": ["Agent", "Customer"], "IVRRecordingBehavior": "Enabled"},
        "VoiceAnalyticsBehavior": {
            "Enabled": "True", "AnalyticsLanguage": "en-GB", "AnalyticsModes": ["RealTime", "AutomatedInteraction"],
            "ConversationalAnalyticsRedactionConfiguration": {"Enabled": "False"},
            "SentimentConfiguration": {"Enabled": "True"},
            "SummaryConfiguration": {"SummaryModes": ["PostContact", "AutomatedInteraction"]}}}}
    chat = {"ChatBehavior": {"ChatAnalyticsBehavior": {
        "Enabled": "True", "AnalyticsLanguage": "en-GB", "AnalyticsModes": ["ContactLens"],
        "ConversationalAnalyticsRedactionConfiguration": {"Enabled": "False"},
        "InFlightChatRedactionConfiguration": {"Enabled": "False"},
        "SentimentConfiguration": {"Enabled": "True"},
        "SummaryConfiguration": {"SummaryModes": ["PostContact", "AutomatedInteraction"]}}}}
    actions = [
        logging_on("checkChannel"),
        compare("checkChannel", "$.Channel", [("CHAT", "chatAnalytics")], "voiceRecordingAnalytics"),
        action("voiceRecordingAnalytics", "UpdateContactRecordingAndAnalyticsBehavior", voice, "setVoiceAmy",
               [("NoMatchingError", "setupFailed"), ("ChannelMismatch", "setupFailed")]),
        action("chatAnalytics", "UpdateContactRecordingAndAnalyticsBehavior", chat, "setVoiceAmy",
               [("NoMatchingError", "setupFailed"), ("ChannelMismatch", "setupFailed"),
                ("InFlightRedactionConfigurationFailed", "setupFailed")]),
        action("setVoiceAmy", "UpdateContactTextToSpeechVoice",
               {"TextToSpeechVoice": "Amy", "TextToSpeechEngine": "Generative", "TextToSpeechStyle": "None"},
               "setLanguage", [("NoMatchingError", "setupFailed")]),
        action("setLanguage", "UpdateContactData", {"LanguageCode": "en-GB"}, "done",
               [("NoMatchingError", "setupFailed")]),
        action("done", "EndFlowModuleExecution"),
        action("setupFailed", "DisconnectParticipant"),
    ]
    layout = {LOGGING: (0, 0), "checkChannel": (1, 0), "voiceRecordingAnalytics": (2, 1), "chatAnalytics": (2, -1),
              "setVoiceAmy": (3, 0), "done": (4, 0), "setupFailed": (4, 2)}
    return flow(actions, LOGGING, layout, fragments={"setVoiceAmy": "setLanguage"})


# ── Module: ARIA - Customer context ─────────────────────────────────────────────────────────────────────────────
def customer_context() -> dict:
    """The session injector puts the customer's context into ARIA's session, and this saves it on the contact."""
    actions = [
        logging_on("sessionInjector"),
        lambda_call("sessionInjector", LAMBDA_SESSION_INJECTOR, "saveCustomerContext", "contextFailed"),
        set_attributes("saveCustomerContext", INJECTOR_ATTRIBUTES, "done", "contextFailed"),
        action("done", "EndFlowModuleExecution"),
        action("contextFailed", "DisconnectParticipant"),
    ]
    layout = {LOGGING: (0, 0), "sessionInjector": (1, 0), "saveCustomerContext": (2, 0), "done": (3, 0),
              "contextFailed": (2, 2)}
    return flow(actions, LOGGING, layout)


# ── Module: ARIA - Decide hand-back ──────────────────────────────────────────────────────────────────────────────
def decide_handback() -> dict:
    """Reads handbackOutcome (handback | error) and the aria* hand-back fields; sets handbackRoute and the attributes the
    destination needs, exactly as the live flow's blocks did; returns."""
    a = "$.Attributes."
    actions = [
        logging_on("startAtEnd"),
        set_attributes("startAtEnd", {"handbackRoute": "end"}, "checkOutcome", "checkOutcome"),
        compare("checkOutcome", f"{a}handbackOutcome", [("handback", "checkTool")], "recoverAfterError"),

        # ARIA handed back through Lex: which tool did she use?
        compare("checkTool", f"{a}lexTool", [
            ("Escalate", "escalateToHuman"), ("Complete", "checkNextStep"),
            ("StartMortgageApplication", "checkMortgageForm"), ("StartCardDispute", "disputeFromAria"),
        ], "done"),
        set_attributes("escalateToHuman", {
            "topicCategory": f"{a}lexTopicCategory", "escalationReason": f"{a}lexEscalationReason",
            "customerIntent": f"{a}lexCustomerIntent", "conversationSummary": f"{a}lexConversationSummary",
            "handbackRoute": "human"}, "done", "done"),
        compare("checkNextStep", f"{a}lexNextStep", [
            ("card_dispute", "disputeFromAria"), ("mortgage_application", "checkMortgageForm"),
        ], "recoverAfterComplete"),
        set_attributes("disputeFromAria", {"handoverSummary": f"{a}lexHandoverSummary", "entry": "aria",
                                           "handbackRoute": "card_dispute"}, "done", "routeCardDispute"),
        # From the internet banking app's mortgage form: to the mortgage assistant joined to that form, on any channel
        compare("checkMortgageForm", f"{a}appPage", [("mortgage", "mortgageForm")], "checkChannelForMortgage"),
        compare("checkMortgageFormRecovered", f"{a}appPage", [("mortgage", "mortgageForm")], "checkAuthenticated"),
        set_attributes("mortgageForm", {"entry": "web_widget", "handoverSummary": f"{a}lexHandoverSummary",
                                        "handbackRoute": "mortgage_form"}, "done", "routeHuman"),
        compare("checkChannelForMortgage", "$.Channel",
                [("CHAT", "mortgageByChat"), ("VOICE", "mortgageByPhone")], "done"),
        set_attributes("mortgageByChat", {
            "topicCategory": "mortgage_application", "escalationReason": "mortgage_application_chat",
            "customerIntent": "start_mortgage_application", "conversationSummary": f"{a}lexHandoverSummary",
            "handbackRoute": "human"}, "done", "done"),
        set_attributes("mortgageByPhone", {
            "handoverSummary": f"{a}lexHandoverSummary", "buyerType": f"{a}lexBuyerType",
            "screenCode": f"{a}lexScreenCode", "entry": "phone"}, "checkAuthenticated", "done"),
        compare("checkAuthenticated", f"{a}authStatus", [("authenticated", "mortgageLiveSync")], "done"),
        set_attributes("mortgageLiveSync", {"cliMatched": "true", "handbackRoute": "mortgage_livesync"},
                       "done", "routeHuman"),

        # Connect lost the hand-back (a chat's Lex error, or Complete without its fields on a call): read ARIA's trace
        lambda_call("recoverAfterError", LAMBDA_HANDBACK_RECOVERY, "checkRecovered", "routeRetry"),
        lambda_call("recoverAfterComplete", LAMBDA_HANDBACK_RECOVERY, "checkRecovered", "done",
                    inputs={"whenNothing": "end"}),
        compare("checkRecovered", "$.External.route", [
            ("card_dispute", "routeCardDispute"), ("mortgage_application", "checkMortgageFormRecovered"),
            ("escalate", "routeHuman"), ("end", "done"),
        ], "routeRetry"),

        set_attributes("routeCardDispute", {"handbackRoute": "card_dispute"}, "done", "done"),
        set_attributes("routeHuman", {"handbackRoute": "human"}, "done", "done"),
        set_attributes("routeRetry", {"handbackRoute": "retry"}, "done", "done"),
        action("done", "EndFlowModuleExecution"),
    ]
    layout = {
        LOGGING: (-1, 0), "startAtEnd": (0, 0), "checkOutcome": (1, 0),
        "checkTool": (2, -2), "escalateToHuman": (3, -4), "checkNextStep": (3, -2), "disputeFromAria": (4, -3),
        "checkChannelForMortgage": (4, -1), "mortgageByChat": (5, -2), "mortgageByPhone": (5, -1),
        "checkAuthenticated": (6, -1), "mortgageLiveSync": (7, -1),
        "checkMortgageForm": (3, 0), "checkMortgageFormRecovered": (6, 1), "mortgageForm": (5, -5),
        "recoverAfterError": (2, 2), "recoverAfterComplete": (4, 1), "checkRecovered": (5, 1),
        "routeCardDispute": (7, -3), "routeHuman": (8, 0), "routeRetry": (7, 2), "done": (9, 0),
    }
    return flow(actions, LOGGING, layout)


# ── Main flow: ARIA conversation bot flow ────────────────────────────────────────────────────────────────────────
# How long Lex waits for the caller to start speaking. ARIA can't say a word until Lex gives her a turn, so on the
# first turn this wait is silence on the line (a call on 19 Oct: 8.6 s of it before she greeted). Lex uses the most
# specific key: "*:*" applies before any intent is running (only the first turn), and the AmazonQinConnect one to
# every turn once ARIA is talking, which keeps the 8 s her silence handling ("I'm still here") is tuned for.
FIRST_TURN_WAIT_MS = "1500"
ARIA_TURN_WAIT_MS = "8000"
ARIA_INTENT = "AmazonQinConnect"          # coversatonalaibot's AMAZON.QInConnectIntent (bot version 3)


def main_flow(modules: dict, aria: str = ARIA_VERSION) -> dict:
    lex = {"Text": " ", "LexV2Bot": {"AliasArn": LEX_BOT_ALIAS},
           "LexSessionAttributes": {
               "x-amz-lex:audio:end-timeout-ms:*:*": "2000", "x-amz-lex:audio:max-length-ms:*:*": "30000",
               "x-amz-lex:audio:start-timeout-ms:*:*": FIRST_TURN_WAIT_MS,
               f"x-amz-lex:audio:start-timeout-ms:{ARIA_INTENT}:*": ARIA_TURN_WAIT_MS,
               "x-amz-lex:q-in-connect:ai-agent-arn": aria},
           "LexTimeoutSeconds": {"Text": "300"}}
    handback = {"handbackOutcome": "handback", **{k: f"$.Lex.SessionAttributes.{v}" for k, v in HANDBACK_FIELDS.items()}}
    actions = [
        logging_on("checkReturned"),
        # Back from the card dispute assistant: Contact setup already ran when the contact first came in, and its
        # failure branch hangs up, so a returning customer skips it
        compare("checkReturned", "$.Attributes.entry", [("returned", "checkAriaStarted")], "contactSetup"),
        module_call("contactSetup", modules["contact_setup"], "checkEntry", "endContact"),

        # Pages that go straight to an assistant (the mortgage form's Point B; a dispute chosen in an older app)
        compare("checkEntry", "$.Attributes.entry",
                [("web_widget", "toMortgageFromForm"), ("card_dispute", "disputeFromPage")], "connectAssistant"),
        # Back to ARIA: her session on this contact goes on (a second Connect assistant block isn't needed); a
        # contact that went straight to the dispute assistant has none yet, so it gets one now
        compare("checkAriaStarted", "$.Attributes.ariaStarted", [("true", "customerContext")], "connectAssistant"),
        transfer("toMortgageFromForm", FLOW_MORTGAGE_LIVE_SYNC, "connectAssistant"),
        set_attributes("disputeFromPage", {"entry": "aria"}, "toCardDispute", "toCardDispute"),

        # ARIA: her Connect assistant session, the customer's context in it, then the conversation
        action("connectAssistant", "CreateWisdomSession", {"WisdomAssistantArn": ASSISTANT}, "saveAssistantSession",
               [("NoMatchingError", "endContact")]),
        action("saveAssistantSession", "UpdateContactData", {"WisdomSessionArn": "$.Wisdom.SessionArn"},
               "markAriaStarted", [("NoMatchingError", "endContact")]),
        set_attributes("markAriaStarted", {"ariaStarted": "true"}, "customerContext", "customerContext"),
        module_call("customerContext", modules["customer_context"], "talkToAria", "endContact"),
        action("talkToAria", "ConnectParticipantWithLexBot", lex, "markLexError", [
            ("InputTimeLimitExceeded", "retryAria"), ("NoMatchingCondition", "saveHandback"),
            ("NoMatchingError", "markLexError")]),
        set_attributes("saveHandback", handback, "decideHandback", "markLexError"),
        set_attributes("markLexError", {"handbackOutcome": "error"}, "decideHandback", "decideHandback"),
        module_call("decideHandback", modules["decide_handback"], "routeHandback", "retryAria"),

        # One destination each
        compare("routeHandback", "$.Attributes.handbackRoute", [
            ("card_dispute", "toCardDispute"), ("mortgage_livesync", "toMortgageFromAria"),
            ("mortgage_form", "toMortgageFormFromAria"),
            ("human", "toHumanHandover"), ("retry", "retryAria"), ("end", "endContact"),
        ], "endContact"),
        transfer("toCardDispute", FLOW_CARD_DISPUTE, "endContact"),
        transfer("toMortgageFromAria", FLOW_MORTGAGE_LIVE_SYNC, "endContact"),
        # The internet banking app's mortgage form: the same flow as Point B (it reads entry=web_widget). If the
        # transfer fails, back to ARIA rather than a second Connect assistant session.
        transfer("toMortgageFormFromAria", FLOW_MORTGAGE_LIVE_SYNC, "retryAria"),
        transfer("toHumanHandover", FLOW_HUMAN_HANDOVER, "endContact"),
        action("retryAria", "Loop", {"LoopCount": "2"}, "endContact", [("NoMatchingError", "endContact")],
               [("ContinueLooping", "talkToAria"), ("DoneLooping", "endContact")]),
        action("endContact", "DisconnectParticipant"),
    ]
    layout = {
        LOGGING: (0, 0), "checkReturned": (0, -2), "contactSetup": (1, 0), "checkEntry": (2, 0),
        "toMortgageFromForm": (3, -2), "disputeFromPage": (3, 2), "checkAriaStarted": (3, -1),
        "connectAssistant": (3, 0), "markAriaStarted": (4, 1), "customerContext": (5, 0), "talkToAria": (6, 0),
        "saveHandback": (7, -1), "markLexError": (7, 1), "decideHandback": (8, 0), "routeHandback": (9, 0),
        "toCardDispute": (10, 2), "toMortgageFromAria": (10, -2), "toHumanHandover": (10, -1),
        "toMortgageFormFromAria": (10, -3),
        "retryAria": (8, 3), "endContact": (11, 1),
    }
    return flow(actions, LOGGING, layout, fragments={"connectAssistant": "saveAssistantSession"})


def build(module_arns: dict | None = None, aria: str = ARIA_VERSION) -> dict:
    """aria: the AI agent version ARIA's chats and calls use (the Lex block's ai-agent-arn): ARIA v2 by default."""
    modules = {**MODULE_TOKENS, **(module_arns or {})}
    return {
        "modules/aria-contact-setup.json": contact_setup(),
        "modules/aria-customer-context.json": customer_context(),
        "modules/aria-decide-handback.json": decide_handback(),
        "flows/aria-conversation-bot-flow.json": main_flow(modules, aria),
    }


def read_config(path) -> tuple[dict, dict]:
    """The filled-in module ARNs and AI agent ARNs from config.json (placeholders are skipped)."""
    config = json.loads(Path(path).read_text())
    cfg = config.get("modules", {})
    arns = {key: cfg[key] for key in MODULE_TOKENS if cfg.get(key) and not cfg[key].startswith("${")}
    agents = {key: config[key] for key in ("aria",) if str(config.get(key, "")).startswith("arn:aws:wisdom:")}
    return arns, agents


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    parser.add_argument("--config", help="config.json with the three module ARNs, once the modules exist")
    args = parser.parse_args()
    arns, agents = read_config(args.config) if args.config else ({}, {})
    for path, document in build(arns, **agents).items():
        target = HERE / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(document, indent=2) + "\n")
        print(f"wrote {path} ({len(document['Actions'])} blocks)")
    if agents:
        print("AI agents: " + ", ".join(f"{k} = {v.rsplit('/', 1)[-1]}" for k, v in agents.items()))
    left = [t for k, t in MODULE_TOKENS.items() if k not in arns] + ([] if agents.get("aria") else [ARIA_VERSION])
    if left:
        print("Still to fill in the main flow: " + ", ".join(left))


if __name__ == "__main__":
    main()
