# Phase 6 — CI/CD & Portfolio Presentation

## Continuous Integration (`.github/workflows/ci.yml`)
Runs on every push and PR to any branch:
1. **Lint** — `ruff check src scripts tests` (import order, unused code, bugbear).
2. **Unit tests** — `pytest` (11 tests): DQ expectations, team-identity normalization,
   the EMA `shift(1)` leakage property, moneyline→probability conversion, and haversine distance.

The tests target the *correctness core* — the invariants that, if broken, silently corrupt results
(a leaky window, a mis-mapped relocated team). Fast, deterministic, no data download required.

## Continuous Deployment (`.github/workflows/deploy.yml`)
On push to the main branch (gated on CI):
1. `databricks bundle validate` → `deploy` → `run nfl_pipeline`.
2. The bundle (`databricks.yml`) defines the medallion job as code: **bronze → silver → gold →
   train**, chained by `depends_on`, all on one single-node job cluster.

Secrets required: `DATABRICKS_HOST`, `DATABRICKS_TOKEN`.

## Databricks Asset Bundle (`databricks.yml`)
Infrastructure-as-code for the *job* (not just the storage). The job cluster carries the ADLS
Gen2 OAuth config via **secret references** (`{{secrets/nfl-adls/...}}`), so notebooks run with no
inline credentials — the production-correct pattern.

## Portfolio README
The root `README.md` leads with the engineering thesis, a Mermaid architecture diagram, the honest
**model-vs-Vegas** results table, key highlights, and both replication paths ($0 local / <$5 Azure).

## Quality tooling
- `pyproject.toml` configures ruff (lint) and pytest (`pythonpath=src`).
- CLI entrypoints are allowed `E402` (they set `sys.path`/stdout encoding before imports).
