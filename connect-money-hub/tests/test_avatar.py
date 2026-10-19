"""
Tests for the face on a call (Tavus): the private room the page Lambda opens and
closes, who may get one, what the browser is allowed to load, and that the key
never leaves the server. No AWS, no Tavus.
"""

import io
import json
import logging
import os
import sys
import unittest
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[1]
for extra in ("", "api", "scripts"):
    sys.path.insert(0, str(FOLDER / extra) if extra else str(FOLDER))

import money_api as api  # noqa: E402
from moneyhub import avatar  # noqa: E402
from moneyhub.service import MoneyHub  # noqa: E402
from moneyhub.store import MemoryStore  # noqa: E402
from test_talk import FakeConnect, http  # noqa: E402

JAMES = "CUST-001"
NOW = 1_800_000_000.0
KEY = "tavus-test-key"
ROOM = {"conversation_id": "c123abc", "conversation_url": "https://tavus.daily.co/c123abc",
        "meeting_token": "jwt-1", "status": "active"}


class FakeTavus:
    """Answers avatar.py's requests, and records them."""

    def __init__(self, reply=None, fail=""):
        self.requests, self.reply, self.fail = [], reply, fail

    def __call__(self, request):
        self.requests.append(request)
        if self.fail:
            raise avatar.AvatarError(self.fail)
        return self.reply


class TavusRooms(unittest.TestCase):

    def test_a_room_is_private_short_lived_and_asked_for_with_the_key(self):
        tavus = FakeTavus(ROOM)
        got = avatar.start(KEY, "face-1", "pal-1", send=tavus)
        self.assertEqual(got, {"conversationId": "c123abc", "conversationUrl": "https://tavus.daily.co/c123abc",
                               "meetingToken": "jwt-1"})
        request = tavus.requests[0]
        self.assertEqual((request.get_method(), request.full_url), ("POST", "https://tavusapi.com/v2/conversations"))
        self.assertEqual(request.get_header("X-api-key"), KEY)
        body = json.loads(request.data)
        self.assertEqual((body["face_id"], body["pal_id"]), ("face-1", "pal-1"))
        self.assertTrue(body["require_auth"], "a private room: joining needs its meeting token")
        self.assertNotIn("test_mode", body)
        self.assertEqual(body["properties"], {"max_call_duration": 1800, "participant_absent_timeout": 60,
                                              "participant_left_timeout": 10})

    def test_a_test_room_checks_the_settings_without_the_face_joining(self):
        tavus = FakeTavus({"conversation_id": "c999", "status": "ended"})
        self.assertEqual(avatar.start(KEY, "f", "p", test=True, send=tavus)["conversationId"], "c999")
        self.assertTrue(json.loads(tavus.requests[0].data)["test_mode"])

    def test_a_room_without_a_token_or_settings_is_an_error_that_never_carries_the_key(self):
        for key, face, pal, tavus in ((KEY, "f", "p", FakeTavus({"conversation_id": "c1", "conversation_url": "https://x"})),
                                      ("", "f", "p", FakeTavus(ROOM)), (KEY, "", "p", FakeTavus(ROOM)),
                                      (KEY, "f", "", FakeTavus(ROOM))):
            with self.assertRaises(avatar.AvatarError) as caught:
                avatar.start(key, face, pal, send=tavus)
            self.assertNotIn(KEY, str(caught.exception))

    def test_ending_closes_the_room_and_an_already_ended_room_is_fine(self):
        tavus = FakeTavus({})
        avatar.end(KEY, "c123abc", send=tavus)
        self.assertEqual(tavus.requests[0].full_url, "https://tavusapi.com/v2/conversations/c123abc/end")
        avatar.end(KEY, "c123abc", send=FakeTavus(fail="tavus http 400"))
        with self.assertRaises(avatar.AvatarError):
            avatar.end(KEY, "../other", send=FakeTavus({}))

    def test_the_pal_only_echoes(self):
        tavus = FakeTavus({"pal_id": "p5e6a7"})
        self.assertEqual(avatar.create_echo_pal(KEY, "face-1", send=tavus), "p5e6a7")
        body = json.loads(tavus.requests[0].data)
        self.assertEqual((body["pipeline_mode"], body["default_face_id"]), ("echo", "face-1"))
        self.assertNotIn("system_prompt", body, "no language model: the face can only repeat the call")


class AvatarRoute(unittest.TestCase):

    def setUp(self):
        api.hub = MoneyHub(MemoryStore(lambda: NOW), lambda: NOW, page_url="https://hub.example")
        api.CONNECT_INSTANCE_ID, api.CONTACT_FLOW_ID = "inst-1", "flow-1"
        api.TAVUS_FACE_ID, api.TAVUS_PAL_ID = "face-1", "pal-1"
        os.environ["TAVUS_API_KEY"] = KEY
        api._connect = FakeConnect()
        self.started, self.ended = [], []
        self.real = avatar.start, avatar.end
        api.avatar.start = lambda key, face, pal: self.started.append((key, face, pal)) or {
            "conversationId": "c123abc", "conversationUrl": ROOM["conversation_url"], "meetingToken": "jwt-1"}
        api.avatar.end = lambda key, conversation_id: self.ended.append((key, conversation_id))
        self.link = api.hub.mint_link(JAMES, "2").split("#k=")[1]
        self.other = api.hub.mint_link(JAMES).split("#k=")[1]

    def tearDown(self):
        api.avatar.start, api.avatar.end = self.real
        api.CONNECT_INSTANCE_ID = api.CONTACT_FLOW_ID = api.TAVUS_FACE_ID = api.TAVUS_PAL_ID = ""
        os.environ.pop("TAVUS_API_KEY", None)
        api._connect = None

    def post(self, path, **body):
        reply = api.lambda_handler(http(path, body), None)
        return reply["statusCode"], json.loads(reply["body"])

    def test_a_call_this_link_started_gets_a_room_and_the_browser_never_sees_the_key(self):
        self.post("/api/contact/call", token=self.link, view="out")
        status, reply = self.post("/api/contact/avatar", token=self.link, contactId="c-1")
        self.assertEqual(status, 200)
        self.assertEqual((reply["conversationId"], reply["meetingToken"]), ("c123abc", "jwt-1"))
        self.assertEqual(self.started, [(KEY, "face-1", "pal-1")])
        self.assertNotIn(KEY, json.dumps(reply))
        self.assertTrue(self.post("/api/hub", token=self.link)[1]["avatar"])

    def test_only_the_link_that_opened_a_room_can_close_it(self):
        self.post("/api/contact/call", token=self.link, view="out")
        self.post("/api/contact/avatar", token=self.link, contactId="c-1")
        self.assertEqual(self.post("/api/contact/avatar/end", token=self.other, conversationId="c123abc")[0], 404)
        self.assertEqual(self.post("/api/contact/avatar/end", token=self.link, conversationId="c-other")[0], 404)
        self.assertEqual(self.ended, [])
        self.assertEqual(self.post("/api/contact/avatar/end", token=self.link, conversationId="c123abc"),
                         (200, {"ended": True}))
        self.assertEqual(self.ended, [(KEY, "c123abc")])

    def test_a_call_started_after_a_room_keeps_the_room_closable(self):
        self.post("/api/contact/call", token=self.link, view="out")
        self.post("/api/contact/avatar", token=self.link, contactId="c-1")
        self.post("/api/contact/chat", token=self.link, view="out")          # remembering a new contact
        self.assertEqual(self.post("/api/contact/avatar/end", token=self.link, conversationId="c123abc")[0], 200)

    def test_no_room_for_a_call_another_link_started_or_no_call_at_all(self):
        self.post("/api/contact/call", token=self.link, view="out")
        for token, contact_id in ((self.other, "c-1"), (self.link, "c-other"), (self.link, "")):
            self.assertEqual(self.post("/api/contact/avatar", token=token, contactId=contact_id)[0], 404)
        self.assertEqual(self.post("/api/contact/avatar", token="made-up", contactId="c-1")[0], 403)
        self.assertEqual(self.started, [], "Tavus was never asked: no minutes spent for them")

    def test_without_a_face_pal_or_key_there_is_no_face_and_calls_stay_voice_only(self):
        self.post("/api/contact/call", token=self.link, view="out")
        for name in ("TAVUS_FACE_ID", "TAVUS_PAL_ID"):
            setattr(api, name, "")
            self.assertFalse(self.post("/api/hub", token=self.link)[1]["avatar"])
            status, reply = self.post("/api/contact/avatar", token=self.link, contactId="c-1")
            self.assertEqual((status, reply["error"]), (503, "avatar_unavailable"))
            setattr(api, name, "face-1" if name == "TAVUS_FACE_ID" else "pal-1")

    def test_a_tavus_failure_is_a_plain_message_and_logs_no_key(self):
        self.post("/api/contact/call", token=self.link, view="out")

        def refuse(key, face, pal):
            raise avatar.AvatarError("tavus http 401")
        api.avatar.start = refuse
        logs = io.StringIO()
        handler = logging.StreamHandler(logs)
        logging.getLogger().addHandler(handler)
        try:
            status, reply = self.post("/api/contact/avatar", token=self.link, contactId="c-1")
        finally:
            logging.getLogger().removeHandler(handler)
        self.assertEqual((status, reply["error"]), (502, "avatar_failed"))
        self.assertIn("carries on", reply["message"])
        self.assertIn("tavus http 401", logs.getvalue())
        self.assertNotIn(KEY, logs.getvalue())


class PageAndBuild(unittest.TestCase):

    def get(self, path):
        return api.lambda_handler({"requestContext": {"http": {"method": "GET"}}, "rawPath": path}, None)

    def test_the_policy_lets_daily_in_and_nothing_inline(self):
        policy = self.get("/")["headers"]["content-security-policy"]
        self.assertIn("script-src 'self' https://*.daily.co https://*.dailywebrtc.com https://*.dailywebrtc.net;", policy)
        for needed in ("wss://*.daily.co", "wss://*.dailywebrtc.com"):
            self.assertIn(needed, policy)
        self.assertNotIn("unsafe", policy)
        self.assertNotIn("blob:;", policy.split("script-src")[1].split(";")[0] + ";",
                         "the audio worklet is served from the page, not a blob")
        for asset in ("avatar.js", "pcm-worklet.js"):
            self.assertEqual(self.get(f"/assets/{asset}")["statusCode"], 200)

    def test_the_face_never_breaks_the_call_never_listens_and_keeps_nothing(self):
        source = (FOLDER / "web" / "avatar.js").read_text()
        for banned in ("innerHTML", "localStorage", "sessionStorage", "TAVUS_API_KEY", "getUserMedia"):
            self.assertNotIn(banned, source)
        self.assertIn("audioSource: false, videoSource: false", source, "no camera or microphone of its own")
        self.assertIn("event_type: 'conversation.echo'", source)
        stop = source[source.index("function stop("):]
        self.assertLess(stop.index("callAudio.muted = false"), stop.index("call.leave()"),
                        "the call's own voice comes back first")
        self.assertIn("/contact/avatar/end", stop, "the room is closed, so it stops counting minutes")
        talk = (FOLDER / "web" / "talk.js").read_text()
        self.assertIn("if (audioContext) videoOn();", talk, "the face starts after the call, alongside it")
        self.assertIn("said.withPerson", talk, "an adviser is never shown through the AI face")
        page = (FOLDER / "web" / "index.html").read_text()
        self.assertIn('class="avatar-badge">AI assistant<', page, "the face is always labelled as AI")

    def test_the_key_lives_in_env_and_secrets_manager_only(self):
        ignored = (FOLDER.parent / ".gitignore").read_text().splitlines()
        self.assertIn(".env", ignored)
        self.assertIn("!.env.example", ignored)
        example = (FOLDER / ".env.example").read_text()
        for name in ("TAVUS_API_KEY", "TAVUS_FACE_ID", "TAVUS_PAL_ID"):
            self.assertIn(f"{name}=\n", example)
        deploy = (FOLDER / "scripts" / "deploy_money_hub.sh").read_text()
        self.assertIn('--secret-string "file://$BUILD/tavus-key.txt"', deploy, "never on a command line")
        self.assertIn("umask 077", deploy)
        self.assertIn('rm -f "$BUILD/tavus-key.txt"', deploy)
        self.assertNotIn("TAVUS_API_KEY=", deploy.split("write_env()")[1].split("\n")[0],
                         "the key is never a Lambda setting")
        build = (FOLDER / "scripts" / "build_chime.sh").read_text()
        self.assertIn("daily-entry.js", build)

    def test_the_local_preview_reads_env_as_data(self):
        import local_preview
        sample = FOLDER / "build" / "test.env"
        sample.parent.mkdir(exist_ok=True)
        sample.write_text("# comment\nTAVUS_API_KEY='abc'\n\nTAVUS_FACE_ID = face-9\nNOT A LINE\n")
        try:
            self.assertEqual(local_preview.read_env(sample), {"TAVUS_API_KEY": "abc", "TAVUS_FACE_ID": "face-9"})
            self.assertEqual(local_preview.read_env(FOLDER / "build" / "missing.env"), {})
        finally:
            sample.unlink()

    def test_check_avatar_saves_only_the_pal_id_and_keeps_the_rest_of_env(self):
        import check_avatar
        sample = FOLDER / "build" / "pal.env"
        sample.write_text("# keep\nTAVUS_API_KEY=k\nTAVUS_PAL_ID=\nOTHER=1\n")
        real, check_avatar.ENV_FILE = check_avatar.ENV_FILE, sample
        try:
            check_avatar.save_pal_id("p123456")
            self.assertEqual(sample.read_text(), "# keep\nTAVUS_API_KEY=k\nTAVUS_PAL_ID=p123456\nOTHER=1\n")
        finally:
            check_avatar.ENV_FILE = real
            sample.unlink()


if __name__ == "__main__":
    unittest.main()
