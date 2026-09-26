"""
fvp_analysis.py
-----------------
Phase 1 orchestrator + printable report for the FVP (Fixed/Anchored Volume
Profile) intelligence layer.

SCOPE STATEMENT (read this before touching cli.py or cli_equity.py):
    Everything in cdcx/volume_profile/ is INFORMATION ONLY, same status as
    mtf_context.py's "Mode A" summaries. build_fvp_shadow_report()'s output
    is never passed to entry_checklist.py, confluence.py, regime.py, or any
    entry/SL/TP/R:R/position-sizing calculation, and calling it must never
    change what a run decides or executes. FVPShadowReport.execution_impact
    is hardcoded to "INFORMATION_ONLY" for exactly this reason -- if a
    future phase ever lets FVP evidence influence the gate, that's a
    separate, explicitly-flagged change, not a silent drift of this one.

    Phase 1 covers: zone detection (reusing existing Fixed/Anchored VP
    math verbatim), tested/untested/first-test state, and lifecycle
    classification, on the SAME entry-timeframe OHLCV cli.py already
    fetches for the real decision -- no extra API calls. Setup
    classification (Accumulation/Trend/Rejection), zone origin, and
    multi-timeframe roll-up are Phase 2+, not implemented here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .zone_detector import detect_fixed_zone, detect_anchored_zone
from .zone_lifecycle import classify_lifecycle
from .zone_state import VolumeZone

EXECUTION_IMPACT = "INFORMATION_ONLY"


@dataclass
class FVPShadowReport:
    timeframe: str
    price: float
    zones: list[VolumeZone] = field(default_factory=list)
    execution_impact: str = EXECUTION_IMPACT


def build_fvp_shadow_report(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], volumes: Sequence[float],
    price: float, timeframe: str,
) -> FVPShadowReport:
    """Phase 1: one fixed-range zone + one anchored zone for the given
    timeframe's own OHLCV. Never raises past a bad indicator read -- a
    zone that fails to compute is simply omitted, since this whole layer
    must never be able to interrupt the real decision flow around it."""
    zones: list[VolumeZone] = []

    try:
        zones.append(detect_fixed_zone(highs, lows, volumes, price, timeframe))
    except Exception:
        pass

    try:
        zones.append(detect_anchored_zone(highs, lows, closes, volumes, price, timeframe))
    except Exception:
        pass

    return FVPShadowReport(timeframe=timeframe, price=price, zones=zones)


def format_fvp_shadow(report: FVPShadowReport) -> str:
    lines = [
        "-" * 60,
        f"FVP SHADOW ANALYSIS (RESEARCH ONLY -- {report.execution_impact})".center(60),
        "-" * 60,
    ]
    if not report.zones:
        lines.append("No zone could be computed for this timeframe.")
        lines.append("-" * 60)
        return "\n".join(lines)

    for zone in report.zones:
        state = classify_lifecycle(zone, report.price)
        kind = "Fixed VP" if zone.zone_type == "fixed_value_area" else "Anchored VP"
        lines.append(f"[{report.timeframe}] {kind} zone: {zone.lower_price:.6f} - {zone.upper_price:.6f}  "
                     f"(POC {zone.poc_price:.6f})")
        lines.append(f"  Status: {state}   Tested: {'yes' if zone.tested else 'no'}"
                     f"   Test count: {zone.test_count}   First test: {'yes' if zone.first_test else 'no'}")
    lines.append("This layer does NOT modify entry, stop loss, take profit, R:R, or risk sizing.")
    lines.append("-" * 60)
    return "\n".join(lines)
