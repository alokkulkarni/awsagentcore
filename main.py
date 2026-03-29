"""
ARIA — Automated Responsive Intelligence Agent
Meridian Bank Voice Banking Agent
"""
import asyncio
import os
import re
import sys
import argparse
import logging
import logging.handlers
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Logging — all output goes to aria.log; the console stays clean for the user
# ---------------------------------------------------------------------------
_LOG_DIR = Path(os.getenv("LOG_DIR", "."))
_LOG_FILE = _LOG_DIR / "aria.log"
_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

_file_handler = logging.handlers.RotatingFileHandler(
    _LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
_file_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
)

logging.root.setLevel(_LOG_LEVEL)
logging.root.addHandler(_file_handler)

for _noisy in ("strands", "botocore", "boto3", "urllib3", "opentelemetry"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

logger = logging.getLogger("aria")

# ---------------------------------------------------------------------------
# Customer-facing messages — never expose internal error details
# ---------------------------------------------------------------------------
_MSG_TECHNICAL = (
    "I'm sorry, I'm experiencing a technical issue. "
    "Please hold while I transfer you to an advisor."
)
_MSG_UNAVAILABLE = (
    "I'm sorry, our banking services are temporarily unavailable. "
    "Please try again in a few moments or call our main line on 0161 900 9900."
)
_MSG_PERMISSIONS = (
    "I'm sorry, I'm unable to access the information you need right now. "
    "Please call our main line on 0161 900 9900 for assistance."
)
_MSG_GOODBYE = "Thank you for calling Meridian Bank. Goodbye."


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _clean_response(text: str) -> str:
    """Strip markdown formatting — ARIA is a voice/terminal agent, not a web UI."""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    text = re.sub(r'_(.+?)_', r'\1', text)
    text = re.sub(r'#{1,6}\s*', '', text)
    text = re.sub(r'^\s*[-*]\s+', '', text, flags=re.MULTILINE)
    return text.strip()


def _aria_say(text: str) -> None:
    """Print ARIA's response — cleaned of markdown, prefixed with ARIA:"""
    print(f"\nARIA: {_clean_response(str(text))}\n")


# ---------------------------------------------------------------------------
# Error → friendly message mapping (logs full detail, returns safe string)
# ---------------------------------------------------------------------------

def _friendly_message(exc: Exception) -> str:
    """Map an exception to a safe customer-facing message and log the detail."""
    exc_type = type(exc).__name__
    exc_str = str(exc)

    try:
        from botocore.exceptions import (
            ClientError,
            NoCredentialsError,
            PartialCredentialsError,
            EndpointResolutionError,
            ConnectTimeoutError,
            ReadTimeoutError,
        )

        if isinstance(exc, (NoCredentialsError, PartialCredentialsError)):
            logger.error(
                "AWS credentials not resolved. Configure one of: "
                "AWS_ACCESS_KEY_ID env vars, AWS_PROFILE, ~/.aws/credentials, "
                "or an IAM instance role. Detail: %s",
                exc_str,
            )
            return _MSG_PERMISSIONS

        if isinstance(exc, ClientError):
            code = exc.response.get("Error", {}).get("Code", "")
            msg = exc.response.get("Error", {}).get("Message", exc_str)
            if code == "ValidationException":
                logger.error("Bedrock ValidationException (check BEDROCK_MODEL_ID / AWS_REGION): %s", msg)
            elif code in ("AccessDeniedException", "UnauthorizedException"):
                logger.error("Bedrock access denied — check IAM permissions: %s", msg)
            elif code in ("ThrottlingException", "ServiceUnavailableException"):
                logger.warning("Bedrock throttled/unavailable: %s", msg)
                return _MSG_UNAVAILABLE
            elif code == "ModelNotReadyException":
                logger.error("Bedrock model not ready: %s", msg)
            else:
                logger.error("Bedrock ClientError [%s]: %s", code, msg)
            return _MSG_TECHNICAL

        if isinstance(exc, (EndpointResolutionError, ConnectTimeoutError, ReadTimeoutError)):
            logger.error("AWS connectivity error [%s]: %s", exc_type, exc_str)
            return _MSG_UNAVAILABLE

    except ImportError:
        pass

    logger.error("Unhandled error [%s]: %s", exc_type, exc_str, exc_info=True)
    return _MSG_TECHNICAL


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _build_session_start(authenticated: bool, customer_id: str | None, channel: str) -> str:
    """Build the SESSION_START trigger sent to the agent on startup."""
    channel_line = f"X-Channel: {channel}. "
    if authenticated and customer_id:
        return (
            f"SESSION_START: An authenticated customer has connected. "
            f"X-Channel-Auth: authenticated. "
            f"X-Customer-ID: {customer_id}. "
            + channel_line +
            "Call get_customer_details with this customer ID to fetch their profile, "
            "then greet them by their preferred_name and ask how you can help today. "
            "Do not ask them to re-verify their identity."
        )
    return (
        "SESSION_START: A new customer has connected on an unauthenticated channel. "
        "X-Channel-Auth: unauthenticated. "
        + channel_line +
        "Greet them as ARIA from Meridian Bank and begin the identity verification flow."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ARIA — Meridian Bank Voice Banking Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 main.py                                   # unauthenticated chat session\n"
            "  python3 main.py --auth --customer-id CUST-001      # authenticated chat session\n"
            "  python3 main.py --channel voice                    # Nova Sonic 2 voice session\n"
            "  python3 main.py --channel voice --auth --customer-id CUST-001  # authenticated voice\n"
        ),
    )
    parser.add_argument(
        "--auth", action="store_true",
        help="Start session as an already-authenticated customer (skips identity verification)."
    )
    parser.add_argument(
        "--customer-id", metavar="ID", default=None,
        help="Customer ID to inject into the authenticated session context (requires --auth)."
    )
    parser.add_argument(
        "--channel",
        metavar="CHANNEL",
        choices=["voice", "chat"],
        default="chat",
        help=(
            "Session channel: 'chat' (default, text REPL) or 'voice' "
            "(Nova Sonic 2 S2S audio stream via Bedrock bidirectional API). "
            "Voice mode requires: pip install 'strands-agents[bidi]' pyaudio"
        ),
    )
    args = parser.parse_args()

    if args.auth and not args.customer_id:
        parser.error("--auth requires --customer-id")
    logger.info("Starting ARIA banking agent")

    auth_label = "AUTHENTICATED" if args.auth else "UNAUTHENTICATED"
    channel_label = args.channel.upper()
    logger.info(
        "Session mode: %s | channel: %s | customer_id=%s",
        auth_label, channel_label, args.customer_id or "unknown",
    )

    # ------------------------------------------------------------------
    # Voice mode — Nova Sonic 2 S2S (audio in / audio out)
    # ------------------------------------------------------------------
    if args.channel == "voice":
        print("\n" + "=" * 60)
        print("  ARIA — Meridian Bank Voice Banking Agent")
        if args.auth:
            print(f"  Mode: Authenticated  |  Customer: {args.customer_id}")
        print("  Channel: VOICE (Nova Sonic 2 S2S)  |  Logs → aria.log")
        print("  Say 'stop' or press Ctrl-C to end the session")
        print("=" * 60 + "\n")

        from aria.voice_agent import run_voice_session
        try:
            asyncio.run(run_voice_session(args.auth, args.customer_id))
        except KeyboardInterrupt:
            # asyncio.run() re-raises KeyboardInterrupt during executor
            # shutdown (PyAudio threads block in C code and can't be
            # joined quickly).  Suppress the traceback and exit cleanly.
            print("\n[Voice session ended]\n")
            import os as _os
            _os._exit(0)
        return

    # ------------------------------------------------------------------
    # Chat / text REPL mode (default)
    # ------------------------------------------------------------------
    try:
        from aria.agent import create_aria_agent
        agent = create_aria_agent()
    except Exception as exc:
        logger.critical("Failed to initialise ARIA agent: %s", exc, exc_info=True)
        print(
            "\nARIA could not start. Check aria.log for details.\n"
            "Ensure AWS credentials and BEDROCK_MODEL_ID are correctly configured."
        )
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  ARIA — Meridian Bank Voice Banking Agent")
    if args.auth:
        print(f"  Mode: Authenticated  |  Customer: {args.customer_id}")
    print(f"  Channel: {args.channel}  |  Type 'quit' to exit  |  Logs → aria.log")
    print("=" * 60)

    # Trigger initial greeting — ARIA speaks first, customer doesn't have to prompt
    try:
        session_start_msg = _build_session_start(args.auth, args.customer_id, args.channel)
        greeting = agent(session_start_msg)
        _aria_say(greeting)
    except Exception as exc:
        _aria_say(_friendly_message(exc))
        sys.exit(1)

    while True:
        try:
            user_input = input("Customer: ").strip()
        except (KeyboardInterrupt, EOFError):
            _aria_say(_MSG_GOODBYE)
            logger.info("Session ended by interrupt")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "q"):
            _aria_say(_MSG_GOODBYE)
            logger.info("Session ended by customer")
            break

        try:
            response = agent(user_input)
            cleaned = _clean_response(str(response))
            if cleaned:
                _aria_say(response)
            logger.debug("Agent response delivered successfully")
        except KeyboardInterrupt:
            _aria_say(_MSG_GOODBYE)
            logger.info("Session interrupted during response")
            break
        except Exception as exc:
            _aria_say(_friendly_message(exc))


if __name__ == "__main__":
    main()

