"""
candlestick_patterns.py
--------------------------
Single- and multi-candle price-action patterns, detected on the most recent
bar(s) and scored by directional signal strength. Complements the swing-
based market_structure.py (which handles HH/HL/LH/LL and BOS) with the
finer-grained candle-shape patterns.

Patterns covered:
    Single candle : Doji, Dragonfly Doji, Gravestone Doji, Hammer, Shooting Star
    Two candle    : Bullish/Bearish Engulfing, Bullish/Bearish Harami, Tweezer Top/Bottom
    Three candle  : Morning Star, Evening Star

Not covered here (need multi-swing sequence detection, deferred):
    Head & Shoulders, Double Top/Bottom, Triple Top/Bottom

Weight: Candlestick Patterns -> 10
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

CANDLESTICK_WEIGHT = 10

# Tolerances (as a fraction of the candle's range) for "small body", "long
# shadow", "matching level", etc. -- tunable if patterns fire too often/rarely
# against real data.
DOJI_BODY_MAX_PCT = 0.10        # body <= 10% of range counts as a doji
SMALL_SHADOW_MAX_PCT = 0.10     # the "short" shadow on a hammer/star/doji variant
LONG_SHADOW_MIN_RATIO = 2.0     # long shadow >= 2x the body
TWEEZER_MATCH_TOLERANCE = 0.001  # 0.1% relative tolerance for "matching" highs/lows


@dataclass
class Candle:
    open: float
    high: float
    low: float
    close: float

    @property
    def range(self) -> float:
        return max(self.high - self.low, 1e-12)

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def body_pct(self) -> float:
        return self.body / self.range

    @property
    def upper_shadow(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_shadow(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open


@dataclass
class PatternMatch:
    name: str
    direction: str  # "bullish" | "bearish"
    strength: int   # 1 (weak/minor) .. 3 (strong reversal signal)


def _to_candles(highs: Sequence[float], lows: Sequence[float], opens: Sequence[float], closes: Sequence[float]) -> list[Candle]:
    return [Candle(o, h, l, c) for o, h, l, c in zip(opens, highs, lows, closes)]


# --- single-candle patterns -------------------------------------------------

def _detect_doji_variants(c: Candle) -> list[PatternMatch]:
    matches = []
    if c.body_pct > DOJI_BODY_MAX_PCT:
        return matches

    upper_pct = c.upper_shadow / c.range
    lower_pct = c.lower_shadow / c.range

    if lower_pct >= (1 - SMALL_SHADOW_MAX_PCT) - c.body_pct and upper_pct <= SMALL_SHADOW_MAX_PCT:
        matches.append(PatternMatch("Dragonfly Doji", "bullish", 2))
    elif upper_pct >= (1 - SMALL_SHADOW_MAX_PCT) - c.body_pct and lower_pct <= SMALL_SHADOW_MAX_PCT:
        matches.append(PatternMatch("Gravestone Doji", "bearish", 2))
    else:
        matches.append(PatternMatch("Doji (Indecision)", "bullish" if c.is_bullish else "bearish", 1))
    return matches


def _detect_hammer_or_star(c: Candle) -> list[PatternMatch]:
    matches = []
    if c.body_pct > DOJI_BODY_MAX_PCT * 3:  # hammer/star need a genuinely small body
        return matches
    if c.body <= 0:
        return matches

    if c.lower_shadow >= c.body * LONG_SHADOW_MIN_RATIO and c.upper_shadow / c.range <= SMALL_SHADOW_MAX_PCT:
        matches.append(PatternMatch("Hammer", "bullish", 2))
    if c.upper_shadow >= c.body * LONG_SHADOW_MIN_RATIO and c.lower_shadow / c.range <= SMALL_SHADOW_MAX_PCT:
        matches.append(PatternMatch("Shooting Star", "bearish", 2))
    return matches


# --- two-candle patterns -----------------------------------------------------

def _detect_engulfing(prev: Candle, curr: Candle) -> list[PatternMatch]:
    matches = []
    prev_top, prev_bottom = max(prev.open, prev.close), min(prev.open, prev.close)
    curr_top, curr_bottom = max(curr.open, curr.close), min(curr.open, curr.close)

    if curr.is_bullish and prev.is_bearish and curr_bottom <= prev_bottom and curr_top >= prev_top:
        matches.append(PatternMatch("Bullish Engulfing", "bullish", 3))
    if curr.is_bearish and prev.is_bullish and curr_bottom <= prev_bottom and curr_top >= prev_top:
        matches.append(PatternMatch("Bearish Engulfing", "bearish", 3))
    return matches


def _detect_harami(prev: Candle, curr: Candle) -> list[PatternMatch]:
    matches = []
    prev_top, prev_bottom = max(prev.open, prev.close), min(prev.open, prev.close)
    curr_top, curr_bottom = max(curr.open, curr.close), min(curr.open, curr.close)

    inside = curr_top <= prev_top and curr_bottom >= prev_bottom
    if not inside:
        return matches

    if prev.is_bearish and curr.is_bullish:
        matches.append(PatternMatch("Bullish Harami", "bullish", 1))
    elif prev.is_bullish and curr.is_bearish:
        matches.append(PatternMatch("Bearish Harami", "bearish", 1))
    return matches


def _detect_tweezer(prev: Candle, curr: Candle) -> list[PatternMatch]:
    matches = []
    high_diff = abs(prev.high - curr.high) / max(prev.high, curr.high, 1e-12)
    low_diff = abs(prev.low - curr.low) / max(prev.low, curr.low, 1e-12)

    if high_diff <= TWEEZER_MATCH_TOLERANCE and prev.is_bullish and curr.is_bearish:
        matches.append(PatternMatch("Tweezer Top", "bearish", 2))
    if low_diff <= TWEEZER_MATCH_TOLERANCE and prev.is_bearish and curr.is_bullish:
        matches.append(PatternMatch("Tweezer Bottom", "bullish", 2))
    return matches


# --- three-candle patterns ---------------------------------------------------

def _detect_star_patterns(first: Candle, second: Candle, third: Candle) -> list[PatternMatch]:
    matches = []
    first_top, first_bottom = max(first.open, first.close), min(first.open, first.close)
    first_mid = (first_top + first_bottom) / 2

    # Morning Star: bearish, small-body/gap-down middle, bullish closing well into candle 1's body
    if (
        first.is_bearish and second.body_pct <= DOJI_BODY_MAX_PCT * 3
        and max(second.open, second.close) <= first_bottom + first.body * 0.3
        and third.is_bullish and third.close >= first_mid
    ):
        matches.append(PatternMatch("Morning Star", "bullish", 3))

    # Evening Star: mirror of the above
    if (
        first.is_bullish and second.body_pct <= DOJI_BODY_MAX_PCT * 3
        and min(second.open, second.close) >= first_top - first.body * 0.3
        and third.is_bearish and third.close <= first_mid
    ):
        matches.append(PatternMatch("Evening Star", "bearish", 3))

    return matches


def detect_patterns(
    highs: Sequence[float], lows: Sequence[float], opens: Sequence[float], closes: Sequence[float]
) -> list[PatternMatch]:
    """Detects every pattern whose LAST candle is the most recent bar (index -1)."""
    candles = _to_candles(highs, lows, opens, closes)
    if len(candles) < 1:
        return []

    matches: list[PatternMatch] = []
    curr = candles[-1]

    matches += _detect_doji_variants(curr)
    matches += _detect_hammer_or_star(curr)

    if len(candles) >= 2:
        prev = candles[-2]
        matches += _detect_engulfing(prev, curr)
        matches += _detect_harami(prev, curr)
        matches += _detect_tweezer(prev, curr)

    if len(candles) >= 3:
        first, second = candles[-3], candles[-2]
        matches += _detect_star_patterns(first, second, curr)

    return matches


def score_patterns(matches: list[PatternMatch], trend: str) -> tuple[int, str]:
    """
    Scores the strongest pattern that aligns with the given trend direction.
    A pattern against the trend contributes nothing (patterns are treated as
    confirmation/reversal signals in context, not traded blind against trend),
    matching how every other indicator in this engine only scores in the
    trend's favor.
    """
    trend = trend.lower().strip()
    aligned = [m for m in matches if m.direction == ("bullish" if trend == "bullish" else "bearish")]

    if not aligned:
        return 0, "No Aligned Pattern"

    best = max(aligned, key=lambda m: m.strength)
    # strength 1..3 maps onto the module's weight proportionally
    score = round(CANDLESTICK_WEIGHT * best.strength / 3)
    sign = 1 if trend == "bullish" else -1
    names = ", ".join(m.name for m in aligned)
    return sign * score, f"{names}"


if __name__ == "__main__":
    # Bullish engulfing example
    opens = [100, 98]
    closes = [98, 103]
    highs = [100.5, 103.5]
    lows = [97.5, 97.8]

    matches = detect_patterns(highs, lows, opens, closes)
    for m in matches:
        print(f"{m.name} ({m.direction}, strength {m.strength})")

    score, label = score_patterns(matches, trend="bullish")
    print(f"Score: {score:+d} ({label})")
