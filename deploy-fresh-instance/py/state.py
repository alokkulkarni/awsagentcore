"""The state file from the shell: `state.py FILE get KEY`, `state.py FILE set KEY VALUE`, `state.py FILE has KEY`."""

from __future__ import annotations

import sys

from common import State

if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit("usage: state.py FILE get|has KEY | set KEY VALUE")
    state, action, key = State(sys.argv[1]), sys.argv[2], sys.argv[3]
    if action == "get":
        print(state.get(key) or "")
    elif action == "has":
        sys.exit(0 if state.get(key) else 1)
    elif action == "set" and len(sys.argv) == 5:
        state.set(key, sys.argv[4])
    else:
        sys.exit("usage: state.py FILE get|has KEY | set KEY VALUE")
