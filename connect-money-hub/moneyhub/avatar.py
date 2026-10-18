"""
avatar.py
=========
The face on a call from the Money Hub page: a real-looking person, rendered
by Tavus, who speaks ARIA's voice with her face moving in time.

Nothing about the call changes. The browser joins a private Tavus room and
streams the call's own audio into it (what Connect sends to the customer:
ARIA's or the Money Hub agent's voice, never the customer's microphone) as
Tavus "echo" messages. The face repeats that audio exactly, with matching
video, and the browser plays both. If the face can't start, the call carries
on as voice only.

The face's PAL is in echo mode: no speech recognition, no language model and
no voice of its own. It only animates the audio it's given, so it can never
say anything ARIA didn't.

The API key never reaches the browser. The page Lambda creates the
conversation (a private room: joining needs its meeting token) and ends it
when the call ends, and only for a call the same page link started.

Tavus API (https://tavusapi.com/v2, header x-api-key):
    POST /conversations                 {face_id, pal_id, conversation_name, require_auth, properties}
                                        -> {conversation_id, conversation_url, meeting_token, status}
    POST /conversations/{id}/end
    POST /pals                          {pal_name, pipeline_mode: "echo", default_face_id}  -> {pal_id}
    GET  /faces?face_type=system        the stock faces
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

TAVUS_URL = "https://tavusapi.com/v2"
# The longest a face stays on a call (the call carries on without it after that); how long the room waits for the
# browser to join; how soon it closes after the browser leaves (so a closed tab stops the minutes quickly).
MAX_CALL_SECONDS = 30 * 60
ABSENT_SECONDS = 60
LEFT_SECONDS = 10
TIMEOUT_SECONDS = 10
_ID = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


class AvatarError(Exception):
    """Tavus refused or couldn't be reached. Carries no key and no response body."""


def _send(request: urllib.request.Request) -> object:
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:     # noqa: S310 (fixed https host)
            return json.loads(response.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as error:
        raise AvatarError(f"tavus http {error.code}") from None
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise AvatarError(f"tavus unreachable: {type(error).__name__}") from None


def _request(api_key: str, path: str, body: dict | None = None, method: str = "POST") -> urllib.request.Request:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    return urllib.request.Request(f"{TAVUS_URL}{path}", data=data, method=method,
                                  headers={"Content-Type": "application/json", "x-api-key": api_key})


def start(api_key: str, face_id: str, pal_id: str, test: bool = False, send=_send) -> dict:
    """A private room with the face in it: {conversationId, conversationUrl, meetingToken}. test: Tavus's test mode,
    which checks the key, face and PAL without the face joining or any minutes counting (setup checks only).
    send is replaced in tests."""
    if not (api_key and face_id and pal_id):
        raise AvatarError("tavus not configured")
    body = {"face_id": face_id, "pal_id": pal_id, "conversation_name": "Money Hub call", "require_auth": True,
            "properties": {"max_call_duration": MAX_CALL_SECONDS, "participant_absent_timeout": ABSENT_SECONDS,
                           "participant_left_timeout": LEFT_SECONDS}}
    if test:
        body["test_mode"] = True
    reply = send(_request(api_key, "/conversations", body))
    if not isinstance(reply, dict):
        raise AvatarError("tavus gave no conversation")
    conversation_id, url, token = (reply.get(k) for k in ("conversation_id", "conversation_url", "meeting_token"))
    if test and isinstance(conversation_id, str) and _ID.match(conversation_id):
        return {"conversationId": conversation_id, "conversationUrl": "", "meetingToken": ""}
    if not (isinstance(conversation_id, str) and _ID.match(conversation_id) and isinstance(url, str)
            and url.startswith("https://") and isinstance(token, str) and token):
        raise AvatarError("tavus gave no private room")
    return {"conversationId": conversation_id, "conversationUrl": url, "meetingToken": token}


def end(api_key: str, conversation_id: str, send=_send) -> None:
    """Ends the room, so it stops counting minutes. Ending one that has already ended is fine."""
    if not (api_key and _ID.match(conversation_id or "")):
        raise AvatarError("tavus not configured")
    try:
        send(_request(api_key, f"/conversations/{conversation_id}/end"))
    except AvatarError as error:
        if str(error) not in ("tavus http 400", "tavus http 404"):      # already ended, or gone
            raise


def create_echo_pal(api_key: str, face_id: str, send=_send) -> str:
    """A PAL that only animates the audio it's given (setup, once): its pal_id."""
    reply = send(_request(api_key, "/pals", {"pal_name": "Money Hub face (echo)", "pipeline_mode": "echo",
                                             "default_face_id": face_id}))
    pal_id = reply.get("pal_id") if isinstance(reply, dict) else None
    if not (isinstance(pal_id, str) and _ID.match(pal_id)):
        raise AvatarError("tavus gave no pal id")
    return pal_id


def stock_faces(api_key: str, send=_send) -> list[dict]:
    """Tavus's stock faces, newest models first: [{face_id, face_name, model_name}]."""
    reply = send(_request(api_key, "/faces?face_type=system&limit=100", method="GET"))
    rows = reply.get("data") if isinstance(reply, dict) else reply
    faces = [{"face_id": f.get("face_id") or f.get("replica_id"), "face_name": f.get("face_name") or f.get("replica_name"),
              "model_name": f.get("model_name", "")} for f in (rows or []) if isinstance(f, dict)]
    return sorted((f for f in faces if f["face_id"]), key=lambda f: f["model_name"] or "", reverse=True)
