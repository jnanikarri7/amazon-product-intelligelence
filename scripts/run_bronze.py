#!/usr/bin/env python
"""CLI entrypoint for local Bronze ingestion.

Examples:
  # One season, quick smoke test:
  python scripts/run_bronze.py --start 2024 --end 2024

  # Just a couple of datasets:
  python scripts/run_bronze.py --start 2023 --end 2024 --datasets schedules pbp

  # Full 2015-present backfill:
  python scripts/run_bronze.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Windows consoles default to cp1252 and choke on UTF-8 output (emojis, polars
# table borders). Force UTF-8 so runs don't crash on a print statement.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

# Make `src/` importable without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nfl import bronze
from nfl.config import DATASETS, END_SEASON, START_SEASON


def main() -> int:
    names = [d.name for d in DATASETS]
    p = argparse.ArgumentParser(description="Local Bronze ingestion (polars + deltalake).")
    p.add_argument("--start", type=int, default=START_SEASON)
    p.add_argument("--end", type=int, default=END_SEASON)
    p.add_argument("--mode", choices=["overwrite", "append"], default="overwrite")
    p.add_argument("--datasets", nargs="+", choices=names, default=names,
                   help="Subset of datasets to ingest (default: all).")
    args = p.parse_args()

    selected = [d for d in DATASETS if d.name in args.datasets]
    counts = bronze.run(seasons=list(range(args.start, args.end + 1)),
                        datasets=selected, mode=args.mode)
    return 0 if any(counts.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
