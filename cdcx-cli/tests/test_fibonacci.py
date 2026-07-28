from cdcx.indicators.fibonacci import (
    calculate_retracement,
    calculate_extension,
    score_retracement,
    score_extension,
)


def test_retracement_levels_bounds():
    levels = calculate_retracement(swing_high=200, swing_low=100)
    assert levels["0.0"] == 200
    assert levels["1.0"] == 100
    assert 100 < levels["0.618"] < 200


def test_extension_levels_up_direction_extend_above_high():
    levels = calculate_extension(swing_high=200, swing_low=100, direction="up")
    assert all(level > 200 for level in levels.values())


def test_extension_levels_down_direction_extend_below_low():
    levels = calculate_extension(swing_high=200, swing_low=100, direction="down")
    assert all(level < 100 for level in levels.values())


def test_score_retracement_awards_points_near_618():
    price = 100 + (200 - 100) * (1 - 0.618)  # exactly at the 0.618 level
    result = score_retracement(price, swing_high=200, swing_low=100, trend="bullish")
    assert result.score == 12
    assert "61.8" in result.label


def test_score_extension_full_ladder_when_trend_confirmed():
    result = score_extension(price=150, swing_high=200, swing_low=100, direction="up", trend_confirmed=True)
    assert result.score == 8


def test_score_extension_zero_when_trend_not_confirmed():
    result = score_extension(price=150, swing_high=200, swing_low=100, direction="up", trend_confirmed=False)
    assert result.score == 0
