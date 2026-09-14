"""
webull_equity.py
-----------------
Same OHLCV interface as cryptocom.py (fetch_ohlcv / fetch_ticker_price),
sourced from Webull's official OpenAPI (the `webull-openapi-python-sdk`
package) instead of Crypto.com -- so `engine.analyze_ohlcv()` and
`engine.format_report()` run unchanged against Webull-listed symbols too.

This is a DIFFERENT Webull connection than the `mcp__claude_ai_Webull__*`
MCP tools available inside a Claude Code session -- those are a managed
Claude.ai connector and are not reachable by a standalone script (see
cdcx/brokers/webull.py for that boundary, if present in this checkout).
This module authenticates directly against Webull's OpenAPI with your own
app_key/app_secret from https://developer.webull.com -- set
WEBULL_APP_KEY / WEBULL_APP_SECRET (and optionally WEBULL_REGION_ID,
default "us") in .env.

Unlike robinhood_equity.py, this module's response parsing was verified
against the SDK's REQUEST-building code (webull/data/request/
get_historical_bars_request.py, webull/data/quotes/market_data.py) but
NOT against a live response body -- the SDK returns the raw `requests`
Response object and leaves JSON parsing to the caller, and no local docs
give the exact field names. `_parse_history_bar_response()` below tries
several plausible key spellings and raises a clear, actionable error
listing the *actual* keys seen if none match, rather than silently
guessing wrong. If you hit that error, paste the raw bar dict it prints
and the key-lookup table can be corrected in one place.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from .cryptocom import OHLCV

# timeframe (cdcx's own strings) -> webull.data.common.timespan.Timespan.
# Webull has a real 240-minute (4h) bar -- unlike Robinhood, no aggregation
# needed here.
_TIMEFRAME_TO_TIMESPAN_NAME = {
    "1h": "M60",
    "4h": "M240",
    "1d": "D",
    "1w": "W",
}

# Plausible field-name spellings for each OHLCV component, tried in order.
# See module docstring: this is the one part of this adapter not verified
# against a live response.
_FIELD_CANDIDATES = {
    "timestamp": ("timestamp", "ts", "time", "tradeTime", "trade_time", "t"),
    "open": ("open", "openPrice", "open_price", "o"),
    "high": ("high", "highPrice", "high_price", "h"),
    "low": ("low", "lowPrice", "low_price", "l"),
    "close": ("close", "closePrice", "close_price", "c"),
    "volume": ("volume", "vol", "v"),
}


class WebullAuthError(RuntimeError):
    pass


DEFAULT_SANDBOX_HOST = "api.sandbox.webull.com"


class WebullEquityExchange:
    def __init__(
        self, app_key: str | None = None, app_secret: str | None = None, region_id: str | None = None,
        environment: str | None = None,
    ):
        app_key = app_key or os.getenv("WEBULL_APP_KEY", "")
        app_secret = app_secret or os.getenv("WEBULL_APP_SECRET", "")
        region_id = region_id or os.getenv("WEBULL_REGION_ID", "us")
        # "production" (default) hits api.webull.com; "sandbox" (or "paper") hits
        # api.sandbox.webull.com -- required if your app was registered as a
        # Paper Trading app on developer.webull.com (per Webull's own docs:
        # https://developer.webull.com/apis/docs/sdk -- "sandbox environment is
        # for development and integration testing... refer to Trading API
        # Application to create a test account"). A Paper Trading app's
        # credentials are rejected with HTTP 401 "ensure you are connecting to
        # the correct environment" against the production host -- that exact
        # error is what sent us here.
        environment = (environment or os.getenv("WEBULL_ENVIRONMENT", "production")).strip().lower()

        if not app_key or not app_secret:
            raise WebullAuthError(
                "WEBULL_APP_KEY / WEBULL_APP_SECRET are not set. Register an app at "
                "https://developer.webull.com and put both in .env. This is separate "
                "from the Webull MCP tools already connected in Claude.ai -- this "
                "module talks to Webull's OpenAPI directly, with your own credentials."
            )

        try:
            from webull.core.client import ApiClient
            from webull.data.data_client import DataClient
            from webull.data.common.category import Category
            from webull.data.common.timespan import Timespan
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "webull-openapi-python-sdk is required -- install with "
                "`pip install webull-openapi-python-sdk`"
            ) from exc

        self._Category = Category
        self._Timespan = Timespan
        api_client = ApiClient(app_key=app_key, app_secret=app_secret, region_id=region_id)
        if environment in ("sandbox", "paper", "paper_trading", "paper-trading"):
            sandbox_host = os.getenv("WEBULL_SANDBOX_HOST", DEFAULT_SANDBOX_HOST)
            api_client.add_endpoint(region_id, sandbox_host)
        self._data_client = DataClient(api_client)

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 200) -> OHLCV:
        if timeframe not in _TIMEFRAME_TO_TIMESPAN_NAME:
            raise ValueError(
                f"Unsupported timeframe '{timeframe}' for Webull -- supported: "
                f"{sorted(_TIMEFRAME_TO_TIMESPAN_NAME)}."
            )
        timespan = getattr(self._Timespan, _TIMEFRAME_TO_TIMESPAN_NAME[timeframe])
        # Webull caps count at 1200 per request (see get_historical_bars_request.py docstring).
        count = str(min(max(limit, 1), 1200))

        response = self._data_client.market_data.get_history_bar(
            symbol=symbol, category=self._Category.US_STOCK, timespan=timespan, count=count,
        )
        rows = _extract_bar_list(response)
        return _parse_history_bar_response(rows)

    def fetch_ticker_price(self, symbol: str) -> float:
        response = self._data_client.market_data.get_snapshot([symbol], category=self._Category.US_STOCK)
        rows = _extract_bar_list(response)
        if not rows:
            raise RuntimeError(f"No snapshot returned for {symbol!r} from Webull.")
        row = rows[0]
        for key in ("last_price", "lastPrice", "close", "price"):
            if key in row and row[key] is not None:
                return float(row[key])
        raise RuntimeError(
            f"Could not find a price field in Webull's snapshot response for {symbol!r}. "
            f"Raw row: {row!r}"
        )


def _extract_bar_list(response) -> list[dict]:
    """response is the raw `requests.Response` object the SDK returns
    (see module docstring -- get_response() does not parse JSON itself)."""
    response.raise_for_status()
    body = response.json()
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("data", "bars", "items", "result", "results"):
            value = body.get(key)
            if isinstance(value, list):
                return value
    raise RuntimeError(
        f"Unexpected Webull response shape -- expected a list of bars, or a dict with a "
        f"'data'/'bars'/'items'/'result' list. Got: {body!r}"
    )


def _parse_history_bar_response(rows: list[dict]) -> OHLCV:
    if not rows:
        raise RuntimeError("Webull returned no historical bars -- check the symbol is valid and tradable.")

    def _get(row: dict, field: str):
        for key in _FIELD_CANDIDATES[field]:
            if key in row and row[key] is not None:
                return row[key]
        raise RuntimeError(
            f"Could not find a '{field}' field in a Webull bar -- tried {_FIELD_CANDIDATES[field]}. "
            f"Raw bar: {row!r}\n"
            "See webull_equity.py's module docstring: this response shape wasn't verified against "
            "a live call. Add the real key name to _FIELD_CANDIDATES."
        )

    timestamps, opens, highs, lows, closes, volumes = [], [], [], [], [], []
    for row in rows:
        raw_ts = _get(row, "timestamp")
        timestamps.append(_normalize_timestamp(raw_ts))
        opens.append(float(_get(row, "open")))
        highs.append(float(_get(row, "high")))
        lows.append(float(_get(row, "low")))
        closes.append(float(_get(row, "close")))
        volumes.append(float(_get(row, "volume")))

    # Webull's history endpoint returns most-recent-first in some SDKs -- normalize to
    # chronological ascending (same order cryptocom.py / engine.py expect) if needed.
    if len(timestamps) > 1 and timestamps[0] > timestamps[-1]:
        timestamps, opens, highs, lows, closes, volumes = (
            list(reversed(timestamps)), list(reversed(opens)), list(reversed(highs)),
            list(reversed(lows)), list(reversed(closes)), list(reversed(volumes)),
        )

    return OHLCV(timestamps=timestamps, opens=opens, highs=highs, lows=lows, closes=closes, volumes=volumes)


def _normalize_timestamp(raw) -> int:
    """Accepts a unix timestamp (seconds or milliseconds, int/float/numeric
    string) or an ISO8601 string, returns unix seconds."""
    if isinstance(raw, str):
        try:
            return int(float(raw))
        except ValueError:
            return int(datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp())
    raw = float(raw)
    return int(raw / 1000) if raw > 10_000_000_000 else int(raw)  # ms vs s heuristic
