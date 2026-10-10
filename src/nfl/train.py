"""Phase 5 — MLOps training pipeline (local MLflow, LightGBM + XGBoost).

Design principles:
  * Time-based WALK-FORWARD validation (train seasons [N-W, N-1], test season N).
    Never random k-fold — that leaks the future into the past.
  * Every run logged to MLflow: params, per-fold + aggregate metrics, feature
    importance plot, model artifact. Best model registered to the Model Registry.
  * The Vegas line is logged as a baseline run so model skill is judged against the
    market, not in a vacuum.

Local MLflow uses a sqlite backend (registry needs a DB) + ./mlruns artifacts —
the same API you'd point at a Databricks tracking server.
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

import lightgbm as lgb
import matplotlib
import mlflow
import numpy as np
import polars as pl
import xgboost as xgb

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.metrics import (accuracy_score, brier_score_loss, log_loss,
                             mean_absolute_error, roc_auc_score)

from .config import GOLD_DIR, REPO_ROOT

TRAIN_WINDOW = 4           # seasons per training window (spec: N..N+3 -> test N+4)
FIRST_TEST_SEASON = 2019   # first season we can test (needs 4 prior seasons)

BOOL_COLS = ["is_dome", "is_neutral_site"]
MARKET_COLS = ["spread_line", "total_line"]
CONTEXT_COLS = ["div_game", "home_field_advantage", "temp", "wind"]


def _mlflow_uri() -> str:
    return f"sqlite:///{(REPO_ROOT / 'mlflow.db').as_posix()}"


def load_modeling_df() -> pl.DataFrame:
    g = pl.read_delta(str(GOLD_DIR / "game_features"))
    # Cast bools to int8 so both tree libs accept them.
    return g.with_columns([pl.col(c).cast(pl.Int8) for c in BOOL_COLS if c in g.columns])


def feature_cols(df: pl.DataFrame) -> list[str]:
    diffs = [c for c in df.columns if c.endswith("_diff")]
    return diffs + MARKET_COLS + CONTEXT_COLS


# ---- Vegas baselines --------------------------------------------------------
def _american_to_prob(ml: float | None) -> float | None:
    if ml is None or np.isnan(ml):
        return None
    return (-ml) / (-ml + 100) if ml < 0 else 100 / (ml + 100)


def vegas_win_prob(df: pl.DataFrame) -> np.ndarray:
    """De-vigged home win probability from the moneyline."""
    hp = df["home_moneyline"].map_elements(_american_to_prob, return_dtype=pl.Float64).to_numpy()
    ap = df["away_moneyline"].map_elements(_american_to_prob, return_dtype=pl.Float64).to_numpy()
    return hp / (hp + ap)


# ---- Walk-forward -----------------------------------------------------------
def walk_forward(df: pl.DataFrame, target: str, last_season: int):
    """Yield (test_season, train_df, test_df) with a sliding TRAIN_WINDOW."""
    d = df.filter(pl.col(target).is_not_null())
    for test_season in range(FIRST_TEST_SEASON, last_season + 1):
        train = d.filter((pl.col("season") >= test_season - TRAIN_WINDOW)
                         & (pl.col("season") < test_season))
        test = d.filter(pl.col("season") == test_season)
        if train.height and test.height:
            yield test_season, train, test


# ---- Model factories --------------------------------------------------------
def _make_model(name: str, task: str):
    if name == "lightgbm":
        cls = lgb.LGBMRegressor if task == "reg" else lgb.LGBMClassifier
        return cls(n_estimators=300, learning_rate=0.03, num_leaves=15,
                   subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0,
                   min_child_samples=20, verbose=-1, random_state=42)
    cls = xgb.XGBRegressor if task == "reg" else xgb.XGBClassifier
    return cls(n_estimators=300, learning_rate=0.03, max_depth=4,
               subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0,
               tree_method="hist", random_state=42,
               **({} if task == "reg" else {"eval_metric": "logloss"}))


def _importance_plot(model, feats: list[str], title: str) -> str:
    imp = getattr(model, "feature_importances_", None)
    order = np.argsort(imp)[-20:]
    plt.figure(figsize=(7, 6))
    plt.barh([feats[i] for i in order], imp[order])
    plt.title(title)
    plt.tight_layout()
    path = os.path.join(tempfile.gettempdir(), f"{title.replace(' ', '_')}.png")
    plt.savefig(path, dpi=110)
    plt.close()
    return path


# ---- Training routines ------------------------------------------------------
def _train_classification(name: str, target: str, df: pl.DataFrame,
                          feats: list[str], last_season: int) -> dict:
    oof_y, oof_p = [], []
    with mlflow.start_run(run_name=name):
        mlflow.log_params({"model": name, "target": target, "task": "classification",
                           "train_window": TRAIN_WINDOW, "n_features": len(feats)})
        for season, tr, te in walk_forward(df, target, last_season):
            model = _make_model(name, "clf")
            model.fit(tr.select(feats).to_pandas(), tr[target].to_numpy())
            p = model.predict_proba(te.select(feats).to_pandas())[:, 1]
            y = te[target].to_numpy()
            oof_y.append(y); oof_p.append(p)
            mlflow.log_metrics({"fold_auc": roc_auc_score(y, p),
                                "fold_logloss": log_loss(y, p, labels=[0, 1])}, step=season)

        y = np.concatenate(oof_y); p = np.concatenate(oof_p)
        metrics = {"auc": roc_auc_score(y, p), "logloss": log_loss(y, p),
                   "brier": brier_score_loss(y, p),
                   "accuracy": accuracy_score(y, (p >= 0.5).astype(int))}
        mlflow.log_metrics(metrics)

        # Final model on all trainable seasons -> artifact + importance + registry.
        full = df.filter(pl.col(target).is_not_null())
        final = _make_model(name, "clf")
        final.fit(full.select(feats).to_pandas(), full[target].to_numpy())
        mlflow.log_artifact(_importance_plot(final, feats, f"{name} {target} importance"))
        info = mlflow.sklearn.log_model(final, name="model",
                                        serialization_format="cloudpickle",
                                        registered_model_name=f"nfl_{target}")
        metrics["version"] = info.registered_model_version
        print(f"  {name:9s} {target:13s} AUC={metrics['auc']:.4f} "
              f"LogLoss={metrics['logloss']:.4f} Acc={metrics['accuracy']:.3f}")
        return metrics


def _train_regression(name: str, df: pl.DataFrame, feats: list[str],
                      last_season: int) -> dict:
    oof_y, oof_p = [], []
    with mlflow.start_run(run_name=name):
        mlflow.log_params({"model": name, "target": "target_margin", "task": "regression"})
        for season, tr, te in walk_forward(df, "target_margin", last_season):
            model = _make_model(name, "reg")
            model.fit(tr.select(feats).to_pandas(), tr["target_margin"].to_numpy())
            p = model.predict(te.select(feats).to_pandas())
            oof_y.append(te["target_margin"].to_numpy()); oof_p.append(p)
            mlflow.log_metrics({"fold_mae": mean_absolute_error(oof_y[-1], p)}, step=season)
        y = np.concatenate(oof_y); p = np.concatenate(oof_p)
        metrics = {"mae": mean_absolute_error(y, p),
                   "rmse": float(np.sqrt(np.mean((y - p) ** 2)))}
        mlflow.log_metrics(metrics)
        full = df.filter(pl.col("target_margin").is_not_null())
        final = _make_model(name, "reg")
        final.fit(full.select(feats).to_pandas(), full["target_margin"].to_numpy())
        mlflow.log_artifact(_importance_plot(final, feats, f"{name} margin importance"))
        mlflow.sklearn.log_model(final, name="model", serialization_format="cloudpickle",
                                 registered_model_name="nfl_margin")
        print(f"  {name:9s} target_margin MAE={metrics['mae']:.3f} RMSE={metrics['rmse']:.3f}")
        return metrics


def _log_vegas_baseline(df: pl.DataFrame, last_season: int) -> None:
    with mlflow.start_run(run_name="vegas_baseline"):
        # Win: moneyline implied prob on the same test seasons.
        test = df.filter((pl.col("season") >= FIRST_TEST_SEASON)
                         & (pl.col("home_win").is_not_null())
                         & pl.col("home_moneyline").is_not_null())
        y = test["home_win"].to_numpy()
        p = vegas_win_prob(test)
        mlflow.log_metrics({"win_auc": roc_auc_score(y, p),
                            "win_logloss": log_loss(y, p),
                            "win_accuracy": accuracy_score(y, (p >= 0.5).astype(int))})
        # Margin: the spread line IS Vegas's margin prediction.
        tm = df.filter((pl.col("season") >= FIRST_TEST_SEASON)
                       & pl.col("target_margin").is_not_null()
                       & pl.col("spread_line").is_not_null())
        mae = mean_absolute_error(tm["target_margin"].to_numpy(), tm["spread_line"].to_numpy())
        mlflow.log_metric("margin_mae", mae)
        print(f"  VEGAS     win AUC={roc_auc_score(y, p):.4f} "
              f"LogLoss={log_loss(y, p):.4f} Acc={accuracy_score(y, (p >= 0.5).astype(int)):.3f} "
              f"| margin MAE={mae:.3f}")


def run() -> int:
    mlflow.set_tracking_uri(_mlflow_uri())
    df = load_modeling_df()
    feats = feature_cols(df)
    last_season = int(df.filter(pl.col("home_win").is_not_null())["season"].max())
    print(f"=== Training | {len(feats)} features | test seasons "
          f"{FIRST_TEST_SEASON}-{last_season} | window {TRAIN_WINDOW} ===")

    results: dict[str, dict] = {}
    mlflow.set_experiment("nfl_home_win")
    for m in ("lightgbm", "xgboost"):
        results[f"{m}_win"] = _train_classification(m, "home_win", df, feats, last_season)
    mlflow.set_experiment("nfl_home_covered")
    for m in ("lightgbm", "xgboost"):
        results[f"{m}_cover"] = _train_classification(m, "home_covered", df, feats, last_season)
    mlflow.set_experiment("nfl_margin")
    for m in ("lightgbm", "xgboost"):
        results[f"{m}_margin"] = _train_regression(m, df, feats, last_season)
    mlflow.set_experiment("nfl_home_win")
    _log_vegas_baseline(df, last_season)

    best = max(("lightgbm", "xgboost"), key=lambda m: results[f"{m}_win"]["auc"])
    champ_version = results[f"{best}_win"]["version"]
    mlflow.MlflowClient().set_registered_model_alias("nfl_home_win", "champion", champ_version)
    print(f"\n[DONE] Champion win model: {best} -> nfl_home_win v{champ_version} "
          f"(AUC {results[f'{best}_win']['auc']:.4f}), aliased 'champion'.")
    print(f"View runs:  mlflow ui --backend-store-uri {_mlflow_uri()}")
    return 0
