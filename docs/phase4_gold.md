# Phase 4 — Gold Layer (Leakage-Safe Feature Engineering)

**One row per scheduled game**, home-vs-away feature deltas, with target labels on played
games (null on the 207 future 2026 games → ready for inference). 3,300 games × 85 columns;
**3,083 trainable** (played, non-tie).

## The cardinal rule: no data leakage
Every feature uses **only information available before kickoff**. Enforced two ways:

1. **Rolling EMAs are `shift(1)` per team.** We compute the exponential moving average over a
   team's game history, then shift it forward one game — so a game's features reflect its
   *prior* form, never its own result or any later game.
2. **Elo is recorded pre-update.** We iterate games in strict date order, snapshot each team's
   rating *before* the game, and only update *after* the game is scored.

Betting lines (`spread_line`, `total_line`) are legitimate pre-kickoff signals and kept as
features. Final scores/results feed **targets only** and never enter the feature set.

### Leakage self-test (run, passing)
- 2015 Week 1: **all 16 games have NULL rolling features** (no prior games exist) ✓
- By 2024 Week 10: features fully populated ✓
- `home_win` reproduces `sign(result)` exactly; home-win rate 55.0%, cover rate 49.1% ✓

## Feature families
| Family | Features | Notes |
|---|---|---|
| **Rolling EPA** | off/def EPA per play, pass & rush split, EMA span 4 & 8 | the core signal |
| **CPOE** | rolling off_cpoe EMA 4 & 8 | passing efficiency over expected |
| **Turnovers** | giveaways / takeaways per game (≈ per 60 min), EMA 4 & 8 | |
| **Rest** | `rest_days` per team (capped 14 for week 1), `rest_days_diff` | |
| **Travel** | `away_travel_miles` (haversine from stadium coords), `travel_diff` | home = 0 |
| **Elo** | `home_elo_pre`, `away_elo_pre`, `elo_diff` | K=20, HFA=55, 0.75 offseason regression |
| **Context** | `div_game`, `is_dome`, `is_neutral_site`, `home_field_advantage`, `temp`, `wind` | |
| **Market** | `spread_line`, `total_line` | the Vegas baseline we'll benchmark against |

For every rolling family we store `home_*`, `away_*`, and the `*_diff` (home − away) — the delta
is what the model keys on.

## Targets
| Target | Definition | Task |
|---|---|---|
| `home_win` | `result > 0` (ties → null) | binary classification |
| `home_covered` | `result > spread_line` (push → null) | binary classification |
| `target_margin` | `result` (home − away points) | regression (spread) |

## Engineering notes
- **Team-identity conform** (`src/nfl/teams.py`): SD→LAC, STL→LAR, OAK→LV. Without this the
  home/away join silently breaks for 2015-16 and Elo splits a franchise in two — caught by the
  `unique(game_id)` DQ check during development.
- **Elo is inherently sequential**, so both engines run it as a driver-side loop (polars
  `iter_rows` locally; `toPandas()` + loop on Databricks). Everything else is vectorized.
- EMAs on Databricks use `applyInPandas` per team (Spark has no native EMA window); locally,
  polars `ewm_mean(...).shift(1).over("team")`.

## Run it
```bash
python scripts/run_gold.py            # local
# Databricks: run notebooks/03_gold_features.py
```
