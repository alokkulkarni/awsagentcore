"""
Tests for the Money Hub page API and gateway tools: the three ways in, the link
gate, the page's safety rules. No AWS.
"""

import json
import re
import sys
import unittest
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FOLDER))
sys.path.insert(0, str(FOLDER / "api"))

import money_api as api  # noqa: E402
from moneyhub import data  # noqa: E402
from moneyhub.service import MoneyHub  # noqa: E402
from moneyhub.store import MemoryStore  # noqa: E402

JAMES, SARAH = "CUST-001", "CUST-002"


class Context:
    def __init__(self, tool):
        self.client_context = type("C", (), {"custom": {"bedrockAgentCoreToolName": tool}})()


def http(method, path, body=None):
    return {"requestContext": {"http": {"method": method}}, "rawPath": path,
            "body": json.dumps(body) if body is not None else None}


class Api(unittest.TestCase):

    def setUp(self):
        api.hub = MoneyHub(MemoryStore(lambda: 1_800_000_000.0), lambda: 1_800_000_000.0, page_url="https://hub.example")
        self.token = api.hub.mint_link(JAMES).split("#k=")[1]

    def call(self, path, **body):
        reply = api.lambda_handler(http("POST", path, {"token": self.token, **body}), None)
        return reply["statusCode"], json.loads(reply["body"])

    def test_the_page_and_its_assets_are_served_with_a_strict_policy(self):
        page = api.lambda_handler(http("GET", "/"), None)
        self.assertEqual(page["statusCode"], 200)
        self.assertIn("frame-ancestors 'none'", page["headers"]["content-security-policy"])
        self.assertNotIn("unsafe", page["headers"]["content-security-policy"])
        for asset in ("/assets/app.js", "/assets/styles.css"):
            self.assertEqual(api.lambda_handler(http("GET", asset), None)["statusCode"], 200)
        for missing in ("/assets/../money_api.py", "/assets/secret.txt", "/admin"):
            self.assertEqual(api.lambda_handler(http("GET", missing), None)["statusCode"], 404)

    def test_logos_are_listed_and_served_only_from_the_logos_folder(self):
        import base64
        import tempfile
        saved_dir = api.WEB_DIR
        with tempfile.TemporaryDirectory() as tmp:
            web = Path(tmp)
            (web / "logos").mkdir()
            (web / "logos" / "aldi.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
            (web / "logos" / "just-eat.png").write_bytes(b"\x89PNG fake")
            (web / "logos" / "notes.txt").write_text("not a logo")
            (web / "logos" / "Bad Name.svg").write_text("<svg/>")
            api.WEB_DIR = web
            try:
                self.assertEqual(api.logo_files(), {"aldi": "aldi.svg", "just-eat": "just-eat.png"})
                svg = api.lambda_handler(http("GET", "/assets/logos/aldi.svg"), None)
                self.assertEqual((svg["statusCode"], svg["headers"]["content-type"]), (200, "image/svg+xml"))
                png = api.lambda_handler(http("GET", "/assets/logos/just-eat.png"), None)
                self.assertTrue(png["isBase64Encoded"])
                self.assertEqual(base64.b64decode(png["body"]), b"\x89PNG fake")
                for bad in ("/assets/logos/notes.txt", "/assets/logos/../index.html", "/assets/logos/missing.svg",
                            "/assets/logos/Bad%20Name.svg"):
                    self.assertEqual(api.lambda_handler(http("GET", bad), None)["statusCode"], 404, bad)
            finally:
                api.WEB_DIR = saved_dir

    def test_the_page_gets_each_goal_with_its_plan(self):
        api.hub.save_goal(JAMES, "Car", 10000, "2027-07")
        status, view = self.call("/api/hub")
        goal = view["goals"][0]
        self.assertEqual((goal["name"], goal["plan"]["targetDateWords"]), ("Car", "July 2027"))
        self.assertIn("reachedWithMix", goal["plan"])
        self.assertLessEqual(len(goal["plan"]["changes"]), 4)
        self.assertIn("logos", view)

    def test_every_call_needs_a_live_link_and_only_sees_that_customer(self):
        status, view = self.call("/api/hub")
        self.assertEqual(status, 200)
        self.assertEqual(view["overview"]["balance"], data.generate(JAMES)[-1]["balanceAfter"])
        reply = api.lambda_handler(http("POST", "/api/hub", {"token": "made-up", "customerId": SARAH}), None)
        self.assertEqual(reply["statusCode"], 403)
        reply = api.lambda_handler(http("POST", "/api/hub", {"customerId": SARAH}), None)
        self.assertEqual(reply["statusCode"], 403, "naming a customer in the body does nothing")

    def test_transactions_page_and_filter(self):
        status, listed = self.call("/api/transactions", direction="in")
        self.assertEqual(status, 200)
        self.assertTrue(all(t["amount"] > 0 for t in listed["transactions"]))
        _, coffee = self.call("/api/transactions", category="coffee", page=2)
        self.assertEqual(coffee["page"], 2)

    def test_recategorise_and_goals_over_http(self):
        tx = next(t for t in data.generate(JAMES) if t["category"] == "takeaways")
        status, moved = self.call("/api/recategorise", transactionId=tx["transactionId"], category="eating_out")
        self.assertEqual((status, moved["transaction"]["category"]), (200, "eating_out"))
        status, refused = self.call("/api/recategorise", transactionId=tx["transactionId"], category="salary")
        self.assertEqual((status, refused["error"]), (400, "wrong_direction"))
        status, goal = self.call("/api/goal", name="Holiday", target=1500, byDate="2027-08-01")
        self.assertEqual((status, goal["goal"]["name"]), (200, "Holiday"))
        status, bad = self.call("/api/goal", name="Holiday", target="lots", byDate="2027-08-01")
        self.assertEqual((status, bad["error"]), (400, "bad_request"))
        self.assertEqual(self.call("/api/goal/delete", name="holiday")[1]["goals"], [])

    def test_oversized_and_malformed_bodies_are_refused(self):
        huge = {**http("POST", "/api/hub"), "body": "x" * 5000}
        self.assertEqual(api.lambda_handler(huge, None)["statusCode"], 413)
        broken = {**http("POST", "/api/hub"), "body": "{nope"}
        self.assertEqual(api.lambda_handler(broken, None)["statusCode"], 400)

    def test_gateway_tools_are_read_only_facts(self):
        summary = api.lambda_handler({"customer_id": JAMES}, Context("aria-money-hub___get_money_hub_summary"))
        self.assertIn("essentialPerMonth", summary)
        forecast = api.lambda_handler({"jsonrpc": "2.0", "params": {"name": "x___get_money_hub_forecast",
                                                                    "arguments": {"customer_id": JAMES}}}, None)
        self.assertEqual(len(forecast["months"]), 3)
        self.assertEqual(api.lambda_handler({"customer_id": JAMES}, Context("x___recategorise"))["error"], "unknown_tool")

    def test_a_tool_call_can_never_mint_a_page_link(self):
        ask = {"operation": "mint_link", "customerId": JAMES}
        for reply in (api.lambda_handler(dict(ask), Context("x___get_money_hub_summary")),
                      api.lambda_handler({**ask, "jsonrpc": "2.0"}, None)):
            self.assertNotIn("link", reply)
        self.assertTrue(api.lambda_handler(dict(ask), None)["link"].startswith("https://hub.example/#k="))
        self.assertEqual(api.lambda_handler({"operation": "mint_link", "customerId": "CUST-999"}, None)["error"],
                         "customer_not_found")

    def test_the_page_has_no_inline_script_and_writes_text_not_html(self):
        html = (FOLDER / "web" / "index.html").read_text()
        self.assertEqual(re.findall(r"<script(?![^>]*\bsrc=)", html), [])
        self.assertNotRegex(html, r"\son[a-z]+=")
        self.assertNotIn("style=", html)
        script = (FOLDER / "web" / "app.js").read_text()
        for unsafe in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
            self.assertNotIn(unsafe, script)
        self.assertIn("history.replaceState", script, "the link's secret is wiped from the address bar")

    def test_logs_carry_no_token_or_content(self):
        with self.assertLogs(level="INFO") as logs:
            self.call("/api/goal", name="SECRET-GOAL-NAME", target=999, byDate="2027-08-01")
            api.lambda_handler(http("POST", "/api/hub", {"token": "GUESSED"}), None)
        written = "\n".join(logs.output)
        for private in (self.token, "SECRET-GOAL-NAME", "GUESSED", JAMES):
            self.assertNotIn(private, written)


if __name__ == "__main__":
    unittest.main()
