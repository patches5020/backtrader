import pathlib

import pytest

from cdcx import avp_rejection as ar

ALL_CLOSED = float("inf")
LEVELS = ar.AvpProfile(anchor_index=0, poc=105.0, vah=110.0, val=100.0)


@pytest.fixture
def fixed_profile(monkeypatch):
    """Isolate the rejection logic from volume-profile math: AVP levels are
    pinned to POC 105 / VAH 110 / VAL 100."""
    monkeypatch.setattr(ar, "anchored_profile", lambda h, l, v, anchor, end=None: LEVELS)
    monkeypatch.setattr(ar, "anchor_at_decline_start", lambda h, l: 0)


def _series(tail):
    """40 warm-up bars around 104 (range 2 -> ATR ~2), then `tail`, a list
    of (close, low) or close; highs are close + 1, lows default close - 1."""
    closes, lows = [104.0 + (0.3 if i % 2 else -0.3) for i in range(40)], []
    lows = [c - 1 for c in closes]
    for item in tail:
        c, low = item if isinstance(item, tuple) else (item, item - 1)
        closes.append(float(c))
        lows.append(float(low))
    highs = [c + 1 for c in closes]
    volumes = [1000.0] * len(closes)
    ts = [i * 3_600_000 for i in range(len(closes))]
    return ts, highs, lows, closes, volumes


def _classify(tail, volumes_override=None):
    ts, h, l, c, v = _series(tail)
    if volumes_override:
        for i, vol in volumes_override.items():
            v[i] = vol
    return ar.classify_avp_rejection(ts, h, l, c, v, "1h", symbol="XRP/USD", now=ALL_CLOSED)


# --- states ----------------------------------------------------------------------

def test_no_reclaim_is_none(fixed_profile):
    assert _classify([103, 102.5, 102.8]).state == "NONE"


def test_reclaim_on_newest_candle_is_pending(fixed_profile):
    r = _classify([101.5, 100.4, (100.6, 99.3)])
    assert (r.state, r.level_name) == ("PENDING", "VAL")
    assert r.plan is None  # no paper trade until the hold candle closes


def test_reclaim_then_hold_is_confirmed_with_existing_risk_model(fixed_profile):
    r = _classify([101.5, 100.4, (100.6, 99.3), 101.2])
    assert r.state == "CONFIRMED" and r.level_name == "VAL"
    p = r.plan
    assert p.entry_type == "confirmation" and p.entry == 101.2
    assert p.stop == pytest.approx(p.entry - 1.5 * p.atr)                      # protected 1.5x ATR
    risk_r = p.entry - p.stop
    assert [round((t - p.entry) / risk_r, 6) for t in p.take_profits] == [2.2, 2.6, 3.2, 4.5]  # protected ladder
    assert p.close_pcts == [25.0, 25.0, 25.0, 25.0]
    assert r.rejection_low > p.stop                                            # stop below the rejection low


def test_reclaim_then_close_back_below_is_failed(fixed_profile):
    r = _classify([101.5, 100.4, (100.6, 99.3), 101.2, 99.4])
    assert r.state == "FAILED" and r.plan is None


def test_wick_that_never_closes_above_is_not_a_reclaim(fixed_profile):
    assert _classify([101.5, (99.8, 99.0), (99.6, 98.9)]).state == "NONE"  # intrabar only


def test_rejection_low_beyond_the_atr_stop_is_rejected_not_widened(fixed_profile):
    r = _classify([101.5, 100.4, (100.6, 94.0), 101.2])
    assert r.state == "REJECTED" and r.plan is None
    assert "Not widened" in r.reasons[0]


def test_held_retest_becomes_the_entry(fixed_profile):
    r = _classify([101.5, 100.4, (100.6, 99.3), 101.2, 102.5, (101.8, 100.5)])
    assert r.state == "CONFIRMED" and r.evidence["retest_held"]
    assert (r.plan.entry_type, r.plan.entry) == ("retest", 101.8)


def test_volume_and_upper_close_evidence(fixed_profile):
    # reclaim bar (index 42): close 100.9 in a 99.3..101.9 range -> 62% up the range; volume 2x
    r = _classify([101.5, 100.4, (100.9, 99.3), 101.2], volumes_override={42: 2000.0})
    assert r.evidence["volume_confirmed"] and r.evidence["upper_close"]


def test_forming_candle_is_ignored(fixed_profile):
    ts, h, l, c, v = _series([101.5, 100.4, (100.6, 99.3), 101.2])
    still_forming = ts[-1] / 1000 + 1800
    r = ar.classify_avp_rejection(ts, h, l, c, v, "1h", now=still_forming)
    assert r.state == "PENDING"  # the hold candle is still open, so it doesn't count yet


# --- anchor --------------------------------------------------------------------

def test_anchor_is_the_top_the_decline_started_from():
    highs = [100, 105, 120, 118, 110, 104, 99, 101]
    lows = [h - 2 for h in highs]
    assert ar.anchor_at_decline_start(highs, lows, lookback=100) == 2


def test_anchor_stays_put_while_price_makes_new_lows():
    highs = [100, 120, 115, 110, 105]
    lows = [h - 2 for h in highs]
    first = ar.anchor_at_decline_start(highs, lows)
    assert ar.anchor_at_decline_start(highs + [95, 90], lows + [93, 88]) == first


# --- paper outcome: trade_manager rules G / H / I ---------------------------------

def _plan():
    return ar.TradePlan(entry_type="confirmation", entry_index=0, entry=100.0, stop=97.0,
                        take_profits=[106.6, 107.8, 109.6, 113.5], tp_ratios=[2.2, 2.6, 3.2, 4.5],
                        close_pcts=[25.0, 25.0, 25.0, 25.0], atr=2.0, atr_multiplier=1.5)


def _replay(bars):
    highs = [100.0] + [b[0] for b in bars]
    lows = [100.0] + [b[1] for b in bars]
    return ar.simulate_outcome(_plan(), highs, lows)


def test_outcome_stopped_is_minus_one_r():
    o = _replay([(101, 96)])
    assert (o.status, o.r_multiple, o.tps_hit) == ("stopped", -1.0, 0)


def test_outcome_all_four_targets():
    o = _replay([(114, 101)])
    assert (o.status, o.tps_hit) == ("tp4", 4)
    assert o.r_multiple == pytest.approx(0.25 * (2.2 + 2.6 + 3.2 + 4.5))


def test_outcome_tp1_then_giveback_exit_rule_i():
    # after TP1 the stop is BE + 20% of (TP1 - BE) = 101.32 -> remaining 75% exits there
    o = _replay([(107, 102), (103, 101)])
    assert o.status == "stopped" and o.tps_hit == 1
    assert o.r_multiple == pytest.approx(0.25 * 2.2 + 0.75 * (1.32 / 3))


def test_outcome_tp2_then_stop_at_tp1_rule_h():
    o = _replay([(108, 104), (107, 106)])
    assert o.status == "stopped" and o.tps_hit == 2
    assert o.r_multiple == pytest.approx(0.25 * 2.2 + 0.25 * 2.6 + 0.5 * (6.6 / 3))


def test_outcome_same_bar_stop_and_target_assumes_stop_first():
    assert _replay([(107, 96)]).status == "stopped"


def test_outcome_still_open():
    o = _replay([(103, 99)])
    assert (o.status, o.r_multiple) == ("open", 0.0)


# --- paper only ------------------------------------------------------------------

def test_avp_rejection_never_reaches_the_trade_gate():
    cdcx_dir = pathlib.Path(ar.__file__).parent
    for gate in ("confluence.py", "entry_checklist.py", "entry_location.py", "no_trade_gate.py",
                 "no_trade_filter.py", "risk.py", "engine.py", "regime.py", "trade_manager.py",
                 "live_execution.py", "paper_approval.py"):
        assert "avp_rejection" not in (cdcx_dir / gate).read_text(), gate
