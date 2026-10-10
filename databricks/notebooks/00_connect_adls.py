# Databricks notebook source
# MAGIC %md
# MAGIC # 00 — Connect Databricks to ADLS Gen2 (Phase 1)
# MAGIC
# MAGIC **Approach: direct ABFSS + OAuth (service principal), secrets from a Databricks secret scope.**
# MAGIC
# MAGIC We deliberately do **not** use `dbutils.fs.mount(...)`. Mounts are legacy, workspace-global,
# MAGIC and discouraged under Unity Catalog. Direct `abfss://` access is the modern, secure pattern:
# MAGIC credentials stay in the secret scope and are applied per-session via Spark config.
# MAGIC
# MAGIC Prereq: secret scope `nfl-adls` exists with keys `sp-client-id`, `sp-client-secret`, `sp-tenant-id`
# MAGIC (created in `scripts/az_setup.sh` step 6).

# COMMAND ----------

# ---- EDIT THIS ONE LINE ----
STORAGE_ACCOUNT = "stnflpredictXX"   # your ADLS Gen2 account name
SCOPE = "nfl-adls"
# ----------------------------

client_id     = dbutils.secrets.get(scope=SCOPE, key="sp-client-id")
client_secret = dbutils.secrets.get(scope=SCOPE, key="sp-client-secret")
tenant_id     = dbutils.secrets.get(scope=SCOPE, key="sp-tenant-id")

# OAuth config applied to this storage account for the current cluster session.
spark.conf.set(f"fs.azure.account.auth.type.{STORAGE_ACCOUNT}.dfs.core.windows.net", "OAuth")
spark.conf.set(
    f"fs.azure.account.oauth.provider.type.{STORAGE_ACCOUNT}.dfs.core.windows.net",
    "org.apache.hadoop.fs.azurebfs.oauth2.ClientCredsTokenProvider",
)
spark.conf.set(f"fs.azure.account.oauth2.client.id.{STORAGE_ACCOUNT}.dfs.core.windows.net", client_id)
spark.conf.set(f"fs.azure.account.oauth2.client.secret.{STORAGE_ACCOUNT}.dfs.core.windows.net", client_secret)
spark.conf.set(
    f"fs.azure.account.oauth2.client.endpoint.{STORAGE_ACCOUNT}.dfs.core.windows.net",
    f"https://login.microsoftonline.com/{tenant_id}/oauth2/token",
)

# Convenience base paths for the medallion layers.
BRONZE = f"abfss://bronze@{STORAGE_ACCOUNT}.dfs.core.windows.net/nfl"
SILVER = f"abfss://silver@{STORAGE_ACCOUNT}.dfs.core.windows.net/nfl"
GOLD   = f"abfss://gold@{STORAGE_ACCOUNT}.dfs.core.windows.net/nfl"
print("Configured. Base paths:\n ", BRONZE, "\n ", SILVER, "\n ", GOLD)

# COMMAND ----------

# MAGIC %md ## Smoke test: write + read a Delta table round-trip

# COMMAND ----------

from pyspark.sql import functions as F

test_df = spark.range(5).withColumn("hello", F.lit("adls-gen2-connected"))
(test_df.write.format("delta").mode("overwrite").save(f"{BRONZE}/_connectivity_check"))

check = spark.read.format("delta").load(f"{BRONZE}/_connectivity_check")
check.show()
assert check.count() == 5, "Round-trip failed"
print("✅ ADLS Gen2 read/write verified. Phase 1 complete.")

# COMMAND ----------

# Optional cleanup of the smoke-test table:
# dbutils.fs.rm(f"{BRONZE}/_connectivity_check", recurse=True)
