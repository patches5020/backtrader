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


# --- equity weekly bars close at Friday's session end -------------------------
from datetime import datetime, timezone  # noqa: E402

from cdcx.no_trade_gate import bar_close_time  # noqa: E402


def _utc(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc).timestamp()


MON_SEP_21 = _utc(2026, 9, 21)  # equity sources stamp weeks Monday 00:00 UTC
PRIOR_WEEK = MON_SEP_21 - 7 * 86400


def test_equity_week_closes_friday_4pm_new_york_daylight_time():
    assert bar_close_time(MON_SEP_21, "1w", market="us_equity") == _utc(2026, 9, 25, 20)  # 16:00 EDT


def test_equity_week_closes_friday_4pm_new_york_standard_time():
    mon_dec_7 = _utc(2026, 12, 7)
    assert bar_close_time(mon_dec_7, "1w", market="us_equity") == _utc(2026, 12, 11, 21)  # 16:00 EST


def test_finished_equity_week_is_closed_on_the_weekend():
    saturday = _utc(2026, 9, 26, 12)
    assert last_bar_is_forming([PRIOR_WEEK, MON_SEP_21], "1w", saturday, market="us_equity") is False
    # ...but still forming at 15:59 ET Friday.
    assert last_bar_is_forming([PRIOR_WEEK, MON_SEP_21], "1w", _utc(2026, 9, 25, 19, 59), market="us_equity") is True


def test_crypto_week_still_runs_the_full_seven_days():
    saturday = _utc(2026, 9, 26, 12)
    assert bar_close_time(MON_SEP_21, "1w") == MON_SEP_21 + 7 * 86400
    assert last_bar_is_forming([PRIOR_WEEK, MON_SEP_21], "1w", saturday) is True


def test_equity_non_weekly_timeframes_unchanged():
    assert bar_close_time(MON_SEP_21, "1d", market="us_equity") == MON_SEP_21 + 86400
    assert bar_close_time(MON_SEP_21, "1h", market="us_equity") == MON_SEP_21 + 3600


def test_engine_uses_finished_equity_week_volume_on_the_weekend(monkeypatch):
    saturday = _utc(2026, 9, 26, 12)
    monkeypatch.setattr(engine, "time", type("T", (), {"time": staticmethod(lambda: saturday)}))
    n = 80
    closes = [100 + math.sin(i / 4) + i * 0.05 for i in range(n)]
    data = OHLCV(
        timestamps=[int(MON_SEP_21 - (n - 1 - i) * 7 * 86400) for i in range(n)],
        opens=closes, highs=[c + 0.5 for c in closes], lows=[c - 0.5 for c in closes], closes=closes,
        volumes=[1000.0] * (n - 1) + [3000.0], market="us_equity",
    )
    assert engine.analyze_ohlcv("SPY", data, timeframe="1w").volume_ratio > 2.0  # the finished week counts
