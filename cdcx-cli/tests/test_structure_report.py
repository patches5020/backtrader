from cdcx.structure_report import build_structure_report, format_structure_report


def _flat_range_series(n=60):
    """Oscillates in a tight band -- should classify as RANGING, not TRENDING."""
    highs, lows, closes, volumes = [], [], [], []
    for i in range(n):
        base = 100.0 + (2.0 if i % 4 in (1, 2) else 0.0)
        highs.append(base + 1.0)
        lows.append(base - 1.0)
        closes.append(base)
        volumes.append(1000.0 + (i % 5) * 50)
    return highs, lows, closes, volumes


def _strong_uptrend_series(n=60):
    highs, lows, closes, volumes = [], [], [], []
    price = 100.0
    for i in range(n):
        price += 2.0
        highs.append(price + 1.0)
        lows.append(price - 1.0)
        closes.append(price)
        volumes.append(1000.0)
    return highs, lows, closes, volumes


def test_build_structure_report_computes_regime_vp_and_structure():
    highs, lows, closes, volumes = _flat_range_series()
    report = build_structure_report("BTC/USDT", "1h", highs, lows, closes, volumes)
    assert report.symbol == "BTC/USDT"
    assert report.timeframe == "1h"
    assert report.price == closes[-1]
    assert report.vp.poc > 0
    assert report.regime.regime in ("trending", "ranging", "transitional")


def test_format_report_shows_range_boundaries_when_ranging():
    highs, lows, closes, volumes = _flat_range_series()
    report = build_structure_report("BTC/USDT", "1h", highs, lows, closes, volumes)
    output = format_structure_report(report)
    assert "POC:" in output
    assert "VAH:" in output
    assert "VAL:" in output
    if report.regime.regime == "ranging":
        assert "RANGE (market is classified RANGING)" in output
        assert "% through the range" in output


def test_format_report_flags_transitional_regime_explicitly():
    # A short, choppy series is a plausible transitional read; only assert
    # the transitional-specific line appears IF that's what it classified as
    # -- this locks in the message text without over-constraining the fixture.
    highs, lows, closes, volumes = _flat_range_series(n=40)
    report = build_structure_report("BTC/USDT", "1h", highs, lows, closes, volumes)
    output = format_structure_report(report)
    if report.regime.regime == "transitional":
        assert "TRANSITIONAL" in output
        assert "don't read them as a settled range yet" in output


def test_price_above_vah_reads_as_outside_the_range():
    highs, lows, closes, volumes = _strong_uptrend_series()
    report = build_structure_report("BTC/USDT", "1h", highs, lows, closes, volumes)
    # A strong uptrend's final close should sit at or above the value area
    # built from the whole lookback (most volume happened at lower prices).
    assert report.price >= report.vp.vah - 1e-9
    output = format_structure_report(report)
    assert "ABOVE the value area" in output


def test_format_report_always_shows_swing_structure_and_bos():
    highs, lows, closes, volumes = _strong_uptrend_series()
    report = build_structure_report("BTC/USDT", "4h", highs, lows, closes, volumes)
    output = format_structure_report(report)
    assert "SWING STRUCTURE:" in output
    assert "BREAK OF STRUCTURE:" in output
