"""
bollinger_bands.py
--------------------
Bollinger Bands (SMA 17, +/- 2 standard deviations) -- measures where price
sits relative to its recent volatility envelope, and whether that position
confirms or undercuts the trend the EMA module already detected.

The moving-average period is intentionally tied to atr_ema_variant1.EMA_LENGTH
(17) rather than the conventional Bollinger SMA(20), so every smoothed/
lookback indicator in the engine runs on the same period as the primary EMA
trend read.

    Middle Band = SMA(17)
    Upper Band  = SMA(17) + 2 * stddev(17)
    Lower Band  = SMA(17) - 2 * stddev(17)
    %B          = (price - lower) / (upper - lower)
                  0.0 = sitting on the lower band, 0.5 = at the middle band
                  (SMA), 1.0 = sitting on the upper band
    Bandwidth   = (upper - lower) / middle  -- relative band width, useful
                  for spotting volatility squeezes/expansions

Weight: Bollinger Bands -> 10
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from .atr_ema_variant1 import EMA_LENGTH

BB_LENGTH = EMA_LENGTH  # kept in lockstep with the EMA/ATR variant's period
BB_STD_MULTIPLIER = 2.0
BB_WEIGHT = 10


@dataclass
class BollingerResult:
    middle: float
    upper: float
    lower: float
    percent_b: float
    bandwidth: float
    score: int
    label: str


def calculate_sma(closes: Sequence[float], period: int = BB_LENGTH) -> list[float]:
    if len(closes) < period:
        raise ValueError(f"Need at least {period} closes to compute SMA({period})")

    sma_values = [0.0] * len(closes)
    for i in range(period - 1, len(closes)):
        sma_values[i] = sum(closes[i - period + 1:i + 1]) / period
    return sma_values


def calculate_bollinger_bands(
    closes: Sequence[float], period: int = BB_LENGTH, std_multiplier: float = BB_STD_MULTIPLIER
) -> tuple[list[float], list[float], list[float]]:
    """Returns (middle_band, upper_band, lower_band) series aligned to `closes`."""
    if len(closes) < period:
        raise ValueError(f"Need at least {period} closes to compute Bollinger Bands({period})")

    sma = calculate_sma(closes, period)
    upper = [0.0] * len(closes)
    lower = [0.0] * len(closes)

    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1:i + 1]
        mean = sma[i]
        variance = sum((x - mean) ** 2 for x in window) / period
        std_dev = math.sqrt(variance)
        upper[i] = mean + std_dev * std_multiplier
        lower[i] = mean - std_dev * std_multiplier

    return sma, upper, lower


def score_bollinger(price: float, middle: float, upper: float, lower: float, trend: str) -> tuple[int, str]:
    """
    %B-based scoring: rewards price riding the band in the direction of the
    trend (a classic continuation signal), penalizes/zeroes out when price
    sits on the wrong side of the mean for the stated trend, and gives
    reduced credit when price is extended beyond the band (mean-reversion
    risk rising).
    """
    band_width = upper - lower
    if band_width <= 0:
        return 0, "Flat Bands (Insufficient Volatility Data)"

    percent_b = (price - lower) / band_width
    trend = trend.lower().strip()

    if trend == "bullish":
        if percent_b > 1.0:
            return BB_WEIGHT // 2, "Above Upper Band (Extended)"
        if 0.5 <= percent_b <= 1.0:
            return BB_WEIGHT, "Riding Upper Band (Bullish Continuation)"
        if percent_b < 0.2:
            return 0, "Below Mean - Bullish Thesis Weak"
        return BB_WEIGHT // 3, "Above Lower Half, Below Mean"

    if trend == "bearish":
        if percent_b < 0.0:
            return -(BB_WEIGHT // 2), "Below Lower Band (Extended)"
        if 0.0 <= percent_b <= 0.5:
            return -BB_WEIGHT, "Riding Lower Band (Bearish Continuation)"
        if percent_b > 0.8:
            return 0, "Above Mean - Bearish Thesis Weak"
        return -(BB_WEIGHT // 3), "Below Upper Half, Above Mean"

    return 0, "No Trend Context"


def analyze(closes: Sequence[float], trend: str, period: int = BB_LENGTH) -> BollingerResult:
    sma, upper, lower = calculate_bollinger_bands(closes, period)
    price = closes[-1]
    middle, up, low = sma[-1], upper[-1], lower[-1]

    band_width = up - low
    percent_b = (price - low) / band_width if band_width > 0 else 0.5
    bandwidth = band_width / middle if middle != 0 else 0.0

    score, label = score_bollinger(price, middle, up, low, trend)

    return BollingerResult(
        middle=middle, upper=up, lower=low,
        percent_b=percent_b, bandwidth=bandwidth,
        score=score, label=label,
    )


if __name__ == "__main__":
    closes = [100 + i * 0.6 for i in range(30)]  # steady uptrend
    result = analyze(closes, trend="bullish")
    print(f"Middle: {result.middle:.2f}  Upper: {result.upper:.2f}  Lower: {result.lower:.2f}")
    print(f"%B: {result.percent_b:.2f}  Bandwidth: {result.bandwidth:.3f}")
    print(f"Score: {result.score:+d} ({result.label})")
