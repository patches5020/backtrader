"""Liquidity level detection (v1: equal-highs / equal-lows pools).

A cluster of swing highs (or lows) within `tolerance` of each other marks a
resting pool of sell-side (or buy-side) liquidity, per common ICT/SMC usage.
"""
import numpy as np


def _swing_points(series, order, is_high):
    """Return indices of local swing highs (or lows) using a symmetric window."""
    values = series.to_numpy()
    n = len(values)
    points = []
    for i in range(order, n - order):
        window = values[i - order:i + order + 1]
        if is_high and values[i] == window.max() and (window == values[i]).sum() == 1:
            points.append(i)
        elif not is_high and values[i] == window.min() and (window == values[i]).sum() == 1:
            points.append(i)
    return points


def detect_liquidity_levels(df, swing_order=3, tolerance=0.0015):
    """Return {"buy_side": [...], "sell_side": [...]} lists of {"price", "indices"} pools."""
    highs_idx = _swing_points(df["high"], swing_order, is_high=True)
    lows_idx = _swing_points(df["low"], swing_order, is_high=False)

    def _cluster(idx_list, series):
        prices = series.iloc[idx_list].to_numpy()
        order = np.argsort(prices)
        clusters = []
        current = [idx_list[order[0]]] if len(order) else []
        for k in range(1, len(order)):
            prev_price = prices[order[k - 1]]
            price = prices[order[k]]
            if abs(price - prev_price) <= tolerance * prev_price:
                current.append(idx_list[order[k]])
            else:
                if len(current) >= 2:
                    clusters.append(current)
                current = [idx_list[order[k]]]
        if len(current) >= 2:
            clusters.append(current)
        return [
            {"price": float(series.iloc[c].mean()), "indices": [df.index[i] for i in c]}
            for c in clusters
        ]

    return {
        "sell_side": _cluster(highs_idx, df["high"]),
        "buy_side": _cluster(lows_idx, df["low"]),
    }
