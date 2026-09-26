"""
vp_setup.py
------------
Volume Profile setup classification -- informational context only (Mode A).

Labels the current market situation relative to the Fixed Volume Profile's
POC/VAH/VAL as one of the three setups from the "Volume Profile Setup
Classification" flowchart, or "none" if no such setup is currently forming:

    POC_BOUNCE            price left the value area, returned to POC, and is
                           sitting there (a possible rejection point)
    VALUE_AREA_REVERSAL   price broke outside the value area (through VAH or
                           VAL) and that break failed -- price reclaimed the
                           value area
    VALUE_AREA_BREAKOUT   price broke outside the value area and is holding
                           the break (retest held, or no retest yet)

This is pure classification: it does NOT feed TradeSignal's score, direction
bias, or the --execute confluence gate -- exactly like bos_state.py's
relationship to the raw BOS flag. It exists so the report can say *what kind*
of situation the market is in, without changing what --execute decides.

Reuses structure_levels.detect_breakout() / detect_retest() against VAH/VAL
(the same primitives bos_state.py reuses against swing highs/lows) rather
than inventing new breakout/retest logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from . import structure_levels
from .indicators import atr_ema_variant1

VpSetupName = str  # "poc_bounce" | "value_area_reversal" | "value_area_breakout" | "none"

# How close price must sit to POC (in ATR multiples) to count as "returned to POC".
POC_PROXIMITY_ATR_MULTIPLE = 0.5
# How many prior closed bars to look back for a prior excursion outside the value area.
# Deliberately longer than structure_levels.BREAKOUT_LOOKBACK: any excursion still
# inside the breakout window is handled by the breakout/retest branch above (which
# runs first and is more specific), so this only needs to reach further back, to the
# "previous session went outside the value area" case the breakout window has already
# aged out of.
POC_BOUNCE_LOOKBACK = structure_levels.BREAKOUT_LOOKBACK * 2


@dataclass
class VpSetup:
    setup_type: VpSetupName
    direction: Optional[str] = None  # "up" | "down"
    reasons: list[str] = field(default_factory=list)


def _recent_excursion(closes: Sequence[float], vah: float, val: float, lookback: int) -> Optional[str]:
    """"above" if any of the last `lookback` closes (excluding the current
    bar) traded above VAH, "below" if any traded below VAL, else None."""
    window = closes[-1 - lookback:-1] if len(closes) > 1 else []
    if any(c > vah for c in window):
        return "above"
    if any(c < val for c in window):
        return "below"
    return None


def classify_vp_setup(
    price: float, poc: float, vah: float, val: float,
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], volumes: Sequence[float],
) -> VpSetup:
    breakout_up = structure_levels.detect_breakout(
        highs, lows, closes, volumes, level_price=vah, level_name="resistance", direction="up",
    )
    breakout_down = structure_levels.detect_breakout(
        highs, lows, closes, volumes, level_price=val, level_name="support", direction="down",
    )
    candidates = [b for b in (breakout_up, breakout_down) if b is not None]
    breakout = max(candidates, key=lambda b: b.index) if candidates else None

    if breakout is not None:
        side = "VAH" if breakout.level_name == "resistance" else "VAL"
        kind = "Bullish" if breakout.direction == "up" else "Bearish"
        retest = structure_levels.detect_retest(highs, lows, closes, breakout)

        if retest.retest_index == -1:
            return VpSetup(
                setup_type="value_area_breakout", direction=breakout.direction,
                reasons=[f"{kind} break of {side} {breakout.level_price:.6f} at bar {breakout.index}, no retest yet."],
            )
        if retest.held:
            return VpSetup(
                setup_type="value_area_breakout", direction=breakout.direction,
                reasons=[f"{kind} break of {side} {breakout.level_price:.6f}, retest held."] + retest.reasons,
            )
        # Retest failed: price closed back through the level -- the breakout
        # reversed and price is back inside the value area.
        reversal_direction = "down" if breakout.direction == "up" else "up"
        return VpSetup(
            setup_type="value_area_reversal", direction=reversal_direction,
            reasons=[f"Failed {side} breakout -- price reclaimed the value area."] + retest.reasons,
        )

    atr_series = atr_ema_variant1.calculate_atr(highs, lows, closes)
    atr = atr_series[-1] if atr_series else 0.0
    if atr and abs(price - poc) <= POC_PROXIMITY_ATR_MULTIPLE * atr:
        prior_side = _recent_excursion(closes, vah, val, POC_BOUNCE_LOOKBACK)
        if prior_side == "above":
            return VpSetup(
                setup_type="poc_bounce", direction="down",
                reasons=[f"Price returned to POC {poc:.6f} after trading above VAH -- possible rejection."],
            )
        if prior_side == "below":
            return VpSetup(
                setup_type="poc_bounce", direction="up",
                reasons=[f"Price returned to POC {poc:.6f} after trading below VAL -- possible rejection."],
            )

    return VpSetup(setup_type="none", reasons=["No POC Bounce / Value Area Reversal / Value Area Breakout currently forming."])


def format_vp_setup(vp: VpSetup) -> str:
    if vp.setup_type == "none":
        return "VP SETUP: None"
    label = {
        "poc_bounce": "POC Bounce",
        "value_area_reversal": "Value Area Reversal",
        "value_area_breakout": "Value Area Breakout",
    }.get(vp.setup_type, vp.setup_type)
    side = "bullish" if vp.direction == "up" else "bearish"
    return f"VP SETUP: {label} ({side})"
