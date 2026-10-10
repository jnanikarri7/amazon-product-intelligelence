#!/usr/bin/env python
"""CLI entrypoint for the local Silver build.

  python scripts/run_silver.py
"""
from __future__ import annotations

import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nfl import silver

if __name__ == "__main__":
    counts = silver.run()
    raise SystemExit(0 if all(counts.values()) else 1)
