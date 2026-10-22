"""
vwap_vp_rq7.py
----------------
RQ7 (DRAFT 2026-10-22, .ai/SHARED/research_questions.md) -- RESEARCH ONLY.
Not binding until the user freezes RQ7; nothing here may be run on the
confirmatory period before then.

Does VP-06 value-area re-entry (cdcx/volume_profile/vp_reentry.py) have a
positive expectancy after costs on 1H, and does its precondition (prior
session closed INSIDE the value area) add information?

    VP-06   re-entry with the precondition met        (the hypothesis)
    VP-06x  the same re-entry with the prior close OUTSIDE (comparator)

Walk-forward exactly like vwap_vp_research.find_signals: at the close of bar
t the previous-day levels are rebuilt from bars <= t only; a signal fires on
the bar whose VP-06 state is PENDING (the re-entry close). Replay, trade
model (1.5 x ATR stop, TP1-4 2.2/2.6/3.2/4.5 R, 25% each), costs and
one-open-trade-per-setup are vwap_vp_research.replay, unchanged. The video's
far-edge target is reported descriptively only (far_edge_outcome).

    python -m cdcx.backtest.vwap_vp_rq7 --fetch DIR --start 2025-06-01 --end 2026-05-31
    python -m cdcx.backtest.vwap_vp_rq7 --data DIR --start 2025-06-01 --end 2026-05-31
"""

from __future__ import annotations

import argparse
import json
import os
import random
from datetime import datetime, timezone
from typing import Optional

from .. import no_trade_gate
from ..exchange.cryptocom import OHLCV
from ..volume_profile.prev_day import crypto_session, prev_day_levels
from ..volume_profile.vp_reentry import evaluate
from . import vwap_vp_research as vr
from .vwap_vp_rq5 import _load, _save, bootstrap_diff_ci, bootstrap_mean_ci

SYMBOLS = ("XRP/USD", "XLM/USD")
TIMEFRAME = "1h"
SEED = 20261022
RESAMPLES = 10_000
CI_LEVEL = 0.975               # two tests (primary + precondition) -> alpha 0.05 / 2
MIN_TRADES = 30
FAR_EDGE_HORIZON = 24          # bars -- descriptive far-edge outcome only
LEAD_IN_DAYS = 60              # history fetched before --start (ATR / structure warm-up)

Signal = tuple[int, str, str, float, float]   # (bar index, "VP-06"|"VP-06x", direction, target, extreme)


def find_reentry_signals(data: OHLCV, timeframe: str = TIMEFRAME, start_index: int = 0) -> list[Signal]:
    """Walk-forward VP-06 / VP-06x fires -- bars <= t only at each t."""
    tf_s = no_trade_gate.timeframe_to_seconds(timeframe)
    ts = [no_trade_gate.timestamp_to_seconds(t) for t in data.timestamps]
    out: list[Signal] = []
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
        e = evaluate(lv, sub, require_inside_prior=False)
        if e.setup.state == "PENDING" and e.setup.direction:
            out.append((t, "VP-06" if e.prior_inside else "VP-06x", e.setup.direction, e.target, e.extreme))
    return out


def far_edge_outcome(data: OHLCV, sig: Signal, horizon: int = FAR_EDGE_HORIZON) -> Optional[dict]:
    """The video's trade, descriptive only: entry next open, target the far edge, stop at the excursion
    extreme. A bar touching both counts as the stop. Not reached within `horizon` bars -> marked at the
    close. None when the next open is already beyond the target or the stop (no trade)."""
    t, _, d, target, extreme = sig
    if t + 1 >= len(data.closes):
        return None
    bull = d == "bullish"
    entry = data.opens[t + 1]
    risk = (entry - extreme) if bull else (extreme - entry)
    reward = (target - entry) if bull else (entry - target)
    if risk <= 0 or reward <= 0:
        return None
    end = min(t + horizon, len(data.closes) - 1)
    for k in range(t + 1, end + 1):
        hi, lo = data.highs[k], data.lows[k]
        if (lo <= extreme) if bull else (hi >= extreme):
            return {"result": "stop", "r": -1.0, "bars": k - t}
        if (hi >= target) if bull else (lo <= target):
            return {"result": "target", "r": round(reward / risk, 4), "bars": k - t}
    move = (data.closes[end] - entry) if bull else (entry - data.closes[end])
    return {"result": "horizon", "r": round(move / risk, 4), "bars": end - t}


def _in_period(data: OHLCV, t: int, start: float, end: float) -> bool:
    return start <= no_trade_gate.timestamp_to_seconds(data.timestamps[t]) < end


def run_symbol(symbol: str, data: OHLCV, start: float, end: float) -> dict:
    sigs = [s for s in find_reentry_signals(data) if _in_period(data, s[0], start, end)]
    trades = vr.replay(data, [(t, name, d) for t, name, d, _, _ in sigs], symbol)
    far = [dict(far_edge_outcome(data, s) or {"result": "no trade"}, setup=s[1]) for s in sigs]
    return {"symbol": symbol, "signals": sigs, "trades": trades, "far_edge": far}


def summarize(per_symbol: list[dict]) -> dict:
    rng = random.Random(SEED)
    out: dict = {"per_symbol": {}, "pooled": {}}
    for setup in ("VP-06", "VP-06x"):
        pooled = [tr for r in per_symbol for tr in r["trades"] if tr.setup == setup]
        for r in per_symbol:
            out["per_symbol"].setdefault(r["symbol"], {})[setup] = vr.stats(
                [tr for tr in r["trades"] if tr.setup == setup]).__dict__
        st = vr.stats(pooled).__dict__
        st["ci"] = bootstrap_mean_ci([tr.net_r for tr in pooled], CI_LEVEL, RESAMPLES, rng)
        fe = [f for r in per_symbol for f in r["far_edge"] if f["setup"] == setup and "r" in f]
        st["far_edge"] = {"n": len(fe), "target_rate": (sum(f["result"] == "target" for f in fe) / len(fe)) if fe else None,
                          "avg_gross_r": (sum(f["r"] for f in fe) / len(fe)) if fe else None}
        out["pooled"][setup] = st
    a = [tr.net_r for r in per_symbol for tr in r["trades"] if tr.setup == "VP-06"]
    b = [tr.net_r for r in per_symbol for tr in r["trades"] if tr.setup == "VP-06x"]
    out["diff_ci"] = bootstrap_diff_ci(a, b, CI_LEVEL, RESAMPLES, rng)
    out["verdict"] = verdict(len(a), out["pooled"]["VP-06"]["ci"], len(b), out["diff_ci"])
    return out


def verdict(n_a: int, ci_a, n_b: int, ci_diff) -> dict:
    """The draft decision rule: a lower bound above 0, with >= MIN_TRADES trades; anything else is no /
    inconclusive. A positive result authorizes nothing by itself."""
    def one(n, ci, yes, label_n):
        if n < MIN_TRADES or ci[0] is None:
            return f"insufficient sample ({label_n} = {n}, need {MIN_TRADES})"
        return yes if ci[0] > 0 else "no evidence (interval includes or is below 0)"
    return {"primary": one(n_a, ci_a, "positive expectancy after costs (advisory; needs separate approval)", "VP-06 trades"),
            "precondition": one(min(n_a, n_b), ci_diff, "the precondition adds information", "smaller group")}


def format_report(s: dict, hashes: dict, start: str, end: str) -> str:
    lines = [f"RQ7 -- VP-06 value-area re-entry, {TIMEFRAME}, {start} -> {end} (research only)",
             "data: " + ", ".join(f"{k} sha256 {v[:12]}..." for k, v in hashes.items())]
    for setup, st in s["pooled"].items():
        lo, hi = st["ci"]
        ci = f"[{lo:+.3f}, {hi:+.3f}]" if lo is not None else "n/a"
        fe = st["far_edge"]
        far = (f"far-edge (descriptive): n {fe['n']}, target {fe['target_rate']:.0%}, avg {fe['avg_gross_r']:+.3f} R gross"
               if fe["n"] else "far-edge: no trades")
        lines.append(f"{setup:<7} trades {st['trades']:>4}  net {st['avg_net_r']:+.3f} R  {CI_LEVEL:.1%} CI {ci}  "
                     f"win {st['win_rate']:.0%}  maxDD {st['max_drawdown_r']:.1f} R | {far}")
    lo, hi = s["diff_ci"]
    lines.append(f"VP-06 - VP-06x: " + (f"[{lo:+.3f}, {hi:+.3f}]" if lo is not None else "n/a"))
    lines.append(f"Primary: {s['verdict']['primary']}")
    lines.append(f"Precondition: {s['verdict']['precondition']}")
    return "\n".join(lines)


def _ts(day: str) -> float:
    return datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()


def _file(dirpath: str, symbol: str) -> str:
    return os.path.join(dirpath, f"rq7_{symbol.split('/')[0].lower()}_1h.json")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="RQ7: VP-06 value-area re-entry on 1H (research only)")
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
