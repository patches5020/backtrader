"""
Tests for the pagination added to CryptoComExchange.fetch_ohlcv -- exercised
against a fake in-memory ccxt-shaped exchange (no network), so these run in
CI without needing real Crypto.com connectivity.
"""

import pytest

from cdcx.exchange.cryptocom import CryptoComExchange

HOUR_MS = 3_600_000


class _FakeCCXTExchange:
    """
    Simulates just enough of ccxt's Exchange interface for pagination: a
    fixed-length history of hourly candles starting at `start_ts`, served
    `per_call_cap` rows at a time.

    Matches two real, confirmed-live Crypto.com behaviors:
      - `since=None` returns the MOST RECENT `limit` candles (not the
        earliest).
      - `since` that predates when history actually starts returns an EMPTY
        list rather than clamping forward to the earliest candle -- this is
        exactly what broke the original forward-walking pagination on a
        real live XRP/USD 1w request.
    """

    def __init__(self, total_bars: int, per_call_cap: int, start_ts: int = 0):
        self.total_bars = total_bars
        self.per_call_cap = per_call_cap
        self.start_ts = start_ts
        self.calls: list[int | None] = []

    def fetch_ohlcv(self, symbol, timeframe=None, since=None, limit=None):
        self.calls.append(since)
        limit = min(limit or self.per_call_cap, self.per_call_cap)

        if since is None:
            idx = max(0, self.total_bars - limit)
        elif since < self.start_ts:
            return []  # before history began -- the real-world footgun
        else:
            idx = -(-(since - self.start_ts) // HOUR_MS)  # ceil div

        rows = []
        while len(rows) < limit and idx < self.total_bars:
            ts = self.start_ts + idx * HOUR_MS
            rows.append([ts, 1.0, 1.0, 1.0, 1.0, 1.0])
            idx += 1
        return rows

    def parse_timeframe(self, timeframe):
        return HOUR_MS // 1000

    def milliseconds(self):
        return self.start_ts + self.total_bars * HOUR_MS

    def load_markets(self):
        # No markets registered -- _resolve_market_symbol falls back to
        # returning the symbol unchanged, exactly as fetch_ohlcv above needs.
        return {}


def _exchange_with_fake(total_bars: int, per_call_cap: int) -> CryptoComExchange:
    exchange = CryptoComExchange()
    exchange._exchange = _FakeCCXTExchange(total_bars, per_call_cap)
    exchange.MAX_CANDLES_PER_CALL = per_call_cap
    return exchange


def test_limit_within_single_call_does_not_paginate():
    exchange = _exchange_with_fake(total_bars=1000, per_call_cap=300)
    data = exchange.fetch_ohlcv("XRP/USD", timeframe="1h", limit=200)

    assert len(data.closes) == 200
    assert len(exchange._exchange.calls) == 1


def test_limit_above_cap_paginates_and_returns_full_count():
    exchange = _exchange_with_fake(total_bars=1000, per_call_cap=300)
    data = exchange.fetch_ohlcv("XRP/USD", timeframe="1h", limit=700)

    assert len(data.timestamps) == 700
    assert len(exchange._exchange.calls) > 1
    # timestamps must be ascending and contiguous (no gaps/dupes across pages)
    diffs = [b - a for a, b in zip(data.timestamps, data.timestamps[1:])]
    assert all(d == HOUR_MS for d in diffs)
    # returns the MOST RECENT 700 candles, i.e. ending at the last available bar
    assert data.timestamps[-1] == exchange._exchange.start_ts + 999 * HOUR_MS


def test_limit_exceeding_available_history_returns_all_available_without_crashing():
    """Regression test for the real bug: XRP/USD 1w has only ~264 candles of
    history; requesting limit=1000 must gracefully return all 264, not crash
    or silently return zero because the initial `since` guess landed before
    history began."""
    exchange = _exchange_with_fake(total_bars=264, per_call_cap=300)
    data = exchange.fetch_ohlcv("XRP/USD", timeframe="1h", limit=1000)

    assert len(data.closes) == 264  # everything that exists, no more, no crash
    assert data.timestamps[-1] == exchange._exchange.start_ts + 263 * HOUR_MS


def test_limit_exceeding_history_when_history_is_smaller_than_one_page():
    """Same regression, but with history smaller than a single page (so the
    very first call already returns everything there is)."""
    exchange = _exchange_with_fake(total_bars=50, per_call_cap=300)
    data = exchange.fetch_ohlcv("XRP/USD", timeframe="1h", limit=1000)

    assert len(data.closes) == 50


def test_paginated_rows_are_deduplicated():
    exchange = _exchange_with_fake(total_bars=1000, per_call_cap=300)
    data = exchange.fetch_ohlcv("XRP/USD", timeframe="1h", limit=1000)

    assert len(data.timestamps) == len(set(data.timestamps))
    assert len(data.timestamps) == 1000


def test_non_page_aligned_history_does_not_drop_the_trailing_partial_chunk():
    """Regression test: total history (1000 bars) isn't an exact multiple of
    per_call_cap (300) relative to how far back pagination needs to walk --
    a naive fixed-page backward jump can overshoot past bar 0 into "since
    predates history" territory and silently lose the last 100 bars. The
    halving backoff must recover them instead."""
    exchange = _exchange_with_fake(total_bars=1000, per_call_cap=300)
    data = exchange.fetch_ohlcv("XRP/USD", timeframe="1h", limit=1000)

    assert len(data.timestamps) == 1000
    assert data.timestamps[0] == 0  # bar 0 must be present, not dropped


@pytest.mark.parametrize("limit", [50, 300])
def test_limit_at_or_below_cap_boundary(limit):
    exchange = _exchange_with_fake(total_bars=1000, per_call_cap=300)
    data = exchange.fetch_ohlcv("XRP/USD", timeframe="1h", limit=limit)
    assert len(data.closes) == limit
    assert len(exchange._exchange.calls) == 1


class _FakeLeverageMarketsExchange:
    """Simulates just enough of ccxt's load_markets()-backed interface for
    fetch_perp_leverage_limits."""

    def __init__(self, markets: dict):
        self._markets = markets

    def load_markets(self):
        return self._markets


def test_fetch_perp_leverage_limits_reads_min_max_from_market():
    exchange = CryptoComExchange()
    exchange._exchange = _FakeLeverageMarketsExchange({
        "XRP/USD:USD": {
            "id": "XRPUSD-PERP",
            "limits": {"leverage": {"min": 1.0, "max": 50.0}},
            "info": {"max_leverage": "50"},
        },
    })

    limits = exchange.fetch_perp_leverage_limits("XRP/USD")

    assert limits.instrument_id == "XRPUSD-PERP"
    assert limits.min_leverage == 1.0
    assert limits.max_leverage == 50.0


def test_fetch_perp_leverage_limits_ignores_quote_currency():
    """XRP/USDT should resolve to the same USD-margined perp as XRP/USD --
    only the base currency matters, matching live_execution.derive_instrument_name."""
    exchange = CryptoComExchange()
    exchange._exchange = _FakeLeverageMarketsExchange({
        "XRP/USD:USD": {
            "id": "XRPUSD-PERP",
            "limits": {"leverage": {"min": 1.0, "max": 50.0}},
            "info": {},
        },
    })

    limits = exchange.fetch_perp_leverage_limits("XRP/USDT")
    assert limits.instrument_id == "XRPUSD-PERP"


def test_fetch_perp_leverage_limits_falls_back_to_raw_info_max_leverage():
    """If ccxt's own limits.leverage.max isn't populated, fall back to the
    exchange-native `max_leverage` field in `info`."""
    exchange = CryptoComExchange()
    exchange._exchange = _FakeLeverageMarketsExchange({
        "BTC/USD:USD": {
            "id": "BTCUSD-PERP",
            "limits": {"leverage": {}},
            "info": {"max_leverage": "100"},
        },
    })

    limits = exchange.fetch_perp_leverage_limits("BTC/USDT")
    assert limits.max_leverage == 100.0
    assert limits.min_leverage == 1.0  # default when not provided


def test_fetch_perp_leverage_limits_raises_for_unlisted_base():
    exchange = CryptoComExchange()
    exchange._exchange = _FakeLeverageMarketsExchange({})

    with pytest.raises(KeyError):
        exchange.fetch_perp_leverage_limits("NOTREAL/USD")


class _FakeMarketDataExchange:
    """Simulates load_markets() + fetch_ohlcv()/fetch_ticker() for exercising
    _resolve_market_symbol without network access."""

    def __init__(self, markets: dict):
        self._markets = markets
        self.ohlcv_calls: list[str] = []
        self.ticker_calls: list[str] = []

    def load_markets(self):
        return self._markets

    def fetch_ohlcv(self, symbol, timeframe=None, since=None, limit=None):
        self.ohlcv_calls.append(symbol)
        return [[0, 1.0, 1.0, 1.0, 1.0, 1.0]]

    def fetch_ticker(self, symbol):
        self.ticker_calls.append(symbol)
        return {"last": 42.0}


def test_fetch_ohlcv_uses_spot_symbol_when_it_exists():
    """A real crypto pair (spot market present) is passed to ccxt unchanged."""
    fake = _FakeMarketDataExchange({"BTC/USDT": {}})
    exchange = CryptoComExchange()
    exchange._exchange = fake

    exchange.fetch_ohlcv("BTC/USDT", timeframe="1h", limit=1)

    assert fake.ohlcv_calls == ["BTC/USDT"]


def test_fetch_ohlcv_falls_back_to_swap_symbol_for_stock_perpetuals():
    """Stock/RWA perpetuals (e.g. AAPL) have no spot market on Crypto.com --
    confirmed live -- only the "{BASE}/USD:USD" swap market. fetch_ohlcv must
    remap to it instead of passing the spot-style symbol straight to ccxt,
    which would otherwise raise BadSymbol."""
    fake = _FakeMarketDataExchange({"AAPL/USD:USD": {}})
    exchange = CryptoComExchange()
    exchange._exchange = fake

    exchange.fetch_ohlcv("AAPL/USDT", timeframe="1h", limit=1)

    assert fake.ohlcv_calls == ["AAPL/USD:USD"]


def test_fetch_ticker_price_falls_back_to_swap_symbol_for_stock_perpetuals():
    fake = _FakeMarketDataExchange({"SPY/USD:USD": {}})
    exchange = CryptoComExchange()
    exchange._exchange = fake

    price = exchange.fetch_ticker_price("SPY/USD")

    assert price == 42.0
    assert fake.ticker_calls == ["SPY/USD:USD"]


def test_resolve_market_symbol_passes_through_when_neither_form_is_listed():
    """Neither the spot nor the swap symbol exists -- leave the symbol
    unchanged so ccxt raises its own (informative) BadSymbol."""
    fake = _FakeMarketDataExchange({})
    exchange = CryptoComExchange()
    exchange._exchange = fake

    assert exchange._resolve_market_symbol("NOTREAL/USDT") == "NOTREAL/USDT"
