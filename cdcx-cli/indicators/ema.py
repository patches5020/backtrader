"""Exponential Moving Average.

Mirrors Pine Script's ``ta.ema(source, length)``.
"""
import backtrader as bt


def ema(series, length):
    """Return the EMA of a pandas Series using Wilder-compatible seeding (SMA seed, then EWM)."""
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


class EMA(bt.Indicator):
    """backtrader wrapper around ``bt.indicators.EMA`` for use inside Cerebro strategies."""

    lines = ("ema",)
    params = (("period", 17),)

    plotinfo = dict(subplot=False)

    def __init__(self):
        self.lines.ema = bt.indicators.EMA(self.data, period=self.p.period)
        super().__init__()
