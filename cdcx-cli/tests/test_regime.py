import numpy as np
import pandas as pd

from indicators.regime import compute_adx, compute_regime, REGIME_TREND, REGIME_RANGE


def make_trending_ohlcv(n=100, drift=0.6, noise=0.05, seed=1):
    """Steady drift with small noise: should read as a strongly trending market."""
    rng = np.random.default_rng(seed)
    index = pd.date_range("2024-01-01", periods=n, freq="h")
    close = 100 + np.cumsum(np.full(n, drift) + rng.normal(0, noise, n))
    high = close + 0.1
    low = close - 0.1
    open_ = close - drift / 2
    volume = rng.uniform(10, 100, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=index
    )


def make_ranging_ohlcv(n=100, amplitude=1.0, seed=2):
    """A sine wave with no net drift: should read as a ranging market."""
    rng = np.random.default_rng(seed)
    index = pd.date_range("2024-01-01", periods=n, freq="h")
    close = 100 + amplitude * np.sin(np.linspace(0, 12 * np.pi, n)) + rng.normal(0, 0.02, n)
    high = close + 0.05
    low = close - 0.05
    open_ = close
    volume = rng.uniform(10, 100, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=index
    )


def test_compute_adx_returns_expected_columns():
    df = make_trending_ohlcv(n=40)
    result = compute_adx(df, length=14)
    assert list(result.columns) == ["plus_di", "minus_di", "adx"]
    assert len(result) == len(df)


def test_adx_classifies_strong_drift_as_trending():
    df = make_trending_ohlcv()
    regime = compute_regime(df, adx_length=14, trend_threshold=25.0)
    tail = regime.dropna().tail(20)
    assert (tail["adx"] >= 25.0).all()
    assert (tail["regime"] == REGIME_TREND).all()
    assert tail["trending"].all()


def test_adx_classifies_oscillation_as_ranging():
    df = make_ranging_ohlcv()
    regime = compute_regime(df, adx_length=14, trend_threshold=25.0)
    tail = regime.dropna().tail(20)
    assert (tail["adx"] < 25.0).all()
    assert (tail["regime"] == REGIME_RANGE).all()
    assert not tail["trending"].any()


def test_regime_is_nan_until_warmup_completes():
    df = make_trending_ohlcv(n=20)
    regime = compute_regime(df, adx_length=14)
    assert regime["adx"].iloc[:13].isna().all()
