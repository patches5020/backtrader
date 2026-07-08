"""Fixed-range volume profile (v1: pandas histogram binning, no backtrader wrapper).

Bins the traded price range into equal-width buckets and sums volume per
bucket to approximate a volume profile, including the point of control (POC)
and a simple value-area estimate.
"""
import numpy as np
import pandas as pd


def compute_volume_profile(df, bins=24, value_area_pct=0.70):
    """Return a DataFrame indexed by price-bin midpoint with a 'volume' column,
    plus 'poc' (point of control price) and 'value_area' (low, high) in the result dict.
    """
    if df.empty:
        return {"profile": pd.DataFrame(columns=["volume"]), "poc": None, "value_area": (None, None)}

    low, high = df["low"].min(), df["high"].max()
    edges = np.linspace(low, high, bins + 1)
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    bin_idx = np.clip(np.digitize(typical_price, edges) - 1, 0, bins - 1)

    volume_per_bin = np.zeros(bins)
    np.add.at(volume_per_bin, bin_idx, df["volume"].to_numpy())

    midpoints = (edges[:-1] + edges[1:]) / 2.0
    profile = pd.DataFrame({"volume": volume_per_bin}, index=pd.Index(midpoints, name="price"))

    poc_bin = int(np.argmax(volume_per_bin))
    poc = midpoints[poc_bin]

    total_volume = volume_per_bin.sum()
    target = total_volume * value_area_pct
    included = {poc_bin}
    acc = volume_per_bin[poc_bin]
    lo, hi = poc_bin, poc_bin
    while acc < target and (lo > 0 or hi < bins - 1):
        left = volume_per_bin[lo - 1] if lo > 0 else -1
        right = volume_per_bin[hi + 1] if hi < bins - 1 else -1
        if right >= left:
            hi += 1
            acc += volume_per_bin[hi]
            included.add(hi)
        else:
            lo -= 1
            acc += volume_per_bin[lo]
            included.add(lo)

    value_area = (midpoints[lo], midpoints[hi])
    return {"profile": profile, "poc": poc, "value_area": value_area}
