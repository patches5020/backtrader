"""ATR_EMA_VARIANT1: Python port of the Pine Script

    "EMA+ ATR Support Resistance Take Profit signal"
    (indicator(title='EMA+ ATR Support Resistance Take Profit signal', overlay=true))

Pine Script core::

    ema = ta.ema(close, EmaMainLength)
    atr = ta.rma(ta.tr(true), AtrMainLength)
    out1 = ema - atr * SRLength   -- Support (bottom line, default)
    out2 = ema + atr * SRLength   -- Resistance (top line, default)
    support_hit    = low  <= out1
    resistance_hit = high >= out2
"""
import backtrader as bt

from indicators.support_resistance import compute_support_resistance, SupportResistance

DEFAULT_EMA_LENGTH = 17
DEFAULT_ATR_LENGTH = 11
DEFAULT_SR_LENGTH = 2.6


def compute_atr_ema_variant1(df, ema_length=DEFAULT_EMA_LENGTH, atr_length=DEFAULT_ATR_LENGTH,
                              sr_length=DEFAULT_SR_LENGTH):
    """Return a DataFrame with ema, support, resistance, support_hit, resistance_hit."""
    sr = compute_support_resistance(
        df, ema_length=ema_length, atr_length=atr_length, mult=sr_length,
        bottom="Support", top="Resistance",
    )
    out = df.copy()
    out["ema"] = sr["ema"]
    out["support"] = sr["bottom"]
    out["resistance"] = sr["top"]
    out["support_hit"] = df["low"] <= out["support"]
    out["resistance_hit"] = df["high"] >= out["resistance"]
    return out[["ema", "support", "resistance", "support_hit", "resistance_hit"]]


class ATREMAVariant1(bt.Indicator):
    """backtrader indicator: EMA+ATR support/resistance with take-profit hit signals."""

    lines = ("ema", "support", "resistance", "support_hit", "resistance_hit")
    params = (
        ("ema_period", DEFAULT_EMA_LENGTH),
        ("atr_period", DEFAULT_ATR_LENGTH),
        ("sr_length", DEFAULT_SR_LENGTH),
    )

    plotinfo = dict(subplot=False)
    plotlines = dict(
        ema=dict(color="orange"),
        support=dict(color="green"),
        resistance=dict(color="red"),
        support_hit=dict(marker="x", markersize=6.0, color="lime", linestyle="None"),
        resistance_hit=dict(marker="x", markersize=6.0, color="red", linestyle="None"),
    )

    def __init__(self):
        sr = SupportResistance(
            self.data,
            ema_period=self.p.ema_period,
            atr_period=self.p.atr_period,
            mult=self.p.sr_length,
            bottom="Support",
            top="Resistance",
        )
        self.lines.ema = sr.ema
        self.lines.support = sr.bottom
        self.lines.resistance = sr.top
        self.lines.support_hit = self.data.low <= sr.bottom
        self.lines.resistance_hit = self.data.high >= sr.top
        super().__init__()
