from cdcx.ranging_strategy import evaluate_ranging_setup
from cdcx.indicators.candlestick_patterns import PatternMatch


def test_valid_long_setup_at_support():
    matches = [PatternMatch("Hammer", "bullish", 2)]
    rsi_series = [40, 32, 30, 33]  # oversold and turning up
    result = evaluate_ranging_setup(
        price=95.5, rsi_series=rsi_series, poc=100, vah=105, val=95, pattern_matches=matches,
    )
    assert result.valid is True
    assert result.direction == "long"
    assert result.tp1 == 100  # POC
    assert result.tp2 == 105  # opposite boundary (VAH)


def test_valid_short_setup_at_resistance():
    matches = [PatternMatch("Shooting Star", "bearish", 2)]
    rsi_series = [60, 68, 70, 66]  # overbought and turning down
    result = evaluate_ranging_setup(
        price=104.5, rsi_series=rsi_series, poc=100, vah=105, val=95, pattern_matches=matches,
    )
    assert result.valid is True
    assert result.direction == "short"
    assert result.tp1 == 100
    assert result.tp2 == 95  # opposite boundary (VAL)


def test_no_setup_in_middle_of_range():
    result = evaluate_ranging_setup(
        price=100, rsi_series=[50, 51, 52], poc=100, vah=105, val=95, pattern_matches=[],
    )
    assert result.valid is False
    assert result.direction is None


def test_rsi_extreme_without_rejection_candle_does_not_qualify():
    # oversold and near support, but no bullish candle pattern present
    result = evaluate_ranging_setup(
        price=95.5, rsi_series=[40, 32, 30, 33], poc=100, vah=105, val=95, pattern_matches=[],
    )
    assert result.valid is False


def test_weak_pattern_strength_does_not_count_as_rejection():
    # strength 1 is below the MIN_PATTERN_STRENGTH threshold
    matches = [PatternMatch("Doji (Indecision)", "bullish", 1)]
    result = evaluate_ranging_setup(
        price=95.5, rsi_series=[40, 32, 30, 33], poc=100, vah=105, val=95, pattern_matches=matches,
    )
    assert result.valid is False


def test_range_profile_middle_location():
    result = evaluate_ranging_setup(
        price=100, rsi_series=[50, 51, 52], poc=100, vah=105, val=95, pattern_matches=[],
    )
    assert result.profile is not None
    assert result.profile.price_location == "MIDDLE"
    assert result.profile.rejection is False


def test_range_profile_upper_edge_with_rejection():
    matches = [PatternMatch("Shooting Star", "bearish", 2)]
    result = evaluate_ranging_setup(
        price=104.5, rsi_series=[60, 68, 70, 66], poc=100, vah=105, val=95, pattern_matches=matches,
    )
    assert result.profile.price_location == "UPPER EDGE"
    assert result.profile.rejection is True
    assert result.profile.rejection_direction == "bearish"


def test_range_profile_edge_distance_near_zero_at_boundary():
    result = evaluate_ranging_setup(
        price=95.0, rsi_series=[40, 32, 30, 33], poc=100, vah=105, val=95, pattern_matches=[],
    )
    assert result.profile.edge_distance_pct < 5.0  # sitting right at the low edge


def test_range_profile_fields_match_inputs():
    result = evaluate_ranging_setup(
        price=100, rsi_series=[50], poc=100, vah=105, val=95, pattern_matches=[],
    )
    assert result.profile.range_high == 105
    assert result.profile.range_low == 95
    assert result.profile.range_mid == 100
    assert result.profile.poc == 100
