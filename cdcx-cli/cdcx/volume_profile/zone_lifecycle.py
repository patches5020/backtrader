"""
zone_lifecycle.py
-------------------
Classifies a VolumeZone's current position in its lifecycle:

    DISCOVERED        -- zone just detected, not yet evaluated further
                         (not used as a terminal state by classify_lifecycle
                         below; kept for future phases that may stage
                         detection separately from classification).
    QUALIFIED         -- zone meets the minimum shape to be worth tracking
                         (non-degenerate range) but price is not near it.
    UNTESTED          -- qualified AND never touched since formation.
    PRICE_APPROACHING -- qualified, untested, and price is within one
                         zone-height of the nearer boundary (not inside yet).
    FIRST_TEST        -- price is inside the zone for the first time.
    REACTION          -- price has touched the zone more than once; still
                         trading near it (within one zone-height).
    TESTED_DEGRADED   -- touched multiple times AND price has since moved
                         away -- the zone's significance is considered
                         diminished (matches Setup #1's "once a zone has
                         been tested, it loses significance" rule).

INFORMATION ONLY -- see fvp_analysis.py's module docstring for scope.
"""

from __future__ import annotations

from .zone_state import VolumeZone, contains

APPROACH_MULTIPLE = 1.0  # "nearby" = within one zone-height of a boundary


class ZoneLifecycleState:
    DISCOVERED = "DISCOVERED"
    QUALIFIED = "QUALIFIED"
    UNTESTED = "UNTESTED"
    PRICE_APPROACHING = "PRICE_APPROACHING"
    FIRST_TEST = "FIRST_TEST"
    REACTION = "REACTION"
    TESTED_DEGRADED = "TESTED_DEGRADED"


def _distance_to_zone(zone: VolumeZone, price: float) -> float:
    if contains(zone, price):
        return 0.0
    if price > zone.upper_price:
        return price - zone.upper_price
    return zone.lower_price - price


def classify_lifecycle(zone: VolumeZone, current_price: float) -> str:
    height = zone.upper_price - zone.lower_price
    if height <= 0:
        return ZoneLifecycleState.QUALIFIED  # degenerate zone -- nothing more to say

    distance = _distance_to_zone(zone, current_price)
    inside = distance == 0.0
    nearby = distance <= height * APPROACH_MULTIPLE

    if not zone.tested:
        if inside:
            return ZoneLifecycleState.FIRST_TEST
        if nearby:
            return ZoneLifecycleState.PRICE_APPROACHING
        return ZoneLifecycleState.UNTESTED

    # zone.tested is True from here on.
    if zone.first_test and inside:
        return ZoneLifecycleState.FIRST_TEST
    if inside or nearby:
        return ZoneLifecycleState.REACTION
    return ZoneLifecycleState.TESTED_DEGRADED
