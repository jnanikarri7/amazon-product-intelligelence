"""Silver layer — clean, validate, and conform Bronze into analysis-ready tables.

Transforms (local polars/deltalake; logic mirrors the Databricks PySpark version):
  silver_pbp          deduped offensive plays, special-teams & garbage-time removed
  silver_schedules    deduped games, dome weather imputed, neutral-site/HFA flags
  silver_player_stats deduped weekly player box scores

Each table is validated by a DataQualityReport before write, then Z-ORDERed
(delta-rs optimize) on the common access keys.
"""
from __future__ import annotations

import polars as pl
from deltalake import DeltaTable, write_deltalake

from . import quality as dq
from .config import BRONZE_DIR, SILVER_DIR

# Validation bounds (sanity-checked against the real 2015-2026 data).
EPA_LO, EPA_HI = -15.0, 15.0            # observed ~[-12.7, 8.5]
SCORE_DIFF_LO, SCORE_DIFF_HI = -75, 75
SPREAD_LO, SPREAD_HI = -30.0, 30.0
TOTAL_LO, TOTAL_HI = 20.0, 75.0

GARBAGE_TIME_SECONDS = 900              # final quarter
GARBAGE_TIME_MARGIN = 21                # 3+ scores


def _read_bronze(name: str) -> pl.DataFrame:
    return pl.read_delta(str(BRONZE_DIR / name))


def _write_silver(df: pl.DataFrame, name: str, z_order: list[str]) -> None:
    path = str(SILVER_DIR / name)
    part = ["season"] if "season" in df.columns else None
    write_deltalake(path, df.to_arrow(), mode="overwrite",
                    partition_by=part, schema_mode="overwrite")
    # Z-ORDER / compaction — mirrors `OPTIMIZE ... ZORDER BY` on Databricks.
    try:
        cols = [c for c in z_order if c in df.columns]
        if cols:
            DeltaTable(path).optimize.z_order(cols)
    except Exception as e:  # optimize is best-effort locally
        print(f"    (z-order skipped for {name}: {type(e).__name__})")
    print(f"  wrote silver/{name}: {df.height:,} rows, {df.width} cols -> {path}")


# ---------------------------------------------------------------------------
def build_silver_pbp() -> pl.DataFrame:
    df = _read_bronze("pbp")
    before = df.height

    df = (
        df
        # 1. Deduplicate on the natural key.
        .unique(subset=["game_id", "play_id"], keep="first")
        # 2. Null-possession plays (kickoffs, timeouts, end-of-quarter) are out.
        .filter(pl.col("posteam").is_not_null())
        # 3. Keep only real offensive plays — this also drops special teams,
        #    no_play penalties, kneels and spikes in one predicate.
        .filter(((pl.col("pass") == 1) | (pl.col("rush") == 1))
                & (pl.col("special").fill_null(0) == 0))
        # 4. EPA is the backbone of Phase-4 features; it must be present.
        .filter(pl.col("epa").is_not_null())
        # 5. Flag + remove garbage time (Q4 blowouts distort team EPA).
        .with_columns(
            ((pl.col("game_seconds_remaining") <= GARBAGE_TIME_SECONDS)
             & (pl.col("score_differential").abs() > GARBAGE_TIME_MARGIN))
            .alias("is_garbage_time")
        )
        .filter(~pl.col("is_garbage_time"))
    )

    report = (
        dq.DataQualityReport("silver_pbp")
        .add(dq.expect_unique(df, ["game_id", "play_id"]))
        .add(dq.expect_not_null(df, "posteam"))
        .add(dq.expect_not_null(df, "epa"))
        .add(dq.expect_in_range(df, "epa", EPA_LO, EPA_HI))
        .add(dq.expect_in_range(df, "score_differential", SCORE_DIFF_LO, SCORE_DIFF_HI))
    )
    report.print_summary()
    report.raise_if_failed()
    print(f"  silver_pbp: {before:,} -> {df.height:,} rows "
          f"({before - df.height:,} filtered)")
    return df


# ---------------------------------------------------------------------------
def build_silver_schedules() -> pl.DataFrame:
    df = _read_bronze("schedules")
    before = df.height

    df = (
        df
        .unique(subset=["game_id"], keep="first")
        .with_columns(
            # Dome / retractable-closed games are climate-controlled.
            pl.col("roof").is_in(["dome", "closed"]).alias("is_dome"),
            (pl.col("location") == "Neutral").alias("is_neutral_site"),
            pl.col("spread_line").is_not_null().alias("has_betting_line"),
            pl.col("result").is_not_null().alias("is_played"),
        )
        .with_columns(
            # Impute weather for indoor games (null temp/wind there is expected,
            # not missing data): ~70F, no wind. Outdoor nulls are left null.
            pl.when(pl.col("is_dome") & pl.col("temp").is_null())
              .then(pl.lit(70)).otherwise(pl.col("temp")).alias("temp"),
            pl.when(pl.col("is_dome") & pl.col("wind").is_null())
              .then(pl.lit(0)).otherwise(pl.col("wind")).alias("wind"),
            # Home-field advantage does not apply at neutral sites.
            pl.when(pl.col("is_neutral_site")).then(pl.lit(0))
              .otherwise(pl.lit(1)).alias("home_field_advantage"),
        )
    )

    report = (
        dq.DataQualityReport("silver_schedules")
        .add(dq.expect_unique(df, ["game_id"]))
        .add(dq.expect_not_null(df, "home_team"))
        .add(dq.expect_not_null(df, "away_team"))
        .add(dq.expect_in_range(df.filter(pl.col("has_betting_line")),
                                "spread_line", SPREAD_LO, SPREAD_HI))
        .add(dq.expect_in_range(df.filter(pl.col("has_betting_line")),
                                "total_line", TOTAL_LO, TOTAL_HI))
    )
    report.print_summary()
    report.raise_if_failed()
    print(f"  silver_schedules: {before:,} -> {df.height:,} rows "
          f"(played={df['is_played'].sum():,})")
    return df


# ---------------------------------------------------------------------------
def build_silver_player_stats() -> pl.DataFrame:
    df = _read_bronze("player_stats")
    before = df.height
    key = [c for c in ["player_id", "season", "week"] if c in df.columns]
    df = df.unique(subset=key, keep="first") if key else df.unique()

    report = dq.DataQualityReport("silver_player_stats")
    if key:
        report.add(dq.expect_unique(df, key))
    report.add(dq.expect_not_null(df, "season"))
    report.print_summary()
    report.raise_if_failed()
    print(f"  silver_player_stats: {before:,} -> {df.height:,} rows")
    return df


def run() -> dict[str, int]:
    SILVER_DIR.mkdir(parents=True, exist_ok=True)
    print("=== Silver build ===")
    pbp = build_silver_pbp();            _write_silver(pbp, "pbp", ["game_id", "week"])
    sched = build_silver_schedules();    _write_silver(sched, "schedules", ["game_id", "week"])
    ps = build_silver_player_stats();    _write_silver(ps, "player_stats", ["player_id", "week"])
    counts = {"pbp": pbp.height, "schedules": sched.height, "player_stats": ps.height}
    print(f"[DONE] Silver complete: {counts}")
    return counts
