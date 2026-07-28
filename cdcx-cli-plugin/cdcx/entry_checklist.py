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

Position sizing itself (1.5x ATR stop distance) is handled by risk.py; this
module only gates whether to proceed, given a TradeSignal for the entry
timeframe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import trade_manager

MAX_RISK_PCT = 2.0


@dataclass
class ChecklistItem:
    name: str
    passed: bool
    detail: str


@dataclass
class ChecklistResult:
    items: list[ChecklistItem] = field(default_factory=list)
    all_passed: bool = False

    def add(self, name: str, passed: bool, detail: str) -> None:
        self.items.append(ChecklistItem(name, passed, detail))


def _confirms(score: float, direction: str) -> bool:
    """A component 'confirms' only with an actual signed reading in the
    trade's direction -- a neutral/zero score does NOT count as confirming."""
    if direction == "long":
        return score > 0
    return score < 0


def evaluate_entry_checklist(
    signal, direction: str, risk_pct: float = MAX_RISK_PCT, symbol: Optional[str] = None,
) -> ChecklistResult:
    """
    `signal` is the TradeSignal for the entry timeframe (see engine.py).
    `direction` is "long" or "short" (from confluence.ConfluenceResult).
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

    result.all_passed = all(item.passed for item in result.items)
    return result


def format_checklist(result: ChecklistResult) -> str:
    lines = ["-" * 49, "ENTRY CHECKLIST".center(49), "-" * 49]
    for item in result.items:
        mark = "PASS" if item.passed else "FAIL"
        lines.append(f"[{mark}] {item.name} -- {item.detail}")
    lines.append("-" * 49)
    lines.append("ALL CONDITIONS MET -- proceeding" if result.all_passed else "NOT ALL CONDITIONS MET -- no trade")
    lines.append("-" * 49)
    return "\n".join(lines)
