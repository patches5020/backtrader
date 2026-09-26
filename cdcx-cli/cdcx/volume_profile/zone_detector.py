"""
zone_detector.py
------------------
Builds VolumeZone objects from cdcx's EXISTING, unmodified Fixed/Anchored
Volume Profile calculations (cdcx.indicators.volume_profile_fixed/
volume_profile_anchor) -- no volume-profile math is reimplemented here.

The zone boundary is the value area itself ([VAL, VAH]), since that's
already defined as "the range containing 70% of traded volume" by the
existing indicators -- exactly the "heavy volume cluster" concept the
Trader Dale-style setups are built around. POC is carried as the zone's
point of control.

INFORMATION ONLY -- see fvp_analysis.py's module docstring for scope.
"""

from __future__ import annotations

from typing import Sequence

from cdcx.indicators import volume_profile_fixed, volume_profile_anchor
from .zone_state import VolumeZone, compute_tested_state


def detect_fixed_zone(
    highs: Sequence[float], lows: Sequence[float], volumes: Sequence[float],
    price: float, timeframe: str, lookback: int = volume_profile_fixed.DEFAULT_LOOKBACK,
) -> VolumeZone:
    result = volume_profile_fixed.analyze(highs, lows, volumes, price=price, lookback=lookback)
    zone = VolumeZone(
        timeframe=timeframe, zone_type="fixed_value_area",
        lower_price=result.val, upper_price=result.vah, poc_price=result.poc,
    )
    formed_at_index = max(0, len(highs) - lookback)
    return compute_tested_state(zone, highs, lows, formed_at_index)


def detect_anchored_zone(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], volumes: Sequence[float],
    price: float, timeframe: str, anchor_lookback: int = 50, anchor_mode: str = "swing_low",
) -> VolumeZone:
    result = volume_profile_anchor.analyze(
        highs, lows, closes, volumes, price=price,
        anchor_lookback=anchor_lookback, anchor_mode=anchor_mode,
    )
    zone = VolumeZone(
        timeframe=timeframe, zone_type="anchored_value_area",
        lower_price=result.val, upper_price=result.vah, poc_price=result.poc,
    )
    return compute_tested_state(zone, highs, lows, result.anchor_index)
