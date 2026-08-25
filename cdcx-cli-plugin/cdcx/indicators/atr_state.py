"""
atr_state.py
-------------
ATR read as a volatility-state *sequence*, not just a single-bar snapshot.

atr_ema_variant1.score_atr_expansion() classifies only the latest bar's ATR
against its own trailing average -- a snapshot, used for scoring. This
module classifies every bar in the series the same way, so the *sequence*
of states can be read like a volatility gear-shift:

    Contraction -> Expansion
        The breakout trigger. Compression resolving into a fresh move.
        On its own this is still "prepare," not "chase" -- see
        `expansion_continuation` below.

    Expansion -> (Flat | Contraction) -> Expansion   ("second expansion")
        A move happened, cooled off (pullback/consolidation), and volatility
        is now picking back up. This is the higher-quality entry: the first
        expansion may already be exhausted by the time it's actionable, but
        a *second* expansion after a genuine cooldown means the move is
        being confirmed rather than chased.

    Expansion, with no prior cooldown found
        Still just the initial/ongoing expansion -- flagged separately
        (`expansion_continuation`) so callers can treat it with more
        caution than a confirmed second expansion, without being told
        outright not to trade it.

Deliberately duplicates score_atr_expansion's +-10% expansion/contraction
thresholds rather than importing them, so this module can classify an
entire series in one pass without changing that function's existing
single-bar contract (still used, unmodified, by confidence scoring and
regime classification).

This module is advisory: it reports what the ATR sequence is doing, it
does not itself decide whether a trade is valid. Callers (entry_checklist.py,
structure_strategy.py) treat its output as an additional, non-blocking
confirmation -- consistent with "don't chase maximum ATR expansion" being
a timing preference, not a hard veto over setups that already qualify on
their own merits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Sequence

AtrState = Literal["expansion", "contraction", "flat"]

EXPANSION_THRESHOLD_PCT = 0.10
CONTRACTION_THRESHOLD_PCT = -0.10

DEFAULT_LOOKBACK = 10

TRIGGER_KINDS = {"contraction_to_expansion", "second_expansion"}


@dataclass
class AtrTransition:
    kind: str  # "contraction_to_expansion" | "second_expansion" | "expansion_continuation" |
               # "contraction" | "flat" | "none"
    detail: str
    bars_since_prior_expansion: Optional[int] = None

    @property
    def is_trigger(self) -> bool:
        """True for the two sequences the strategy treats as an entry-timing
        trigger: a fresh break out of compression, or a confirmed second
        expansion following a cooldown."""
        return self.kind in TRIGGER_KINDS


def classify_atr_series(
    atr_series: Sequence[float], lookback: int = DEFAULT_LOOKBACK,
) -> list[Optional[AtrState]]:
    """Per-bar ATR state, each bar compared against the rolling average of
    the `lookback` bars immediately before it -- same window and thresholds
    as atr_ema_variant1.score_atr_expansion(), just applied at every index
    instead of only the last one. Bars without enough history behind them
    return None."""
    states: list[Optional[AtrState]] = []
    for i in range(len(atr_series)):
        if i < lookback:
            states.append(None)
            continue
        recent_avg = sum(atr_series[i - lookback:i]) / lookback
        if recent_avg == 0:
            states.append(None)
            continue
        change_pct = (atr_series[i] - recent_avg) / recent_avg
        if change_pct > EXPANSION_THRESHOLD_PCT:
            states.append("expansion")
        elif change_pct < CONTRACTION_THRESHOLD_PCT:
            states.append("contraction")
        else:
            states.append("flat")
    return states


def detect_transition(states: Sequence[Optional[AtrState]]) -> AtrTransition:
    """Reads the tail of a state sequence for the two transitions treated as
    entry-timing triggers, falling back to a plain current-state read
    (or "none") when neither applies."""
    clean = [s for s in states if s is not None]
    if len(clean) < 2:
        return AtrTransition(kind="none", detail="Not enough ATR history to read a transition.")

    current, previous = clean[-1], clean[-2]

    if previous == "contraction" and current == "expansion":
        return AtrTransition(
            kind="contraction_to_expansion",
            detail="ATR just turned from contraction to expansion -- breakout trigger "
                   "(Mode 1: prepare -> confirmed).",
        )

    if current == "expansion":
        # Walk back past the current expansion run, then past any
        # flat/contraction cooldown behind it, to see whether an earlier
        # expansion preceded that cooldown -- the "second expansion" pattern.
        i = len(clean) - 1
        while i >= 0 and clean[i] == "expansion":
            i -= 1
        cooldown_end = i
        while i >= 0 and clean[i] in ("flat", "contraction"):
            i -= 1
        cooldown_start = i

        if cooldown_start >= 0 and cooldown_end > cooldown_start and clean[cooldown_start] == "expansion":
            bars = cooldown_end - cooldown_start
            return AtrTransition(
                kind="second_expansion",
                detail=f"ATR expanded, cooled for {bars} bar(s), and is expanding again -- "
                       f"second-expansion entry (the higher-quality trigger; not chasing the first move).",
                bars_since_prior_expansion=bars,
            )

        return AtrTransition(
            kind="expansion_continuation",
            detail="ATR is expanding, but this reads as the first/ongoing expansion rather than "
                   "a post-pullback second expansion -- be wary of chasing it here.",
        )

    if current == "contraction":
        return AtrTransition(
            kind="contraction",
            detail="ATR is contracting -- compression (Mode 1: prepare/wait, direction not yet known).",
        )

    return AtrTransition(
        kind="flat",
        detail="ATR is flat -- rotation environment (Mode 2), not a breakout trigger.",
    )


def analyze(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
    lookback: int = DEFAULT_LOOKBACK,
) -> AtrTransition:
    """Convenience wrapper: computes ATR from raw OHLC using the existing
    ATR calculation, then classifies the full series and reads the tail
    transition, for real usage against live/fetched data."""
    from . import atr_ema_variant1

    atr_series = atr_ema_variant1.calculate_atr(highs, lows, closes)
    states = classify_atr_series(atr_series, lookback=lookback)
    return detect_transition(states)


def format_atr_transition(transition: AtrTransition, label: str = "ATR TIMING") -> str:
    tag = "TRIGGER" if transition.is_trigger else transition.kind.upper()
    return f"{label} [{tag}]: {transition.detail}"


if __name__ == "__main__":
    # Contraction -> Expansion (breakout trigger)
    demo_states: list[Optional[AtrState]] = ["contraction"] * 5 + ["expansion"]
    print(format_atr_transition(detect_transition(demo_states)))

    # Expansion -> cooldown -> Expansion (second expansion)
    demo_states2: list[Optional[AtrState]] = ["expansion"] * 3 + ["flat"] * 2 + ["expansion"]
    print(format_atr_transition(detect_transition(demo_states2)))

    # Ongoing first expansion, no prior cooldown
    demo_states3: list[Optional[AtrState]] = ["flat"] * 5 + ["expansion"]
    print(format_atr_transition(detect_transition(demo_states3)))

    # Flat (rotation)
    demo_states4: list[Optional[AtrState]] = ["flat"] * 5
    print(format_atr_transition(detect_transition(demo_states4)))
