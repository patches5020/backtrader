"""
Forming-candle detection must work for both timestamp units in use:
Crypto.com (ccxt) = milliseconds, robinhood_equity / webull_equity = seconds.

Regression: engine.py used `timestamps[-1] / 1000` unconditionally. For the
equity sources that put the last bar's open in 1970, so a still-forming
candle always looked closed and VOL(17) read its partial volume.
"""
import math
import time

import pytest

from cdcx import engine
from cdcx.exchange.cryptocom import OHLCV
from cdcx.no_trade_gate import last_bar_is_forming, timestamp_to_seconds

NOW = 1_790_000_000.0  # a fixed "now" (Sep 2026), unix seconds


def test_timestamp_to_seconds_handles_both_units():
    assert timestamp_to_seconds(1_790_000_000) == 1_790_000_000
    assert timestamp_to_seconds(1_790_000_000_000) == 1_790_000_000


@pytest.mark.parametrize("scale", [1, 1000], ids=["seconds", "milliseconds"])
def test_last_bar_is_forming_either_unit(scale):
    opened_10_min_ago = [(NOW - 7200) * scale, (NOW - 600) * scale]
    opened_2h_ago = [(NOW - 10800) * scale, (NOW - 7200) * scale]
    assert last_bar_is_forming(opened_10_min_ago, "1h", NOW) is True
    assert last_bar_is_forming(opened_2h_ago, "1h", NOW) is False


def test_last_bar_is_forming_unknown_timeframe_or_short_series():
    assert last_bar_is_forming([NOW - 600, NOW - 60], "banana", NOW) is False
    assert last_bar_is_forming([NOW - 60], "1h", NOW) is False


def _equity_like_series(last_volume, last_open_age_s):
    """80 hourly bars with SECONDS timestamps, last bar opened
    `last_open_age_s` ago; every bar trades 1000 except the last."""
    n = 80
    closes = [100 + math.sin(i / 4) + i * 0.05 for i in range(n)]
    last_open = NOW - last_open_age_s
    timestamps = [int(last_open - (n - 1 - i) * 3600) for i in range(n)]
    volumes = [1000.0] * (n - 1) + [last_volume]
    return OHLCV(
        timestamps=timestamps, opens=closes, highs=[c + 0.5 for c in closes],
        lows=[c - 0.5 for c in closes], closes=closes, volumes=volumes,
    )


def test_engine_volume_ratio_skips_forming_equity_bar(monkeypatch):
    # 10 minutes into the hour, only 50 traded so far. The ratio must come
    # from the prior CLOSED bar (1000 vs 1000 avg = 1.0x), not read 0.05x.
    monkeypatch.setattr(engine, "time", type("T", (), {"time": staticmethod(lambda: NOW)}))
    signal = engine.analyze_ohlcv("SPY", _equity_like_series(50.0, 600), timeframe="1h")
    assert signal.volume_ratio == pytest.approx(1.0, abs=0.01)


def test_engine_volume_ratio_uses_closed_equity_bar(monkeypatch):
    # Last bar opened 2h ago -> closed; its 3000 volume counts in full.
    monkeypatch.setattr(engine, "time", type("T", (), {"time": staticmethod(lambda: NOW)}))
    signal = engine.analyze_ohlcv("SPY", _equity_like_series(3000.0, 7200), timeframe="1h")
    assert signal.volume_ratio > 2.0
