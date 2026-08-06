"""
structure_strategy.py
----------------------
Combines structure_levels.py across the 1W/1D/4H/1H role hierarchy into an
actual LONG/SHORT entry decision:

    1W -> major structure        advisory bias: which side of the weekly
                                  POC is price on right now?
    1D -> major volume structure the POC / resistance / support levels
                                  that the 4H setup trades against
    4H -> primary setup          where the breakout+retest, or the FVG +
                                  volume confluence, is actually detected
    1H -> entry confirmation     does the fastest timeframe agree, right
                                  now, with the direction the setup implies?

Three triggers, exactly as specified (no unrequested symmetric variants
added -- e.g. there's no bearish FVG-confluence trigger below because it
wasn't part of the spec, even though structure_levels.find_fvg_near_level
would support one trivially):

    LONG  breakout_retest:  4H closes through the 1D support/low-volume
                             area -> retest holds -> 1H confirms bullish.
    LONG  fvg_confluence:   an unfilled bullish 4H FVG sits near the 1D
                             POC or support -> price reacts bullishly ->
                             1H confirms bullish.
    SHORT breakdown_retest: 4H closes through the 1D resistance/high-
                             volume area -> retest holds -> 1H confirms
                             bearish.

1W is advisory, not a hard gate: LONG triggers only fire with price on the
bullish side of the weekly POC, SHORT only on the bearish side -- matching
"major structure" as context the lower timeframes shouldn't fight, not a
pass/fail checklist item of its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional, Sequence

from . import structure_levels
from .indicators import atr_ema_variant1, candlestick_patterns

Direction = Literal["long", "short"]


@dataclass
class StructureSetup:
    direction: Optional[Direction]
    valid: bool
    trigger: str  # "breakout_retest" | "fvg_confluence" | ""
    reasons: list[str] = field(default_factory=list)
    entry: Optional[float] = None
    stop_level: Optional[float] = None  # the broken/tested level -- the natural stop reference


def weekly_bias(w1: structure_levels.StructureMap, price: float) -> str:
    """'bullish' if price trades above the weekly POC, 'bearish' if below,
    'neutral' exactly at it (neither LONG nor SHORT is blocked by neutral --
    only an opposing bias blocks the opposing side's triggers)."""
    if price > w1.poc:
        return "bullish"
    if price < w1.poc:
        return "bearish"
    return "neutral"


def _confirm_1h(
    h1_highs: Sequence[float], h1_lows: Sequence[float], h1_opens: Sequence[float], h1_closes: Sequence[float],
    direction: Direction,
) -> tuple[bool, str]:
    wanted = "bullish" if direction == "long" else "bearish"
    matches = candlestick_patterns.detect_patterns(h1_highs, h1_lows, h1_opens, h1_closes)
    hits = [m for m in matches if m.direction == wanted]
    if hits:
        strongest = max(hits, key=lambda m: m.strength)
        return True, f"1H confirmation: {strongest.name} ({wanted}, strength {strongest.strength})."
    return False, f"1H shows no {wanted} confirmation pattern on the latest candle."


def _try_breakout_retest(
    d1: structure_levels.StructureMap,
    h4_highs: Sequence[float], h4_lows: Sequence[float], h4_closes: Sequence[float], h4_volumes: Sequence[float],
    h1_highs: Sequence[float], h1_lows: Sequence[float], h1_opens: Sequence[float], h1_closes: Sequence[float],
    direction: Direction,
) -> Optional[StructureSetup]:
    if direction == "long":
        level_name, level_price = "support", d1.support
        breakout_direction = "up"
    else:
        level_name, level_price = "resistance", d1.resistance
        breakout_direction = "down"

    reasons = []
    breakout = structure_levels.detect_breakout(
        h4_highs, h4_lows, h4_closes, h4_volumes,
        level_price=level_price, level_name=level_name, direction=breakout_direction,
    )
    if breakout is None:
        reasons.append(f"No 4H {'breakout above' if direction == 'long' else 'breakdown below'} "
                        f"1D {level_name} ({level_price:.6f}) in the lookback window.")
        return StructureSetup(direction=None, valid=False, trigger="breakout_retest", reasons=reasons)

    verb = "breakout above" if direction == "long" else "breakdown below"
    reasons.append(f"4H {verb} 1D {level_name} ({level_price:.6f}) at bar {breakout.index} "
                    f"(volume {'confirmed' if breakout.volume_confirmed else 'not confirmed'}).")

    retest = structure_levels.detect_retest(h4_highs, h4_lows, h4_closes, breakout)
    reasons.extend(retest.reasons)
    if not retest.held:
        return StructureSetup(direction=None, valid=False, trigger="breakout_retest", reasons=reasons)

    confirmed, note = _confirm_1h(h1_highs, h1_lows, h1_opens, h1_closes, direction)
    reasons.append(note)
    if not confirmed:
        return StructureSetup(direction=None, valid=False, trigger="breakout_retest", reasons=reasons)

    return StructureSetup(
        direction=direction, valid=True, trigger="breakout_retest", reasons=reasons,
        entry=h1_closes[-1], stop_level=level_price,
    )


def _try_fvg_confluence(
    d1: structure_levels.StructureMap, h4: structure_levels.StructureMap,
    h4_highs: Sequence[float], h4_lows: Sequence[float], h4_closes: Sequence[float],
    h1_highs: Sequence[float], h1_lows: Sequence[float], h1_opens: Sequence[float], h1_closes: Sequence[float],
) -> StructureSetup:
    reasons = []
    atr_series = atr_ema_variant1.calculate_atr(h4_highs, h4_lows, h4_closes)
    atr = atr_series[-1]

    gap = None
    for level_name, level_price in (("support", d1.support), ("poc", d1.poc)):
        gap = structure_levels.find_fvg_near_level(h4.fvgs, level_price, atr, kind="bullish")
        if gap is not None:
            reasons.append(f"4H bullish FVG [{gap.bottom:.6f}, {gap.top:.6f}] sits near 1D {level_name} "
                            f"({level_price:.6f}).")
            break

    if gap is None:
        reasons.append("No unfilled 4H bullish FVG near the 1D POC or support.")
        return StructureSetup(direction=None, valid=False, trigger="fvg_confluence", reasons=reasons)

    # "Bullish reaction": the most recent 4H bar traded into the gap and
    # closed back above it -- a wick-and-reject, not a clean break through.
    price = h4_closes[-1]
    reacted = h4_lows[-1] <= gap.top and price > gap.bottom
    reasons.append(
        f"4H bullish reaction at the gap: {'yes' if reacted else 'no'} "
        f"(low {h4_lows[-1]:.6f}, close {price:.6f})."
    )
    if not reacted:
        return StructureSetup(direction=None, valid=False, trigger="fvg_confluence", reasons=reasons)

    confirmed, note = _confirm_1h(h1_highs, h1_lows, h1_opens, h1_closes, "long")
    reasons.append(note)
    if not confirmed:
        return StructureSetup(direction=None, valid=False, trigger="fvg_confluence", reasons=reasons)

    return StructureSetup(
        direction="long", valid=True, trigger="fvg_confluence", reasons=reasons,
        entry=h1_closes[-1], stop_level=gap.bottom,
    )


def evaluate_structure_setup(
    w1: structure_levels.StructureMap,
    d1: structure_levels.StructureMap,
    h4: structure_levels.StructureMap,
    h4_highs: Sequence[float], h4_lows: Sequence[float], h4_closes: Sequence[float], h4_volumes: Sequence[float],
    h1_highs: Sequence[float], h1_lows: Sequence[float], h1_opens: Sequence[float], h1_closes: Sequence[float],
) -> StructureSetup:
    """Evaluates all three triggers in order (breakout_retest LONG, then
    fvg_confluence LONG, then breakdown_retest SHORT) and returns the first
    that qualifies. If none qualify, returns the last-attempted setup's
    reasons (whichever ran last) so the caller still has something to show
    for why nothing fired -- callers that need every attempt's reasoning
    should call the `_try_*` helpers directly instead."""
    price = h4_closes[-1]
    bias = weekly_bias(w1, price)
    header = [f"1W major structure: price is {bias} of the weekly POC ({w1.poc:.6f})."]

    last: Optional[StructureSetup] = None

    if bias != "bearish":
        result = _try_breakout_retest(
            d1, h4_highs, h4_lows, h4_closes, h4_volumes, h1_highs, h1_lows, h1_opens, h1_closes, "long",
        )
        result.reasons = header + result.reasons
        if result.valid:
            return result
        last = result

        result = _try_fvg_confluence(d1, h4, h4_highs, h4_lows, h4_closes, h1_highs, h1_lows, h1_opens, h1_closes)
        result.reasons = header + result.reasons
        if result.valid:
            return result
        last = result

    if bias != "bullish":
        result = _try_breakout_retest(
            d1, h4_highs, h4_lows, h4_closes, h4_volumes, h1_highs, h1_lows, h1_opens, h1_closes, "short",
        )
        result.reasons = header + result.reasons
        if result.valid:
            return result
        last = result

    if last is None:
        # bias blocked every trigger outright (shouldn't happen: bias is
        # only ever bullish/bearish/neutral, and neutral blocks nothing)
        last = StructureSetup(direction=None, valid=False, trigger="", reasons=header)

    return last


def format_structure_setup(result: StructureSetup) -> str:
    lines = ["-" * 49, "STRUCTURE SETUP (1W/1D/4H/1H)".center(49), "-" * 49]
    lines.extend(result.reasons)
    lines.append("-" * 49)
    if result.valid:
        lines.append(
            f"SETUP: {result.direction.upper()} via {result.trigger} -- "
            f"entry ~{result.entry:.6f}  stop reference: {result.stop_level:.6f}"
        )
    else:
        lines.append("SETUP: NO TRADE -- no qualifying structure setup right now.")
    lines.append("-" * 49)
    return "\n".join(lines)
