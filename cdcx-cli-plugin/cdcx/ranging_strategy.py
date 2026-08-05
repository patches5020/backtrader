"""
ranging_strategy.py
----------------------
Step 3 of the strategy: only used when regime.py classifies the market as
RANGING. Does NOT require multi-timeframe agreement (unlike the trending
path) -- instead trades the boundaries of the range:

    Long:  price at lower support, RSI < 35 and turning up, bullish
           rejection candle, near the lower value area / a high-volume node.
    Short: price at upper resistance, RSI > 65 and turning down, bearish
           rejection candle, near the upper value area.

Targets:
    TP1 = POC (Point of Control)
    TP2 = the opposite side of the range (VAH for a long, VAL for a short)

This replaces the ATR-extension TP ladder used on the trending path --
extension-based Fibonacci targets assume directional continuation, which
is exactly what a ranging market isn't giving you.

A high Range Score alone does NOT mean a range trade should fire -- it
just means the market is choppy/non-trending. Every report now also builds
a RangeProfile showing exactly where price sits within the range (edge vs
middle) and whether a rejection candle is present, so "Range = 8/10, price
in the middle" is visibly distinguished from "Range = 8/10, price at the
upper edge with a bearish rejection" -- the former is correctly still NO
TRADE even though the regime score alone looks identical.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 65
NEAR_BOUNDARY_FRACTION = 0.15  # fraction of the range width counted as "at" support/resistance
MIN_PATTERN_STRENGTH = 2       # candlestick pattern strength required to count as a "rejection"


@dataclass
class RangeProfile:
    range_high: float   # VAH
    range_low: float     # VAL
    range_mid: float
    poc: float
    price_location: str            # "LOWER EDGE" | "MIDDLE" | "UPPER EDGE"
    edge_distance_pct: float       # 0% = sitting exactly at the nearest edge, 100% = exactly at range_mid
    rejection: bool
    rejection_direction: Optional[str]  # "bullish" | "bearish" | None


@dataclass
class RangingSetup:
    direction: Optional[str]  # "long" | "short" | None
    valid: bool
    reasons: list[str] = field(default_factory=list)
    tp1: Optional[float] = None  # POC
    tp2: Optional[float] = None  # opposite side of the range
    profile: Optional[RangeProfile] = None


def _rsi_turning(rsi_series: Sequence[float]) -> tuple[bool, bool]:
    """Returns (turning_up, turning_down) based on the last two RSI readings."""
    if len(rsi_series) < 2:
        return False, False
    return rsi_series[-1] > rsi_series[-2], rsi_series[-1] < rsi_series[-2]


def build_range_profile(
    price: float, poc: float, vah: float, val: float, pattern_matches: list,
    near_fraction: float = NEAR_BOUNDARY_FRACTION,
) -> RangeProfile:
    range_width = vah - val
    range_mid = (vah + val) / 2

    near_support = range_width > 0 and price <= val + range_width * near_fraction
    near_resistance = range_width > 0 and price >= vah - range_width * near_fraction

    if near_support:
        price_location = "LOWER EDGE"
    elif near_resistance:
        price_location = "UPPER EDGE"
    else:
        price_location = "MIDDLE"

    if range_width > 0:
        nearest_edge_dist = min(price - val, vah - price)
        edge_distance_pct = round(max(0.0, nearest_edge_dist) / (range_width / 2) * 100, 1)
    else:
        edge_distance_pct = 0.0

    bullish_rejection = any(m.direction == "bullish" and m.strength >= MIN_PATTERN_STRENGTH for m in pattern_matches)
    bearish_rejection = any(m.direction == "bearish" and m.strength >= MIN_PATTERN_STRENGTH for m in pattern_matches)
    rejection = bullish_rejection or bearish_rejection
    rejection_direction = "bullish" if bullish_rejection else ("bearish" if bearish_rejection else None)

    return RangeProfile(
        range_high=vah, range_low=val, range_mid=range_mid, poc=poc,
        price_location=price_location, edge_distance_pct=edge_distance_pct,
        rejection=rejection, rejection_direction=rejection_direction,
    )


def evaluate_ranging_setup(
    price: float,
    rsi_series: Sequence[float],
    poc: float,
    vah: float,
    val: float,
    pattern_matches: list,  # list of candlestick_patterns.PatternMatch
    near_fraction: float = NEAR_BOUNDARY_FRACTION,
) -> RangingSetup:
    profile = build_range_profile(price, poc, vah, val, pattern_matches, near_fraction)

    range_width = vah - val
    turning_up, turning_down = _rsi_turning(rsi_series)
    rsi_now = rsi_series[-1] if rsi_series else 50.0

    near_support = profile.price_location == "LOWER EDGE"
    near_resistance = profile.price_location == "UPPER EDGE"

    bullish_rejection = any(m.direction == "bullish" and m.strength >= MIN_PATTERN_STRENGTH for m in pattern_matches)
    bearish_rejection = any(m.direction == "bearish" and m.strength >= MIN_PATTERN_STRENGTH for m in pattern_matches)

    long_checks = [
        ("Price near lower support", near_support),
        (f"RSI < {RSI_OVERSOLD} ({rsi_now:.1f})", rsi_now < RSI_OVERSOLD),
        ("RSI turning up", turning_up),
        ("Bullish rejection candle", bullish_rejection),
    ]
    short_checks = [
        ("Price near upper resistance", near_resistance),
        (f"RSI > {RSI_OVERBOUGHT} ({rsi_now:.1f})", rsi_now > RSI_OVERBOUGHT),
        ("RSI turning down", turning_down),
        ("Bearish rejection candle", bearish_rejection),
    ]

    long_ok = all(passed for _, passed in long_checks)
    short_ok = all(passed for _, passed in short_checks)

    if long_ok:
        return RangingSetup(
            direction="long", valid=True,
            reasons=[f"[PASS] {name}" for name, _ in long_checks],
            tp1=poc, tp2=vah, profile=profile,
        )
    if short_ok:
        return RangingSetup(
            direction="short", valid=True,
            reasons=[f"[PASS] {name}" for name, _ in short_checks],
            tp1=poc, tp2=val, profile=profile,
        )

    # Neither qualifies -- report whichever side got further, for transparency
    long_passed = sum(1 for _, p in long_checks if p)
    short_passed = sum(1 for _, p in short_checks if p)
    checks = long_checks if long_passed >= short_passed else short_checks
    label = "long" if long_passed >= short_passed else "short"
    reasons = [f"[{'PASS' if p else 'FAIL'}] {name}" for name, p in checks]
    reasons.insert(0, f"Closest qualifying side: {label} ({max(long_passed, short_passed)}/4 conditions met)")

    return RangingSetup(direction=None, valid=False, reasons=reasons, profile=profile)


def format_ranging_setup(result: RangingSetup) -> str:
    lines = ["-" * 49, "RANGING STRATEGY SETUP".center(49), "-" * 49]

    if result.profile:
        p = result.profile
        lines.append(f"RANGE HIGH: {p.range_high:.6f}")
        lines.append(f"RANGE LOW:  {p.range_low:.6f}")
        lines.append(f"RANGE MID:  {p.range_mid:.6f}")
        lines.append(f"POC:        {p.poc:.6f}")
        lines.append("")
        lines.append(f"PRICE LOCATION: {p.price_location}")
        lines.append(f"EDGE DISTANCE: {p.edge_distance_pct:.1f}%  (0% = at the edge, 100% = at range mid)")
        lines.append(f"REJECTION: {'YES (' + p.rejection_direction + ')' if p.rejection else 'NO'}")
        lines.append("-" * 49)

    lines.extend(result.reasons)
    lines.append("-" * 49)
    if result.valid:
        lines.append(f"RANGE TRADE: {result.direction.upper()} -- TP1 (POC): {result.tp1}  TP2 (range edge): {result.tp2}")
    else:
        lines.append("RANGE TRADE: NO TRADE -- no valid ranging setup right now.")
    lines.append("-" * 49)
    return "\n".join(lines)
