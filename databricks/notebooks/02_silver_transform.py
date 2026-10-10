# Databricks notebook source
# MAGIC %md
# MAGIC # 02 — Silver Transform (Phase 3)
# MAGIC
# MAGIC Bronze → Silver: dedupe, drop special-teams / garbage-time / null-possession plays,
# MAGIC impute dome weather, flag neutral sites, enforce schema + range checks, then
# MAGIC `OPTIMIZE ... ZORDER BY`. PySpark logic mirror of `src/nfl/silver.py`.

# COMMAND ----------

from pyspark.sql import functions as F

STORAGE_ACCOUNT = "stnflpredictXX"   # must match 00_connect_adls
BRONZE = f"abfss://bronze@{STORAGE_ACCOUNT}.dfs.core.windows.net/nfl"
SILVER = f"abfss://silver@{STORAGE_ACCOUNT}.dfs.core.windows.net/nfl"

EPA_LO, EPA_HI = -15.0, 15.0
GARBAGE_TIME_SECONDS, GARBAGE_TIME_MARGIN = 900, 21

# COMMAND ----------

# MAGIC %md ## silver_pbp

# COMMAND ----------

pbp = spark.read.format("delta").load(f"{BRONZE}/pbp")

silver_pbp = (
    pbp.dropDuplicates(["game_id", "play_id"])
       .filter(F.col("posteam").isNotNull())
       .filter(((F.col("pass") == 1) | (F.col("rush") == 1))
               & (F.coalesce(F.col("special"), F.lit(0)) == 0))
       .filter(F.col("epa").isNotNull())
       .withColumn("is_garbage_time",
                   (F.col("game_seconds_remaining") <= GARBAGE_TIME_SECONDS)
                   & (F.abs(F.col("score_differential")) > GARBAGE_TIME_MARGIN))
       .filter(~F.col("is_garbage_time"))
)

# Range checks (fail fast if violated).
bad_epa = silver_pbp.filter((F.col("epa") < EPA_LO) | (F.col("epa") > EPA_HI)).count()
assert bad_epa == 0, f"{bad_epa} EPA values out of range"

(silver_pbp.write.format("delta").mode("overwrite")
    .partitionBy("season").save(f"{SILVER}/pbp"))
spark.sql(f"OPTIMIZE delta.`{SILVER}/pbp` ZORDER BY (game_id, week)")
print(f"silver_pbp rows: {silver_pbp.count():,}")

# COMMAND ----------

# MAGIC %md ## silver_schedules

# COMMAND ----------

sched = spark.read.format("delta").load(f"{BRONZE}/schedules").dropDuplicates(["game_id"])

silver_sched = (
    sched
    .withColumn("is_dome", F.col("roof").isin("dome", "closed"))
    .withColumn("is_neutral_site", F.col("location") == "Neutral")
    .withColumn("has_betting_line", F.col("spread_line").isNotNull())
    .withColumn("is_played", F.col("result").isNotNull())
    .withColumn("temp", F.when(F.col("roof").isin("dome", "closed") & F.col("temp").isNull(),
                               F.lit(70)).otherwise(F.col("temp")))
    .withColumn("wind", F.when(F.col("roof").isin("dome", "closed") & F.col("wind").isNull(),
                               F.lit(0)).otherwise(F.col("wind")))
    .withColumn("home_field_advantage",
                F.when(F.col("location") == "Neutral", F.lit(0)).otherwise(F.lit(1)))
)

(silver_sched.write.format("delta").mode("overwrite")
    .partitionBy("season").save(f"{SILVER}/schedules"))
spark.sql(f"OPTIMIZE delta.`{SILVER}/schedules` ZORDER BY (game_id, week)")
print(f"silver_schedules rows: {silver_sched.count():,}")

# COMMAND ----------

# MAGIC %md ## silver_player_stats

# COMMAND ----------

ps = (spark.read.format("delta").load(f"{BRONZE}/player_stats")
         .dropDuplicates(["player_id", "season", "week"]))
(ps.write.format("delta").mode("overwrite").partitionBy("season")
    .save(f"{SILVER}/player_stats"))
spark.sql(f"OPTIMIZE delta.`{SILVER}/player_stats` ZORDER BY (player_id, week)")
print(f"silver_player_stats rows: {ps.count():,}")
print("✅ Silver complete.")
