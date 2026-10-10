"""The DQ framework is the pipeline's safety net — verify each expectation
flags the bad case and passes the good one."""
import polars as pl
import pytest

from nfl import quality as dq


def test_expect_unique():
    good = pl.DataFrame({"id": [1, 2, 3]})
    bad = pl.DataFrame({"id": [1, 1, 3]})
    assert dq.expect_unique(good, ["id"]).passed
    assert not dq.expect_unique(bad, ["id"]).passed


def test_expect_not_null():
    df = pl.DataFrame({"x": [1, None, 3]})
    assert not dq.expect_not_null(df, "x").passed
    assert dq.expect_not_null(df, "x", max_null_frac=0.5).passed


def test_expect_in_range():
    df = pl.DataFrame({"epa": [-13.0, 0.0, 8.0]})
    assert dq.expect_in_range(df, "epa", -15, 15).passed
    assert not dq.expect_in_range(df, "epa", -10, 10).passed


def test_report_raises_on_failure():
    rep = dq.DataQualityReport("t").add(dq.expect_unique(pl.DataFrame({"id": [1, 1]}), ["id"]))
    with pytest.raises(ValueError):
        rep.raise_if_failed()
