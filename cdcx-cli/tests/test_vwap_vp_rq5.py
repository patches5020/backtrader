"""RQ5 research harness: pre-registered filter definitions, bootstrap helpers, causality."""

import random

import pytest

from cdcx.backtest import vwap_vp_rq5 as rq5
from cdcx.exchange.cryptocom import OHLCV


def test_filter_a_needs_rising_adx_and_matching_di():
    adx = [0, 0, 0, 20, 21, 22, 24]
    pdi = [0] * 6 + [30]
    mdi = [0] * 6 + [10]
    assert rq5.filter_a(adx, pdi, mdi, 6, "bullish") is True        # 24 > 20, +DI leads
    assert rq5.filter_a(adx, pdi, mdi, 6, "bearish") is False       # -DI does not lead
    flat = [0, 0, 0, 24, 21, 22, 24]
    assert rq5.filter_a(flat, pdi, mdi, 6, "bullish") is False      # tie over 3 bars fails
    assert rq5.filter_a(adx, pdi, mdi, 2, "bullish") is False       # before enough history
    assert rq5.filter_a([0, 0, 0, 0, 1, 2, 3], pdi, mdi, 6, "bullish") is False   # undefined ADX[t-3] fails


def test_filter_b_rsi_side_of_50_ties_fail():
    assert rq5.filter_b([55.0], 0, "bullish") is True
    assert rq5.filter_b([45.0], 0, "bearish") is True
    assert rq5.filter_b([50.0], 0, "bullish") is False
    assert rq5.filter_b([50.0], 0, "bearish") is False
    assert rq5.filter_b([float("nan")], 0, "bullish") is False


def test_bootstrap_intervals_cover_the_mean_and_are_seeded():
    xs = [1.0, -1.0, 0.5, -0.5, 2.0, -1.0] * 20
    lo, hi = rq5.bootstrap_mean_ci(xs)
    mean = sum(xs) / len(xs)
    assert lo < mean < hi
    assert (lo, hi) == rq5.bootstrap_mean_ci(xs)                    # fixed seed -> reproducible
    assert rq5.bootstrap_mean_ci([1.0]) == (None, None)
    a, b = [1.0] * 50 + [0.9] * 50, [-1.0] * 50 + [-0.9] * 50
    dlo, dhi = rq5.bootstrap_diff_ci(a, b)
    assert dlo > 0 and dhi < 2.1
    assert rq5.bootstrap_diff_ci([1.0], b) == (None, None)


def _series(n, seed=1):
    rng = random.Random(seed)
    c, out = 1.0, []
    for _ in range(n):
        c *= 1 + rng.uniform(-0.01, 0.01)
        out.append(c)
    o = [out[0]] + out[:-1]
    return OHLCV(timestamps=[1_700_000_000 + 3600 * i for i in range(n)], opens=o,
                 highs=[max(a, b) * 1.003 for a, b in zip(o, out)], lows=[min(a, b) * 0.997 for a, b in zip(o, out)],
                 closes=out, volumes=[100.0] * n)


def test_annotation_is_causal_future_bars_do_not_change_it():
    d = _series(400)
    sigs = [(t, "VP-04", "bullish" if t % 2 else "bearish") for t in range(120, 300, 7)]
    full = rq5.annotate(d, sigs)
    cut = OHLCV(*(getattr(d, k)[:301] for k in ("timestamps", "opens", "highs", "lows", "closes", "volumes")))
    assert rq5.annotate(cut, sigs) == full


def test_verdict_follows_the_preregistered_rule():
    def pf(dlo, rlo):
        return {"A": {"diff_ci": [dlo, 1.0], "refiltered": {"ci": [rlo, 1.0]}}}
    assert rq5.verdict(pf(None, None), "A").startswith("INCONCLUSIVE")
    assert rq5.verdict(pf(-0.01, 0.2), "A").startswith("NO EVIDENCE")
    assert rq5.verdict(pf(0.0, 0.2), "A").startswith("NO EVIDENCE")      # touching 0 is not "above 0"
    assert "not proposed" in rq5.verdict(pf(0.05, -0.01), "A")
    assert "may be proposed" in rq5.verdict(pf(0.05, 0.01), "A")


def test_report_runs_end_to_end_on_synthetic_data(monkeypatch):
    d = _series(600, seed=3)
    monkeypatch.setattr(rq5, "vp04_signals", lambda data: [(t, "VP-04", "bullish" if t % 3 else "bearish")
                                                            for t in range(150, 560, 9)])
    per = []
    for sym in rq5.SYMBOLS:
        r = rq5.run_symbol(sym, d)
        for t in r["baseline"]:
            t._symbol = sym
        per.append(r)
    s = rq5.summarize(per)
    text = rq5.format_report(s, {"XRP/USD": "0" * 64, "XLM/USD": "1" * 64})
    assert "DECISION" in text and "A ADX:" in text and "B RSI:" in text
    pooled = s["pooled"]["POOLED"]
    for which in ("fresh", "seen"):
        for f in "AB":
            row = pooled[which][f]
            assert row["pass"]["trades"] + row["fail"]["trades"] == pooled[which]["baseline"]["trades"]
