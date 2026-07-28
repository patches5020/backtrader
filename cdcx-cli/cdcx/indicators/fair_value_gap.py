"""
fair_value_gap.py
------------------
Detects Fair Value Gaps (FVGs) -- 3-candle imbalance patterns -- and scores
whether price is currently trading inside/near an unfilled gap that aligns
with the prevailing trend.

Bullish FVG: candle[i-1].high < candle[i+1].low  (gap between candle 1 and 3)
Bearish FVG: candle[i-1].low  > candle[i+1].high

Weight: Fair Value Gap -> 15
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

FVG_WEIGHT = 15


@dataclass
class FVG:
    index: int          # index of the middle candle of the 3-candle pattern
    top: float
    bottom: float
    kind: str            # "bullish" | "bearish"
    filled: bool = False


@dataclass
class FVGResult:
    gaps: list[FVG]
    active_gap: FVG | None
    score: int
    label: str


def detect_fvgs(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]
) -> list[FVG]:
    gaps: list[FVG] = []

    for i in range(1, len(highs) - 1):
        prev_high, prev_low = highs[i - 1], lows[i - 1]
        next_high, next_low = highs[i + 1], lows[i + 1]

        if prev_high < next_low:
            gaps.append(FVG(index=i, top=next_low, bottom=prev_high, kind="bullish"))
        elif prev_low > next_high:
            gaps.append(FVG(index=i, top=prev_low, bottom=next_high, kind="bearish"))

    # Mark gaps as filled if any later close has traded back through them
    for gap in gaps:
        for j in range(gap.index + 2, len(closes)):
            if gap.bottom <= closes[j] <= gap.top:
                gap.filled = True
                break

    return gaps


def score_fvg(gaps: list[FVG], price: float, trend: str) -> FVGResult:
    """
    Score the most recent unfilled gap that aligns with the trend direction.
    An aligned, unfilled gap acting as support/resistance under current price
    scores full weight; a filled or misaligned gap scores 0.
    """
    trend = trend.lower().strip()
    unfilled = [g for g in gaps if not g.filled]

    aligned = [
        g for g in unfilled
        if (trend == "bullish" and g.kind == "bullish")
        or (trend == "bearish" and g.kind == "bearish")
    ]

    if not aligned:
        return FVGResult(gaps, None, 0, "No Aligned FVG")

    active_gap = aligned[-1]  # most recent aligned unfilled gap
    score = FVG_WEIGHT if active_gap.kind == "bullish" else -FVG_WEIGHT
    label = f"{'Bullish' if active_gap.kind == 'bullish' else 'Bearish'} FVG"
    return FVGResult(gaps, active_gap, score, label)


if __name__ == "__main__":
    highs = [100, 101, 105, 106, 107, 108]
    lows = [98, 99, 103, 104, 105, 106]
    closes = [99, 100.5, 104, 105.5, 106.5, 107.5]

    gaps = detect_fvgs(highs, lows, closes)
    result = score_fvg(gaps, price=closes[-1], trend="bullish")
    print(f"Gaps found: {len(gaps)}")
    print(f"Score: +{result.score} ({result.label})")
