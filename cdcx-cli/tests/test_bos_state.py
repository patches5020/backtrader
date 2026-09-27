from cdcx.bos_state import classify_bos_state, format_bos_state
from cdcx.indicators.market_structure import MarketStructureResult, SwingPoint


def _flat_then_breakout(n, break_at, level, post_break_step, seed_bars=15):
    """Flat just under `level` for the first `break_at` bars (enough seed
    bars before that for ATR to have real data), then a decisive close
    above `level` that moves by `post_break_step` per bar afterward.
    `post_break_step` > 0 keeps running away (continuation); 0 holds flat
    at the breakout level (sets up a retest); a later dip back through
    `level` turns a held retest into a failed one."""
    highs, lows, closes, volumes = [], [], [], []
    price = level - 0.5
    for i in range(n):
        if i < break_at:
            price = level - 0.05
        elif i == break_at:
            price = level + 1.0  # decisive breakout close, well past the 0.25*ATR threshold
        else:
            price += post_break_step
        highs.append(price + 0.1)
        lows.append(price - 0.1)
        closes.append(price)
        volumes.append(2000.0 if i == break_at else 1000.0)  # breakout bar trades above average
    return highs, lows, closes, volumes


def _result_with_high(level_price: float, index: int = 5) -> MarketStructureResult:
    """A MarketStructureResult whose only labeled swing is the high being
    broken -- classify_bos_state only reads .swings, so the rest of the
    dataclass's fields are irrelevant filler."""
    return MarketStructureResult(
        swings=[SwingPoint(index=index, price=level_price, kind="high", label="LH")],
        structure="LH", bos="None", score=0, label="",
    )


def test_no_break_when_price_never_clears_the_level():
    highs, lows, closes, volumes = _flat_then_breakout(n=30, break_at=999, level=100.0, post_break_step=0.0)
    result = classify_bos_state(_result_with_high(100.0), highs, lows, closes, volumes)
    assert result.state == "no_break"
    assert "BOS STATE: No confirmed break" in format_bos_state(result)


def test_continuation_when_price_runs_away_without_a_retest():
    highs, lows, closes, volumes = _flat_then_breakout(n=30, break_at=15, level=100.0, post_break_step=1.0)
    result = classify_bos_state(_result_with_high(100.0), highs, lows, closes, volumes)
    assert result.state == "continuation"
    assert result.direction == "up"
    assert "Continuation" in format_bos_state(result)


def test_retest_held_when_price_returns_and_holds_above_the_level():
    highs, lows, closes, volumes = _flat_then_breakout(n=30, break_at=15, level=100.0, post_break_step=0.3)
    # Pull the tail back down to just above the level (low dips within
    # retest proximity) without ever closing below it.
    for i in range(25, 30):
        closes[i] = 100.05
        highs[i] = 100.15
        lows[i] = 99.98
    result = classify_bos_state(_result_with_high(100.0), highs, lows, closes, volumes)
    assert result.state == "retest_held"
    assert "Retest Held" in format_bos_state(result)


def test_retest_failed_after_bullish_break_reads_as_bearish_reversal():
    highs, lows, closes, volumes = _flat_then_breakout(n=30, break_at=15, level=100.0, post_break_step=0.3)
    # Pull the tail back down and CLOSE below the level -- a failed retest.
    for i in range(25, 30):
        closes[i] = 99.5
        highs[i] = 99.6
        lows[i] = 99.4
    result = classify_bos_state(_result_with_high(100.0), highs, lows, closes, volumes)
    assert result.state == "retest_failed"
    assert result.direction == "up"
    assert "bearish reversal" in format_bos_state(result)


def test_retest_failed_after_bearish_break_reads_as_bullish_reclaim():
    # A bearish break of a swing low, retested, then price closes back
    # ABOVE the level -- that invalidates the bearish break, which is
    # bullish news for the level, not "deterioration".
    result_with_low = MarketStructureResult(
        swings=[SwingPoint(index=5, price=100.0, kind="low", label="LL")],
        structure="LL", bos="None", score=0, label="",
    )
    highs, lows, closes, volumes = [], [], [], []
    price = 100.5
    for i in range(30):
        if i < 15:
            price = 100.05
        elif i == 15:
            price = 99.0  # decisive bearish breakout close
        elif i < 25:
            price -= 0.0  # hold below
        highs.append(price + 0.1)
        lows.append(price - 0.1)
        closes.append(price)
        volumes.append(2000.0 if i == 15 else 1000.0)
    for i in range(25, 30):
        closes[i] = 100.5  # closes back ABOVE the level -- reclaim
        highs[i] = 100.6
        lows[i] = 100.02
    result = classify_bos_state(result_with_low, highs, lows, closes, volumes)
    assert result.state == "retest_failed"
    assert result.direction == "down"
    assert "bullish reclaim" in format_bos_state(result)


def test_prefers_the_direction_the_raw_bos_flag_currently_names():
    # Both a stale bearish break (of the labeled low) and a fresh bullish
    # break (of the labeled high) are present in the window -- since
    # structure_result.bos says "Bullish BOS", the state must describe
    # THAT break, not whichever side happens to have a later bar index.
    mixed_result = MarketStructureResult(
        swings=[
            SwingPoint(index=3, price=95.0, kind="low", label="LL"),
            SwingPoint(index=5, price=100.0, kind="high", label="LH"),
        ],
        structure="LL / LH", bos="Bullish BOS", score=0, label="",
    )
    highs, lows, closes, volumes = [], [], [], []
    price = 94.0
    for i in range(30):
        if i < 10:
            price = 94.5  # decisive bearish break of the 95.0 low early on
        elif i < 20:
            price = 99.9  # sits just under the 100.0 high
        else:
            price = 101.0 + (i - 20) * 0.5  # decisive, later bullish break of 100.0, then runs away
        highs.append(price + 0.1)
        lows.append(price - 0.1)
        closes.append(price)
        volumes.append(2000.0 if i in (10, 20) else 1000.0)
    result = classify_bos_state(mixed_result, highs, lows, closes, volumes)
    assert result.direction == "up"
    assert result.level_price == 100.0


def test_no_labeled_swings_is_no_break():
    empty_result = MarketStructureResult(swings=[], structure="Insufficient Data", bos="None", score=0, label="")
    highs, lows, closes, volumes = _flat_then_breakout(n=30, break_at=15, level=100.0, post_break_step=1.0)
    result = classify_bos_state(empty_result, highs, lows, closes, volumes)
    assert result.state == "no_break"


def test_close_beyond_the_level_before_the_swing_formed_is_not_a_break():
    # Regression (XRP/USD 1H, 2026-09-27): "bullish break of 1.5298" cited
    # a close from nine hours BEFORE the 1.5298 swing high existed. Here
    # the decisive close is at bar 15 but the swing high is only labeled
    # at bar 20 -- nothing after bar 20 closes above it.
    highs, lows, closes, volumes = _flat_then_breakout(n=30, break_at=15, level=100.0, post_break_step=0.0)
    for i in range(21, 30):
        closes[i], highs[i], lows[i] = 99.5, 99.6, 99.4
    result = classify_bos_state(_result_with_high(100.0, index=20), highs, lows, closes, volumes)
    assert result.state == "no_break"


def test_close_after_the_swing_formed_still_breaks_it():
    highs, lows, closes, volumes = _flat_then_breakout(n=30, break_at=15, level=100.0, post_break_step=1.0)
    result = classify_bos_state(_result_with_high(100.0, index=10), highs, lows, closes, volumes)
    assert result.state == "continuation"
