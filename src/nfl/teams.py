"""Canonical team-identity normalization across franchise relocations.

nflverse PBP uses current team codes; the schedules table keeps the historical
code for pre-relocation seasons (SD, STL, OAK). Conforming both to a single
canonical code is essential — otherwise home/away joins break and Elo treats a
relocated franchise as two different teams.
"""
from __future__ import annotations

import polars as pl

# historical/alias -> current canonical code
TEAM_NORMALIZE: dict[str, str] = {
    "SD": "LAC",   # San Diego -> Los Angeles Chargers (2017)
    "STL": "LAR",  # St. Louis -> Los Angeles Rams (2016)
    "LA": "LAR",   # some sources use LA for the Rams
    "OAK": "LV",   # Oakland -> Las Vegas Raiders (2020)
    "JAC": "JAX",  # Jacksonville alias
}


def normalize(col: str) -> pl.Expr:
    """polars expr that maps a team-code column to its canonical code (idempotent)."""
    return pl.col(col).replace(TEAM_NORMALIZE).alias(col)
