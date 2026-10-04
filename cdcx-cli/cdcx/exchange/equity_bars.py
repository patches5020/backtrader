"""
equity_bars.py
--------------
Intraday bar building shared by the equity sources (robinhood_equity.py,
webull_equity.py): makes an N-minute bar the source doesn't serve (e.g. 15m,
30m, 45m from Robinhood's 5/10-minute bars) out of a smaller native one.

US equities trade a 9:30-16:00 ET session, so intraday bars are anchored to
each trading day's FIRST bar (the session open), the way TradingView draws
them -- 9:30, 9:45, 10:00 ... for 15m; 9:30, 10:15, 11:00 ... for 45m. The
session's last group can be short (6.5 h isn't a multiple of 45 min); it is
kept, like TradingView's last bar of the day. open = first open, high = max,
low = min, close = last close, volume = sum, timestamp = the group's start.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .cryptocom import OHLCV


def aggregate_session_minutes(data: OHLCV, minutes: int) -> OHLCV:
    """Group intraday bars into `minutes`-minute bars anchored to each UTC date's
    first bar (a regular US session never crosses UTC midnight). Timestamps may be
    unix seconds or milliseconds; the output keeps the input's unit."""
    if not data.timestamps:
        return data
    scale = 1000 if data.timestamps[0] > 1e11 else 1
    span = minutes * 60 * scale
    keys: list[tuple] = []
    out = {"t": [], "o": [], "h": [], "l": [], "c": [], "v": []}
    anchor_by_day: dict = {}
    for i, ts in enumerate(data.timestamps):
        day = datetime.fromtimestamp(ts / scale, tz=timezone.utc).date()
        anchor = anchor_by_day.setdefault(day, ts)
        key = (day, (ts - anchor) // span)
        if keys and keys[-1] == key:
            out["h"][-1] = max(out["h"][-1], data.highs[i])
            out["l"][-1] = min(out["l"][-1], data.lows[i])
            out["c"][-1] = data.closes[i]
            out["v"][-1] += data.volumes[i]
        else:
            keys.append(key)
            out["t"].append(anchor + key[1] * span)
            out["o"].append(data.opens[i])
            out["h"].append(data.highs[i])
            out["l"].append(data.lows[i])
            out["c"].append(data.closes[i])
            out["v"].append(data.volumes[i])
    return OHLCV(timestamps=out["t"], opens=out["o"], highs=out["h"], lows=out["l"], closes=out["c"],
                 volumes=out["v"])
