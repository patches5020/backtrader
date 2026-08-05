"""
volume_profile_anchor.py
--------------------------
Anchored Volume Profile: same POC/VAH/VAL mechanics as the fixed-range
profile, but the lookback window starts at a specific anchor point (e.g. a
swing low/high, a session open, or a market-structure break) instead of a
fixed bar count. Re-uses the histogram/value-area math from
volume_profile_fixed.py.

Weight: Anchored Volume Profile -> 10
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .volume_profile_fixed import build_volume_profile, calculate_poc_vah_val

ANCHORED_VP_WEIGHT = 10


@dataclass
class AnchoredVolumeProfileResult:
    anchor_index: int
    poc: float
    vah: float
    val: float
    score: int
    label: str


def find_anchor_index(
    closes: Sequence[float], lookback: int = 50, mode: str = "swing_low"
) -> int:
    """
    Locates a reasonable anchor point within the last `lookback` bars.
    mode: "swing_low" anchors at the lowest close, "swing_high" at the highest.
    """
    window = closes[-lookback:]
    offset = len(closes) - len(window)

    if mode == "swing_high":
        idx_in_window = max(range(len(window)), key=lambda i: window[i])
    else:
        idx_in_window = min(range(len(window)), key=lambda i: window[i])

    return offset + idx_in_window


def score_anchored_volume_profile(price: float, poc: float, vah: float, val: float) -> tuple[int, str]:
    if price > vah:
        return ANCHORED_VP_WEIGHT, "Above Value Area"
    if price > poc:
        return ANCHORED_VP_WEIGHT * 2 // 3, "Above POC"
    if price < val:
        return -ANCHORED_VP_WEIGHT, "Below Value Area"
    if price < poc:
        return -(ANCHORED_VP_WEIGHT * 2 // 3), "Below POC"
    return 0, "At POC"


def analyze(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
    volumes: Sequence[float], price: float, anchor_lookback: int = 50, anchor_mode: str = "swing_low",
) -> AnchoredVolumeProfileResult:
    anchor_idx = find_anchor_index(closes, lookback=anchor_lookback, mode=anchor_mode)

    anchored_highs = highs[anchor_idx:]
    anchored_lows = lows[anchor_idx:]
    anchored_volumes = volumes[anchor_idx:]

    histogram = build_volume_profile(anchored_highs, anchored_lows, anchored_volumes)
    poc, vah, val = calculate_poc_vah_val(histogram)
    score, label = score_anchored_volume_profile(price, poc, vah, val)

    return AnchoredVolumeProfileResult(
        anchor_index=anchor_idx, poc=poc, vah=vah, val=val, score=score, label=label
    )


if __name__ == "__main__":
    import random
    random.seed(2)
    n = 60
    closes = [100 + i * 0.4 + random.uniform(-0.4, 0.4) for i in range(n)]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    volumes = [random.uniform(50, 200) for _ in range(n)]

    result = analyze(highs, lows, closes, volumes, price=closes[-1])
    print(f"Anchor index: {result.anchor_index}")
    print(f"POC: {result.poc:.2f}  VAH: {result.vah:.2f}  VAL: {result.val:.2f}")
    print(f"Score: {result.score:+d} ({result.label})")
