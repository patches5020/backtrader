"""
robinhood_equity.py
--------------------
Same OHLCV interface as cryptocom.py (fetch_ohlcv / fetch_ticker_price),
sourced from Robinhood instead of Crypto.com -- so `engine.analyze_ohlcv()`
and `engine.format_report()` (the exact "CDCX AI TRADE ANALYSIS" report) run
completely unchanged against equities/ETFs/indexes, same as crypto.

Auth is NOT reimplemented here -- `robinhood_mcp.auth.login()` (the same
package backing the connected robinhood-trading MCP tools) already solves
headless device-approval polling + TOTP + session caching to
~/.tokens/robinhood.pickle correctly; this module just calls it. See that
package's auth.py for the real logic.

Robinhood has no native 4-hour bar (interval is one of 5minute/10minute/
hour/day/week) -- "4h" is built by aggregating 4 consecutive hourly bars.
This is NOT calendar-aligned (a trading day is ~6.5 regular hours, so the
grouping drifts across day boundaries) -- good enough for indicator
scoring, not a precise 4h chart. Documented here rather than silently
treated as exact.

"1w" is built from DAILY bars grouped by calendar week (Mon-Fri, stamped
Monday 00:00 UTC), not Robinhood's native interval="week". The native
weekly series lags: confirmed live 2026-09-26 (a Saturday) it still ended
at the week of Sep 14 while the daily series already held all of Sep
21-25. Checked against the native series over 60 completed weeks: the
daily-built bars matched open/high/low/close/volume exactly, with the
same Monday stamp.

WARNING -- crypto-shorthand ticker collisions: this module only calls
`get_stock_historicals()`, Robinhood's stocks/ETFs endpoint -- there is no
crypto code path here at all. If you pass a crypto shorthand like "XRP",
"BTC", or "ETH" as --symbol, Robinhood will NOT reject it: several spot
crypto ETFs are listed under exactly those tickers (e.g. NYSE Arca "XRP"
= Bitwise XRP ETF), so the fetch silently succeeds against the ETF's
share price instead of the coin's spot price. An ETF's share price is
NOT 1:1 with spot (it reflects the trust's per-share unit structure --
confirmed a ~10x gap for XRP), so every downstream number (entry, ATR,
stop, FVG, structure report) will be real but for the wrong instrument,
with no error to flag it. For the actual cryptocurrency, use the crypto
path (`cdcx-ai` / cli.py -> cryptocom.py), which expects pair-style
symbols like "XRPUSD", not bare "XRP".
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from .cryptocom import OHLCV

# timeframe (cdcx's own strings, e.g. "1h") -> (robin_stocks interval, span).
# span is chosen generously so `limit` bars are almost always available;
# fetch_ohlcv slices to the last `limit` afterward.
_TIMEFRAME_MAP = {
    "1h": ("hour", "3month"),
    "4h": ("hour", "3month"),  # aggregated 4x below -- see module docstring
    "1d": ("day", "5year"),
    "1w": ("day", "5year"),  # grouped into calendar weeks below -- see module docstring
}


class RobinhoodAuthError(RuntimeError):
    pass


class RobinhoodEquityExchange:
    def __init__(self):
        try:
            from robinhood_mcp import auth as rh_auth
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "robinhood_mcp is required -- install with `pip install robinhood-mcp`"
            ) from exc
        try:
            import robin_stocks.robinhood as rh
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "robin_stocks is required -- install with `pip install robin_stocks`"
            ) from exc

        try:
            rh_auth.login()
        except rh_auth.AuthenticationError as exc:
            raise RobinhoodAuthError(
                f"Robinhood login failed: {exc}\n"
                "Set ROBINHOOD_USERNAME / ROBINHOOD_PASSWORD (and optionally "
                "ROBINHOOD_TOTP_SECRET for authenticator-app 2FA) in .env. "
                "On first login you'll need to approve a device prompt in the "
                "Robinhood app, or answer the TOTP challenge -- after that the "
                "session is cached to ~/.tokens/robinhood.pickle."
            ) from exc
        self._rh = rh

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 200) -> OHLCV:
        if timeframe not in _TIMEFRAME_MAP:
            raise ValueError(
                f"Unsupported timeframe '{timeframe}' for Robinhood -- supported: "
                f"{sorted(_TIMEFRAME_MAP)}."
            )
        interval, span = _TIMEFRAME_MAP[timeframe]
        rows = self._rh.get_stock_historicals(symbol, interval=interval, span=span, bounds="regular")
        data = _parse_historicals(rows)

        if timeframe == "4h":
            data = _aggregate(data, factor=4)
        elif timeframe == "1w":
            data = _aggregate_weekly(data)

        return _tail(data, limit)

    def fetch_ticker_price(self, symbol: str) -> float:
        price = self._rh.get_latest_price(symbol, includeExtendedHours=False)
        if not price or price[0] is None:
            raise RuntimeError(f"No live price returned for {symbol!r} from Robinhood.")
        return float(price[0])


def _parse_historicals(rows: list[dict | None]) -> OHLCV:
    """rows: robin_stocks get_stock_historicals() output -- see module
    docstring for the verified dict-key schema (begins_at/open_price/
    close_price/high_price/low_price/volume). Robinhood returns None for
    bars with no data (e.g. a gap) -- those are dropped."""
    rows = [r for r in rows if r]
    if not rows:
        raise RuntimeError("Robinhood returned no historical bars -- check the symbol is valid and tradable.")

    timestamps, opens, highs, lows, closes, volumes = [], [], [], [], [], []
    for row in rows:
        dt = datetime.strptime(row["begins_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        timestamps.append(int(dt.timestamp()))
        opens.append(float(row["open_price"]))
        highs.append(float(row["high_price"]))
        lows.append(float(row["low_price"]))
        closes.append(float(row["close_price"]))
        volumes.append(float(row["volume"]))

    return OHLCV(timestamps=timestamps, opens=opens, highs=highs, lows=lows, closes=closes, volumes=volumes)


def _aggregate(data: OHLCV, factor: int) -> OHLCV:
    """Groups every `factor` consecutive bars into one (open of the first,
    close of the last, max high, min low, summed volume). Non-calendar-
    aligned -- see module docstring."""
    n = len(data.closes) - (len(data.closes) % factor)
    timestamps, opens, highs, lows, closes, volumes = [], [], [], [], [], []
    for i in range(0, n, factor):
        timestamps.append(data.timestamps[i])
        opens.append(data.opens[i])
        highs.append(max(data.highs[i:i + factor]))
        lows.append(min(data.lows[i:i + factor]))
        closes.append(data.closes[i + factor - 1])
        volumes.append(sum(data.volumes[i:i + factor]))
    return OHLCV(timestamps=timestamps, opens=opens, highs=highs, lows=lows, closes=closes, volumes=volumes)


def _aggregate_weekly(data: OHLCV) -> OHLCV:
    """Groups daily bars into calendar weeks (open of the week's first
    session, close of its last, max high, min low, summed volume), each
    stamped Monday 00:00 UTC -- the same stamp Robinhood's native weekly
    bars use, even for a holiday-shortened week."""
    timestamps, opens, highs, lows, closes, volumes = [], [], [], [], [], []
    for i, ts in enumerate(data.timestamps):
        day = datetime.fromtimestamp(ts, tz=timezone.utc)
        monday = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp()) - day.weekday() * 86400
        if timestamps and timestamps[-1] == monday:
            highs[-1] = max(highs[-1], data.highs[i])
            lows[-1] = min(lows[-1], data.lows[i])
            closes[-1] = data.closes[i]
            volumes[-1] += data.volumes[i]
        else:
            timestamps.append(monday)
            opens.append(data.opens[i])
            highs.append(data.highs[i])
            lows.append(data.lows[i])
            closes.append(data.closes[i])
            volumes.append(data.volumes[i])
    return OHLCV(timestamps=timestamps, opens=opens, highs=highs, lows=lows, closes=closes, volumes=volumes)


def _tail(data: OHLCV, limit: int) -> OHLCV:
    if limit <= 0 or len(data.closes) <= limit:
        return data
    return OHLCV(
        timestamps=data.timestamps[-limit:], opens=data.opens[-limit:], highs=data.highs[-limit:],
        lows=data.lows[-limit:], closes=data.closes[-limit:], volumes=data.volumes[-limit:],
    )
