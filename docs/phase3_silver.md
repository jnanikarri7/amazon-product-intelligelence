# Phase 3 — Silver Layer (Clean, Validate, Conform)

Bronze is raw and trusted-as-delivered; **Silver is where data becomes analysis-ready.**
Every transform is deterministic, validated by a data-quality suite, and optimized for the
access patterns of Phase 4.

## Tables produced
| Table | Rows (2015–2026) | Key transforms |
|---|---|---|
| `silver_pbp` | 543,703 → **391,849** | dedupe, drop special-teams / garbage-time / null-possession, EPA not-null + range |
| `silver_schedules` | 3,300 (3,093 played) | dedupe, dome weather imputation, neutral-site & HFA flags, betting-line flag |
| `silver_player_stats` | **204,385** | dedupe on (player_id, season, week) |

## silver_pbp filtering logic (28% of plays removed, by design)
1. **Dedupe** on `(game_id, play_id)` — the natural play key.
2. **Null possession** (`posteam IS NULL`) → out. Kickoffs, timeouts, end-of-quarter markers.
3. **Real offensive plays only**: `(pass = 1 OR rush = 1) AND special = 0`. One predicate removes
   special teams, `no_play` penalties, QB kneels and spikes.
4. **EPA present**: `epa IS NOT NULL` — EPA is the backbone of every Phase-4 feature.
5. **Garbage time removed**: Q4 (`game_seconds_remaining <= 900`) blowouts
   (`|score_differential| > 21`) distort team EPA, so they're flagged and dropped.

## silver_schedules cleaning logic
- **Dome weather imputation**: `temp`/`wind` are null for indoor games — that's *expected*, not
  missing. For `roof IN ('dome','closed')` we set `temp=70`, `wind=0`. Outdoor nulls stay null.
- **Neutral site**: `location = 'Neutral'` → `is_neutral_site=true`, `home_field_advantage=0`
  (no HFA at neutral sites — matters for Phase-4 features and avoids a bias).
- **Flags**: `has_betting_line` (spread present), `is_played` (result present → separates the
  3,093 trainable games from 207 future 2026 fixtures).

## Data-quality gate (the "Great Expectations / PySpark rules" requirement)
`src/nfl/quality.py` implements expectations — `unique`, `not_null`, `in_range`, `in_set` — that
run **before** each write and **hard-fail** the pipeline on violation. Current run: **12/12 pass**.
Range bounds were calibrated against the real data:
- `epa ∈ [-15, 15]` (observed [-13.6, 8.9])
- `score_differential ∈ [-75, 75]` (observed [-49, 42])
- `spread_line ∈ [-30, 30]`, `total_line ∈ [20, 75]`

## Optimization
Both engines OPTIMIZE + Z-ORDER on the common access keys:
- `silver_pbp`, `silver_schedules`: `ZORDER BY (game_id, week)`
- `silver_player_stats`: `ZORDER BY (player_id, week)`

On Databricks this is `OPTIMIZE delta.\`...\` ZORDER BY (...)` (or Liquid Clustering). Locally,
delta-rs `DeltaTable.optimize.z_order([...])` does file compaction + co-location.

## Run it
```bash
python scripts/run_silver.py          # local
# Databricks: run notebooks/02_silver_transform.py on the cluster
```
