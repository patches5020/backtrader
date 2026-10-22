"""
vwap_vp_rq8.py
----------------
RQ8 (DRAFT 2026-10-22, .ai/SHARED/research_questions.md) -- RESEARCH ONLY.
Not binding until the user freezes RQ8; nothing here may be run on the
confirmatory period before then.

Does VP-04P breakout -> pullback hold -> BOS (vp_breakout_pullback.py) have
a positive expectancy after costs on 1H, and is it better than the current
VP-04 (an accepted value-area breakout, RQ3)?

    VP-04P  the sequence, DEFAULT parameters            (the hypothesis)
    VP-04   vwap_vp_research.find_signals' VP-04 fires  (comparator, unchanged)

Walk-forward like vwap_vp_research.find_signals: at the close of bar t the
previous-day levels are rebuilt from bars <= t only; VP-04P fires on the bar
whose state is PENDING (the BOS close). Replay, trade model (1.5 x ATR stop,
TP1-4 2.2/2.6/3.2/4.5 R, 25% each), costs and one-open-trade-per-setup are
vwap_vp_research.replay, unchanged. SENSITIVITY re-runs VP-04P with each
parameter moved one at a time -- descriptive only, never a verdict.

    python -m cdcx.backtest.vwap_vp_rq8 --fetch DIR --start YYYY-MM-DD --end YYYY-MM-DD
    python -m cdcx.backtest.vwap_vp_rq8 --data DIR --start YYYY-MM-DD --end YYYY-MM-DD
"""

from __future__ import annotations

import argparse
import json
import os
import random
from dataclasses import replace
from typing import Optional

from .. import no_trade_gate
from ..exchange.cryptocom import OHLCV
from ..volume_profile import vp_breakout_pullback as bp
from ..volume_profile.prev_day import crypto_session, prev_day_levels
from . import vwap_vp_research as vr
from .vwap_vp_rq5 import _load, _save, bootstrap_diff_ci, bootstrap_mean_ci
from .vwap_vp_rq7 import LEAD_IN_DAYS, MIN_TRADES, _ts

SYMBOLS = ("XRP/USD", "XLM/USD")
TIMEFRAME = "1h"
SEED = 20261023
RESAMPLES = 10_000
CI_LEVEL = 0.975               # two tests (primary + vs VP-04) -> alpha 0.05 / 2
SENSITIVITY = {                # one parameter at a time, the rest DEFAULT
    "effort_high": (1.2, 2.0), "result_big": (0.8, 1.2), "touch_atr": (0.10, 0.50),
    "hold_wick_atr": (0.25, 0.75), "bos_atr": (0.0, 0.5), "max_bars": (8, 24),
}


def find_signals(data: OHLCV, timeframe: str = TIMEFRAME, p: bp.Params = bp.DEFAULT,
                 start_index: int = 0) -> list[tuple[int, str, str]]:
    """Walk-forward VP-04P fires -- bars <= t only at each t."""
    tf_s = no_trade_gate.timeframe_to_seconds(timeframe)
    ts = [no_trade_gate.timestamp_to_seconds(t) for t in data.timestamps]
    out: list[tuple[int, str, str]] = []
    lo = 0
    for t in range(start_index, len(ts)):
        now = ts[t] + tf_s
        sess_start = crypto_session(now)[0]
        while lo < t and ts[lo] < sess_start - vr.STRUCTURE_BARS * tf_s:
            lo += 1
        sub = vr._slice(data, lo, t + 1)
        lv = prev_day_levels(sub, timeframe, now=now)
        if lv.status != "OK":
            continue
        row, ep, fired = bp.evaluate(lv, sub, p)
        if fired and row.direction:
            out.append((t, "VP-04P", row.direction))
    return out


def _period(data: OHLCV, sigs, start: float, end: float):
    return [s for s in sigs if start <= no_trade_gate.timestamp_to_seconds(data.timestamps[s[0]]) < end]


def run_symbol(symbol: str, data: OHLCV, start: float, end: float, sensitivity: bool = True) -> dict:
    p_sigs = _period(data, find_signals(data), start, end)
    b_sigs = _period(data, [s for s in vr.find_signals(data, TIMEFRAME) if s[1] == "VP-04"], start, end)
    out = {"symbol": symbol, "trades": vr.replay(data, p_sigs + b_sigs, symbol), "sensitivity": {}}
    if sensitivity:
        for name, values in SENSITIVITY.items():
            for val in values:
                sigs = _period(data, find_signals(data, p=replace(bp.DEFAULT, **{name: val})), start, end)
                out["sensitivity"][f"{name}={val}"] = vr.replay(data, sigs, symbol)
    return out


def summarize(per_symbol: list[dict]) -> dict:
    rng = random.Random(SEED)
    out: dict = {"pooled": {}, "per_symbol": {}, "sensitivity": {}}
    groups = {}
    for setup in ("VP-04P", "VP-04"):
        groups[setup] = [tr for r in per_symbol for tr in r["trades"] if tr.setup == setup]
        st = vr.stats(groups[setup]).__dict__
        st["ci"] = bootstrap_mean_ci([tr.net_r for tr in groups[setup]], CI_LEVEL, RESAMPLES, rng)
        out["pooled"][setup] = st
        for r in per_symbol:
            out["per_symbol"].setdefault(r["symbol"], {})[setup] = vr.stats(
                [tr for tr in r["trades"] if tr.setup == setup]).__dict__
    a = [tr.net_r for tr in groups["VP-04P"]]
    b = [tr.net_r for tr in groups["VP-04"]]
    out["diff_ci"] = bootstrap_diff_ci(a, b, CI_LEVEL, RESAMPLES, rng)
    keys = per_symbol[0]["sensitivity"].keys() if per_symbol else []
    for k in keys:
        out["sensitivity"][k] = vr.stats([tr for r in per_symbol for tr in r["sensitivity"][k]]).__dict__
    out["verdict"] = verdict(len(a), out["pooled"]["VP-04P"]["ci"], len(b), out["diff_ci"])
    return out


def verdict(n_a: int, ci_a, n_b: int, ci_diff) -> dict:
    def one(n, ci, yes, what):
        if n < MIN_TRADES or ci[0] is None:
            return f"insufficient sample ({what} = {n}, need {MIN_TRADES})"
        return yes if ci[0] > 0 else "no evidence (interval includes or is below 0)"
    return {"primary": one(n_a, ci_a, "positive expectancy after costs (advisory; needs separate approval)",
                           "VP-04P trades"),
            "vs_vp04": one(min(n_a, n_b), ci_diff, "the sequence beats the current VP-04", "smaller group")}


def format_report(s: dict, hashes: dict, start: str, end: str) -> str:
    lines = [f"RQ8 -- VP-04P breakout -> pullback -> BOS vs VP-04, {TIMEFRAME}, {start} -> {end} (research only)",
             "data: " + ", ".join(f"{k} sha256 {v[:12]}..." for k, v in hashes.items())]
    for setup, st in s["pooled"].items():
        lo, hi = st["ci"]
        ci = f"[{lo:+.3f}, {hi:+.3f}]" if lo is not None else "n/a"
        lines.append(f"{setup:<7} trades {st['trades']:>4}  net {st['avg_net_r']:+.3f} R  {CI_LEVEL:.1%} CI {ci}  "
                     f"win {st['win_rate']:.0%}  maxDD {st['max_drawdown_r']:.1f} R")
    lo, hi = s["diff_ci"]
    lines.append("VP-04P - VP-04: " + (f"[{lo:+.3f}, {hi:+.3f}]" if lo is not None else "n/a"))
    lines.append(f"Primary: {s['verdict']['primary']}")
    lines.append(f"vs VP-04: {s['verdict']['vs_vp04']}")
    if s["sensitivity"]:
        lines.append("Sensitivity (descriptive only, one parameter moved):")
        for k, st in s["sensitivity"].items():
            lines.append(f"  {k:<20} trades {st['trades']:>4}  net {st['avg_net_r']:+.3f} R")
    return "\n".join(lines)


def _file(dirpath: str, symbol: str) -> str:
    return os.path.join(dirpath, f"rq8_{symbol.split('/')[0].lower()}_1h.json")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="RQ8: VP-04P breakout -> pullback -> BOS on 1H (research only)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--fetch", metavar="DIR", help="fetch the 1H series once and save it with its SHA-256")
    g.add_argument("--data", metavar="DIR", help="run on the saved series only")
    ap.add_argument("--start", required=True, help="period start, YYYY-MM-DD (UTC)")
    ap.add_argument("--end", required=True, help="period end (exclusive), YYYY-MM-DD (UTC)")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    start, end = _ts(a.start), _ts(a.end)
    if a.fetch:
        import time
        from ..exchange.cryptocom import CryptoComExchange
        ex, now = CryptoComExchange(), time.time()
        for sym in SYMBOLS:
            d = ex.fetch_ohlcv(sym, TIMEFRAME, int((now - start) / 3600) + LEAD_IN_DAYS * 24)
            if no_trade_gate.last_bar_is_forming(d.timestamps, TIMEFRAME, now):
                d = vr._slice(d, 0, len(d.timestamps) - 1)
            print(f"{sym}: {len(d.timestamps)} bars, sha256 {_save(_file(a.fetch, sym), d)}")
        return 0
    per, hashes = [], {}
    for sym in SYMBOLS:
        d, h = _load(_file(a.data, sym))
        hashes[sym] = h
        per.append(run_symbol(sym, d, start, end))
    s = summarize(per)
    print(format_report(s, hashes, a.start, a.end))
    if a.out:
        with open(a.out, "w") as fh:
            json.dump({"hashes": hashes, "start": a.start, "end": a.end, "summary": s}, fh, indent=1, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
