"""VP-06 value-area re-entry (vp_reentry.py) and the RQ7 research driver -- synthetic data only."""
import hashlib
import pathlib
import random
import re
from types import SimpleNamespace

import pytest

from cdcx.backtest import vwap_vp_rq7 as rq7
from cdcx.exchange.cryptocom import OHLCV
from cdcx.volume_profile import prev_day, vp_reentry
from cdcx.volume_profile import vwap_confluence as vc

ROOT = pathlib.Path(__file__).resolve().parents[1]
T0 = 1_790_000_000 - 1_790_000_000 % 86400        # a UTC midnight


def _levels(n_prior, val=10.0, vah=12.0, n=None):
    """Window = all bars; 'today' starts at bar n_prior."""
    return SimpleNamespace(status="OK", val=val, vah=vah, session_end=T0 + n_prior * 3600,
                           avwap=SimpleNamespace(anchor_ts=T0, last_bar_ts=T0 + (n - 1) * 3600))


def _data(closes, highs=None, lows=None):
    n = len(closes)
    return OHLCV(timestamps=[(T0 + i * 3600) * 1000 for i in range(n)], opens=list(closes),
                 highs=highs or [c + 0.1 for c in closes], lows=lows or [c - 0.1 for c in closes],
                 closes=list(closes), volumes=[100.0] * n)


def _eval(closes, n_prior=2, require=True, **kw):
    d = _data(closes, **kw)
    return vp_reentry.evaluate(_levels(n_prior, n=len(closes)), d, require_inside_prior=require)


def test_reentry_events_need_a_close_outside_then_a_close_inside():
    assert vp_reentry.reentry_events([11, 9.5, 9.8, 10.5], 10, 12) == [(3, "bullish", 1)]
    assert vp_reentry.reentry_events([11, 12.5, 11.5, 13, 11], 10, 12) == [(2, "bearish", 1), (4, "bearish", 3)]
    assert vp_reentry.reentry_events([11, 11.5, 9.0], 10, 12) == []           # still outside
    assert vp_reentry.reentry_events([9.0, 11.0], 10, 12, start=1) == []       # excursion before `start` ignored


def test_prior_close_outside_is_not_applicable():
    e = _eval([11, 12.5, 9.5, 10.5])                                           # prior close (bar 1) above VAH
    assert e.setup.state == "N/A" and e.setup.direction is None and e.prior_inside is False


def test_pending_on_the_reentry_bar_with_far_edge_target_and_excursion_extreme():
    e = _eval([11, 11, 9.5, 9.6, 10.5], lows=[10.9, 10.9, 9.2, 9.4, 10.3])
    assert (e.setup.state, e.setup.direction) == ("PENDING", "bullish")
    assert e.target == 12.0 and e.extreme == 9.2 and e.prior_inside is True
    assert "target VAH 12" in e.setup.detail and "reference only" in e.setup.detail


def test_target_reached_failed_active_outside():
    base = [11, 11, 9.5, 10.5]
    assert _eval(base + [11.0, 11.95], highs=[11.1, 11.1, 9.6, 10.6, 11.1, 12.0]).setup.state == "TARGET REACHED"
    assert _eval(base + [10.2]).setup.state == "ACTIVE"
    assert _eval(base + [9.0]).setup.state == "OUTSIDE"                        # newest close outside again
    failed = _eval(base + [9.0, 9.1, 10.4])                                    # failed, then a NEW re-entry
    assert failed.setup.state == "PENDING"


def test_bearish_mirror():
    e = _eval([11, 11, 12.5, 11.5], highs=[11.1, 11.1, 12.8, 11.6])
    assert (e.setup.state, e.setup.direction, e.target, e.extreme) == ("PENDING", "bearish", 10.0, 12.8)


def test_wick_outside_is_not_an_excursion():
    e = _eval([11, 11, 10.2, 10.5], lows=[10.9, 10.9, 9.0, 10.3])              # low pierces VAL, close inside
    assert e.setup.state == "NONE"


def test_comparator_mode_keeps_prior_outside_reentries():
    e = _eval([11, 12.5, 9.5, 10.5], require=False)
    assert e.setup.state == "PENDING" and e.prior_inside is False


def test_unknown_inputs_fail_closed():
    assert vp_reentry.evaluate(SimpleNamespace(status="UNKNOWN", avwap=None), None).setup.state == "UNKNOWN"
    assert _eval([11, 11], n_prior=0).setup.state == "UNKNOWN"                 # no prior close


# --- isolation: VP-06 never enters classify(), the watcher (RQ6) or RQ3/RQ5 ------------------------

def _series(days=4, seed=7):
    rng = random.Random(seed)
    n = days * 24
    start = T0 - (days - 1) * 86400
    c, p = [], 1.30
    for _ in range(n):
        p *= 1 + rng.uniform(-0.012, 0.012)
        c.append(p)
    o = [c[0]] + c[:-1]
    return OHLCV(timestamps=[(start + i * 3600) * 1000 for i in range(n)], opens=o,
                 highs=[max(a, b) * 1.003 for a, b in zip(o, c)], lows=[min(a, b) * 0.997 for a, b in zip(o, c)],
                 closes=c, volumes=[rng.uniform(100, 1000) for _ in range(n)])


def test_classify_setups_are_still_vp01_to_vp05():
    d = _series()
    now = d.timestamps[-1] / 1000 + 3600
    lv = prev_day.prev_day_levels(d, "1h", now=now)
    assert lv.status == "OK"
    assert [s.code for s in vc.classify(lv, d).setups] == ["VP-01", "VP-02", "VP-03", "VP-04", "VP-05"]


def test_section_prints_vp06_under_vp05_and_decision_is_unchanged():
    d = _series()
    now = d.timestamps[-1] / 1000 + 3600
    lv = prev_day.prev_day_levels(d, "1h", now=now)
    res = vc.classify(lv, d)
    plain = vc.format_vwap_vp("T/USD", "1h", lv, res, d.closes[-1])
    with_r = vc.format_vwap_vp("T/USD", "1h", lv, res, d.closes[-1], research=[vp_reentry.value_area_reentry(lv, d)])
    lines = with_r.splitlines()
    i5 = next(i for i, x in enumerate(lines) if x.startswith("VP-05"))
    assert lines[i5 + 1].startswith("VP-06 Value-area re-entry") and lines[i5 + 1].endswith(vp_reentry.TAG)
    assert [x for x in lines if not x.startswith("VP-06")] == plain.splitlines()


@pytest.mark.parametrize("path", ["cdcx/volume_profile/vwap_watch.py", "cdcx/backtest/vwap_vp_research.py",
                                  "cdcx/backtest/vwap_vp_rq5.py", "cdcx/volume_profile/vwap_confluence.py"])
def test_trade_and_research_paths_do_not_score_vp06(path):
    src = (ROOT / path).read_text(encoding="utf-8")
    if path.endswith("vwap_confluence.py"):   # display layer only: imported inside the two formatters
        assert "value_area_reentry" not in src.split("def classify(")[1].split("\ndef ")[0]
    else:
        assert "vp_reentry" not in src


def test_rq6_frozen_files_unchanged():
    frozen = re.search(r"vwap_watch\.py=([0-9a-f]{64}) vwap_watch_rq6\.py=([0-9a-f]{64})",
                       (ROOT.parent / ".ai/SHARED/research_questions.md").read_text(encoding="utf-8"))
    for rel, want in (("cdcx/volume_profile/vwap_watch.py", frozen.group(1)),
                      ("cdcx/backtest/vwap_watch_rq6.py", frozen.group(2))):
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == want, rel


# --- RQ7 driver ---------------------------------------------------------------------------------

def test_signals_are_walk_forward_no_lookahead():
    d = _series(days=6, seed=11)
    full = rq7.find_reentry_signals(d)
    cut = len(d.closes) - 20
    prefix = rq7.find_reentry_signals(rq7.vr._slice(d, 0, cut))
    assert {s[1] for s in full} == {"VP-06", "VP-06x"} and any(s[0] >= cut for s in full)   # not vacuous
    assert [s for s in full if s[0] < cut] == prefix
    for t, name, direction, target, extreme in full:
        assert name in ("VP-06", "VP-06x") and direction in ("bullish", "bearish")


def test_far_edge_outcome_target_stop_same_bar_and_horizon():
    d = _data([10.5, 10.5, 11.0, 12.5], highs=[10.6, 10.6, 11.1, 12.6], lows=[10.4, 10.4, 10.9, 12.4])
    assert rq7.far_edge_outcome(d, (0, "VP-06", "bullish", 12.0, 9.5))["result"] == "target"
    both = _data([10.5, 10.5, 11.0], highs=[10.6, 10.6, 12.5], lows=[10.4, 10.4, 9.0])
    assert rq7.far_edge_outcome(both, (0, "VP-06", "bullish", 12.0, 9.5)) == {"result": "stop", "r": -1.0, "bars": 2}
    flat = _data([10.5] * 5)
    out = rq7.far_edge_outcome(flat, (0, "VP-06", "bullish", 12.0, 9.5), horizon=3)
    assert out["result"] == "horizon" and out["r"] == 0.0
    assert rq7.far_edge_outcome(flat, (0, "VP-06", "bullish", 10.0, 9.5)) is None   # next open beyond target


def test_verdict_needs_sample_and_a_positive_lower_bound():
    assert rq7.verdict(10, (0.1, 0.5), 40, (0.1, 0.2))["primary"].startswith("insufficient sample")
    assert rq7.verdict(40, (-0.1, 0.5), 40, (0.1, 0.2))["primary"].startswith("no evidence")
    v = rq7.verdict(40, (0.05, 0.5), 40, (0.01, 0.2))
    assert v["primary"].startswith("positive") and v["precondition"] == "the precondition adds information"
