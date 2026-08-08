"""
cryptocom.py
------------
Thin CCXT wrapper around the Crypto.com exchange for fetching OHLCV candles.
Public market data (OHLCV) doesn't require API keys; keys are only wired in
for future authenticated features (balances, order placement, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass
class OHLCV:
    timestamps: list[int]
    opens: list[float]
    highs: list[float]
    lows: list[float]
    closes: list[float]
    volumes: list[float]


class CryptoComExchange:
    def __init__(self, api_key: str | None = None, api_secret: str | None = None):
        try:
            import ccxt
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "ccxt is required for live data -- install with `pip install ccxt`"
            ) from exc
        self._exchange = ccxt.cryptocom({
            "apiKey": api_key or "",
            "secret": api_secret or "",
            "enableRateLimit": True,
        })

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 200) -> OHLCV:
        """
        symbol: CCXT unified format, e.g. "BTC/USDT"
        timeframe: "1m", "5m", "15m", "1h", "4h", "1d", etc.
        """
        raw: Sequence[Sequence[float]] = self._exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

        return OHLCV(
            timestamps=[int(row[0]) for row in raw],
            opens=[row[1] for row in raw],
            highs=[row[2] for row in raw],
            lows=[row[3] for row in raw],
            closes=[row[4] for row in raw],
            volumes=[row[5] for row in raw],
        )

    def fetch_ticker_price(self, symbol: str) -> float:
        ticker = self._exchange.fetch_ticker(symbol)
        return float(ticker["last"])


if __name__ == "__main__":
    exchange = CryptoComExchange()
    data = exchange.fetch_ohlcv("BTC/USDT", timeframe="1h", limit=50)
    print(f"Fetched {len(data.closes)} candles")
    print(f"Latest close: {data.closes[-1]}")
