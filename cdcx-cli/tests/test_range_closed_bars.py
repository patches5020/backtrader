"""
The range check (cdcx-ai --execute range mode and its read-only preview, cdcx-equity's
preview) reads CLOSED candles only: `cli._closed_bars` drops a still-forming last bar.
"""
import time

from cdcx import cli
from cdcx.exchange.cryptocom import OHLCV


def _bars(last_open_s: float, n: int = 5, step: int = 1800, market: str = "24x7") -> OHLCV:
    ts = [int((last_open_s - (n - 1 - i) * step) * 1000) for i in range(n)]   # ms, like Crypto.com
    return OHLCV(ts, [1.0 + i for i in range(n)], [2.0 + i for i in range(n)], [0.5 + i for i in range(n)],
                 [1.5 + i for i in range(n)], [10.0 + i for i in range(n)], market)


def test_forming_last_bar_is_dropped():
    data = _bars(time.time() - 60)                       # last 30m bar opened a minute ago
    out = cli._closed_bars(data, "30m")
    assert len(out.closes) == 4
    for field in ("timestamps", "opens", "highs", "lows", "closes", "volumes"):
        assert getattr(out, field) == getattr(data, field)[:-1]
    assert out.market == data.market


def test_closed_last_bar_is_kept():
    data = _bars(time.time() - 1800 - 60)                # last 30m bar closed a minute ago
    assert cli._closed_bars(data, "30m") is data


def test_range_setup_inputs_use_closed_bars(monkeypatch):
    data = _bars(time.time() - 60)
    seen = []

    class FakeExchange:
        def __init__(self, *a, **k):
            pass

        def fetch_ohlcv(self, symbol, timeframe, limit):
            return data

    monkeypatch.setattr("cdcx.exchange.cryptocom.CryptoComExchange", FakeExchange)
    monkeypatch.setattr(cli, "_range_inputs_from_data", lambda d: seen.append(d) or "inputs")
    assert cli._range_setup_inputs("XRP/USD", "30m", 5) == "inputs"
    assert seen[0].closes == data.closes[:-1]           # what --execute and the preview evaluate
