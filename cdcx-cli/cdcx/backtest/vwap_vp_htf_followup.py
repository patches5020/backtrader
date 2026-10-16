"""
vwap_vp_htf_followup.py
-------------------------
Follow-up to the Phase 5 research (2026-10-16). RESEARCH ONLY.

Hypothesis, written down before any run (the user approved this test after
Phase 5's results, so it is chosen with hindsight and must be judged on data
Phase 5 never looked at):

    VP-04 (prior-day value-area breakout ACCEPTED) on 1H bars, taken ONLY
    when cdcx's own 2-of-4 higher-timeframe confluence (1H/4H/1D/1W,
    transitional timeframes excluded -- vwap_confluence.htf_direction, the
    --execute filter) points the same way at the signal bar.

    Reference: the same VP-04 1H signals without the filter.

Periods: FRESH = 2025-06-01 -> 2026-05-30 (before anything Phase 5 used) is
the test; SEEN = 2026-05-30 onward is reported separately and doesn't count.

Higher-timeframe replay: at each signal bar's close, every timeframe gets its
last LIMIT CLOSED bars at that moment (no forming bar -- slightly stricter
than a live run, which includes the forming candle) and is analysed with
engine.analyze_ohlcv exactly as cdcx-ai does (higher_timeframes_aligned=False).

Trade model, costs and statistics: identical to vwap_vp_research (protected
1.5x ATR stop, 2.2/2.6/3.2/4.5 R ladder, rules G/H/I, 7.5 + 2 bps per side).

    python -m cdcx.backtest.vwap_vp_htf_followup --symbol XRP/USD
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional

from .. import engine, no_trade_gate
from ..exchange.cryptocom import OHLCV
from ..volume_profile.vwap_confluence import htf_direction
from . import vwap_vp_research as vr

LIMIT = 200
FRESH_START = datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp()
SEEN_START = datetime(2026, 5, 30, tzinfo=timezone.utc).timestamp()
HTF = ["1h", "4h", "1d", "1w"]


def _closed_upto(data: OHLCV, tf: str, now: float, limit: int = LIMIT) -> Optional[OHLCV]:
    tf_s = no_trade_gate.timeframe_to_seconds(tf)
    ts = [no_trade_gate.timestamp_to_seconds(t) for t in data.timestamps]
    hi = 0
    while hi < len(ts) and ts[hi] + tf_s <= now:
        hi += 1
    if hi < limit:
        return None   # not enough closed history at that moment
    return vr._slice(data, hi - limit, hi)


def htf_at(symbol: str, frames: dict[str, OHLCV], now: float) -> tuple[str, str]:
    results = {}
    for tf in HTF:
        sub = _closed_upto(frames[tf], tf, now)
        if sub is None:
            return "unknown", f"{tf} history too short"
        results[tf] = engine.analyze_ohlcv(symbol, sub, timeframe=tf)
    return htf_direction(results)


def run(symbol: str, frames: dict[str, OHLCV]) -> dict:
    d1h = frames["1h"]
    ts = [no_trade_gate.timestamp_to_seconds(t) for t in d1h.timestamps]
    start = next(i for i, t in enumerate(ts) if t >= FRESH_START - 3 * 86400)   # small warm-up before FRESH
    signals = [s for s in vr.find_signals(d1h, "1h", start_index=start) if s[1] == "VP-04"
               and ts[s[0]] >= FRESH_START]
    filtered, htf_log = [], []
    for t, setup, direction in signals:
        htf, label = htf_at(symbol, frames, ts[t] + 3600)
        htf_log.append({"t": ts[t], "direction": direction, "htf": htf, "label": label})
        if htf == direction:
            filtered.append((t, "VP04+HTF", direction))
    trades = vr.replay(d1h, [(t, "VP04", d) for t, _, d in signals] + filtered, symbol)
    out = {"symbol": symbol, "signals": len(signals), "passed_htf": len(filtered), "table": {}, "htf_log": htf_log,
           "trades": [asdict(t) for t in trades]}
    for name in ("VP04", "VP04+HTF"):
        mine = [t for t in trades if t.setup == name]
        out["table"][name] = {
            "fresh": asdict(vr.stats([t for t in mine if t.signal_ts < SEEN_START])),
            "seen": asdict(vr.stats([t for t in mine if t.signal_ts >= SEEN_START])),
        }
    return out


def format_report(r: dict) -> str:
    lines = [f"VP-04 1H + cdcx HTF filter -- {r['symbol']} | {r['signals']} VP-04 signals since 2025-06-01, "
             f"{r['passed_htf']} with HTF agreeing | research only",
             f"FRESH = 2025-06-01 -> 2026-05-30 (the test) | SEEN = 2026-05-30 -> now (reference only)", "",
             f"{'Variant':<10}{'Period':<7}{'Trades':>7}{'Win%':>7}{'GrossR':>8}{'CostR':>7}{'NetR':>8}{'TotalR':>9}"
             f"{'PF':>7}{'MaxDD R':>9}"]
    for name, row in r["table"].items():
        for period in ("fresh", "seen"):
            s = row[period]
            pf = "-" if s["profit_factor"] is None else f"{s['profit_factor']:.2f}"
            lines.append(f"{name:<10}{period:<7}{s['trades']:>7}{s['win_rate'] * 100:>6.0f}%{s['avg_gross_r']:>8.3f}"
                         f"{s['avg_cost_r']:>7.3f}{s['avg_net_r']:>8.3f}{s['total_net_r']:>9.2f}{pf:>7}"
                         f"{s['max_drawdown_r']:>9.2f}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="VP-04 1H + cdcx HTF filter follow-up (research only)")
    ap.add_argument("--symbol", default="XRP/USD")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    from ..exchange.cryptocom import CryptoComExchange

    t0 = time.time()
    ex = CryptoComExchange()
    now = time.time()
    need = {tf: int((now - FRESH_START) / no_trade_gate.timeframe_to_seconds(tf)) + LIMIT + 80 for tf in HTF}
    frames = {}
    for tf in HTF:
        d = ex.fetch_ohlcv(args.symbol, tf, need[tf])
        if no_trade_gate.last_bar_is_forming(d.timestamps, tf, now):
            d = vr._slice(d, 0, len(d.timestamps) - 1)
        frames[tf] = d
    first = {tf: datetime.fromtimestamp(no_trade_gate.timestamp_to_seconds(f.timestamps[0]), timezone.utc)
             .strftime("%Y-%m-%d") for tf, f in frames.items()}
    r = run(args.symbol, frames)
    r["first_bars"] = first
    print(format_report(r))
    print(f"\nhistory starts {first}; {time.time() - t0:.0f}s")
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(r, fh, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
