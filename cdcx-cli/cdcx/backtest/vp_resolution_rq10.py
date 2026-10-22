"""
vp_resolution_rq10.py
-----------------------
RQ10 (PLAN 2026-10-22, .ai/SHARED/research_questions.md) -- a CALCULATION
study, not a signal test. RESEARCH ONLY: it never changes
volume_profile_fixed (DEFAULT_BUCKETS stays 24 -- RQ6-RQ9 are frozen on it)
and reads no trade outcomes.

For the last N completed UTC sessions per symbol it computes POC / VAH / VAL
for every cell of rows {24, 100, 400} x source bars {1h, 15m, 5m}, using
volume_profile_fixed.build_volume_profile + calculate_poc_vah_val unchanged.

    reference   5m @ 400 rows -- an INTERNAL PROXY (finest data available
                here), not TradingView; TradingView parity is step 2 of the
                plan and is read separately through the TradingView MCP
    error       |level - reference| / ATR(11) of the 1h series at the
                session's last bar
    shift       the same cell on the window moved one source bar later
                (drop the first bar, add the next) -- stability
    rows +/-10% the same source bars at round(0.9 x rows) and round(1.1 x
                rows) -- stability (max of the two moves)
    tv-style VA the value area grown two rows at a time (TradingView's
                documented method) vs cdcx's one row at a time, same
                histogram -- audit only

    python -m cdcx.backtest.vp_resolution_rq10 --fetch DIR
    python -m cdcx.backtest.vp_resolution_rq10 --data DIR [--sessions 20] [--out FILE]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
from typing import Optional

from .. import no_trade_gate
from ..exchange.cryptocom import OHLCV
from ..indicators import atr_ema_variant1
from ..indicators.volume_profile_fixed import VALUE_AREA_PCT, build_volume_profile, calculate_poc_vah_val
from .vwap_vp_rq5 import _load, _save

SYMBOLS = ("XRP/USD", "XLM/USD")
ROWS = (24, 100, 400)
SOURCES = ("1h", "15m", "5m")
REFERENCE = ("5m", 400)
SESSIONS = 20
DAY = 86400
LEVELS = ("poc", "vah", "val")


def tv_value_area(histogram: dict[float, float], value_area_pct: float = VALUE_AREA_PCT) -> tuple[float, float]:
    """VAH/VAL grown two rows at a time: compare the sum of the next two rows above with the next two below,
    add the larger pair (ties go up). Audit only -- not used by cdcx."""
    prices = sorted(histogram)
    poc_i = prices.index(max(histogram, key=histogram.get))
    target = sum(histogram.values()) * value_area_pct
    lo = hi = poc_i
    acc = histogram[prices[poc_i]]
    while acc < target and (lo > 0 or hi < len(prices) - 1):
        up = [histogram[prices[k]] for k in range(hi + 1, min(hi + 3, len(prices)))]
        dn = [histogram[prices[k]] for k in range(max(lo - 2, 0), lo)]
        if sum(up) >= sum(dn) and up:
            hi += len(up)
            acc += sum(up)
        else:
            lo -= len(dn)
            acc += sum(dn)
    return prices[hi], prices[lo]


def _sec(data: OHLCV) -> list[float]:
    return [no_trade_gate.timestamp_to_seconds(t) for t in data.timestamps]


def session_bars(data: OHLCV, tf: str, start: float, end: float, shift: int = 0) -> Optional[tuple[list, list, list]]:
    """(highs, lows, volumes) of the bars opening in [start, end), moved `shift` bars later. None if a bar is
    missing (fail closed, like prev_day)."""
    ts = _sec(data)
    idx = [i for i, t in enumerate(ts) if start <= t < end]
    want = int((end - start) // no_trade_gate.timeframe_to_seconds(tf))
    if len(idx) != want:
        return None
    idx = [i + shift for i in idx]
    if idx[-1] >= len(ts):
        return None
    return [data.highs[i] for i in idx], [data.lows[i] for i in idx], [data.volumes[i] for i in idx]


def levels(h, l, v, rows: int) -> dict[str, float]:
    hist = build_volume_profile(h, l, v, buckets=rows)
    poc, vah, val = calculate_poc_vah_val(hist)
    tv_vah, tv_val = tv_value_area(hist)
    return {"poc": poc, "vah": vah, "val": val, "tv_vah": tv_vah, "tv_val": tv_val}


def study_symbol(series: dict[str, OHLCV], n_sessions: int = SESSIONS) -> list[dict]:
    """One row per (session, cell)."""
    h1 = series["1h"]
    ts1 = _sec(h1)
    atr = atr_ema_variant1.calculate_atr(h1.highs, h1.lows, h1.closes)
    last_day = (ts1[-1] + 3600) // DAY * DAY            # sessions end at or before the last complete hour's day
    out = []
    for k in range(n_sessions, 0, -1):
        start = last_day - k * DAY
        end = start + DAY
        a_idx = max(i for i, t in enumerate(ts1) if t < end)
        a = atr[a_idx]
        ref_bars = session_bars(series[REFERENCE[0]], REFERENCE[0], start, end)
        if ref_bars is None or not a or a != a:
            continue
        ref = levels(*ref_bars, REFERENCE[1])
        for src in SOURCES:
            bars = session_bars(series[src], src, start, end)
            moved = session_bars(series[src], src, start, end, shift=1)
            if bars is None:
                continue
            for rows in ROWS:
                lv = levels(*bars, rows)
                row = {"session": start, "source": src, "rows": rows, "atr": a, **lv}
                row["err"] = {x: abs(lv[x] - ref[x]) / a for x in LEVELS}
                row["shift"] = ({x: abs(levels(*moved, rows)[x] - lv[x]) / a for x in LEVELS} if moved else None)
                near = [levels(*bars, r) for r in (round(rows * 0.9), round(rows * 1.1))]
                row["rows10"] = {x: max(abs(n[x] - lv[x]) for n in near) / a for x in LEVELS}
                row["tv_va_diff"] = {"vah": abs(lv["tv_vah"] - lv["vah"]) / a, "val": abs(lv["tv_val"] - lv["val"]) / a}
                out.append(row)
    return out


def summarize(rows: list[dict]) -> dict:
    cells: dict = {}
    for r in rows:
        c = cells.setdefault(f"{r['source']}@{r['rows']}", {"n": 0, "err": [], "shift": [], "rows10": [], "tv": []})
        c["n"] += 1
        c["err"].append(max(r["err"].values()))
        if r["shift"]:
            c["shift"].append(max(r["shift"].values()))
        c["rows10"].append(max(r["rows10"].values()))
        c["tv"].append(max(r["tv_va_diff"].values()))
    med = lambda xs: statistics.median(xs) if xs else None
    return {k: {"n": c["n"], "median_err_atr": med(c["err"]), "median_shift_atr": med(c["shift"]),
                "median_rows10_atr": med(c["rows10"]), "median_tv_va_diff_atr": med(c["tv"])}
            for k, c in cells.items()}


def tv_parity(rows: list[dict], tv_levels: dict) -> dict:
    """Step 2: |cdcx level - TradingView Fixed Range VP level| / ATR per cell. `tv_levels` = {session start: [poc,
    vah, val]} read through the TradingView MCP (400 rows, 70% VA). Returns median / mean of the worst level and of
    each level, and the share of sessions within 0.10 ATR."""
    cells: dict = {}
    for r in rows:
        tv = tv_levels.get(str(int(float(r["session"]))))
        if not tv:
            continue
        e = {x: abs(r[x] - t) / r["atr"] for x, t in zip(LEVELS, tv)}
        c = cells.setdefault(f"{r['source']}@{r['rows']}", {"worst": [], **{x: [] for x in LEVELS}})
        c["worst"].append(max(e.values()))
        for x in LEVELS:
            c[x].append(e[x])
    return {k: {"n": len(c["worst"]), "median_worst": statistics.median(c["worst"]),
                "mean_worst": statistics.fmean(c["worst"]),
                "within_0.10": sum(w <= 0.10 for w in c["worst"]) / len(c["worst"]),
                **{f"median_{x}": statistics.median(c[x]) for x in LEVELS}} for k, c in cells.items()}


def format_parity(par: dict) -> str:
    lines = ["TradingView parity (step 2): |cdcx - TV FRVP 400 rows| / ATR(11, 1h); worst of POC/VAH/VAL unless named"]
    for sym, p in par.items():
        lines.append(f"\n{sym}   cell      n   median worst   mean worst   <=0.10 ATR   med POC   med VAH   med VAL")
        for src in SOURCES:
            for rows in ROWS:
                c = p.get(f"{src}@{rows}")
                if c:
                    lines.append(f"      {src:>3}@{rows:<4} {c['n']:>4}      {c['median_worst']:6.3f}       {c['mean_worst']:6.3f}"
                                 f"       {c['within_0.10']:5.0%}     {c['median_poc']:6.3f}    {c['median_vah']:6.3f}    {c['median_val']:6.3f}")
    return "\n".join(lines)


def format_report(per: dict, hashes: dict) -> str:
    f = lambda x: f"{x:6.3f}" if x is not None else "   n/a"
    lines = ["RQ10 -- profile resolution x source bars (calculation study; reference = 5m@400 PROXY, not TradingView)",
             "data: " + ", ".join(f"{k} sha256 {v[:12]}..." for k, v in hashes.items()),
             "values = median over sessions of the WORST of POC/VAH/VAL, in ATR(11, 1h) units"]
    for sym, summ in per.items():
        lines.append(f"\n{sym}   cell      n   err vs ref   shift 1 bar   rows +/-10%   tv-style VA diff")
        for src in SOURCES:
            for rows in ROWS:
                c = summ.get(f"{src}@{rows}")
                if c:
                    lines.append(f"      {src:>3}@{rows:<4} {c['n']:>4}   {f(c['median_err_atr'])}       "
                                 f"{f(c['median_shift_atr'])}        {f(c['median_rows10_atr'])}        "
                                 f"{f(c['median_tv_va_diff_atr'])}")
    return "\n".join(lines)


# --- step 4: downstream state changes (descriptive; no trade outcomes) --------------------------------------
STEP4_ROWS = (100, 400)


def _states(lv, sub) -> dict[str, str]:
    """state:direction of VP-01..05 (classify) and the research rows VP-06 / VP-04P / VP-01F on one bar."""
    from ..volume_profile import vp_breakout_pullback, vp_first_touch, vp_reentry
    from ..volume_profile.vwap_confluence import classify

    res = classify(lv, sub)
    out = {s.code: f"{s.state}:{s.direction}" for s in res.setups}
    out["DECISION"] = f"{res.qualification}:{res.qualification_direction}"
    for fn in (vp_reentry.value_area_reentry, vp_breakout_pullback.breakout_pullback, vp_first_touch.first_touch):
        r = fn(lv, sub)
        out[r.code] = f"{r.state}:{r.direction}"
    return out


def downstream(h1: OHLCV, m5: OHLCV, rows_list=STEP4_ROWS, last_days: int = SESSIONS) -> dict:
    """For each closed 1h bar of the last `last_days` days: setup states with the current 1h/24 levels vs the
    same bar with POC/VAH/VAL replaced by 5m @ rows levels of the same frozen session. Returns, per rows value
    and setup, the share of bars whose state:direction differs, plus counts of trigger-state bars each way."""
    from dataclasses import replace

    from ..volume_profile.prev_day import prev_day_levels
    from . import vwap_vp_research as vr

    ts = _sec(h1)
    first = ts[-1] - last_days * DAY
    lo = 0
    trig = {"VP-01": "CONFIRMED", "VP-04": "ACCEPTED", "VP-06": "PENDING", "VP-04P": "PENDING", "VP-01F": "PASS"}
    out = {r: {"bars": 0, "changed": {}, "trig_base": {}, "trig_alt": {}} for r in rows_list}
    cache: dict = {}
    for t in range(len(ts)):
        if ts[t] < first:
            continue
        now = ts[t] + 3600
        floor = (now // DAY) * DAY - DAY - vr.STRUCTURE_BARS * 3600
        while lo < t and ts[lo] < floor:
            lo += 1
        sub = vr._slice(h1, lo, t + 1)
        lv = prev_day_levels(sub, "1h", now=now)
        if lv.status != "OK":
            continue
        base = _states(lv, sub)
        for rows in rows_list:
            key = (lv.session_start, rows)
            if key not in cache:
                bars = session_bars(m5, "5m", lv.session_start, lv.session_end)
                cache[key] = levels(*bars, rows) if bars else None
            alt_lv = cache[key]
            if alt_lv is None:
                continue
            alt = _states(replace(lv, poc=alt_lv["poc"], vah=alt_lv["vah"], val=alt_lv["val"]), sub)
            o = out[rows]
            o["bars"] += 1
            for k in base:
                o["changed"][k] = o["changed"].get(k, 0) + (base[k] != alt.get(k))
            for k, st in trig.items():
                o["trig_base"][k] = o["trig_base"].get(k, 0) + base.get(k, "").startswith(st + ":")
                o["trig_alt"][k] = o["trig_alt"].get(k, 0) + alt.get(k, "").startswith(st + ":")
    for o in out.values():
        o["changed_share"] = {k: v / o["bars"] for k, v in o["changed"].items()} if o["bars"] else {}
    return out


def format_downstream(per: dict) -> str:
    lines = ["Step 4 -- share of 1h bars whose setup state changes if the frozen session's POC/VAH/VAL come from 5m bars "
             "(descriptive; no outcomes)"]
    for sym, d in per.items():
        for rows, o in d.items():
            ch = "  ".join(f"{k} {v:.0%}" for k, v in o["changed_share"].items())
            tr = "  ".join(f"{k} {o['trig_base'][k]}->{o['trig_alt'][k]}" for k in o["trig_base"])
            lines.append(f"{sym} 5m@{rows} ({o['bars']} bars): {ch}")
            lines.append(f"    trigger-state bars (1h@24 -> 5m@{rows}): {tr}")
    return "\n".join(lines)


def _file(dirpath: str, symbol: str, tf: str) -> str:
    return os.path.join(dirpath, f"rq10_{symbol.split('/')[0].lower()}_{tf}.json")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="RQ10: profile resolution x source bars (calculation study)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--fetch", metavar="DIR")
    g.add_argument("--data", metavar="DIR")
    ap.add_argument("--sessions", type=int, default=SESSIONS)
    ap.add_argument("--tv", metavar="DIR", help="also compare with rq10_tv_<sym>.json TradingView readings (step 2)")
    ap.add_argument("--step4", action="store_true", help="also count downstream setup-state changes (step 4)")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if a.fetch:
        import time
        from ..exchange.cryptocom import CryptoComExchange
        from . import vwap_vp_research as vr
        ex, now = CryptoComExchange(), time.time()
        for sym in SYMBOLS:
            for tf in SOURCES:
                per_day = DAY // no_trade_gate.timeframe_to_seconds(tf)
                d = ex.fetch_ohlcv(sym, tf, int(per_day * (a.sessions + 3)) + 60)
                if no_trade_gate.last_bar_is_forming(d.timestamps, tf, now):
                    d = vr._slice(d, 0, len(d.timestamps) - 1)
                print(f"{sym} {tf}: {len(d.timestamps)} bars, sha256 {_save(_file(a.fetch, sym, tf), d)}")
        return 0
    per, hashes, raw = {}, {}, {}
    for sym in SYMBOLS:
        series = {}
        for tf in SOURCES:
            series[tf], hashes[f"{sym} {tf}"] = _load(_file(a.data, sym, tf))
        raw[sym] = study_symbol(series, a.sessions)
        per[sym] = summarize(raw[sym])
    print(format_report(per, hashes))
    parity = {}
    if a.tv:
        for sym in SYMBOLS:
            path = os.path.join(a.tv, f"rq10_tv_{sym.split('/')[0].lower()}.json")
            if os.path.exists(path):
                with open(path) as fh:
                    parity[sym] = tv_parity(raw[sym], json.load(fh)["levels"])
        print()
        print(format_parity(parity))
    step4 = {}
    if a.step4:
        for sym in SYMBOLS:
            h1, _ = _load(_file(a.data, sym, "1h"))
            m5, _ = _load(_file(a.data, sym, "5m"))
            step4[sym] = downstream(h1, m5, last_days=a.sessions)
        print()
        print(format_downstream(step4))
    if a.out:
        with open(a.out, "w") as fh:
            json.dump({"hashes": hashes, "summary": per, "parity": parity, "step4": step4, "rows": raw}, fh, indent=1,
                      default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
