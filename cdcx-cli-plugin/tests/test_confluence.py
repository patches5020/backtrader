from cdcx.confluence import evaluate_confluence


def test_two_bullish_timeframes_triggers_execute_long():
    result = evaluate_confluence({"1h": "BUY", "4h": "STRONG BUY"})
    assert result.should_execute is True
    assert result.direction == "long"


def test_two_bearish_timeframes_triggers_execute_short():
    result = evaluate_confluence({"1h": "SELL", "1d": "STRONG SELL"})
    assert result.should_execute is True
    assert result.direction == "short"


def test_single_agreeing_timeframe_does_not_execute():
    result = evaluate_confluence({"1h": "BUY", "4h": "WATCH"})
    assert result.should_execute is False


def test_tied_bullish_bearish_is_watch_not_execute():
    result = evaluate_confluence({"1h": "BUY", "4h": "BUY", "1d": "SELL", "1w": "SELL"})
    assert result.should_execute is False
    assert result.tier == "watch"


def test_entry_timeframe_is_the_fastest_agreeing_timeframe():
    result = evaluate_confluence({"4h": "BUY", "1h": "BUY", "1d": "BUY"})
    assert result.entry_timeframe == "1h"


def test_timeframes_outside_the_allowed_set_are_ignored():
    result = evaluate_confluence({"1h": "BUY", "15m": "BUY", "1d": "WATCH"})
    assert result.should_execute is False  # only 1 of {1h,4h,1d,1w} qualifies
    assert "15m" in result.ignored_timeframes


def test_confidence_tiers_match_spec_examples():
    strong = evaluate_confluence({"1w": "STRONG BUY", "1d": "BUY"})
    assert strong.confidence_pct == 70 and strong.tier == "strong"

    normal = evaluate_confluence({"1d": "BUY", "4h": "BUY"})
    assert normal.confidence_pct == 50 and normal.tier == "normal"

    lower = evaluate_confluence({"4h": "BUY", "1h": "BUY"})
    assert lower.confidence_pct == 30 and lower.tier == "lower_confidence"


def test_all_four_bullish_is_100_percent_strong_buy():
    result = evaluate_confluence({"1h": "BUY", "4h": "BUY", "1d": "BUY", "1w": "BUY"})
    assert result.confidence_pct == 100
    assert result.tier == "strong"
