"""
market_structure.py
---------------------
Detects swing highs/lows, classifies them as Higher High (HH), Higher Low
(HL), Lower High (LH), Lower Low (LL), and flags a Break of Structure (BOS)
when price closes beyond the most recent relevant swing point.

Weight: Market Structure -> 10
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

MARKET_STRUCTURE_WEIGHT = 10


@dataclass
class SwingPoint:
    index: int
    price: float
    kind: str  # "high" | "low"
    label: str = ""  # HH / HL / LH / LL


@dataclass
class MarketStructureResult:
    swings: list[SwingPoint]
    structure: str          # e.g. "Higher High / Higher Low"
    bos: str                # "Bullish BOS" | "Bearish BOS" | "None"
    score: int
    label: str


def find_swings(highs: Sequence[float], lows: Sequence[float], left: int = 2, right: int = 2) -> list[SwingPoint]:
    swings: list[SwingPoint] = []
    n = len(highs)

    for i in range(left, n - right):
        window_highs = highs[i - left:i + right + 1]
        window_lows = lows[i - left:i + right + 1]

        if highs[i] == max(window_highs):
            swings.append(SwingPoint(index=i, price=highs[i], kind="high"))
        if lows[i] == min(window_lows):
            swings.append(SwingPoint(index=i, price=lows[i], kind="low"))

    swings.sort(key=lambda s: s.index)
    return swings


def classify_structure(swings: list[SwingPoint]) -> list[SwingPoint]:
    last_high = None
    last_low = None

    for swing in swings:
        if swing.kind == "high":
            if last_high is not None:
                swing.label = "HH" if swing.price > last_high else "LH"
            last_high = swing.price
        else:
            if last_low is not None:
                swing.label = "HL" if swing.price > last_low else "LL"
            last_low = swing.price

    return swings


def detect_bos(price: float, swings: list[SwingPoint]) -> str:
    """A break of structure occurs when price closes beyond the most recent
    opposite-side swing point that already has a label (i.e. confirmed)."""
    labeled_highs = [s for s in swings if s.kind == "high" and s.label]
    labeled_lows = [s for s in swings if s.kind == "low" and s.label]

    if labeled_highs and price > labeled_highs[-1].price:
        return "Bullish BOS"
    if labeled_lows and price < labeled_lows[-1].price:
        return "Bearish BOS"
    return "None"


def score_market_structure(swings: list[SwingPoint], bos: str) -> tuple[int, str]:
    recent_labels = [s.label for s in swings[-4:] if s.label]

    bullish_run = recent_labels.count("HH") + recent_labels.count("HL") >= 2
    bearish_run = recent_labels.count("LH") + recent_labels.count("LL") >= 2

    if bullish_run and bos == "Bullish BOS":
        return MARKET_STRUCTURE_WEIGHT, "Higher High / Higher Low - Bullish BOS"
    if bearish_run and bos == "Bearish BOS":
        return -MARKET_STRUCTURE_WEIGHT, "Lower High / Lower Low - Bearish BOS"
    if bullish_run or bearish_run:
        return MARKET_STRUCTURE_WEIGHT // 2, "Structure Forming, No Confirmed BOS"
    return 0, "No Clear Structure"


def analyze(highs: Sequence[float], lows: Sequence[float], price: float) -> MarketStructureResult:
    swings = classify_structure(find_swings(highs, lows))
    bos = detect_bos(price, swings)
    score, label = score_market_structure(swings, bos)

    structure_desc = " / ".join(s.label for s in swings[-4:] if s.label) or "Insufficient Data"

    return MarketStructureResult(swings=swings, structure=structure_desc, bos=bos, score=score, label=label)


if __name__ == "__main__":
    highs = [100, 102, 101, 104, 103, 106, 105, 108, 107, 110]
    lows = [98, 99, 97, 101, 100, 103, 102, 105, 104, 107]

    result = analyze(highs, lows, price=highs[-1] + 1)
    print(f"Structure: {result.structure}")
    print(f"BOS: {result.bos}")
    print(f"Score: {result.score:+d} ({result.label})")
