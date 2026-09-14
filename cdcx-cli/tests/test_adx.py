from cdcx.indicators.adx import calculate_adx, score_adx


def test_calculate_adx_series_length_matches_input():
    closes = [100 + i * 0.5 for i in range(40)]
    highs = [c + 0.4 for c in closes]
    lows = [c - 0.4 for c in closes]
    adx_series, plus_di_series, minus_di_series = calculate_adx(highs, lows, closes, period=14)
    assert len(adx_series) == len(closes)
    assert len(plus_di_series) == len(closes)
    assert len(minus_di_series) == len(closes)


def test_strong_uptrend_gives_high_adx_and_plus_di_dominant():
    closes = [100 + i * 0.8 for i in range(40)]  # steady, strong uptrend
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    adx_series, plus_di_series, minus_di_series = calculate_adx(highs, lows, closes, period=14)
    assert adx_series[-1] > 25
    assert plus_di_series[-1] > minus_di_series[-1]


def test_score_adx_strong_confirmed_bullish():
    result_score, label = score_adx(adx_value=40, plus_di=30, minus_di=10, trend="bullish")
    assert result_score == 10


def test_score_adx_strong_but_unconfirmed_direction():
    result_score, label = score_adx(adx_value=40, plus_di=10, minus_di=30, trend="bullish")
    assert result_score == 0


def test_score_adx_choppy_market():
    result_score, label = score_adx(adx_value=12, plus_di=18, minus_di=16, trend="bullish")
    assert result_score == 0
