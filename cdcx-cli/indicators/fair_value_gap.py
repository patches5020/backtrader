"""Fair value gap / imbalance detection (v1: classic 3-candle ICT definition).

Bullish FVG: candle[i].low > candle[i-2].high  (gap left by candle i-1's move up)
Bearish FVG: candle[i].high < candle[i-2].low  (gap left by candle i-1's move down)
"""
import pandas as pd


def detect_fair_value_gaps(df):
    """Return a list of {"index", "type", "top", "bottom"} dicts, oldest first."""
    gaps = []
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    index = df.index

    for i in range(2, len(df)):
        if low[i] > high[i - 2]:
            gaps.append({
                "index": index[i],
                "type": "bullish",
                "bottom": high[i - 2],
                "top": low[i],
            })
        elif high[i] < low[i - 2]:
            gaps.append({
                "index": index[i],
                "type": "bearish",
                "bottom": high[i],
                "top": low[i - 2],
            })
    return gaps


def fair_value_gaps_dataframe(df):
    gaps = detect_fair_value_gaps(df)
    return pd.DataFrame(gaps, columns=["index", "type", "top", "bottom"]).set_index("index") if gaps \
        else pd.DataFrame(columns=["type", "top", "bottom"])
