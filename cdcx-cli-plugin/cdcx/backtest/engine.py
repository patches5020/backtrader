"""
backtest/engine.py
------------------
Offline backtester for the CDCX AI scoring engine.

Walks synthetic (or any pre-loaded) OHLCV bar-by-bar, runs the exact same
indicator + scoring path as live analysis, applies entry filters, sizes
positions with the real risk module, and simulates the paper trade-manager
trailing / give-back / stop rules.

No network, no live orders. Results are purely for research.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from typing import Optional

from cdcx.config import settings
from cdcx.engine import analyze_ohlcv, TradeSignal
from cdcx.exchange.cryptocom import OHLCV
from cdcx import risk, trade_manager
from cdcx.entry_checklist import evaluate_entry_checklist
from cdcx.confluence import evaluate_confluence


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

@dataclass
class BacktestTrade:
    direction: str
    entry_bar: int
    entry_price: float
    exit_bar: int
    exit_price: float
    exit_reason: str
    position_size: float
    risk_amount: float
    realized_pnl: float          # after all costs
    realized_pnl_pct: float
    signal_score: float
    signal_label: str
    gross_pnl: float = 0.0       # before costs
    costs: float = 0.0           # total fees + fixed slip + impact in $
    fee_cost: float = 0.0
    slip_cost: float = 0.0
    impact_cost: float = 0.0


@dataclass
class BacktestResult:
    symbol: str
    timeframe: str
    n_bars: int
    initial_balance: float
    final_balance: float
    total_return_pct: float
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0          # average $ per trade (after costs)
    avg_win: float = 0.0
    avg_loss: float = 0.0
    n_wins: int = 0
    n_losses: int = 0
    n_signals_seen: int = 0
    n_trades_opened: int = 0
    total_costs: float = 0.0
    total_fee_cost: float = 0.0
    total_slip_cost: float = 0.0
    total_impact_cost: float = 0.0
    fee_pct: float = 0.0
    slippage_pct: float = 0.0
    impact_coeff: float = 0.0
    notes: str = ""


def _sqrt_market_impact_pct(
    position_size: float,
    avg_volume: float,
    volatility_pct: float,
    impact_coeff: float,
) -> float:
    """
    Square-root market impact (Almgren-style simplified):

        impact% = impact_coeff * volatility% * sqrt(Q / ADV)

    where Q = position size (base units) and ADV = average daily/bar volume.
    Caps participation at 100% so impact cannot explode on tiny-volume bars.
    Returns impact in *percent* (same units as fee_pct / slippage_pct).
    """
    if avg_volume <= 0 or position_size <= 0 or impact_coeff <= 0:
        return 0.0
    participation = min(position_size / avg_volume, 1.0)
    return impact_coeff * max(volatility_pct, 0.0) * (participation ** 0.5)


def apply_trade_costs(
    direction: str,
    entry_price: float,
    exit_price: float,
    position_size: float,
    fee_pct: float,
    slippage_pct: float,
    avg_volume: float = 0.0,
    volatility_pct: float = 0.0,
    impact_coeff: float = 0.10,
) -> tuple[float, float, float, float, float, float, float]:
    """
    Apply fee + fixed slippage + size-dependent market impact on both sides.

    Slippage / impact worsen the fill:
      long  entry: pay higher; exit: receive lower
      short entry: sell lower;  exit: buy higher

    fee_pct / slippage_pct / impact are in percent (e.g. 0.10 = 10 bps).

    Market impact uses the square-root law vs recent average volume and a
    volatility proxy (typically ATR/price * 100).

    Returns:
        (gross_pnl, total_costs, net_pnl, fill_exit,
         fee_cost, slip_cost, impact_cost)
    """
    fee = fee_pct / 100.0
    slip = slippage_pct / 100.0
    impact = _sqrt_market_impact_pct(
        position_size, avg_volume, volatility_pct, impact_coeff
    ) / 100.0

    # Combined adverse move per side
    adverse = slip + impact

    if direction == "long":
        fill_entry = entry_price * (1 + adverse)
        fill_exit = exit_price * (1 - adverse)
        gross = (exit_price - entry_price) * position_size
        fee_cost = fee * fill_entry * position_size + fee * fill_exit * position_size
        slip_cost = (
            entry_price * slip * position_size + exit_price * slip * position_size
        )
        impact_cost = (
            entry_price * impact * position_size + exit_price * impact * position_size
        )
    else:
        fill_entry = entry_price * (1 - adverse)
        fill_exit = exit_price * (1 + adverse)
        gross = (entry_price - exit_price) * position_size
        fee_cost = fee * fill_entry * position_size + fee * fill_exit * position_size
        slip_cost = (
            entry_price * slip * position_size + exit_price * slip * position_size
        )
        impact_cost = (
            entry_price * impact * position_size + exit_price * impact * position_size
        )

    costs = fee_cost + slip_cost + impact_cost
    net = gross - costs
    return gross, costs, net, fill_exit, fee_cost, slip_cost, impact_cost


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slice_ohlcv(data: OHLCV, end: int) -> OHLCV:
    """Return OHLCV covering bars [0 .. end] inclusive."""
    end = min(end + 1, len(data.closes))
    return OHLCV(
        timestamps=data.timestamps[:end],
        opens=data.opens[:end],
        highs=data.highs[:end],
        lows=data.lows[:end],
        closes=data.closes[:end],
        volumes=data.volumes[:end],
    )


def _signal_direction(signal: TradeSignal) -> Optional[str]:
    s = signal.signal.upper()
    if s in ("STRONG BUY", "BUY"):
        return "long"
    if s in ("STRONG SELL", "SELL"):
        return "short"
    return None


def _liquidity_snapshot(data: OHLCV, bar_index: int, atr: float, price: float, lookback: int) -> tuple[float, float]:
    """Return (avg_volume, volatility_pct) over the last `lookback` bars ending at bar_index."""
    start = max(0, bar_index - lookback + 1)
    vols = data.volumes[start:bar_index + 1]
    avg_vol = sum(vols) / len(vols) if vols else 0.0
    vol_pct = (atr / price * 100.0) if price > 0 else 0.0
    return avg_vol, vol_pct


def _compute_stats(trades: list[BacktestTrade], initial: float, equity: list[float]) -> dict:
    if not trades:
        return dict(
            win_rate=0.0, profit_factor=0.0, expectancy=0.0,
            avg_win=0.0, avg_loss=0.0, n_wins=0, n_losses=0,
            max_drawdown_pct=0.0, final_balance=initial, total_return_pct=0.0,
        )

    pnls = [t.realized_pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    pf = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)

    # max drawdown on equity curve
    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        peak = max(peak, e)
        dd = (peak - e) / peak * 100 if peak > 0 else 0.0
        max_dd = max(max_dd, dd)

    final = equity[-1] if equity else initial
    return dict(
        win_rate=len(wins) / len(trades) * 100,
        profit_factor=round(pf, 3) if pf != float("inf") else 999.0,
        expectancy=sum(pnls) / len(trades),
        avg_win=sum(wins) / len(wins) if wins else 0.0,
        avg_loss=sum(losses) / len(losses) if losses else 0.0,
        n_wins=len(wins),
        n_losses=len(losses),
        max_drawdown_pct=round(max_dd, 2),
        final_balance=round(final, 2),
        total_return_pct=round((final - initial) / initial * 100, 2),
    )


# ---------------------------------------------------------------------------
# Core single-timeframe backtest
# ---------------------------------------------------------------------------

def run_single_tf_backtest(
    data: OHLCV,
    symbol: str = "BTC/USDT",
    timeframe: str = "1h",
    warmup: int = 120,
    initial_balance: float = 10_000.0,
    risk_pct: float = 2.0,
    min_score_long: float = 60.0,
    min_score_short: float = 40.0,   # scores below this become candidates for short
    require_checklist: bool = True,
    trade_state_path: Optional[str] = None,
    fee_pct: float = 0.075,          # 7.5 bps per side (Crypto.com-style mid-tier taker)
    slippage_pct: float = 0.05,      # 5 bps fixed adverse slippage per side
    impact_coeff: float = 0.10,      # square-root impact coeff (see apply_trade_costs)
    volume_lookback: int = 48,       # bars for ADV used in impact model
) -> BacktestResult:
    """
    Walk the series bar-by-bar.

    Entry rules (configurable):
      - Signal must be BUY / STRONG BUY (or SELL / STRONG SELL)
      - Optional entry checklist (EMA, Fib, FVG, VP confirmation)
      - Only one open trade at a time (mirrors live rule C)
      - Risk-sized with the real risk.py logic

    Costs (applied on every round-trip, both sides):
      - fee_pct: exchange fee in percent per side
      - slippage_pct: fixed adverse fill slippage in percent per side
      - impact_coeff: square-root market impact
            impact% = impact_coeff * (ATR/price*100) * sqrt(Q / ADV)
        Larger positions vs recent volume pay more. Default 0.10 is a
        moderate coefficient used in many equity/crypto impact studies.
      Defaults ≈ mid-tier CEX taker + modest size impact.
    """
    n = len(data.closes)
    if n < warmup + 10:
        raise ValueError(f"Need at least {warmup + 10} bars, got {n}")

    # isolate paper-trade state
    tmp = trade_state_path or tempfile.mktemp(suffix="_bt_trades.json")
    original_path = settings.trade_state_path
    settings.trade_state_path = tmp
    if os.path.exists(tmp):
        os.remove(tmp)

    balance = initial_balance
    equity = [balance]
    closed: list[BacktestTrade] = []
    n_signals = 0
    n_opened = 0
    open_trade_meta: Optional[dict] = None  # tracks entry_bar + signal info
    last_close_bar = -999  # cooldown: no re-entry on the same bar as a close

    try:
        for i in range(warmup, n):
            price = data.closes[i]
            window = _slice_ohlcv(data, i)

            # --- update any open trade first ---
            # Load full list, mutate the open trade in-place, then save the
            # same list (do NOT re-load after mutation or the close is lost).
            all_trades = trade_manager.load_trades()
            open_t = next((t for t in all_trades if t.symbol == symbol and t.status == "open"), None)
            if open_t is not None:
                trade_manager.update_trade(open_t, price)
                trade_manager.save_trades(all_trades)
                if open_t.status == "closed":
                    meta = open_trade_meta or {}
                    exit_px = open_t.close_price or price
                    gross, costs, net, _, fee_c, slip_c, imp_c = apply_trade_costs(
                        open_t.direction, open_t.entry_price, exit_px,
                        open_t.position_size, fee_pct, slippage_pct,
                        avg_volume=meta.get("avg_volume", 0.0),
                        volatility_pct=meta.get("volatility_pct", 0.0),
                        impact_coeff=impact_coeff,
                    )
                    bt = BacktestTrade(
                        direction=open_t.direction,
                        entry_bar=meta.get("entry_bar", i),
                        entry_price=open_t.entry_price,
                        exit_bar=i,
                        exit_price=exit_px,
                        exit_reason=open_t.close_reason or "unknown",
                        position_size=open_t.position_size,
                        risk_amount=open_t.risk_amount,
                        realized_pnl=round(net, 2),
                        realized_pnl_pct=round(net / open_t.account_balance * 100, 4) if open_t.account_balance else 0.0,
                        signal_score=meta.get("score", 0.0),
                        signal_label=meta.get("label", ""),
                        gross_pnl=round(gross, 2),
                        costs=round(costs, 2),
                        fee_cost=round(fee_c, 2),
                        slip_cost=round(slip_c, 2),
                        impact_cost=round(imp_c, 2),
                    )
                    closed.append(bt)
                    balance += bt.realized_pnl
                    open_trade_meta = None
                    last_close_bar = i

            equity.append(balance)

            # --- look for new entry only if flat + cooldown ---
            if trade_manager.get_open_trade(symbol) is not None:
                continue
            if i <= last_close_bar:  # no same-bar re-entry
                continue

            try:
                signal = analyze_ohlcv(symbol, window)
            except Exception:
                continue  # insufficient data for some indicator on this window

            direction = _signal_direction(signal)
            if direction is None:
                continue

            # soft score filter (high score = bullish, low score = bearish)
            if direction == "long" and signal.total_score < min_score_long:
                continue
            if direction == "short" and signal.total_score > min_score_short:
                continue

            n_signals += 1

            if require_checklist:
                checklist = evaluate_entry_checklist(
                    signal, direction, risk_pct=risk_pct, symbol=symbol
                )
                if not checklist.all_passed:
                    continue

            # Reject stale targets: TP1 must still be ahead of entry with meaningful room
            tp1 = signal.take_profits["TP1"]
            if direction == "long" and tp1 <= signal.entry * 1.001:
                continue
            if direction == "short" and tp1 >= signal.entry * 0.999:
                continue
            if abs(tp1 - signal.entry) < max(0.4 * signal.atr, signal.entry * 0.002):
                continue

            plan = risk.build_position_plan(
                symbol=symbol,
                direction=direction,
                entry_price=signal.entry,
                atr=signal.atr,
                account_balance=balance,
                risk_pct=risk_pct,
            )
            if plan.position_size <= 0 or plan.stop_distance <= 0:
                continue
            if direction == "long" and plan.stop_price >= plan.entry_price:
                continue
            if direction == "short" and plan.stop_price <= plan.entry_price:
                continue

            tp_levels = [signal.take_profits[f"TP{k}"] for k in range(1, 5)]

            trade, msg = trade_manager.open_trade(
                symbol=symbol,
                direction=direction,
                entry_price=plan.entry_price,
                atr=plan.atr,
                stop_price=plan.stop_price,
                tp_levels=tp_levels,
                position_size=plan.position_size,
                risk_amount=plan.risk_amount,
                account_balance=plan.account_balance,
                confluence_timeframes=[timeframe],
                confluence_score=int(signal.total_score),
            )
            if trade is not None:
                n_opened += 1
                avg_vol, vol_pct = _liquidity_snapshot(
                    data, i, signal.atr, signal.entry, volume_lookback
                )
                open_trade_meta = {
                    "entry_bar": i,
                    "score": signal.total_score,
                    "label": signal.signal,
                    "avg_volume": avg_vol,
                    "volatility_pct": vol_pct,
                }

        # force-close any remaining open trade at last price
        all_trades = trade_manager.load_trades()
        open_t = next((t for t in all_trades if t.symbol == symbol and t.status == "open"), None)
        if open_t is not None:
            last_price = data.closes[-1]
            trade_manager.update_trade(open_t, last_price)
            if open_t.status == "open":
                from cdcx.trade_manager import _close_trade
                _close_trade(open_t, last_price, "End of backtest force-close", [])
            trade_manager.save_trades(all_trades)

            meta = open_trade_meta or {}
            exit_px = open_t.close_price or last_price
            gross, costs, net, _, fee_c, slip_c, imp_c = apply_trade_costs(
                open_t.direction, open_t.entry_price, exit_px,
                open_t.position_size, fee_pct, slippage_pct,
                avg_volume=meta.get("avg_volume", 0.0),
                volatility_pct=meta.get("volatility_pct", 0.0),
                impact_coeff=impact_coeff,
            )
            bt = BacktestTrade(
                direction=open_t.direction,
                entry_bar=meta.get("entry_bar", n - 1),
                entry_price=open_t.entry_price,
                exit_bar=n - 1,
                exit_price=exit_px,
                exit_reason=open_t.close_reason or "force-close",
                position_size=open_t.position_size,
                risk_amount=open_t.risk_amount,
                realized_pnl=round(net, 2),
                realized_pnl_pct=round(net / open_t.account_balance * 100, 4) if open_t.account_balance else 0.0,
                signal_score=meta.get("score", 0.0),
                signal_label=meta.get("label", ""),
                gross_pnl=round(gross, 2),
                costs=round(costs, 2),
                fee_cost=round(fee_c, 2),
                slip_cost=round(slip_c, 2),
                impact_cost=round(imp_c, 2),
            )
            closed.append(bt)
            balance += bt.realized_pnl
            equity.append(balance)

    finally:
        settings.trade_state_path = original_path
        if os.path.exists(tmp) and trade_state_path is None:
            try:
                os.remove(tmp)
            except OSError:
                pass

    stats = _compute_stats(closed, initial_balance, equity)
    return BacktestResult(
        symbol=symbol,
        timeframe=timeframe,
        n_bars=n,
        initial_balance=initial_balance,
        trades=closed,
        equity_curve=equity,
        n_signals_seen=n_signals,
        n_trades_opened=n_opened,
        total_costs=round(sum(t.costs for t in closed), 2),
        total_fee_cost=round(sum(t.fee_cost for t in closed), 2),
        total_slip_cost=round(sum(t.slip_cost for t in closed), 2),
        total_impact_cost=round(sum(t.impact_cost for t in closed), 2),
        fee_pct=fee_pct,
        slippage_pct=slippage_pct,
        impact_coeff=impact_coeff,
        notes=(
            f"Single-TF + paper rules | fee {fee_pct:.3f}% + slip {slippage_pct:.3f}% "
            f"+ impact_coeff {impact_coeff:.2f}/side"
        ),
        **stats,
    )


# ---------------------------------------------------------------------------
# Simplified multi-TF confluence backtest
# ---------------------------------------------------------------------------

def run_confluence_backtest(
    data_1h: OHLCV,
    symbol: str = "BTC/USDT",
    warmup_1h: int = 200,
    initial_balance: float = 10_000.0,
    risk_pct: float = 2.0,
    fee_pct: float = 0.075,
    slippage_pct: float = 0.05,
    impact_coeff: float = 0.10,
    volume_lookback: int = 48,
) -> BacktestResult:
    """
    Approximate multi-TF confluence by resampling the 1h series into
    4h / 1d / 1w and evaluating signals on aligned bars.

    Entry only when confluence.should_execute is True and the entry-TF
    checklist passes. Uses the same risk + trade-manager path.
    """
    from cdcx.backtest.synthetic import resample_ohlcv

    data_4h = resample_ohlcv(data_1h, 4)
    data_1d = resample_ohlcv(data_1h, 24)
    data_1w = resample_ohlcv(data_1h, 168)

    n = len(data_1h.closes)
    tmp = tempfile.mktemp(suffix="_bt_conf.json")
    original_path = settings.trade_state_path
    settings.trade_state_path = tmp
    if os.path.exists(tmp):
        os.remove(tmp)

    balance = initial_balance
    equity = [balance]
    closed: list[BacktestTrade] = []
    n_signals = 0
    n_opened = 0
    open_meta: Optional[dict] = None

    def _tf_index(higher: OHLCV, ts: int) -> int:
        """Largest index in higher TF whose timestamp <= ts."""
        for j in range(len(higher.timestamps) - 1, -1, -1):
            if higher.timestamps[j] <= ts:
                return j
        return 0

    try:
        for i in range(warmup_1h, n):
            price = data_1h.closes[i]
            ts = data_1h.timestamps[i]

            # update open trade (mutate in-place, then save — never re-load after)
            all_trades = trade_manager.load_trades()
            open_t = next((t for t in all_trades if t.symbol == symbol and t.status == "open"), None)
            if open_t is not None:
                trade_manager.update_trade(open_t, price)
                trade_manager.save_trades(all_trades)
                if open_t.status == "closed":
                    meta = open_meta or {}
                    exit_px = open_t.close_price or price
                    gross, costs, net, _, fee_c, slip_c, imp_c = apply_trade_costs(
                        open_t.direction, open_t.entry_price, exit_px,
                        open_t.position_size, fee_pct, slippage_pct,
                        avg_volume=meta.get("avg_volume", 0.0),
                        volatility_pct=meta.get("volatility_pct", 0.0),
                        impact_coeff=impact_coeff,
                    )
                    bt = BacktestTrade(
                        direction=open_t.direction,
                        entry_bar=meta.get("entry_bar", i),
                        entry_price=open_t.entry_price,
                        exit_bar=i,
                        exit_price=exit_px,
                        exit_reason=open_t.close_reason or "unknown",
                        position_size=open_t.position_size,
                        risk_amount=open_t.risk_amount,
                        realized_pnl=round(net, 2),
                        realized_pnl_pct=round(net / open_t.account_balance * 100, 4) if open_t.account_balance else 0.0,
                        signal_score=meta.get("score", 0.0),
                        signal_label=meta.get("label", ""),
                        gross_pnl=round(gross, 2),
                        costs=round(costs, 2),
                        fee_cost=round(fee_c, 2),
                        slip_cost=round(slip_c, 2),
                        impact_cost=round(imp_c, 2),
                    )
                    closed.append(bt)
                    balance += bt.realized_pnl
                    open_meta = None

            equity.append(balance)

            if trade_manager.get_open_trade(symbol) is not None:
                continue

            # build signals for each TF up to current time
            try:
                w1h = _slice_ohlcv(data_1h, i)
                sig_1h = analyze_ohlcv(symbol, w1h)

                i4 = _tf_index(data_4h, ts)
                i1d = _tf_index(data_1d, ts)
                i1w = _tf_index(data_1w, ts)
                if min(i4, i1d, i1w) < 50:
                    continue

                sig_4h = analyze_ohlcv(symbol, _slice_ohlcv(data_4h, i4))
                sig_1d = analyze_ohlcv(symbol, _slice_ohlcv(data_1d, i1d))
                sig_1w = analyze_ohlcv(symbol, _slice_ohlcv(data_1w, i1w))
            except Exception:
                continue

            signals = {
                "1h": sig_1h.signal,
                "4h": sig_4h.signal,
                "1d": sig_1d.signal,
                "1w": sig_1w.signal,
            }
            conf = evaluate_confluence(signals)
            if not conf.should_execute:
                continue

            n_signals += 1
            direction = conf.direction
            entry_sig = sig_1h  # fastest TF for sizing

            checklist = evaluate_entry_checklist(
                entry_sig, direction, risk_pct=risk_pct, symbol=symbol
            )
            if not checklist.all_passed:
                continue

            tp1 = entry_sig.take_profits["TP1"]
            if direction == "long" and tp1 <= entry_sig.entry * 1.001:
                continue
            if direction == "short" and tp1 >= entry_sig.entry * 0.999:
                continue
            if abs(tp1 - entry_sig.entry) < max(0.4 * entry_sig.atr, entry_sig.entry * 0.002):
                continue

            plan = risk.build_position_plan(
                symbol=symbol,
                direction=direction,
                entry_price=entry_sig.entry,
                atr=entry_sig.atr,
                account_balance=balance,
                risk_pct=risk_pct,
            )
            if plan.position_size <= 0 or plan.stop_distance <= 0:
                continue
            tp_levels = [entry_sig.take_profits[f"TP{k}"] for k in range(1, 5)]

            trade, _ = trade_manager.open_trade(
                symbol=symbol,
                direction=direction,
                entry_price=plan.entry_price,
                atr=plan.atr,
                stop_price=plan.stop_price,
                tp_levels=tp_levels,
                position_size=plan.position_size,
                risk_amount=plan.risk_amount,
                account_balance=plan.account_balance,
                confluence_timeframes=conf.agreeing_timeframes,
                confluence_score=conf.confluence_score,
            )
            if trade is not None:
                n_opened += 1
                avg_vol, vol_pct = _liquidity_snapshot(
                    data_1h, i, entry_sig.atr, entry_sig.entry, volume_lookback
                )
                open_meta = {
                    "entry_bar": i,
                    "score": entry_sig.total_score,
                    "label": conf.label,
                    "avg_volume": avg_vol,
                    "volatility_pct": vol_pct,
                }

        # force close leftover
        all_trades = trade_manager.load_trades()
        open_t = next((t for t in all_trades if t.symbol == symbol and t.status == "open"), None)
        if open_t is not None:
            last = data_1h.closes[-1]
            trade_manager.update_trade(open_t, last)
            if open_t.status == "open":
                from cdcx.trade_manager import _close_trade
                _close_trade(open_t, last, "End of backtest force-close", [])
            trade_manager.save_trades(all_trades)
            meta = open_meta or {}
            exit_px = open_t.close_price or last
            gross, costs, net, _, fee_c, slip_c, imp_c = apply_trade_costs(
                open_t.direction, open_t.entry_price, exit_px,
                open_t.position_size, fee_pct, slippage_pct,
                avg_volume=meta.get("avg_volume", 0.0),
                volatility_pct=meta.get("volatility_pct", 0.0),
                impact_coeff=impact_coeff,
            )
            bt = BacktestTrade(
                direction=open_t.direction,
                entry_bar=meta.get("entry_bar", n - 1),
                entry_price=open_t.entry_price,
                exit_bar=n - 1,
                exit_price=exit_px,
                exit_reason=open_t.close_reason or "force-close",
                position_size=open_t.position_size,
                risk_amount=open_t.risk_amount,
                realized_pnl=round(net, 2),
                realized_pnl_pct=round(net / open_t.account_balance * 100, 4) if open_t.account_balance else 0.0,
                signal_score=meta.get("score", 0.0),
                signal_label=meta.get("label", ""),
                gross_pnl=round(gross, 2),
                costs=round(costs, 2),
                fee_cost=round(fee_c, 2),
                slip_cost=round(slip_c, 2),
                impact_cost=round(imp_c, 2),
            )
            closed.append(bt)
            balance += bt.realized_pnl
            equity.append(balance)

    finally:
        settings.trade_state_path = original_path
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass

    stats = _compute_stats(closed, initial_balance, equity)
    return BacktestResult(
        symbol=symbol,
        timeframe="1h+confluence",
        n_bars=n,
        initial_balance=initial_balance,
        trades=closed,
        equity_curve=equity,
        n_signals_seen=n_signals,
        n_trades_opened=n_opened,
        total_costs=round(sum(t.costs for t in closed), 2),
        total_fee_cost=round(sum(t.fee_cost for t in closed), 2),
        total_slip_cost=round(sum(t.slip_cost for t in closed), 2),
        total_impact_cost=round(sum(t.impact_cost for t in closed), 2),
        fee_pct=fee_pct,
        slippage_pct=slippage_pct,
        impact_coeff=impact_coeff,
        notes=(
            f"Multi-TF confluence + checklist | fee {fee_pct:.3f}% + slip {slippage_pct:.3f}% "
            f"+ impact_coeff {impact_coeff:.2f}/side"
        ),
        **stats,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def format_backtest_report(result: BacktestResult) -> str:
    lines = [
        "=" * 60,
        "CDCX BACKTEST REPORT".center(60),
        "=" * 60,
        f"Symbol:          {result.symbol}",
        f"Timeframe:       {result.timeframe}",
        f"Bars:            {result.n_bars}",
        f"Notes:           {result.notes}",
        "",
        f"Fee / side:      {result.fee_pct:.3f}%",
        f"Fixed slip/side: {result.slippage_pct:.3f}%",
        f"Impact coeff:    {result.impact_coeff:.2f}  (sqrt law vs ADV)",
        f"Total costs:     ${result.total_costs:,.2f}",
        f"  of which fees:    ${result.total_fee_cost:,.2f}",
        f"  fixed slippage:   ${result.total_slip_cost:,.2f}",
        f"  market impact:    ${result.total_impact_cost:,.2f}",
        "",
        f"Initial balance: {result.initial_balance:,.2f}",
        f"Final balance:   {result.final_balance:,.2f}",
        f"Total return:    {result.total_return_pct:+.2f}%",
        f"Max drawdown:    {result.max_drawdown_pct:.2f}%",
        "",
        f"Signals seen:    {result.n_signals_seen}",
        f"Trades opened:   {result.n_trades_opened}",
        f"Trades closed:   {len(result.trades)}",
        f"Wins / Losses:   {result.n_wins} / {result.n_losses}",
        f"Win rate:        {result.win_rate:.1f}%",
        f"Profit factor:   {result.profit_factor:.3f}",
        f"Expectancy:      {result.expectancy:+.2f} $ / trade (after costs)",
        f"Avg win:         {result.avg_win:+.2f}",
        f"Avg loss:        {result.avg_loss:+.2f}",
        "",
    ]

    if result.trades:
        lines.append("-" * 60)
        lines.append("TRADE LOG (last 15)  [net | fee | slip | impact]")
        lines.append("-" * 60)
        for t in result.trades[-15:]:
            lines.append(
                f"  {t.direction.upper():5} bar {t.entry_bar:4}→{t.exit_bar:4}  "
                f"net {t.realized_pnl:+8.2f}  "
                f"fee {t.fee_cost:5.2f} slip {t.slip_cost:5.2f} imp {t.impact_cost:5.2f}  "
                f"({t.exit_reason[:28]})"
            )
    lines.append("=" * 60)
    return "\n".join(lines)
