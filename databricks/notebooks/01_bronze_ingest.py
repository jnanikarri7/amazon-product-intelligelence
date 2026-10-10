# Databricks notebook source
# MAGIC %md
# MAGIC # 01 — Bronze Ingestion (Phase 2)
# MAGIC
# MAGIC Pull 2015–present NFL data via **`nflreadpy`** and land it **raw** in ADLS Gen2 as
# MAGIC **append-only Delta** tables under `abfss://bronze@<acct>.dfs.core.windows.net/nfl/`.
# MAGIC
# MAGIC **Bronze contract (what we promise):**
# MAGIC - *No business logic.* We do not clean, dedupe, or cast. Schema is as-delivered by nflverse.
# MAGIC - *Append-only, immutable log.* Every run appends; dedup happens in **Silver** (Phase 3).
# MAGIC - *Lineage columns on every row:* `_ingest_ts`, `_source_file`, `_batch_id`, `_source_rows`.
# MAGIC
# MAGIC Flow per dataset: `nflreadpy` (polars) → pandas (Arrow) → Spark DF → add lineage → Delta append.

# COMMAND ----------

# MAGIC %pip install -q nflreadpy polars pyarrow
# dbutils.library.restartPython()  # uncomment on first install so the new libs load

# COMMAND ----------

# MAGIC %md ## Parameters & connection
# MAGIC Run `00_connect_adls` first in the same cluster session, or paste its config here.

# COMMAND ----------

import datetime as dt
import uuid
import polars as pl
import nflreadpy as nfl
from pyspark.sql import functions as F

# ---- EDIT ----
STORAGE_ACCOUNT = "stnflpredictXX"
# --------------

# Widgets let you re-run for a subset of seasons without editing code.
dbutils.widgets.text("start_season", "2015", "Start season")
dbutils.widgets.text("end_season", str(dt.date.today().year), "End season (inclusive)")
dbutils.widgets.dropdown("write_mode", "append", ["append", "overwrite_season"], "Write mode")

START = int(dbutils.widgets.get("start_season"))
END = int(dbutils.widgets.get("end_season"))
WRITE_MODE = dbutils.widgets.get("write_mode")
SEASONS = list(range(START, END + 1))

BRONZE = f"abfss://bronze@{STORAGE_ACCOUNT}.dfs.core.windows.net/nfl"
BATCH_ID = f"{dt.datetime.utcnow():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"

# Arrow makes the pandas -> Spark hop fast and type-faithful.
spark.conf.set("spark.sql.execution.arrow.pyspark.enabled", "true")

print(f"Seasons   : {SEASONS[0]}–{SEASONS[-1]}  ({len(SEASONS)} seasons)")
print(f"Write mode: {WRITE_MODE}")
print(f"Batch ID  : {BATCH_ID}")
print(f"Target    : {BRONZE}/")

# COMMAND ----------

# MAGIC %md ## Reusable ingestion helper

# COMMAND ----------

def ingest_to_bronze(name: str, loader, source_file: str, partition_cols=None):
    """Load one nflverse dataset (polars), stamp lineage, append to a Bronze Delta table.

    `loader` is a zero-arg callable returning a polars.DataFrame — keeps season/stat_type
    binding at the call site so this helper stays generic.
    """
    print(f"\n=== {name} ===")
    pldf = loader()
    n = pldf.height
    if n == 0:
        print(f"  (no rows returned for {name}; skipping)")
        return

    # Edge case: nflverse all-null columns arrive as polars `Null` dtype, which Spark/Arrow
    # cannot materialize. Cast them to string so the schema is writable. Pure plumbing, not cleaning.
    null_cols = [c for c, t in pldf.schema.items() if t == pl.Null]
    if null_cols:
        pldf = pldf.with_columns([pl.col(c).cast(pl.Utf8) for c in null_cols])
        print(f"  cast {len(null_cols)} all-null column(s) to string: {null_cols}")

    sdf = (
        spark.createDataFrame(pldf.to_pandas(use_pyarrow_extension_array=False))
        .withColumn("_ingest_ts", F.current_timestamp())
        .withColumn("_source_file", F.lit(source_file))
        .withColumn("_batch_id", F.lit(BATCH_ID))
        .withColumn("_source_rows", F.lit(n))
    )

    path = f"{BRONZE}/{name}"
    writer = sdf.write.format("delta").option("mergeSchema", "true")
    if partition_cols:
        writer = writer.partitionBy(*partition_cols)

    if WRITE_MODE == "overwrite_season" and partition_cols == ["season"] and "season" in sdf.columns:
        # Idempotent dev re-runs: replace only the seasons in this batch (no duplicate rows).
        seasons_in = [r[0] for r in sdf.select("season").distinct().collect()]
        pred = "season in (" + ",".join(str(s) for s in seasons_in) + ")"
        writer.mode("overwrite").option("replaceWhere", pred).save(path)
        print(f"  overwrote seasons {seasons_in} -> {path}")
    else:
        writer.mode("append").save(path)  # true Bronze: append-only
        print(f"  appended {n:,} rows -> {path}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Ingest datasets
# MAGIC NGS exists only from **2016**, so we clamp its season list.
# MAGIC
# MAGIC > ⚠️ Verify loader names against your installed `nflreadpy` (`help(nfl)`); the nflverse
# MAGIC > API occasionally renames functions between versions.

# COMMAND ----------

NGS_SEASONS = [s for s in SEASONS if s >= 2016]

# Play-by-play — the big one (~370 cols, ~48k rows/season)
ingest_to_bronze(
    "pbp",
    lambda: nfl.load_pbp(seasons=SEASONS),
    source_file="nflverse/pbp",
    partition_cols=["season"],
)

# Schedules + betting lines (spread_line, total_line, moneyline, result, …)
ingest_to_bronze(
    "schedules",
    lambda: nfl.load_schedules(seasons=SEASONS),
    source_file="nflverse/schedules",
    partition_cols=["season"],
)

# Weekly player stats
ingest_to_bronze(
    "player_stats",
    lambda: nfl.load_player_stats(seasons=SEASONS),
    source_file="nflverse/player_stats",
    partition_cols=["season"],
)

# Weekly rosters
ingest_to_bronze(
    "rosters",
    lambda: nfl.load_rosters_weekly(seasons=SEASONS),
    source_file="nflverse/rosters_weekly",
    partition_cols=["season"],
)

# Next Gen Stats — three stat types, 2016+ only
for stat_type in ["passing", "rushing", "receiving"]:
    ingest_to_bronze(
        f"ngs_{stat_type}",
        lambda st=stat_type: nfl.load_nextgen_stats(seasons=NGS_SEASONS, stat_type=st),
        source_file=f"nflverse/ngs_{stat_type}",
        partition_cols=["season"],
    )

# COMMAND ----------

# MAGIC %md ## Validate the landing zone

# COMMAND ----------

for name in ["pbp", "schedules", "player_stats", "rosters",
             "ngs_passing", "ngs_rushing", "ngs_receiving"]:
    try:
        df = spark.read.format("delta").load(f"{BRONZE}/{name}")
        seasons = [r[0] for r in df.select("season").distinct().orderBy("season").collect()] \
            if "season" in df.columns else []
        print(f"{name:16s} rows={df.count():>8,}  seasons={seasons[:3]}…{seasons[-1:]}")
    except Exception as e:
        print(f"{name:16s} NOT FOUND ({type(e).__name__})")

print(f"\n✅ Bronze ingestion complete. Batch {BATCH_ID}")
