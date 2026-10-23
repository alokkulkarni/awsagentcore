"""Offline tests for deploy-fresh-instance: nothing here calls AWS.

    python3 -m unittest discover -s deploy-fresh-instance/tests
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE / "py"))

from common import ROOT, State  # noqa: E402
import rebase  # noqa: E402

LIVE = json.loads((PACKAGE / "templates" / "live-map.json").read_text())
CONNECT = json.loads((PACKAGE / "templates" / "connect.json").read_text())
FAKE = "11111111-2222-3333-4444-{:012d}"

COMMITTED = [
    ROOT / "connect-bot-flow-modular/flows/aria-conversation-bot-flow.json",
    ROOT / "connect-bot-flow-modular/flows/mortgage-live-sync-handover.json",
    ROOT / "connect-bot-flow-modular/modules/aria-contact-setup.json",
    ROOT / "connect-bot-flow-modular/modules/aria-customer-context.json",
    ROOT / "connect-bot-flow-modular/modules/aria-decide-handback.json",
    ROOT / "connect-agent-assist/flows/aria-agent-assist-flow.json",
    ROOT / "connect-agent-assist/flows/aria-agent-screen-pop-flow.json",
    PACKAGE / "templates/flows/aria-human-handover.json",
    PACKAGE / "templates/flows/mortgage-live-sync-entry.json",
]


def complete_state(path: Path, region: str = "eu-west-2") -> State:
    """Every key a full run writes, with fake new IDs."""
    s = State(path)
    n = iter(range(1, 1000))
    s.set("REGION", region)
    s.set("ACCOUNT_ID", "999988887777")
    for key in ("INSTANCE_ID", "ASSISTANT_ID", "KB_ASSOC_ID", "HOURS_BASIC", "APP_MONEY_HUB_ID", "GUARDRAIL_ID",
                "ACXD_WORKSPACE_ID", "ACXD_MORTGAGE_APP_ID", "ACXD_DISPUTE_APP_ID"):
        s.set(key, FAKE.format(next(n)))
    s.set("GATEWAY_ID", "aria-banking-mcp-gateway-prod-newgateway1")
    s.set("GUARDRAIL_VERSION", "1")
    s.set("LEX_BOT_ALIAS_PATH", "NEWBOT0001/NEWALIAS01")
    s.set("ACXD_MORTGAGE_ALIAS", "NewMortgageAlias000001")
    s.set("ACXD_DISPUTE_ALIAS", "NewDisputeAlias0000001")
    for key in CONNECT["flows"]:
        s.set(f"FLOW_{key.upper()}", FAKE.format(next(n)))
    for key in CONNECT["modules"]:
        s.set(f"MODULE_{key.upper()}", FAKE.format(next(n)))
    s.set("QUEUES_JSON", json.dumps({name: FAKE.format(next(n)) for name in LIVE["queues"]}))
    for key in LIVE["ai_agents"]:
        s.set(f"{key.upper()}_AGENT_ID", FAKE.format(next(n)))
        s.set(f"{key.upper()}_AGENT_VERSION", "1")
    for key in LIVE["ai_prompts"]:
        s.set(f"{key.upper()}_PROMPT_ID", FAKE.format(next(n)))
        s.set(f"{key.upper()}_PROMPT_VERSION", "1")
    return s


class Rebase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = complete_state(Path(self.tmp.name) / "s.env")

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_committed_flow_and_module_moves_onto_the_new_instance_with_nothing_old_left(self):
        for path in COMMITTED:
            out = rebase.rebase_checked(path.read_text(), self.state, path.name)
            json.loads(out)
            self.assertNotIn(LIVE["account"], out, path.name)
            self.assertNotIn(LIVE["instance"], out, path.name)

    def test_aria_v2_moves_its_tools_knowledge_guardrail_and_collaborator(self):
        agent = json.loads((ROOT / "connect-bot-flow-modular/ai-agent/agent/aria-conversation-agent-v2.json").read_text())
        text = json.dumps(agent["configuration"]).replace("${PROMPT_ID_V2}", "p:1")
        out = rebase.rebase_checked(text, self.state, "ARIA v2")
        self.assertIn("gateway_aria-banking-mcp-gateway-prod-newgateway1__aria-banking-account___get_account_balance", out)
        self.assertIn(self.state.get("KB_ASSOC_ID"), out)
        self.assertIn(f"{self.state.get('GUARDRAIL_ID')}:1", out, "id:version becomes the new id:version")
        self.assertIn(self.state.get("APP_MONEY_HUB_ID"), out)

    def test_the_main_flow_names_the_new_aria_version_bot_and_lambdas(self):
        out = rebase.rebase_checked(COMMITTED[0].read_text(), self.state, "main")
        self.assertIn(f"{self.state.get('ARIA_AGENT_ID')}:1", out)
        self.assertIn("bot-alias/NEWBOT0001/NEWALIAS01", out)
        self.assertIn(f"assistant/{self.state.get('ASSISTANT_ID')}", out)
        module = rebase.rebase_checked(COMMITTED[3].read_text(), self.state, "customer context")
        self.assertIn("arn:aws:lambda:eu-west-2:999988887777:function:aria-session-injector-qconnect", module)

    def test_the_mortgage_handover_points_at_the_new_designer_app_and_alias_code(self):
        out = rebase.rebase_checked(COMMITTED[1].read_text(), self.state, "mortgage handover")
        block = next(a for a in json.loads(out)["Actions"] if a["Type"] == "ConnectParticipantWithAgenticCX")
        config = block["Parameters"]["AgentConfiguration"]
        self.assertEqual((config["WorkspaceId"], config["ApplicationId"], config["Alias"]),
                         (self.state.get("ACXD_WORKSPACE_ID"), self.state.get("ACXD_MORTGAGE_APP_ID"), "NewMortgageAlias000001"))

    def test_a_queue_moves_by_name(self):
        out = rebase.rebase_checked(COMMITTED[8].read_text(), self.state, "mortgage entry")
        new = json.loads(self.state.get("QUEUES_JSON"))["Mortgage Advisors"]
        self.assertIn(f"/queue/{new}", out)

    def test_a_missing_new_id_is_named_and_nothing_half_done_comes_back(self):
        self.state.values.pop("ACXD_MORTGAGE_ALIAS")
        with self.assertRaises(rebase.MissingValue) as caught:
            rebase.rebase_checked(COMMITTED[1].read_text(), self.state, "mortgage handover")
        self.assertIn("ACXD_MORTGAGE_ALIAS", str(caught.exception))

    def test_another_region_moves_every_arn(self):
        other = complete_state(Path(self.tmp.name) / "o.env", region="eu-central-1")
        out = rebase.rebase_checked(COMMITTED[0].read_text(), other, "main")
        self.assertNotIn(":eu-west-2:", out)

    def test_leftovers_catches_an_old_id(self):
        self.assertTrue(rebase.leftovers(f'{{"x": "{LIVE["flows"]["main"]}"}}'))


class StateFile(unittest.TestCase):
    def test_values_round_trip_and_the_shell_can_source_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.env"
            s = State(path)
            s.set("QUEUES_JSON", json.dumps({"Bob's queue": "x"}))
            s.set("REGION", "eu-west-2")
            self.assertEqual(State(path).get("QUEUES_JSON"), json.dumps({"Bob's queue": "x"}))
            import subprocess
            got = subprocess.run(["bash", "-c", f"source {path} && printf '%s' \"$QUEUES_JSON\""],
                                 capture_output=True, text=True).stdout
            self.assertEqual(got, json.dumps({"Bob's queue": "x"}))
            self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600", "IDs aren't secret, but the file is yours")

    def test_bad_keys_and_multi_line_values_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = State(Path(tmp) / "s.env")
            with self.assertRaises(ValueError):
                s.set("lower", "x")
            with self.assertRaises(ValueError):
                s.set("OK", "a\nb")


class HelperCommandLine(unittest.TestCase):
    """deploy.sh calls every helper as `helper.py <command> --state FILE <values...>`."""

    def run_cli(self, argv: list[str]) -> list[str]:
        import common
        seen = []
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "s.env"
            State(state).set("REGION", "eu-west-2")
            old = sys.argv
            sys.argv = ["helper.py", *[state.as_posix() if a == "STATE" else a for a in argv]]
            try:
                common.cli("test", {"associate": lambda ctx: seen.extend(ctx.extra),
                                    "put": lambda ctx: seen.extend(ctx.extra)})
            finally:
                sys.argv = old
        return seen

    def test_values_after_the_state_reach_the_command(self):
        self.assertEqual(self.run_cli(["associate", "--state", "STATE", "aria-routing-lookup", "aria-x"]),
                         ["aria-routing-lookup", "aria-x"])
        self.assertEqual(self.run_cli(["put", "--state", "STATE", "aria-card-dispute/touchpoint"]),
                         ["aria-card-dispute/touchpoint"])

    def test_deploy_sh_passes_them_that_way(self):
        text = (PACKAGE / "deploy.sh").read_text()
        self.assertIn('"$PY" "$HERE/py/${helper}.py" "$command" --state "$STATE" "$@"', text)


class Orchestrator(unittest.TestCase):
    TEXT = (PACKAGE / "deploy.sh").read_text()

    def steps(self) -> list[str]:
        block = re.search(r"STEPS=\((.*?)\n\)", self.TEXT, re.S).group(1)
        return [line.strip().strip('"').split("|")[0] for line in block.strip().splitlines()]

    def test_every_step_has_its_function(self):
        for step in self.steps():
            self.assertIn(f"\nstep_{step.replace('-', '_')}() {{", self.TEXT, step)

    def test_dependency_order(self):
        order = {s: i for i, s in enumerate(self.steps())}
        before = [("preflight", "instance"), ("instance", "assistant"), ("assistant", "lex-bot"), ("assistant", "gateway"),
                  ("gateway", "mcp-app"), ("queues", "routing"), ("flow-shells", "money-hub"),
                  ("flow-shells", "mortgage-backend"), ("money-hub-bridge", "money-hub-a2a"),
                  ("card-dispute", "tool-grants"), ("money-hub", "tool-grants"), ("mortgage-backend", "designer-access"),
                  ("web-urls", "designer-apps"), ("card-dispute", "agent-assist-lambda"),
                  ("mortgage-backend", "agent-assist-lambda"), ("money-hub-a2a", "aria-agent"),
                  ("knowledge-base", "aria-agent"), ("guardrail", "aria-agent"), ("tool-grants", "aria-agent"),
                  ("designer-apps", "flows-fill"), ("aria-agent", "flows-fill"), ("assist-agents", "flows-fill"),
                  ("lex-bot", "flows-fill"), ("flows-fill", "phone"), ("flows-fill", "banking-app"),
                  ("banking-app", "smoke")]
        for first, then in before:
            self.assertLess(order[first], order[then], f"{first} must come before {then}")

    # Values a step reads that may rightly be empty (a declined phone number; the summary's display lines).
    OPTIONAL = {"PHONE_NUMBER", "CONNECT_URL", "ADMIN_USER", "BANKING_APP_URL", "MONEY_HUB_URL"}

    def test_every_step_asks_and_checks_its_inputs_before_running(self):
        for body in re.findall(r"(?ms)^step_[a-z0-9_]+\(\) \{\n(.*?)^\}", self.TEXT):
            self.assertIn("go || return 0", body)
            self.assertNotIn("$(need ", body, "a failing $(...) wouldn't stop the command it feeds")
            after = body.split("go || return 0")[1]
            needed = set(re.findall(r"needs ([A-Z_ ]+)", after)[0].split()) if "needs " in after else set()
            for key in set(re.findall(r"\$\(v ([A-Z_]+)\)", after)) - self.OPTIONAL:
                self.assertIn(key, needed, f"{key} is used but not checked first: {body[:70]}")

    def test_secrets_never_go_on_a_command_line(self):
        for name in ("pass", "key", "dkey", "akey", "OLD_KEY"):
            for line in self.TEXT.splitlines():
                if f'"${name}"' in line and "printf" not in line and "ACXD_API_KEY=" not in line and "secret " not in line:
                    self.fail(f"${name} on a command line: {line.strip()}")

    def test_errors_stop_the_run(self):
        self.assertIn("set -Eeuo pipefail", self.TEXT)
        self.assertIn('"step_${id//-/_}"          # a plain call', self.TEXT)


class Templates(unittest.TestCase):
    def test_captured_flows_are_whole(self):
        for name in ("aria-human-handover.json", "mortgage-live-sync-entry.json"):
            flow = json.loads((PACKAGE / "templates/flows" / name).read_text())
            ids = {a["Identifier"] for a in flow["Actions"]}
            self.assertIn(flow["StartAction"], ids)
            for action in flow["Actions"]:
                t = action.get("Transitions", {})
                for target in [t.get("NextAction")] + [x["NextAction"] for x in t.get("Errors", []) + t.get("Conditions", [])]:
                    if target:
                        self.assertIn(target, ids, (name, action["Identifier"]))

    def test_the_map_names_every_flow_and_module_the_deploy_makes(self):
        self.assertEqual(set(CONNECT["flows"]), set(LIVE["flows"]) - {"legacy_conversation_bot_flow"})
        self.assertEqual(set(CONNECT["modules"]), set(LIVE["modules"]))
        for module in CONNECT["modules"].values():
            self.assertTrue((ROOT / module["file"]).exists(), module["file"])


if __name__ == "__main__":
    unittest.main()
