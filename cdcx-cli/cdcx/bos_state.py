"""
bos_state.py
------------
Classifies a swing-based Break of Structure (market_structure.py) into a
persistent state across scans, instead of the raw BOS flag re-deriving
"Bullish BOS" / "Bearish BOS" / "None" fresh on every call from whichever
swing point is currently most recent. Confirmed live (XRP/USD, 2026-09):
the same uptrend produced "Bullish BOS" on one scan, "None" two scans
later with no reversal, then "Bullish BOS" again -- not a bug, just what a
stateless "is price still beyond the latest labeled swing" check does as
the swing-pivot window slides forward. This module answers the different,
higher-level question: given the specific swing point structure.py's BOS
flag most recently referenced, what actually happened to price *since*
that break?

Deliberately reuses structure_levels.detect_breakout / detect_retest
as-is -- both are already level-agnostic (any price + direction), so the
only new work here is pointing them at a swing high/low instead of a
POC/VAH/VAL level. No new breakout/retest algorithm.

Informational only, same as structure_report.py (which this is meant to
be printed alongside): never consulted by the confluence/execution gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from . import structure_levels
from .indicators.market_structure import MarketStructureResult

# "no_break"     -- no confirmed break of either swing extreme in the
#                    lookback window (structure_levels.BREAKOUT_LOOKBACK).
# "continuation" -- broke, and price never came back to retest the level
#                    (still running -- the "price holds above and makes
#                    higher highs" case).
# "retest_held"  -- broke, price returned to the level, and held (closed
#                    on the breakout side) -- bullish/bearish acceptance.
# "retest_failed"-- broke, price returned to the level, and closed back
#                    through it -- structural deterioration.
BosStateName = str


@dataclass
class BosState:
    state: BosStateName
    direction: Optional[str] = None       # "up" | "down", None for no_break
    level_price: Optional[float] = None   # the specific swing high/low that broke
    reasons: list[str] = field(default_factory=list)


def _most_recent_labeled(swings, kind: str):
    labeled = [s for s in swings if s.kind == kind and s.label]
    return labeled[-1] if labeled else None


def classify_bos_state(
    structure_result: MarketStructureResult,
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], volumes: Sequence[float],
) -> BosState:
    """Reports on whichever break structure_result.bos currently names
    (Bullish BOS -> the break of the most recent labeled swing high,
    Bearish BOS -> the swing low) so this never contradicts the raw flag
    printed right above it. Only when the raw flag has slid back to "None"
    (per this module's docstring -- a stateless read, not evidence the
    break stopped mattering) does it fall back to whichever side has a
    breakout at all in the lookback window, most recent by bar index."""
    last_high = _most_recent_labeled(structure_result.swings, "high")
    last_low = _most_recent_labeled(structure_result.swings, "low")

    # min_index: only closes AFTER the swing formed can break it. Without
    # this, a close from hours before the swing existed (inside the same
    # 20-bar lookback) was reported as its "break" -- confirmed live,
    # XRP/USD 1H 2026-09-27: "bullish break of 1.5298" cited a 12:00 close
    # of 1.5363, nine hours before the 21:00 swing high at 1.5298 formed.
    up = None
    if last_high is not None:
        up = structure_levels.detect_breakout(
            highs, lows, closes, volumes,
            level_price=last_high.price, level_name="resistance", direction="up",
            min_index=last_high.index + 1,
        )
    down = None
    if last_low is not None:
        down = structure_levels.detect_breakout(
            highs, lows, closes, volumes,
            level_price=last_low.price, level_name="support", direction="down",
            min_index=last_low.index + 1,
        )

    if structure_result.bos == "Bullish BOS":
        breakout = up
    elif structure_result.bos == "Bearish BOS":
        breakout = down
    else:
        candidates = [b for b in (up, down) if b is not None]
        breakout = max(candidates, key=lambda b: b.index) if candidates else None

    if breakout is None:
        return BosState(state="no_break", reasons=["No confirmed swing break in the lookback window."])

    retest = structure_levels.detect_retest(highs, lows, closes, breakout)

    if retest.retest_index == -1:
        state = "continuation"
    elif retest.held:
        state = "retest_held"
    else:
        state = "retest_failed"

    kind = "swing high" if breakout.direction == "up" else "swing low"
    reasons = [
        f"{'Bullish' if breakout.direction == 'up' else 'Bearish'} break of {kind} "
        f"{breakout.level_price:.6f} at bar {breakout.index} "
        f"(volume {'confirmed' if breakout.volume_confirmed else 'not confirmed'})."
    ]
    reasons.extend(retest.reasons)

    return BosState(state=state, direction=breakout.direction, level_price=breakout.level_price, reasons=reasons)


def format_bos_state(bos: BosState) -> str:
    if bos.state == "no_break":
        return "BOS STATE: No confirmed break"

    side = "bullish" if bos.direction == "up" else "bearish"
    level = f"{side} break of {bos.level_price:.6f}"

    if bos.state == "continuation":
        return f"BOS STATE: Continuation ({level}, unchallenged)"
    if bos.state == "retest_held":
        return f"BOS STATE: Retest Held ({level} confirmed)"
    if bos.state == "retest_failed":
        # A failed retest means price closed back through the level, which
        # is bearish news when the break itself was bullish (the breakout
        # reversed -- real deterioration) but is BULLISH news when the
        # break was bearish (a bullish reclaim of the level, not
        # deterioration) -- direction of the break and direction of the
        # consequence are opposite, so this can't share one static phrase.
        consequence = "bearish reversal" if bos.direction == "up" else "bullish reclaim"
        return f"BOS STATE: Retest Failed -- {consequence} ({level} invalidated)"
    return f"BOS STATE: {bos.state}"
