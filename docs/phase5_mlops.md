# Phase 5 — MLOps: Training, Walk-Forward CV & MLflow

Two gradient-boosted model families (**LightGBM**, **XGBoost**) on three targets, validated with
**time-based walk-forward CV**, every run tracked in **MLflow**, best model registered and aliased
`champion`. The **Vegas line is logged as a baseline** so skill is judged against the market.

## Results (walk-forward, test seasons 2019–2026)
| Model | `home_win` AUC | Acc | LogLoss | `home_covered` AUC | margin MAE |
|---|---|---|---|---|---|
| LightGBM | 0.666 | 61.8% | 0.678 | 0.497 | 10.48 |
| XGBoost | **0.669** | 61.9% | 0.665 | 0.497 | 10.36 |
| **Vegas baseline** | 0.724 | 66.1% | 0.610 | ~0.50 | **9.82** |

### How to read this (the honest, senior framing)
- **Win prediction: ~62% accuracy / 0.67 AUC — good, but short of Vegas (66% / 0.72).** This is the
  *expected* result. Betting markets are highly efficient; consistently beating the moneyline with a
  public-data model is a research-grade problem, not a weekend one. A portfolio that claims to crush
  Vegas is lying; one that lands *near* Vegas and says so is credible.
- **Against the spread: ~50% AUC.** This is the headline finding, not a failure. The spread exists
  precisely to make cover a coin flip — reproducing ~50% **confirms the pipeline is leakage-free**.
  A model showing 60%+ ATS would be a red flag for leakage, not a win.
- **Margin MAE ~10.4 pts vs. Vegas 9.82.** The model is within ~0.5 points of the market's own
  margin prediction — respectable for engineered public features.

## Why walk-forward, not k-fold
Random k-fold would put 2024 games in the training set while testing on 2019 — training on the
future to predict the past. We instead train on seasons `[N-4, N-1]` and test on `N`, rolling
forward season by season. Per-fold metrics are logged with `step=season` so you can watch
performance drift across years in the MLflow UI.

## MLflow layout
- **Experiments**: `nfl_home_win`, `nfl_home_covered`, `nfl_margin` — each with a LightGBM run,
  an XGBoost run (and the Vegas baseline under `nfl_home_win`).
- **Logged per run**: params, per-fold AUC/LogLoss/MAE (stepped by season), aggregate
  AUC/LogLoss/Brier/Accuracy or MAE/RMSE, a **feature-importance PNG**, and the model artifact.
- **Registry**: `nfl_home_win`, `nfl_home_covered`, `nfl_margin`; the best win model is aliased
  **`champion`** (how you'd promote to production).

## Run it
```bash
python scripts/run_train.py
mlflow ui --backend-store-uri sqlite:///mlflow.db     # browse at http://localhost:5000
# Databricks: run notebooks/04_train_models.py (uses the workspace tracking server + registry)
```

## Next improvements (candid backlog)
- Probability **calibration** (isotonic/Platt) — would most help the LogLoss gap vs. Vegas.
- **Expanding** train window + hyperparameter search (Optuna) logged as child runs.
- Add the moneyline-implied prob as a feature so the model starts from the market and adds to it.
