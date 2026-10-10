# 🏈 NFL Prediction Platform

Production-grade, cost-optimized NFL game prediction platform built on **Azure Databricks**,
**ADLS Gen2**, **Delta Lake**, **MLflow**, and **LightGBM/XGBoost** — showcasing modern Data
Engineering & MLOps practices on a **< $5/month** budget (Azure for Students).

> 🚧 Built in 6 phases. This README is a stub; the full FAANG-ready version lands in **Phase 6**.

## Medallion architecture

```
nflreadpy ──► Bronze (raw Delta) ──► Silver (clean + DQ) ──► Gold (features) ──► MLflow (LightGBM/XGBoost)
```

## Build phases
- [x] **Phase 1 — Environment & cost-optimized architecture** → see [`docs/phase1_architecture.md`](docs/phase1_architecture.md)
- [x] **Phase 2 — Bronze ingestion** (`nflreadpy`, 2015–present) → see [`docs/phase2_bronze.md`](docs/phase2_bronze.md)
- [x] **Phase 3 — Silver** (cleaning, DQ, Z-ORDER) → see [`docs/phase3_silver.md`](docs/phase3_silver.md)
- [x] **Phase 4 — Gold** (leakage-safe feature engineering) → see [`docs/phase4_gold.md`](docs/phase4_gold.md)
- [x] **Phase 5 — MLOps** (walk-forward CV, MLflow tracking + registry) → see [`docs/phase5_mlops.md`](docs/phase5_mlops.md)
- [ ] Phase 6 — CI/CD (GitHub Actions + Databricks Workflows) & portfolio README

## Repo layout
```
infra/terraform/     IaC: resource group, ADLS Gen2, SP, Databricks workspace
scripts/             Azure CLI equivalent of the Terraform
databricks/          cluster_config.json + notebooks (00_connect_adls.py …)
docs/                architecture & phase notes
.github/workflows/   CI/CD (Phase 6)
```

## Phase 1 quickstart
```bash
az login
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # edit storage_account_name
terraform init && terraform apply
```
Then create the Databricks secret scope and run `databricks/notebooks/00_connect_adls.py`.
Full details: [`docs/phase1_architecture.md`](docs/phase1_architecture.md).
