"""
circuit_breaker.py
-------------------
Portfolio-level protective throttle -- distinct from trade_manager.py's
PER-TRADE rules (breakeven at TP1, give-back exit, planned-vs-realized loss
warning). Nothing here manages an open position; like entry_checklist.py
and no_trade_filter.py, it only gates whether a NEW trade is allowed to
open.

Two independent triggers, either one blocks new entries:

    A. Consecutive-loss pause: after `max_consecutive_losses` losing trades
       in a row (for one symbol), no new entry until a winning trade
       resets the streak.
    B. Drawdown throttle: once realized equity has drawn down more than
       `max_drawdown_pct` from its running peak, no new entries until
       equity recovers back above that peak minus `max_drawdown_pct`.

Motivated by a real, empirically observed pattern: backtesting XRP/USD
after the regime gate fix (see backtest/engine.py) still showed a run of 4
consecutive losing trades driving most of that run's 20.89% max drawdown --
this throttle is aimed directly at that failure mode, not a generic
risk-management checkbox.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from . import trade_manager

DEFAULT_MAX_CONSECUTIVE_LOSSES = 3
DEFAULT_MAX_DRAWDOWN_PCT = 10.0


@dataclass
class CircuitBreakerResult:
    tripped: bool
    reason: str
    consecutive_losses: int
    current_drawdown_pct: float
    peak_equity: float
    current_equity: float


def check_circuit_breaker(
    realized_pnls: Sequence[float],
    peak_equity: float,
    current_equity: float,
    max_consecutive_losses: int = DEFAULT_MAX_CONSECUTIVE_LOSSES,
    max_drawdown_pct: float = DEFAULT_MAX_DRAWDOWN_PCT,
) -> CircuitBreakerResult:
    """
    Pure function -- no I/O, works equally for live/paper (fed from
    trade_manager's closed trades) and the offline backtester (fed from its
    own running equity curve). `realized_pnls` is chronological, oldest
    first. A loss is `pnl <= 0` (a breakeven close counts as a loss for
    streak purposes -- it didn't advance the account either).
    """
    consecutive = 0
    for pnl in reversed(realized_pnls):
        if pnl <= 0:
            consecutive += 1
        else:
            break

    drawdown_pct = (
        (peak_equity - current_equity) / peak_equity * 100 if peak_equity > 0 else 0.0
    )

    if consecutive >= max_consecutive_losses:
        return CircuitBreakerResult(
            tripped=True,
            reason=f"{consecutive} consecutive losses (limit {max_consecutive_losses}) -- pausing until a win resets the streak.",
            consecutive_losses=consecutive, current_drawdown_pct=round(drawdown_pct, 2),
            peak_equity=peak_equity, current_equity=current_equity,
        )

    if drawdown_pct >= max_drawdown_pct:
        return CircuitBreakerResult(
            tripped=True,
            reason=f"Drawdown {drawdown_pct:.2f}% from peak equity {peak_equity:,.2f} exceeds the {max_drawdown_pct:.2f}% limit.",
            consecutive_losses=consecutive, current_drawdown_pct=round(drawdown_pct, 2),
            peak_equity=peak_equity, current_equity=current_equity,
        )

    return CircuitBreakerResult(
        tripped=False, reason="", consecutive_losses=consecutive,
        current_drawdown_pct=round(drawdown_pct, 2), peak_equity=peak_equity, current_equity=current_equity,
    )


def check_circuit_breaker_for_symbol(
    symbol: str,
    max_consecutive_losses: int = DEFAULT_MAX_CONSECUTIVE_LOSSES,
    max_drawdown_pct: float = DEFAULT_MAX_DRAWDOWN_PCT,
) -> CircuitBreakerResult:
    """
    Live/paper convenience wrapper: reads trade_manager's persisted closed
    trades for `symbol`, builds a running equity curve from each trade's
    `account_balance` (balance the trade was sized against) + its
    `realized_pnl`, and delegates to check_circuit_breaker().

    Note: this project doesn't track a single persistent "current account
    equity" across CLI invocations (each run takes --balance fresh) -- this
    reconstructs equity from each trade's own recorded account_balance,
    which is only as accurate as --balance being passed consistently run to
    run. Good enough to catch a losing streak within one continuous session;
    treat the drawdown-from-peak number as approximate across sessions with
    a changing --balance.
    """
    trades = [
        t for t in trade_manager.load_trades()
        if t.symbol == symbol and t.status == "closed" and t.realized_pnl is not None
    ]
    trades.sort(key=lambda t: t.closed_at or 0)

    if not trades:
        return CircuitBreakerResult(
            tripped=False, reason="", consecutive_losses=0, current_drawdown_pct=0.0,
            peak_equity=0.0, current_equity=0.0,
        )

    equity_curve = [t.account_balance + t.realized_pnl for t in trades]
    pnls = [t.realized_pnl for t in trades]
    peak_equity = max(equity_curve)
    current_equity = equity_curve[-1]

    return check_circuit_breaker(pnls, peak_equity, current_equity, max_consecutive_losses, max_drawdown_pct)


def format_circuit_breaker(result: CircuitBreakerResult) -> str:
    lines = [
        "-" * 49,
        "CIRCUIT BREAKER".center(49),
        "-" * 49,
        f"Consecutive losses: {result.consecutive_losses}",
        f"Drawdown from peak: {result.current_drawdown_pct:.2f}%  "
        f"(peak {result.peak_equity:,.2f} -> current {result.current_equity:,.2f})",
        f"Status: {'TRIPPED -- new entries blocked' if result.tripped else 'clear'}",
    ]
    if result.tripped:
        lines.append(f"Reason: {result.reason}")
    lines.append("-" * 49)
    return "\n".join(lines)
