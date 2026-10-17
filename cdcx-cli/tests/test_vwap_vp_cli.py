import time

from cdcx import cli, cli_equity
from cdcx.exchange.cryptocom import OHLCV


def _recent_5m(market="24x7"):
    """Bars from the start of yesterday (UTC) up to the last closed 5m bar."""
    now = time.time()
    start = (int(now // 86400) - 1) * 86400
    last_open = int(now // 300) * 300 - 300          # newest bar that has already closed
    ts = list(range(start, last_open + 1, 300))
    closes = [1.0 + 0.01 * ((i // 12) % 5) for i in range(len(ts))]
    return OHLCV([t * 1000 for t in ts], closes, [c + 0.005 for c in closes], [c - 0.005 for c in closes],
                 closes, [100.0] * len(ts), market=market)


def test_flag_parsing():
    p = cli.build_parser()
    assert p.parse_args(["--symbol", "XRP/USD"]).vwap_vp == "1h"                  # on by default
    assert p.parse_args(["--symbol", "XRP/USD", "--vwap-vp"]).vwap_vp == "5m"
    assert p.parse_args(["--symbol", "XRP/USD", "--vwap-vp", "15m"]).vwap_vp == "15m"
    assert p.parse_args(["--symbol", "XRP/USD", "--no-vwap-vp"]).vwap_vp is None
    pe = cli_equity.build_parser()
    assert pe.parse_args(["--source", "robinhood", "--symbol", "SPY"]).vwap_vp == "15m"
    assert pe.parse_args(["--source", "robinhood", "--symbol", "SPY", "--vwap-vp"]).vwap_vp == "5m"
    assert pe.parse_args(["--source", "robinhood", "--symbol", "SPY", "--no-vwap-vp"]).vwap_vp is None


def test_section_prints_and_never_authorizes(monkeypatch, capsys):
    class FakeExchange:
        def __init__(self, *a, **k):
            pass

        def fetch_ohlcv(self, symbol, timeframe="5m", limit=0):
            return _recent_5m()

    monkeypatch.setattr("cdcx.exchange.cryptocom.CryptoComExchange", FakeExchange)
    cli._print_vwap_vp("XRP/USD", "5m", results={})
    out = capsys.readouterr().out
    assert "PREV-DAY AVWAP + AFVP -- XRP/USD 5m" in out
    assert "Execution: NOT AUTHORIZED (analysis only)" in out


def test_data_failure_is_unknown_not_a_crash(monkeypatch, capsys):
    class Broken:
        def __init__(self, *a, **k):
            pass

        def fetch_ohlcv(self, *a, **k):
            raise RuntimeError("exchange down")

    monkeypatch.setattr("cdcx.exchange.cryptocom.CryptoComExchange", Broken)
    cli._print_vwap_vp("XRP/USD", "5m", results={})
    assert "UNKNOWN (data unavailable: exchange down)" in capsys.readouterr().out
    cli._print_vwap_vp("XRP/USD", "1d", results={})
    assert "needs an intraday timeframe" in capsys.readouterr().out


def test_equity_section_uses_the_given_exchange(capsys):
    class FakeEquity:
        def fetch_ohlcv(self, symbol, timeframe="5m", limit=0):
            raise RuntimeError("no session")

    cli_equity._print_vwap_vp(FakeEquity(), "SPY", "5m", results=None)
    assert "SPY 5m: UNKNOWN (data unavailable: no session)" in capsys.readouterr().out
