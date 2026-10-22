"""VP-04P breakout -> pullback hold -> BOS (vp_breakout_pullback.py) and the RQ8 driver -- synthetic data only."""
import pathlib

import pytest

from cdcx.backtest import vwap_vp_rq8 as rq8
from cdcx.indicators import atr_ema_variant1
from cdcx.volume_profile import vp_breakout_pullback as bp

ROOT = pathlib.Path(__file__).resolve().parents[1]
VAL, VAH = 10.0, 12.0


def _bars(extra, base=25):
    """`base` quiet bars inside the value area (range 0.2, volume 100), then `extra` (h, l, c, v) bars."""
    h = [11.1] * base
    l = [10.9] * base
    c = [11.0] * base
    v = [100.0] * base
    c[-1] = 11.9
    h[-1], l[-1] = 12.0, 11.8
    for hi, lo, cl, vo in extra:
        h.append(hi), l.append(lo), c.append(cl), v.append(vo)
    return h, l, c, v, atr_ema_variant1.calculate_atr(h, l, c)


def _scan(extra, mirror=False, p=bp.DEFAULT):
    h, l, c, v, atr = _bars(extra)
    if mirror:                                  # reflect around 11: VAH <-> VAL, highs <-> lows
        h, l, c = [22 - x for x in l], [22 - x for x in h], [22 - x for x in c]
    return bp.scan(h, l, c, v, atr, VAL, VAH, start=25, p=p)


BREAK = (12.6, 11.9, 12.5, 300.0)             # range 0.7 >> ATR, volume 3x -> HEALTHY
HOLD = (12.7, 12.45, 12.6, 120.0)              # no touch yet
TOUCH = (12.6, 12.03, 12.2, 120.0)             # low within 0.25 ATR of VAH, close above the hold line
BOS = (13.0, 12.5, 12.9, 150.0)                # close above max(high since break) + 0.25 ATR


def test_healthy_break_pullback_bos_triggers():
    ep = _scan([BREAK, HOLD, TOUCH, BOS])[-1]
    assert (ep.label, ep.state, ep.direction) == ("HEALTHY", "TRIGGERED", "bullish")
    assert (ep.break_index, ep.pullback_index, ep.end_index) == (25, 27, 28)
    assert ep.bos_level == pytest.approx(12.7 + 0.25 * ep.atr)


def test_bearish_mirror_triggers():
    ep = _scan([BREAK, HOLD, TOUCH, BOS], mirror=True)[-1]
    assert (ep.state, ep.direction, ep.level) == ("TRIGGERED", "bearish", VAL)


@pytest.mark.parametrize("bar, label", [((12.6, 11.9, 12.5, 100.0), "NORMAL"),
                                        ((12.05, 11.97, 12.02, 300.0), "ABSORPTION"),
                                        ((12.6, 11.9, 12.5, 50.0), "NO SUPPLY")])
def test_only_a_healthy_break_can_trigger(bar, label):
    ep = _scan([bar, HOLD, TOUCH, BOS])[0]
    assert (ep.label, ep.state) == (label, "WEAK BREAK")


def test_deep_pullback_fails():
    assert _scan([BREAK, HOLD, (12.6, 11.7, 11.9, 120.0), BOS])[0].state == "FAILED"     # close back inside
    assert _scan([BREAK, HOLD, (12.6, 11.80, 12.2, 120.0), BOS])[0].state == "FAILED"    # wick > 0.5 ATR inside


def test_no_bos_within_max_bars_expires_and_open_episode_is_pending():
    ep = _scan([BREAK, HOLD, TOUCH] + [(12.6, 12.3, 12.4, 100.0)] * 12)[0]
    assert ep.state == "EXPIRED" and ep.end_index == 25 + bp.DEFAULT.max_bars
    assert _scan([BREAK, HOLD, TOUCH])[0].state == "PULLBACK"
    assert _scan([BREAK])[0].state == "BREAK"


def test_bos_needs_the_pullback_first():
    assert _scan([BREAK, BOS])[0].state == "BREAK"        # BOS-sized close without a pullback is not a trigger


def test_params_move_the_thresholds():
    assert _scan([BREAK, HOLD, TOUCH, BOS], p=bp.Params(effort_high=4.0))[0].state == "WEAK BREAK"
    assert _scan([BREAK, HOLD, TOUCH, BOS], p=bp.Params(touch_atr=0.0))[0].state == "BREAK"


def test_too_little_history_is_unknown_not_healthy():
    h, l, c, v, atr = _bars([BREAK], base=12)
    assert bp.scan(h, l, c, v, atr, VAL, VAH, start=12)[0].label == "UNKNOWN"


@pytest.mark.parametrize("path", ["cdcx/volume_profile/vwap_watch.py", "cdcx/backtest/vwap_vp_research.py",
                                  "cdcx/backtest/vwap_vp_rq5.py"])
def test_trade_and_research_paths_do_not_score_vp04p(path):
    assert "vp_breakout_pullback" not in (ROOT / path).read_text(encoding="utf-8")


def test_classify_does_not_call_vp04p():
    src = (ROOT / "cdcx/volume_profile/vwap_confluence.py").read_text(encoding="utf-8")
    assert "breakout_pullback" not in src.split("def classify(")[1].split("\ndef ")[0]


def test_rq8_signals_are_walk_forward_no_lookahead():
    from test_vp_reentry import _series
    d = _series(days=6, seed=5)
    loose = bp.Params(effort_high=1.0, result_big=0.5, touch_atr=0.5, hold_wick_atr=1.5, hold_close_atr=1.0)
    full = rq8.find_signals(d, p=loose)
    cut = len(d.closes) - 20
    assert full, "loosened parameters should fire on the synthetic series"
    assert [s for s in full if s[0] < cut] == rq8.find_signals(rq8.vr._slice(d, 0, cut), p=loose)


def test_rq8_verdict():
    assert rq8.verdict(10, (0.1, 0.2), 50, (0.1, 0.2))["primary"].startswith("insufficient")
    assert rq8.verdict(40, (0.01, 0.2), 50, (-0.1, 0.2))["vs_vp04"].startswith("no evidence")


def test_rq8_frozen_files_unchanged():
    import hashlib
    import re
    frozen = re.search(r"vp_breakout_pullback\.py=([0-9a-f]{64}) vwap_vp_rq8\.py=([0-9a-f]{64})",
                       (ROOT.parent / ".ai/SHARED/research_questions.md").read_text(encoding="utf-8"))
    for rel, want in (("cdcx/volume_profile/vp_breakout_pullback.py", frozen.group(1)),
                      ("cdcx/backtest/vwap_vp_rq8.py", frozen.group(2))):
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == want, rel
