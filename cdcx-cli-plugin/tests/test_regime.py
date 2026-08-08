from cdcx.regime import detect_regime, classify_ema_slope, classify_value_area_position


def test_all_trend_conditions_gives_trending():
    result = detect_regime(
        adx_value=32, ema_slope_state="strong", value_area_position="outside",
        atr_state="expansion", higher_timeframes_aligned=True, reversal_count=1,
    )
    assert result.regime == "trending"
    assert result.trend_score >= 8


def test_all_range_conditions_gives_ranging():
    result = detect_regime(
        adx_value=15, ema_slope_state="flat", value_area_position="oscillating",
        atr_state="contraction", higher_timeframes_aligned=False, reversal_count=5,
    )
    assert result.regime == "ranging"
    assert result.range_score >= 8


def test_dead_zone_everywhere_gives_transitional():
    result = detect_regime(
        adx_value=22, ema_slope_state="neutral", value_area_position="inside",
        atr_state="flat", higher_timeframes_aligned=False, reversal_count=2,
    )
    assert result.regime == "transitional"


def test_partial_trend_signals_not_enough_stays_transitional():
    # only ADX + EMA slope trending (4 points) -- below the 8 threshold
    result = detect_regime(
        adx_value=30, ema_slope_state="strong", value_area_position="inside",
        atr_state="flat", higher_timeframes_aligned=False, reversal_count=1,
    )
    assert result.regime == "transitional"
    assert result.trend_score == 4


def test_ema_slope_classification():
    # flat series -> flat
    flat_series = [100.0] * 20
    state, pct = classify_ema_slope(flat_series, lookback=5)
    assert state == "flat"

    # strongly rising series -> strong
    rising_series = [100 + i * 2 for i in range(20)]
    state2, pct2 = classify_ema_slope(rising_series, lookback=5)
    assert state2 == "strong"
    assert pct2 > 0


def test_value_area_position_outside_above_vah():
    assert classify_value_area_position(price=110, poc=100, vah=105, val=95) == "outside"


def test_value_area_position_oscillating_near_poc():
    assert classify_value_area_position(price=101, poc=100, vah=105, val=95) == "oscillating"


def test_value_area_position_inside_but_not_near_poc():
    # inside VA (between val/vah) but far enough from POC
    assert classify_value_area_position(price=103.5, poc=100, vah=105, val=95) == "inside"
