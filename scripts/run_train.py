#!/usr/bin/env python
"""CLI entrypoint for Phase 5 training.

  python scripts/run_train.py
Then explore:  mlflow ui --backend-store-uri sqlite:///mlflow.db
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

from nfl import train

if __name__ == "__main__":
    raise SystemExit(train.run())
