"""Fibonacci retracement levels (v1: simple swing-based, no backtrader wrapper).

Finds the highest high / lowest low over a lookback window and derives the
standard retracement levels between them. Direction (uptrend vs downtrend)
is inferred from which swing point occurred more recently.
"""
RATIOS = (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0)


def compute_fibonacci_levels(df, lookback=100, ratios=RATIOS):
    """Return {"direction": "up"|"down", "high": float, "low": float, "levels": {ratio: price}}."""
    window = df.tail(lookback)
    if window.empty:
        return {"direction": None, "high": None, "low": None, "levels": {}}

    high_idx = window["high"].idxmax()
    low_idx = window["low"].idxmin()
    high = window.loc[high_idx, "high"]
    low = window.loc[low_idx, "low"]

    uptrend = window.index.get_loc(low_idx) < window.index.get_loc(high_idx)
    span = high - low

    levels = {}
    for ratio in ratios:
        levels[ratio] = high - span * ratio if uptrend else low + span * ratio

    return {
        "direction": "up" if uptrend else "down",
        "high": high,
        "low": low,
        "levels": levels,
    }
