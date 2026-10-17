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


# --- several timeframes in one --vwap-vp (2026-10-17) ---------------------------------
from cdcx.volume_profile.vwap_confluence import split_timeframes


def test_split_timeframes_keeps_intraday_in_order():
    assert split_timeframes("1w,1d,4h,1h,45m,30m,15m,5m") == (["4h", "1h", "45m", "30m", "15m", "5m"], ["1w", "1d"])
    assert split_timeframes("1h") == (["1h"], [])
    assert split_timeframes(" 15m , 1h,15m,,") == (["15m", "1h"], [])            # spaces, duplicates, blanks
    assert split_timeframes("1d,banana") == ([], ["1d", "banana"])


def test_crypto_prints_one_section_per_intraday_timeframe(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(cli, "_print_vwap_vp_one", lambda s, tf, r: calls.append(tf) or print(f"SECTION {tf}"))
    cli._print_vwap_vp("XRP/USD", "1w,1d,1h,15m", results={})
    out = capsys.readouterr().out
    assert calls == ["1h", "15m"]
    assert "skipped 1w, 1d" in out and out.index("SECTION 1h") < out.index("SECTION 15m")
    cli._print_vwap_vp("XRP/USD", "1w,1d", results={})
    assert "needs an intraday timeframe, got '1w,1d'" in capsys.readouterr().out


def test_equity_prints_one_section_per_timeframe_and_isolates_failures(capsys):
    class Partly:
        def fetch_ohlcv(self, symbol, timeframe="5m", limit=0):
            if timeframe == "15m":
                raise RuntimeError("no 15m data")
            return _recent_5m(market="us_equity")

    cli_equity._print_vwap_vp(Partly(), "SPY", "1d,15m,5m", results=None)
    out = capsys.readouterr().out
    assert "skipped 1d" in out
    assert "SPY 15m: UNKNOWN (data unavailable: no 15m data)" in out
    assert "PREV-DAY AVWAP + AFVP -- SPY 5m" in out                     # one failure doesn't stop the next
