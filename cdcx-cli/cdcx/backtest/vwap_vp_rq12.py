"""
vwap_vp_rq12.py
-----------------
RQ12 (DRAFT 2026-10-22, .ai/SHARED/research_questions.md) -- RESEARCH ONLY.
Not binding until the user freezes RQ12; nothing here may be run on the
confirmatory period before then.

Do VP-04 (and VP-01) signals do better on vwap-vp-3 levels (prev_day_v3:
the same frozen session from 1m bars at 400 rows, which matches TradingView's
Fixed Range VP) than on vwap-vp-1 levels (1h / 24 rows)? Same design as RQ11
(vwap_vp_rq11.py, frozen, not imported for its signal logic), with 1m bars
in place of 5m.

Signals: classify() UNCHANGED, run on the vwap-vp-1 PrevDayLevels with only
POC / VAH / VAL replaced by vwap-vp-3's (HVN / LVN only affect VP-05 text).
A session whose 1m bars are incomplete gives no vwap-vp-3 signals (counted).
Walk-forward, replay, protected trade model and costs: vwap_vp_research,
unchanged. Comparator: vwap_vp_research.find_signals on vwap-vp-1.

    python -m cdcx.backtest.vwap_vp_rq12 --fetch DIR --start YYYY-MM-DD --end YYYY-MM-DD
    python -m cdcx.backtest.vwap_vp_rq12 --data DIR --start YYYY-MM-DD --end YYYY-MM-DD
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
from ..volume_profile.prev_day import crypto_session, prev_day_levels
from ..volume_profile.prev_day_v3 import levels_v3
from ..volume_profile.vwap_confluence import classify
from . import vwap_vp_research as vr
from .vwap_vp_rq5 import _load, _save, bootstrap_diff_ci, bootstrap_mean_ci
from .vwap_vp_rq7 import LEAD_IN_DAYS, MIN_TRADES, _ts

SYMBOLS = ("XRP/USD", "XLM/USD")
SEED = 20261026
RESAMPLES = 10_000
CI_LEVEL = 0.975               # two tests (VP-04 v3, VP-04 v3 - v1) -> alpha 0.05 / 2
TRIGGERS = {"VP-01": "CONFIRMED", "VP-04": "ACCEPTED"}


def find_signals_v3(h1: OHLCV, m1: OHLCV) -> tuple[list[tuple[int, str, str]], int]:
    """Walk-forward VP-01 / VP-04 fires on vwap-vp-3 levels, bars <= t only. Returns (signals, sessions skipped
    because their 1m bars were incomplete). Mirrors vwap_vp_research.find_signals' windowing and state logic."""
    tf_s = 3600
    ts = [no_trade_gate.timestamp_to_seconds(t) for t in h1.timestamps]
    signals: list[tuple[int, str, str]] = []
    prev: dict[str, str] = {}
    cache: dict = {}
    lo = 0
    for t in range(len(ts)):
        now = ts[t] + tf_s
        sess_start = crypto_session(now)[0]
        while lo < t and ts[lo] < sess_start - vr.STRUCTURE_BARS * tf_s:
            lo += 1
        sub = vr._slice(h1, lo, t + 1)
        lv = prev_day_levels(sub, "1h", now=now)
        if lv.status != "OK":
            prev = {}
            continue
        if lv.session_start not in cache:
            cache[lv.session_start] = levels_v3(m1, lv.session_start, lv.session_end)
        v3 = cache[lv.session_start]
        if v3.status != "OK":
            prev = {}
            continue
        res = classify(replace(lv, poc=v3.poc, vah=v3.vah, val=v3.val), sub)
        if res.status != "OK":
            prev = {}
            continue
        for s in res.setups:
            trig = TRIGGERS.get(s.code)
            if trig and s.state == trig and s.direction and prev.get(s.code) != f"{trig}:{s.direction}":
                signals.append((t, s.code, s.direction))
            prev[s.code] = f"{s.state}:{s.direction}"
    skipped = sum(1 for v in cache.values() if v.status != "OK")
    return signals, skipped


def _period(data: OHLCV, sigs, start: float, end: float):
    return [s for s in sigs if start <= no_trade_gate.timestamp_to_seconds(data.timestamps[s[0]]) < end]


def run_symbol(symbol: str, h1: OHLCV, m1: OHLCV, start: float, end: float) -> dict:
    v3, skipped = find_signals_v3(h1, m1)
    v3 = [(t, f"{c}v3", d) for t, c, d in _period(h1, v3, start, end)]
    v1 = [(t, f"{c}v1", d) for t, c, d in _period(h1, vr.find_signals(h1, "1h"), start, end) if c in TRIGGERS]
    return {"symbol": symbol, "trades": vr.replay(h1, v1 + v3, symbol), "skipped_sessions": skipped}


def summarize(per_symbol: list[dict]) -> dict:
    rng = random.Random(SEED)
    out: dict = {"pooled": {}, "per_symbol": {}, "skipped_sessions": sum(r["skipped_sessions"] for r in per_symbol)}
    g = {}
    for k in ("VP-04v3", "VP-04v1", "VP-01v3", "VP-01v1"):   # this order fixes the generator's draws
        g[k] = [tr.net_r for r in per_symbol for tr in r["trades"] if tr.setup == k]
        st = vr.stats([tr for r in per_symbol for tr in r["trades"] if tr.setup == k]).__dict__
        st["ci"] = bootstrap_mean_ci(g[k], CI_LEVEL, RESAMPLES, rng)
        out["pooled"][k] = st
        for r in per_symbol:
            out["per_symbol"].setdefault(r["symbol"], {})[k] = vr.stats(
                [tr for tr in r["trades"] if tr.setup == k]).__dict__
    out["diff_vp04"] = bootstrap_diff_ci(g["VP-04v3"], g["VP-04v1"], CI_LEVEL, RESAMPLES, rng)
    out["diff_vp01"] = bootstrap_diff_ci(g["VP-01v3"], g["VP-01v1"], CI_LEVEL, RESAMPLES, rng)
    out["verdict"] = verdict(len(g["VP-04v3"]), out["pooled"]["VP-04v3"]["ci"],
                             min(len(g["VP-04v3"]), len(g["VP-04v1"])), out["diff_vp04"])
    return out


def verdict(n_v3: int, ci_v3, n_pair: int, ci_diff) -> dict:
    def one(n, ci, yes, what):
        if n < MIN_TRADES or ci[0] is None:
            return f"insufficient sample ({what} = {n}, need {MIN_TRADES})"
        return yes if ci[0] > 0 else "no evidence (interval includes or is below 0)"
    return {"primary": one(n_v3, ci_v3, "VP-04 on vwap-vp-3 has positive expectancy after costs", "VP-04v3 trades"),
            "vs_v1": one(n_pair, ci_diff, "vwap-vp-3 VP-04 beats vwap-vp-1 VP-04", "smaller group")}


def format_report(s: dict, hashes: dict, start: str, end: str) -> str:
    ci = lambda c: f"[{c[0]:+.3f}, {c[1]:+.3f}]" if c[0] is not None else "n/a"
    lines = [f"RQ12 -- vwap-vp-3 (1m @ 400 rows) vs vwap-vp-1 (1h @ 24) levels, 1h, {start} -> {end} (research only)",
             "data: " + ", ".join(f"{k} sha256 {v[:12]}..." for k, v in hashes.items()),
             f"sessions skipped for incomplete 1m bars: {s['skipped_sessions']}"]
    for k, st in s["pooled"].items():
        lines.append(f"{k:<8} trades {st['trades']:>4}  net {st['avg_net_r']:+.3f} R  {CI_LEVEL:.1%} CI {ci(st['ci'])}  "
                     f"win {st['win_rate']:.0%}  maxDD {st['max_drawdown_r']:.1f} R")
    lines.append(f"VP-04 v3 - v1: {ci(s['diff_vp04'])}   VP-01 v3 - v1 (descriptive): {ci(s['diff_vp01'])}")
    lines.append(f"Primary: {s['verdict']['primary']}")
    lines.append(f"vs vwap-vp-1: {s['verdict']['vs_v1']}")
    return "\n".join(lines)


def _file(dirpath: str, symbol: str, tf: str) -> str:
    return os.path.join(dirpath, f"rq12_{symbol.split('/')[0].lower()}_{tf}.json")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="RQ12: vwap-vp-3 vs vwap-vp-1 levels for VP-04 / VP-01 (research only)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--fetch", metavar="DIR", help="fetch the 1h and 1m series once and save them with SHA-256")
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
            for tf, per_hour in (("1h", 1), ("1m", 60)):
                d = ex.fetch_ohlcv(sym, tf, (int((now - start) / 3600) + LEAD_IN_DAYS * 24) * per_hour)
                if no_trade_gate.last_bar_is_forming(d.timestamps, tf, now):
                    d = vr._slice(d, 0, len(d.timestamps) - 1)
                print(f"{sym} {tf}: {len(d.timestamps)} bars, sha256 {_save(_file(a.fetch, sym, tf), d)}")
        return 0
    per, hashes = [], {}
    for sym in SYMBOLS:
        h1, hh = _load(_file(a.data, sym, "1h"))
        m1, hm = _load(_file(a.data, sym, "1m"))
        hashes[f"{sym} 1h"], hashes[f"{sym} 1m"] = hh, hm
        per.append(run_symbol(sym, h1, m1, start, end))
    s = summarize(per)
    print(format_report(s, hashes, a.start, a.end))
    if a.out:
        with open(a.out, "w") as fh:
            json.dump({"hashes": hashes, "start": a.start, "end": a.end, "summary": s}, fh, indent=1, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
