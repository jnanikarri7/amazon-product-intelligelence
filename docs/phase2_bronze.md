# Phase 2 — Bronze Layer (Raw Ingestion)

## What lands where

```
abfss://bronze@<acct>.dfs.core.windows.net/nfl/
├── pbp/            season-partitioned  ~480k rows   (the big one)
├── schedules/      season-partitioned  ~2.9k rows   (+ betting: spread_line, total_line, moneyline)
├── player_stats/   season-partitioned  weekly box scores
├── rosters/        season-partitioned  weekly rosters
├── ngs_passing/    season-partitioned  2016+ only
├── ngs_rushing/    season-partitioned  2016+ only
└── ngs_receiving/  season-partitioned  2016+ only
```

## Bronze contract (the design principle to defend in interviews)
Bronze is a **raw, immutable, append-only landing zone**. We deliberately do **no** cleaning,
deduping, or type-casting here — Bronze preserves exactly what the source delivered so we can
always replay history and audit lineage. All business logic is deferred to **Silver (Phase 3)**.

Every row carries lineage columns:
| Column | Meaning |
|---|---|
| `_ingest_ts` | UTC timestamp the row was written |
| `_source_file` | logical source (e.g. `nflverse/pbp`) |
| `_batch_id` | unique id per notebook run — groups one ingestion batch |
| `_source_rows` | row count the source returned that run (quick completeness check) |

## Why polars → pandas → Spark
`nflreadpy` returns **polars** DataFrames. We hop polars → pandas (Arrow) → Spark because:
- Arrow makes it zero-copy-ish and type-faithful.
- The one real gotcha — nflverse **all-null columns** arrive as polars `Null` dtype, which
  Arrow/Spark can't materialize — is handled explicitly by casting them to string (still "raw":
  no values change, only an untyped empty column becomes a typed empty column).

## Append-only vs. idempotent re-runs
- **`write_mode=append`** (default): true Bronze. Re-running duplicates rows — that's fine,
  Silver dedupes. The `_batch_id` lets you tell batches apart.
- **`write_mode=overwrite_season`**: dev convenience. Uses Delta `replaceWhere "season in (...)"`
  to atomically replace just the seasons in the current run — re-runnable with no duplicates.

## How to run
1. Run `00_connect_adls` in the cluster session (sets OAuth config).
2. Open `01_bronze_ingest`, set `STORAGE_ACCOUNT`, attach to the single-node cluster.
3. First run: uncomment `dbutils.library.restartPython()` after the `%pip install`.
4. Set widgets (`start_season`, `end_season`, `write_mode`) and **Run All**.

Expect a few minutes end-to-end (PBP download dominates). Watch the final validation cell for
per-table row counts and the ✅ message.

## Cost note
Downloads are from nflverse GitHub (free). The only spend is cluster time — this notebook is a
single pass, so let the cluster auto-terminate right after. ~1 cluster-hour covers a full backfill.
