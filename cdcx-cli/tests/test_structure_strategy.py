import random

from cdcx import regime as regime_module
from cdcx.indicators.fair_value_gap import FVG
from cdcx.structure_levels import StructureMap
from cdcx.structure_strategy import (
    evaluate_structure_setup,
    weekly_bias,
    _confirm_1h,
    _try_breakout_retest,
    _try_fvg_confluence,
)


def _flat_series(n, base=100.0, spread=0.1, vol=100.0, seed=1):
    rng = random.Random(seed)
    closes = [base + rng.uniform(-spread, spread) for _ in range(n)]
    highs = [c + spread * 3 for c in closes]
    lows = [c - spread * 3 for c in closes]
    opens = closes[:]
    volumes = [vol] * n
    return highs, lows, opens, closes, volumes


def _fake_regime(state="ranging"):
    return regime_module.RegimeResult(regime=state, trend_score=0, range_score=8, breakdown=[], icon="", label="")


def _map(poc, resistance, support, fvgs=None, condition="ranging"):
    return StructureMap(
        poc=poc, resistance=resistance, support=support, fvgs=fvgs or [],
        condition=condition, regime=_fake_regime(condition if condition != "consolidation" else "ranging"),
    )


# ---------------------------------------------------------------------------
# weekly_bias
# ---------------------------------------------------------------------------

def test_weekly_bias_bullish_above_poc():
    w1 = _map(poc=100.0, resistance=110.0, support=90.0)
    assert weekly_bias(w1, price=105.0) == "bullish"


def test_weekly_bias_bearish_below_poc():
    w1 = _map(poc=100.0, resistance=110.0, support=90.0)
    assert weekly_bias(w1, price=95.0) == "bearish"


def test_weekly_bias_neutral_exactly_at_poc():
    w1 = _map(poc=100.0, resistance=110.0, support=90.0)
    assert weekly_bias(w1, price=100.0) == "neutral"


# ---------------------------------------------------------------------------
# _confirm_1h
# ---------------------------------------------------------------------------

def test_confirm_1h_true_on_bullish_engulfing():
    # same construction as test_candlestick_patterns.py's bullish engulfing
    opens = [100, 98]
    closes = [98, 103]
    highs = [100.5, 103.5]
    lows = [97.5, 97.8]
    ok, note = _confirm_1h(highs, lows, opens, closes, "long")
    assert ok is True
    assert "bullish" in note


def test_confirm_1h_false_with_no_matching_pattern():
    highs, lows, opens, closes, _ = _flat_series(10, spread=0.02)
    ok, note = _confirm_1h(highs, lows, opens, closes, "long")
    assert ok is False


# ---------------------------------------------------------------------------
# _try_breakout_retest
# ---------------------------------------------------------------------------

def _breakout_retest_h4(direction="up"):
    """20 flat 4H bars, then a decisive breakout bar, then a held retest bar.
    The retest bar's own close is deliberately kept on the "held" side of the
    level but short of the breakout threshold itself -- otherwise detect_breakout
    (which always returns the MOST RECENT qualifying bar) would pick the retest
    bar instead of the actual breakout bar. Exact numbers verified against
    calculate_atr() for this series rather than guessed."""
    highs, lows, _, closes, volumes = _flat_series(20, base=100.0, spread=0.1)
    if direction == "up":
        highs += [106.0, 99.6]
        lows += [99.5, 99.1]
        closes += [105.0, 99.2]
        volumes += [500.0, 200.0]
    else:
        highs += [100.5, 100.4]
        lows += [94.0, 99.3]
        closes += [95.0, 99.8]
        volumes += [500.0, 200.0]
    return highs, lows, closes, volumes


def test_try_breakout_retest_long_succeeds_end_to_end():
    d1 = _map(poc=99.5, resistance=101.0, support=99.0)
    h4_highs, h4_lows, h4_closes, h4_volumes = _breakout_retest_h4("up")
    h1_opens = [100, 98]
    h1_closes = [98, 103]
    h1_highs = [100.5, 103.5]
    h1_lows = [97.5, 97.8]

    result = _try_breakout_retest(
        d1, h4_highs, h4_lows, h4_closes, h4_volumes, h1_highs, h1_lows, h1_opens, h1_closes, "long",
    )
    assert result.valid is True
    assert result.direction == "long"
    assert result.trigger == "breakout_retest"
    assert result.stop_level == d1.support


def test_try_breakout_retest_long_fails_without_1h_confirmation():
    d1 = _map(poc=99.5, resistance=101.0, support=99.0)
    h4_highs, h4_lows, h4_closes, h4_volumes = _breakout_retest_h4("up")
    h1_highs, h1_lows, h1_opens, h1_closes, _ = _flat_series(10, spread=0.02)

    result = _try_breakout_retest(
        d1, h4_highs, h4_lows, h4_closes, h4_volumes, h1_highs, h1_lows, h1_opens, h1_closes, "long",
    )
    assert result.valid is False


def test_try_breakout_retest_short_succeeds_end_to_end():
    d1 = _map(poc=99.5, resistance=100.0, support=90.0)
    h4_highs, h4_lows, h4_closes, h4_volumes = _breakout_retest_h4("down")
    # bearish engulfing for 1H confirmation (mirrors test_candlestick_patterns.py)
    h1_opens = [98, 103]
    h1_closes = [103, 98]
    h1_highs = [103.5, 103.6]
    h1_lows = [97.5, 97.6]

    result = _try_breakout_retest(
        d1, h4_highs, h4_lows, h4_closes, h4_volumes, h1_highs, h1_lows, h1_opens, h1_closes, "short",
    )
    assert result.valid is True
    assert result.direction == "short"


def test_try_breakout_retest_no_breakout_is_invalid():
    d1 = _map(poc=99.5, resistance=101.0, support=99.0)
    h4_highs, h4_lows, h4_opens, h4_closes, h4_volumes = _flat_series(20, base=100.0, spread=0.05)
    h1_opens = [100, 98]
    h1_closes = [98, 103]
    h1_highs = [100.5, 103.5]
    h1_lows = [97.5, 97.8]

    result = _try_breakout_retest(
        d1, h4_highs, h4_lows, h4_closes, h4_volumes, h1_highs, h1_lows, h1_opens, h1_closes, "long",
    )
    assert result.valid is False
    assert result.trigger == "breakout_retest"


# ---------------------------------------------------------------------------
# _try_fvg_confluence
# ---------------------------------------------------------------------------

def test_try_fvg_confluence_succeeds_when_gap_near_poc_and_price_reacts():
    d1 = _map(poc=100.5, resistance=105.0, support=95.0)
    h4_highs, h4_lows, _, h4_closes, _ = _flat_series(20, base=102.0, spread=0.1)
    # an unfilled bullish FVG whose bottom sits right at/near the 1D POC
    gap = FVG(index=15, top=101.5, bottom=100.4, kind="bullish", filled=False)
    h4 = _map(poc=100.0, resistance=103.0, support=99.0, fvgs=[gap])
    # last 4H bar wicks into the gap and closes back above it -- a reaction
    h4_highs.append(102.5)
    h4_lows.append(100.3)
    h4_closes.append(101.0)

    h1_opens = [100, 98]
    h1_closes = [98, 103]
    h1_highs = [100.5, 103.5]
    h1_lows = [97.5, 97.8]

    result = _try_fvg_confluence(d1, h4, h4_highs, h4_lows, h4_closes, h1_highs, h1_lows, h1_opens, h1_closes)
    assert result.valid is True
    assert result.trigger == "fvg_confluence"
    assert result.direction == "long"


def test_try_fvg_confluence_fails_when_no_gap_near_the_level():
    d1 = _map(poc=100.5, resistance=105.0, support=95.0)
    h4_highs, h4_lows, _, h4_closes, _ = _flat_series(20, base=102.0, spread=0.1)
    far_gap = FVG(index=15, top=200.0, bottom=199.0, kind="bullish", filled=False)
    h4 = _map(poc=100.0, resistance=103.0, support=99.0, fvgs=[far_gap])
    h1_highs, h1_lows, h1_opens, h1_closes, _ = _flat_series(10, spread=0.02)

    result = _try_fvg_confluence(d1, h4, h4_highs, h4_lows, h4_closes, h1_highs, h1_lows, h1_opens, h1_closes)
    assert result.valid is False


# ---------------------------------------------------------------------------
# evaluate_structure_setup (full orchestration)
# ---------------------------------------------------------------------------

def test_evaluate_structure_setup_returns_long_when_bias_and_breakout_agree():
    w1 = _map(poc=90.0, resistance=120.0, support=80.0)  # price (100ish) > 90 -> bullish bias
    d1 = _map(poc=99.5, resistance=101.0, support=99.0)
    h4_highs, h4_lows, h4_closes, h4_volumes = _breakout_retest_h4("up")
    h4 = _map(poc=99.0, resistance=101.0, support=99.0, fvgs=[])
    h1_opens = [100, 98]
    h1_closes = [98, 103]
    h1_highs = [100.5, 103.5]
    h1_lows = [97.5, 97.8]

    result = evaluate_structure_setup(
        w1, d1, h4, h4_highs, h4_lows, h4_closes, h4_volumes, h1_highs, h1_lows, h1_opens, h1_closes,
    )
    assert result.valid is True
    assert result.direction == "long"
    assert any("1W major structure" in r for r in result.reasons)


def test_evaluate_structure_setup_bearish_bias_blocks_long_triggers():
    # price ends ~102 (from _breakout_retest_h4("up")), weekly POC far above it -> bearish bias
    w1 = _map(poc=500.0, resistance=600.0, support=400.0)
    d1 = _map(poc=99.5, resistance=101.0, support=99.0)
    h4_highs, h4_lows, h4_closes, h4_volumes = _breakout_retest_h4("up")
    h4 = _map(poc=99.0, resistance=101.0, support=99.0, fvgs=[])
    h1_highs, h1_lows, h1_opens, h1_closes, _ = _flat_series(10, spread=0.02)

    result = evaluate_structure_setup(
        w1, d1, h4, h4_highs, h4_lows, h4_closes, h4_volumes, h1_highs, h1_lows, h1_opens, h1_closes,
    )
    # long breakout_retest setup exists on h4, but bearish 1W bias must block it
    assert result.direction is None or result.direction == "short"
