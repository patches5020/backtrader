"""RQ6 analysis script -- synthetic data only (no real or locked series is read here)."""

import ast
import pathlib
import random

import pytest

from cdcx.backtest import vwap_watch_rq6 as rq
from cdcx.exchange.cryptocom import OHLCV

H = 3600
DAY = 86400
D0 = 1_799_971_200            # 2027-01-15 00:00Z


def _series(n=400, seed=7, start=D0 - 20 * DAY, gap_at=None):
    rng = random.Random(seed)
    ts = [start + H * i for i in range(n)]
    if gap_at is not None:
        ts = ts[:gap_at] + [t + H for t in ts[gap_at:]]
    c, closes = 1.30, []
    for _ in range(n):
        c *= 1 + rng.uniform(-0.008, 0.008)
        closes.append(c)
    opens = [closes[0]] + closes[:-1]
    return OHLCV([t * 1000 for t in ts], opens, [max(o, x) * 1.003 for o, x in zip(opens, closes)],
                 [min(o, x) * 0.997 for o, x in zip(opens, closes)], closes,
                 [100.0 + (i * 37) % 23 for i in range(n)])


def _bars(n_hl, closes):
    """OHLCV with explicit (high, low) pairs after bar 0."""
    return OHLCV([D0 * 1000 + i * H * 1000 for i in range(len(n_hl))], list(closes), [h for h, _ in n_hl],
                 [lo for _, lo in n_hl], list(closes), [1.0] * len(n_hl))


# ------------------------------------------------------------------ periods / freeze
def test_confirmatory_period_starts_first_day_24h_after_freeze():
    assert rq.confirmatory_period(D0) == (D0 + DAY, D0 + DAY + 56 * DAY)            # exactly midnight
    assert rq.confirmatory_period(D0 + 1) == (D0 + 2 * DAY, D0 + 58 * DAY)
    assert rq.confirmatory_period(D0 + 0.5)[0] == D0 + 2 * DAY                       # fractional second
    assert rq.confirmatory_period(D0 + DAY - 1)[0] == D0 + 2 * DAY


def _rq_file(tmp_path, frozen="<empty = draft>"):
    p = tmp_path / "research_questions.md"
    p.write_text("## RQ5\nx\n## RQ6 -- test\n**0. Freeze.**\n- `FROZEN: " + frozen + "`\n**10. Reported.** y\n"
                 "**Known limits.** z\n", encoding="utf-8")
    return str(p)


def test_draft_is_not_frozen_and_runs_are_refused(tmp_path):
    p = _rq_file(tmp_path)
    assert rq.frozen_at(p) is None
    for period in ("confirmatory", "exploratory"):
        frozen, why = rq.guard(period, now=D0, path=p)
        assert frozen is None and "not FROZEN" in why


def test_confirmatory_refused_before_e_plus_24h(tmp_path):
    p = _rq_file(tmp_path, "2027-01-15T12:00:00Z commit abc vwap_watch.py 00 rq6 00 text 00")
    frozen = rq.frozen_at(p)
    assert frozen == D0 + 12 * H
    _, e = rq.confirmatory_period(frozen)
    assert "no interim looks" in rq.guard("confirmatory", now=e + DAY - 1, path=p)[1]
    assert rq.guard("confirmatory", now=e + DAY, path=p)[1] is None
    assert rq.guard("exploratory", now=D0, path=p)[1] is None


def test_rq6_text_is_heading_to_end_of_section_10(tmp_path):
    t = rq.rq6_text(_rq_file(tmp_path))
    assert t.startswith("## RQ6") and "**10. Reported.**" in t and "Known limits" not in t and "RQ5" not in t


def test_freeze_hashes_cover_the_three_items():
    h = rq.freeze_hashes()
    assert set(h) == {"vwap_watch.py", "vwap_watch_rq6.py", "rq6_text"} and all(len(v) == 64 for v in h.values())


def test_the_real_rq6_block_is_still_a_draft():
    assert rq.frozen_at() is None


# ------------------------------------------------------------------ ATR / outcome / eligibility
def test_atr_matches_the_written_formula():
    d = _series(n=40)
    h, lo, c = d.highs, d.lows, d.closes
    tr = [h[0] - lo[0]] + [max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])) for i in range(1, 40)]
    want = [None] * 10 + [sum(tr[:11]) / 11]
    for i in range(11, 40):
        want.append((want[-1] * 10 + tr[i]) / 11)
    got = rq.atr_series(d)
    assert got[:10] == [None] * 10
    assert all(abs(a - b) < 1e-12 for a, b in zip(got[10:], want[10:]))


def test_outcome_first_touch_and_ambiguous():
    c = [1.0] * 14
    flat = [(1.0, 1.0)]
    assert rq.outcome(_bars(flat + [(1.05, 0.99)] * 13, c), 0, 0.1) == "NONE"
    assert rq.outcome(_bars(flat + [(1.05, 0.99), (1.10, 0.95)] + [(1.0, 1.0)] * 11, c), 0, 0.1) == "UP"
    assert rq.outcome(_bars(flat + [(1.0, 0.90), (1.2, 0.95)] + [(1.0, 1.0)] * 11, c), 0, 0.1) == "DOWN"
    assert rq.outcome(_bars(flat + [(1.10, 0.90)] + [(1.0, 1.0)] * 12, c), 0, 0.1) == "AMBIGUOUS"
    # a touch at bar t+13 is beyond the 12-bar horizon
    assert rq.outcome(_bars(flat + [(1.0, 1.0)] * 12 + [(2.0, 1.0)], c), 0, 0.1) == "NONE"


def test_hit_rules():
    assert rq.hit("UP", "bullish", "fav") == rq.hit("DOWN", "bearish", "fav") == 1
    assert rq.hit("DOWN", "bullish", "adv") == rq.hit("UP", "bearish", "adv") == 1
    for o in ("AMBIGUOUS", "NONE"):
        assert all(rq.hit(o, d, r) == 0 for d in ("bullish", "bearish") for r in ("fav", "adv"))


def test_eligibility_needs_valid_atr_and_12_gapless_bars():
    ts = [i * H for i in range(30)]
    assert rq.eligible(ts, 10, True, 0.1)
    assert not rq.eligible(ts, 10, False, 0.1)
    assert not rq.eligible(ts, 10, True, None)
    assert rq.eligible(ts, 17, True, 0.1) and not rq.eligible(ts, 18, True, 0.1)    # needs t+12 to exist
    gap = ts[:15] + [t + H for t in ts[15:]]
    assert not rq.eligible(gap, 10, True, 0.1) and rq.eligible(gap, 15, True, 0.1)


# ------------------------------------------------------------------ dedup / comparator / bootstrap
def _ev(event, ts, d="bullish", sym="XRP/USD", out="UP", anchor="a"):
    return rq.Ev(sym, d, event, ts, anchor, f"{event}{ts}{d}{sym}", out)


def test_primary_dedup_first_per_type_symbol_direction_day():
    evs = [_ev("ENTRY_SETUP", D0 + 5 * H), _ev("ENTRY_SETUP", D0 + 2 * H), _ev("ENTRY_SETUP", D0 + 3 * H, "bearish"),
           _ev("ENTRY_SETUP", D0 + DAY), _ev("ENTRY_SETUP", D0 + 4 * H, out=None), _ev("ENTRY_WATCH", D0)]
    got = rq.primary(evs, "entry")
    assert [(e.ts, e.direction) for e in got] == [(D0 + 2 * H, "bullish"), (D0 + 3 * H, "bearish"), (D0 + DAY, "bullish")]
    ret = rq.primary([_ev("RETEST_HOLD", D0), _ev("RETEST_FAILURE", D0 + H), _ev("RETEST_HOLD", D0 + 2 * H)], "retest")
    assert [e.event for e in ret] == ["RETEST_HOLD", "RETEST_FAILURE"]


def test_delta_against_same_symbol_same_rule_base_rate():
    bars = [rq.Bar("XRP/USD", i, o) for i, o in enumerate(["UP", "UP", "DOWN", "NONE"])] + \
           [rq.Bar("XLM/USD", i, o) for i, o in enumerate(["DOWN", "AMBIGUOUS"])]
    c = rq._counts(bars)
    assert rq.base_rate(c, "XRP/USD", "bullish", "fav") == 0.5
    assert rq.base_rate(c, "XRP/USD", "bearish", "adv") == 0.5
    assert rq.base_rate(c, "XRP/USD", "bearish", "fav") == 0.25
    assert rq.base_rate(c, "XLM/USD", "bullish", "adv") == 0.5
    evs = [_ev("ENTRY_SETUP", 0, out="UP"), _ev("RETEST_FAILURE", 1, "bearish", "XLM/USD", "UP")]
    # (1 - 0.5) + (1 - 0.0)  [bearish adverse = UP; XLM has no UP bars]
    assert rq.delta(evs, c) == pytest.approx(0.75)


def _toy(n_days=20, hit_all=True):
    bars, evs = [], []
    for d in range(n_days):
        for k in range(24):
            t = D0 + d * DAY + k * H
            bars.append(rq.Bar("XRP/USD", t, {0: "UP", 2: "DOWN"}.get(k % 4, "NONE")))
        evs += [_ev("ENTRY_SETUP", D0 + d * DAY, out="UP" if hit_all else "NONE"),
                _ev("ENTRY_SETUP", D0 + d * DAY + H, "bearish", out="DOWN" if hit_all else "UP")]
    return bars, evs


def test_bootstrap_is_seeded_paired_and_uses_the_written_indexing():
    bars, evs = _toy()
    blocks = rq.period_blocks(["XRP/USD"], D0, D0 + 20 * DAY)
    a = rq.bootstrap(bars, evs, blocks, random.Random(rq.SEED), n=500)
    b = rq.bootstrap(bars, evs, blocks, random.Random(rq.SEED), n=500)
    assert a == b and a["undefined"] == 0 and a["defined"] == 500
    # every event hits and both base rates are exactly 0.25 in every block -> Delta is 0.75 in every resample
    assert a["lower"] == pytest.approx(0.75) and a["upper"] == pytest.approx(0.75)


def test_bootstrap_interval_indices():
    bars, evs = _toy()
    for i, e in enumerate(evs):
        e.outcome = "UP" if i % 3 else "NONE"
    blocks = rq.period_blocks(["XRP/USD"], D0, D0 + 20 * DAY)
    n = 1000
    rng = random.Random(1)
    res = rq.bootstrap(bars, evs, blocks, rng, n=n)
    # recompute by hand with the same generator sequence
    rng2, vals = random.Random(1), []
    by_day = {}
    for e in evs:
        by_day.setdefault(e.ts // DAY, []).append(e)
    for _ in range(n):
        drawn = rng2.choices(blocks, k=len(blocks))
        es = [e for blk in drawn for e in by_day.get(blk[1], [])]
        vals.append(sum(rq.hit(e.outcome, e.direction, "fav") - 0.25 for e in es) / len(es))
    vals.sort()
    assert res["lower"] == pytest.approx(vals[int(n * rq.TAIL)])
    assert res["upper"] == pytest.approx(vals[int(n * (1 - rq.TAIL)) - 1])


def test_bootstrap_counts_undefined_resamples():
    bars, _ = _toy(n_days=20)
    blocks = rq.period_blocks(["XRP/USD"], D0, D0 + 20 * DAY)
    res = rq.bootstrap(bars, [_ev("ENTRY_SETUP", D0)], blocks, random.Random(rq.SEED), n=2000)
    # one event in one of 20 blocks: a resample misses it with probability (19/20)^20 ~ 0.358
    assert 0.30 < res["undefined"] / 2000 < 0.42 and res["defined"] + res["undefined"] == 2000


def test_two_day_blocks():
    assert rq.period_blocks(["X"], D0, D0 + 6 * DAY, rq.block_2day) == [("X", 0), ("X", 1), ("X", 2)]
    assert len(rq.period_blocks(["X", "Y"], D0, D0 + 6 * DAY)) == 12


# ------------------------------------------------------------------ analysis / decision
def _collected(n_days, hit_all=True):
    bars, evs = _toy(n_days, hit_all)
    return [{"symbol": "XRP/USD", "bars": bars, "events": evs, "bars_not_eligible": 3}]


def test_analyse_verdicts_by_period_and_sample():
    end = D0 + 20 * DAY
    conf = rq.analyse(_collected(20), D0, end, "confirmatory", n=300)
    f = conf["families"]["entry"]
    assert f["primary_events"] == 40 and f["blocks_with_events"] == 20
    assert f["verdict"] == "INFORMATIVE (lower > 0)" and f["delta"] == pytest.approx(0.75)
    assert rq.analyse(_collected(20, hit_all=False), D0, end, "confirmatory", n=300)["families"]["entry"][
        "verdict"] == "INCONCLUSIVE / NO"
    assert rq.analyse(_collected(20), D0, end, "exploratory", n=300)["families"]["entry"]["verdict"].startswith(
        "EXPLORATORY")
    small = rq.analyse(_collected(9), D0, D0 + 9 * DAY, "confirmatory", n=300)["families"]["entry"]
    assert small["verdict"].startswith("INSUFFICIENT")                 # 18 events < 30
    assert conf["families"]["retest"]["verdict"].startswith("INSUFFICIENT")    # no retest events
    assert conf["bars_not_eligible"] == 3 and set(conf["sensitivity_2day"]) == set(rq.FAMILIES)


def test_ambiguous_and_none_stay_in_denominators():
    bars = [rq.Bar("XRP/USD", D0 + k * DAY + h * H, o) for k in range(3) for h, o in ((0, "UP"), (1, "NONE"))]
    rep = rq.analyse([{"symbol": "XRP/USD", "bars": bars,
                       "events": [_ev("ENTRY_SETUP", D0, out="UP"), _ev("ENTRY_SETUP", D0 + DAY, out="AMBIGUOUS"),
                                  _ev("ENTRY_SETUP", D0 + 2 * DAY, out="NONE")],
                       "bars_not_eligible": 0}], D0, D0 + 3 * DAY, "confirmatory", n=50)
    r = rep["event_types"]["ENTRY_SETUP"]
    assert r["hit_rate"] == pytest.approx(1 / 3, abs=1e-4) and r["outcomes"]["AMBIGUOUS"] == pytest.approx(1 / 3, abs=1e-4)
    assert rep["families"]["entry"]["delta"] == pytest.approx(1 / 3 - 0.5)


def test_lead_times():
    evs = [_ev("ENTRY_WATCH", D0, out=None), _ev("ENTRY_WATCH", D0 + H, out=None), _ev("ENTRY_SETUP", D0 + 3 * H),
           _ev("ENTRY_SETUP", D0 + 5 * H), _ev("WATCH_CLEARED", D0 + 6 * H, out=None),
           _ev("ENTRY_WATCH", D0 + 10 * H, out=None), _ev("ENTRY_SETUP", D0 + 11 * H),
           _ev("ENTRY_SETUP", D0 + 12 * H, anchor="b")]       # different anchor, no ENTRY_WATCH
    lt = rq.lead_times(evs)
    assert lt["ENTRY_SETUP"]["n"] == 2 and lt["ENTRY_SETUP"]["median"] == 3
    assert lt["ENTRY_CONFIRMATION_CANDIDATE"]["n"] == 0


def test_report_formats():
    rep = rq.analyse(_collected(20), D0, D0 + 20 * DAY, "confirmatory", n=100)
    txt = rq.format_report(rep, {"rq6_confirmatory_xrp_1h.json": "ab" * 32})
    assert "execution NOT AUTHORIZED" in txt and "INFORMATIVE" in txt and "ENTRY_SETUP" in txt


# ------------------------------------------------------------------ end to end through replay()
def test_collect_runs_through_replay_and_has_no_look_ahead():
    d = _series(n=24 * 12, seed=11, start=D0 - 12 * DAY)
    start, end = D0 - 5 * DAY, D0 - 2 * DAY
    a = rq.collect("XRP/USD", d, {}, start, end)
    assert a["bars"] and all(start <= b.ts < end for b in a["bars"])
    assert all(start <= e.ts < end for e in a["events"])
    # change bars after end + 12h: events and eligible bars are unchanged
    ts = [t // 1000 for t in d.timestamps]
    cut = next(i for i, t in enumerate(ts) if t >= end + 13 * H)
    e = OHLCV(d.timestamps, d.opens, d.highs[:cut] + [x * 3 for x in d.highs[cut:]],
              d.lows[:cut] + [x / 3 for x in d.lows[cut:]], d.closes[:cut] + [x * 2 for x in d.closes[cut:]],
              d.volumes)
    b = rq.collect("XRP/USD", e, {}, start, end)
    assert [(x.event, x.ts, x.direction, x.outcome) for x in a["events"]] == \
           [(x.event, x.ts, x.direction, x.outcome) for x in b["events"]]
    assert [(x.ts, x.outcome) for x in a["bars"]] == [(x.ts, x.outcome) for x in b["bars"]]


def test_collect_drops_bars_near_a_gap():
    d = _series(n=24 * 12, seed=11, start=D0 - 12 * DAY, gap_at=24 * 9)
    start, end = D0 - 5 * DAY, D0 - 2 * DAY
    a = rq.collect("XRP/USD", d, {}, start, end)
    assert a["bars_not_eligible"] > 0


# ------------------------------------------------------------------ isolation
def test_imports_nothing_from_execution_paths():
    src = pathlib.Path(rq.__file__).read_text()
    mods = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom):
            mods.add(node.module or "")
        elif isinstance(node, ast.Import):
            mods |= {a.name for a in node.names}
    banned = ("execution", "order", "approval", "risk", "paper", "ledger", "telegram", "trade_plan")
    assert not [m for m in mods if any(b in m for b in banned)], mods
    assert "--execute" not in src
