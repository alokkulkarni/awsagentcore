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
"""

import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(FOLDER), str(FOLDER / "api")]

import money_api  # noqa: E402
from moneyhub.service import MoneyHub  # noqa: E402
from moneyhub.store import MemoryStore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview the Money Hub page locally.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--customer", default="CUST-001")
    parser.add_argument("--talk", nargs=2, metavar=("INSTANCE_ID", "FLOW_ID"))
    parser.add_argument("--verified", action="store_true")
    args = parser.parse_args()
    if args.talk:
        money_api.CONNECT_INSTANCE_ID, money_api.CONTACT_FLOW_ID = args.talk
    base = f"http://127.0.0.1:{args.port}"
    money_api.hub = MoneyHub(MemoryStore(time.time), time.time, page_url=base)

    class Handler(BaseHTTPRequestHandler):
        def _run(self, method: str) -> None:
            length = int(self.headers.get("content-length") or 0)
            event = {"requestContext": {"http": {"method": method}}, "rawPath": self.path.split("?")[0],
                     "body": self.rfile.read(length).decode() if length else None}
            reply = money_api.lambda_handler(event, None)
            body = reply["body"].encode()
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
    print(f"Money Hub preview for {args.customer}:\n  {link}\nCtrl+C to stop.",
          flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
