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


@dataclass
class LeverageLimits:
    instrument_id: str  # exchange-native id, e.g. "XRPUSD-PERP" (matches
                         # live_execution.derive_instrument_name's format)
    min_leverage: float
    max_leverage: float


class CryptoComExchange:
    # Crypto.com's REST API caps a single OHLCV request at 300 candles --
    # confirmed empirically (a live `limit=1000` call returned exactly 300
    # rows; not documented anywhere we could find, ccxt just relays whatever
    # the exchange sends back). Any `limit` above this is paginated below
    # via repeated `since`-advancing calls rather than silently truncated.
    MAX_CANDLES_PER_CALL = 300

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
        symbol: CCXT unified format, e.g. "BTC/USDT" -- or a stock/RWA
        perpetual base like "AAPL/USDT" (see _resolve_market_symbol: these
        have no spot listing on Crypto.com and get remapped to their swap
        market automatically).
        timeframe: "1m", "5m", "15m", "1h", "4h", "1d", etc.

        `limit` above MAX_CANDLES_PER_CALL (300) is paginated transparently --
        see _fetch_ohlcv_paginated -- so e.g. limit=1000 actually returns up
        to 1000 candles instead of silently capping at whatever the exchange
        allows in one request.
        """
        symbol = self._resolve_market_symbol(symbol)
        if limit <= self.MAX_CANDLES_PER_CALL:
            raw: Sequence[Sequence[float]] = self._exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        else:
            raw = self._fetch_ohlcv_paginated(symbol, timeframe, limit)

        return self._to_ohlcv(raw)

    def _fetch_ohlcv_paginated(
        self, symbol: str, timeframe: str, limit: int,
    ) -> list[Sequence[float]]:
        """
        Walks BACKWARD from "now", one MAX_CANDLES_PER_CALL page at a time,
        each `since` anchored on the oldest timestamp already confirmed to
        exist -- rather than guessing an upfront `since` far in the past
        (e.g. `now - limit * timeframe_ms`), which is what actually broke
        this originally: confirmed live that Crypto.com returns an EMPTY
        list (not the earliest available candles) for a `since` that's
        DECADES before a pair's real history (`since=0`/epoch on XRP/USD 1w
        -> 0 rows), even though a `since` only modestly early -- confirmed
        with 1 and 5 weeks before XRP/USD 1w's real ~2021 start -- correctly
        clamps forward to the earliest candle instead. Asking for 1000
        weekly candles computed a since ~19 years back (XRP/USD only has
        ~5 years of 1w history), landing squarely in "decades early" empty
        territory. Anchoring on "now" and walking backward one page at a
        time keeps every `since` close to data already confirmed to exist,
        which stays well inside the "clamps forward fine" range in practice.

        The halving retry below is defensive insurance for the residual
        edge case where total available history isn't an exact multiple of
        page size: if a page-sized backward jump ever does overshoot past
        where history begins, an empty response alone can't distinguish
        "no more history" from "overshot the boundary, a smaller chunk is
        still sitting there unfetched" -- so it halves the step and retries
        rather than assuming either way and risking dropped candles.
        """
        timeframe_ms = int(self._exchange.parse_timeframe(timeframe) * 1000)

        latest_batch = self._exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=self.MAX_CANDLES_PER_CALL)
        if not latest_batch:
            return []

        all_rows: list[Sequence[float]] = list(latest_batch)
        seen_timestamps = {int(row[0]) for row in all_rows}
        oldest_ts = int(all_rows[0][0])

        page_span_bars = self.MAX_CANDLES_PER_CALL
        while len(all_rows) < limit and page_span_bars >= 1:
            since = oldest_ts - page_span_bars * timeframe_ms
            batch = self._exchange.fetch_ohlcv(
                symbol, timeframe=timeframe, since=since, limit=self.MAX_CANDLES_PER_CALL,
            )
            new_rows = [row for row in batch if int(row[0]) not in seen_timestamps]

            if not new_rows:
                page_span_bars //= 2  # might have overshot the boundary -- try a smaller step
                continue

            seen_timestamps.update(int(row[0]) for row in new_rows)
            all_rows = new_rows + all_rows
            oldest_ts = int(new_rows[0][0])
            page_span_bars = self.MAX_CANDLES_PER_CALL  # back to full speed after a successful hop

        all_rows.sort(key=lambda row: row[0])
        # A page can overshoot past what's strictly needed -- trim to the
        # most recent `limit` candles, since every caller wants the latest
        # window, not the earliest.
        return all_rows[-limit:]

    @staticmethod
    def _to_ohlcv(raw: Sequence[Sequence[float]]) -> OHLCV:
        return OHLCV(
            timestamps=[int(row[0]) for row in raw],
            opens=[row[1] for row in raw],
            highs=[row[2] for row in raw],
            lows=[row[3] for row in raw],
            closes=[row[4] for row in raw],
            volumes=[row[5] for row in raw],
        )

    def fetch_ticker_price(self, symbol: str) -> float:
        symbol = self._resolve_market_symbol(symbol)
        ticker = self._exchange.fetch_ticker(symbol)
        return float(ticker["last"])

    def _resolve_market_symbol(self, symbol: str) -> str:
        """
        Resolve our internal "BASE/QUOTE" symbol to the CCXT market symbol
        Crypto.com actually lists data under.

        Crypto pairs (e.g. "BTC/USDT") have a real spot market and are used
        as-is. Stock/RWA perpetuals (e.g. "AAPL/USDT", "SPY/USD") have NO
        spot listing on Crypto.com -- confirmed live via `get-instruments`,
        their only instrument is the PERPETUAL_SWAP itself -- so a spot
        lookup raises `ccxt.BadSymbol` immediately. Those fall back to the
        swap symbol "{BASE}/USD:USD", same convention as
        fetch_perp_leverage_limits / live_execution.derive_instrument_name.
        """
        markets = self._exchange.load_markets()
        if symbol in markets:
            return symbol
        base = symbol.split("/")[0].upper()
        swap_symbol = f"{base}/USD:USD"
        if swap_symbol in markets:
            return swap_symbol
        return symbol  # not found either way -- let ccxt raise its own BadSymbol

    def fetch_perp_leverage_limits(self, symbol: str) -> LeverageLimits:
        """
        Min/max leverage for the USD-margined perpetual matching `symbol`
        (our internal "BASE/QUOTE" spot-style format, e.g. "XRP/USD" or
        "BTC/USDT" -- the quote currency is ignored, same convention as
        live_execution.derive_instrument_name). Works the same for
        stock/RWA perpetuals (e.g. "AAPL/USDT") since Crypto.com lists them
        under the identical PERPETUAL_SWAP inst_type -- only `product_type`
        in the raw instrument data distinguishes them, which ccxt doesn't
        surface, so no special-casing is needed here.

        Confirmed live: ccxt's unified swap symbol for Crypto.com's
        USD-margined perps is "{BASE}/USD:USD" (e.g. "XRP/USD:USD" ->
        exchange-native id "XRPUSD-PERP"), and each market's `info` carries
        `max_leverage` (Crypto.com doesn't expose a separate raw min beyond
        ccxt's own default of 1.0). Raises `ccxt.BadSymbol` if the base
        currency has no listed perpetual.
        """
        base = symbol.split("/")[0].upper()
        unified_symbol = f"{base}/USD:USD"
        markets = self._exchange.load_markets()
        market = markets[unified_symbol]

        limits = market.get("limits", {}).get("leverage", {})
        return LeverageLimits(
            instrument_id=market["id"],
            min_leverage=float(limits.get("min") or 1.0),
            max_leverage=float(limits.get("max") or market.get("info", {}).get("max_leverage", 1)),
        )


if __name__ == "__main__":
    exchange = CryptoComExchange()
    data = exchange.fetch_ohlcv("BTC/USDT", timeframe="1h", limit=50)
    print(f"Fetched {len(data.closes)} candles")
    print(f"Latest close: {data.closes[-1]}")
