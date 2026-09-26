from cdcx.vp_setup import classify_vp_setup, format_vp_setup

POC, VAH, VAL = 100.0, 105.0, 95.0


def _flat_then_breakout(n, break_at, level, direction, post_break_step, seed_bars=15):
    """Flat just inside `level` for the first `break_at` bars, then a
    decisive close through `level` in `direction`, moving by
    `post_break_step` per bar afterward. Mirrors test_bos_state.py's helper,
    parameterized by direction since VP breakouts can go either way through
    VAH (up) or VAL (down)."""
    highs, lows, closes, volumes = [], [], [], []
    for i in range(n):
        if i < break_at:
            price = level - 0.05 if direction == "up" else level + 0.05
        elif i == break_at:
            price = level + 1.0 if direction == "up" else level - 1.0
        else:
            step = post_break_step if direction == "up" else -post_break_step
            price = closes[-1] + step
        highs.append(price + 0.1)
        lows.append(price - 0.1)
        closes.append(price)
        volumes.append(2000.0 if i == break_at else 1000.0)
    return highs, lows, closes, volumes


def test_none_when_price_stays_inside_the_value_area():
    n = 30
    highs = [POC + 0.5] * n
    lows = [POC - 0.5] * n
    closes = [POC + 0.1] * n
    volumes = [1000.0] * n
    result = classify_vp_setup(closes[-1], POC, VAH, VAL, highs, lows, closes, volumes)
    assert result.setup_type == "none"
    assert format_vp_setup(result) == "VP SETUP: None"


def test_value_area_breakout_with_no_retest_yet():
    highs, lows, closes, volumes = _flat_then_breakout(
        n=30, break_at=15, level=VAH, direction="up", post_break_step=1.0,
    )
    result = classify_vp_setup(closes[-1], POC, VAH, VAL, highs, lows, closes, volumes)
    assert result.setup_type == "value_area_breakout"
    assert result.direction == "up"
    assert "Breakout" in format_vp_setup(result)


def test_value_area_breakout_retest_held_above_vah():
    highs, lows, closes, volumes = _flat_then_breakout(
        n=30, break_at=15, level=VAH, direction="up", post_break_step=0.3,
    )
    for i in range(25, 30):
        closes[i] = VAH + 0.05
        highs[i] = VAH + 0.15
        lows[i] = VAH - 0.02
    result = classify_vp_setup(closes[-1], POC, VAH, VAL, highs, lows, closes, volumes)
    assert result.setup_type == "value_area_breakout"
    assert result.direction == "up"


def test_value_area_reversal_after_failed_vah_breakout():
    highs, lows, closes, volumes = _flat_then_breakout(
        n=30, break_at=15, level=VAH, direction="up", post_break_step=0.3,
    )
    for i in range(25, 30):
        closes[i] = VAH - 0.5  # closes back BELOW VAH -- failed breakout
        highs[i] = VAH - 0.3
        lows[i] = VAH - 0.7
    result = classify_vp_setup(closes[-1], POC, VAH, VAL, highs, lows, closes, volumes)
    assert result.setup_type == "value_area_reversal"
    assert result.direction == "down"
    assert "Reversal" in format_vp_setup(result)


def test_value_area_reversal_after_failed_val_breakout_reads_bullish():
    highs, lows, closes, volumes = _flat_then_breakout(
        n=30, break_at=15, level=VAL, direction="down", post_break_step=0.3,
    )
    for i in range(25, 30):
        closes[i] = VAL + 0.5  # closes back ABOVE VAL -- failed bearish breakout, bullish reclaim
        highs[i] = VAL + 0.7
        lows[i] = VAL + 0.3
    result = classify_vp_setup(closes[-1], POC, VAH, VAL, highs, lows, closes, volumes)
    assert result.setup_type == "value_area_reversal"
    assert result.direction == "up"


def test_poc_bounce_after_an_aged_out_excursion_above_vah():
    n = 50
    highs, lows, closes, volumes = [], [], [], []
    for i in range(n):
        if 10 <= i <= 15:
            price = VAH + 2.0  # old excursion above VAH, aged out of the breakout lookback window
        else:
            price = POC  # otherwise flat at POC
        highs.append(price + 0.1)
        lows.append(price - 0.1)
        closes.append(price)
        volumes.append(1000.0)
    result = classify_vp_setup(closes[-1], POC, VAH, VAL, highs, lows, closes, volumes)
    assert result.setup_type == "poc_bounce"
    assert result.direction == "down"
    assert "POC Bounce" in format_vp_setup(result)


def test_poc_bounce_after_an_aged_out_excursion_below_val():
    n = 50
    highs, lows, closes, volumes = [], [], [], []
    for i in range(n):
        if 10 <= i <= 15:
            price = VAL - 2.0  # old excursion below VAL, aged out of the breakout lookback window
        else:
            price = POC
        highs.append(price + 0.1)
        lows.append(price - 0.1)
        closes.append(price)
        volumes.append(1000.0)
    result = classify_vp_setup(closes[-1], POC, VAH, VAL, highs, lows, closes, volumes)
    assert result.setup_type == "poc_bounce"
    assert result.direction == "up"
