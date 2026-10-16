"""
Tests for the Connect A2A bridge, using events shaped like the AWS samples
("A2A sample events", A.1 to A.10). No AWS: Connect, the secret and the agent
are stand-ins.
"""

import json
import sys
import unittest
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FOLDER))
sys.path.insert(0, str(FOLDER / "bridge"))

import a2a_bridge as bridge  # noqa: E402
import protocol  # noqa: E402
from moneyhub.store import MemoryStore  # noqa: E402

EXT = "https://docs.aws.amazon.com/connect/a2a/ext/v1"
CONTACT = "0a1b2c3d-1111-2222-3333-444455556666"
ARN = f"arn:aws:connect:eu-west-2:395402194296:instance/f969d4b4/contact/{CONTACT}"
VERIFIED = {"customerId": "CUST-001", "authStatus": "authenticated", "preferredName": "James", "channel": "VOICE"}
TRACEPARENT = "00-550e8400e29b41d4a716446655440000-1111222233334444-01"
TRACESTATE = "connect=parentSpanId:6ba7b810-9dad-11d1-80b4-00c04fd430c8"


def send(message_parts, metadata=None, context="ctx-1", rid="1"):
    return {"jsonrpc": "2.0", "method": "SendMessage", "id": rid, "params": {"message": {
        "messageId": f"m-{rid}", "contextId": context, "role": "ROLE_USER", "parts": message_parts,
        "metadata": metadata or {}}}}


def init_session(history=None, finish=("COMPLETE", "ESCALATE"), context="ctx-1", tracing=True):
    return send([{"data": {"initSession": {"instanceArn": "arn:aws:connect:eu-west-2:1:instance/x", "contactArn": ARN,
                                           "supportedFinishTypes": list(finish), "subscribeToTracingEvents": tracing,
                                           "history": history or []}}, "mediaType": "application/json"}],
                {f"{EXT}/eventType": "INIT_SESSION"}, context)


def channel_ready(context="ctx-1"):
    return send([{"data": {"channelState": {"state": "READY"}}, "mediaType": "application/json"}],
                {f"{EXT}/eventType": "CHANNEL_STATE"}, context, "cs-1")


def turn(text, context="ctx-1", rid="req-1"):
    return send([{"text": text, "mediaType": "text/plain"}], {}, context, rid)


class Bridge(unittest.TestCase):

    def setUp(self):
        self.calls = []
        self.attributes = dict(VERIFIED)
        bridge.store = MemoryStore(lambda: 1_800_000_000.0)
        bridge.api_key = lambda: "the-key"
        bridge.contact_attributes = lambda contact: self.attributes if contact == CONTACT else {}
        self.answer = {"reply": "You spent £312.40 on eating out and takeaways last month.", "finish": None,
                       "model": "eu.anthropic.claude-haiku-5-5", "usage": {"input": 900, "output": 60},
                       "startNs": 1715000000000000000, "endNs": 1715000002000000000,
                       "tools": [{"name": "spending_by_category", "input": "{\"period\":\"last_month\"}",
                                  "output": "{...}", "startNs": 1715000000500000000, "endNs": 1715000000900000000}]}
        bridge.invoke_agent = lambda payload, session: self.calls.append((payload, session)) or dict(self.answer)

    def post(self, body, key="the-key", headers=None):
        event = {"requestContext": {"http": {"method": "POST"}}, "rawPath": "/",
                 "headers": {"Authorization": f"Bearer {key}", "A2A-Extensions": EXT, "traceparent": TRACEPARENT,
                             "tracestate": TRACESTATE, **(headers or {})}, "body": json.dumps(body)}
        reply = bridge.lambda_handler(event, None)
        return reply["statusCode"], json.loads(reply["body"]), reply["headers"]

    def start(self, **kw):
        self.post(init_session(**kw))
        self.post(channel_ready(kw.get("context", "ctx-1")))

    def test_the_key_is_checked_on_every_request(self):
        self.assertEqual(self.post(init_session(), key="wrong")[0], 401)
        self.assertEqual(self.post(init_session(), key="")[0], 401)
        bridge.api_key = lambda: ""
        self.assertEqual(self.post(init_session())[0], 503, "not set up: refuse rather than accept anything")

    def test_a_failed_key_read_is_not_remembered(self):
        import importlib
        import os
        import types
        real = importlib.reload(bridge)            # the real api_key, not setUp's stand-in
        calls = []

        class Secrets:
            def get_secret_value(self, SecretId):
                calls.append(SecretId)
                if len(calls) == 1:
                    raise RuntimeError("AccessDeniedException: Access to KMS is not allowed")
                return {"SecretString": "the-key"}

        fake_boto3 = types.SimpleNamespace(client=lambda name: Secrets())
        saved = sys.modules.get("boto3")
        sys.modules["boto3"] = fake_boto3
        os.environ["API_KEY_SECRET_ID"] = "test/secret"
        try:
            self.assertEqual(real.api_key(), "", "the first read fails (new permissions not there yet)")
            self.assertEqual(real.api_key(), "the-key", "the next request tries again rather than reusing the failure")
            self.assertEqual(real.api_key(), "the-key")
            self.assertEqual(len(calls), 2, "a good key is kept")
        finally:
            os.environ.pop("API_KEY_SECRET_ID", None)
            if saved is None:
                sys.modules.pop("boto3", None)
            else:
                sys.modules["boto3"] = saved
            real._secret_cache.clear()

    def test_init_session_is_answered_like_sample_a2(self):
        status, body, headers = self.post(init_session())
        self.assertEqual((status, body["id"]), (200, "1"))
        message = body["result"]["message"]
        self.assertEqual((message["role"], message["contextId"]), ("ROLE_AGENT", "ctx-1"))
        self.assertEqual(message["parts"][0]["data"], {"initSessionResponse": {"statusCode": "200"}})
        self.assertEqual(message["metadata"][f"{EXT}/eventType"], "INIT_SESSION_RESPONSE")
        self.assertIn(EXT, message["extensions"])
        self.assertEqual(headers["a2a-extensions"], EXT, "the extension header is echoed")

    def test_a_turn_returns_the_reply_its_trace_and_a_completed_status(self):
        self.start()
        _, body, _ = self.post(turn("How much did I spend eating out last month?"))
        task = body["result"]["task"]
        self.assertEqual((body["id"], task["contextId"], task["status"]["state"]), ("req-1", "ctx-1", "TASK_STATE_COMPLETED"))
        text, trace = task["artifacts"]
        self.assertEqual(text["parts"][0]["text"], self.answer["reply"])
        self.assertEqual(text["metadata"][f"{EXT}/eventType"], "TEXT_RESPONSE_CHUNK")
        self.assertEqual(trace["metadata"][f"{EXT}/eventType"], "TRACING_SPAN")
        self.assertNotIn("message", task["status"], "a normal turn doesn't hand back")
        payload, session = self.calls[0]
        self.assertEqual((payload["customerId"], payload["channel"], payload["firstName"]), ("CUST-001", "VOICE", "James"))
        self.assertGreaterEqual(len(session), 33, "AgentCore needs a 33+ character session ID")

    def test_the_trace_adopts_connects_context_and_names_spans_the_genai_way(self):
        self.start()
        _, body, _ = self.post(turn("What did I spend?"))
        spans = body["result"]["task"]["artifacts"][1]["parts"][0]["data"]["tracingSpan"]["otlp"]["resourceSpans"][0][
            "scopeSpans"][0]["spans"]
        root = spans[0]
        self.assertEqual((root["traceId"], root["parentSpanId"]), ("550e8400e29b41d4a716446655440000", "6ba7b8109dad11d1"))
        self.assertEqual((root["name"], root["kind"]), ("invoke_agent money-hub-agent", 2))
        roles = [next(a["value"]["stringValue"] for a in e["attributes"] if a["key"] == "aws.connect.span.message.role")
                 for e in root["events"]]
        self.assertEqual(roles, ["input", "output"])
        names = [s["name"] for s in spans]
        self.assertIn("execute_tool spending_by_category", names)
        self.assertTrue(any(n.startswith("chat ") for n in names))
        for s in spans:
            for field in ("traceId", "spanId", "name", "startTimeUnixNano", "endTimeUnixNano"):
                self.assertIn(field, s)
            self.assertEqual(s["traceId"], root["traceId"], "one trace per turn")

    def test_when_the_agent_is_done_it_hands_back_with_finish(self):
        self.start()
        self.answer["finish"] = {"type": "COMPLETE", "reason": "Explained grocery spending; customer has no more questions."}
        _, body, _ = self.post(turn("Thanks, that's all"))
        status = body["result"]["task"]["status"]
        self.assertEqual(status["state"], "TASK_STATE_COMPLETED")
        self.assertEqual(status["message"]["parts"][0]["data"]["finish"]["type"], "COMPLETE")
        self.assertEqual(status["message"]["metadata"][f"{EXT}/eventType"], "FINISH")

    def test_only_finish_types_connect_offered_are_sent(self):
        self.start(finish=("COMPLETE",))
        self.answer["finish"] = {"type": "ESCALATE", "reason": "wants a person"}
        _, body, _ = self.post(turn("Let me speak to someone"))
        self.assertNotIn("message", body["result"]["task"]["status"])

    def test_an_unverified_customer_is_handed_back_without_the_agent_running(self):
        self.attributes = {"customerId": "CUST-001", "authStatus": "unauthenticated"}
        self.start()
        _, body, _ = self.post(turn("Show me my spending"))
        status = body["result"]["task"]["status"]
        self.assertEqual(status["message"]["parts"][0]["data"]["finish"]["type"], "COMPLETE")
        self.assertIn("not verified", status["message"]["parts"][0]["data"]["finish"]["reason"])
        self.assertEqual(self.calls, [], "no data is read for an unverified customer")

    def test_on_chat_silence_gets_a_gentle_reprompt_without_calling_the_agent(self):
        self.attributes = {**VERIFIED, "channel": "CHAT"}
        self.start()
        _, body, _ = self.post(turn("<EMPTY_USER_INPUT>"))
        self.assertIn("still there", body["result"]["task"]["artifacts"][0]["parts"][0]["text"])
        self.assertEqual(self.calls, [])

    def test_on_a_call_one_silence_says_nothing_and_a_second_in_a_row_reprompts(self):
        self.attributes = {**VERIFIED, "channel": "VOICE"}
        self.start()
        self.post(turn("Where does my money go?"))
        self.assertEqual(len(self.calls), 1)
        for rid, expected in (("s1", None), ("s2", "Are you still there?"), ("s3", None)):
            _, body, _ = self.post(turn("", rid=rid))
            task = body["result"]["task"]
            texts = [p["text"] for a in task["artifacts"] if a["metadata"][f"{EXT}/eventType"] == "TEXT_RESPONSE_CHUNK"
                     for p in a["parts"]]
            self.assertEqual(task["status"]["state"], "TASK_STATE_COMPLETED")
            self.assertTrue(texts, "Connect needs text on every turn: a turn without it errors the bot block")
            if expected:
                self.assertTrue(texts[0].startswith(expected), "the second silence in a row re-prompts")
            else:
                self.assertEqual(texts, ["Take your time."], "a short, easy reply to a pause")
            self.assertTrue(any(a["metadata"][f"{EXT}/eventType"] == "TRACING_SPAN" for a in task["artifacts"]),
                            "every turn still carries its trace")
        self.assertEqual(len(self.calls), 1, "silence never reaches the agent")
        self.post(turn(protocol.EMPTY_INPUT, rid="s4"))
        self.post(turn("And next month?", rid="t2"))
        history = [t["text"] for t in self.calls[-1][0]["history"]]
        self.assertNotIn("", history)
        self.assertNotIn(protocol.EMPTY_INPUT, history, "silences aren't part of the conversation the agent sees")

    def test_a_sentence_split_by_a_pause_is_answered_as_one(self):
        said = "can you revise that goal and put the realistic figure I can save each month"
        history = [{"messageId": "h1", "role": "ROLE_AGENT", "parts": [{"text": "Your Car goal is saved."}]},
                   {"messageId": "h2", "role": "ROLE_USER", "parts": [{"text": said}]},
                   {"messageId": "h3", "role": "ROLE_USER", "parts": [{"text": "to reach the goal"}]}]
        self.attributes = {**VERIFIED, "channel": "VOICE"}
        self.post(init_session(history=history))
        self.post(channel_ready("ctx-1"))
        self.post(turn("to reach the goal"))
        payload = self.calls[-1][0]
        self.assertEqual(payload["input"], f"{said} to reach the goal")
        self.assertEqual(payload["history"][-1], {"role": "assistant", "text": "Your Car goal is saved."},
                         "the agent's history ends with its last answer, not the pieces again")

    def test_a_normal_turn_is_not_doubled(self):
        bridge_ = bridge
        history = [{"role": "assistant", "text": "About £3,158 a month."}, {"role": "user", "text": "And next month?"}]
        self.assertEqual(bridge_.with_unanswered(history, "And next month?"),
                         ([{"role": "assistant", "text": "About £3,158 a month."}], "And next month?"))
        self.assertEqual(bridge_.with_unanswered([], "Hello"), ([], "Hello"))
        self.assertEqual(bridge_.with_unanswered([{"role": "user", "text": "first"}], "second"), ([], "first second"),
                         "an unanswered piece is never lost")

    def test_handed_over_before_the_customer_spoke_the_agent_starts_with_their_tab(self):
        self.attributes = {**VERIFIED, "channel": "VOICE", "entry": "money_hub", "moneyHubView": "expected", "LoA": "2"}
        self.start()
        _, body, _ = self.post(turn(""))
        self.assertEqual(self.calls[-1][0]["input"],
                         "I'm on my Money Hub page, on the Expected tab, and I'd like some help understanding my money.")
        self.post(turn("", rid="s2"))
        self.assertEqual(len(self.calls), 1, "only the first empty turn starts the agent; later ones are pauses")

    def test_silence_carries_across_connects_per_turn_sessions(self):
        self.attributes = {**VERIFIED, "channel": "VOICE"}
        self.start()
        self.post(turn("Where does my money go?"))
        self.post(init_session(history=[{"messageId": "h1", "role": "ROLE_USER", "parts": [{"text": ""}]}]))
        _, body, _ = self.post(turn("", rid="s1"))
        texts = [p["text"] for a in body["result"]["task"]["artifacts"]
                 if a["metadata"][f"{EXT}/eventType"] == "TEXT_RESPONSE_CHUNK" for p in a["parts"]]
        self.assertEqual(texts, ["Take your time."], "the count carried over, so not the re-prompt yet")

    def test_silence_while_an_answer_is_on_its_way_waits_and_says_next_to_nothing(self):
        self.attributes = {**VERIFIED, "channel": "VOICE"}
        self.start()
        key = bridge._session_key("ctx-1")
        session = bridge.store.get(key)
        bridge.store.put(key, {**session, "inflight": {"id": "t1", "at": bridge.store.clock()}})
        waits = []

        def finish_the_answer(_):            # the real turn finishes while the silence waits
            waits.append(1)
            current = bridge.store.get(key)
            current.pop("inflight", None)
            bridge.store.put(key, {**current, "lastAnswer": {"id": "t1", "reply": "About £3,158 a month.",
                                                            "finish": None}})
        bridge.sleep = finish_the_answer
        try:
            self.post(init_session())                # Connect restarts the session for the silence turn
            _, body, _ = self.post(turn("", rid="s1"))
        finally:
            bridge.sleep = __import__("time").sleep
        texts = [p["text"] for a in body["result"]["task"]["artifacts"]
                 if a["metadata"][f"{EXT}/eventType"] == "TEXT_RESPONSE_CHUNK" for p in a["parts"]]
        self.assertEqual(texts, ["."], "Connect speaks every reply: the answer comes once, from its own turn")
        self.assertEqual(waits, [1])
        self.assertEqual(self.calls, [], "the agent isn't asked twice")

    def test_the_conversation_is_kept_and_chat_history_from_connect_is_the_record(self):
        self.start()
        self.post(turn("first question", rid="r1"))
        self.post(turn("second question", rid="r2"))
        second_history = self.calls[1][0]["history"]
        self.assertEqual([h["text"] for h in second_history][:2], ["first question", self.answer["reply"]])
        chat_history = [{"messageId": "h-1", "role": "ROLE_USER", "parts": [{"text": "hello", "mediaType": "text/plain"}]},
                        {"messageId": "h-2", "role": "ROLE_AGENT", "parts": [{"text": "hi James", "mediaType": "text/plain"}]}]
        self.post(init_session(history=chat_history))
        self.post(turn("third", rid="r3"))
        self.assertEqual(self.calls[2][0]["history"], [{"role": "user", "text": "hello"}, {"role": "assistant", "text": "hi James"}])

    def test_a_failing_agent_fails_the_task_with_a_structured_error(self):
        self.start()
        bridge.invoke_agent = lambda payload, session: (_ for _ in ()).throw(RuntimeError("runtime down"))
        _, body, _ = self.post(turn("anything"))
        status = body["result"]["task"]["status"]
        self.assertEqual(status["state"], "TASK_STATE_FAILED")
        error = status["message"]["parts"][0]["data"]["error"]
        self.assertEqual((error["errorCode"], error["errorCategory"]), (424, "DEPENDENCY_FAILURE"))

    def test_events_that_need_no_answer_are_acknowledged(self):
        self.post(init_session())
        for kind, data in (("CHANNEL_STATE", {"channelState": {"state": "READY"}}),
                           ("INTERRUPTION", {"interruption": {"type": "USER_AUDIO_INPUT", "reason": "user_speech"}}),
                           ("DTMF_INPUT_COMPLETE", {"dtmfInputComplete": {"inputString": "1", "terminationReason": "TIMEOUT"}})):
            _, body, _ = self.post(send([{"data": data, "mediaType": "application/json"}], {f"{EXT}/eventType": kind}))
            self.assertEqual(body["result"]["message"]["metadata"][f"{EXT}/eventType"], kind)

    def test_requests_it_cannot_dispatch_get_json_rpc_errors_with_error_info(self):
        _, body, _ = self.post({"jsonrpc": "2.0", "id": "9", "method": "DeleteEverything", "params": {}})
        self.assertEqual(body["error"]["code"], -32601)
        self.assertEqual(body["error"]["data"][0]["@type"], "type.googleapis.com/google.rpc.ErrorInfo")
        _, body, _ = self.post(turn("no session yet", context="unknown"))
        self.assertEqual(body["error"]["data"][0]["reason"], "SESSION_NOT_FOUND")

    def test_poll_mode_answers_working_then_get_task_returns_the_result(self):
        import os
        self.start()
        queued = []
        bridge.invoke_self = queued.append
        os.environ["BRIDGE_MODE"] = "poll"
        try:
            _, body, _ = self.post(turn("What's coming out next month?"))
        finally:
            os.environ.pop("BRIDGE_MODE")
        task_id = body["result"]["task"]["id"]
        self.assertEqual(body["result"]["task"]["status"]["state"], "TASK_STATE_WORKING")
        bridge.lambda_handler(queued[0], None)
        _, done, _ = self.post({"jsonrpc": "2.0", "id": "g1", "method": "GetTask", "params": {"id": task_id, "contextId": "ctx-1"}})
        self.assertEqual(done["result"]["task"]["status"]["state"], "TASK_STATE_COMPLETED")

    def test_the_agent_card_is_public_and_names_the_connect_extension(self):
        reply = bridge.lambda_handler({"requestContext": {"http": {"method": "GET"}},
                                       "rawPath": "/.well-known/agent-card.json", "headers": {}}, None)
        card = json.loads(reply["body"])
        self.assertEqual(card["capabilities"]["extensions"][0]["uri"], EXT)

    def test_logs_carry_no_customer_words_reply_or_key(self):
        with self.assertLogs(level="INFO") as logs:
            self.start()
            self.post(turn("PRIVATE-QUESTION"))
            self.post(turn("x"), key="GUESSED-KEY")
        written = "\n".join(logs.output)
        for private in ("PRIVATE-QUESTION", "£312.40", "the-key", "GUESSED-KEY", "CUST-001", "James"):
            self.assertNotIn(private, written)


class Protocol(unittest.TestCase):

    def test_trace_context_falls_back_and_reads_connects_parent(self):
        trace_id, parent = protocol.trace_context({})
        self.assertEqual((len(trace_id), parent), (32, ""))
        self.assertEqual(protocol.trace_context({"traceparent": TRACEPARENT}),
                         ("550e8400e29b41d4a716446655440000", "1111222233334444"))

    def test_contact_id_and_history_are_read_from_init_session(self):
        self.assertEqual(protocol.contact_id_of(ARN), CONTACT)
        self.assertEqual(protocol.contact_id_of("nonsense"), "")


if __name__ == "__main__":
    unittest.main()
