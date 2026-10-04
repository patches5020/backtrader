"""
Timeframes below 1h: 1m/5m/15m/30m are native Crypto.com candles; 10m and 45m
are built from the largest native size that divides them (5m x2, 15m x3),
grouped on epoch/UTC-midnight boundaries like TradingView. Lower timeframes are
analysed and reported, but never count toward confluence (protected 1h/4h/1d/1w).
"""
import pytest

from cdcx import confluence
from cdcx.exchange import cryptocom
from cdcx.exchange.cryptocom import CryptoComExchange, _resample

M = 60_000
NATIVE = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "6h": 21600, "12h": 43200,
          "1d": 86400, "1w": 604800, "2w": 1209600, "1M": 2592000}


class FakeCcxt:
    timeframes = {k: k for k in NATIVE}

    def __init__(self):
        self.calls = []

    def parse_timeframe(self, tf):
        if tf in NATIVE:
            return NATIVE[tf]
        return int(tf[:-1]) * {"m": 60, "h": 3600, "d": 86400}[tf[-1]]

    def fetch_ohlcv(self, symbol, timeframe, limit, since=None):
        self.calls.append((timeframe, limit))
        step = NATIVE[timeframe] * 1000
        end = 1_790_000_000_000 // step * step          # aligned "now"
        return [[end - (limit - 1 - i) * step, 1.0 + i, 2.0 + i, 0.5 + i, 1.5 + i, 10.0] for i in range(limit)]


@pytest.fixture
def ex(monkeypatch):
    e = CryptoComExchange.__new__(CryptoComExchange)
    e._exchange = FakeCcxt()
    monkeypatch.setattr(e, "_resolve_market_symbol", lambda s: s)
    return e


def test_native_timeframes_are_fetched_as_is(ex):
    for tf in ("1m", "5m", "15m", "30m", "1h"):
        assert ex._synthetic_base(tf) is None
        assert len(ex.fetch_ohlcv("XRP/USD", tf, 50).closes) == 50
    assert [c[0] for c in ex._exchange.calls] == ["1m", "5m", "15m", "30m", "1h"]


@pytest.mark.parametrize("tf,base", [("10m", ("5m", 2)), ("45m", ("15m", 3)), ("20m", ("5m", 4)), ("90m", ("30m", 3)),
                                     ("2h", ("1h", 2))])
def test_synthetic_timeframes_use_the_largest_dividing_native_size(ex, tf, base):
    assert ex._synthetic_base(tf) == base


def test_any_minute_size_builds_but_day_week_sizes_are_refused(ex):
    assert ex._synthetic_base("7m") == ("1m", 7)
    for tf in ("3d", "3w"):
        with pytest.raises(ValueError, match="not a Crypto.com candle size"):
            ex._synthetic_base(tf)


def test_45m_fetch_returns_the_requested_count_of_aligned_bars(ex):
    d = ex.fetch_ohlcv("XRP/USD", "45m", 40)
    assert ex._exchange.calls[-1][0] == "15m"
    assert len(d.closes) == 40
    assert all(t % (45 * M) == 0 for t in d.timestamps)                    # epoch / UTC-midnight aligned
    assert all(b - a == 45 * M for a, b in zip(d.timestamps, d.timestamps[1:]))


def test_resample_ohlcv_rules_and_partial_groups():
    rows = [[t * 5 * M, 1.0 + t, 2.0 + t, 0.1 * t, 1.5 + t, 10.0] for t in range(1, 12)]  # 00:05 .. 00:55
    out = _resample(rows, 2)
    assert [r[0] // M for r in out] == [10, 20, 30, 40, 50]                  # 00:00 group (one bar) dropped
    first = out[0]                                                         # 00:10 + 00:15
    assert first[1:] == [3.0, 5.0, pytest.approx(0.2), 4.5, 20.0]          # open first, high max, low min, close last, vol sum
    forming = _resample(rows[:-1], 2)[-1]                                    # newest group partial -> kept (forming bar)
    assert forming[0] // M == 50 and forming[5] == 10.0


def test_lower_timeframes_never_count_toward_confluence():
    assert confluence.ALLOWED_TIMEFRAMES == ["1h", "4h", "1d", "1w"]          # protected
    result = confluence.evaluate_confluence({"1m": "STRONG BUY", "5m": "STRONG BUY", "15m": "BUY", "45m": "BUY",
                                             "1h": "BUY"})
    assert not result.should_execute                                        # only 1h counts -> 1 tf, not 2
    assert sorted(result.ignored_timeframes) == ["15m", "1m", "45m", "5m"]


def test_module_exposes_resample_for_the_exchange_only():
    assert cryptocom._resample is _resample
