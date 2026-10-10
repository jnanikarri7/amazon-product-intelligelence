"""Gold layer — leakage-safe feature engineering.

The cardinal rule: every feature on a game's row uses ONLY information available
BEFORE kickoff. We enforce this two ways:
  1. Rolling EMAs are shift(1)'d within each team's timeline, so a game never
     sees its own result (or any later game).
  2. Elo ratings are recorded PRE-update and the update happens only after a game
     is scored, iterating strictly in chronological order.

Betting lines (spread/total) are legitimate pre-kickoff features and are kept;
final scores/results are targets only and never enter the feature set.

Output: gold_game_features — one row per scheduled game, home-vs-away deltas,
with target labels on played games (null on future games, ready for inference).
"""
from __future__ import annotations

import math

import polars as pl
from deltalake import DeltaTable, write_deltalake

from . import quality as dq
from .config import GOLD_DIR, SILVER_DIR
from .stadiums import TEAM_COORDS

EMA_SPANS = (4, 8)
ELO_K = 20.0
ELO_HFA = 55.0          # home-field advantage in Elo points
ELO_BASE = 1500.0
ELO_REGRESS = 0.75      # offseason regression toward the mean
MAX_REST_DAYS = 14      # cap offseason gap so week-1 "rest" isn't ~200 days


# ---------------------------------------------------------------------------
# 1. Per-team, per-game box score (offense + defense) from play-by-play.
# ---------------------------------------------------------------------------
def _team_game_stats(pbp: pl.DataFrame) -> pl.DataFrame:
    off = pbp.group_by("game_id", "posteam").agg(
        pl.len().alias("off_plays"),
        pl.col("epa").mean().alias("off_epa"),
        pl.col("epa").filter(pl.col("pass") == 1).mean().alias("off_pass_epa"),
        pl.col("epa").filter(pl.col("rush") == 1).mean().alias("off_rush_epa"),
        pl.col("cpoe").mean().alias("off_cpoe"),
        (pl.col("interception").sum() + pl.col("fumble_lost").sum()).alias("giveaways"),
    ).rename({"posteam": "team"})

    deff = pbp.group_by("game_id", "defteam").agg(
        pl.col("epa").mean().alias("def_epa"),
        pl.col("epa").filter(pl.col("pass") == 1).mean().alias("def_pass_epa"),
        pl.col("epa").filter(pl.col("rush") == 1).mean().alias("def_rush_epa"),
        (pl.col("interception").sum() + pl.col("fumble_lost").sum()).alias("takeaways"),
    ).rename({"defteam": "team"})

    return off.join(deff, on=["game_id", "team"], how="inner")


# ---------------------------------------------------------------------------
# 2. Team timeline with leakage-safe rolling EMAs + rest days.
# ---------------------------------------------------------------------------
EMA_BASE_COLS = ["off_epa", "def_epa", "off_pass_epa", "off_rush_epa",
                 "def_pass_epa", "def_rush_epa", "off_cpoe",
                 "giveaways", "takeaways"]


def _team_timeline(team_game: pl.DataFrame, sched: pl.DataFrame) -> pl.DataFrame:
    ctx = sched.select("game_id", "season", "week", "gameday",
                        "home_team", "away_team")
    tg = (
        team_game.join(ctx, on="game_id", how="inner")
        .with_columns(
            pl.col("gameday").str.to_date().alias("game_date"),
            (pl.col("team") == pl.col("home_team")).alias("is_home"),
        )
        .sort("team", "game_date", "game_id")
    )

    # Rolling EMAs over PRIOR games only (ewm then shift(1) within team).
    ema_exprs = []
    for span in EMA_SPANS:
        for col in EMA_BASE_COLS:
            ema_exprs.append(
                pl.col(col).ewm_mean(span=span, adjust=False, min_samples=1)
                  .shift(1).over("team").alias(f"{col}_ema{span}")
            )

    # Days of rest within a season; new-season week 1 gets the cap.
    rest = (
        pl.when(pl.col("season") == pl.col("season").shift(1).over("team"))
          .then((pl.col("game_date") - pl.col("game_date").shift(1).over("team")).dt.total_days())
          .otherwise(pl.lit(MAX_REST_DAYS))
          .clip(0, MAX_REST_DAYS)
          .alias("rest_days")
    )

    feat_cols = [f"{c}_ema{s}" for s in EMA_SPANS for c in EMA_BASE_COLS]
    return tg.with_columns(ema_exprs + [rest]).select(
        ["game_id", "team", "season", "week", "is_home", "rest_days"] + feat_cols
    )


# ---------------------------------------------------------------------------
# 3. Elo ratings — chronological, recorded pre-update (leakage-safe).
# ---------------------------------------------------------------------------
def _compute_elo(sched: pl.DataFrame) -> pl.DataFrame:
    games = sched.sort("gameday", "game_id").select(
        "game_id", "season", "home_team", "away_team",
        "result", "is_neutral_site", "is_played"
    )
    ratings: dict[str, float] = {}
    cur_season = None
    rows = []

    for r in games.iter_rows(named=True):
        if cur_season is None:
            cur_season = r["season"]
        if r["season"] != cur_season:  # offseason regression toward mean
            for t in ratings:
                ratings[t] = ELO_REGRESS * ratings[t] + (1 - ELO_REGRESS) * ELO_BASE
            cur_season = r["season"]

        home, away = r["home_team"], r["away_team"]
        eh = ratings.get(home, ELO_BASE)
        ea = ratings.get(away, ELO_BASE)
        rows.append({"game_id": r["game_id"], "home_elo_pre": eh, "away_elo_pre": ea})

        if r["is_played"] and r["result"] is not None:
            hfa = 0.0 if r["is_neutral_site"] else ELO_HFA
            exp_home = 1.0 / (1.0 + 10 ** ((ea - eh - hfa) / 400.0))
            actual = 1.0 if r["result"] > 0 else (0.5 if r["result"] == 0 else 0.0)
            delta = ELO_K * (actual - exp_home)
            ratings[home] = eh + delta
            ratings[away] = ea - delta

    return pl.DataFrame(rows).with_columns(
        (pl.col("home_elo_pre") - pl.col("away_elo_pre")).alias("elo_diff")
    )


# ---------------------------------------------------------------------------
# 4. Travel distance (haversine) for the away team.
# ---------------------------------------------------------------------------
def _haversine(lat1, lon1, lat2, lon2) -> float:
    r = 3958.8  # miles
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return r * 2 * math.asin(math.sqrt(a))


def _travel(sched: pl.DataFrame) -> pl.DataFrame:
    def miles(home: str, away: str) -> float | None:
        h, a = TEAM_COORDS.get(home), TEAM_COORDS.get(away)
        return _haversine(a[0], a[1], h[0], h[1]) if h and a else None

    out = sched.select("game_id", "home_team", "away_team")
    away_miles = [miles(r["home_team"], r["away_team"]) for r in out.iter_rows(named=True)]
    return out.select("game_id").with_columns(
        pl.Series("away_travel_miles", away_miles),
        pl.lit(0.0).alias("home_travel_miles"),
    )


# ---------------------------------------------------------------------------
# 5. Assemble gold_game_features.
# ---------------------------------------------------------------------------
def build_gold() -> pl.DataFrame:
    pbp = pl.read_delta(str(SILVER_DIR / "pbp"))
    sched = pl.read_delta(str(SILVER_DIR / "schedules"))

    timeline = _team_timeline(_team_game_stats(pbp), sched)
    elo = _compute_elo(sched)
    travel = _travel(sched)

    feat_cols = [c for c in timeline.columns
                 if c not in ("game_id", "team", "season", "week", "is_home")]
    home_feats = timeline.filter(pl.col("is_home")).drop("team", "is_home", "season", "week")
    away_feats = timeline.filter(~pl.col("is_home")).drop("team", "is_home", "season", "week")
    home_feats = home_feats.rename({c: f"home_{c}" for c in feat_cols})
    away_feats = away_feats.rename({c: f"away_{c}" for c in feat_cols})

    base = sched.select(
        "game_id", "season", "week", "gameday", "home_team", "away_team",
        "spread_line", "total_line", "home_moneyline", "away_moneyline",
        "div_game", "is_dome", "is_neutral_site", "home_field_advantage",
        "temp", "wind", "is_played", "result", "total",
    )

    g = (
        base
        .join(home_feats, on="game_id", how="left")
        .join(away_feats, on="game_id", how="left")
        .join(elo, on="game_id", how="left")
        .join(travel, on="game_id", how="left")
    )

    # Home-minus-away deltas (what the model actually keys on).
    delta_exprs = [
        (pl.col(f"home_{c}") - pl.col(f"away_{c}")).alias(f"{c}_diff")
        for c in feat_cols
    ]
    g = g.with_columns(
        delta_exprs
        + [(pl.col("away_travel_miles") - pl.col("home_travel_miles")).alias("travel_diff")]
    )

    # Targets (null on unplayed games -> inference set). Pushes/ties -> null.
    g = g.with_columns(
        pl.when(pl.col("is_played") & (pl.col("result") != 0))
          .then((pl.col("result") > 0).cast(pl.Int8)).alias("home_win"),
        pl.when(pl.col("is_played") & (pl.col("result") != pl.col("spread_line")))
          .then((pl.col("result") > pl.col("spread_line")).cast(pl.Int8)).alias("home_covered"),
        pl.when(pl.col("is_played")).then(pl.col("result")).alias("target_margin"),
    )
    return g.sort("season", "week", "game_id")


def run() -> int:
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    print("=== Gold build ===")
    g = build_gold()

    report = (
        dq.DataQualityReport("gold_game_features")
        .add(dq.expect_unique(g, ["game_id"]))
        .add(dq.expect_not_null(g, "home_team"))
        .add(dq.expect_in_range(g, "home_elo_pre", 1000, 2000))
        .add(dq.expect_in_range(g, "away_elo_pre", 1000, 2000))
    )
    report.print_summary()
    report.raise_if_failed()

    path = str(GOLD_DIR / "game_features")
    write_deltalake(path, g.to_arrow(), mode="overwrite",
                    partition_by=["season"], schema_mode="overwrite")
    try:
        DeltaTable(path).optimize.z_order(["week", "game_id"])
    except Exception as e:
        print(f"  (z-order skipped: {type(e).__name__})")

    trainable = g.filter(pl.col("home_win").is_not_null()).height
    print(f"  wrote gold/game_features: {g.height:,} games, {g.width} cols")
    print(f"  trainable (played, non-tie): {trainable:,}  |  future: "
          f"{g.filter(~pl.col('is_played')).height:,}")
    print("[DONE] Gold complete.")
    return 0
