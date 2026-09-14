"""
atr_ema_variant1.py
--------------------
Python port of the "EMA+ ATR Support Resistance" Pine Script indicator.

Computes:
    - EMA(17) trend
    - ATR(11), Wilder-smoothed
    - Dynamic support / resistance bands: EMA +/- (ATR * SRLength)

Scoring:
    EMA Trend      -> weight 15
    ATR Expansion  -> weight 8
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

EMA_LENGTH = 17
ATR_LENGTH = 11
SR_LENGTH = 2.6  # multiplier applied to ATR for the S/R bands

EMA_TREND_WEIGHT = 15
ATR_EXPANSION_WEIGHT = 8


@dataclass
class EMAATRResult:
    ema: float
    atr: float
    support: float
    resistance: float
    trend: str  # "bullish" | "bearish" | "neutral"
    ema_score: int
    ema_label: str
    atr_score: int
    atr_label: str


def calculate_ema(closes: Sequence[float], length: int = EMA_LENGTH) -> list[float]:
    if len(closes) < length:
        raise ValueError(f"Need at least {length} closes to compute EMA({length})")

    multiplier = 2 / (length + 1)
    ema_values = [closes[0]]
    for price in closes[1:]:
        ema_values.append((price - ema_values[-1]) * multiplier + ema_values[-1])
    return ema_values


def calculate_true_range(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> list[float]:
    tr = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        high_low = highs[i] - lows[i]
        high_close = abs(highs[i] - closes[i - 1])
        low_close = abs(lows[i] - closes[i - 1])
        tr.append(max(high_low, high_close, low_close))
    return tr


def calculate_atr(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], length: int = ATR_LENGTH
) -> list[float]:
    """Wilder's smoothed ATR (matches Pine Script's ta.rma)."""
    if len(closes) < length + 1:
        raise ValueError(f"Need at least {length + 1} bars to compute ATR({length})")

    tr = calculate_true_range(highs, lows, closes)
    atr_values = [0.0] * len(tr)
    atr_values[length - 1] = sum(tr[:length]) / length

    for i in range(length, len(tr)):
        atr_values[i] = (atr_values[i - 1] * (length - 1) + tr[i]) / length

    return atr_values


def calculate_support_resistance(
    ema: float, atr: float, sr_length: float = SR_LENGTH
) -> tuple[float, float]:
    """Returns (support, resistance) as EMA -/+ ATR * sr_length."""
    support = ema - atr * sr_length
    resistance = ema + atr * sr_length
    return support, resistance


def detect_trend(price: float, ema: float, ema_series: Sequence[float], lookback: int = 5) -> str:
    """
    Simple trend read: price vs EMA, confirmed by EMA slope over `lookback` bars.
    """
    if len(ema_series) < lookback + 1:
        slope = 0.0
    else:
        slope = ema_series[-1] - ema_series[-1 - lookback]

    if price > ema and slope > 0:
        return "bullish"
    if price < ema and slope < 0:
        return "bearish"
    return "neutral"


def score_ema_trend(trend: str) -> tuple[int, str]:
    if trend == "bullish":
        return EMA_TREND_WEIGHT, "Bullish"
    if trend == "bearish":
        return -EMA_TREND_WEIGHT, "Bearish"
    return 0, "No Clear Trend"


def score_atr_expansion(atr_series: Sequence[float], lookback: int = 10) -> tuple[int, str]:
    """
    Rewards ATR expansion (volatility picking up) vs its own recent average --
    a contracting/flat ATR scores 0 since there's no fresh momentum behind the move.
    """
    if len(atr_series) < lookback + 1:
        return 0, "Insufficient Data"

    recent_avg = sum(atr_series[-lookback - 1:-1]) / lookback
    latest = atr_series[-1]

    if recent_avg == 0:
        return 0, "No Volatility"

    change_pct = (latest - recent_avg) / recent_avg
    if change_pct > 0.10:
        return ATR_EXPANSION_WEIGHT, "Expansion"
    if change_pct < -0.10:
        return 0, "Contraction"
    return ATR_EXPANSION_WEIGHT // 2, "Flat"


def analyze(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]
) -> EMAATRResult:
    ema_series = calculate_ema(closes, EMA_LENGTH)
    atr_series = calculate_atr(highs, lows, closes, ATR_LENGTH)

    price = closes[-1]
    ema = ema_series[-1]
    atr = atr_series[-1]
    support, resistance = calculate_support_resistance(ema, atr)

    trend = detect_trend(price, ema, ema_series)
    ema_score, ema_label = score_ema_trend(trend)
    atr_score, atr_label = score_atr_expansion(atr_series)

    return EMAATRResult(
        ema=ema, atr=atr, support=support, resistance=resistance, trend=trend,
        ema_score=ema_score, ema_label=ema_label, atr_score=atr_score, atr_label=atr_label,
    )


if __name__ == "__main__":
    closes = [100 + i * 0.5 for i in range(30)]
    highs = [c + 0.8 for c in closes]
    lows = [c - 0.8 for c in closes]

    result = analyze(highs, lows, closes)
    print(f"EMA: {result.ema:.2f}  ATR: {result.atr:.2f}")
    print(f"Support: {result.support:.2f}  Resistance: {result.resistance:.2f}")
    print(f"Trend: {result.trend}")
    print(f"EMA score: {result.ema_score:+d} ({result.ema_label})")
    print(f"ATR score: {result.atr_score:+d} ({result.atr_label})")
