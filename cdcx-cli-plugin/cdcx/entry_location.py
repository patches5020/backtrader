"""
entry_location.py
-------------------
Distinguishes two different reasons a run ends in NO TRADE -- requested
directly after reviewing a live run (XRP/USD, 2026-09-22) where all 4
timeframes were TRENDING and bullish, confluence hit 100%, ATR was expanding
on every timeframe, and BOS/FVG/Volume Profile all confirmed direction --
and the system still (correctly) refused the trade because Fibonacci
retracement never formed. A bare "NO TRADE" reads identically to a
genuinely bad/contradictory market. This module classifies which case it
actually is, for display and the trade journal only:

    INVALID     -- market direction itself isn't established: confluence
                   didn't reach the required 2-timeframe majority, the
                   entry-timeframe regime isn't trending, or a non-location
                   checklist item (trend, risk, existing position) failed.
                   There's no "location" to wait for because there's no
                   confirmed direction/context to enter into.
    DEVELOPING  -- direction IS established (confluence passed, regime is
                   trending, every non-location checklist item passed) but
                   Fibonacci and/or Volume Profile -- the two checklist
                   items that answer WHERE to enter, not WHETHER to trade --
                   haven't confirmed yet. "Good market, entry location not
                   confirmed." Subdivided (Phase 2, requested as a direct
                   follow-on) by exactly which location item(s) are still
                   pending, since "waiting on Fibonacci" and "waiting on
                   Volume Profile" call for watching different price action:
                       WAIT_FIB              -- only Fibonacci pending
                       WAIT_VOLUME_PROFILE   -- only Volume Profile pending
                       WAIT_FIB_AND_VP       -- both pending
    CONFIRMED   -- entry_checklist.py's `all_passed` is True: every gate,
                   including the location-specific ones, has confirmed.

Pure narration: it reads the SAME ConfluenceResult / ChecklistResult /
regime string that already drive the real PASS/FAIL decisions in cli.py,
strictly after those have decided, and never feeds back into
confluence.should_execute, entry_checklist.ChecklistResult.all_passed, or
any entry price / stop-loss / take-profit / risk-sizing calculation.

WAIT_RETEST / WAIT_BOS / WAIT_CANDLE_CONFIRMATION were proposed alongside
the three substates above but deliberately not built: entry_checklist.py
has no BOS-retest or candlestick-pattern item that blocks `all_passed`
today (bos_state.py and candlestick_patterns.py are informational, not
gates), so a substate for either would describe a condition the code
doesn't actually enforce -- exactly the kind of gap this module exists to
avoid. If BOS-retest or candlestick confirmation becomes a real checklist
gate, add its substate here the same way Fibonacci/Volume Profile are done.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import confluence as confluence_module
from . import entry_checklist as entry_checklist_module
from . import mtf_context as mtf_context_module

INVALID = "INVALID"
DEVELOPING = "DEVELOPING"
CONFIRMED = "CONFIRMED"

WAIT_FIB = "WAIT_FIB"
WAIT_VOLUME_PROFILE = "WAIT_VOLUME_PROFILE"
WAIT_FIB_AND_VP = "WAIT_FIB_AND_VP"

# The entry_checklist.py items that answer WHERE to enter (an actual price
# location), as opposed to WHETHER a trade is on the table at all (trend
# direction, risk sizing, existing position state). Named by the checklist's
# own item strings so this stays in sync with entry_checklist.py rather than
# re-deriving its logic.
FIBONACCI_ITEM_NAME = "Fibonacci level confirms"
VOLUME_PROFILE_ITEM_NAME = "Volume Profile confirms (fixed or anchored)"
LOCATION_ITEM_NAMES = {FIBONACCI_ITEM_NAME, VOLUME_PROFILE_ITEM_NAME}

# What market event would cause each DEVELOPING substate to re-evaluate --
# the "why not enter, and what changes that" half of the diagnostic.
NEXT_TRIGGER_BY_SUBSTATE = {
    WAIT_FIB: "Price pulls back into a Fibonacci retracement level that confirms this direction.",
    WAIT_VOLUME_PROFILE: (
        "Fixed or Anchored Volume Profile confirms this direction "
        "(price re-enters/holds the value area on that side)."
    ),
    WAIT_FIB_AND_VP: "Both a Fibonacci retracement confluence AND Volume Profile confirmation form in this direction.",
}


@dataclass
class EntryLocationState:
    state: str  # INVALID | DEVELOPING | CONFIRMED
    substate: Optional[str] = None  # WAIT_FIB | WAIT_VOLUME_PROFILE | WAIT_FIB_AND_VP -- only set when state == DEVELOPING
    reasons: list[str] = field(default_factory=list)


def classify_entry_location(
    confluence_result: "confluence_module.ConfluenceResult",
    regime: Optional[str],
    checklist_result: Optional["entry_checklist_module.ChecklistResult"] = None,
) -> EntryLocationState:
    if not confluence_result.should_execute:
        return EntryLocationState(
            state=INVALID,
            reasons=[f"No multi-timeframe direction established: {confluence_result.label}"],
        )
    if regime != "trending":
        return EntryLocationState(
            state=INVALID,
            reasons=[f"Entry-timeframe regime is '{regime}', not trending -- no edge to enter into."],
        )
    if checklist_result is None:
        return EntryLocationState(state=INVALID, reasons=["Entry checklist not yet evaluated."])
    if checklist_result.all_passed:
        return EntryLocationState(
            state=CONFIRMED, reasons=["Every entry-checklist item, including location, has confirmed."],
        )

    failed = [item.name for item in checklist_result.items if not item.advisory and not item.passed]
    failed_location = [name for name in failed if name in LOCATION_ITEM_NAMES]
    failed_other = [name for name in failed if name not in LOCATION_ITEM_NAMES]

    if failed_other:
        return EntryLocationState(
            state=INVALID,
            reasons=[f"Non-location checklist item(s) failed: {', '.join(failed_other)}."],
        )

    location_set = set(failed_location)
    if location_set == {FIBONACCI_ITEM_NAME}:
        substate = WAIT_FIB
    elif location_set == {VOLUME_PROFILE_ITEM_NAME}:
        substate = WAIT_VOLUME_PROFILE
    else:
        substate = WAIT_FIB_AND_VP

    return EntryLocationState(
        state=DEVELOPING,
        substate=substate,
        reasons=[
            "Direction confirmed (confluence + trending regime), entry location not yet confirmed: "
            f"{', '.join(failed_location)} pending."
        ],
    )


def format_entry_location(state: EntryLocationState) -> str:
    labels = {
        INVALID: "NO TRADE",
        DEVELOPING: "NO TRADE -- ENTRY LOCATION NOT CONFIRMED (WAIT)",
        CONFIRMED: "ENTRY LOCATION CONFIRMED",
    }
    lines = [f"ENTRY LOCATION: {labels.get(state.state, state.state)}"]
    if state.substate:
        lines.append(f"  WAIT CONDITION: {state.substate}")
        trigger = NEXT_TRIGGER_BY_SUBSTATE.get(state.substate)
        if trigger:
            lines.append(f"  NEXT TRIGGER: {trigger}")
    lines.extend(f"  {reason}" for reason in state.reasons)
    return "\n".join(lines)


def format_entry_assessment(
    direction, confluence_result, regime: str,
    atr_alignment: "mtf_context_module.AtrAlignment", vp_hierarchy: "mtf_context_module.VpHierarchy",
    checklist_result: "entry_checklist_module.ChecklistResult", entry_signal, bos_state_result, state: EntryLocationState,
) -> str:
    """The 'why not enter, and what would change that' diagnostic -- composes
    confluence.py / mtf_context.py / entry_checklist.py / bos_state.py /
    this module's own classification into one report. Shared by cli.py and
    cli_equity.py (both pass their own already-computed results in; this
    function reads, never recomputes or overrides any of them) so the
    report can't drift between the crypto and equity CLIs. Pure
    presentation -- never touches entry price / stop-loss / TP1-4 / R:R /
    position sizing, restated explicitly at the bottom of the report itself
    for exactly that reason.

    `bos_state_result` is a bos_state.BosState (import deferred by the
    caller to avoid a bos_state <-> entry_location import cycle risk)."""
    from . import bos_state as bos_state_module

    bar = "=" * 48
    lines = [bar, "ENTRY LOCATION ASSESSMENT".center(48), bar, ""]

    lines.append(f"Market Direction:        {'BULLISH' if direction == 'long' else 'BEARISH'}")
    lines.append(f"MTF Confluence:          {confluence_result.confidence_pct}% ({len(confluence_result.agreeing_timeframes)}/4)")
    lines.append(f"Trend Regime:            {regime.upper()}")
    lines.append(f"ATR Alignment:           {atr_alignment.expansion_count}/{atr_alignment.total_count} EXPANSION")
    lines.append("")

    lines.append("Volume Profile:")
    for entry in vp_hierarchy.entries:
        setup_label = mtf_context_module.VP_SETUP_LABELS.get(entry.setup_type, entry.setup_type)
        word = mtf_context_module.direction_word(entry.direction).upper()
        lines.append(f"  {entry.timeframe.upper()}: {entry.role:<28} {word} ({setup_label})")
    if vp_hierarchy.macro_conflict:
        lines.append(f"  NOTE: {vp_hierarchy.macro_conflict}")
    lines.append("")

    def _item_status(name: str) -> str:
        item = next((i for i in checklist_result.items if i.name == name), None)
        return "CONFIRMED" if item and item.passed else "NOT CONFIRMED"

    fvg_status = _item_status("Fair Value Gap confirms")
    lines.append(f"FVG:                     {fvg_status} ({entry_signal.labels.get('fair_value_gap', 'n/a')})")
    bos_text = bos_state_module.format_bos_state(bos_state_result).replace("BOS STATE: ", "")
    lines.append(f"BOS:                     {bos_text}")
    fib_status = _item_status(FIBONACCI_ITEM_NAME)
    fib_mark = "✅" if fib_status == "CONFIRMED" else "❌"
    lines.append(f"Fibonacci:               {fib_mark} {fib_status}")
    vp_checklist_status = _item_status(VOLUME_PROFILE_ITEM_NAME)
    vp_mark = "✅" if vp_checklist_status == "CONFIRMED" else "❌"
    lines.append(f"Volume Profile (entry):  {vp_mark} {vp_checklist_status}")
    lines.append("")

    lines.append(f"ENTRY LOCATION:          {state.state}")
    if state.substate:
        lines.append("")
        lines.append("WAIT CONDITION:")
        lines.append(f"  -> {state.substate}")
        trigger = NEXT_TRIGGER_BY_SUBSTATE.get(state.substate)
        if trigger:
            lines.append(f"  -> {trigger}")
    lines.append("")

    trade_status = "NO TRADE -- WAIT" if state.state != CONFIRMED else "PROCEEDING"
    lines.append("TRADE STATUS:")
    lines.append(f"  -> {trade_status}")
    lines.append("")
    lines.append("IMPORTANT:")
    lines.append("  Entry / SL / TP / R:R / position sizing unchanged")
    lines.append(bar)
    return "\n".join(lines)
