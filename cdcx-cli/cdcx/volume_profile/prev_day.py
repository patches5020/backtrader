"""
prev_day.py
-------------
Previous-day anchor (Variant A, chosen by the user 2026-10-16): a FROZEN
fixed volume profile of the previous completed session, plus an anchored
VWAP (with +/- 1/2/3 sigma bands) that starts at that session's open and
runs through the latest CLOSED bar.

Sessions:
    crypto ("24x7")       the previous completed UTC day, 00:00-24:00 UTC
                          (Crypto.com's daily candle)
    equity ("us_equity")  the most recent completed regular session,
                          09:30-16:00 America/New_York (DST-correct). The
                          equity sources only fetch regular-hours bars, so
                          the VWAP skips overnight by construction.

The profile is built only from bars that opened inside the session window,
so it can't change until the next session completes -- a level can't form
around price after the fact. It reuses volume_profile_fixed's existing
POC/VAH/VAL/HVN/LVN math (70% value area, 24 buckets) unchanged.

Fails closed: any missing bar in the session, no completed session in the
data, or an unusable VWAP gives status UNKNOWN with the reason -- never a
partial profile presented as complete.

Known limitation: equity half-days (13:00 ET close) count as completed only
after 16:00 ET, and their shorter bar count reads as missing bars (UNKNOWN).
Holidays are skipped because they have no bars; the session actually used
is always reported.

INFORMATION ONLY -- see fvp_analysis.py's module docstring for scope.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from .. import no_trade_gate
from ..indicators import anchored_vwap as avwap_module
from ..indicators import volume_profile_fixed

ET = ZoneInfo("America/New_York")
EQUITY_OPEN = (9, 30)
EQUITY_CLOSE = (16, 0)
DAY_S = 86400


@dataclass
class PrevDayLevels:
    status: str                         # "OK" | "UNKNOWN"
    reasons: list[str] = field(default_factory=list)
    market: str = no_trade_gate.MARKET_24X7
    timeframe: str = ""
    session_start: Optional[float] = None   # unix seconds
    session_end: Optional[float] = None
    session_bars: int = 0
    poc: Optional[float] = None
    vah: Optional[float] = None
    val: Optional[float] = None
    hvn: Optional[float] = None
    lvn: Optional[float] = None
    avwap: Optional[avwap_module.AnchoredVWAP] = None


def _seconds(ts: float) -> float:
    return no_trade_gate.timestamp_to_seconds(ts)


def crypto_session(now: float) -> tuple[float, float]:
    """[start, end) of the previous completed UTC day."""
    end = math.floor(now / DAY_S) * DAY_S
    return end - DAY_S, end


def _equity_bounds(day) -> tuple[float, float]:
    start = datetime(day.year, day.month, day.day, *EQUITY_OPEN, tzinfo=ET)
    end = datetime(day.year, day.month, day.day, *EQUITY_CLOSE, tzinfo=ET)
    return start.timestamp(), end.timestamp()


def equity_session(timestamps_s: list[float], now: float) -> Optional[tuple[float, float]]:
    """[start, end) of the most recent regular session with bars that had
    closed (16:00 ET) by `now`. None if the data has no such session."""
    days = sorted({datetime.fromtimestamp(t, timezone.utc).astimezone(ET).date() for t in timestamps_s},
                  reverse=True)
    for day in days:
        start, end = _equity_bounds(day)
        if end <= now:
            return start, end
    return None


def prev_day_levels(
    data, timeframe: str, now: Optional[float] = None, market: Optional[str] = None,
    source: str = avwap_module.DEFAULT_SOURCE,
) -> PrevDayLevels:
    """Previous-session frozen profile + previous-session-anchored VWAP from
    one OHLCV series (`data.timestamps` are bar OPEN times, ms or s)."""
    now = time.time() if now is None else now
    market = market or getattr(data, "market", no_trade_gate.MARKET_24X7)
    out = PrevDayLevels(status="UNKNOWN", market=market, timeframe=timeframe)

    tf_s = no_trade_gate.timeframe_to_seconds(timeframe)
    if not tf_s or tf_s >= DAY_S:
        out.reasons.append(f"timeframe {timeframe!r} must be intraday")
        return out
    ts = [_seconds(t) for t in data.timestamps]
    if not ts:
        out.reasons.append("no bars")
        return out

    if market == no_trade_gate.MARKET_US_EQUITY:
        bounds = equity_session(ts, now)
        if bounds is None:
            out.reasons.append("no completed regular session in the data")
            return out
    else:
        bounds = crypto_session(now)
    start, end = bounds
    out.session_start, out.session_end = start, end

    idx = [i for i, t in enumerate(ts) if start <= t < end]
    expected = math.ceil((end - start) / tf_s)
    out.session_bars = len(idx)
    if len(idx) != expected:
        out.reasons.append(f"session has {len(idx)} of {expected} {timeframe} bars -- missing data")
        return out

    highs = [data.highs[i] for i in idx]
    lows = [data.lows[i] for i in idx]
    vols = [data.volumes[i] for i in idx]
    if sum(vols) <= 0:
        out.reasons.append("session volume is zero")
        return out
    vp = volume_profile_fixed.analyze(highs, lows, vols, price=data.closes[idx[-1]], lookback=len(idx))
    out.poc, out.vah, out.val, out.hvn, out.lvn = vp.poc, vp.vah, vp.val, vp.hvn, vp.lvn

    # VWAP: from the session open through the latest CLOSED bar (the forming one never counts).
    n = len(ts)
    if no_trade_gate.last_bar_is_forming(ts, timeframe, now, market=market):
        n -= 1
    # Stale feed (24x7 only -- an equity feed is legitimately quiet outside the session).
    if market != no_trade_gate.MARKET_US_EQUITY and n > 0:
        age_bars = (now - (ts[n - 1] + tf_s)) / tf_s
        if age_bars > no_trade_gate.DEFAULT_MAX_DATA_STALENESS_BARS:
            out.reasons.append(f"data is stale: last closed {timeframe} bar ended {age_bars:.1f} bars ago")
            return out
    out.avwap = avwap_module.anchored_vwap(
        ts[:n], data.opens[:n], data.highs[:n], data.lows[:n], data.closes[:n], data.volumes[:n],
        anchor_ts=start, source=source,
    )
    if out.avwap is None:
        out.reasons.append("anchored VWAP unavailable (no volume or history after the anchor)")
        return out

    out.status = "OK"
    return out
