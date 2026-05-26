#!/usr/bin/env python3
"""Compatibility wrapper for generate_backlog.py."""
from __future__ import annotations
import runpy
import sys
from pathlib import Path
if __name__ == "__main__":
    script = Path(__file__).with_name("generate_backlog.py")
    sys.argv[0] = str(script)
    runpy.run_path(str(script), run_name="__main__")
