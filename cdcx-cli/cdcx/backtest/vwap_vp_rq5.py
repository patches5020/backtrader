"""
vwap_vp_rq5.py
----------------
RQ5 (pre-registered 2026-10-17 in .ai/SHARED/research_questions.md). RESEARCH ONLY.

Do ADX or RSI add information to VP-04 on 1H bars? Two pre-specified filters,
sampled at the signal bar t (closed), from 1H bars up to and including t:

    A (ADX)  ADX[t] > ADX[t-3] AND the trade's DI leads (long +DI > -DI, short -DI > +DI)
    B (RSI)  long RSI[t] > 50, short RSI[t] < 50                      (ties fail)

cdcx's own Wilder calculate_adx / calculate_rsi, length 17. Signals, replay,
trade model and costs are vwap_vp_research's, unchanged.

Primary: the BASELINE trades split into PASS / FAIL by each filter, pooled
XRP + XLM over FRESH (2025-06-01 -> 2026-05-30); 97.5% bootstrap interval of
mean net R (PASS - FAIL), 10,000 resamples, seed 20261017.
Secondary: the filtered strategy re-replayed on its own signals.

    python -m cdcx.backtest.vwap_vp_rq5 --fetch DIR      save the 1H series once (+ SHA-256)
    python -m cdcx.backtest.vwap_vp_rq5 --data DIR       run on the saved files only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
from dataclasses import asdict
from typing import Optional, Sequence

from .. import no_trade_gate
from ..exchange.cryptocom import OHLCV
from ..indicators.adx import calculate_adx
from ..indicators.rsi import calculate_rsi
from . import vwap_vp_research as vr
from .vwap_vp_htf_followup import FRESH_START, SEEN_START

SYMBOLS = ("XRP/USD", "XLM/USD")
ADX_SLOPE_BARS = 3
RESAMPLES = 10_000
SEED = 20261017
CI_LEVEL = 0.975          # two tests -> alpha 0.05 / 2


def filter_a(adx: Sequence[float], pdi: Sequence[float], mdi: Sequence[float], t: int, direction: str) -> bool:
    if t < ADX_SLOPE_BARS or not adx[t - ADX_SLOPE_BARS]:
        return False      # ADX not yet defined -> fail (never a pass by default)
    rising = adx[t] > adx[t - ADX_SLOPE_BARS]
    leads = pdi[t] > mdi[t] if direction == "bullish" else mdi[t] > pdi[t]
    return rising and leads


def filter_b(rsi: Sequence[float], t: int, direction: str) -> bool:
    r = rsi[t]
    if r is None or r != r:
        return False
    return r > 50 if direction == "bullish" else r < 50


def bootstrap_mean_ci(xs: Sequence[float], level: float = CI_LEVEL, n: int = RESAMPLES,
                      rng: Optional[random.Random] = None) -> tuple[Optional[float], Optional[float]]:
    if len(xs) < 2:
        return None, None
    rng = rng or random.Random(SEED)
    k = len(xs)
    means = sorted(sum(rng.choices(xs, k=k)) / k for _ in range(n))
    tail = (1 - level) / 2
    return means[int(tail * n)], means[int((1 - tail) * n) - 1]


def bootstrap_diff_ci(a: Sequence[float], b: Sequence[float], level: float = CI_LEVEL, n: int = RESAMPLES,
                      rng: Optional[random.Random] = None) -> tuple[Optional[float], Optional[float]]:
    """Interval of mean(a) - mean(b), resampling within each group."""
    if len(a) < 2 or len(b) < 2:
        return None, None
    rng = rng or random.Random(SEED)
    diffs = sorted(sum(rng.choices(a, k=len(a))) / len(a) - sum(rng.choices(b, k=len(b))) / len(b)
                   for _ in range(n))
    tail = (1 - level) / 2
    return diffs[int(tail * n)], diffs[int((1 - tail) * n) - 1]


def annotate(data: OHLCV, signals: list[tuple[int, str, str]]) -> dict[int, dict[str, bool]]:
    """Filter results per signal bar, from indicators computed on the full series (Wilder smoothing is
    causal: the value at t uses bars <= t only)."""
    adx, pdi, mdi = calculate_adx(data.highs, data.lows, data.closes)
    rsi = calculate_rsi(data.closes)
    return {t: {"A": filter_a(adx, pdi, mdi, t, d), "B": filter_b(rsi, t, d)} for t, _, d in signals}


def vp04_signals(data: OHLCV) -> list[tuple[int, str, str]]:
    ts = [no_trade_gate.timestamp_to_seconds(t) for t in data.timestamps]
    start = next(i for i, t in enumerate(ts) if t >= FRESH_START - 3 * 86400)   # same warm-up as RQ3
    return [s for s in vr.find_signals(data, "1h", start_index=start) if s[1] == "VP-04" and ts[s[0]] >= FRESH_START]


def _row(trades: list[vr.Trade]) -> dict:
    done = [t.net_r for t in trades if t.status != "open"]
    lo, hi = bootstrap_mean_ci(done)
    return {**asdict(vr.stats(trades)), "ci": [lo, hi]}


def run_symbol(symbol: str, data: OHLCV) -> dict:
    signals = vp04_signals(data)
    flags = annotate(data, signals)
    base = vr.replay(data, [(t, "VP04", d) for t, _, d in signals], symbol)
    refilt = {f: vr.replay(data, [(t, "VP04", d) for t, _, d in signals if flags[t][f]], symbol) for f in "AB"}
    return {"symbol": symbol, "signals": len(signals), "flags": {str(k): v for k, v in flags.items()},
            "baseline": base, "refiltered": refilt}


def summarize(per_symbol: list[dict]) -> dict:
    def period(trs, which):
        return [t for t in trs if (t.signal_ts < SEEN_START) == (which == "fresh")]

    out: dict = {"symbols": {}, "pooled": {}}
    groups = {s["symbol"]: s for s in per_symbol}
    groups["POOLED"] = {
        "baseline": [t for s in per_symbol for t in s["baseline"]],
        "refiltered": {f: [t for s in per_symbol for t in s["refiltered"][f]] for f in "AB"},
        "flags": {f"{s['symbol']}:{k}": v for s in per_symbol for k, v in s["flags"].items()},
    }
    for name, g in groups.items():
        res = {}
        for which in ("fresh", "seen"):
            base = period(g["baseline"], which)
            row = {"baseline": _row(base)}
            for f in "AB":
                if name == "POOLED":
                    flag = lambda t: g["flags"][f"{t._symbol}:{t.signal_index}"][f]
                else:
                    flag = lambda t: g["flags"][str(t.signal_index)][f]
                p = [t for t in base if flag(t)]
                q = [t for t in base if not flag(t)]
                pr = [t.net_r for t in p if t.status != "open"]
                qr = [t.net_r for t in q if t.status != "open"]
                row[f] = {"pass": _row(p), "fail": _row(q), "diff_ci": list(bootstrap_diff_ci(pr, qr)),
                          "diff": (round(sum(pr) / len(pr) - sum(qr) / len(qr), 3) if pr and qr else None),
                          "refiltered": _row(period(g["refiltered"][f], which))}
            res[which] = row
        out["symbols" if name != "POOLED" else "pooled"][name] = res
    return out


def verdict(pooled_fresh: dict, f: str) -> str:
    lo, _ = pooled_fresh[f]["diff_ci"]
    rlo = pooled_fresh[f]["refiltered"]["ci"][0]
    if lo is None:
        return "INCONCLUSIVE (too few trades)"
    if lo <= 0:
        return "NO EVIDENCE -- PASS - FAIL interval includes 0 (inconclusive; no threshold search)"
    if rlo is not None and rlo > 0:
        return "ADDS INFORMATION and the filtered strategy is positive -> may be proposed as an advisory line"
    return "ADDS INFORMATION, but the filtered strategy's interval includes 0 -> not proposed"


def _fmt(r: dict) -> str:
    lo, hi = r["ci"]
    ci = f"[{lo:+.3f}, {hi:+.3f}]" if lo is not None else "[-, -]"
    pf = "-" if r["profit_factor"] is None else f"{r['profit_factor']:.2f}"
    return (f"{r['trades']:>6}{r['win_rate'] * 100:>6.0f}%{r['avg_gross_r']:>8.3f}{r['avg_cost_r']:>7.3f}"
            f"{r['avg_net_r']:>8.3f} {ci:<20}{r['total_net_r']:>8.2f}{pf:>6}{r['max_drawdown_r']:>8.2f}")


def format_report(s: dict, data_hashes: dict) -> str:
    head = f"{'':<26}{'Trades':>6}{'Win':>7}{'Gross':>8}{'Cost':>7}{'NetR':>8} {'97.5% CI of mean':<20}" \
           f"{'TotalR':>8}{'PF':>6}{'MaxDD':>8}"
    lines = ["RQ5 -- ADX / RSI filters on VP-04 1H (pre-registered 2026-10-17) | research only",
             "data: " + ", ".join(f"{k} sha256 {v[:16]}" for k, v in data_hashes.items()), ""]
    for name, res in [("POOLED", s["pooled"]["POOLED"])] + list(s["symbols"].items()):
        for which in ("fresh", "seen"):
            row = res[which]
            tag = "TEST" if which == "fresh" else "reference only"
            lines += [f"== {name} {which.upper()} ({tag})", head, f"{'baseline':<26}" + _fmt(row["baseline"])]
            for f, label in (("A", "A ADX rising + DI"), ("B", "B RSI side of 50")):
                d = row[f]
                lo, hi = d["diff_ci"]
                lines += [f"{label + ' PASS':<26}" + _fmt(d["pass"]),
                          f"{label + ' FAIL':<26}" + _fmt(d["fail"]),
                          f"{label + ' re-replayed':<26}" + _fmt(d["refiltered"]),
                          f"{'':<26}PASS - FAIL = {d['diff'] if d['diff'] is not None else '-'} R, 97.5% CI "
                          + (f"[{lo:+.3f}, {hi:+.3f}]" if lo is not None else "[-, -]")]
            lines.append("")
    pf = s["pooled"]["POOLED"]["fresh"]
    lines += ["DECISION (pre-registered rule, pooled FRESH):",
              f"  A ADX: {verdict(pf, 'A')}", f"  B RSI: {verdict(pf, 'B')}"]
    return "\n".join(lines)


def _save(path: str, d: OHLCV) -> str:
    raw = json.dumps({k: list(getattr(d, k)) for k in ("timestamps", "opens", "highs", "lows", "closes", "volumes")})
    with open(path, "w") as fh:
        fh.write(raw)
    return hashlib.sha256(raw.encode()).hexdigest()


def _load(path: str) -> tuple[OHLCV, str]:
    raw = open(path).read()
    j = json.loads(raw)
    return OHLCV(**j), hashlib.sha256(raw.encode()).hexdigest()


def _file(dirpath: str, symbol: str) -> str:
    return os.path.join(dirpath, f"rq5_{symbol.split('/')[0].lower()}_1h.json")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="RQ5: ADX / RSI filters on VP-04 1H (research only)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--fetch", metavar="DIR", help="fetch the 1H series once and save it with its SHA-256")
    g.add_argument("--data", metavar="DIR", help="run on the saved series only")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if a.fetch:
        import time
        from ..exchange.cryptocom import CryptoComExchange
        from ..no_trade_gate import last_bar_is_forming
        ex, now = CryptoComExchange(), time.time()
        for sym in SYMBOLS:
            d = ex.fetch_ohlcv(sym, "1h", int((now - FRESH_START) / 3600) + 280)
            if last_bar_is_forming(d.timestamps, "1h", now):
                d = vr._slice(d, 0, len(d.timestamps) - 1)
            print(f"{sym}: {len(d.timestamps)} bars, sha256 {_save(_file(a.fetch, sym), d)}")
        return 0
    per, hashes = [], {}
    for sym in SYMBOLS:
        d, h = _load(_file(a.data, sym))
        hashes[sym] = h
        r = run_symbol(sym, d)
        for t in r["baseline"]:
            t._symbol = sym
        per.append(r)
    s = summarize(per)
    print(format_report(s, hashes))
    if a.out:
        with open(a.out, "w") as fh:
            json.dump({"hashes": hashes, "summary": s}, fh, indent=1, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
