import math
import pathlib

from cdcx import vp_bos

ALL_CLOSED = 10**12  # a "now" far past every bar: nothing is still forming


def _series(tail, ts_unit_ms=True):
    """60 bars of a clean sine range (swing low ~97.7), then `tail`."""
    closes = [100 + 2 * math.sin(i / 3) for i in range(60)] + list(tail)
    highs = [c + 0.3 for c in closes]
    lows = [c - 0.3 for c in closes]
    volumes = [100.0] * 60 + [300.0] * len(tail)
    step = 3600_000 if ts_unit_ms else 3600
    timestamps = [i * step for i in range(len(closes))]
    return timestamps, highs, lows, closes, volumes


def _classify(tail, now=ALL_CLOSED, ts_unit_ms=True):
    return vp_bos.classify_vp_bos(*_series(tail, ts_unit_ms), "1h", now=now)


def test_sustained_break_with_volume_beyond_is_vp_bos():
    r = _classify([97, 95, 94, 93.5, 93.2, 93, 92.8, 92.9])
    assert r.signal == "VP-BOS-BEAR"
    assert r.acceptance == "CONFIRMED"
    assert r.status == "BEARISH"
    assert r.evidence["sustained"] and r.evidence["new_hvn_beyond"]


def test_break_that_closes_back_through_is_failed_not_vp_bos():
    r = _classify([97, 95, 99])
    assert r.signal == "BOS-FAILED"
    assert r.acceptance == "REJECTED"
    assert r.status == "TRANSITIONAL"


def test_fresh_break_without_acceptance_yet_is_pending():
    # Closed beyond the level (a real BOS) but only 1 bar old -- the
    # market hasn't shown it's doing business down there yet.
    r = _classify([95])
    assert r.signal == "BOS-PENDING"
    assert r.acceptance == "NOT CONFIRMED"
    assert r.bos_label == "BEAR PENDING"
    assert r.status == "TRANSITIONAL"


def test_forming_candle_is_ignored_ms_timestamps():
    ts, *_ = _series([95])
    still_forming = ts[-1] / 1000 + 1800  # halfway through the last 1h bar
    r = _classify([95], now=still_forming)
    assert r.signal == "NONE"
    assert r.level_price is None


def test_forming_candle_is_ignored_seconds_timestamps():
    # robinhood_equity returns seconds, not milliseconds.
    ts, *_ = _series([95], ts_unit_ms=False)
    r = _classify([95], now=ts[-1] + 1800, ts_unit_ms=False)
    assert r.level_price is None
    # ...and once that bar has closed it counts.
    assert _classify([95], now=ts[-1] + 7200, ts_unit_ms=False).signal == "BOS-PENDING"


def test_section_counts_vp_bos_confluence():
    bear = _classify([97, 95, 94, 93.5, 93.2, 93, 92.8, 92.9])
    failed = _classify([97, 95, 99])
    text = vp_bos.format_vp_bos_section("TEST", {"1w": bear, "1d": bear, "4h": failed, "1h": None})
    assert "VP-BOS CONFIRMED: 2/4  (bull 0, bear 2)" in text
    assert "DIRECTION: BEARISH" in text
    assert "BOS-FAILED:       1/4" in text
    assert "BOS-PENDING:      0/4" in text
    assert "ERROR" in text  # a missing series is a row, not a crash


def test_vp_bos_is_informational_only():
    # Nothing on the decision path may read VP-BOS until that is a
    # deliberate, reviewed change (see the XRP baseline test).
    cdcx_dir = pathlib.Path(vp_bos.__file__).parent
    for gate in ("confluence.py", "entry_checklist.py", "entry_location.py", "no_trade_gate.py",
                 "risk.py", "engine.py", "regime.py", "trade_manager.py", "live_execution.py"):
        assert "vp_bos" not in (cdcx_dir / gate).read_text(), gate


def test_marginal_close_past_the_swing_is_none_with_a_raw_note():
    # Closes just under the ~97.7 swing low -- inside the 0.25x ATR margin.
    ts, highs, lows, closes, volumes = _series([97.6])
    r = vp_bos.classify_vp_bos(ts, highs, lows, closes, volumes, "1h", now=ALL_CLOSED)
    assert r.signal == "NONE"
    assert r.raw_note and "raw bearish flag" in r.raw_note
    text = vp_bos.format_vp_bos_section("TEST", {"1h": r})
    assert "not a BOS" in text and "BOS-PENDING:      0/1" in text


# --- temporal causality invariant: break_index > swing_index -----------------

def test_causality_a_break_after_the_swing_forms_is_reported_with_both_indexes():
    # The "close BEFORE the swing forms must not count" direction is
    # test_bos_state.py::test_close_beyond_the_level_before_the_swing_formed_is_not_a_break.
    r = _classify([97, 95, 99])  # swing low forms, later closes break it, then reclaim
    assert r.break_index > r.swing_index


def test_causality_invariant_holds_across_random_series():
    import random

    from cdcx.bos_state import classify_bos_state
    from cdcx.indicators import market_structure

    rng = random.Random(7)
    checked_bos = checked_vp = 0
    for _ in range(300):
        price, closes = 100.0, []
        for _ in range(120):
            price += rng.gauss(0, 1)
            closes.append(price)
        highs = [c + abs(rng.gauss(0, 0.6)) for c in closes]
        lows = [c - abs(rng.gauss(0, 0.6)) for c in closes]
        volumes = [rng.uniform(500, 1500) for _ in closes]
        ms = market_structure.analyze(highs, lows, price=closes[-1])
        bos = classify_bos_state(ms, highs, lows, closes, volumes)
        if bos.break_index is not None:
            checked_bos += 1
            assert bos.break_index > bos.swing_index
        ts = [i * 3600_000 for i in range(len(closes))]
        r = vp_bos.classify_vp_bos(ts, highs, lows, closes, volumes, "1h", now=ALL_CLOSED)
        if r.break_index is not None:
            checked_vp += 1
            assert r.break_index > r.swing_index
    assert checked_bos > 20 and checked_vp > 20  # the invariant was actually exercised
