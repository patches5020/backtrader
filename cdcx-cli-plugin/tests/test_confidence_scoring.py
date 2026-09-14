from types import SimpleNamespace
from cdcx.confidence_scoring import calculate_weighted_confidence


def _all_confirming_signal():
    return SimpleNamespace(scores={
        "ema_trend": 15, "rsi_momentum": 12, "adx_trend_strength": 10,
        "fair_value_gap": 15, "fixed_volume_profile": 10, "anchored_volume_profile": 10,
    })


def test_all_timeframes_and_indicators_confirming_gives_100():
    signals = {"1w": "STRONG BUY", "1d": "BUY", "4h": "BUY", "1h": "BUY"}
    result = calculate_weighted_confidence(signals, "long", _all_confirming_signal())
    assert result.score == 100
    assert result.tier == "Very Strong"


def test_missing_timeframe_does_not_count():
    signals = {"1d": "BUY", "4h": "BUY"}  # no 1w, no 1h
    result = calculate_weighted_confidence(signals, "long", _all_confirming_signal())
    # 20 (1d) + 15 (4h) + 30 (all indicators) = 65
    assert result.score == 65
    assert result.tier == "Moderate"


def test_disagreeing_timeframe_does_not_count():
    signals = {"1w": "STRONG SELL", "1d": "BUY", "4h": "BUY", "1h": "BUY"}
    result = calculate_weighted_confidence(signals, "long", _all_confirming_signal())
    # 1w disagrees -> only 20+15+10 = 45 from timeframes + 30 indicators = 75
    assert result.score == 75


def test_no_indicators_confirming_only_timeframes_count():
    signal = SimpleNamespace(scores={
        "ema_trend": -5, "rsi_momentum": 0, "adx_trend_strength": -5,
        "fair_value_gap": 0, "fixed_volume_profile": -5, "anchored_volume_profile": -5,
    })
    signals = {"1w": "STRONG BUY", "1d": "BUY", "4h": "BUY", "1h": "BUY"}
    result = calculate_weighted_confidence(signals, "long", signal)
    assert result.score == 70  # just the timeframe weights, no indicator confirmation


def test_tier_thresholds():
    from cdcx.confidence_scoring import _tier
    assert _tier(95) == "Very Strong"
    assert _tier(80) == "Strong"
    assert _tier(65) == "Moderate"
    assert _tier(45) == "Weak"
    assert _tier(20) == "No Trade"
