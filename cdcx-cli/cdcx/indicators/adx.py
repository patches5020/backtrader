"""
adx.py
------
Average Directional Index (ADX) -- measures trend *strength* (not direction).
Paired with +DI/-DI to confirm which direction that strength is behind, and
cross-checked against the trend the EMA module already detected.

Standard Wilder calculation, period tied to atr_ema_variant1.EMA_LENGTH (17)
rather than the conventional ADX(14), so every smoothed/lookback indicator
in the engine runs on the same period as the primary EMA trend read:
    +DM, -DM  -> directional movement per bar
    TR        -> true range per bar
    +DI, -DI  -> Wilder-smoothed DM as a % of Wilder-smoothed TR
    DX        -> 100 * |+DI - -DI| / (+DI + -DI)
    ADX       -> Wilder-smoothed DX

Reading:
    ADX < 20        -> no meaningful trend / choppy
    ADX 20-25       -> trend developing
    ADX > 25        -> trending market
    ADX > 40        -> very strong trend

Weight: ADX Trend Strength -> 10
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .atr_ema_variant1 import EMA_LENGTH

ADX_LENGTH = EMA_LENGTH  # kept in lockstep with the EMA/ATR variant's period
ADX_WEIGHT = 10


@dataclass
class ADXResult:
    adx: float
    plus_di: float
    minus_di: float
    score: int
    label: str


def _wilder_smooth(values: Sequence[float], period: int) -> list[float]:
    """Wilder's smoothing (same recursive average used for ATR/RSI)."""
    smoothed = [0.0] * len(values)
    smoothed[period - 1] = sum(values[:period])
    for i in range(period, len(values)):
        smoothed[i] = smoothed[i - 1] - (smoothed[i - 1] / period) + values[i]
    return smoothed


def calculate_adx(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = ADX_LENGTH
) -> tuple[list[float], list[float], list[float]]:
    """Returns (adx_series, plus_di_series, minus_di_series), all aligned to input length."""
    n = len(closes)
    if n < period * 2:
        raise ValueError(f"Need at least {period * 2} bars to compute ADX({period})")

    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    tr = [0.0] * n

    for i in range(1, n):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]

        plus_dm[i] = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm[i] = down_move if (down_move > up_move and down_move > 0) else 0.0

        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )

    smoothed_tr = _wilder_smooth(tr, period)
    smoothed_plus_dm = _wilder_smooth(plus_dm, period)
    smoothed_minus_dm = _wilder_smooth(minus_dm, period)

    plus_di = [0.0] * n
    minus_di = [0.0] * n
    dx = [0.0] * n

    for i in range(period - 1, n):
        if smoothed_tr[i] == 0:
            continue
        plus_di[i] = 100 * smoothed_plus_dm[i] / smoothed_tr[i]
        minus_di[i] = 100 * smoothed_minus_dm[i] / smoothed_tr[i]

        di_sum = plus_di[i] + minus_di[i]
        dx[i] = 100 * abs(plus_di[i] - minus_di[i]) / di_sum if di_sum != 0 else 0.0

    # ADX = Wilder-smoothed DX, starting once DX has `period` valid values
    adx = [0.0] * n
    dx_valid_start = period - 1
    first_adx_idx = dx_valid_start + period - 1
    if first_adx_idx >= n:
        return adx, plus_di, minus_di  # not enough bars for a full ADX read yet

    adx[first_adx_idx] = sum(dx[dx_valid_start:dx_valid_start + period]) / period
    for i in range(first_adx_idx + 1, n):
        adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period

    return adx, plus_di, minus_di


def score_adx(adx_value: float, plus_di: float, minus_di: float, trend: str) -> tuple[int, str]:
    """
    Full weight when ADX confirms a strong trend AND the dominant DI line
    agrees with the EMA-detected trend direction. Partial credit for a
    developing trend. Zero for chop, or when ADX is strong but the DI lines
    disagree with the trend call (a warning sign, not a confirmation).
    """
    trend = trend.lower().strip()
    di_bullish = plus_di > minus_di
    di_bearish = minus_di > plus_di

    if adx_value >= 25:
        if trend == "bullish" and di_bullish:
            return ADX_WEIGHT, "Strong Trend (+DI Confirmed)"
        if trend == "bearish" and di_bearish:
            return -ADX_WEIGHT, "Strong Trend (-DI Confirmed)"
        return 0, "Strong Trend but Direction Unconfirmed"

    if adx_value >= 20:
        if trend == "bullish" and di_bullish:
            return ADX_WEIGHT // 2, "Trend Developing (+DI)"
        if trend == "bearish" and di_bearish:
            return -(ADX_WEIGHT // 2), "Trend Developing (-DI)"
        return 0, "Trend Developing, Direction Unclear"

    return 0, "No Trend / Choppy"


def analyze(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], trend: str) -> ADXResult:
    adx_series, plus_di_series, minus_di_series = calculate_adx(highs, lows, closes)
    adx_value = adx_series[-1]
    plus_di = plus_di_series[-1]
    minus_di = minus_di_series[-1]

    score, label = score_adx(adx_value, plus_di, minus_di, trend)
    return ADXResult(adx=adx_value, plus_di=plus_di, minus_di=minus_di, score=score, label=label)


if __name__ == "__main__":
    closes = [100 + i * 0.8 for i in range(40)]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]

    result = analyze(highs, lows, closes, trend="bullish")
    print(f"ADX: {result.adx:.2f}  +DI: {result.plus_di:.2f}  -DI: {result.minus_di:.2f}")
    print(f"Score: {result.score:+d} ({result.label})")
