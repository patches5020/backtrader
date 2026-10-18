"""
vwap_watch_rq6.py
-------------------
RQ6 (.ai/SHARED/research_questions.md, sections 3-10). RESEARCH ONLY.

Are vwap-watch-1 closed-bar warnings informative? Events come from
`vwap_watch.replay()` only (the live evaluate -> step path, HTF 2-of-4 from
closed bars). For each counted event at bar t the outcome is the first touch,
within 12 1H bars, of C_t +/- 1.0 x ATR(11) (cdcx Wilder ATR); AMBIGUOUS and
NONE stay in every denominator as non-hits. A family's statistic is the mean,
over its primary events, of (hit - base rate of the same rule on all eligible
bars of the same symbol); the interval is a paired (symbol, UTC day) block
bootstrap, 10,000 resamples, random.Random(20261018), Bonferroni 0.05/6 per tail.

Nothing here changes the watcher, a plan, sizing or a protected parameter, and
no result authorizes execution. Runs refuse to start until RQ6 is FROZEN, and
the confirmatory period cannot be fetched or analysed before E + 24 h.

    python -m cdcx.backtest.vwap_watch_rq6 --freeze-hashes             hashes for the FROZEN line
    python -m cdcx.backtest.vwap_watch_rq6 --fetch DIR --period P      save the series once (+ SHA-256)
    python -m cdcx.backtest.vwap_watch_rq6 --data DIR --period P       run on the saved files only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Sequence

from .. import no_trade_gate
from ..indicators.atr_ema_variant1 import ATR_LENGTH, calculate_atr
from ..volume_profile import vwap_watch as vw

SYMBOLS = ("XRP/USD", "XLM/USD")
HTF = ("4h", "1d", "1w")
H1 = 3600
DAY = 86400
HORIZON = 12
BARRIER_ATR = 1.0
WARMUP_S = 7 * DAY
RESAMPLES = 10_000
SEED = 20261018
TAIL = 0.05 / 6                      # Bonferroni: 5% family-wise over 3 two-sided tests
MAX_UNDEFINED = 100
MIN_EVENTS, MIN_BLOCKS = 30, 10
CONFIRMATORY_DAYS = 56
EXPLORATORY = (1_748_736_000, 1_780_185_600)    # 2025-06-01 00:00Z -> 2026-05-31 00:00Z

FAMILIES = ("entry", "retest", "deterioration")
# event -> (family, hit rule): "fav" = the favourable barrier for d, "adv" = the adverse one
RULES = {
    "ENTRY_WATCH": ("entry", "fav"), "ENTRY_SETUP": ("entry", "fav"),
    "ENTRY_CONFIRMATION_CANDIDATE": ("entry", "fav"),
    "RETEST_HOLD": ("retest", "fav"), "RETEST_FAILURE": ("retest", "adv"),
    "SETUP_DETERIORATION": ("deterioration", "adv"), "AVWAP_LOST": ("deterioration", "adv"),
    "STRUCTURAL_INVALIDATION": ("deterioration", "adv"),
}
PRIMARY = {"entry": ("ENTRY_SETUP",), "retest": ("RETEST_HOLD", "RETEST_FAILURE"),
           "deterioration": ("SETUP_DETERIORATION", "AVWAP_LOST", "STRUCTURAL_INVALIDATION")}
COUNTED_ONLY = ("WATCH_CLEARED", "EXPIRED", "DATA_UNKNOWN", "DATA_RESTORED", "BASELINE")

RQ_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "..", ".ai", "SHARED", "research_questions.md")


# ---------------------------------------------------------------------------
# Periods and freeze
# ---------------------------------------------------------------------------
def confirmatory_period(frozen_ts: float) -> tuple[int, int]:
    """S = 00:00Z of the first UTC day beginning at least 24 h after the freeze; E = S + 56 days."""
    s = math.ceil((frozen_ts + DAY) / DAY) * DAY
    return s, s + CONFIRMATORY_DAYS * DAY


def rq6_text(path: str = RQ_FILE) -> str:
    """RQ6 from its heading to the end of section 10 (the hashed, frozen block)."""
    s = open(path, encoding="utf-8").read()
    i = s.index("## RQ6")
    j = s.index("**Known limits.**", i)
    return s[i:j]


def frozen_at(path: str = RQ_FILE) -> Optional[float]:
    """The FROZEN timestamp, or None while RQ6 is a draft."""
    m = re.search(r"`FROZEN:\s*([^`<]*?)\s*`", rq6_text(path))
    if not m or not m.group(1):
        return None
    stamp = m.group(1).split()[0].replace("Z", "+00:00")
    return datetime.fromisoformat(stamp).timestamp()


def sha256_file(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def freeze_hashes(path: str = RQ_FILE) -> dict:
    """What the FROZEN line records (besides date/time and commit)."""
    here = os.path.dirname(__file__)
    return {"vwap_watch.py": sha256_file(os.path.join(here, "..", "volume_profile", "vwap_watch.py")),
            "vwap_watch_rq6.py": sha256_file(__file__),
            "rq6_text": hashlib.sha256(rq6_text(path).encode()).hexdigest()}


# ---------------------------------------------------------------------------
# Outcome (section 4) and eligibility (section 3)
# ---------------------------------------------------------------------------
def atr_series(data) -> list[Optional[float]]:
    a = calculate_atr(data.highs, data.lows, data.closes, length=ATR_LENGTH)
    return [None if i < ATR_LENGTH - 1 else v for i, v in enumerate(a)]


def outcome(data, t: int, atr: float) -> str:
    c = data.closes[t]
    up, dn = c + BARRIER_ATR * atr, c - BARRIER_ATR * atr
    for k in range(1, HORIZON + 1):
        h, lo = data.highs[t + k], data.lows[t + k]
        if h >= up and lo <= dn:
            return "AMBIGUOUS"
        if h >= up:
            return "UP"
        if lo <= dn:
            return "DOWN"
    return "NONE"


def hit(out: str, direction: str, rule: str) -> int:
    fav = "UP" if direction == "bullish" else "DOWN"
    adv = "DOWN" if direction == "bullish" else "UP"
    return int(out == (fav if rule == "fav" else adv))


def eligible(ts: Sequence[float], t: int, valid: bool, atr: Optional[float]) -> bool:
    if not valid or atr is None or t + HORIZON >= len(ts):
        return False
    return all(ts[t + k] - ts[t + k - 1] == H1 for k in range(1, HORIZON + 1))


# ---------------------------------------------------------------------------
# Collection: replay -> events and eligible bars of one symbol
# ---------------------------------------------------------------------------
@dataclass
class Bar:
    symbol: str
    ts: int
    outcome: str


@dataclass
class Ev:
    symbol: str
    direction: str
    event: str
    ts: int
    anchor: Optional[str]
    key: str
    outcome: Optional[str] = None       # None = not eligible (dropped)
    record: dict = field(default_factory=dict, repr=False)


def _ts(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp())


def collect(symbol: str, h1, htf: dict, start: int, end: int) -> dict:
    """Replay `symbol` from start - 7 days to the last bar opening before `end`; return the period's
    eligible bars, all its events (with outcome or None) and counts. `htf` = {"4h"|"1d"|"1w": OHLCV}."""
    ts = [no_trade_gate.timestamp_to_seconds(t) for t in h1.timestamps]
    n_end = sum(1 for t in ts if t < end)
    bars = sum(1 for t in ts[:n_end] if t >= start - WARMUP_S)
    valid: dict[int, bool] = {}
    histories = {"1h": h1, **htf}
    recs = vw.replay(symbol, vw._slice(h1, None, n_end), "1h", bars,
                     htf_fn=vw.htf_from_history(histories, symbol), now=end + 1,
                     on_snapshot=lambda s: s.bar_ts is not None and valid.__setitem__(
                         int(s.bar_ts), s.data_quality == "valid"))
    atr = atr_series(h1)
    index = {int(t): i for i, t in enumerate(ts)}

    def out_at(t: int) -> Optional[str]:
        i = index.get(t)
        if i is None or not eligible(ts, i, valid.get(t, False), atr[i]):
            return None
        return outcome(h1, i, atr[i])

    period_bars, not_eligible = [], 0
    for t in ts[:n_end]:
        t = int(t)
        if start <= t < end and t in valid:
            o = out_at(t)
            if o is None:
                not_eligible += 1
            else:
                period_bars.append(Bar(symbol, t, o))
    events = []
    for r in recs:
        t = _ts(r["bar_open"]) if r["bar_open"] else None
        if t is None or not start <= t < end:
            continue
        events.append(Ev(symbol, r["direction"], r["event"], t, r["anchor"], r["key"],
                         out_at(t) if r["event"] in RULES else None, r))
    return {"symbol": symbol, "bars": period_bars, "events": events, "bars_not_eligible": not_eligible}


# ---------------------------------------------------------------------------
# De-duplication (6), comparator (7), bootstrap (8)
# ---------------------------------------------------------------------------
def primary(events: list[Ev], family: str) -> list[Ev]:
    """First event of each event type per (symbol, direction, UTC day of its bar), eligible only."""
    seen, out = set(), []
    for e in sorted((e for e in events if e.event in PRIMARY[family] and e.outcome is not None),
                    key=lambda e: e.ts):
        k = (e.event, e.symbol, e.direction, e.ts // DAY)
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out


def _counts(bars: list[Bar]) -> dict:
    c: dict = defaultdict(lambda: [0, 0, 0])      # symbol -> [UP, DOWN, total]
    for b in bars:
        x = c[b.symbol]
        x[0] += b.outcome == "UP"
        x[1] += b.outcome == "DOWN"
        x[2] += 1
    return c


def base_rate(c: dict, symbol: str, direction: str, rule: str) -> Optional[float]:
    up, dn, n = c.get(symbol, (0, 0, 0))
    if not n:
        return None
    return (up if (direction == "bullish") == (rule == "fav") else dn) / n


def delta(events: list[Ev], counts: dict) -> Optional[float]:
    if not events:
        return None
    tot = 0.0
    for e in events:
        rule = RULES[e.event][1]
        tot += hit(e.outcome, e.direction, rule) - base_rate(counts, e.symbol, e.direction, rule)
    return tot / len(events)


def block_day(symbol: str, ts: int, start: int) -> tuple:
    return symbol, ts // DAY


def block_2day(symbol: str, ts: int, start: int) -> tuple:
    return symbol, (ts - start) // (2 * DAY)


def period_blocks(symbols: Sequence[str], start: int, end: int, block_of=block_day) -> list[tuple]:
    out = []
    for s in symbols:
        for t in range(start, end, DAY):
            b = block_of(s, t, start)
            if b not in out:
                out.append(b)
    return out


def bootstrap(bars: list[Bar], events: list[Ev], blocks: list[tuple], rng: random.Random,
              n: int = RESAMPLES, block_of=block_day, start: int = 0) -> dict:
    """Paired block bootstrap of Delta: bars and events of the drawn blocks, with multiplicity."""
    bar_c: dict = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))
    for b in bars:
        x = bar_c[block_of(b.symbol, b.ts, start)][b.symbol]
        x[0] += b.outcome == "UP"
        x[1] += b.outcome == "DOWN"
        x[2] += 1
    ev_b: dict = defaultdict(list)
    for e in events:
        rule = RULES[e.event][1]
        ev_b[block_of(e.symbol, e.ts, start)].append((e.symbol, e.direction, rule, hit(e.outcome, e.direction, rule)))
    vals, undefined = [], 0
    for _ in range(n):
        drawn = rng.choices(blocks, k=len(blocks))
        c: dict = defaultdict(lambda: [0, 0, 0])
        evs = []
        for blk in drawn:
            for s, x in bar_c.get(blk, {}).items():
                y = c[s]
                y[0] += x[0]
                y[1] += x[1]
                y[2] += x[2]
            evs += ev_b.get(blk, ())
        if not evs:
            undefined += 1
            continue
        tot = 0.0
        for s, d, rule, h in evs:
            tot += h - base_rate(c, s, d, rule)
        vals.append(tot / len(evs))
    vals.sort()
    k = len(vals)
    lo = vals[int(k * TAIL)] if k else None
    hi = vals[int(k * (1 - TAIL)) - 1] if k else None
    return {"lower": lo, "upper": hi, "defined": k, "undefined": undefined}


# ---------------------------------------------------------------------------
# Analysis (sections 5-10)
# ---------------------------------------------------------------------------
def _rates(outs: list[str]) -> dict:
    n = len(outs)
    return {o: (round(outs.count(o) / n, 4) if n else None) for o in ("UP", "DOWN", "AMBIGUOUS", "NONE")}


def lead_times(events: list[Ev]) -> dict:
    """Bars from an episode's first ENTRY_WATCH to its ENTRY_SETUP / ENTRY_CONFIRMATION_CANDIDATE."""
    open_at: dict = {}
    got: dict = {"ENTRY_SETUP": [], "ENTRY_CONFIRMATION_CANDIDATE": []}
    done: set = set()
    for e in sorted(events, key=lambda e: e.ts):
        k = (e.symbol, e.direction, e.anchor)
        if e.event == "ENTRY_WATCH" and k not in open_at:
            open_at[k] = e.ts
        elif e.event in got and k in open_at and (k, open_at[k], e.event) not in done:
            got[e.event].append((e.ts - open_at[k]) // H1)
            done.add((k, open_at[k], e.event))
        elif e.event in ("WATCH_CLEARED", "STRUCTURAL_INVALIDATION", "EXPIRED"):
            open_at.pop(k, None)

    def q(xs):
        if not xs:
            return {"n": 0, "median": None, "iqr": None}
        xs = sorted(xs)
        at = lambda p: xs[min(len(xs) - 1, int(p * len(xs)))]
        return {"n": len(xs), "median": at(0.5), "iqr": [at(0.25), at(0.75)]}
    return {k: q(v) for k, v in got.items()}


def analyse(collected: list[dict], start: int, end: int, label: str, n: int = RESAMPLES) -> dict:
    bars = [b for c in collected for b in c["bars"]]
    events = [e for c in collected for e in c["events"]]
    symbols = [c["symbol"] for c in collected]
    counts = _counts(bars)
    rep: dict = {"period": label, "start": start, "end": end, "eligible_bars": len(bars),
                 "bars_not_eligible": sum(c["bars_not_eligible"] for c in collected),
                 "bar_outcomes": _rates([b.outcome for b in bars]),
                 "base_rates": {s: {d: {r: base_rate(counts, s, d, r) for r in ("fav", "adv")}
                                    for d in vw.DIRECTIONS} for s in symbols},
                 "event_types": {}, "families": {}, "sensitivity_2day": {},
                 "counted_only": {k: sum(e.event == k for e in events) for k in COUNTED_ONLY},
                 "lead_time_bars": lead_times(events)}
    for et, (fam, rule) in RULES.items():
        raw = [e for e in events if e.event == et]
        ok = [e for e in raw if e.outcome is not None]
        prim = [e for e in primary(events, fam) if e.event == et] if et in PRIMARY[fam] else []
        hits = [hit(e.outcome, e.direction, rule) for e in ok]
        false = [hit(e.outcome, e.direction, "adv" if rule == "fav" else "fav") for e in ok]
        rep["event_types"][et] = {
            "family": fam, "rule": rule, "role": "primary" if et in PRIMARY[fam] else "secondary",
            "raw": len(raw), "dropped": len(raw) - len(ok), "primary": len(prim),
            "outcomes": _rates([e.outcome for e in ok]),
            "hit_rate": round(sum(hits) / len(hits), 4) if hits else None,
            "false_warning_rate": round(sum(false) / len(false), 4) if false else None,
            "delta_all_events": delta(ok, counts),
            "per_symbol": {s: {"raw": sum(e.symbol == s for e in raw),
                               "delta_all_events": delta([e for e in ok if e.symbol == s], counts)}
                           for s in symbols},
        }
    rng = random.Random(SEED)                         # one generator, families in order
    blocks = period_blocks(symbols, start, end)
    for fam in FAMILIES:
        prim = primary(events, fam)
        nblk = len({block_day(e.symbol, e.ts, start) for e in prim})
        bs = bootstrap(bars, prim, blocks, rng, n=n)
        enough = len(prim) >= MIN_EVENTS and nblk >= MIN_BLOCKS and bs["undefined"] <= MAX_UNDEFINED
        lo = bs["lower"]
        if not enough:
            verdict = "INSUFFICIENT SAMPLE (descriptive only)"
        elif label != "confirmatory":
            verdict = "EXPLORATORY -- descriptive, no verdict"
        else:
            verdict = "INFORMATIVE (lower > 0)" if lo is not None and lo > 0 else "INCONCLUSIVE / NO"
        rep["families"][fam] = {"primary_events": len(prim), "blocks_with_events": nblk,
                                "delta": delta(prim, counts), **bs, "verdict": verdict,
                                "keys": [e.key for e in prim]}
    rng2 = random.Random(SEED)                        # sensitivity: own run, same seed, 2-day blocks
    blocks2 = period_blocks(symbols, start, end, block_2day)
    for fam in FAMILIES:
        bs = bootstrap(bars, primary(events, fam), blocks2, rng2, n=n, block_of=block_2day, start=start)
        rep["sensitivity_2day"][fam] = bs
    return rep


def _f(x, fmt="{:+.4f}") -> str:
    return "-" if x is None else fmt.format(x)


def format_report(rep: dict, hashes: dict) -> str:
    iso = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%MZ")
    lines = [f"RQ6 -- vwap-watch-1 closed-bar warnings | {rep['period'].upper()} {iso(rep['start'])} -> "
             f"{iso(rep['end'])} | research only, execution NOT AUTHORIZED",
             "data: " + ", ".join(f"{k} {v[:16]}" for k, v in sorted(hashes.items())),
             f"eligible bars {rep['eligible_bars']} (not eligible {rep['bars_not_eligible']}); outcomes "
             + " ".join(f"{k} {_f(v, '{:.3f}')}" for k, v in rep["bar_outcomes"].items()), "",
             f"{'event':<30}{'role':<10}{'raw':>5}{'drop':>5}{'prim':>5}{'hit':>7}{'false':>7}{'Delta':>9}"
             f"  UP/DOWN/AMB/NONE"]
    for et, r in rep["event_types"].items():
        o = r["outcomes"]
        lines.append(f"{et:<30}{r['role']:<10}{r['raw']:>5}{r['dropped']:>5}{r['primary']:>5}"
                     f"{_f(r['hit_rate'], '{:.3f}'):>7}{_f(r['false_warning_rate'], '{:.3f}'):>7}"
                     f"{_f(r['delta_all_events']):>9}  " + "/".join(_f(o[k], "{:.2f}") for k in o))
    lines += ["", "counted only: " + ", ".join(f"{k} {v}" for k, v in rep["counted_only"].items()),
              "lead time (bars from first ENTRY_WATCH): " + ", ".join(
                  f"{k} n={v['n']} median={v['median']} IQR={v['iqr']}" for k, v in rep["lead_time_bars"].items()),
              "", "PRIMARY TESTS (paired (symbol, UTC day) block bootstrap, 10,000, Bonferroni 0.05/6 per tail):"]
    for fam, r in rep["families"].items():
        s2 = rep["sensitivity_2day"][fam]
        lines.append(f"  {fam:<14} n={r['primary_events']:<4} blocks={r['blocks_with_events']:<4} "
                     f"Delta={_f(r['delta'])} CI [{_f(r['lower'])}, {_f(r['upper'])}] "
                     f"undefined={r['undefined']} | 2-day [{_f(s2['lower'])}, {_f(s2['upper'])}] -> {r['verdict']}")
    lines.append("\"Informative\" adds no weight or alert by itself; that needs a separate user-approved proposal.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Files and CLI
# ---------------------------------------------------------------------------
def _save(path: str, d) -> str:
    raw = json.dumps({k: list(getattr(d, k)) for k in ("timestamps", "opens", "highs", "lows", "closes", "volumes")})
    with open(path, "w") as fh:
        fh.write(raw)
    return hashlib.sha256(raw.encode()).hexdigest()


def _load(path: str):
    from ..exchange.cryptocom import OHLCV
    raw = open(path).read()
    return OHLCV(**json.loads(raw)), hashlib.sha256(raw.encode()).hexdigest()


def _file(dirpath: str, period: str, symbol: str, tf: str) -> str:
    return os.path.join(dirpath, f"rq6_{period}_{symbol.split('/')[0].lower()}_{tf}.json")


def period_bounds(period: str, frozen: float) -> tuple[int, int]:
    return confirmatory_period(frozen) if period == "confirmatory" else EXPLORATORY


def fetch_ranges(start: int, end: int) -> dict:
    """1H from S - 60 days, 4H/1D/1W from S - 400 days, all to E + 1 day."""
    return {"1h": (start - 60 * DAY, end + DAY), **{tf: (start - 400 * DAY, end + DAY) for tf in HTF}}


def _trim(d, lo: int, hi: int):
    ts = [no_trade_gate.timestamp_to_seconds(t) for t in d.timestamps]
    i = next((k for k, t in enumerate(ts) if t >= lo), len(ts))
    j = sum(1 for t in ts if t < hi)
    return vw._slice(d, i, j)


def guard(period: str, now: float, path: str = RQ_FILE) -> tuple[Optional[float], Optional[str]]:
    """(frozen timestamp, refusal reason or None)."""
    frozen = frozen_at(path)
    if frozen is None:
        return None, "RQ6 is not FROZEN -- no fetch or evaluation before the freeze"
    if period == "confirmatory":
        _, e = confirmatory_period(frozen)
        if now < e + DAY:
            return frozen, (f"confirmatory data can be fetched/analysed only once, at or after E + 24 h "
                            f"({datetime.fromtimestamp(e + DAY, timezone.utc):%Y-%m-%d %H:%MZ}) -- no interim looks")
    return frozen, None


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="RQ6: vwap-watch-1 closed-bar warnings (research only)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--freeze-hashes", action="store_true", help="print the SHA-256 values the FROZEN line records")
    g.add_argument("--fetch", metavar="DIR", help="fetch the series once and save them with their SHA-256")
    g.add_argument("--data", metavar="DIR", help="run on the saved series only")
    ap.add_argument("--period", choices=("confirmatory", "exploratory"), default="confirmatory")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if a.freeze_hashes:
        for k, v in freeze_hashes().items():
            print(f"{k}: {v}")
        return 0
    frozen, why = guard(a.period, time.time())
    if why:
        print(f"REFUSED: {why}")
        return 2
    start, end = period_bounds(a.period, frozen)
    d = a.fetch or a.data
    if a.fetch:
        from ..exchange.cryptocom import CryptoComExchange
        ex, now, manifest = CryptoComExchange(), time.time(), {}
        for sym in SYMBOLS:
            for tf, (lo, hi) in fetch_ranges(start, end).items():
                tf_s = no_trade_gate.timeframe_to_seconds(tf)
                raw = ex.fetch_ohlcv(sym, tf, int((now - lo) / tf_s) + 2)
                f = _file(d, a.period, sym, tf)
                manifest[os.path.basename(f)] = _save(f, _trim(raw, lo, hi))
                print(f"{sym} {tf}: sha256 {manifest[os.path.basename(f)]}")
        with open(os.path.join(d, f"rq6_{a.period}_manifest.json"), "w") as fh:
            json.dump(manifest, fh, indent=1)
        return 0
    manifest = json.load(open(os.path.join(d, f"rq6_{a.period}_manifest.json")))
    collected, hashes = [], {}
    for sym in SYMBOLS:
        series = {}
        for tf in ("1h",) + HTF:
            f = _file(d, a.period, sym, tf)
            series[tf], h = _load(f)
            if manifest.get(os.path.basename(f)) != h:
                print(f"REFUSED: {os.path.basename(f)} does not match its saved SHA-256")
                return 2
            hashes[os.path.basename(f)] = h
        collected.append(collect(sym, series["1h"], {tf: series[tf] for tf in HTF}, start, end))
    rep = analyse(collected, start, end, a.period)
    print(format_report(rep, hashes))
    if a.out:
        with open(a.out, "w") as fh:
            json.dump({"hashes": hashes, "report": rep,
                       "events": [e.record for c in collected for e in c["events"]]}, fh, indent=1, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
