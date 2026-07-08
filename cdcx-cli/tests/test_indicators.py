import numpy as np
import pandas as pd
import pytest

from indicators.ema import ema
from indicators.atr import atr, true_range
from indicators.support_resistance import compute_support_resistance
from indicators.atr_ema_variant1 import compute_atr_ema_variant1


def make_ohlcv(n=60, seed=7):
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


def test_ema_matches_manual_recursive_formula():
    series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    length = 3
    result = ema(series, length)

    alpha = 2.0 / (length + 1)
    manual = [series[0]]
    for value in series[1:]:
        manual.append(alpha * value + (1 - alpha) * manual[-1])

    assert result.iloc[-1] == pytest.approx(manual[-1])


def test_true_range_and_atr_basic():
    df = pd.DataFrame({
        "open": [10, 11, 12, 11],
        "high": [12, 13, 13, 12],
        "low": [9, 10, 11, 10],
        "close": [11, 12, 11, 11.5],
    })
    tr = true_range(df)
    assert tr.iloc[0] == pytest.approx(3.0)  # first bar: high - low
    assert tr.iloc[1] == pytest.approx(max(13 - 10, abs(13 - 11), abs(10 - 11)))

    result = atr(df, length=2)
    assert (result.dropna() > 0).all()


def test_support_resistance_bands_bracket_ema():
    df = make_ohlcv()
    sr = compute_support_resistance(df, ema_length=10, atr_length=10, mult=2.0)
    valid = sr.dropna()
    assert (valid["bottom"] < valid["ema"]).all()
    assert (valid["ema"] < valid["top"]).all()


def test_atr_ema_variant1_hit_flags_match_price_comparison():
    df = make_ohlcv()
    signal = compute_atr_ema_variant1(df, ema_length=10, atr_length=10, sr_length=1.0)

    expected_support_hit = df["low"] <= signal["support"]
    expected_resistance_hit = df["high"] >= signal["resistance"]

    pd.testing.assert_series_equal(
        signal["support_hit"], expected_support_hit, check_names=False
    )
    pd.testing.assert_series_equal(
        signal["resistance_hit"], expected_resistance_hit, check_names=False
    )


def test_atr_ema_variant1_columns_present():
    df = make_ohlcv(n=30)
    signal = compute_atr_ema_variant1(df)
    assert list(signal.columns) == ["ema", "support", "resistance", "support_hit", "resistance_hit"]
    assert len(signal) == len(df)
