"""VP-01F first-touch POC filter (vp_first_touch.py) and the RQ9 driver -- synthetic data only."""
import pathlib
import random

import pytest

from cdcx.backtest import vwap_vp_rq9 as rq9
from cdcx.volume_profile import vp_first_touch as ft
from cdcx.volume_profile import vwap_confluence as vc

ROOT = pathlib.Path(__file__).resolve().parents[1]
POC, VAL, VAH = 11.0, 10.0, 12.0
ATR = [0.2] * 40


def _today(bars, prior_close=12.5):
    """Bar 0 = the prior session's last bar; `bars` (h, l, c, v) are today's, t0 = 1."""
    h, l, c, v = [prior_close + 0.1], [prior_close - 0.1], [prior_close], [100.0]
    for hi, lo, cl, vo in bars:
        h.append(hi), l.append(lo), c.append(cl), v.append(vo)
    return h, l, c, v


AWAY = (12.4, 12.1, 12.3, 100.0)            # far above the POC zone
REJECT = (11.1, 10.8, 10.9, 150.0)          # high >= POC > close: bearish reaction, volume up


def _checks(bars, prior_close=12.5):
    h, l, c, v = _today(bars, prior_close)
    return ft.checks(h, l, c, v, ATR, POC, VAL, VAH, t0=1)


def test_all_three_pass():
    i, d, f1, f2, f3 = _checks([AWAY, AWAY, REJECT])
    assert (i, d, f1, f2, f3) == (3, "bearish", True, True, True)


def test_each_check_can_fail_on_its_own():
    assert _checks([AWAY, AWAY, REJECT], prior_close=11.5)[2] is False             # F1: prior close inside
    assert _checks([AWAY, (11.2, 11.03, 11.1, 100.0), REJECT])[3] is False         # F2: earlier bar in the zone
    assert _checks([AWAY, AWAY, (11.1, 10.8, 10.9, 90.0)])[4] is False             # F3: volume not up
    assert _checks([AWAY, (11.3, 11.06, 11.2, 100.0), REJECT])[3] is True          # just outside the 0.05 zone


def test_no_reaction_is_none():
    assert _checks([AWAY, AWAY]) is None


def test_reaction_scan_matches_vp01_rule():
    rng = random.Random(3)
    for _ in range(300):
        c = [11 + rng.uniform(-0.6, 0.6) for _ in range(9)]
        h = [x + rng.uniform(0, 0.4) for x in c]
        l = [x - rng.uniform(0, 0.4) for x in c]
        t0 = rng.randint(1, 8)
        th, tl, tc = h[t0:], l[t0:], c[t0:]
        ref = vc._level_reaction("VP-01", "POC reaction", POC, th[-vc.REACTION_BARS:], tl[-vc.REACTION_BARS:],
                                 tc[-vc.REACTION_BARS:])
        mine = ft.reaction_index(h, l, c, POC, t0)
        assert (mine[1] if mine else None) == ref.direction


def test_rq9_annotation_agrees_with_vp01_signals():
    from test_vp_reentry import _series
    d = _series(days=6, seed=5)
    sigs = [s for s in rq9.vr.find_signals(d, "1h") if s[1] == "VP-01"]
    assert sigs, "synthetic series should produce VP-01 signals"
    notes = rq9.annotate(d, sigs)
    assert all(notes[t] is not None for t, _, _ in sigs)          # same reaction, same direction
    assert all(isinstance(notes[t].passed, bool) for t, _, _ in sigs)


def test_rq9_verdict_follows_rq5_rule():
    assert rq9.verdict(10, 50, (0.1, 0.2), 10, (0.1, 0.2))["information"].startswith("insufficient")
    v = rq9.verdict(40, 50, (0.05, 0.3), 40, (-0.1, 0.3))
    assert v == {"information": "the filter adds information", "worth_proposing": False}
    assert rq9.verdict(40, 50, (0.05, 0.3), 40, (0.01, 0.3))["worth_proposing"] is True


@pytest.mark.parametrize("path", ["cdcx/volume_profile/vwap_watch.py", "cdcx/backtest/vwap_vp_research.py",
                                  "cdcx/backtest/vwap_vp_rq5.py"])
def test_trade_and_research_paths_do_not_score_vp01f(path):
    assert "vp_first_touch" not in (ROOT / path).read_text(encoding="utf-8")


def test_classify_does_not_call_vp01f():
    src = (ROOT / "cdcx/volume_profile/vwap_confluence.py").read_text(encoding="utf-8")
    assert "first_touch" not in src.split("def classify(")[1].split("\ndef ")[0]


def test_rq9_frozen_files_unchanged():
    import hashlib
    import re
    frozen = re.search(r"vp_first_touch\.py=([0-9a-f]{64}) vwap_vp_rq9\.py=([0-9a-f]{64})",
                       (ROOT.parent / ".ai/SHARED/research_questions.md").read_text(encoding="utf-8"))
    for rel, want in (("cdcx/volume_profile/vp_first_touch.py", frozen.group(1)),
                      ("cdcx/backtest/vwap_vp_rq9.py", frozen.group(2))):
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == want, rel
