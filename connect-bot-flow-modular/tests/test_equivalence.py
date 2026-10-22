"""
The modular flow does exactly what the live flow does.

A small interpreter runs Amazon Connect Flow Language (the blocks these flows use, with modules), and every scenario
is run twice: through reference/conversation-bot-flow-live.json (the live flow, as read from Connect) and through
flows/ + modules/. Each run ends in a transfer (to which flow) or a disconnect, with the contact attributes the
destination reads, after some number of ARIA turns. Both must match for every scenario.

Scenarios cover: chat and voice; every entry (mortgage form, dispute page, Money Hub, banking app, none); signed in or
not; ARIA timing out, erroring, or handing back with each tool and nextStep; the recovery Lambda answering each
route, nothing, something unexpected, or failing; and a failure injected at each block that can fail.
"""

import itertools
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import build_flows  # noqa: E402

LIVE = json.loads((HERE / "reference" / "conversation-bot-flow-live.json").read_text())
# What the destinations read (the lex* and handback* working attributes are the new flow's own bookkeeping)
COMPARED = ("entry", "handoverSummary", "buyerType", "screenCode", "cliMatched", "topicCategory",
            "escalationReason", "customerIntent", "conversationSummary")
INJECTED = {"sessionId": "sess-1", "customerId": "CUST-001", "authStatus": "", "channel": "",
            "preferredName": "James", "productSummary": "p", "productContext": "{}", "vulnerabilityContext": "",
            "priorSummary": "", "priorChannel": "", "priorContactId": "", "priorTranscript": "", "locale": "en-GB",
            "dateTime": "now", "instanceId": "i"}


class Contact:
    def __init__(self, channel, entry, auth, lex_turns, recoveries, fail):
        self.channel, self.fail = channel, set(fail)
        self.attributes = {"entry": entry} if entry else {}
        self.auth = auth
        self.lex_turns, self.recoveries = list(lex_turns), list(recoveries)
        self.lex = {}
        self.turns = 0
        self.loops = {}


def resolve(value, contact, external):
    if not isinstance(value, str) or not value.startswith("$."):
        return value
    if value == "$.Channel":
        return contact.channel
    if value == "$.CustomerEndpoint.Address":
        return "+447700900000"
    if value.startswith("$.Attributes."):
        return contact.attributes.get(value.split(".", 2)[2], "")
    if value.startswith("$.Lex.SessionAttributes."):
        return contact.lex.get(value.split(".", 3)[3], "")
    if value.startswith("$.External."):
        return external.get(value.split(".", 2)[2], "")
    return ""


def failure_key(a):
    """A name for this block that means the same in both flows, so one failure can be injected into each."""
    p, t = a.get("Parameters") or {}, a["Type"]
    if t == "UpdateContactRecordingAndAnalyticsBehavior":
        return "recording"
    if t == "UpdateContactTextToSpeechVoice":
        return "voice"
    if t == "UpdateContactData":
        return "language" if "LanguageCode" in p else ("session1" if "_first_" in str(p) else "session")
    if t == "CreateWisdomSession":
        # Live has two Connect assistant blocks: before the injector (with an agent-assistance setting) and again
        # before ARIA. The modular flow has one, before the customer context: it plays the first one's part.
        return "assistant1" if "OrchestrationAIAgentConfiguration" in p or a["Identifier"] == "connectAssistant" else "assistant2"
    if t == "InvokeLambdaFunction":
        return "injector" if "injector" in p["LambdaFunctionARN"] else "recovery-lambda"
    if t == "TransferToFlow":
        return "transfer:" + p["ContactFlowId"].rsplit("/", 1)[-1][:8]
    if t == "UpdateContactAttributes":
        keys = sorted(k for k in p["Attributes"] if not k.startswith(("lex", "handback")))
        return "set:" + ",".join(keys) if keys else None
    return None


def run(document, contact, modules=None, external=None, depth=0):
    """Run one flow (or module) until it disconnects, transfers or returns. Returns (outcome, flow id) or None."""
    actions = {a["Identifier"]: a for a in document["Actions"]}
    external = {} if external is None else external          # a module has its own External namespace
    current, steps = document["StartAction"], 0
    while True:
        steps += 1
        assert steps < 500, "the flow is going round in circles"
        a = actions[current]
        t, p, tr = a["Type"], a.get("Parameters") or {}, a.get("Transitions") or {}
        errors = {e["ErrorType"]: e["NextAction"] for e in tr.get("Errors", [])}
        failed = failure_key(a) in contact.fail

        def err(kind="NoMatchingError"):
            return errors.get(kind) or errors["NoMatchingError"]

        if t == "DisconnectParticipant":
            return ("disconnect", None)
        if t == "EndFlowModuleExecution":
            return None
        if t == "TransferToFlow":
            if failed:
                current = err(); continue
            return ("transfer", p["ContactFlowId"].rsplit("/", 1)[-1][:8])
        if t == "Compare":
            value = resolve(p["ComparisonValue"], contact, external)
            match = next((c["NextAction"] for c in tr.get("Conditions", []) if c["Condition"]["Operands"][0] == value), None)
            current = match or errors.get("NoMatchingCondition") or tr["NextAction"]; continue
        if t == "UpdateContactAttributes":
            if failed:
                current = err(); continue
            for k, v in p["Attributes"].items():
                contact.attributes[k] = resolve(v, contact, external)
            current = tr["NextAction"]; continue
        if t == "InvokeLambdaFunction":
            if "injector" in p["LambdaFunctionARN"]:
                if failed:
                    current = err(); continue
                external.clear(); external.update({**INJECTED, "authStatus": contact.auth})
            else:
                answer = contact.recoveries.pop(0) if contact.recoveries else "none"
                if answer == "fail":
                    current = err(); continue
                when_nothing = (p.get("LambdaInvocationAttributes") or {}).get("whenNothing")
                external.clear(); external["route"] = ("end" if when_nothing == "end" else "none") if answer == "none" else answer
            current = tr["NextAction"]; continue
        if t == "ConnectParticipantWithLexBot":
            contact.turns += 1
            turn = contact.lex_turns.pop(0) if contact.lex_turns else ("timeout", {})
            kind, contact.lex = turn[0], dict(turn[1])
            current = {"timeout": errors["InputTimeLimitExceeded"], "handback": errors["NoMatchingCondition"],
                       "error": errors["NoMatchingError"]}[kind]; continue
        if t == "Loop":
            count = contact.loops.get(current, 0)
            if count < int(p["LoopCount"]):
                contact.loops[current] = count + 1
                current = next(c["NextAction"] for c in tr["Conditions"] if c["Condition"]["Operands"] == ["ContinueLooping"])
            else:
                current = next(c["NextAction"] for c in tr["Conditions"] if c["Condition"]["Operands"] == ["DoneLooping"])
            continue
        if t == "InvokeFlowModule":
            result = run(modules[p["FlowModuleId"]], contact, modules, {}, depth + 1)
            if result is not None:
                return result                                    # the module ended the contact
            current = tr["NextAction"]; continue
        # Logging, recording, voice, language, assistant, session data: they only fail when told to
        if failed:
            current = err(); continue
        current = tr["NextAction"]


def outcome(document, modules, scenario):
    contact = Contact(*scenario)
    result = run(document, contact, modules)
    return result, {k: contact.attributes.get(k, "") for k in COMPARED}, contact.turns


NEW = build_flows.build()
MODULES = {build_flows.MODULE_TOKENS[k]: NEW[f"modules/aria-{k.replace('_', '-')}.json"] for k in build_flows.MODULE_TOKENS}
MAIN = NEW["flows/aria-conversation-bot-flow.json"]

HANDBACKS = {
    "escalate": {"Tool": "Escalate", "topicCategory": "credit_card", "escalationReason": "customer_requested",
                 "customerIntent": "talk to someone", "conversationSummary": "Wants a person."},
    "complete-dispute": {"Tool": "Complete", "nextStep": "card_dispute", "handoverSummary": "M&S £65."},
    "complete-mortgage": {"Tool": "Complete", "nextStep": "mortgage_application", "handoverSummary": "FTB.",
                          "buyerType": "first_time", "screenCode": "303567"},
    "complete-bare": {"Tool": "Complete"},
    "start-dispute": {"Tool": "StartCardDispute", "handoverSummary": "Unknown payment."},
    "start-mortgage": {"Tool": "StartMortgageApplication", "handoverSummary": "Remortgage.", "buyerType": "remortgage"},
    "unknown-tool": {"Tool": "SomethingElse"},
}
RECOVERIES = ["card_dispute", "mortgage_application", "escalate", "end", "none", "weird", "fail"]
# (No "assistant2": the live flow's second, duplicate Connect assistant block isn't in the modular flow.)
FAILURES = ["", "recording", "voice", "language", "assistant1", "session", "injector",
            "transfer:6788a011", "transfer:6395dd02", "transfer:0978883b", "set:entry", "set:cliMatched",
            "set:conversationSummary,customerIntent,escalationReason,topicCategory", "set:entry,handoverSummary",
            "set:buyerType,entry,handoverSummary,screenCode"]


def scenarios():
    entries = ["web_widget", "card_dispute", "money_hub", "banking_app", ""]
    turns = [[("timeout", {})] * 4, [("error", {}), ("error", {}), ("error", {})]]
    turns += [[("handback", h)] for h in HANDBACKS.values()]
    turns += [[("error", {}), ("handback", HANDBACKS["complete-dispute"])],
              [("timeout", {}), ("handback", HANDBACKS["escalate"])]]
    for channel, entry, auth, lex, recovery, fail in itertools.product(
            ["CHAT", "VOICE"], entries, ["authenticated", "unauthenticated"], turns, RECOVERIES, FAILURES):
        yield channel, entry, auth, lex, [recovery, recovery, recovery], [fail] if fail else []


class TheModularFlowMatchesTheLiveOne(unittest.TestCase):

    def test_every_scenario_ends_the_same_way(self):
        checked, differences = 0, []
        for scenario in scenarios():
            live = outcome(LIVE, {}, scenario)
            new = outcome(MAIN, MODULES, scenario)
            checked += 1
            if live != new:
                differences.append((scenario, live, new))
        self.assertEqual(differences[:3], [], f"{len(differences)} of {checked} scenarios differ")
        self.assertGreater(checked, 10000)

    def test_the_scenarios_reach_every_destination(self):
        seen = {outcome(MAIN, MODULES, s)[0] for s in itertools.islice(scenarios(), 0, None, 7)}
        for expected in (("transfer", "6788a011"), ("transfer", "6395dd02"), ("transfer", "0978883b"),
                         ("disconnect", None)):
            self.assertIn(expected, seen)

    def test_spot_checks(self):
        dispute = outcome(MAIN, MODULES, ("CHAT", "banking_app", "authenticated",
                                          [("error", {})], ["card_dispute"], []))
        self.assertEqual(dispute[0], ("transfer", "6395dd02"))
        mortgage = outcome(MAIN, MODULES, ("VOICE", "money_hub", "authenticated",
                                           [("handback", HANDBACKS["complete-mortgage"])], [], []))
        self.assertEqual((mortgage[0], mortgage[1]["screenCode"], mortgage[1]["cliMatched"]),
                         (("transfer", "6788a011"), "303567", "true"))
        point_b = outcome(MAIN, MODULES, ("CHAT", "web_widget", "authenticated", [], [], []))
        self.assertEqual((point_b[0], point_b[2]), (("transfer", "6788a011"), 0))


class TheNewWaysIn(unittest.TestCase):
    """Added 20 Oct 2026, so not in the live flow: back to ARIA from the card dispute assistant, and the internet
    banking app's mortgage form starting with ARIA."""

    def run_contact(self, channel, attributes, turns, recoveries=(), fail=()):
        contact = Contact(channel, "", "authenticated", turns, list(recoveries), list(fail))
        contact.attributes.update(attributes)
        return run(MAIN, contact, MODULES), contact

    def test_a_new_contact_marks_that_aria_has_her_session(self):
        _, contact = self.run_contact("CHAT", {"entry": "banking_app"}, [("handback", HANDBACKS["escalate"])])
        self.assertEqual(contact.attributes["ariaStarted"], "true")

    def test_back_from_the_dispute_assistant_aria_carries_on_without_a_second_session(self):
        back = {"entry": "returned", "returnedFrom": "card_dispute", "ariaStarted": "true"}
        # A failing Connect assistant block would end the contact: reaching ARIA proves the block is skipped.
        result, contact = self.run_contact("CHAT", back, [("handback", HANDBACKS["escalate"])], fail=["assistant1"])
        self.assertEqual((result, contact.turns), (("transfer", "0978883b"), 1))
        result, contact = self.run_contact("VOICE", back, [("handback", HANDBACKS["complete-bare"])], ["end"],
                                           fail=["assistant1"])
        self.assertEqual((result, contact.turns), (("disconnect", None), 1))

    def test_back_from_the_dispute_assistant_skips_contact_setup(self):
        back = {"entry": "returned", "returnedFrom": "card_dispute", "ariaStarted": "true"}
        # Contact setup's failure branch hangs up: a returning customer must never run it again.
        for fail in ("recording", "voice", "language"):
            result, contact = self.run_contact("CHAT", back, [("handback", HANDBACKS["escalate"])], fail=[fail])
            self.assertEqual((result, contact.turns), (("transfer", "0978883b"), 1), fail)

    def test_back_on_a_chat_goes_straight_to_aria_s_usual_block(self):
        # The designer's Import drops "Initialize bot with message"; the banking app's widget gives ARIA the note instead.
        self.assertNotIn("LexInitializationData", json.dumps(MAIN))
        blocks = {a["Identifier"]: a for a in MAIN["Actions"]}
        self.assertEqual(blocks["customerContext"]["Transitions"]["NextAction"], "talkToAria")

    def test_back_without_an_aria_session_yet_gets_one_first(self):
        back = {"entry": "returned", "returnedFrom": "card_dispute"}
        self.assertEqual(self.run_contact("CHAT", back, [], fail=["assistant1"])[0], ("disconnect", None))
        result, contact = self.run_contact("CHAT", back, [("handback", HANDBACKS["escalate"])])
        self.assertEqual((result, contact.turns, contact.attributes["ariaStarted"]), (("transfer", "0978883b"), 1, "true"))

    def test_the_apps_mortgage_form_goes_through_aria_to_the_form_on_chat_and_calls(self):
        form = {"entry": "banking_app", "appPage": "mortgage", "applicationId": "MA-ABCDEFGH", "stage": "about_you"}
        for channel in ("CHAT", "VOICE"):
            for handback in ("start-mortgage", "complete-mortgage"):
                result, contact = self.run_contact(channel, form, [("handback", HANDBACKS[handback])])
                self.assertEqual(result, ("transfer", "6788a011"), (channel, handback))
                self.assertEqual((contact.attributes["entry"], contact.attributes["applicationId"]),
                                 ("web_widget", "MA-ABCDEFGH"), "the mortgage flow reads the form's own attributes")
                self.assertEqual(contact.attributes["handoverSummary"], HANDBACKS[handback]["handoverSummary"])
                self.assertNotIn("cliMatched", contact.attributes, "not the phone path")
        # Connect lost the hand-back: the recovery Lambda's answer still reaches the form.
        result, contact = self.run_contact("CHAT", form, [("error", {})], ["mortgage_application"])
        self.assertEqual((result, contact.attributes["entry"]), (("transfer", "6788a011"), "web_widget"))

    def test_aria_escalating_a_colleague_needed_return_gives_the_adviser_the_specialist_s_full_notes(self):
        notes = "Card dispute DSP-VBTXDRJK drafted. STARBUCKS, £4.77 on 2026-10-14; charged the wrong amount. " * 8
        back = {"entry": "returned", "returnedFrom": "card_dispute", "returnIntent": "escalate", "ariaStarted": "true",
                "returnSummary": notes, "disputeId": "DSP-VBTXDRJK"}
        result, contact = self.run_contact("CHAT", back, [("handback", HANDBACKS["escalate"])])
        self.assertEqual(result, ("transfer", "0978883b"))
        self.assertEqual(contact.attributes["conversationSummary"], notes, "not ARIA's 500-character summary")
        self.assertEqual(contact.attributes["escalationReason"], "customer_requested", "ARIA's decision stands")
        self.assertEqual(contact.attributes["disputeId"], "DSP-VBTXDRJK")
        # On chat ARIA's hand-back errors and the recovery Lambda decides: the notes still win.
        result, contact = self.run_contact("CHAT", back, [("error", {})], ["escalate"])
        self.assertEqual((result, contact.attributes["conversationSummary"]), (("transfer", "0978883b"), notes))

    def test_a_mortgage_colleague_needed_keeps_the_topic_the_screen_pop_opens_the_application_for(self):
        back = {"entry": "returned", "returnedFrom": "mortgage", "returnIntent": "escalate", "ariaStarted": "true",
                "returnSummary": "Wants advice on which product.", "applicationId": "MA-ABCDEFGH"}
        _, contact = self.run_contact("VOICE", back, [("handback", HANDBACKS["escalate"])])
        self.assertEqual((contact.attributes["topicCategory"], contact.attributes["applicationId"]),
                         ("mortgage_application", "MA-ABCDEFGH"))

    def test_a_return_to_help_never_borrows_old_notes(self):
        back = {"entry": "returned", "returnedFrom": "card_dispute", "returnIntent": "help", "ariaStarted": "true",
                "returnSummary": "Wants a joint account."}
        _, contact = self.run_contact("CHAT", back, [("handback", HANDBACKS["escalate"])])
        self.assertEqual(contact.attributes["conversationSummary"], HANDBACKS["escalate"]["conversationSummary"])

    def test_a_failed_transfer_to_the_form_goes_back_to_aria(self):
        form = {"entry": "banking_app", "appPage": "mortgage"}
        result, contact = self.run_contact("CHAT", form, [("handback", HANDBACKS["start-mortgage"]),
                                                          ("handback", HANDBACKS["escalate"])],
                                           fail=["transfer:6788a011"])
        self.assertEqual((result, contact.turns), (("transfer", "0978883b"), 2))


class TheFilesAreImportable(unittest.TestCase):
    def test_structure(self):
        for path, document in NEW.items():
            ids = [a["Identifier"] for a in document["Actions"]]
            self.assertEqual(len(ids), len(set(ids)), path)
            self.assertIn(document["StartAction"], ids, path)
            self.assertEqual(set(ids), set(document["Metadata"]["ActionMetadata"]), path)
            for a in document["Actions"]:
                tr = a.get("Transitions") or {}
                targets = [tr.get("NextAction")] + [e["NextAction"] for e in tr.get("Errors", [])] + \
                          [c["NextAction"] for c in tr.get("Conditions", [])]
                for target in filter(None, targets):
                    self.assertIn(target, ids, f"{path}: {a['Identifier']} → {target}")
                if a["Type"] not in ("DisconnectParticipant", "EndFlowModuleExecution", "TransferToFlow"):
                    self.assertTrue(tr.get("NextAction"), f"{path}: {a['Identifier']} has no way on")
                if a["Type"] not in ("DisconnectParticipant", "EndFlowModuleExecution", "Compare",
                                     "UpdateFlowLoggingBehavior"):
                    self.assertIn("NoMatchingError", [e["ErrorType"] for e in tr.get("Errors", [])],
                                  f"{path}: {a['Identifier']}")
                self.assertLessEqual(len(a["Identifier"]), 50)

    def test_the_written_files_are_what_the_builder_makes(self):
        # The files are written either with placeholders (build_flows.py) or with the real ARNs
        # (build_flows.py --config config.json). Either is fine; anything else is a stale file.
        arns, agents = build_flows.read_config(HERE / "config.json")
        filled = build_flows.build(arns, **agents)
        for path, document in NEW.items():
            written = json.loads((HERE / path).read_text())
            self.assertIn(written, (document, filled[path]),
                          f"{path}: stale. Run python3 build_flows.py --config config.json")

    def test_hidden_contact_data_blocks_are_tied_to_their_designer_block(self):
        # Every UpdateContactData must be the hidden half of the block before it, as in the live
        # flow; on its own the designer shows it as an empty "Set contact attributes" and won't publish.
        for path, document in NEW.items():
            meta = document["Metadata"]["ActionMetadata"]
            for a in document["Actions"]:
                if a["Type"] != "UpdateContactData":
                    continue
                parents = [p for p in document["Actions"] if p["Transitions"].get("NextAction") == a["Identifier"]]
                self.assertEqual(len(parents), 1, f"{path}: {a['Identifier']}")
                parent = parents[0]
                self.assertIn(parent["Type"], ("CreateWisdomSession", "UpdateContactTextToSpeechVoice"), path)
                self.assertEqual(meta[parent["Identifier"]].get("fragments"), {"SetContactData": a["Identifier"]}, path)
                self.assertEqual(meta[parent["Identifier"]].get("children"), [a["Identifier"]], path)
                self.assertEqual(meta[a["Identifier"]]["position"], meta[parent["Identifier"]]["position"], path)

    def test_the_main_flow_never_uses_the_live_aria(self):
        written = (HERE / "flows/aria-conversation-bot-flow.json").read_text()
        self.assertNotIn("68179bd0-78d7-4298-8696-b3817a93b6c2", written)   # my-conversation-agent
        aria = build_flows.read_config(HERE / "config.json")[1].get("aria")
        if aria and aria in written:
            self.assertNotIn("${ARIA_AGENT_V2_ARN}", written)

    def test_every_flow_and_module_switches_logging_on_first(self):
        for path, document in NEW.items():
            first = next(a for a in document["Actions"] if a["Identifier"] == document["StartAction"])
            self.assertEqual((first["Type"], first["Parameters"]), ("UpdateFlowLoggingBehavior", {"FlowLoggingBehavior": "Enabled"}), path)

    def test_recording_and_analytics_are_set_for_both_channels(self):
        setup = NEW["modules/aria-contact-setup.json"]
        behaviours = [a["Parameters"] for a in setup["Actions"] if a["Type"] == "UpdateContactRecordingAndAnalyticsBehavior"]
        voice = next(b["VoiceBehavior"] for b in behaviours if "VoiceBehavior" in b)
        chat = next(b["ChatBehavior"] for b in behaviours if "ChatBehavior" in b)
        self.assertEqual(voice["VoiceRecordingBehavior"]["IVRRecordingBehavior"], "Enabled")
        self.assertIn("AutomatedInteraction", voice["VoiceAnalyticsBehavior"]["AnalyticsModes"])
        self.assertEqual(chat["ChatAnalyticsBehavior"]["Enabled"], "True")
        for b in (voice["VoiceAnalyticsBehavior"], chat["ChatAnalyticsBehavior"]):
            self.assertIn("AutomatedInteraction", b["SummaryConfiguration"]["SummaryModes"])

    def test_aria_is_v2_and_agent_assist_is_left_to_its_own_flow(self):
        text = json.dumps(NEW)
        self.assertNotIn("AgentAssistance", text)
        self.assertEqual(sum(a["Type"] == "CreateWisdomSession" for d in NEW.values() for a in d["Actions"]), 1)
        lex = next(a for a in MAIN["Actions"] if a["Type"] == "ConnectParticipantWithLexBot")
        self.assertEqual(lex["Parameters"]["LexSessionAttributes"]["x-amz-lex:q-in-connect:ai-agent-arn"], "${ARIA_AGENT_V2_ARN}")
        waits = {k: v for k, v in lex["Parameters"]["LexSessionAttributes"].items() if "start-timeout" in k}
        self.assertEqual(waits, {"x-amz-lex:audio:start-timeout-ms:*:*": "1500",
                                 "x-amz-lex:audio:start-timeout-ms:AmazonQinConnect:*": "8000"},
                         "a short wait before ARIA's first turn, the usual 8 s once she's talking")

    def test_modules_never_read_the_calling_flows_lex_or_external_attributes(self):
        for name in ("aria-contact-setup", "aria-customer-context", "aria-decide-handback"):
            module = NEW[f"modules/{name}.json"]
            text = json.dumps(module)
            self.assertNotIn("$.Lex.", text, name)
            lambdas = [a for a in module["Actions"] if a["Type"] == "InvokeLambdaFunction"]
            if "$.External." in text:
                self.assertTrue(lambdas, f"{name} reads External without calling its own Lambda")


if __name__ == "__main__":
    unittest.main()
