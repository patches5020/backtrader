"""
anchored_vwap.py
------------------
Anchored VWAP with standard-deviation bands -- the same calculation as
TradingView's built-in "Anchored VWAP" in "Standard Deviation" band mode.
Verified 2026-10-16 against the live XRP/USD 1H chart (anchor 2026-10-14
00:00 UTC, source ohlc4): VWAP 1.319486 vs TradingView 1.319485, sigma
0.015153 vs 0.015155 (the gap is the still-forming candle ticking).

    p_i     = the bar's source price (ohlc4 by default; hlcc4 / hlc3 / close)
    VWAP_t  = sum(p_i * v_i) / sum(v_i)                over bars i = anchor..t
    sigma_t = sqrt(sum(v_i * p_i^2) / sum(v_i) - VWAP_t^2)
              (volume-weighted standard deviation -- not the plain stdev
              of prices)
    band k  = VWAP_t +/- k * sigma_t                  (k = 1, 2, 3)

A bar counts from its OPEN time: the first bar is the one opening at or
after the anchor. Bars that opened before the anchor are ignored.

Fails closed (returns None): no bars at or after the anchor, zero total
volume, or history that starts after the anchor (the VWAP would be missing
part of its range).

Analysis only: nothing here is read by confluence, the entry checklist,
the regime gate, the no-trade gate, risk sizing or execution.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

SOURCES = {
    "ohlc4": lambda o, h, l, c: (o + h + l + c) / 4,
    "hlcc4": lambda o, h, l, c: (h + l + c + c) / 4,
    "hlc3": lambda o, h, l, c: (h + l + c) / 3,
    "close": lambda o, h, l, c: c,
}
DEFAULT_SOURCE = "ohlc4"   # matches the user's TradingView Anchored VWAP and the VP/VWAP watchers
DEFAULT_BAND_MULTS = (1, 2, 3)


@dataclass
class AnchoredVWAP:
    anchor_ts: float                  # unix seconds
    source: str
    vwap: float
    sigma: float
    bars_used: int
    last_bar_ts: float                # open time (unix seconds) of the last bar included
    bands: dict[int, tuple[float, float]] = field(default_factory=dict)  # k -> (lower, upper)
    series: list[float] = field(default_factory=list)                    # VWAP after each included bar
    sigma_series: list[float] = field(default_factory=list)              # sigma after each included bar --
    # use these (not the final vwap/sigma) to judge a PAST bar against the bands as they stood then


def _seconds(ts: float) -> float:
    return ts / 1000 if ts > 1e11 else ts   # Crypto.com sends ms, the equity sources seconds


def anchored_vwap(
    timestamps: Sequence[float], opens: Sequence[float], highs: Sequence[float],
    lows: Sequence[float], closes: Sequence[float], volumes: Sequence[float],
    anchor_ts: float, source: str = DEFAULT_SOURCE,
    band_mults: Sequence[float] = DEFAULT_BAND_MULTS,
) -> Optional[AnchoredVWAP]:
    """Anchored VWAP and +/- k sigma bands through the last bar given. Pass
    closed bars only if the forming candle must not count."""
    if source not in SOURCES:
        raise ValueError(f"unknown VWAP source {source!r} (use one of {sorted(SOURCES)})")
    price_of = SOURCES[source]
    anchor = _seconds(anchor_ts)
    if not timestamps or _seconds(timestamps[0]) > anchor:
        return None   # history does not reach the anchor

    pv = pv2 = vol = 0.0
    used, last_ts, series, sigmas = 0, None, [], []
    for t, o, h, l, c, v in zip(timestamps, opens, highs, lows, closes, volumes):
        ts = _seconds(t)
        if ts < anchor:
            continue
        p = price_of(o, h, l, c)
        pv += p * v
        pv2 += p * p * v
        vol += v
        used += 1
        last_ts = ts
        if vol > 0:
            series.append(pv / vol)
            sigmas.append(math.sqrt(max(pv2 / vol - (pv / vol) ** 2, 0.0)))
        else:
            series.append(float("nan"))
            sigmas.append(float("nan"))
    if used == 0 or vol <= 0:
        return None

    vwap = pv / vol
    sigma = math.sqrt(max(pv2 / vol - vwap * vwap, 0.0))
    return AnchoredVWAP(
        anchor_ts=anchor, source=source, vwap=vwap, sigma=sigma, bars_used=used, last_bar_ts=last_ts,
        bands={k: (vwap - k * sigma, vwap + k * sigma) for k in band_mults},
        series=series, sigma_series=sigmas,
    )


def band_position(price: float, result: AnchoredVWAP) -> float:
    """Price's distance from the VWAP in sigmas (+1.5 = halfway between +1 and +2 sigma).
    0.0 when sigma is 0 (a single price so far)."""
    return (price - result.vwap) / result.sigma if result.sigma > 0 else 0.0
