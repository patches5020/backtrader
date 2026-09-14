from cdcx.indicators.rsi import calculate_rsi, score_rsi


def test_calculate_rsi_length_matches_input():
    closes = [100 + i for i in range(30)]
    rsi_series = calculate_rsi(closes, period=14)
    assert len(rsi_series) == len(closes)


def test_rsi_uptrend_is_high():
    closes = [100 + i for i in range(30)]  # strictly rising
    rsi_series = calculate_rsi(closes, period=14)
    assert rsi_series[-1] > 70


def test_score_rsi_bullish_band():
    result = score_rsi(60, trend="bullish")
    assert result.score == 12


def test_score_rsi_bearish_band():
    result = score_rsi(35, trend="bearish")
    assert result.score == -10


def test_score_rsi_oversold_bullish_context_waits():
    result = score_rsi(25, trend="bullish")
    assert result.score == 0
