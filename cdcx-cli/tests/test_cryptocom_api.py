import pytest

from api.cryptocom import CryptocomClient, CryptocomAPIError, _normalize_candle


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return FakeResponse(self.payload)


def test_normalize_candle_abbreviated_keys():
    raw = {"o": "1.0", "h": "2.0", "l": "0.5", "c": "1.5", "v": "100", "t": 1700000000000}
    candle = _normalize_candle(raw)
    assert candle["open"] == 1.0
    assert candle["high"] == 2.0
    assert candle["low"] == 0.5
    assert candle["close"] == 1.5
    assert candle["volume"] == 100.0
    assert candle["timestamp"].year >= 2023


def test_normalize_candle_verbose_keys():
    raw = {
        "open": "1.0", "high": "2.0", "low": "0.5", "close": "1.5",
        "volume": "100", "timestamp": "2024-01-01T00:00:00Z",
    }
    candle = _normalize_candle(raw)
    assert candle["open"] == 1.0
    assert candle["timestamp"].year == 2024


def test_get_candlestick_parses_result_envelope():
    payload = {
        "id": 1, "method": "public/get-candlestick", "code": 0,
        "result": {
            "instrument_name": "BTC_USDT",
            "interval": "1h",
            "data": [
                {"o": "100", "h": "110", "l": "90", "c": "105", "v": "10", "t": 1700000000000},
                {"o": "105", "h": "115", "l": "95", "c": "108", "v": "12", "t": 1700003600000},
            ],
        },
    }
    client = CryptocomClient()
    client.session = FakeSession(payload)
    candles = client.get_candlestick("BTC_USDT", timeframe="1h", count=2)
    assert len(candles) == 2
    assert candles[0]["close"] == 105.0
    assert candles[1]["open"] == 105.0


def test_get_candles_dataframe_sorted_and_indexed():
    payload = {
        "code": 0,
        "result": {
            "data": [
                {"open": "2", "high": "3", "low": "1", "close": "2.5", "volume": "5",
                 "timestamp": "2024-01-01T01:00:00Z"},
                {"open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "4",
                 "timestamp": "2024-01-01T00:00:00Z"},
            ],
        },
    }
    client = CryptocomClient()
    client.session = FakeSession(payload)
    df = client.get_candles_dataframe("BTC_USDT")
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index[0] < df.index[1]
    assert df["close"].iloc[0] == 1.5


def test_get_ticker_returns_first_element():
    payload = {"code": 0, "result": {"data": [{"instrument_name": "BTC_USDT", "last": "100"}]}}
    client = CryptocomClient()
    client.session = FakeSession(payload)
    ticker = client.get_ticker("BTC_USDT")
    assert ticker["last"] == "100"


def test_get_book_parses_levels():
    payload = {
        "code": 0,
        "result": {"data": [{"bids": [{"price": "10", "qty": "1"}], "asks": [["11", "2"]]}]},
    }
    client = CryptocomClient()
    client.session = FakeSession(payload)
    book = client.get_book("BTC_USDT", depth=5)
    assert book["bids"] == [(10.0, 1.0)]
    assert book["asks"] == [(11.0, 2.0)]


def test_error_code_raises():
    payload = {"code": 10001, "message": "boom"}
    client = CryptocomClient()
    client.session = FakeSession(payload)
    with pytest.raises(CryptocomAPIError):
        client.get_instruments()
