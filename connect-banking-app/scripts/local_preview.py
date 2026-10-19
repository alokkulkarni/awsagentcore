#!/usr/bin/env python3
"""
local_preview.py
================
Runs the internet banking app on your laptop with the sample data in memory, so you can click through it
before deploying. Without options, no AWS is touched: chat and call are off, and the mortgage and dispute
services aren't reached (their pages still show and the forms work by hand).

    python3 connect-banking-app/scripts/local_preview.py [--port 8770] [--customer CUST-001] [--verified]
                                                         [--talk INSTANCE_ID FLOW_ID] [--partners] [--unverified]

It prints a link (with its secret after '#'); open it in a browser. Changes you make last until you stop it.

--talk       starts REAL chats and calls in that Connect instance and flow with your AWS credentials, and shows
             the face on calls if connect-money-hub/.env has the Tavus settings (as the Money Hub preview does).
--partners   uses the REAL mortgage and dispute services (their Lambdas and Live Sync keys) with your AWS
             credentials: help codes, submitting, the dispute form.
--unverified the link is NOT verified (by default it is: the app stands for signed-in internet banking, so a
             contact from any page arrives verified, as when deployed).

Uses the Money Hub and dispute code from their own folders, unchanged.
"""

import argparse
import base64
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
sys.path[:0] = [str(APP), str(APP / "api"), str(ROOT / "connect-money-hub"), str(ROOT / "connect-money-hub" / "api"),
                str(ROOT / "connect-card-dispute" / "lambda")]


def read_env(path: Path) -> dict:
    """KEY=VALUE lines from a .env file (comments and blanks skipped, quotes taken off). Never run as a script."""
    found = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key and not key.startswith("#"):
                found[key.strip()] = value.strip().strip('"').strip("'")
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview the internet banking app locally.")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--customer", default="CUST-001")
    parser.add_argument("--talk", nargs=2, metavar=("INSTANCE_ID", "FLOW_ID"))
    parser.add_argument("--partners", action="store_true")
    parser.add_argument("--unverified", action="store_true")
    args = parser.parse_args()
    if args.partners:
        os.environ.update(MORTGAGE_FUNCTION_NAME="mortgage-livesync-api", MORTGAGE_TOUCHPOINT_SECRET="mortgage-livesync-api/touchpoint",
                          HELP_PHONE_NUMBER="02046394728", DISPUTE_FUNCTION_NAME="aria-card-dispute",
                          DISPUTE_TOUCHPOINT_SECRET="aria-card-dispute/touchpoint",
                          DISPUTE_PAGES_URL="https://d120l7in463wla.cloudfront.net", DISPUTE_TABLE_NAME="aria-card-disputes")
        os.environ.setdefault("AWS_REGION", "eu-west-2")

    import banking_api
    import money_api
    from moneyhub.service import MoneyHub
    from moneyhub.store import MemoryStore

    if args.talk:
        money_api.CONNECT_INSTANCE_ID, money_api.CONTACT_FLOW_ID = args.talk
        face = read_env(ROOT / "connect-money-hub" / ".env")
        if all(face.get(k) for k in ("TAVUS_API_KEY", "TAVUS_FACE_ID", "TAVUS_PAL_ID")):
            os.environ["TAVUS_API_KEY"] = face["TAVUS_API_KEY"]
            money_api.TAVUS_FACE_ID, money_api.TAVUS_PAL_ID = face["TAVUS_FACE_ID"], face["TAVUS_PAL_ID"]
            print("Face on: calls show the Tavus face (settings from connect-money-hub/.env).", flush=True)
    base = f"http://127.0.0.1:{args.port}"
    money_api.hub = MoneyHub(MemoryStore(time.time), time.time, page_url=base)
    if not args.partners:
        # The customer's disputes, in memory, with one sample dispute so the Cards and Help pages show one.
        import dispute_model
        from bankapp import disputes
        from dispute_service import DisputeService
        from dispute_store import MemoryStore as DisputeMemory
        disputes._service = DisputeService(DisputeMemory(time.time), time.time, page_url="https://disputes.example")
        payment = next(t for t in dispute_model.card_transactions(args.customer) if "ELECTROWORLD" in t["merchant"])
        disputes._service.start_card_dispute(args.customer, payment["transaction_id"], "merchant")
        # And a complete one, so the "Submit" path shows too (the customer may submit a complete draft).
        other = next((t for t in dispute_model.card_transactions(args.customer) if "ELECTROWORLD" not in t["merchant"]), None)
        if other:
            done = disputes._service.start_card_dispute(args.customer, other["transaction_id"], "unauthorised")["dispute_id"]
            disputes._service.update_card_dispute(args.customer, done, {
                "reason": "not_recognised", "cardInPossession": "yes", "narrative": "I don't recognise this payment."})

    class Handler(BaseHTTPRequestHandler):
        def _run(self, method: str) -> None:
            length = int(self.headers.get("content-length") or 0)
            event = {"requestContext": {"http": {"method": method}}, "rawPath": self.path.split("?")[0],
                     "body": self.rfile.read(length).decode() if length else None}
            reply = banking_api.lambda_handler(event, None)
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

    link = money_api.hub.mint_link(args.customer, "" if args.unverified else "2", expires=False)
    print(f"Internet banking preview for {args.customer}:\n  {link}\nCtrl+C to stop.", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
