"""
cdcx-equity below 1h: Robinhood serves 5m/10m (15m/30m/45m built from them),
Webull serves 1m/5m/15m/30m (10m/45m built), all session-anchored to the
9:30 ET open like TradingView. cdcx-equity's advisory sections include
requested lower timeframes; the 1h/4h/1d/1w confluence path is unchanged.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from cdcx import cli_equity
from cdcx.exchange import robinhood_equity, webull_equity
from cdcx.exchange.cryptocom import OHLCV
from cdcx.exchange.equity_bars import aggregate_session_minutes

OPEN_UTC = int(datetime(2026, 10, 2, 13, 30, tzinfo=timezone.utc).timestamp())  # Fri 9:30 ET (EDT)


def _session(minutes_per_bar, sessions=2, start=OPEN_UTC):
    ts = []
    for d in range(sessions):
        day0 = start - d * 86400
        ts = [day0 + i * minutes_per_bar * 60 for i in range(390 // minutes_per_bar)] + ts
    n = len(ts)
    return OHLCV(timestamps=ts, opens=[100.0 + i for i in range(n)], highs=[101.0 + i for i in range(n)],
                 lows=[99.0 + i for i in range(n)], closes=[100.5 + i for i in range(n)], volumes=[10.0] * n)


def _hhmm_et(ts):
    return datetime.fromtimestamp(ts - 4 * 3600, tz=timezone.utc).strftime("%H:%M")  # EDT


def test_45m_bars_are_anchored_to_the_session_open_with_a_short_last_bar():
    out = aggregate_session_minutes(_session(5, sessions=1), 45)
    assert [_hhmm_et(t) for t in out.timestamps] == ["09:30", "10:15", "11:00", "11:45", "12:30", "13:15",
                                                    "14:00", "14:45", "15:30"]
    assert out.volumes[0] == 90.0 and out.volumes[-1] == 60.0       # 9 x 5m, then the short 15:30-16:00 bar
    first = out
    assert (first.opens[0], first.highs[0], first.lows[0], first.closes[0]) == (100.0, 109.0, 99.0, 108.5)


def test_groups_never_span_two_sessions_and_ms_timestamps_keep_their_unit():
    data = _session(5, sessions=2)
    out = aggregate_session_minutes(data, 30)
    assert len(out.closes) == 2 * 13                                  # 13 x 30m per 6.5h session
    ms = OHLCV(timestamps=[t * 1000 for t in data.timestamps], opens=data.opens, highs=data.highs,
               lows=data.lows, closes=data.closes, volumes=data.volumes)
    assert aggregate_session_minutes(ms, 30).timestamps == [t * 1000 for t in out.timestamps]


class FakeRh:
    def __init__(self):
        self.calls = []

    def get_stock_historicals(self, symbol, interval, span, bounds):
        self.calls.append((interval, span))
        step = {"5minute": 5, "10minute": 10, "hour": 60, "day": 1440}[interval]
        data = _session(step, sessions=5)
        return [{"begins_at": datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "open_price": o, "high_price": h, "low_price": l, "close_price": c, "volume": v}
                for t, o, h, l, c, v in zip(data.timestamps, data.opens, data.highs, data.lows, data.closes,
                                            data.volumes)]


@pytest.fixture
def rh():
    ex = robinhood_equity.RobinhoodEquityExchange.__new__(robinhood_equity.RobinhoodEquityExchange)
    ex._rh = FakeRh()
    return ex


@pytest.mark.parametrize("tf,interval,minutes", [("5m", "5minute", 5), ("10m", "10minute", 10),
                                                 ("15m", "5minute", 15), ("30m", "10minute", 30),
                                                 ("45m", "5minute", 45)])
def test_robinhood_intraday_timeframes(rh, tf, interval, minutes):
    d = rh.fetch_ohlcv("SPY", tf, 500)
    assert rh._rh.calls[-1] == (interval, "week")
    assert d.market == "us_equity"
    assert _hhmm_et(d.timestamps[-1 - (390 // minutes - 1 if 390 % minutes == 0 else 390 // minutes)]) == "09:30"


def test_robinhood_still_refuses_1m(rh):
    with pytest.raises(ValueError, match="Unsupported timeframe '1m' for Robinhood"):
        rh.fetch_ohlcv("SPY", "1m", 100)


def test_webull_builds_10m_and_45m_from_native_bars(monkeypatch):
    ex = webull_equity.WebullEquityExchange.__new__(webull_equity.WebullEquityExchange)
    asked = []
    native = webull_equity.WebullEquityExchange.fetch_ohlcv

    def fake_fetch(self, symbol, timeframe="1h", limit=200):
        if timeframe in webull_equity._BUILT_INTRADAY:
            return native(self, symbol, timeframe, limit)
        asked.append((timeframe, limit))
        return _session({"5m": 5, "15m": 15}[timeframe], sessions=3)

    monkeypatch.setattr(webull_equity.WebullEquityExchange, "fetch_ohlcv", fake_fetch)
    d10 = ex.fetch_ohlcv("SPY", "10m", 50)
    d45 = ex.fetch_ohlcv("SPY", "45m", 20)
    assert asked == [("5m", 50 * 2 + 2), ("15m", 20 * 3 + 3)]
    assert len(d10.closes) == 50 and len(d45.closes) == 20 and d45.market == "us_equity"
    assert all(b - a in (600, 600 + 86400 - 390 * 60) for a, b in zip(d10.timestamps, d10.timestamps[1:]))
    for tf in ("1m", "5m", "15m", "30m"):
        assert tf in webull_equity._TIMEFRAME_TO_TIMESPAN_NAME


def _sig(regime):
    return SimpleNamespace(regime=SimpleNamespace(regime=regime), entry=770.0)


def test_equity_range_preview_uses_fetched_bars_and_writes_nothing(monkeypatch, capsys):
    from cdcx import cli, journal
    vp = SimpleNamespace(poc=769.4, vah=772.0, val=768.6)
    used = []
    monkeypatch.setattr(cli, "_range_inputs_from_data", lambda data: used.append(data) or (None, [], [], [50, 51], vp, []))
    for name in ("write_signal", "write_rejected", "write_simulated_order"):
        monkeypatch.setattr(journal, name, lambda *a, **k: pytest.fail("preview must not write the journal"))
    results = {"5m": _sig("ranging"), "1h": _sig("trending"), "4h": _sig("ranging")}
    cli_equity._print_range_preview(results, {"5m": "DATA5", "1h": "DATA1H", "4h": "DATA4H"})
    out = capsys.readouterr().out
    assert used == ["DATA5", "DATA4H"]                                 # ranging only, no refetch
    assert out.count("RANGE MODE PREVIEW") == 2 and "cdcx-equity --execute has no range mode" in out


def test_equity_help_lists_lower_timeframes():
    help_text = " ".join(cli_equity.build_parser().format_help().split())
    assert "45m" in help_text and "only 1h/4h/1d/1w count toward confluence" in help_text
