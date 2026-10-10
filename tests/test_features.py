"""Leakage-safety and numeric helpers — the correctness core of the project."""
import polars as pl

from nfl.gold import _haversine
from nfl.train import _american_to_prob


def test_ema_shift_is_leakage_free():
    # The exact windowing used in gold.py: a game must never see its own value.
    s = pl.DataFrame({"team": ["A"] * 4, "x": [1.0, 2.0, 3.0, 4.0]})
    out = s.with_columns(
        pl.col("x").ewm_mean(span=4, adjust=False, min_samples=1).shift(1).over("team").alias("ema")
    )
    # First game has no prior -> null; later games never include the current row.
    assert out["ema"][0] is None
    assert out["ema"][1] == 1.0  # only game 1 informs game 2's feature


def test_american_to_prob():
    assert abs(_american_to_prob(-110) - 0.5238) < 1e-3
    assert abs(_american_to_prob(100) - 0.5) < 1e-9
    assert abs(_american_to_prob(-200) - 0.6667) < 1e-3
    assert _american_to_prob(None) is None
    assert _american_to_prob(float("nan")) is None


def test_haversine_known_distance():
    # Approx MetLife (NY) -> SoFi (LA) ~ 2440 miles.
    d = _haversine(40.8128, -74.0742, 34.0141, -118.2879)
    assert 2350 < d < 2550


def test_haversine_zero():
    assert _haversine(40.0, -74.0, 40.0, -74.0) == 0.0
