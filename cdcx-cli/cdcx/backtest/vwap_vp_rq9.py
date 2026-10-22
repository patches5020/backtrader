"""
vwap_vp_rq9.py
----------------
RQ9 (DRAFT 2026-10-22, .ai/SHARED/research_questions.md) -- RESEARCH ONLY.
Not binding until the user freezes RQ9; nothing here may be run on the
confirmatory period before then.

Does the video's setup-1 filter (vp_first_touch: F1 prior close outside the
value area, F2 first touch of the POC zone today, F3 reaction volume above
the previous bar's) add information to VP-01 on 1H?

Same design as RQ5: the VP-01 BASELINE trades (vwap_vp_research.find_signals
VP-01 CONFIRMED fires, replayed unchanged) are split PASS / FAIL by the
filter, sampled at the signal bar from bars <= t only. Secondary: the
filtered strategy (PASS signals only) re-replayed. F1 / F2 / F3 alone are
descriptive. Trade model, costs and replay: vwap_vp_research, unchanged.

    python -m cdcx.backtest.vwap_vp_rq9 --fetch DIR --start YYYY-MM-DD --end YYYY-MM-DD
    python -m cdcx.backtest.vwap_vp_rq9 --data DIR --start YYYY-MM-DD --end YYYY-MM-DD
"""

from __future__ import annotations

import argparse
import json
import os
import random
from typing import Optional

from .. import no_trade_gate
from ..exchange.cryptocom import OHLCV
from ..volume_profile import vp_first_touch as ft
from ..volume_profile.prev_day import crypto_session, prev_day_levels
from . import vwap_vp_research as vr
from .vwap_vp_rq5 import _load, _save, bootstrap_diff_ci, bootstrap_mean_ci
from .vwap_vp_rq7 import LEAD_IN_DAYS, MIN_TRADES, _ts

SYMBOLS = ("XRP/USD", "XLM/USD")
TIMEFRAME = "1h"
SEED = 20261024
RESAMPLES = 10_000
CI_LEVEL = 0.975               # two intervals (PASS - FAIL, filtered strategy) -> alpha 0.05 / 2


def annotate(data: OHLCV, signals: list[tuple[int, str, str]],
             timeframe: str = TIMEFRAME) -> dict[int, Optional[ft.FirstTouch]]:
    """Filter result at each VP-01 signal bar, from the same bars find_signals saw at that bar. None when the
    filter's reaction disagrees with the signal's direction (counted, never silently re-labelled)."""
    tf_s = no_trade_gate.timeframe_to_seconds(timeframe)
    ts = [no_trade_gate.timestamp_to_seconds(t) for t in data.timestamps]
    out: dict[int, Optional[ft.FirstTouch]] = {}
    for t, setup, d in signals:
        now = ts[t] + tf_s
        floor = crypto_session(now)[0] - vr.STRUCTURE_BARS * tf_s
        lo = next((k for k in range(t + 1) if ts[k] >= floor), t)
        sub = vr._slice(data, lo, t + 1)
        lv = prev_day_levels(sub, timeframe, now=now)
        r = ft.evaluate(lv, sub) if lv.status == "OK" else None
        out[t] = r if r is not None and r.direction == d else None
    return out


def _period(data: OHLCV, sigs, start: float, end: float):
    return [s for s in sigs if start <= no_trade_gate.timestamp_to_seconds(data.timestamps[s[0]]) < end]


def run_symbol(symbol: str, data: OHLCV, start: float, end: float) -> dict:
    base = _period(data, [s for s in vr.find_signals(data, TIMEFRAME) if s[1] == "VP-01"], start, end)
    notes = annotate(data, base)
    trades = vr.replay(data, base, symbol)
    passed = [s for s in base if notes.get(s[0]) is not None and notes[s[0]].passed]
    filtered = vr.replay(data, [(t, "VP-01F", d) for t, _, d in passed], symbol)
    return {"symbol": symbol, "trades": trades, "notes": notes, "filtered": filtered,
            "mismatch": sum(1 for s in base if notes.get(s[0]) is None)}


def _split(per_symbol: list[dict], key) -> tuple[list[float], list[float]]:
    yes, no = [], []
    for r in per_symbol:
        for tr in r["trades"]:
            n = r["notes"].get(tr.signal_index)
            if n is None:
                continue
            (yes if key(n) else no).append(tr.net_r)
    return yes, no


def summarize(per_symbol: list[dict]) -> dict:
    rng = random.Random(SEED)
    out: dict = {"mismatch": sum(r["mismatch"] for r in per_symbol)}
    base = [tr for r in per_symbol for tr in r["trades"]]
    out["baseline"] = vr.stats(base).__dict__
    p, f = _split(per_symbol, lambda n: n.passed)
    out["pass"] = {"n": len(p), "avg_net_r": sum(p) / len(p) if p else None}
    out["fail"] = {"n": len(f), "avg_net_r": sum(f) / len(f) if f else None}
    out["diff_ci"] = bootstrap_diff_ci(p, f, CI_LEVEL, RESAMPLES, rng)
    filt = [tr for r in per_symbol for tr in r["filtered"]]
    out["filtered"] = vr.stats(filt).__dict__
    out["filtered"]["ci"] = bootstrap_mean_ci([tr.net_r for tr in filt], CI_LEVEL, RESAMPLES, rng)
    out["components"] = {}
    for name in ("f1", "f2", "f3"):
        y, n = _split(per_symbol, lambda x, a=name: getattr(x, a))
        out["components"][name] = {"pass_n": len(y), "pass_r": sum(y) / len(y) if y else None,
                                   "fail_n": len(n), "fail_r": sum(n) / len(n) if n else None}
    out["verdict"] = verdict(len(p), len(f), out["diff_ci"], len(filt), out["filtered"]["ci"])
    return out


def verdict(n_pass: int, n_fail: int, ci_diff, n_filt: int, ci_filt) -> dict:
    """RQ5's rule: the filter "adds information" only if PASS - FAIL's lower bound > 0 (>= MIN_TRADES in each
    group); it is worth proposing as an advisory line only if, in addition, the filtered strategy's lower
    bound > 0 (>= MIN_TRADES trades)."""
    if min(n_pass, n_fail) < MIN_TRADES or ci_diff[0] is None:
        info = f"insufficient sample (PASS {n_pass}, FAIL {n_fail}, need {MIN_TRADES} each)"
    else:
        info = "the filter adds information" if ci_diff[0] > 0 else "no evidence (interval includes or is below 0)"
    propose = (info == "the filter adds information" and n_filt >= MIN_TRADES
               and ci_filt[0] is not None and ci_filt[0] > 0)
    return {"information": info, "worth_proposing": propose}


def format_report(s: dict, hashes: dict, start: str, end: str) -> str:
    f = lambda x: f"{x:+.3f}" if x is not None else "n/a"
    ci = lambda c: f"[{c[0]:+.3f}, {c[1]:+.3f}]" if c[0] is not None else "n/a"
    lines = [f"RQ9 -- VP-01 first-touch filter, {TIMEFRAME}, {start} -> {end} (research only)",
             "data: " + ", ".join(f"{k} sha256 {v[:12]}..." for k, v in hashes.items()),
             f"VP-01 baseline: trades {s['baseline']['trades']}, net {f(s['baseline']['avg_net_r'])} R "
             f"(filter/direction mismatches excluded from the split: {s['mismatch']})",
             f"PASS {s['pass']['n']} trades {f(s['pass']['avg_net_r'])} R | FAIL {s['fail']['n']} trades "
             f"{f(s['fail']['avg_net_r'])} R | PASS - FAIL {CI_LEVEL:.1%} CI {ci(s['diff_ci'])}",
             f"Filtered strategy: trades {s['filtered']['trades']}, net {f(s['filtered']['avg_net_r'])} R, "
             f"CI {ci(s['filtered']['ci'])}, maxDD {s['filtered']['max_drawdown_r']:.1f} R"]
    for k, c in s["components"].items():
        lines.append(f"  {k.upper()} alone (descriptive): pass {c['pass_n']} {f(c['pass_r'])} R / "
                     f"fail {c['fail_n']} {f(c['fail_r'])} R")
    lines.append(f"Verdict: {s['verdict']['information']}; worth proposing: {'YES' if s['verdict']['worth_proposing'] else 'no'}")
    return "\n".join(lines)


def _file(dirpath: str, symbol: str) -> str:
    return os.path.join(dirpath, f"rq9_{symbol.split('/')[0].lower()}_1h.json")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="RQ9: VP-01 first-touch filter on 1H (research only)")
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
