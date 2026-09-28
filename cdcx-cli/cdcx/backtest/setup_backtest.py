"""
setup_backtest.py
-----------------
Stage 2 of the AVP Bullish Rejection validation plan: a historical,
walk-forward backtest that measures each bullish volume-profile setup
SEPARATELY, on 1H and 4H separately, with identical risk and costs -- so we
can tell whether the labels carry different information or just describe
the same bounce several ways.

Strategies (all long, all paper):
    avp_confirm    AVP Bullish Rejection, entry at the hold candle's close
    avp_retest     AVP Bullish Rejection, entry at a held retest's close
    poc_bounce     vp_setup POC Bounce (up), entry at the close it first appears
    va_reversal    vp_setup Value Area Reversal (up), same
    vpbos_bull     vp_bos VP-BOS-BULL (confirmed acceptance), same
    baseline       an unconditional long every BASELINE_EVERY bars -- the
                   "does the setup beat just being long?" control

Every trade uses the EXISTING protected risk model via avp_rejection.build_plan
(1.5x ATR stop, TP1-4 at 2.2/2.6/3.2/4.5R closing 25% each) and
avp_rejection.simulate_outcome (trade_manager rules G/H/I, stop first when a
bar touches both). One open trade per strategy at a time (trade_manager
rule C). Costs: fee + slippage per side (defaults match
cdcx.backtest.engine: 7.5 bps + 5 bps), charged as R on the full size.

No lookahead: at bar e the classifiers see only bars [0..e]; all bars there
are closed. Outcomes then replay the bars after entry.

Splits (chronological by entry time): development 60% / validation 20% /
out-of-sample 20%. Stage 2 reports development + validation only; the OOS
slice is NOT computed unless include_oos=True (stage 3) -- nothing may be
tuned on it.

Run:  python -m cdcx.backtest.setup_backtest --symbol XRP/USD --bars-1h 8760 --bars-4h 4380
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional

from cdcx import avp_rejection as ar
from cdcx import vp_bos, vp_setup
from cdcx.exchange.cryptocom import OHLCV
from cdcx.indicators import atr_ema_variant1, volume_profile_fixed

WINDOW = 300               # bars the classifiers see at each step (anchor lookback 100, ATR/VP warm-up)
WARMUP = 120
BASELINE_EVERY = 24
DEFAULT_FEE_PCT = 0.075    # per side, same as cdcx.backtest.engine
DEFAULT_SLIPPAGE_PCT = 0.05
SPLITS = (("development", 0.6), ("validation", 0.2), ("out_of_sample", 0.2))
STRATEGIES = ("avp_confirm", "avp_retest", "poc_bounce", "va_reversal", "vpbos_bull", "baseline")
DATA_DIR = Path(__file__).resolve().parents[2] / "trading" / "backtest_data"


@dataclass
class Trade:
    strategy: str
    timeframe: str
    signal_index: int
    entry_index: int
    entry_time: int
    entry: float
    stop: float
    status: str
    tps_hit: int
    gross_r: float
    cost_r: float
    net_r: float
    exit_index: Optional[int]


# --- signal detectors: each returns (key, entry_index, entry_type) for a NEW signal at bar e, else None ---

def _window(data: OHLCV, e: int):
    s = max(0, e + 1 - WINDOW)
    return s, (data.timestamps[s:e + 1], data.highs[s:e + 1], data.lows[s:e + 1],
               data.closes[s:e + 1], data.volumes[s:e + 1])


def detect_avp(data: OHLCV, e: int, tf: str, symbol: str, variant: str):
    s, (ts, h, l, c, v) = _window(data, e)
    r = ar.classify_avp_rejection(ts, h, l, c, v, tf, symbol=symbol, now=float("inf"))
    if r.state != "CONFIRMED" or r.plan is None:
        return None
    key = (r.level_name, s + r.reclaim_index)
    if variant == "confirm":
        return (key, s + r.reclaim_index + 1) if s + r.reclaim_index + 1 == e else None
    if r.plan.entry_type == "retest" and s + r.plan.entry_index == e:
        return key, e
    return None


def detect_vp_setup(data: OHLCV, e: int, kind: str):
    s, (ts, h, l, c, v) = _window(data, e)
    fvp = volume_profile_fixed.analyze(h, l, v, price=c[-1])
    r = vp_setup.classify_vp_setup(c[-1], fvp.poc, fvp.vah, fvp.val, h, l, c, v)
    if r.setup_type == kind and r.direction == "up":
        return (kind, round(fvp.poc, 8)), e
    return None


def detect_vpbos_bull(data: OHLCV, e: int, tf: str):
    s, (ts, h, l, c, v) = _window(data, e)
    r = vp_bos.classify_vp_bos(ts, h, l, c, v, tf, now=float("inf"))
    if r.signal == "VP-BOS-BULL":
        return ("vpbos", s + r.break_index), e
    return None


def cost_in_r(entry: float, stop: float, fee_pct: float, slippage_pct: float) -> float:
    """Round-trip fee + slippage on the full size, expressed in R."""
    return 2 * (fee_pct + slippage_pct) / 100.0 * entry / (entry - stop)


def run_strategy(data: OHLCV, tf: str, symbol: str, strategy: str,
                 fee_pct: float = DEFAULT_FEE_PCT, slippage_pct: float = DEFAULT_SLIPPAGE_PCT,
                 progress: Optional[Callable[[int, int], None]] = None) -> list[Trade]:
    detector = {
        "avp_confirm": lambda e: detect_avp(data, e, tf, symbol, "confirm"),
        "avp_retest": lambda e: detect_avp(data, e, tf, symbol, "retest"),
        "poc_bounce": lambda e: detect_vp_setup(data, e, "poc_bounce"),
        "va_reversal": lambda e: detect_vp_setup(data, e, "value_area_reversal"),
        "vpbos_bull": lambda e: detect_vpbos_bull(data, e, tf),
        "baseline": lambda e: (("baseline", e), e) if e % BASELINE_EVERY == 0 else None,
    }[strategy]
    atr = atr_ema_variant1.calculate_atr(data.highs, data.lows, data.closes)
    trades, seen, busy_until, was_active = [], set(), -1, False
    n = len(data.closes)
    for e in range(WARMUP, n - 1):
        if progress and e % 500 == 0:
            progress(e, n)
        # The detector runs on every bar (even while a trade is open) so a
        # setup that stays active for many bars is entered only when it FIRST
        # appears -- not re-entered on every bar it persists.
        hit = detector(e)
        first_appearance = hit is not None and not was_active
        was_active = hit is not None
        if not first_appearance or e <= busy_until:  # rule C: one open trade at a time
            continue
        key, entry_index = hit
        if key in seen:
            continue
        seen.add(key)
        plan = ar.build_plan(symbol, entry_index, data.closes[entry_index], atr[entry_index], strategy)
        out = ar.simulate_outcome(plan, data.highs, data.lows)
        cost = cost_in_r(plan.entry, plan.stop, fee_pct, slippage_pct)
        trades.append(Trade(strategy, tf, e, entry_index, data.timestamps[entry_index], plan.entry, plan.stop,
                            out.status, out.tps_hit, out.r_multiple, round(cost, 4),
                            round(out.r_multiple - cost, 4), out.exit_index))
        busy_until = out.exit_index if out.exit_index is not None else n
    return trades


def split_bounds(data: OHLCV) -> dict[str, tuple[int, int]]:
    """Chronological [start_ts, end_ts) per split over the tradable range."""
    ts = data.timestamps[WARMUP:]
    bounds, start = {}, 0
    for name, frac in SPLITS:
        end = len(ts) if name == SPLITS[-1][0] else start + int(len(ts) * frac)
        bounds[name] = (ts[start], ts[end - 1] + 1)
        start = end
    return bounds


def metrics(trades: list[Trade]) -> dict:
    closed = [t for t in trades if t.status != "open"]
    rs = [t.net_r for t in closed]
    if not rs:
        return {"trades": 0, "open": len(trades) - len(closed)}
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    equity, peak, max_dd, streak, max_streak = 0.0, 0.0, 0.0, 0, 0
    for r in rs:
        equity += r
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        streak = streak + 1 if r <= 0 else 0
        max_streak = max(max_streak, streak)
    return {
        "trades": len(rs), "open": len(trades) - len(closed),
        "win_rate": round(len(wins) / len(rs), 3),
        "expectancy_r": round(sum(rs) / len(rs), 3),
        "gross_expectancy_r": round(sum(t.gross_r for t in closed) / len(rs), 3),
        "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) else None,
        "total_r": round(sum(rs), 2),
        "max_drawdown_r": round(max_dd, 2),
        "max_losing_streak": max_streak,
        "avg_cost_r": round(sum(t.cost_r for t in closed) / len(rs), 3),
    }


def load_or_fetch(symbol: str, tf: str, bars: int, refresh: bool = False) -> tuple[OHLCV, str]:
    """Cache under trading/backtest_data so every run (and stage 3) sees the
    exact same frozen dataset; returns (data, sha256 of the cached file)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{symbol.replace('/', '')}_{tf}_{bars}.json"
    if refresh or not path.exists():
        from cdcx.config import settings
        from cdcx.exchange.cryptocom import CryptoComExchange

        data = CryptoComExchange(settings.cryptocom_api_key, settings.cryptocom_api_secret).fetch_ohlcv(
            symbol, timeframe=tf, limit=bars)
        path.write_text(json.dumps(asdict(data)))
    raw = path.read_bytes()
    return OHLCV(**json.loads(raw)), hashlib.sha256(raw).hexdigest()


def run(symbol: str, bars: dict[str, int], include_oos: bool = False, refresh: bool = False,
        fee_pct: float = DEFAULT_FEE_PCT, slippage_pct: float = DEFAULT_SLIPPAGE_PCT) -> dict:
    report = {"symbol": symbol, "generated": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
              "fee_pct_per_side": fee_pct, "slippage_pct_per_side": slippage_pct,
              "include_oos": include_oos, "timeframes": {}}
    for tf, n_bars in bars.items():
        data, digest = load_or_fetch(symbol, tf, n_bars, refresh)
        bounds = split_bounds(data)
        tf_report = {"bars": len(data.closes), "first_ts": data.timestamps[0], "last_ts": data.timestamps[-1],
                     "data_sha256": digest, "splits": bounds, "results": {}}
        for strategy in STRATEGIES:
            t0 = time.time()
            trades = run_strategy(data, tf, symbol, strategy, fee_pct, slippage_pct)
            by_split = {}
            for name, (lo, hi) in bounds.items():
                if name == "out_of_sample" and not include_oos:
                    by_split[name] = {"locked": True}
                    continue
                by_split[name] = metrics([t for t in trades if lo <= t.entry_time < hi])
            tf_report["results"][strategy] = {"by_split": by_split, "seconds": round(time.time() - t0, 1),
                                              "trades": [asdict(t) for t in trades
                                                         if include_oos or t.entry_time < bounds["out_of_sample"][0]]}
            print(f"  {tf} {strategy:<12} done in {time.time() - t0:.0f}s", flush=True)
        report["timeframes"][tf] = tf_report
    return report


def format_report(report: dict) -> str:
    def ts(t):
        return time.strftime("%Y-%m-%d", time.gmtime(t / 1000 if t > 1e11 else t))

    lines = [f"SETUP BACKTEST -- {report['symbol']} (stage 2, paper research; costs {report['fee_pct_per_side']}% fee + "
             f"{report['slippage_pct_per_side']}% slippage per side)", ""]
    for tf, r in report["timeframes"].items():
        lines.append(f"=== {tf.upper()}  {r['bars']} bars  {ts(r['first_ts'])} -> {ts(r['last_ts'])}  "
                     f"data sha256 {r['data_sha256'][:12]} ===")
        for name, (lo, hi) in r["splits"].items():
            lines.append(f"  {name:<14} {ts(lo)} -> {ts(hi - 1)}")
        for split in [s for s, _ in SPLITS]:
            lines.append(f"  -- {split} --")
            lines.append(f"  {'strategy':<12} {'n':>4} {'open':>4} {'win%':>6} {'exp R':>7} {'gross R':>8} {'PF':>6} "
                         f"{'total R':>8} {'maxDD R':>8} {'L-strk':>6} {'cost R':>7}")
            for strategy, res in r["results"].items():
                m = res["by_split"][split]
                if m.get("locked"):
                    lines.append(f"  {strategy:<12} LOCKED (out-of-sample is reserved for stage 3)")
                    continue
                if not m.get("trades"):
                    lines.append(f"  {strategy:<12} {0:>4} {m.get('open', 0):>4}   no closed trades")
                    continue
                pf = f"{m['profit_factor']:.2f}" if m["profit_factor"] is not None else "  inf"
                lines.append(f"  {strategy:<12} {m['trades']:>4} {m['open']:>4} {m['win_rate'] * 100:>5.1f}% "
                             f"{m['expectancy_r']:>+7.3f} {m['gross_expectancy_r']:>+8.3f} {pf:>6} {m['total_r']:>+8.2f} "
                             f"{m['max_drawdown_r']:>8.2f} {m['max_losing_streak']:>6} {m['avg_cost_r']:>7.3f}")
        lines.append("")
    lines.append("R = multiples of the 1.5x ATR stop distance, after costs unless labelled gross. Small samples "
                 "(n < 30) are not evidence either way.")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--symbol", default="XRP/USD")
    p.add_argument("--bars-1h", type=int, default=8760)
    p.add_argument("--bars-4h", type=int, default=4380)
    p.add_argument("--refresh", action="store_true", help="re-download instead of using the frozen cache")
    p.add_argument("--include-oos", action="store_true", help="STAGE 3 ONLY: unlock the out-of-sample split")
    args = p.parse_args(argv)
    report = run(args.symbol, {"1h": args.bars_1h, "4h": args.bars_4h}, include_oos=args.include_oos,
                 refresh=args.refresh)
    text = format_report(report)
    print(text)
    out_dir = DATA_DIR.parent / "backtests"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M")
    (out_dir / f"setup_backtest_{args.symbol.replace('/', '')}_{stamp}.json").write_text(json.dumps(report, indent=1))
    (out_dir / f"setup_backtest_{args.symbol.replace('/', '')}_{stamp}.txt").write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
