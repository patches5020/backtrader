"""Order block detection (v1: simplified last-opposite-candle-before-impulse definition).

Bullish order block: the last down-close candle before an impulsive up move
(close moves up by more than `impulse_mult` * ATR within `lookahead` bars).
Bearish order block: the last up-close candle before an impulsive down move.
"""
from indicators.atr import atr as atr_series


def detect_order_blocks(df, lookahead=3, impulse_mult=1.5, atr_length=11):
    """Return a list of {"index", "type", "top", "bottom"} dicts, oldest first."""
    a = atr_series(df, atr_length)
    close = df["close"]
    open_ = df["open"]
    high = df["high"]
    low = df["low"]

    blocks = []
    n = len(df)
    for i in range(n - lookahead):
        atr_i = a.iloc[i]
        if atr_i != atr_i:  # NaN before warm-up
            continue
        future_close = close.iloc[i + lookahead]

        is_down_candle = close.iloc[i] < open_.iloc[i]
        if is_down_candle and (future_close - close.iloc[i]) > impulse_mult * atr_i:
            blocks.append({
                "index": df.index[i],
                "type": "bullish",
                "top": high.iloc[i],
                "bottom": low.iloc[i],
            })
            continue

        is_up_candle = close.iloc[i] > open_.iloc[i]
        if is_up_candle and (close.iloc[i] - future_close) > impulse_mult * atr_i:
            blocks.append({
                "index": df.index[i],
                "type": "bearish",
                "top": high.iloc[i],
                "bottom": low.iloc[i],
            })
    return blocks
