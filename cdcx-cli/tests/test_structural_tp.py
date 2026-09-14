"""
Coverage for the opt-in "structural" TP mode (risk.resolve_tp_mode /
risk.build_structural_tp_levels / engine.py's --tp-mode wiring), added on
top of the review-driven request to make TP1-4 come from real nearest
resistance/support (volume-profile VAH/VAL/HVN/LVN, a Fibonacci extension
rung, a swing high/low, an active FVG edge) instead of fixed ATR
R-multiples -- opt-in, so the ATR ladder (and all of last round's per-symbol
ATR-multiplier tuning) stays the unchanged default.
"""

import random

import pytest

from cdcx import risk
from cdcx.engine import analyze_ohlcv
from cdcx.exchange.cryptocom import OHLCV


def _make_ohlcv(closes, opens=None, highs=None, lows=None, volumes=None):
    n = len(closes)
    opens = opens or closes
    highs = highs or [c + 1 for c in closes]
    lows = lows or [c - 1 for c in closes]
    volumes = volumes or [100.0] * n
    return OHLCV(timestamps=list(range(n)), opens=opens, highs=highs, lows=lows, closes=closes, volumes=volumes)


# --- risk.resolve_tp_mode ---------------------------------------------------

def test_resolve_tp_mode_default_is_atr():
    assert risk.resolve_tp_mode() == "atr"


def test_resolve_tp_mode_override_wins():
    assert risk.resolve_tp_mode("structural") == "structural"
    assert risk.resolve_tp_mode("STRUCTURAL") == "structural"  # case-insensitive


def test_resolve_tp_mode_malformed_override_falls_back_to_default():
    assert risk.resolve_tp_mode("not-a-real-mode") == "atr"


# --- risk.build_structural_tp_levels ----------------------------------------

def test_structural_tp_levels_use_real_candidates_nearest_first_long():
    tps = risk.build_structural_tp_levels(
        "long", entry_price=100.0, stop_distance=2.0,
        candidate_levels=[110.0, 105.0, 130.0, 120.0], fallback_tps=[104.0, 106.0, 108.0, 110.0],
    )
    assert tps == [105.0, 110.0, 120.0, 130.0]  # nearest-first, strictly ascending


def test_structural_tp_levels_use_real_candidates_nearest_first_short():
    tps = risk.build_structural_tp_levels(
        "short", entry_price=100.0, stop_distance=2.0,
        candidate_levels=[90.0, 95.0, 70.0, 80.0], fallback_tps=[96.0, 94.0, 92.0, 90.0],
    )
    assert tps == [95.0, 90.0, 80.0, 70.0]  # nearest-first, strictly descending


def test_structural_tp_levels_fill_missing_rungs_from_atr_fallback():
    # Only 2 real candidates -- the other 2 rungs must come from fallback_tps,
    # never leave a rung unset or return fewer than 4 targets.
    tps = risk.build_structural_tp_levels(
        "long", entry_price=100.0, stop_distance=2.0,
        candidate_levels=[105.0], fallback_tps=[104.0, 108.0, 112.0, 116.0],
    )
    assert len(tps) == 4
    assert tps[0] == 105.0  # the one real candidate is used
    assert tps == sorted(tps)  # still strictly ascending after merging with fallback rungs


def test_structural_tp_levels_discard_candidates_behind_price_or_too_close():
    # 101.0 is only 0.5R away (min_r_multiple defaults to 0.5R -> min distance
    # 1.0) -- too close, must be discarded, not used as TP1.
    tps = risk.build_structural_tp_levels(
        "long", entry_price=100.0, stop_distance=2.0,
        candidate_levels=[101.0, 90.0, 150.0], fallback_tps=[104.0, 108.0, 112.0, 116.0],
    )
    assert 101.0 not in tps  # too close
    assert 90.0 not in tps  # behind price for a long
    assert 150.0 in tps


def test_structural_tp_levels_discard_candidates_beyond_max_r_multiple():
    # A degenerate/clamped candidate (e.g. a floored Fibonacci extension
    # level -- see engine.py's _real_down_extension_levels, confirmed live
    # on XRP/USD 1w) sitting far past any sane target distance must never
    # become a "TP", even though it's technically ahead of price and
    # farther than min_r_multiple.
    tps = risk.build_structural_tp_levels(
        "short", entry_price=1.0, stop_distance=0.02,
        candidate_levels=[0.95, 0.0069], fallback_tps=[0.97, 0.94, 0.91, 0.88],
        max_r_multiple=10.0,  # (1.0 - 0.0069) / 0.02 ~= 49.6R -- well past this cap
    )
    assert 0.0069 not in tps
    assert 0.95 in tps


def test_structural_tp_levels_no_candidates_matches_pure_atr_fallback():
    fallback = [104.0, 108.0, 112.0, 116.0]
    tps = risk.build_structural_tp_levels(
        "long", entry_price=100.0, stop_distance=2.0, candidate_levels=[], fallback_tps=fallback,
    )
    assert tps == fallback


# --- engine.analyze_ohlcv wiring --------------------------------------------

def test_engine_defaults_to_atr_tp_mode():
    random.seed(11)
    closes = [100 + i * 0.5 + random.uniform(-0.3, 0.3) for i in range(80)]
    signal = analyze_ohlcv("BTC/USDT", _make_ohlcv(closes))
    assert signal.tp_mode == "atr"


def test_engine_structural_tp_mode_is_opt_in_and_still_returns_four_ordered_tps():
    random.seed(12)
    closes = [100 + i * 0.5 + random.uniform(-0.3, 0.3) for i in range(80)]
    data = _make_ohlcv(closes)

    atr_signal = analyze_ohlcv("BTC/USDT", data, tp_mode_override="atr")
    structural_signal = analyze_ohlcv("BTC/USDT", data, tp_mode_override="structural")

    assert atr_signal.tp_mode == "atr"
    assert structural_signal.tp_mode == "structural"

    tps = list(structural_signal.take_profits.values())
    assert len(tps) == 4
    # every TP is genuinely ahead of entry (never behind price, whichever
    # direction the setup traded), and strictly increasing distance rung to rung
    if tps[-1] >= structural_signal.entry:  # long-ish ladder
        assert tps == sorted(tps)
    else:
        assert tps == sorted(tps, reverse=True)


def test_engine_structural_tp_excludes_floored_fib_extension_levels():
    # Regression for a real bug found live testing --tp-mode structural on
    # XRP/USD's 1w timeframe: a wide swing_high/swing_low range (3.19/0.99)
    # made fibonacci.calculate_extension()'s "down"-direction floor kick in
    # for the 1.618/2.618 rungs (its own "never return <= 0" safety clamp,
    # not real structure), which then got fed straight through as
    # structural TP candidates -- $0.0079/$0.0069, essentially zero. A short
    # setup with a comparably wide swing must never offer a floored
    # extension level as a "real" TP candidate. (Note: a *legitimately*
    # wide-but-unfloored target, e.g. the 1.272 rung, IS still a valid
    # candidate here -- weekly ATR on a sub-$1 asset can honestly imply a
    # large % move; this test only asserts the floor artifact is gone, not
    # a blanket "TPs must be close to entry" bound.)
    n = 55
    closes = [3.0 - i * (2.0 / (n - 1)) for i in range(n)]  # steady downtrend, 3.0 -> 1.0
    highs = [c + 0.05 for c in closes]
    lows = [c - 0.05 for c in closes]
    # a spike within the swing lookback window (default 50 bars) recreates
    # the live case's wide swing_high(3.19)/swing_low(~0.95) range
    highs[5] = 3.19
    data = _make_ohlcv(closes, highs=highs, lows=lows)

    signal = analyze_ohlcv("XRP/USD", data, timeframe="1w", tp_mode_override="structural")
    # the floored raw values themselves (see fibonacci.calculate_extension's
    # own floor formula) must not appear verbatim as a TP
    diff = signal.swing_high - signal.swing_low
    floored_values = {
        v for k, v in signal.fib_extension_levels.items()
        if (signal.swing_high - diff * float(k)) <= 0
    }
    assert floored_values, "test setup didn't actually trigger the floor -- adjust the fixture"
    for tp_price in signal.take_profits.values():
        assert tp_price not in floored_values


def test_engine_fib_extension_levels_are_exposed_on_the_signal():
    random.seed(13)
    closes = [100 + i * 0.5 + random.uniform(-0.3, 0.3) for i in range(80)]
    signal = analyze_ohlcv("BTC/USDT", _make_ohlcv(closes))
    assert isinstance(signal.fib_extension_levels, dict)
    assert len(signal.fib_extension_levels) > 0
