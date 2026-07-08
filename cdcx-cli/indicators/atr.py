"""Average True Range (Wilder's RMA smoothing).

Mirrors Pine Script's ``ta.rma(ta.tr(true), length)``, i.e. ``ta.atr(length)``.
"""
import numpy as np
import backtrader as bt


def true_range(df):
    """Return the true range series for an OHLC DataFrame."""
    prev_close = df["close"].shift(1)
    ranges = np.vstack([
        (df["high"] - df["low"]).to_numpy(),
        (df["high"] - prev_close).abs().to_numpy(),
        (df["low"] - prev_close).abs().to_numpy(),
    ])
    tr = ranges.max(axis=0)
    tr[0] = (df["high"] - df["low"]).iloc[0]
    return df["close"].__class__(tr, index=df.index, name="tr")


def atr(df, length):
    """Return Wilder's RMA-smoothed ATR for an OHLC DataFrame."""
    tr = true_range(df)
    return tr.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


class ATR(bt.Indicator):
    """backtrader wrapper around ``bt.indicators.ATR`` (Wilder smoothing) for Cerebro strategies."""

    lines = ("atr",)
    params = (("period", 11),)

    def __init__(self):
        self.lines.atr = bt.indicators.ATR(self.data, period=self.p.period)
        super().__init__()
