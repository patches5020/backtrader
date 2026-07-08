"""Crypto.com Exchange public REST API client.

Only public market-data endpoints are used (no API key, no order
placement): candlesticks, tickers, order book, and instrument listing.

Reference: https://exchange-docs.crypto.com/exchange/v1/rest-ws/index.html
"""
import time
from datetime import datetime, timezone

import requests

BASE_URL = "https://api.crypto.com/exchange/v1/public"

VALID_TIMEFRAMES = (
    "1m", "5m", "15m", "30m",
    "1h", "4h", "6h", "12h",
    "1D", "7D", "14D", "1M",
)


class CryptocomAPIError(RuntimeError):
    """Raised when the Crypto.com Exchange API returns an error response."""


class CryptocomClient:
    """Thin wrapper around the Crypto.com Exchange public REST API."""

    def __init__(self, base_url=BASE_URL, timeout=10, max_retries=3):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()

    def _get(self, path, params=None):
        url = f"{self.base_url}/{path}"
        last_exc = None
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                payload = response.json()
                break
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
        else:
            raise CryptocomAPIError(
                f"Request to {url} failed after {self.max_retries} attempts: {last_exc}"
            ) from last_exc

        code = payload.get("code", 0)
        if code not in (0, "0"):
            raise CryptocomAPIError(
                f"Crypto.com API error (code={code}) for {url}: {payload.get('message', payload)}"
            )
        return payload.get("result", payload)

    def get_instruments(self):
        """Return the list of tradable instruments (list of dicts or names)."""
        result = self._get("get-instruments")
        data = result.get("data", result) if isinstance(result, dict) else result
        return data

    def get_ticker(self, instrument_name):
        """Return the ticker dict for a single instrument."""
        result = self._get("get-tickers", params={"instrument_name": instrument_name})
        data = result.get("data", result) if isinstance(result, dict) else result
        if isinstance(data, list):
            return data[0] if data else {}
        return data

    def get_book(self, instrument_name, depth=10):
        """Return {"bids": [(price, qty), ...], "asks": [(price, qty), ...]}."""
        result = self._get(
            "get-book", params={"instrument_name": instrument_name, "depth": depth}
        )
        data = result.get("data", result) if isinstance(result, dict) else result
        if isinstance(data, list):
            data = data[0] if data else {}

        def _levels(raw_levels):
            levels = []
            for level in raw_levels or []:
                if isinstance(level, dict):
                    levels.append((float(level["price"]), float(level["qty"])))
                else:
                    levels.append((float(level[0]), float(level[1])))
            return levels

        return {
            "bids": _levels(data.get("bids")),
            "asks": _levels(data.get("asks")),
        }

    def get_candlestick(self, instrument_name, timeframe="1h", count=200):
        """Return a list of candle dicts: open, high, low, close, volume, timestamp."""
        if timeframe not in VALID_TIMEFRAMES:
            raise ValueError(
                f"Unsupported timeframe {timeframe!r}; expected one of {VALID_TIMEFRAMES}"
            )
        result = self._get(
            "get-candlestick",
            params={"instrument_name": instrument_name, "timeframe": timeframe, "count": count},
        )
        raw_candles = result.get("data", []) if isinstance(result, dict) else result
        return [_normalize_candle(c) for c in raw_candles]

    def get_candles_dataframe(self, instrument_name, timeframe="1h", count=200):
        """Fetch candles and return a chronologically sorted pandas DataFrame."""
        import pandas as pd

        candles = self.get_candlestick(instrument_name, timeframe=timeframe, count=count)
        df = pd.DataFrame(candles)
        if df.empty:
            return df
        df = df.sort_values("timestamp").reset_index(drop=True)
        df = df.set_index(pd.DatetimeIndex(df["timestamp"], name="datetime"))
        return df[["open", "high", "low", "close", "volume"]]


def _normalize_candle(raw):
    """Normalize a candle dict from either abbreviated or verbose API field names."""
    key_map = {
        "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume", "t": "timestamp",
    }
    candle = dict(raw)
    for short, full in key_map.items():
        if short in candle and full not in candle:
            candle[full] = candle.pop(short)

    for field in ("open", "high", "low", "close", "volume"):
        if field in candle:
            candle[field] = float(candle[field])

    ts = candle.get("timestamp")
    candle["timestamp"] = _normalize_timestamp(ts)
    return candle


def _normalize_timestamp(ts):
    """Accept ISO-8601 strings, seconds, or millisecond epoch timestamps."""
    if isinstance(ts, str):
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if isinstance(ts, (int, float)):
        if ts > 1e12:  # milliseconds
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    return ts
