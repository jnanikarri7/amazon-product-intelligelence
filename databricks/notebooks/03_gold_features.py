# Databricks notebook source
# MAGIC %md
# MAGIC # 03 — Gold Feature Engineering (Phase 4)
# MAGIC
# MAGIC Leakage-safe `gold_game_features`: one row per game, home-vs-away deltas, targets on
# MAGIC played games. PySpark logic mirror of `src/nfl/gold.py`.
# MAGIC
# MAGIC **Leakage controls:** rolling EMAs are `shift(1)` per team (via `applyInPandas`);
# MAGIC Elo is recorded pre-update, iterating in date order. Betting lines are features;
# MAGIC scores/results are targets only.

# COMMAND ----------

import pandas as pd
from pyspark.sql import Window
from pyspark.sql import functions as F

STORAGE_ACCOUNT = "stnflpredictXX"
SILVER = f"abfss://silver@{STORAGE_ACCOUNT}.dfs.core.windows.net/nfl"
GOLD = f"abfss://gold@{STORAGE_ACCOUNT}.dfs.core.windows.net/nfl"

EMA_SPANS = [4, 8]
EMA_BASE = ["off_epa", "def_epa", "off_pass_epa", "off_rush_epa",
            "def_pass_epa", "def_rush_epa", "off_cpoe", "giveaways", "takeaways"]
ELO_K, ELO_HFA, ELO_BASE, ELO_REGRESS = 20.0, 55.0, 1500.0, 0.75

# COMMAND ----------

# MAGIC %md ## 1. Per-team, per-game box score from PBP

# COMMAND ----------

pbp = spark.read.format("delta").load(f"{SILVER}/pbp")

off = (pbp.groupBy("game_id", "posteam").agg(
        F.count(F.lit(1)).alias("off_plays"),
        F.mean("epa").alias("off_epa"),
        F.mean(F.when(F.col("pass") == 1, F.col("epa"))).alias("off_pass_epa"),
        F.mean(F.when(F.col("rush") == 1, F.col("epa"))).alias("off_rush_epa"),
        F.mean("cpoe").alias("off_cpoe"),
        (F.sum("interception") + F.sum("fumble_lost")).alias("giveaways"))
       .withColumnRenamed("posteam", "team"))

deff = (pbp.groupBy("game_id", "defteam").agg(
        F.mean("epa").alias("def_epa"),
        F.mean(F.when(F.col("pass") == 1, F.col("epa"))).alias("def_pass_epa"),
        F.mean(F.when(F.col("rush") == 1, F.col("epa"))).alias("def_rush_epa"),
        (F.sum("interception") + F.sum("fumble_lost")).alias("takeaways"))
        .withColumnRenamed("defteam", "team"))

team_game = off.join(deff, ["game_id", "team"], "inner")

# COMMAND ----------

# MAGIC %md ## 2. Timeline + leakage-safe EMAs (applyInPandas per team)

# COMMAND ----------

sched = spark.read.format("delta").load(f"{SILVER}/schedules")
ctx = sched.select("game_id", "season", "week", "gameday", "home_team", "away_team")
tg = (team_game.join(ctx, "game_id", "inner")
         .withColumn("game_date", F.to_date("gameday"))
         .withColumn("is_home", F.col("team") == F.col("home_team")))

ema_out_cols = [f"{c}_ema{s}" for s in EMA_SPANS for c in EMA_BASE]
out_schema = (tg.select("game_id", "team", "season", "week", "is_home").schema)
for name in ema_out_cols + ["rest_days"]:
    from pyspark.sql.types import DoubleType, StructField
    out_schema = out_schema.add(StructField(name, DoubleType()))


def _per_team(pdf: pd.DataFrame) -> pd.DataFrame:
    pdf = pdf.sort_values(["game_date", "game_id"]).reset_index(drop=True)
    for s in EMA_SPANS:
        for c in EMA_BASE:
            pdf[f"{c}_ema{s}"] = pdf[c].ewm(span=s, adjust=False).mean().shift(1)
    same = pdf["season"].eq(pdf["season"].shift(1))
    rest = (pdf["game_date"] - pdf["game_date"].shift(1)).dt.days
    pdf["rest_days"] = rest.where(same, 14).clip(0, 14)
    return pdf[["game_id", "team", "season", "week", "is_home"] + ema_out_cols + ["rest_days"]]


timeline = tg.groupBy("team").applyInPandas(_per_team, schema=out_schema)

# COMMAND ----------

# MAGIC %md ## 3. Elo — driver-side chronological iteration (inherently sequential)

# COMMAND ----------

games_pd = (sched.select("game_id", "season", "home_team", "away_team",
                         "result", "is_neutral_site", "is_played")
            .orderBy("gameday", "game_id").toPandas())

ratings, cur_season, rows = {}, None, []
for r in games_pd.itertuples(index=False):
    if cur_season is None:
        cur_season = r.season
    if r.season != cur_season:
        ratings = {t: ELO_REGRESS * v + (1 - ELO_REGRESS) * ELO_BASE for t, v in ratings.items()}
        cur_season = r.season
    eh, ea = ratings.get(r.home_team, ELO_BASE), ratings.get(r.away_team, ELO_BASE)
    rows.append((r.game_id, eh, ea))
    if r.is_played and r.result is not None:
        hfa = 0.0 if r.is_neutral_site else ELO_HFA
        exp = 1.0 / (1.0 + 10 ** ((ea - eh - hfa) / 400.0))
        actual = 1.0 if r.result > 0 else (0.5 if r.result == 0 else 0.0)
        d = ELO_K * (actual - exp)
        ratings[r.home_team], ratings[r.away_team] = eh + d, ea - d

elo = spark.createDataFrame(rows, ["game_id", "home_elo_pre", "away_elo_pre"]) \
           .withColumn("elo_diff", F.col("home_elo_pre") - F.col("away_elo_pre"))

# COMMAND ----------

# MAGIC %md ## 4. Assemble + targets

# COMMAND ----------

feat_cols = ema_out_cols + ["rest_days"]
home = timeline.filter("is_home").drop("team", "is_home", "season", "week")
away = timeline.filter("not is_home").drop("team", "is_home", "season", "week")
for c in feat_cols:
    home = home.withColumnRenamed(c, f"home_{c}")
    away = away.withColumnRenamed(c, f"away_{c}")

base = sched.select("game_id", "season", "week", "home_team", "away_team",
                    "spread_line", "total_line", "div_game", "is_dome",
                    "is_neutral_site", "home_field_advantage", "temp", "wind",
                    "is_played", "result", "total")

g = base.join(home, "game_id", "left").join(away, "game_id", "left").join(elo, "game_id", "left")
for c in feat_cols:
    g = g.withColumn(f"{c}_diff", F.col(f"home_{c}") - F.col(f"away_{c}"))

g = (g.withColumn("home_win", F.when(F.col("is_played") & (F.col("result") != 0),
                                     (F.col("result") > 0).cast("int")))
      .withColumn("home_covered", F.when(F.col("is_played") & (F.col("result") != F.col("spread_line")),
                                         (F.col("result") > F.col("spread_line")).cast("int")))
      .withColumn("target_margin", F.when(F.col("is_played"), F.col("result"))))

(g.write.format("delta").mode("overwrite").partitionBy("season").save(f"{GOLD}/game_features"))
spark.sql(f"OPTIMIZE delta.`{GOLD}/game_features` ZORDER BY (week, game_id)")
print(f"gold_game_features rows: {g.count():,}")
print("✅ Gold complete.")
