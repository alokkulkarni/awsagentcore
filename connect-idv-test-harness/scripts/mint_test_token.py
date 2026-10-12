#!/usr/bin/env python3
"""
mint_test_token.py
==================
Mints the test tokens and codes that the bank's mobile or chat backend would
normally create, so Options D (app-to-call handoff) and E (authenticated chat)
can be tested without a real app.

This runs entirely on your machine. It needs the same secret the Lambda has in
its IDV_TEST_SIGNING_SECRET environment variable.

Usage:
    export IDV_TEST_SIGNING_SECRET='<the secret the deploy script printed>'

    # Option D — in-app call: set the output as the idvCallToken contact attribute
    python3 mint_test_token.py call CUST-001

    # Option D — PSTN handoff: key the 6 digits when the harness asks for a dial code
    python3 mint_test_token.py dial-code CUST-001

    # Option E — authenticated chat: set as the idvSessionToken contact attribute
    python3 mint_test_token.py session CUST-002

    # Option E — in-app approval that lifts the chat to level 3: set as idvStepUpToken
    python3 mint_test_token.py sca CUST-002
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambda"))

import idv_tokens  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Mint ID&V test harness tokens and dial codes.")
    parser.add_argument("kind", choices=["call", "session", "sca", "dial-code"])
    parser.add_argument("customer_id", help="for example CUST-001")
    parser.add_argument("--loa", type=int, default=None, help="level carried by the token (call: 3, session: 2)")
    parser.add_argument("--intent", default="servicing", help=argparse.SUPPRESS)
    parser.add_argument("--ttl", type=int, default=300, help="seconds until the token expires (default 300)")
    args = parser.parse_args()

    secret = os.environ.get("IDV_TEST_SIGNING_SECRET", "")
    if len(secret) < 16:
        sys.exit("Set IDV_TEST_SIGNING_SECRET to the same value as the Lambda's environment variable.")

    if args.kind == "dial-code":
        print(idv_tokens.dial_code_for(args.customer_id, secret))
        return
    loa = args.loa if args.loa is not None else (2 if args.kind == "session" else 3)
    print(idv_tokens.mint_token(args.kind, args.customer_id, secret, loa=loa, intent=args.intent, ttl=args.ttl))


if __name__ == "__main__":
    main()
