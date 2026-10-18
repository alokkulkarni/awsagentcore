#!/usr/bin/env python3
"""
local_preview.py
================
Runs the Money Hub page on your laptop, with the sample data in memory, so you
can see and click through it before deploying. Without --talk, no AWS is touched.

    python3 connect-money-hub/scripts/local_preview.py [--port 8765] [--customer CUST-001]
                                    [--talk INSTANCE_ID FLOW_ID] [--verified]

It prints a link (with its secret after '#'); open it in a browser. Changes you
make (categories, goals) last until you stop it.

--talk shows the Chat and Call buttons and starts REAL contacts in that Connect
instance and flow, with your AWS credentials (connect:StartChatContact and
connect:StartWebRTCContact). Only that option touches AWS. --verified makes the
link count as Level 2, so ARIA lets the Money Hub agent take over at once.
Calls need web/vendor/chime.js (scripts/build_chime.sh).

With --talk, calls also show the face (Tavus) if connect-money-hub/.env has
TAVUS_API_KEY, TAVUS_FACE_ID and TAVUS_PAL_ID (the key stays in this process;
the browser only gets a private room's address and its meeting token).

--avatar-demo serves /avatar-demo: the call's face speaking a sample of ARIA's
own voice (Amazon Polly, Amy, generative engine: the voice the flow sets), to
judge how real it looks and how well the lips follow, with no call. Making the
sample is one Polly SynthesizeSpeech request with your AWS credentials (it
changes nothing); without them it falls back to the Mac's `say`, which sounds
nothing like Amy. Uses Tavus minutes; Stop on the page ends the room.
"""

import argparse
import base64
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(FOLDER), str(FOLDER / "api")]

import money_api  # noqa: E402
from moneyhub import avatar  # noqa: E402
from moneyhub.service import MoneyHub  # noqa: E402
from moneyhub.store import MemoryStore  # noqa: E402


def read_env(path: Path) -> dict:
    """KEY=VALUE lines from a .env file (comments and blanks skipped, quotes taken off). Never run as a script."""
    found = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key and not key.startswith("#"):
                found[key.strip()] = value.strip().strip('"').strip("'")
    return found


DEMO = FOLDER / "scripts" / "avatar-demo"
DEMO_FILES = {"/avatar-demo": ("avatar-demo.html", "text/html"), "/avatar-demo.js": ("avatar-demo.js", "text/javascript"),
              "/avatar-demo.css": ("avatar-demo.css", "text/css")}
DEMO_WORDS = ("Over the last three months you've had about two hundred and ten pounds left over each month. "
              "Your holiday goal needs two hundred of that until January, so about ten pounds a month is free. "
              "Would you like to see where your money goes?")


def demo_voice() -> Path:
    """A sample for the avatar check, made once: ARIA's voice (Polly Amy, generative) as a 16 kHz WAV, or, without AWS
    credentials, the Mac's `say` as a stand-in."""
    import subprocess
    import wave
    amy = FOLDER / "build" / "avatar-demo-amy.wav"
    if amy.is_file():
        return amy
    amy.parent.mkdir(exist_ok=True)
    raw = amy.with_suffix(".pcm")
    made = subprocess.run(["aws", "polly", "synthesize-speech", "--region", os.environ.get("AWS_REGION", "eu-west-2"),
                           "--engine", "generative", "--voice-id", "Amy", "--output-format", "pcm",
                           "--sample-rate", "16000", "--text", DEMO_WORDS, str(raw)], capture_output=True)
    if made.returncode == 0 and raw.is_file() and raw.stat().st_size:
        with wave.open(str(amy), "wb") as out:          # Polly's PCM is 16-bit mono little-endian
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(16000)
            out.writeframes(raw.read_bytes())
        raw.unlink()
        print("Sample voice: Amazon Polly, Amy (generative), as on the call.", flush=True)
        return amy
    raw.unlink(missing_ok=True)
    print("[WARN] Couldn't make the sample with Amazon Polly (sign in with the AWS CLI); using the Mac's `say`, "
          "which doesn't sound like Amy.", flush=True)
    out = FOLDER / "build" / "avatar-demo.wav"
    if not out.is_file():
        for voice in ("Flo", "Serena", "Kate", "Daniel"):
            done = subprocess.run(["say", "-v", voice, "-o", str(out), "--data-format=LEI16@16000", DEMO_WORDS],
                                  capture_output=True)
            if done.returncode == 0 and out.is_file():
                break
        else:
            sys.exit("--avatar-demo needs the Mac's `say` command to make the sample voice.")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview the Money Hub page locally.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--customer", default="CUST-001")
    parser.add_argument("--talk", nargs=2, metavar=("INSTANCE_ID", "FLOW_ID"))
    parser.add_argument("--verified", action="store_true")
    parser.add_argument("--avatar-demo", action="store_true")
    args = parser.parse_args()
    settings = read_env(FOLDER / ".env")
    face_ready = all(settings.get(k) for k in ("TAVUS_API_KEY", "TAVUS_FACE_ID", "TAVUS_PAL_ID"))
    if args.avatar_demo and not face_ready:
        sys.exit(f"--avatar-demo needs TAVUS_API_KEY, TAVUS_FACE_ID and TAVUS_PAL_ID in {FOLDER / '.env'} "
                 "(scripts/check_avatar.py helps).")
    if args.talk:
        money_api.CONNECT_INSTANCE_ID, money_api.CONTACT_FLOW_ID = args.talk
        if face_ready:
            os.environ["TAVUS_API_KEY"] = settings["TAVUS_API_KEY"]
            money_api.TAVUS_FACE_ID, money_api.TAVUS_PAL_ID = settings["TAVUS_FACE_ID"], settings["TAVUS_PAL_ID"]
            print("Face on: calls show the Tavus face (settings from .env).", flush=True)
    base = f"http://127.0.0.1:{args.port}"
    money_api.hub = MoneyHub(MemoryStore(time.time), time.time, page_url=base)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, headers: dict) -> None:
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _demo(self, method: str) -> bool:
            """The face check's own page, script, sample voice, and its room (only with --avatar-demo)."""
            path = self.path.split("?")[0]
            rooms = ("/api/avatar-demo", "/api/avatar-demo/end")
            if not args.avatar_demo or not (path in DEMO_FILES or path == "/avatar-demo.wav" or path in rooms):
                return False
            headers = dict(money_api.SECURITY_HEADERS)
            if path in rooms and method == "POST":
                key = settings["TAVUS_API_KEY"]
                try:
                    if path.endswith("/end"):
                        length = int(self.headers.get("content-length") or 0)
                        asked = json.loads(self.rfile.read(length) or b"{}") if length else {}
                        avatar.end(key, str(asked.get("conversationId") or ""))
                        reply = {"ended": True}
                    else:
                        reply = avatar.start(key, settings["TAVUS_FACE_ID"], settings["TAVUS_PAL_ID"])
                    body, status = json.dumps(reply).encode(), 200
                except avatar.AvatarError as error:
                    body, status = json.dumps({"message": str(error)}).encode(), 502
                self._send(status, body, {**headers, "content-type": "application/json"})
            elif path == "/avatar-demo.wav":
                self._send(200, demo_voice().read_bytes(), {**headers, "content-type": "audio/wav"})
            elif path in DEMO_FILES:
                name, kind = DEMO_FILES[path]
                self._send(200, (DEMO / name).read_bytes(), {**headers, "content-type": f"{kind}; charset=utf-8"})
            else:
                return False
            return True

        def _run(self, method: str) -> None:
            if self._demo(method):
                return
            length = int(self.headers.get("content-length") or 0)
            event = {"requestContext": {"http": {"method": method}}, "rawPath": self.path.split("?")[0],
                     "body": self.rfile.read(length).decode() if length else None}
            reply = money_api.lambda_handler(event, None)
            body = base64.b64decode(reply["body"]) if reply.get("isBase64Encoded") else reply["body"].encode()
            self.send_response(reply["statusCode"])
            for key, value in reply["headers"].items():
                self.send_header(key, value)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            self._run("GET")

        def do_POST(self):  # noqa: N802
            self._run("POST")

        def log_message(self, *a):
            pass

    link = money_api.hub.mint_link(args.customer, "2" if args.verified else "")
    if args.avatar_demo:
        demo_voice()
        print(f"Avatar check: {base}/avatar-demo", flush=True)
    print(f"Money Hub preview for {args.customer}:\n  {link}\nCtrl+C to stop.",
          flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
