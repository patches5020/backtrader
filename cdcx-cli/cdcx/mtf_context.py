"""
mtf_context.py
----------------
Two informational summaries added as a follow-on to entry_location.py, both
purely descriptive -- context only (Mode A), never touch score, confluence,
the entry checklist, or any entry/SL/TP/R:R/risk calculation:

1. ATR alignment: how many of the 1W/1D/4H/1H timeframes are in ATR
   Expansion right now (each TradeSignal already carries this in
   `.labels["atr_expansion"]` -- see engine.py). ATR answers WHEN a market
   is actually moving, never WHERE to enter or WHETHER a trade is valid --
   alignment here describes momentum breadth, it does not authorize
   anything by itself.

2. Volume Profile hierarchy: labels each timeframe's already-computed
   vp_setup (vp_setup.py) with its structural ROLE in the 1W -> 1D -> 4H ->
   1H hierarchy this codebase already uses everywhere else (see
   structure_report.py's "STRUCTURE -- 1W (major structure)" /
   "STRUCTURE -- 4H (primary setup)" headers):
       1W -> macro location
       1D -> major trend/value location
       4H -> setup location
       1H -> entry-area location
   Also flags when the slowest timeframe carrying a VP direction disagrees
   with the fastest one -- confirmed live (XRP/USD, 2026-09-22 Run 21):
   1H/4H/1D all read "Value Area Breakout (bullish)" while 1W still read
   "Value Area Breakout (bearish)" (price still below the weekly VAL) --
   short-term strength with an unconfirmed higher-timeframe location, not a
   contradiction to alarm over.

Lower timeframes (anything under 1h that was requested, e.g. 45m/15m/5m) are
listed too, on their own lines marked "context only": they never change the
x/4 ATR count, the four roles, or the macro-conflict note above.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from .no_trade_gate import timeframe_to_seconds

TIMEFRAME_ORDER = ["1w", "1d", "4h", "1h"]  # macro -> entry, matches this codebase's existing hierarchy

VP_ROLE_BY_TIMEFRAME = {
    "1w": "macro location",
    "1d": "major trend/value location",
    "4h": "setup location",
    "1h": "entry-area location",
}

VP_SETUP_LABELS = {
    "poc_bounce": "POC Bounce",
    "value_area_reversal": "Value Area Reversal",
    "value_area_breakout": "Value Area Breakout",
    "none": "None",
}


def lower_timeframes(timeframes: Iterable[str]) -> list[str]:
    """Requested timeframes below 1h, slowest first (45m, 30m, 15m, 10m, 5m, 1m)."""
    lower = [tf for tf in dict.fromkeys(timeframes) if tf not in TIMEFRAME_ORDER
             and (timeframe_to_seconds(tf) or 0) and timeframe_to_seconds(tf) < 3600]
    return sorted(lower, key=lambda tf: -timeframe_to_seconds(tf))


def direction_word(direction: Optional[str]) -> str:
    if direction == "up":
        return "bullish"
    if direction == "down":
        return "bearish"
    return "n/a"


@dataclass
class AtrAlignment:
    by_timeframe: dict = field(default_factory=dict)  # tf -> "Expansion" | "Flat" | "Contraction" | "n/a"
    expansion_count: int = 0
    total_count: int = 0
    lower: dict = field(default_factory=dict)         # lower tf -> label; context only, NOT in the counts above


@dataclass
class VpHierarchyEntry:
    timeframe: str
    role: str
    setup_type: str
    direction: Optional[str]


@dataclass
class VpHierarchy:
    entries: list = field(default_factory=list)
    macro_conflict: Optional[str] = None  # set when the slowest and fastest directional readings disagree
    lower_entries: list = field(default_factory=list)  # lower timeframes; context only, not in macro_conflict


def build_atr_alignment(results: dict) -> AtrAlignment:
    by_timeframe = {}
    for tf in TIMEFRAME_ORDER:
        signal = results.get(tf)
        by_timeframe[tf] = signal.labels.get("atr_expansion", "n/a") if signal is not None else "n/a"
    expansion_count = sum(1 for label in by_timeframe.values() if label == "Expansion")
    total_count = sum(1 for label in by_timeframe.values() if label != "n/a")
    lower = {tf: results[tf].labels.get("atr_expansion", "n/a")
             for tf in lower_timeframes(results) if results.get(tf) is not None}
    return AtrAlignment(by_timeframe=by_timeframe, expansion_count=expansion_count, total_count=total_count,
                        lower=lower)


def build_vp_hierarchy(results: dict) -> VpHierarchy:
    entries = []
    for tf in TIMEFRAME_ORDER:
        signal = results.get(tf)
        if signal is None:
            continue
        entries.append(VpHierarchyEntry(
            timeframe=tf, role=VP_ROLE_BY_TIMEFRAME[tf],
            setup_type=getattr(signal, "vp_setup_type", "none"),
            direction=getattr(signal, "vp_setup_direction", None),
        ))

    macro_conflict = None
    directional = [e for e in entries if e.direction is not None]
    if len(directional) >= 2:
        slow, fast = directional[0], directional[-1]
        if slow.timeframe != fast.timeframe and slow.direction != fast.direction:
            macro_conflict = (
                f"{fast.timeframe.upper()} Volume Profile is {direction_word(fast.direction)} while "
                f"{slow.timeframe.upper()} ({slow.role}) is still {direction_word(slow.direction)} -- "
                f"the higher-timeframe location has not confirmed the move."
            )
    lower_entries = [
        VpHierarchyEntry(timeframe=tf, role="lower timeframe, context only",
                         setup_type=getattr(results[tf], "vp_setup_type", "none"),
                         direction=getattr(results[tf], "vp_setup_direction", None))
        for tf in lower_timeframes(results) if results.get(tf) is not None
    ]
    return VpHierarchy(entries=entries, macro_conflict=macro_conflict, lower_entries=lower_entries)


def format_atr_alignment(alignment: AtrAlignment) -> str:
    lines = [f"ATR ALIGNMENT: {alignment.expansion_count}/{alignment.total_count} timeframes expanding"]
    for tf in TIMEFRAME_ORDER:
        label = alignment.by_timeframe.get(tf, "n/a")
        if label != "n/a":
            lines.append(f"  {tf.upper()}: {label}")
    known = {tf: label for tf, label in alignment.lower.items() if label != "n/a"}
    if known:
        n_exp = sum(1 for label in known.values() if label == "Expansion")
        lines.append(f"  LOWER TIMEFRAMES (context only, not in the {alignment.total_count}): "
                     f"{n_exp}/{len(known)} expanding")
        for tf, label in known.items():
            lines.append(f"    {tf.upper()}: {label}")
    return "\n".join(lines)


def format_vp_hierarchy(hierarchy: VpHierarchy) -> str:
    lines = ["VOLUME PROFILE HIERARCHY:"]
    for entry in hierarchy.entries:
        setup_label = VP_SETUP_LABELS.get(entry.setup_type, entry.setup_type)
        direction_suffix = f" ({direction_word(entry.direction)})" if entry.direction else ""
        lines.append(f"  {entry.timeframe.upper()} [{entry.role}]: {setup_label}{direction_suffix}")
    if hierarchy.macro_conflict:
        lines.append(f"  NOTE: {hierarchy.macro_conflict}")
    for entry in hierarchy.lower_entries:
        setup_label = VP_SETUP_LABELS.get(entry.setup_type, entry.setup_type)
        direction_suffix = f" ({direction_word(entry.direction)})" if entry.direction else ""
        lines.append(f"  {entry.timeframe.upper()} [{entry.role}]: {setup_label}{direction_suffix}")
    return "\n".join(lines)
