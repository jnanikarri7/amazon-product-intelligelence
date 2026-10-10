"""Central config: paths, season range, and the dataset registry.

Keeping the dataset registry in one place means Bronze (and later layers) iterate
over a single source of truth — add a dataset here and it flows everywhere.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import nflreadpy as nfl
import polars as pl

# ---- Paths (local lake) -----------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
BRONZE_DIR = DATA_DIR / "bronze"
SILVER_DIR = DATA_DIR / "silver"
GOLD_DIR = DATA_DIR / "gold"

# ---- Seasons ----------------------------------------------------------------
START_SEASON = 2015
END_SEASON = dt.date.today().year  # "present"
NGS_FIRST_SEASON = 2016  # NFL did not publish Next Gen Stats before 2016


def season_range(start: int = START_SEASON, end: int = END_SEASON) -> list[int]:
    return list(range(start, end + 1))


# ---- Dataset registry -------------------------------------------------------
@dataclass(frozen=True)
class Dataset:
    name: str                              # bronze table folder name
    loader: Callable[[list[int]], pl.DataFrame]  # seasons -> polars DataFrame
    source_file: str                       # lineage tag
    partition_by: tuple[str, ...] = ("season",)
    first_season: int | None = None        # clamp (e.g. NGS -> 2016+)


def _ngs(stat_type: str) -> Callable[[list[int]], pl.DataFrame]:
    return lambda seasons: nfl.load_nextgen_stats(seasons=seasons, stat_type=stat_type)


DATASETS: list[Dataset] = [
    Dataset("pbp",          lambda s: nfl.load_pbp(seasons=s),            "nflverse/pbp"),
    Dataset("schedules",    lambda s: nfl.load_schedules(seasons=s),      "nflverse/schedules"),
    Dataset("player_stats", lambda s: nfl.load_player_stats(seasons=s),   "nflverse/player_stats"),
    Dataset("rosters",      lambda s: nfl.load_rosters_weekly(seasons=s), "nflverse/rosters_weekly"),
    Dataset("ngs_passing",   _ngs("passing"),   "nflverse/ngs_passing",   first_season=NGS_FIRST_SEASON),
    Dataset("ngs_rushing",   _ngs("rushing"),   "nflverse/ngs_rushing",   first_season=NGS_FIRST_SEASON),
    Dataset("ngs_receiving", _ngs("receiving"), "nflverse/ngs_receiving", first_season=NGS_FIRST_SEASON),
]
