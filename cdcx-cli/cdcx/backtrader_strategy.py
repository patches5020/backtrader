"""
backtrader_strategy.py
-----------------------
Bridges the CDCX AI signal engine into a native `backtrader.Strategy`, so
the same indicator/scoring/risk pipeline used for live analysis
(`engine.analyze_ohlcv`) and the standalone offline backtester
(`cdcx.backtest.engine`) can also be driven through backtrader's own
Cerebro engine, data feeds, brokers, and analyzers -- this repository's
native backtesting stack.

This is deliberately a *bridge*, not a reimplementation of
`cdcx.backtest.engine`'s paper trade-manager. The two share the same
signal generation (`engine.analyze_ohlcv`), entry gating
(`entry_checklist.evaluate_entry_checklist`), and position sizing
(`risk.build_position_plan`), but exits differ:

  - `cdcx.backtest.engine` simulates its own trailing / break-even /
    give-back exits via `trade_manager.py`, plus a custom fee + slippage +
    square-root market-impact cost model, against a persisted JSON trade
    state file.
  - This bridge instead places a backtrader-native bracket order (market
    entry + ATR stop-loss + TP1 limit) and lets backtrader's own broker,
    commission scheme, and order management handle fills and exits. There
    is no TP2-TP4 laddering or trailing-stop follow-through here -- once
    the stop or TP1 leg fills, the position is flat again.

Use this when you want CDCX signals inside a normal backtrader `Cerebro`
run (alongside other strategies, analyzers, or live broker integrations);
use `cdcx.backtest.engine` when you want the full paper trade-manager
simulation (trailing stops, give-back, market-impact costs) this project
was originally built around.
"""

from __future__ import annotations

import tempfile
from typing import Optional

import backtrader as bt

from . import risk
from .config import settings
from .engine import TradeSignal, analyze_ohlcv
from .entry_checklist import evaluate_entry_checklist
from .exchange.cryptocom import OHLCV


def _execution_direction(signal: TradeSignal) -> Optional[str]:
    """
    Long/short/None from the *execution* signal (which overrides to "NO
    TRADE" when the regime is transitional or R:R doesn't clear 2:1) rather
    than the raw indicator `signal`, mirroring `cdcx.backtest.engine`.
    """
    label = (signal.execution_signal or signal.signal or "").upper()
    if label in ("STRONG BUY", "BUY"):
        return "long"
    if label in ("STRONG SELL", "SELL"):
        return "short"
    return None


class CDCXSignalStrategy(bt.Strategy):
    """
    Runs the full CDCX AI scoring pipeline (`engine.analyze_ohlcv`) bar by
    bar against whatever data feed backtrader is fed, gates entries with
    the same entry-checklist + risk-sizing modules used for live trading,
    and executes via a backtrader stop/limit bracket order.

    Only one open position at a time -- mirrors `cdcx.backtest.engine`'s
    "ride the first entry" rule (`trade_manager.py` enforces the same rule
    for live/paper trading).
    """

    params = (
        ("symbol", None),               # defaults to settings.default_symbol
        ("warmup", 120),                # bars required before the first signal
        ("risk_pct", None),             # defaults to settings.risk_pct_per_trade
        ("min_score_long", 60.0),
        ("min_score_short", 40.0),
        ("require_checklist", True),
        ("trade_state_path", None),     # isolate the paper trade-state file; None => a fresh tempfile
        ("printlog", True),
    )

    def __init__(self):
        self.symbol = self.p.symbol or settings.default_symbol
        self.risk_pct = (
            self.p.risk_pct if self.p.risk_pct is not None else settings.risk_pct_per_trade
        )
        self.last_signal: Optional[TradeSignal] = None
        self._bracket_orders: list = []

        # entry_checklist.evaluate_entry_checklist consults trade_manager's
        # persisted JSON state (to refuse a symbol that already has an open
        # tracked trade). Point it at an isolated file so a backtrader run
        # never collides with, or is gated by, a real/live trade_manager
        # state file on disk.
        self._state_path = self.p.trade_state_path or tempfile.mktemp(suffix="_bt_cdcx_trades.json")
        settings.trade_state_path = self._state_path

    def log(self, message: str) -> None:
        if self.p.printlog:
            dt = self.data.datetime.date(0)
            print(f"{dt.isoformat()} {message}")

    def _window(self) -> OHLCV:
        """Build a cdcx OHLCV window from the last `warmup` backtrader bars."""
        lookback = min(len(self), self.p.warmup)
        agos = range(lookback - 1, -1, -1)  # oldest -> newest
        return OHLCV(
            timestamps=[int(self.data.datetime.datetime(-ago).timestamp()) for ago in agos],
            opens=[float(self.data.open[-ago]) for ago in agos],
            highs=[float(self.data.high[-ago]) for ago in agos],
            lows=[float(self.data.low[-ago]) for ago in agos],
            closes=[float(self.data.close[-ago]) for ago in agos],
            volumes=[float(self.data.volume[-ago]) for ago in agos],
        )

    def _bracket_pending(self) -> bool:
        return any(o.alive() for o in self._bracket_orders)

    def next(self):
        if self.position or self._bracket_pending():
            return
        if len(self) < self.p.warmup:
            return

        try:
            signal = analyze_ohlcv(self.symbol, self._window())
        except Exception as exc:  # insufficient/degenerate data for some indicator on this window
            self.log(f"analyze_ohlcv skipped: {exc}")
            return
        self.last_signal = signal

        direction = _execution_direction(signal)
        if direction is None:
            return

        # soft score filter (high score = bullish, low score = bearish)
        if direction == "long" and signal.total_score < self.p.min_score_long:
            return
        if direction == "short" and signal.total_score > self.p.min_score_short:
            return

        if self.p.require_checklist:
            checklist = evaluate_entry_checklist(
                signal, direction, risk_pct=self.risk_pct, symbol=self.symbol
            )
            if not checklist.all_passed:
                return

        # Reject stale targets: TP1 must still be ahead of entry with meaningful room
        tp1 = signal.take_profits.get("TP1")
        if tp1 is None:
            return
        if direction == "long" and tp1 <= signal.entry * 1.001:
            return
        if direction == "short" and tp1 >= signal.entry * 0.999:
            return
        if abs(tp1 - signal.entry) < max(0.4 * signal.atr, signal.entry * 0.002):
            return

        plan = risk.build_position_plan(
            symbol=self.symbol,
            direction=direction,
            entry_price=signal.entry,
            atr=signal.atr,
            account_balance=self.broker.getvalue(),
            risk_pct=self.risk_pct,
        )
        if plan.position_size <= 0 or plan.stop_distance <= 0:
            return
        if direction == "long" and plan.stop_price >= plan.entry_price:
            return
        if direction == "short" and plan.stop_price <= plan.entry_price:
            return

        self.log(
            f"{direction.upper()} setup: score={signal.total_score:.1f} "
            f"entry~={plan.entry_price:.4f} stop={plan.stop_price:.4f} "
            f"tp1={tp1:.4f} size={plan.position_size:.6f}"
        )

        bracket = self.buy_bracket if direction == "long" else self.sell_bracket
        self._bracket_orders = bracket(
            size=plan.position_size,
            exectype=bt.Order.Market,
            stopprice=plan.stop_price,
            limitprice=tp1,
        )

    def notify_order(self, order):
        if order.status == order.Completed:
            side = "BUY" if order.isbuy() else "SELL"
            self.log(f"{side} EXECUTED price={order.executed.price:.4f} size={order.executed.size}")
        if not order.alive():
            self._bracket_orders = [o for o in self._bracket_orders if o.alive()]
