"""EMA +/- ATR band support/resistance.

Pine Script reference::

    ema = ta.ema(close, EmaMainLength)
    atr = ta.rma(ta.tr(true), AtrMainLength)
    out1 = SR1 == 'Support' ? ema - atr * SRLength : ema + atr * SRLength
    out2 = SR2 == 'Support' ? ema - atr * SRLength : ema + atr * SRLength

``SR1``/``SR2`` just let the Pine user choose which of the two plotted lines
(bottom/top) shows the lower or upper band. We keep the same "bottom"/"top"
naming here rather than hard-coding "support"/"resistance", since the Pine
script's hit-test compares ``low`` against the bottom line and ``high``
against the top line regardless of which label the user assigned to it.
"""
import backtrader as bt

from indicators.ema import ema as ema_series
from indicators.atr import atr as atr_series


def compute_support_resistance(df, ema_length=17, atr_length=11, mult=2.6,
                                bottom="Support", top="Resistance"):
    """Return a DataFrame with columns: ema, atr, bottom, top."""
    e = ema_series(df["close"], ema_length)
    a = atr_series(df, atr_length)
    band_lower = e - a * mult
    band_upper = e + a * mult

    out = df.copy()
    out["ema"] = e
    out["atr"] = a
    out["bottom"] = band_lower if bottom == "Support" else band_upper
    out["top"] = band_upper if top == "Resistance" else band_lower
    return out[["ema", "atr", "bottom", "top"]]


class SupportResistance(bt.Indicator):
    """EMA +/- ATR band indicator for backtrader Cerebro strategies."""

    lines = ("ema", "atr", "bottom", "top")
    params = (
        ("ema_period", 17),
        ("atr_period", 11),
        ("mult", 2.6),
        ("bottom", "Support"),
        ("top", "Resistance"),
    )

    plotinfo = dict(subplot=False)
    plotlines = dict(
        ema=dict(color="orange"),
        bottom=dict(color="green"),
        top=dict(color="red"),
        atr=dict(_plotskip=True),
    )

    def __init__(self):
        self.lines.ema = bt.indicators.EMA(self.data, period=self.p.ema_period)
        self.lines.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        band_lower = self.lines.ema - self.lines.atr * self.p.mult
        band_upper = self.lines.ema + self.lines.atr * self.p.mult
        self.lines.bottom = band_lower if self.p.bottom == "Support" else band_upper
        self.lines.top = band_upper if self.p.top == "Resistance" else band_lower
        super().__init__()
