"""
entry_checklist.py
--------------------
Component-level confirmation gate for trade execution. Multi-timeframe
confluence (confluence.py) decides *whether the overall bias qualifies*;
this module separately verifies that the specific indicator groups called
out in the execution checklist each individually confirm that same
direction on the entry timeframe -- not just that the blended AI score
happens to be positive/negative overall (a high FVG or Volume Profile score
could otherwise paper over a Fibonacci level that's actually against the
trade).

Checklist (mirrors the specified execution rules):
    - ATR/EMA trend (atr_ema_variant1) confirms direction
    - Fibonacci retracement confirms direction (an actual bounce/rejection,
      not just "no contradiction")
    - Fair Value Gap confirms direction
    - Volume Profile confirms direction (fixed OR anchored -- either counts)
    - Risk per trade <= 2% of account equity
    - No existing open position on the same symbol

Optional, advisory:
    - ATR transition timing (atr_state.py) -- reads whether ATR just moved
      from contraction to expansion, or is in a confirmed "second expansion"
      after a pullback (the higher-quality trigger vs. chasing the first
      move). Only evaluated when the caller passes `atr_series`; when
      omitted this item is skipped entirely, so existing callers/tests are
      unaffected. Advisory items never gate `all_passed` -- they inform,
      they don't block a setup that already confirms on every required
      component.

Position sizing itself (1.5x ATR stop distance) is handled by risk.py; this
module only gates whether to proceed, given a TradeSignal for the entry
timeframe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from . import trade_manager

MAX_RISK_PCT = 2.0


@dataclass
class ChecklistItem:
    name: str
    passed: bool
    detail: str
    advisory: bool = False  # informational only -- excluded from all_passed


@dataclass
class ChecklistResult:
    items: list[ChecklistItem] = field(default_factory=list)
    all_passed: bool = False

    def add(self, name: str, passed: bool, detail: str, advisory: bool = False) -> None:
        self.items.append(ChecklistItem(name, passed, detail, advisory))


def _confirms(score: float, direction: str) -> bool:
    """A component 'confirms' only with an actual signed reading in the
    trade's direction -- a neutral/zero score does NOT count as confirming."""
    if direction == "long":
        return score > 0
    return score < 0


def evaluate_entry_checklist(
    signal, direction: str, risk_pct: float = MAX_RISK_PCT, symbol: Optional[str] = None,
    atr_series: Optional[Sequence[float]] = None,
) -> ChecklistResult:
    """
    `signal` is the TradeSignal for the entry timeframe (see engine.py).
    `direction` is "long" or "short" (from confluence.ConfluenceResult).
    `atr_series` is optional: the entry timeframe's raw ATR series. When
    provided, adds the advisory ATR-transition timing item (see module
    docstring); omit it to keep the checklist exactly as before.
    """
    result = ChecklistResult()
    scores = signal.scores

    ema_ok = _confirms(scores.get("ema_trend", 0), direction)
    result.add(
        "ATR/EMA trend confirms",
        ema_ok,
        f"ema_trend score = {scores.get('ema_trend', 0):+g} ({signal.labels.get('ema_trend', 'n/a')})",
    )

    fib_ok = _confirms(scores.get("fib_retracement", 0), direction)
    result.add(
        "Fibonacci level confirms",
        fib_ok,
        f"fib_retracement score = {scores.get('fib_retracement', 0):+g} ({signal.labels.get('fib_retracement', 'n/a')})",
    )

    fvg_ok = _confirms(scores.get("fair_value_gap", 0), direction)
    result.add(
        "Fair Value Gap confirms",
        fvg_ok,
        f"fair_value_gap score = {scores.get('fair_value_gap', 0):+g} ({signal.labels.get('fair_value_gap', 'n/a')})",
    )

    fixed_vp_ok = _confirms(scores.get("fixed_volume_profile", 0), direction)
    anchored_vp_ok = _confirms(scores.get("anchored_volume_profile", 0), direction)
    vp_ok = fixed_vp_ok or anchored_vp_ok
    result.add(
        "Volume Profile confirms (fixed or anchored)",
        vp_ok,
        f"fixed = {scores.get('fixed_volume_profile', 0):+g}, "
        f"anchored = {scores.get('anchored_volume_profile', 0):+g}",
    )

    risk_ok = risk_pct <= MAX_RISK_PCT
    result.add("Account risk <= 2%", risk_ok, f"risk_pct = {risk_pct}%")

    if symbol is not None:
        existing = trade_manager.get_open_trade(symbol)
        no_existing_ok = existing is None
        detail = "no open position" if no_existing_ok else f"open trade {existing.id[:8]} already exists"
        result.add("No existing position in this symbol", no_existing_ok, detail)

    if atr_series is not None:
        from .indicators import atr_state

        states = atr_state.classify_atr_series(atr_series)
        transition = atr_state.detect_transition(states)
        result.add(
            "ATR transition timing (advisory)",
            transition.is_trigger,
            transition.detail,
            advisory=True,
        )

    result.all_passed = all(item.passed for item in result.items if not item.advisory)
    return result


def format_checklist(result: ChecklistResult) -> str:
    lines = ["-" * 49, "ENTRY CHECKLIST".center(49), "-" * 49]
    for item in result.items:
        if item.advisory:
            mark = "INFO" if item.passed else "NOTE"
        else:
            mark = "PASS" if item.passed else "FAIL"
        lines.append(f"[{mark}] {item.name} -- {item.detail}")
    lines.append("-" * 49)
    lines.append("ALL CONDITIONS MET -- proceeding" if result.all_passed else "NOT ALL CONDITIONS MET -- no trade")
    lines.append("-" * 49)
    return "\n".join(lines)
