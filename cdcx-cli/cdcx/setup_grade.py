"""
setup_grade.py
----------------
"A+ setup" grading, composing results already produced elsewhere into one
labeled tier -- the sequential MTF framework's own definition of its best
trade:

    1W bias confirmed             -> structure_strategy.weekly_bias() != "neutral",
                                      matching the setup's own direction
    1D at a Fib/VP location       -> structure_strategy's structural trigger
                                      already required this to fire at all
    4H ATR contraction/flat,      -> atr_state.AtrTransition.is_trigger:
      then transitioning toward       True only for a compression -> expansion
      expansion                       read (contraction_to_expansion,
                                       compression_release, second_expansion)
    Fib + POC/HVN/LVN + FVG       -> the structural trigger itself
      confluence                      (breakout_retest / fvg_confluence /
                                       breakdown_retest)
    1H reversal/continuation      -> structure_strategy's 1H candlestick
      candle confirmed                 confirmation, already required
    Breakout/retest confirmation  -> StructureSetup.valid

Every one of those is already enforced by structure_strategy.evaluate_
structure_setup() plus atr_state.analyze() -- so "A" is simply a valid
StructureSetup, and "A+" is that same valid setup PLUS a confirmed ATR
timing trigger (the one piece structure_strategy deliberately treats as
non-blocking context, per its own docstring). Optional confluence.py /
confidence_scoring.py results tighten the grade further when supplied, but
neither is required -- callers that only have a StructureSetup + AtrTransition
(e.g. structure_strategy's own CLI path) still get a useful A/No-Trade read.

This module is advisory-only, same convention as atr_state.py and
entry_checklist.py's `advisory=True` items: it labels setup quality for the
printed report, it is never consulted by no_trade_gate.py and never blocks
or authorizes a live order. Wiring it into the live gate would be a
deliberate, separate decision -- not made here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .indicators.atr_state import AtrTransition

Grade = str  # "A+" | "A" | "No Trade"

STRONG_CONFLUENCE_TIERS = {"strong", "normal"}
STRONG_CONFIDENCE_TIERS = {"Very Strong", "Strong"}


@dataclass
class SetupGrade:
    grade: Grade
    direction: Optional[str]  # "long" | "short" | None
    reasons: list[str] = field(default_factory=list)


def grade_setup(
    structure_result,        # structure_strategy.StructureSetup
    atr_transition: AtrTransition,
    confluence_result=None,   # confluence.ConfluenceResult, optional
    confidence_result=None,   # confidence_scoring.WeightedConfidenceResult, optional
) -> SetupGrade:
    if not structure_result.valid:
        return SetupGrade(
            grade="No Trade",
            direction=None,
            reasons=["No qualifying structural setup (1W/1D/4H/1H) -- A+ grading not applicable."],
        )

    direction = structure_result.direction
    reasons = [
        f"Structural setup valid: {direction.upper()} via {structure_result.trigger} "
        f"(1W bias + 1D location + 4H setup + 1H confirmation all satisfied).",
    ]

    if atr_transition.is_trigger:
        reasons.append(
            f"4H ATR timing CONFIRMS ({atr_transition.kind}): {atr_transition.detail}"
        )
        atr_ok = True
    else:
        reasons.append(
            f"4H ATR timing does not yet confirm ({atr_transition.kind}) -- "
            f"structurally valid, but not the higher-quality timed entry."
        )
        atr_ok = False

    confluence_ok = True
    if confluence_result is not None:
        matches_direction = (
            confluence_result.direction == direction
            and confluence_result.should_execute
            and confluence_result.tier in STRONG_CONFLUENCE_TIERS
        )
        confluence_ok = matches_direction
        reasons.append(
            f"Multi-timeframe confluence: {confluence_result.label} -- "
            f"{'confirms' if matches_direction else 'does not confirm'} the {direction.upper()} direction "
            f"at A+ strength."
        )

    confidence_ok = True
    if confidence_result is not None:
        confidence_ok = confidence_result.tier in STRONG_CONFIDENCE_TIERS
        reasons.append(
            f"Weighted confidence score: {confidence_result.score}/100 ({confidence_result.tier})."
        )

    if atr_ok and confluence_ok and confidence_ok:
        grade: Grade = "A+"
        reasons.append("GRADE: A+ -- location, state, confluence, trigger, and timing all align.")
    else:
        grade = "A"
        reasons.append(
            "GRADE: A -- structurally valid setup, but missing the confirmed ATR timing trigger "
            "and/or full confluence/confidence strength that would make it A+."
        )

    return SetupGrade(grade=grade, direction=direction, reasons=reasons)


def format_setup_grade(result: SetupGrade) -> str:
    lines = ["-" * 49, "SETUP GRADE (advisory)".center(49), "-" * 49]
    lines.extend(result.reasons)
    lines.append("-" * 49)
    if result.direction:
        lines.append(f"{result.grade} {result.direction.upper()}")
    else:
        lines.append(result.grade)
    lines.append("-" * 49)
    return "\n".join(lines)


if __name__ == "__main__":
    from .indicators import atr_state
    from . import structure_strategy

    valid_setup = structure_strategy.StructureSetup(
        direction="long", valid=True, trigger="breakout_retest",
        reasons=["demo"], entry=100.0, stop_level=95.0,
    )
    trigger_transition = atr_state.detect_transition(["contraction", "contraction", "expansion"])
    print(format_setup_grade(grade_setup(valid_setup, trigger_transition)))
    print()

    no_trigger_transition = atr_state.detect_transition(["flat", "flat", "flat"])
    print(format_setup_grade(grade_setup(valid_setup, no_trigger_transition)))
    print()

    no_setup = structure_strategy.StructureSetup(direction=None, valid=False, trigger="", reasons=["demo"])
    print(format_setup_grade(grade_setup(no_setup, no_trigger_transition)))
