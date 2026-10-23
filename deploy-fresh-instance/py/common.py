"""Shared by every deploy-fresh-instance helper: the run's state file, AWS clients, waiting and output.

The state file (state/<alias>.env) is how steps hand IDs to later steps. It is plain KEY='value' lines, so
deploy.sh can source it and every helper reads and writes it through State. A value is written once a resource
exists, so a re-run finds it and moves on (create-only: nothing that exists is changed unless a step says so).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent                      # deploy-fresh-instance/
ROOT = PACKAGE.parent                      # the repository
TEMPLATES = PACKAGE / "templates"
TAG_KEY, TAG_VALUE = "project", "deploy-fresh-instance"
TAGS = {TAG_KEY: TAG_VALUE}

GREEN, YELLOW, RED, CYAN, RESET = "\033[0;32m", "\033[1;33m", "\033[0;31m", "\033[0;36m", "\033[0m"


def ok(msg: str) -> None: print(f"{GREEN}[ OK ] {msg}{RESET}", flush=True)
def info(msg: str) -> None: print(f"{CYAN}[....] {msg}{RESET}", flush=True)
def warn(msg: str) -> None: print(f"{YELLOW}[WARN] {msg}{RESET}", flush=True)


def fail(msg: str) -> None:
    print(f"{RED}[FAIL] {msg}{RESET}", file=sys.stderr, flush=True)
    sys.exit(1)


_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _unquote(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] == "'":
        return raw[1:-1].replace("'\\''", "'")
    return raw


class State:
    """KEY='value' lines; written whole on every change (small file, one writer at a time)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.values: dict[str, str] = {}
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    key, _, raw = line.partition("=")
                    self.values[key.strip()] = _unquote(raw)

    def get(self, key: str, default: str | None = None) -> str | None:
        return self.values.get(key) or default

    def need(self, key: str) -> str:
        value = self.values.get(key)
        if not value:
            fail(f"{key} isn't in {self.path.name} yet: run the step that makes it first (./deploy.sh --list).")
        return value

    def set(self, key: str, value: Any) -> None:
        if not _KEY.match(key):
            raise ValueError(f"bad state key {key!r}")
        value = str(value)
        if "\n" in value:
            raise ValueError(f"{key}: state values are one line")
        self.values[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = "# deploy-fresh-instance state: IDs this run made. Don't edit by hand unless a step tells you to.\n"
        body += "".join(f"{k}={_quote(v)}\n" for k, v in sorted(self.values.items()))
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(body)
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)


def cli(description: str, commands: dict[str, Callable[["Context"], None]]) -> None:
    """Every helper: `python3 py/<helper>.py <command> --state FILE`. Region and account come from the state."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("command", choices=sorted(commands))
    parser.add_argument("--state", required=True)
    parser.add_argument("--yes", action="store_true", help="don't ask before an optional action")
    parser.add_argument("extra", nargs="*", help="command-specific values")
    args = parser.parse_intermixed_args()   # extras after --state too (older Pythons' parse_args refuses them)
    ctx = Context(State(args.state), args.yes, args.extra)
    commands[args.command](ctx)


class Context:
    def __init__(self, state: State, yes: bool, extra: list[str]):
        self.state, self.yes, self.extra = state, yes, extra
        self.region = state.need("REGION")
        self._clients: dict[str, Any] = {}

    def client(self, service: str):
        if service not in self._clients:
            import boto3
            self._clients[service] = boto3.client(service, region_name=self.region)
        return self._clients[service]

    @property
    def account(self) -> str:
        return self.state.need("ACCOUNT_ID")

    @property
    def instance_id(self) -> str:
        return self.state.need("INSTANCE_ID")

    @property
    def instance_arn(self) -> str:
        return f"arn:aws:connect:{self.region}:{self.account}:instance/{self.instance_id}"


def wait(check: Callable[[], Any], what: str, timeout: int = 600, every: int = 10) -> Any:
    """Calls check() until it returns something truthy; prints progress so a long wait never looks stuck."""
    start = time.time()
    while True:
        result = check()
        if result:
            return result
        waited = int(time.time() - start)
        if waited >= timeout:
            fail(f"Gave up waiting for {what} after {waited}s. Re-run this step to carry on.")
        info(f"Waiting for {what} ({waited}s)...")
        time.sleep(every)


def paged(call: Callable[..., dict], key: str, token: str = "NextToken", **params) -> list:
    """All items of a List* call. token: the paging field's name (Connect "NextToken", qconnect "nextToken")."""
    items, next_token = [], None
    while True:
        page = call(**params, **({token: next_token} if next_token else {}))
        items.extend(page.get(key, []))
        next_token = page.get(token)
        if not next_token:
            return items


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text())


def ask(question: str, ctx: Context) -> bool:
    if ctx.yes:
        return True
    try:
        with open("/dev/tty") as tty:
            print(f"{CYAN}{question} [y/N] {RESET}", end="", flush=True)
            return tty.readline().strip().lower() in ("y", "yes")
    except OSError:
        return False


def exists_error(err: Exception) -> bool:
    code = getattr(err, "response", {}).get("Error", {}).get("Code", "")
    return code in ("ConflictException", "ResourceExistsException", "DuplicateResourceException",
                    "ResourceAlreadyExistsException", "EntityAlreadyExists", "BucketAlreadyOwnedByYou")
