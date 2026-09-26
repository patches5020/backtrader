"""
zone_state.py
--------------
VolumeZone: the data model for a single detected volume-profile zone, plus
the tested/untested/first-test state computation on top of it.

INFORMATION ONLY (Phase 1 scope) -- see fvp_analysis.py's module docstring
for the full scope statement. Nothing here is read by entry_checklist.py,
confluence.py, regime.py, or any entry/SL/TP/R:R/risk calculation.

Field groups on VolumeZone, matching the phased rollout this module is
part of:
    Phase 1 (populated now): timeframe, zone_type, lower_price,
        upper_price, poc_price, tested, test_count, first_test.
    Phase 2+ (present but default-unset until that phase lands):
        origin_price, departure_strength, setup_type, and the individual
        *_confluence booleans -- kept on the dataclass now so later phases
        extend it rather than replace it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass
class VolumeZone:
    timeframe: str
    zone_type: str  # "fixed_value_area" | "anchored_value_area" (Phase 1)

    lower_price: float
    upper_price: float
    poc_price: float

    # Phase 2+ fields -- present now so the dataclass shape is stable across
    # phases (ADD, don't replace), populated by later modules.
    origin_price: Optional[float] = None
    setup_type: Optional[str] = None
    departure_strength: Optional[float] = None
    fvg_confluence: bool = False
    fib_confluence: bool = False
    bos_confluence: bool = False
    trend_aligned: bool = False
    avp_confluence: bool = False
    sr_flip_confluence: bool = False
    vwap_confluence: bool = False

    # Phase 1: tested/untested state.
    tested: bool = False
    test_count: int = 0
    first_test: bool = False


def contains(zone: VolumeZone, price: float) -> bool:
    return zone.lower_price <= price <= zone.upper_price


def compute_tested_state(
    zone: VolumeZone, highs: Sequence[float], lows: Sequence[float], formed_at_index: int,
) -> VolumeZone:
    """Walks price action *after* the zone was formed and counts how many
    distinct bars traded back into [lower_price, upper_price]. A zone with
    zero touches since formation is UNTESTED; the first touch, if any, is
    the first_test.

    `formed_at_index` is the bar index the zone's underlying volume-profile
    lookback window started at (e.g. anchor_index for an anchored profile,
    or len(data) - lookback for a fixed one) -- touches are only counted
    from the bar *after* that window closes, so the zone isn't marked
    "tested" by the very same bars that built it.
    """
    touches = 0
    current_bar_touches = False
    last_index = len(highs) - 1
    for i in range(formed_at_index + 1, len(highs)):
        bar_high, bar_low = highs[i], lows[i]
        # A bar "touches" the zone if its range overlaps it at all.
        if bar_low <= zone.upper_price and bar_high >= zone.lower_price:
            touches += 1
            if i == last_index:
                current_bar_touches = True

    zone.test_count = touches
    zone.tested = touches > 0
    # "First test" means price is touching the zone for the first time
    # RIGHT NOW (the most recent bar), not merely "has been touched exactly
    # once at some point in the past" -- those are different claims.
    zone.first_test = touches == 1 and current_bar_touches
    return zone
