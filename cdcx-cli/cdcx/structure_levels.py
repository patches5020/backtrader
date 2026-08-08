"""
structure_levels.py
--------------------
Named structural levels + market-condition classification for ONE
timeframe, per the chart-analysis component spec:

    Letter  Component                      Display        Backed by
    ------  ------------------------------  -------------  ------------------------------------
    A       POC (Point of Control)          WHITE level    indicators.volume_profile_fixed (poc)
    B       FVG (Fair Value Gap)            zone           indicators.fair_value_gap
    C       Volume High / Resistance        GREEN level    indicators.volume_profile_fixed (vah)
    D       Volume Low / Support            RED level      indicators.volume_profile_fixed (val)
    E       Consolidation                   market cond.   ranging regime + contracting ATR
    F       Ranging                         market cond.   regime.py's "ranging" state
    G       Breakout                        price event    detect_breakout() below
    H       Retest                          price event    detect_retest() below

This module doesn't recompute any indicator math on its own -- it names
and classifies what volume_profile_fixed / fair_value_gap / regime /
atr_ema_variant1 already calculate, then adds the two genuinely new
detectors (G, H) that nothing else in this codebase provides: a decisive
close through a named level (breakout), and a controlled return to that
level afterward without re-crossing it (retest).

See structure_strategy.py for how these combine, across the 1W/1D/4H/1H
timeframe roles, into an actual LONG/SHORT entry decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional, Sequence

from . import regime as regime_module
from .indicators import atr_ema_variant1, fair_value_gap, volume_profile_fixed

Condition = Literal["consolidation", "ranging", "trending", "transitional"]
Direction = Literal["up", "down"]
LevelName = Literal["poc", "resistance", "support"]

# How far beyond a level a close must land to count as a decisive breakout,
# expressed as a multiple of that timeframe's own ATR -- a level "brushed"
# by a wick or a marginal close doesn't count.
BREAKOUT_ATR_MULTIPLE = 0.25
# How many bars back to look for a breakout at all.
BREAKOUT_LOOKBACK = 20
# How close (in ATR multiples) price must return to a broken level to count
# as touching it for a retest.
RETEST_PROXIMITY_ATR_MULTIPLE = 0.5
# How many bars after a breakout to wait for a retest before giving up.
RETEST_MAX_LOOKAHEAD = 20
# An FVG counts as "near" a volume level (POC/support/resistance) when the
# gap's nearer edge sits within this many ATR of the level -- used for the
# FVG+POC/volume confluence entry, not for the breakout+retest entry.
FVG_LEVEL_PROXIMITY_ATR_MULTIPLE = 0.75


@dataclass
class StructureMap:
    poc: float                      # A -- WHITE
    resistance: float                # C -- GREEN (VAH)
    support: float                   # D -- RED (VAL)
    fvgs: list[fair_value_gap.FVG]   # B
    condition: Condition              # E / F (+ trending/transitional passthrough)
    regime: "regime_module.RegimeResult"


@dataclass
class BreakoutEvent:
    index: int                       # bar index (into the series passed to detect_breakout) of the breakout close
    direction: Direction
    level_name: LevelName
    level_price: float
    close_price: float
    volume_confirmed: bool


@dataclass
class RetestEvent:
    breakout: BreakoutEvent
    retest_index: int
    held: bool                        # True: price returned to the level and did NOT close back through it
    reasons: list[str] = field(default_factory=list)


def classify_condition(regime_state: str, atr_label: str) -> Condition:
    """"Consolidation" is the tighter of the two non-trending conditions: a
    ranging regime whose ATR is actively contracting (the range is still
    narrowing). A ranging regime with flat/expanding ATR is just "ranging"
    -- an established range, not one still compressing. Trending and
    transitional pass through unchanged."""
    if regime_state == "ranging" and atr_label == "Contraction":
        return "consolidation"
    return regime_state  # "ranging" | "trending" | "transitional"


def compute_structure_map(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], volumes: Sequence[float],
    higher_timeframes_aligned: bool = False,
) -> StructureMap:
    """Convenience wrapper: everything needed for one timeframe's StructureMap
    from raw OHLCV, reusing the same indicator modules `engine.py` does."""
    vp_result = volume_profile_fixed.analyze(highs, lows, volumes, price=closes[-1])
    fvgs = fair_value_gap.detect_fvgs(highs, lows, closes)
    regime_result = regime_module.analyze(
        highs, lows, closes, volumes, higher_timeframes_aligned=higher_timeframes_aligned,
    )

    atr_series = atr_ema_variant1.calculate_atr(highs, lows, closes)
    _, atr_label = atr_ema_variant1.score_atr_expansion(atr_series)
    condition = classify_condition(regime_result.regime, atr_label)

    return StructureMap(
        poc=vp_result.poc, resistance=vp_result.vah, support=vp_result.val,
        fvgs=fvgs, condition=condition, regime=regime_result,
    )


def detect_breakout(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], volumes: Sequence[float],
    level_price: float, level_name: LevelName, direction: Direction,
    lookback: int = BREAKOUT_LOOKBACK, atr_multiple: float = BREAKOUT_ATR_MULTIPLE,
) -> Optional[BreakoutEvent]:
    """
    Scans the most recent `lookback` closed bars for a decisive close beyond
    `level_price` in `direction`:

        up:   close > level_price + atr_multiple * ATR
        down: close < level_price - atr_multiple * ATR

    Returns the MOST RECENT qualifying bar (closest to the end of the
    series), or None if no such breakout occurred in the window.
    `volume_confirmed` flags whether that bar's volume was at/above the
    lookback average -- a genuine breakout should trade more, not less,
    than the consolidation it's leaving, but this is informational only
    (not required for the event to be returned).
    """
    n = len(closes)
    if n < 2:
        return None

    atr_series = atr_ema_variant1.calculate_atr(highs, lows, closes)
    start = max(atr_ema_variant1.ATR_LENGTH, n - lookback)

    avg_volume = sum(volumes[start:n]) / max(1, n - start)

    for i in range(n - 1, start - 1, -1):
        atr = atr_series[i]
        threshold = atr_multiple * atr
        close = closes[i]

        if direction == "up" and close > level_price + threshold:
            return BreakoutEvent(
                index=i, direction="up", level_name=level_name, level_price=level_price,
                close_price=close, volume_confirmed=volumes[i] >= avg_volume,
            )
        if direction == "down" and close < level_price - threshold:
            return BreakoutEvent(
                index=i, direction="down", level_name=level_name, level_price=level_price,
                close_price=close, volume_confirmed=volumes[i] >= avg_volume,
            )

    return None


def detect_retest(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
    breakout: BreakoutEvent,
    max_lookahead: int = RETEST_MAX_LOOKAHEAD, proximity_atr_multiple: float = RETEST_PROXIMITY_ATR_MULTIPLE,
) -> Optional[RetestEvent]:
    """
    Looks forward from `breakout.index` for price returning to within
    `proximity_atr_multiple` * ATR of the broken level. The first bar to
    touch that zone is the retest; `held` is False if any bar from the
    retest onward (within the same lookahead window) closes back through
    the level in the direction that would invalidate the breakout --
    i.e. a genuine hold-and-continue, not a failed breakout that reversed.
    """
    n = len(closes)
    atr_series = atr_ema_variant1.calculate_atr(highs, lows, closes)
    end = min(n, breakout.index + 1 + max_lookahead)

    retest_index: Optional[int] = None
    for i in range(breakout.index + 1, end):
        atr = atr_series[i]
        proximity = proximity_atr_multiple * atr
        touched_from_above = breakout.direction == "up" and lows[i] <= breakout.level_price + proximity
        touched_from_below = breakout.direction == "down" and highs[i] >= breakout.level_price - proximity
        if touched_from_above or touched_from_below:
            retest_index = i
            break

    if retest_index is None:
        return RetestEvent(
            breakout=breakout, retest_index=-1, held=False,
            reasons=[f"No retest of {breakout.level_name} within {max_lookahead} bars of the breakout."],
        )

    held = True
    reasons = [f"Retest touched {breakout.level_name} at bar {retest_index}."]
    for i in range(retest_index, end):
        if breakout.direction == "up" and closes[i] < breakout.level_price:
            held = False
            reasons.append(f"Closed back below {breakout.level_name} at bar {i} -- breakout failed.")
            break
        if breakout.direction == "down" and closes[i] > breakout.level_price:
            held = False
            reasons.append(f"Closed back above {breakout.level_name} at bar {i} -- breakout failed.")
            break
    else:
        reasons.append(f"Held {breakout.level_name} through bar {end - 1} -- retest confirmed.")

    return RetestEvent(breakout=breakout, retest_index=retest_index, held=held, reasons=reasons)


def find_fvg_near_level(
    fvgs: list[fair_value_gap.FVG], level_price: float, atr: float, kind: Literal["bullish", "bearish"],
    proximity_atr_multiple: float = FVG_LEVEL_PROXIMITY_ATR_MULTIPLE,
) -> Optional[fair_value_gap.FVG]:
    """The most recent unfilled FVG of `kind` whose nearer edge sits within
    `proximity_atr_multiple` * ATR of `level_price` -- the "FVG + POC/volume
    confluence" half of the entry spec. Returns None if no unfilled gap of
    that kind is close enough to the level to call it confluence rather than
    coincidence."""
    proximity = proximity_atr_multiple * atr
    candidates = [g for g in fvgs if not g.filled and g.kind == kind]
    for gap in reversed(candidates):  # most recent first
        nearer_edge = min(abs(gap.top - level_price), abs(gap.bottom - level_price))
        if nearer_edge <= proximity:
            return gap
    return None


def format_structure_map(name: str, s: StructureMap) -> str:
    lines = [
        "-" * 49,
        f"STRUCTURE — {name}".center(49),
        "-" * 49,
        f"POC (white):         {s.poc:.6f}",
        f"Resistance (green):  {s.resistance:.6f}",
        f"Support (red):       {s.support:.6f}",
        f"FVGs:                {len(s.fvgs)} total, {sum(1 for g in s.fvgs if not g.filled)} unfilled",
        f"Condition:           {s.condition.upper()}",
        "-" * 49,
    ]
    return "\n".join(lines)
