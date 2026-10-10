"""Team-identity normalization is load-bearing: a miss silently breaks home/away
joins and splits a relocated franchise's Elo. These tests lock the mapping down."""
import polars as pl

from nfl.teams import TEAM_NORMALIZE, normalize


def test_relocations_map_to_current_codes():
    assert TEAM_NORMALIZE["SD"] == "LAC"
    assert TEAM_NORMALIZE["STL"] == "LAR"
    assert TEAM_NORMALIZE["OAK"] == "LV"


def test_normalize_expr_rewrites_historical_and_keeps_current():
    df = pl.DataFrame({"home_team": ["SD", "STL", "OAK", "KC", "NE"]})
    out = df.with_columns(normalize("home_team"))["home_team"].to_list()
    assert out == ["LAC", "LAR", "LV", "KC", "NE"]


def test_normalize_is_idempotent():
    df = pl.DataFrame({"t": ["LAC", "LAR", "LV"]})
    once = df.with_columns(normalize("t"))
    twice = once.with_columns(normalize("t"))
    assert once["t"].to_list() == twice["t"].to_list()
