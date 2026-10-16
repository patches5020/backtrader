"""
vwap_vp_research.py
---------------------
Phase 5 of the previous-day AVWAP + AFVP framework (2026-10-16): offline
research on the vwap-vp-1 setups. RESEARCH ONLY -- it reads history, never
places, plans or journals a trade, and changes nothing in the live system.

Walk-forward, bar by bar: at the close of every bar t it rebuilds the
previous-day levels and classification from bars <= t only (now = bar t's
close), so no future bar can leak into a signal. A setup FIRES when its
state changes into its trigger state:

    VP-01  POC reaction        -> CONFIRMED   (trade in its direction)
    VP-03  trend continuation  -> CONFIRMED
    VP-04  value-area breakout -> ACCEPTED
    VP-05  band exhaustion     -> RETURNED    (reversal direction)
    CAND   qualification       -> CANDIDATE   (2+ evidence families; the
                                  higher-timeframe check is NOT replayed here)
    B0     baseline: a close crossing the anchored VWAP (reclaim = long,
           loss = short) -- "is any of this better than VWAP alone?"
VP-02 has no direction and is not traded.

Each fire is replayed with cdcx's EXISTING, protected trade model -- nothing
here is tuned: entry = next bar's open; stop = resolve_atr_multiplier(symbol)
x ATR (1.5x) at the signal bar; TP1-4 = resolve_tp_ratios() R (2.2/2.6/3.2/
4.5), 25% each; trade_manager rules G/H/I via avp_rejection.simulate_outcome
(a bar touching stop and target counts as the stop). One open trade per
setup at a time. Trades still open at the end of the data are excluded.

Costs (assumptions, override on the CLI): FEE_BPS per side and SLIPPAGE_BPS
per side, charged on the entry notional both ways and converted to R
(cost_R = 2 x (fee + slippage) x entry / stop_distance).

Development / out-of-sample: trades are split by signal time at a fixed
fraction of the history (default the first 70% vs the last 30%); the rules
were frozen (ruleset vwap-vp-1) before any run, so the split only checks
whether a result holds up on data the rules never saw.

    python -m cdcx.backtest.vwap_vp_research --symbol XRP/USD --bars 40000
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

from .. import avp_rejection, no_trade_gate, risk
from ..exchange.cryptocom import OHLCV
from ..indicators import atr_ema_variant1
from ..volume_profile.prev_day import crypto_session, prev_day_levels
from ..volume_profile.vwap_confluence import RULESET_VERSION, classify

FEE_BPS = 7.5          # per side -- assumption, not a quoted Crypto.com rate
SLIPPAGE_BPS = 2.0     # per side
DEV_FRACTION = 0.70
STRUCTURE_BARS = 300   # bars before the previous session kept for the BOS/FVG reads
TRIGGERS = {"VP-01": "CONFIRMED", "VP-03": "CONFIRMED", "VP-04": "ACCEPTED", "VP-05": "RETURNED"}
SETUP_ORDER = ["B0", "VP-01", "VP-03", "VP-04", "VP-05", "CAND"]


@dataclass
class Trade:
    setup: str
    direction: str
    signal_index: int
    signal_ts: float
    entry: float
    stop: float
    status: str = "open"
    gross_r: float = 0.0
    cost_r: float = 0.0
    net_r: float = 0.0
    tps_hit: int = 0
    exit_index: Optional[int] = None
    mae_r: float = 0.0


@dataclass
class Stats:
    trades: int = 0
    win_rate: float = 0.0
    avg_net_r: float = 0.0
    avg_gross_r: float = 0.0       # before costs -- separates a setup's edge from the cost drag
    avg_cost_r: float = 0.0
    total_net_r: float = 0.0
    profit_factor: Optional[float] = None
    max_drawdown_r: float = 0.0
    avg_mae_r: float = 0.0
    avg_bars_held: float = 0.0


def _slice(data: OHLCV, lo: int, hi: int) -> OHLCV:
    return OHLCV(data.timestamps[lo:hi], data.opens[lo:hi], data.highs[lo:hi], data.lows[lo:hi],
                 data.closes[lo:hi], data.volumes[lo:hi], market=data.market)


def find_signals(data: OHLCV, timeframe: str, start_index: int = 0) -> list[tuple[int, str, str]]:
    """[(bar index, setup, direction)] -- walk-forward, bars <= t only at each t."""
    tf_s = no_trade_gate.timeframe_to_seconds(timeframe)
    ts = [no_trade_gate.timestamp_to_seconds(t) for t in data.timestamps]
    signals: list[tuple[int, str, str]] = []
    prev_state: dict[str, str] = {}
    prev_side: Optional[bool] = None
    lo = 0
    for t in range(start_index, len(ts)):
        now = ts[t] + tf_s
        sess_start = crypto_session(now)[0]
        while lo < t and ts[lo] < sess_start - STRUCTURE_BARS * tf_s:
            lo += 1
        sub = _slice(data, lo, t + 1)
        lv = prev_day_levels(sub, timeframe, now=now)
        if lv.status != "OK":
            prev_state, prev_side = {}, None
            continue
        res = classify(lv, sub)
        if res.status != "OK":
            prev_state, prev_side = {}, None
            continue
        for s in res.setups:
            trig = TRIGGERS.get(s.code)
            if trig and s.state == trig and s.direction and prev_state.get(s.code) != f"{trig}:{s.direction}":
                signals.append((t, s.code, s.direction))
            prev_state[s.code] = f"{s.state}:{s.direction}"
        cand = f"{res.qualification}:{res.qualification_direction}"
        if res.qualification == "CANDIDATE" and prev_state.get("CAND") != cand:
            signals.append((t, "CAND", res.qualification_direction))
        prev_state["CAND"] = cand
        side = data.closes[t] > lv.avwap.vwap
        if prev_side is not None and side != prev_side:
            signals.append((t, "B0", "bullish" if side else "bearish"))
        prev_side = side
    return signals


def replay(data: OHLCV, signals: list[tuple[int, str, str]], symbol: str,
           fee_bps: float = FEE_BPS, slippage_bps: float = SLIPPAGE_BPS) -> list[Trade]:
    """Replays each signal with the protected stop/TP model; one open trade per setup."""
    h, l, c, o = data.highs, data.lows, data.closes, data.opens
    atr = atr_ema_variant1.calculate_atr(h, l, c)
    mult = risk.resolve_atr_multiplier(symbol)
    ratios = risk.resolve_tp_ratios()
    pcts = risk.resolve_tp_close_pcts()
    busy_until: dict[str, int] = {}
    trades: list[Trade] = []
    for t, setup, direction in signals:
        if t + 1 >= len(c) or busy_until.get(setup, -1) >= t:
            continue
        a = atr[t]
        if not a or a != a or a <= 0:
            continue
        long = direction == "bullish"
        entry = o[t + 1]
        dist = mult * a
        stop = entry - dist if long else entry + dist
        sign = 1 if long else -1
        tps = [entry + sign * r * dist for r in ratios]
        # simulate_outcome is long-only: mirror a short by negating every price.
        if long:
            hh, ll, e, s, tp = h, l, entry, stop, tps
        else:
            hh, ll, e, s, tp = [-x for x in l], [-x for x in h], -entry, -stop, [-x for x in tps]
        plan = avp_rejection.TradePlan("research", t, e, s, tp, list(ratios), list(pcts), a, mult)
        out = avp_rejection.simulate_outcome(plan, hh, ll)
        tr = Trade(setup, direction, t, no_trade_gate.timestamp_to_seconds(data.timestamps[t]), entry, stop,
                   status=out.status, gross_r=out.r_multiple, tps_hit=out.tps_hit, exit_index=out.exit_index)
        end = out.exit_index if out.exit_index is not None else len(c) - 1
        worst = min(ll[t + 1:end + 1]) if end >= t + 1 else e
        tr.mae_r = round(max(0.0, (e - worst) / dist), 3)
        tr.cost_r = round(2 * (fee_bps + slippage_bps) / 10_000 * entry / dist, 4)
        tr.net_r = round(tr.gross_r - tr.cost_r, 4)
        busy_until[setup] = end if out.status != "open" else len(c)
        trades.append(tr)
    return trades


def stats(trades: list[Trade]) -> Stats:
    done = [t for t in trades if t.status != "open"]
    if not done:
        return Stats()
    rs = [t.net_r for t in done]
    wins, losses = sum(r for r in rs if r > 0), -sum(r for r in rs if r < 0)
    eq = peak = dd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return Stats(
        trades=len(done), win_rate=round(sum(1 for r in rs if r > 0) / len(rs), 3),
        avg_net_r=round(sum(rs) / len(rs), 3),
        avg_gross_r=round(sum(t.gross_r for t in done) / len(done), 3),
        avg_cost_r=round(sum(t.cost_r for t in done) / len(done), 3),
        total_net_r=round(sum(rs), 2),
        profit_factor=round(wins / losses, 2) if losses > 0 else None,
        max_drawdown_r=round(dd, 2), avg_mae_r=round(sum(t.mae_r for t in done) / len(done), 3),
        avg_bars_held=round(sum(t.exit_index - t.signal_index for t in done) / len(done), 1),
    )


def run(data: OHLCV, symbol: str, timeframe: str, dev_fraction: float = DEV_FRACTION,
        fee_bps: float = FEE_BPS, slippage_bps: float = SLIPPAGE_BPS) -> dict:
    signals = find_signals(data, timeframe)
    trades = replay(data, signals, symbol, fee_bps, slippage_bps)
    split_ts = no_trade_gate.timestamp_to_seconds(
        data.timestamps[int(len(data.timestamps) * dev_fraction)])
    table = {}
    for setup in SETUP_ORDER:
        mine = [t for t in trades if t.setup == setup]
        table[setup] = {
            "all": asdict(stats(mine)),
            "development": asdict(stats([t for t in mine if t.signal_ts < split_ts])),
            "out_of_sample": asdict(stats([t for t in mine if t.signal_ts >= split_ts])),
            "still_open": sum(1 for t in mine if t.status == "open"),
        }
    return {
        "ruleset": RULESET_VERSION, "symbol": symbol, "timeframe": timeframe,
        "bars": len(data.timestamps), "first_bar": no_trade_gate.timestamp_to_seconds(data.timestamps[0]),
        "last_bar": no_trade_gate.timestamp_to_seconds(data.timestamps[-1]), "split_ts": split_ts,
        "fee_bps": fee_bps, "slippage_bps": slippage_bps, "signals": len(signals), "setups": table,
        "trades": [asdict(t) for t in trades],
    }


def format_report(result: dict) -> str:
    from datetime import datetime, timezone

    f = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
    lines = [
        f"VWAP-VP RESEARCH ({result['ruleset']}) -- {result['symbol']} {result['timeframe']}, "
        f"{result['bars']} bars {f(result['first_bar'])} -> {f(result['last_bar'])}",
        f"Costs {result['fee_bps']:g} bps fee + {result['slippage_bps']:g} bps slippage per side | "
        f"development < {f(result['split_ts'])} <= out-of-sample | research only, no trades placed",
        "",
        f"{'Setup':<7}{'Split':<15}{'Trades':>7}{'Win%':>7}{'GrossR':>8}{'CostR':>7}{'NetR':>8}{'TotalR':>9}{'PF':>7}{'MaxDD R':>9}{'MAE R':>7}",
    ]
    for setup in SETUP_ORDER:
        row = result["setups"][setup]
        for split in ("development", "out_of_sample"):
            s = row[split]
            pf = "-" if s["profit_factor"] is None else f"{s['profit_factor']:.2f}"
            lines.append(f"{setup:<7}{split:<15}{s['trades']:>7}{s['win_rate'] * 100:>6.0f}%{s['avg_gross_r']:>8.3f}{s['avg_cost_r']:>7.3f}{s['avg_net_r']:>8.3f}"
                         f"{s['total_net_r']:>9.2f}{pf:>7}{s['max_drawdown_r']:>9.2f}{s['avg_mae_r']:>7.2f}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--symbol", default="XRP/USD")
    ap.add_argument("--timeframe", default="5m")
    ap.add_argument("--bars", type=int, default=40000)
    ap.add_argument("--fee-bps", type=float, default=FEE_BPS)
    ap.add_argument("--slippage-bps", type=float, default=SLIPPAGE_BPS)
    ap.add_argument("--dev-fraction", type=float, default=DEV_FRACTION)
    ap.add_argument("--out", help="write the full result (incl. every trade) as JSON here")
    args = ap.parse_args(argv)

    from ..exchange.cryptocom import CryptoComExchange

    t0 = time.time()
    data = CryptoComExchange().fetch_ohlcv(args.symbol, args.timeframe, args.bars)
    tf_s = no_trade_gate.timeframe_to_seconds(args.timeframe)
    if no_trade_gate.last_bar_is_forming(data.timestamps, args.timeframe, time.time()):
        data = _slice(data, 0, len(data.timestamps) - 1)
    ts = [no_trade_gate.timestamp_to_seconds(x) for x in data.timestamps]
    gaps = sum(1 for a, b in zip(ts, ts[1:]) if b - a != tf_s)
    result = run(data, args.symbol, args.timeframe, args.dev_fraction, args.fee_bps, args.slippage_bps)
    result["data_gaps"] = gaps
    print(format_report(result))
    print(f"\n{result['signals']} signals, {gaps} data gaps, {time.time() - t0:.0f}s")
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(result, fh, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
