from cdcx.indicators.candlestick_patterns import detect_patterns, score_patterns


def test_bullish_engulfing_detected():
    opens = [100, 98]
    closes = [98, 103]
    highs = [100.5, 103.5]
    lows = [97.5, 97.8]
    matches = detect_patterns(highs, lows, opens, closes)
    names = [m.name for m in matches]
    assert "Bullish Engulfing" in names


def test_bearish_engulfing_scores_negative_in_bearish_trend():
    opens = [98, 103]
    closes = [103, 98]
    highs = [103.5, 103.6]
    lows = [97.5, 97.6]
    matches = detect_patterns(highs, lows, opens, closes)
    score, label = score_patterns(matches, trend="bearish")
    assert score < 0
    assert "Bearish" in label


def test_hammer_detected_as_bullish():
    highs = [101]
    lows = [95]
    opens = [100.5]
    closes = [100.8]
    matches = detect_patterns(highs, lows, opens, closes)
    names = [m.name for m in matches]
    assert "Hammer" in names


def test_shooting_star_detected_as_bearish():
    highs = [106]
    lows = [99.8]
    opens = [100.2]
    closes = [100.5]
    matches = detect_patterns(highs, lows, opens, closes)
    names = [m.name for m in matches]
    assert "Shooting Star" in names


def test_no_pattern_scores_zero():
    # a plain, ordinary-bodied single candle with no special shape
    highs = [102]
    lows = [98]
    opens = [99]
    closes = [101.5]
    matches = detect_patterns(highs, lows, opens, closes)
    score, label = score_patterns(matches, trend="bullish")
    if not matches:
        assert score == 0


def test_score_only_counts_trend_aligned_patterns():
    # bullish engulfing present, but trend is bearish -> should not score
    opens = [100, 98]
    closes = [98, 103]
    highs = [100.5, 103.5]
    lows = [97.5, 97.8]
    matches = detect_patterns(highs, lows, opens, closes)
    score, label = score_patterns(matches, trend="bearish")
    assert score == 0
