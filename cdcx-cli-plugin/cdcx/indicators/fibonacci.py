"""
fibonacci.py
------------
Fibonacci Retracement + Trend-Based Fibonacci Extension for the CDCX AI
trading engine.

Retracement levels (swing high -> swing low, or vice versa):
    0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0

Extension levels (profit targets, measured off the retracement swing):
    1.272, 1.414, 1.618, 2.618

Weights:
    Fibonacci Retracement -> 12 pts
    Fibonacci Extension    -> 8 pts
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Direction = Literal["up", "down"]

RETRACEMENT_RATIOS = (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0)
EXTENSION_RATIOS = (1.272, 1.414, 1.618, 2.618)

FIB_RETRACEMENT_WEIGHT = 12
FIB_EXTENSION_WEIGHT = 8

# How close (as a fraction of the swing range) price must be to a level
# to count as a "touch/bounce" for retracement scoring.
DEFAULT_TOLERANCE_PCT = 0.0025  # 0.25% of price


@dataclass
class RetracementResult:
    levels: dict[str, float]
    nearest_level: str | None
    nearest_price: float | None
    score: int
    label: str


@dataclass
class ExtensionResult:
    levels: dict[str, float]
    targets_hit: list[str] = field(default_factory=list)
    score: int = 0
    label: str = "No Confirmed Extension"


def calculate_retracement(swing_high: float, swing_low: float) -> dict[str, float]:
    """
    Build retracement levels between a swing high and swing low.
    Level "0.0" sits at swing_high, level "1.0" sits at swing_low
    (standard down-drawn retracement convention; works for either
    trend direction since we key off high/low, not up/down).
    """
    if swing_high <= swing_low:
        raise ValueError("swing_high must be greater than swing_low")

    diff = swing_high - swing_low
    return {f"{ratio}": swing_high - diff * ratio for ratio in RETRACEMENT_RATIOS}


def calculate_extension(
    swing_high: float, swing_low: float, direction: Direction
) -> dict[str, float]:
    """
    Trend-based Fibonacci extension, projected beyond the swing in the
    direction of the trend.

    direction="up"   -> targets extend above swing_high (uptrend continuation)
    direction="down" -> targets extend below swing_low (downtrend continuation)
    """
    if swing_high <= swing_low:
        raise ValueError("swing_high must be greater than swing_low")

    diff = swing_high - swing_low
    levels: dict[str, float] = {}

    for ratio in EXTENSION_RATIOS:
        if direction == "up":
            levels[f"{ratio}"] = swing_low + diff * ratio
        elif direction == "down":
            levels[f"{ratio}"] = swing_high - diff * ratio
        else:
            raise ValueError("direction must be 'up' or 'down'")

    return levels


def score_retracement(
    price: float,
    swing_high: float,
    swing_low: float,
    trend: str,
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
) -> RetracementResult:
    """
    Award points when price is bouncing near a retracement level in the
    direction of the prevailing trend. Deeper, more significant levels
    (0.5, 0.618, 0.786) score higher than shallow ones (0.236, 0.382),
    matching how traders weight retracement confluence.
    """
    levels = calculate_retracement(swing_high, swing_low)
    tolerance = price * tolerance_pct
    trend = trend.lower().strip()
    sign = 1 if trend == "bullish" else -1 if trend == "bearish" else 0

    level_weight = {
        "0.236": 4,
        "0.382": 7,
        "0.5": 9,
        "0.618": 12,
        "0.786": 9,
        "0.0": 0,
        "1.0": 0,
    }

    nearest_level = None
    nearest_price = None
    best_distance = float("inf")

    for name, level_price in levels.items():
        distance = abs(price - level_price)
        if distance <= tolerance and distance < best_distance:
            best_distance = distance
            nearest_level = name
            nearest_price = level_price

    if nearest_level is None:
        return RetracementResult(levels, None, None, 0, "No Level Confluence")

    raw_score = level_weight.get(nearest_level, 0)
    # Cap at the module weight, then sign it by trend direction
    score = sign * min(raw_score, FIB_RETRACEMENT_WEIGHT)
    label = f"Bounce from {float(nearest_level) * 100:.1f}%"

    return RetracementResult(levels, nearest_level, nearest_price, score, label)


def score_extension(
    price: float,
    swing_high: float,
    swing_low: float,
    direction: Direction,
    trend_confirmed: bool,
) -> ExtensionResult:
    """
    Extensions are primarily used as take-profit targets rather than an
    entry trigger, so scoring here rewards having a clean, valid target
    ladder ahead of price in the direction of the trend. Full points are
    awarded when the trend is confirmed and all targets sit ahead of the
    current price (i.e. none have already been blown through, which would
    indicate the move is already exhausted).
    """
    levels = calculate_extension(swing_high, swing_low, direction)

    if not trend_confirmed:
        return ExtensionResult(levels, [], 0, "Trend Not Confirmed")

    ahead_of_price = []
    for name, level_price in levels.items():
        is_ahead = level_price > price if direction == "up" else level_price < price
        if is_ahead:
            ahead_of_price.append(name)

    targets_hit = [name for name in levels if name not in ahead_of_price]

    if len(ahead_of_price) == len(EXTENSION_RATIOS):
        return ExtensionResult(levels, targets_hit, FIB_EXTENSION_WEIGHT, "Full Target Ladder Ahead")
    if len(ahead_of_price) >= len(EXTENSION_RATIOS) // 2:
        return ExtensionResult(levels, targets_hit, FIB_EXTENSION_WEIGHT // 2, "Partial Target Ladder Ahead")
    if ahead_of_price:
        return ExtensionResult(levels, targets_hit, 2, "Limited Room to Targets")

    return ExtensionResult(levels, targets_hit, 0, "Extension Targets Already Exceeded")


if __name__ == "__main__":
    swing_low, swing_high = 100_000.0, 108_000.0
    price = 103_945.0  # ~ near 0.618 retracement

    retr = score_retracement(price, swing_high, swing_low, trend="bullish")
    print("Retracement levels:", {k: round(v, 1) for k, v in retr.levels.items()})
    print(f"Retracement score: +{retr.score} ({retr.label})")

    ext = score_extension(price, swing_high, swing_low, direction="up", trend_confirmed=True)
    print("Extension levels:", {k: round(v, 1) for k, v in ext.levels.items()})
    print(f"Extension score: +{ext.score} ({ext.label})")
