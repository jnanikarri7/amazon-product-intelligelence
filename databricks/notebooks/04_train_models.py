# Databricks notebook source
# MAGIC %md
# MAGIC # 04 — Model Training & MLflow Tracking (Phase 5)
# MAGIC
# MAGIC LightGBM + XGBoost on two targets, **walk-forward** validation, logged to MLflow and
# MAGIC registered. Logic mirror of `src/nfl/train.py`.
# MAGIC
# MAGIC On Databricks, MLflow tracking + the Model Registry are built in — no sqlite backend
# MAGIC needed; `mlflow.set_experiment("/Users/<you>/nfl")` points at the workspace tracking server.

# COMMAND ----------

# MAGIC %pip install -q lightgbm xgboost
# dbutils.library.restartPython()

# COMMAND ----------

import lightgbm as lgb
import mlflow
import numpy as np
import xgboost as xgb
from sklearn.metrics import accuracy_score, log_loss, mean_absolute_error, roc_auc_score

STORAGE_ACCOUNT = "stnflpredictXX"
GOLD = f"abfss://gold@{STORAGE_ACCOUNT}.dfs.core.windows.net/nfl"
TRAIN_WINDOW, FIRST_TEST_SEASON = 4, 2019

mlflow.set_experiment("/Shared/nfl_prediction")  # workspace tracking server

# COMMAND ----------

pdf = (spark.read.format("delta").load(f"{GOLD}/game_features")
          .toPandas())
for c in ["is_dome", "is_neutral_site"]:
    pdf[c] = pdf[c].astype("float")

feats = ([c for c in pdf.columns if c.endswith("_diff")]
         + ["spread_line", "total_line", "div_game", "home_field_advantage", "temp", "wind"])
last_season = int(pdf.loc[pdf["home_win"].notna(), "season"].max())

# COMMAND ----------

def walk_forward(df, target):
    d = df[df[target].notna()]
    for s in range(FIRST_TEST_SEASON, last_season + 1):
        tr = d[(d["season"] >= s - TRAIN_WINDOW) & (d["season"] < s)]
        te = d[d["season"] == s]
        if len(tr) and len(te):
            yield s, tr, te

def make(name, task):
    if name == "lightgbm":
        cls = lgb.LGBMRegressor if task == "reg" else lgb.LGBMClassifier
        return cls(n_estimators=300, learning_rate=0.03, num_leaves=15, subsample=0.8,
                   colsample_bytree=0.8, reg_lambda=1.0, verbose=-1, random_state=42)
    cls = xgb.XGBRegressor if task == "reg" else xgb.XGBClassifier
    return cls(n_estimators=300, learning_rate=0.03, max_depth=4, subsample=0.8,
               colsample_bytree=0.8, reg_lambda=1.0, tree_method="hist", random_state=42)

# COMMAND ----------

# MAGIC %md ## Classification targets (home_win, home_covered)

# COMMAND ----------

for target in ["home_win", "home_covered"]:
    for name in ["lightgbm", "xgboost"]:
        with mlflow.start_run(run_name=f"{name}_{target}"):
            mlflow.log_params({"model": name, "target": target, "train_window": TRAIN_WINDOW})
            ys, ps = [], []
            for s, tr, te in walk_forward(pdf, target):
                m = make(name, "clf"); m.fit(tr[feats], tr[target])
                p = m.predict_proba(te[feats])[:, 1]
                ys.append(te[target].values); ps.append(p)
                mlflow.log_metric("fold_auc", roc_auc_score(ys[-1], p), step=s)
            y, p = np.concatenate(ys), np.concatenate(ps)
            mlflow.log_metrics({"auc": roc_auc_score(y, p), "logloss": log_loss(y, p),
                                "accuracy": accuracy_score(y, (p >= 0.5))})
            full = pdf[pdf[target].notna()]
            final = make(name, "clf"); final.fit(full[feats], full[target])
            mlflow.sklearn.log_model(final, name="model", registered_model_name=f"nfl_{target}")

# COMMAND ----------

# MAGIC %md ## Regression target (margin) + Vegas baseline

# COMMAND ----------

for name in ["lightgbm", "xgboost"]:
    with mlflow.start_run(run_name=f"{name}_margin"):
        ys, ps = [], []
        for s, tr, te in walk_forward(pdf, "target_margin"):
            m = make(name, "reg"); m.fit(tr[feats], tr["target_margin"])
            ys.append(te["target_margin"].values); ps.append(m.predict(te[feats]))
        y, p = np.concatenate(ys), np.concatenate(ps)
        mlflow.log_metric("mae", mean_absolute_error(y, p))
        full = pdf[pdf["target_margin"].notna()]
        final = make(name, "reg"); final.fit(full[feats], full["target_margin"])
        mlflow.sklearn.log_model(final, name="model", registered_model_name="nfl_margin")

with mlflow.start_run(run_name="vegas_baseline"):
    tm = pdf[(pdf["season"] >= FIRST_TEST_SEASON) & pdf["target_margin"].notna()]
    mlflow.log_metric("margin_mae", mean_absolute_error(tm["target_margin"], tm["spread_line"]))
print("✅ Training complete. See Experiments + Models tabs in the workspace.")
