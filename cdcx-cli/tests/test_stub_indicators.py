import numpy as np
import pandas as pd
import pytest

from indicators.fibonacci import compute_fibonacci_levels
from indicators.fixed_volume_profile import compute_volume_profile
from indicators.anchored_volume_profile import compute_anchored_volume_profile
from indicators.fair_value_gap import detect_fair_value_gaps
from indicators.order_blocks import detect_order_blocks
from indicators.liquidity import detect_liquidity_levels


def make_ohlcv(n=60, seed=3):
    rng = np.random.default_rng(seed)
    index = pd.date_range("2024-01-01", periods=n, freq="h")
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    high = close + rng.uniform(0.1, 1.0, n)
    low = close - rng.uniform(0.1, 1.0, n)
    open_ = close + rng.normal(0, 0.3, n)
    volume = rng.uniform(10, 100, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=index
    )


def test_fibonacci_levels_bracket_high_low():
    df = make_ohlcv()
    result = compute_fibonacci_levels(df, lookback=40)
    levels = result["levels"]
    assert levels[0.0] in (result["high"], result["low"])
    assert levels[1.0] in (result["high"], result["low"])
    assert min(result["low"], result["high"]) <= levels[0.5] <= max(result["low"], result["high"])


def test_volume_profile_poc_within_range_and_conserves_volume():
    df = make_ohlcv()
    result = compute_volume_profile(df, bins=10)
    assert df["low"].min() <= result["poc"] <= df["high"].max()
    assert result["profile"]["volume"].sum() == pytest.approx(df["volume"].sum())


def test_anchored_volume_profile_uses_slice():
    df = make_ohlcv()
    anchored = compute_anchored_volume_profile(df, anchor=30, bins=10)
    full = compute_volume_profile(df, bins=10)
    assert anchored["profile"]["volume"].sum() < full["profile"]["volume"].sum()


def test_fair_value_gap_detects_bullish_gap():
    df = pd.DataFrame({
        "open": [10, 11, 15],
        "high": [10.5, 11.5, 16],
        "low": [9.5, 10.5, 14.5],
        "close": [10.2, 11.2, 15.5],
    })
    gaps = detect_fair_value_gaps(df)
    assert len(gaps) == 1
    assert gaps[0]["type"] == "bullish"
    assert gaps[0]["bottom"] == 10.5
    assert gaps[0]["top"] == 14.5


def test_order_blocks_returns_list_without_error():
    df = make_ohlcv(n=50)
    blocks = detect_order_blocks(df, lookahead=3, impulse_mult=0.5)
    assert isinstance(blocks, list)
    for block in blocks:
        assert block["type"] in ("bullish", "bearish")
        assert block["top"] >= block["bottom"]


def test_liquidity_levels_returns_expected_keys():
    df = make_ohlcv(n=80)
    levels = detect_liquidity_levels(df)
    assert set(levels.keys()) == {"sell_side", "buy_side"}
    for pool in levels["sell_side"] + levels["buy_side"]:
        assert "price" in pool and "indices" in pool
