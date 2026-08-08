import random

from cdcx.indicators.fair_value_gap import FVG
from cdcx.structure_levels import (
    BreakoutEvent,
    classify_condition,
    compute_structure_map,
    detect_breakout,
    detect_retest,
    find_fvg_near_level,
)


def _flat_series(n, base=100.0, spread=0.1, vol=100.0, seed=1):
    rng = random.Random(seed)
    closes = [base + rng.uniform(-spread, spread) for _ in range(n)]
    highs = [c + spread * 3 for c in closes]
    lows = [c - spread * 3 for c in closes]
    volumes = [vol] * n
    return highs, lows, closes, volumes


# ---------------------------------------------------------------------------
# classify_condition
# ---------------------------------------------------------------------------

def test_classify_condition_ranging_contracting_is_consolidation():
    assert classify_condition("ranging", "Contraction") == "consolidation"


def test_classify_condition_ranging_expanding_stays_ranging():
    assert classify_condition("ranging", "Expansion") == "ranging"


def test_classify_condition_trending_passes_through():
    assert classify_condition("trending", "Expansion") == "trending"


def test_classify_condition_transitional_passes_through():
    assert classify_condition("transitional", "Insufficient Data") == "transitional"


# ---------------------------------------------------------------------------
# detect_breakout
# ---------------------------------------------------------------------------

def test_detect_breakout_finds_the_decisive_close():
    highs, lows, closes, volumes = _flat_series(30, base=100.0, spread=0.1)
    # one decisive breakout bar appended at the end
    highs.append(106.0)
    lows.append(99.5)
    closes.append(105.0)
    volumes.append(500.0)  # comfortably above the lookback average

    event = detect_breakout(highs, lows, closes, volumes, level_price=99.0, level_name="support", direction="up")
    assert event is not None
    assert event.index == len(closes) - 1
    assert event.direction == "up"
    assert event.level_name == "support"
    assert event.volume_confirmed is True


def test_detect_breakout_returns_none_when_price_never_clears_the_level():
    # oscillates tightly around the level itself -- never decisively clears it
    highs, lows, closes, volumes = _flat_series(30, base=100.0, spread=0.05)
    event = detect_breakout(highs, lows, closes, volumes, level_price=100.0, level_name="support", direction="up")
    assert event is None


def test_detect_breakout_down_direction():
    highs, lows, closes, volumes = _flat_series(30, base=100.0, spread=0.1)
    highs.append(100.5)
    lows.append(94.0)
    closes.append(95.0)
    volumes.append(500.0)

    event = detect_breakout(highs, lows, closes, volumes, level_price=100.0, level_name="resistance", direction="down")
    assert event is not None
    assert event.direction == "down"
    assert event.level_name == "resistance"


# ---------------------------------------------------------------------------
# detect_retest
# ---------------------------------------------------------------------------

def _breakout_then(*extra_bars):
    """20 flat bars, one breakout bar (index 20, close 105), then `extra_bars`
    of (high, low, close). Returns (highs, lows, closes, breakout)."""
    highs, lows, closes, _ = _flat_series(20, base=100.0, spread=0.1)
    highs.append(106.0)
    lows.append(99.5)
    closes.append(105.0)
    breakout = BreakoutEvent(
        index=20, direction="up", level_name="support", level_price=99.0,
        close_price=105.0, volume_confirmed=True,
    )
    for h, l, c in extra_bars:
        highs.append(h)
        lows.append(l)
        closes.append(c)
    return highs, lows, closes, breakout


def test_detect_retest_held_when_pullback_stays_above_the_level():
    highs, lows, closes, breakout = _breakout_then((102.5, 99.1, 102.0))
    result = detect_retest(highs, lows, closes, breakout)
    assert result.retest_index == 21
    assert result.held is True


def test_detect_retest_fails_when_pullback_closes_back_through_the_level():
    highs, lows, closes, breakout = _breakout_then((100.0, 99.1, 98.5))
    result = detect_retest(highs, lows, closes, breakout)
    assert result.retest_index == 21
    assert result.held is False


def test_detect_retest_none_when_price_never_returns():
    # 20 bars that run away from the level without ever coming back near it
    extra = [(110.0 + i, 108.0 + i, 109.0 + i) for i in range(20)]
    highs, lows, closes, breakout = _breakout_then(*extra)
    result = detect_retest(highs, lows, closes, breakout)
    assert result.retest_index == -1
    assert result.held is False


# ---------------------------------------------------------------------------
# find_fvg_near_level
# ---------------------------------------------------------------------------

def test_find_fvg_near_level_matches_close_unfilled_gap():
    gaps = [
        FVG(index=5, top=101.0, bottom=100.0, kind="bullish", filled=False),
        FVG(index=10, top=95.0, bottom=94.0, kind="bearish", filled=False),
    ]
    found = find_fvg_near_level(gaps, level_price=100.5, atr=1.0, kind="bullish")
    assert found is not None
    assert found.index == 5


def test_find_fvg_near_level_excludes_filled_gaps():
    gaps = [FVG(index=5, top=101.0, bottom=100.0, kind="bullish", filled=True)]
    found = find_fvg_near_level(gaps, level_price=100.5, atr=1.0, kind="bullish")
    assert found is None


def test_find_fvg_near_level_none_when_too_far():
    gaps = [FVG(index=5, top=101.0, bottom=100.0, kind="bullish", filled=False)]
    found = find_fvg_near_level(gaps, level_price=200.0, atr=1.0, kind="bullish")
    assert found is None


# ---------------------------------------------------------------------------
# compute_structure_map
# ---------------------------------------------------------------------------

def test_compute_structure_map_levels_match_volume_profile():
    from cdcx.indicators import volume_profile_fixed

    rng = random.Random(1)
    n = 60
    closes = [100 + i * 0.3 + rng.uniform(-0.5, 0.5) for i in range(n)]
    highs = [c + 0.6 for c in closes]
    lows = [c - 0.6 for c in closes]
    volumes = [rng.uniform(50, 200) for _ in range(n)]

    vp = volume_profile_fixed.analyze(highs, lows, volumes, price=closes[-1])
    smap = compute_structure_map(highs, lows, closes, volumes)

    assert smap.poc == vp.poc
    assert smap.resistance == vp.vah
    assert smap.support == vp.val
    assert smap.condition in ("consolidation", "ranging", "trending", "transitional")
