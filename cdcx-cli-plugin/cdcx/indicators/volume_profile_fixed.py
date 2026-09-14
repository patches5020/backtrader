"""
volume_profile_fixed.py
------------------------
Fixed-range Volume Profile over the most recent N bars: builds a price/volume
histogram and derives:
    POC (Point of Control)   -> price bucket with the highest traded volume
    VAH (Value Area High)    -> upper bound of the 70% value area
    VAL (Value Area Low)     -> lower bound of the 70% value area

Weight: Fixed Volume Profile -> 10
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

FIXED_VP_WEIGHT = 10
VALUE_AREA_PCT = 0.70
DEFAULT_BUCKETS = 24
DEFAULT_LOOKBACK = 100


@dataclass
class VolumeProfileResult:
    poc: float
    vah: float
    val: float
    score: int
    label: str


def build_volume_profile(
    highs: Sequence[float], lows: Sequence[float], volumes: Sequence[float],
    buckets: int = DEFAULT_BUCKETS,
) -> dict[float, float]:
    """Distributes each bar's volume evenly across the price buckets it spans."""
    lo = min(lows)
    hi = max(highs)
    if hi <= lo:
        raise ValueError("Invalid price range for volume profile")

    bucket_size = (hi - lo) / buckets
    histogram = {lo + i * bucket_size + bucket_size / 2: 0.0 for i in range(buckets)}
    bucket_prices = list(histogram.keys())

    for bar_high, bar_low, vol in zip(highs, lows, volumes):
        touched = [p for p in bucket_prices if bar_low <= p <= bar_high]
        if not touched:
            # bar entirely inside one bucket (rounding edge case) -> nearest bucket
            nearest = min(bucket_prices, key=lambda p: abs(p - (bar_high + bar_low) / 2))
            histogram[nearest] += vol
            continue
        share = vol / len(touched)
        for p in touched:
            histogram[p] += share

    return histogram


def calculate_poc_vah_val(histogram: dict[float, float], value_area_pct: float = VALUE_AREA_PCT):
    poc_price = max(histogram, key=histogram.get)
    total_volume = sum(histogram.values())
    target_volume = total_volume * value_area_pct

    sorted_prices = sorted(histogram.keys())
    poc_idx = sorted_prices.index(poc_price)

    included = {poc_price}
    accumulated = histogram[poc_price]
    low_idx, high_idx = poc_idx, poc_idx

    while accumulated < target_volume and (low_idx > 0 or high_idx < len(sorted_prices) - 1):
        vol_below = histogram[sorted_prices[low_idx - 1]] if low_idx > 0 else -1
        vol_above = histogram[sorted_prices[high_idx + 1]] if high_idx < len(sorted_prices) - 1 else -1

        if vol_above >= vol_below:
            high_idx += 1
            accumulated += histogram[sorted_prices[high_idx]]
            included.add(sorted_prices[high_idx])
        else:
            low_idx -= 1
            accumulated += histogram[sorted_prices[low_idx]]
            included.add(sorted_prices[low_idx])

    vah = max(included)
    val = min(included)
    return poc_price, vah, val


def score_volume_profile(price: float, poc: float, vah: float, val: float) -> tuple[int, str]:
    if price > vah:
        return FIXED_VP_WEIGHT, "Above Value Area"
    if price > poc:
        return FIXED_VP_WEIGHT * 2 // 3, "Above POC"
    if price < val:
        return -FIXED_VP_WEIGHT, "Below Value Area"
    if price < poc:
        return -(FIXED_VP_WEIGHT * 2 // 3), "Below POC"
    return 0, "At POC"


def analyze(
    highs: Sequence[float], lows: Sequence[float], volumes: Sequence[float], price: float,
    lookback: int = DEFAULT_LOOKBACK,
) -> VolumeProfileResult:
    highs, lows, volumes = highs[-lookback:], lows[-lookback:], volumes[-lookback:]
    histogram = build_volume_profile(highs, lows, volumes)
    poc, vah, val = calculate_poc_vah_val(histogram)
    score, label = score_volume_profile(price, poc, vah, val)
    return VolumeProfileResult(poc=poc, vah=vah, val=val, score=score, label=label)


if __name__ == "__main__":
    import random
    random.seed(1)
    n = 50
    closes = [100 + i * 0.3 + random.uniform(-0.5, 0.5) for i in range(n)]
    highs = [c + 0.6 for c in closes]
    lows = [c - 0.6 for c in closes]
    volumes = [random.uniform(50, 200) for _ in range(n)]

    result = analyze(highs, lows, volumes, price=closes[-1])
    print(f"POC: {result.poc:.2f}  VAH: {result.vah:.2f}  VAL: {result.val:.2f}")
    print(f"Score: {result.score:+d} ({result.label})")
