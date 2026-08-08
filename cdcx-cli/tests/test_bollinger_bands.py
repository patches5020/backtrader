from cdcx.indicators.bollinger_bands import calculate_bollinger_bands, score_bollinger


def test_bands_length_matches_input():
    closes = [100 + i * 0.5 for i in range(30)]
    sma, upper, lower = calculate_bollinger_bands(closes, period=20)
    assert len(sma) == len(closes)
    assert len(upper) == len(closes)
    assert len(lower) == len(closes)


def test_upper_band_above_lower_band():
    closes = [100 + i * 0.5 for i in range(30)]
    sma, upper, lower = calculate_bollinger_bands(closes, period=20)
    assert upper[-1] > lower[-1]


def test_score_bullish_riding_upper_band():
    score, label = score_bollinger(price=115, middle=110, upper=118, lower=102, trend="bullish")
    assert score == 10
    assert "Bullish Continuation" in label


def test_score_bearish_riding_lower_band():
    score, label = score_bollinger(price=105, middle=110, upper=118, lower=102, trend="bearish")
    assert score == -10
    assert "Bearish Continuation" in label


def test_score_bullish_thesis_weak_below_mean():
    score, label = score_bollinger(price=103, middle=110, upper=118, lower=102, trend="bullish")
    assert score == 0
