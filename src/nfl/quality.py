"""Lightweight data-quality framework (local analogue of Great Expectations).

Each `expect_*` returns a QualityResult. A `DataQualityReport` collects them,
prints a readable summary, and can hard-fail the pipeline on any violation —
the same contract a Great Expectations suite enforces on Databricks.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import polars as pl


@dataclass
class QualityResult:
    check: str
    column: str
    passed: bool
    detail: str = ""


@dataclass
class DataQualityReport:
    dataset: str
    results: list[QualityResult] = field(default_factory=list)

    def add(self, r: QualityResult) -> DataQualityReport:
        self.results.append(r)
        return self

    @property
    def failures(self) -> list[QualityResult]:
        return [r for r in self.results if not r.passed]

    def print_summary(self) -> None:
        print(f"\n  DQ report [{self.dataset}] — {len(self.results)} checks, "
              f"{len(self.failures)} failed")
        for r in self.results:
            flag = "PASS" if r.passed else "FAIL"
            print(f"    [{flag}] {r.check}({r.column}) {r.detail}")

    def raise_if_failed(self) -> None:
        if self.failures:
            msgs = "; ".join(f"{r.check}({r.column}) {r.detail}" for r in self.failures)
            raise ValueError(f"[{self.dataset}] data quality failed: {msgs}")


# ---- Expectations -----------------------------------------------------------
def expect_unique(df: pl.DataFrame, cols: list[str]) -> QualityResult:
    dupes = df.height - df.select(cols).n_unique()
    return QualityResult("unique", "+".join(cols), dupes == 0, f"{dupes} duplicate keys")


def expect_not_null(df: pl.DataFrame, col: str, max_null_frac: float = 0.0) -> QualityResult:
    frac = df[col].null_count() / max(df.height, 1)
    return QualityResult("not_null", col, frac <= max_null_frac,
                         f"{frac:.3%} null (allowed {max_null_frac:.0%})")


def expect_in_range(df: pl.DataFrame, col: str, lo: float, hi: float) -> QualityResult:
    vals = df[col].drop_nulls()
    bad = vals.filter((vals < lo) | (vals > hi)).len()
    rng = f"[{vals.min()}, {vals.max()}]" if vals.len() else "[empty]"
    return QualityResult("in_range", col, bad == 0, f"{bad} outside [{lo},{hi}]; actual {rng}")


def expect_values_in_set(df: pl.DataFrame, col: str, allowed: set) -> QualityResult:
    seen = set(df[col].drop_nulls().unique().to_list())
    extra = seen - allowed
    return QualityResult("in_set", col, not extra, f"unexpected values {sorted(extra)[:5]}")
