"""
synthetic.py
------------
Generate realistic multi-regime synthetic OHLCV for offline backtesting.
Produces trending, ranging, and high-volatility segments so the CDCX
indicators have something non-trivial to react to.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional

from cdcx.exchange.cryptocom import OHLCV


@dataclass
class Regime:
    name: str
    n_bars: int
    drift: float          # mean log-return per bar
    vol: float            # std of log-return per bar
    vol_of_vol: float = 0.0


def _generate_segment(
    start_price: float,
    n: int,
    drift: float,
    vol: float,
    vol_of_vol: float,
    rng: random.Random,
    start_ts: int,
    bar_ms: int,
) -> tuple[list[float], list[float], list[float], list[float], list[float], list[int]]:
    opens, highs, lows, closes, volumes, timestamps = [], [], [], [], [], []
    price = start_price
    current_vol = vol

    for i in range(n):
        # stochastic volatility
        current_vol = max(0.001, current_vol + rng.gauss(0, vol_of_vol))
        ret = drift + current_vol * rng.gauss(0, 1)
        open_p = price
        close_p = price * math.exp(ret)

        # intra-bar range proportional to vol
        range_pct = abs(rng.gauss(0, current_vol * 1.8))
        high_p = max(open_p, close_p) * (1 + range_pct * 0.6)
        low_p = min(open_p, close_p) * (1 - range_pct * 0.6)

        # occasional wicks
        if rng.random() < 0.15:
            if rng.random() < 0.5:
                high_p *= 1 + abs(rng.gauss(0, current_vol))
            else:
                low_p *= 1 - abs(rng.gauss(0, current_vol))

        vol_bar = max(10.0, rng.lognormvariate(5.0, 0.6) * (1 + abs(ret) * 8))

        opens.append(open_p)
        highs.append(high_p)
        lows.append(low_p)
        closes.append(close_p)
        volumes.append(vol_bar)
        timestamps.append(start_ts + i * bar_ms)
        price = close_p

    return opens, highs, lows, closes, volumes, timestamps


def generate_ohlcv(
    n_bars: int = 1500,
    start_price: float = 60000.0,
    seed: int = 42,
    timeframe: str = "1h",
    regimes: Optional[list[Regime]] = None,
) -> OHLCV:
    """
    Build a multi-regime synthetic series.

    Default regimes (for ~1500 1h bars ≈ 2 months):
      - mild uptrend
      - choppy range
      - strong downtrend
      - high-vol recovery
      - quiet grind higher
    """
    rng = random.Random(seed)

    bar_ms = {
        "1h": 3_600_000,
        "4h": 14_400_000,
        "1d": 86_400_000,
        "1w": 604_800_000,
    }.get(timeframe, 3_600_000)

    if regimes is None:
        # approximate proportions of total bars
        regimes = [
            Regime("mild_up", int(n_bars * 0.20), drift=0.00018, vol=0.007, vol_of_vol=0.0006),
            Regime("chop", int(n_bars * 0.22), drift=0.00000, vol=0.010, vol_of_vol=0.0010),
            Regime("strong_down", int(n_bars * 0.18), drift=-0.00045, vol=0.013, vol_of_vol=0.0012),
            Regime("high_vol_up", int(n_bars * 0.18), drift=0.00030, vol=0.016, vol_of_vol=0.0015),
            Regime("quiet_range", n_bars - int(n_bars * 0.78), drift=0.00005, vol=0.006, vol_of_vol=0.0004),
        ]

    all_o, all_h, all_l, all_c, all_v, all_ts = [], [], [], [], [], []
    price = start_price
    ts = 1_700_000_000_000  # arbitrary epoch ms

    for reg in regimes:
        o, h, l, c, v, t = _generate_segment(
            price, reg.n_bars, reg.drift, reg.vol, reg.vol_of_vol, rng, ts, bar_ms
        )
        all_o.extend(o)
        all_h.extend(h)
        all_l.extend(l)
        all_c.extend(c)
        all_v.extend(v)
        all_ts.extend(t)
        if all_c:
            price = all_c[-1]
            ts = all_ts[-1] + bar_ms

    return OHLCV(
        timestamps=all_ts,
        opens=all_o,
        highs=all_h,
        lows=all_l,
        closes=all_c,
        volumes=all_v,
    )


def resample_ohlcv(data: OHLCV, factor: int) -> OHLCV:
    """Simple OHLC resampling by integer factor (e.g. 4x 1h -> 4h)."""
    n = len(data.closes) // factor
    timestamps, opens, highs, lows, closes, volumes = [], [], [], [], [], []
    for i in range(n):
        sl = slice(i * factor, (i + 1) * factor)
        timestamps.append(data.timestamps[sl][-1])
        opens.append(data.opens[sl][0])
        highs.append(max(data.highs[sl]))
        lows.append(min(data.lows[sl]))
        closes.append(data.closes[sl][-1])
        volumes.append(sum(data.volumes[sl]))
    return OHLCV(timestamps, opens, highs, lows, closes, volumes)


if __name__ == "__main__":
    data = generate_ohlcv(800, seed=7)
    print(f"Generated {len(data.closes)} bars")
    print(f"Start {data.closes[0]:.1f} -> End {data.closes[-1]:.1f}")
    print(f"Min {min(data.lows):.1f}  Max {max(data.highs):.1f}")
