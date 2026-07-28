"""
rsi.py
------
RSI(17) calculation and momentum scoring for the CDCX AI trading engine.

The period is intentionally tied to atr_ema_variant1.EMA_LENGTH (17) rather
than the conventional RSI(14), so every smoothed/lookback indicator in the
engine runs on the same period as the primary EMA trend read.

Scoring rules (from spec):

Bullish trend context:
    RSI 55-70   -> +12
    RSI 50-55   -> +8
    RSI >70     -> +5   (overbought, momentum still counted but capped)
    RSI <30     -> 0    (wait for reversal confirmation)

Bearish trend context:
    RSI 30-45   -> -10
    RSI <30     -> -10  (oversold, bearish momentum confirmed)
    RSI >80     -> -5   (potential exhaustion of the bearish move)

Any value not covered by the above bands scores 0 (neutral / no edge).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .atr_ema_variant1 import EMA_LENGTH

RSI_LENGTH = EMA_LENGTH  # kept in lockstep with the EMA/ATR variant's period
RSI_MOMENTUM_WEIGHT = 12  # max points this indicator can contribute


@dataclass
class RSIResult:
    value: float
    score: int
    label: str


def calculate_rsi(closes: Sequence[float], period: int = RSI_LENGTH) -> list[float]:
    """
    Wilder's RSI, returned as a list aligned to `closes`
    (first `period` entries are NaN-equivalent -> filled with 50.0 as neutral).
    """
    if len(closes) < period + 1:
        raise ValueError(f"Need at least {period + 1} closes to compute RSI({period})")

    gains = [0.0] * len(closes)
    losses = [0.0] * len(closes)

    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains[i] = max(change, 0.0)
        losses[i] = max(-change, 0.0)

    rsi_values = [50.0] * len(closes)

    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period

    def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    rsi_values[period] = _rsi_from_averages(avg_gain, avg_loss)

    for i in range(period + 1, len(closes)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period
        rsi_values[i] = _rsi_from_averages(avg_gain, avg_loss)

    return rsi_values


def score_rsi(rsi_value: float, trend: str) -> RSIResult:
    """
    Score the latest RSI reading against the CDCX momentum rules.

    trend: "bullish" or "bearish" (as determined by the EMA / market-structure
           trend detector upstream of this module).
    """
    trend = trend.lower().strip()

    if trend == "bullish":
        if 55 <= rsi_value <= 70:
            return RSIResult(rsi_value, 12, "Bullish Momentum")
        if 50 <= rsi_value < 55:
            return RSIResult(rsi_value, 8, "Early Bullish Momentum")
        if rsi_value > 70:
            return RSIResult(rsi_value, 5, "Overbought")
        if rsi_value < 30:
            return RSIResult(rsi_value, 0, "Oversold - Wait for Reversal Confirmation")
        return RSIResult(rsi_value, 0, "Neutral")

    if trend == "bearish":
        if 30 <= rsi_value <= 45:
            return RSIResult(rsi_value, -10, "Bearish Momentum")
        if rsi_value < 30:
            return RSIResult(rsi_value, -10, "Oversold")
        if rsi_value > 80:
            return RSIResult(rsi_value, -5, "Potential Exhaustion")
        return RSIResult(rsi_value, 0, "Neutral")

    # Unknown/neutral trend context: no directional bias applied
    return RSIResult(rsi_value, 0, "Neutral (No Trend Context)")


if __name__ == "__main__":
    # Quick smoke test
    sample_closes = [
        100, 101, 102, 101.5, 103, 104, 103.8, 105, 106, 107,
        106.5, 108, 109, 110, 109.5, 111, 111.5, 112.5,
    ]
    rsi_series = calculate_rsi(sample_closes)
    latest = rsi_series[-1]
    result = score_rsi(latest, trend="bullish")
    print(f"RSI({RSI_LENGTH}): {latest:.2f}")
    print(f"Score: {result.score:+d}  ({result.label})")
