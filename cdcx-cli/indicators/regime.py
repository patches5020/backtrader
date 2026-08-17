"""Trend/range market regime classification (Wilder's ADX).

Pine/Wilder reference::

    up_move   = high - high[1]
    down_move = low[1] - low
    +dm = up_move   if up_move   > down_move and up_move   > 0 else 0
    -dm = down_move if down_move > up_move   and down_move > 0 else 0
    +di = 100 * rma(+dm, length) / atr(length)
    -di = 100 * rma(-dm, length) / atr(length)
    dx  = 100 * abs(+di - -di) / (+di + -di)
    adx = rma(dx, length)

``adx >= trend_threshold`` is classified as a **trending** market,
``adx < trend_threshold`` as a **ranging** one. This is the standard Wilder
reading of ADX (values below ~20-25 indicate a non-trending/ranging market).
"""
import numpy as np
import pandas as pd
import backtrader as bt

from indicators.atr import true_range

DEFAULT_ADX_LENGTH = 14
DEFAULT_TREND_THRESHOLD = 25.0

REGIME_TREND = "trend"
REGIME_RANGE = "range"


def _rma(series, length):
    """Wilder's smoothed moving average (same seeding convention as atr.py)."""
    return series.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


def compute_adx(df, length=DEFAULT_ADX_LENGTH):
    """Return a DataFrame with columns: plus_di, minus_di, adx."""
    up_move = df["high"].diff()
    down_move = -df["low"].diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = true_range(df)
    atr = _rma(tr, length)

    plus_di = 100.0 * _rma(pd.Series(plus_dm, index=df.index), length) / atr
    minus_di = 100.0 * _rma(pd.Series(minus_dm, index=df.index), length) / atr

    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = _rma(dx, length)

    out = pd.DataFrame(index=df.index)
    out["plus_di"] = plus_di
    out["minus_di"] = minus_di
    out["adx"] = adx
    return out


def compute_regime(df, adx_length=DEFAULT_ADX_LENGTH, trend_threshold=DEFAULT_TREND_THRESHOLD):
    """Return a DataFrame with columns: adx, trending (bool), regime ("trend"/"range")."""
    adx_df = compute_adx(df, length=adx_length)
    out = pd.DataFrame(index=df.index)
    out["adx"] = adx_df["adx"]
    out["trending"] = out["adx"] >= trend_threshold
    out["regime"] = np.where(out["trending"], REGIME_TREND, REGIME_RANGE)
    out.loc[out["adx"].isna(), "regime"] = None
    return out


class MarketRegime(bt.Indicator):
    """backtrader indicator: ADX-based trend/range classification.

    ``lines.adx`` is the raw ADX value; ``lines.trending`` is ``1.0`` once
    ``adx >= trend_threshold`` (a trending market) and ``0.0`` otherwise
    (a ranging market).
    """

    lines = ("adx", "trending")
    params = (
        ("adx_period", DEFAULT_ADX_LENGTH),
        ("trend_threshold", DEFAULT_TREND_THRESHOLD),
    )

    plotinfo = dict(subplot=True)
    plotlines = dict(
        adx=dict(color="purple"),
        trending=dict(_plotskip=True),
    )

    def __init__(self):
        adx = bt.indicators.ADX(self.data, period=self.p.adx_period)
        self.lines.adx = adx.adx
        self.lines.trending = adx.adx >= self.p.trend_threshold
        super().__init__()
