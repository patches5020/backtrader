from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from cdcx.exchange.cryptocom import OHLCV
from cdcx.volume_profile import prev_day

DAY = 86400
D0 = 1_792_022_400            # 2026-10-14 00:00 UTC
ET = ZoneInfo("America/New_York")


def _series(start, n, step, price=1.0, vol=100.0, market="24x7", ms=True):
    ts = [start + i * step for i in range(n)]
    highs = [price + 0.01 * (i % 7) + 0.02 for i in range(n)]
    lows = [price + 0.01 * (i % 7) - 0.02 for i in range(n)]
    closes = [price + 0.01 * (i % 7) for i in range(n)]
    return OHLCV([t * 1000 if ms else t for t in ts], list(closes), highs, lows, closes, [vol] * n, market=market)


def test_crypto_session_is_previous_utc_day():
    assert prev_day.crypto_session(D0 + DAY + 5 * 3600) == (D0, D0 + DAY)
    assert prev_day.crypto_session(D0 + DAY) == (D0, D0 + DAY)          # exactly midnight: that day just closed


def test_crypto_ok_and_vwap_anchored_at_session_open():
    data = _series(D0, 30, 3600)                       # Oct 14 00:00 .. Oct 15 05:00 (open times)
    now = D0 + DAY + 6 * 3600 + 60                     # Oct 15 06:01 -> bar 05:00 closed, none forming
    r = prev_day.prev_day_levels(data, "1h", now=now)
    assert r.status == "OK", r.reasons
    assert (r.session_start, r.session_end, r.session_bars) == (D0, D0 + DAY, 24)
    assert r.val <= r.poc <= r.vah
    assert r.avwap.anchor_ts == D0 and r.avwap.bars_used == 30


def test_profile_is_frozen_while_vwap_moves():
    now = D0 + DAY + 6 * 3600 + 60
    a = prev_day.prev_day_levels(_series(D0, 30, 3600), "1h", now=now)
    b_data = _series(D0, 30, 3600)
    for i in range(24, 30):                            # today's bars jump far away
        b_data.highs[i] += 5
        b_data.lows[i] += 5
        b_data.closes[i] += 5
        b_data.opens[i] += 5
    b = prev_day.prev_day_levels(b_data, "1h", now=now)
    assert (a.poc, a.vah, a.val) == (b.poc, b.vah, b.val)
    assert b.avwap.vwap > a.avwap.vwap


def test_forming_bar_is_excluded_from_vwap():
    data = _series(D0, 30, 3600)
    now = D0 + DAY + 5 * 3600 + 60                     # bar 05:00 is still forming
    r = prev_day.prev_day_levels(data, "1h", now=now)
    assert r.status == "OK" and r.avwap.bars_used == 29


def test_unfinished_day_is_never_used():
    data = _series(D0, 20, 3600)                       # Oct 14 00:00..19:00 only
    r = prev_day.prev_day_levels(data, "1h", now=D0 + 20 * 3600 + 60)
    assert r.status == "UNKNOWN"                       # previous completed day is Oct 13, not in the data
    assert r.session_start == D0 - DAY


def test_missing_bar_fails_closed():
    data = _series(D0, 30, 3600)
    for seq in (data.timestamps, data.opens, data.highs, data.lows, data.closes, data.volumes):
        del seq[10]
    r = prev_day.prev_day_levels(data, "1h", now=D0 + DAY + 6 * 3600 + 60)
    assert r.status == "UNKNOWN" and "missing data" in r.reasons[0]


def test_stale_crypto_feed_fails_closed():
    data = _series(D0, 30, 3600)
    r = prev_day.prev_day_levels(data, "1h", now=D0 + DAY + 12 * 3600)
    assert r.status == "UNKNOWN" and "stale" in r.reasons[0]


def test_non_intraday_timeframe_rejected():
    r = prev_day.prev_day_levels(_series(D0, 30, 3600), "1d", now=D0 + 2 * DAY)
    assert r.status == "UNKNOWN"


def _equity_day(y, m, d, step=300):
    open_ = datetime(y, m, d, 9, 30, tzinfo=ET).timestamp()
    return [open_ + i * step for i in range(int(6.5 * 3600 / step))]


def _equity(days):
    ts = [t for day in days for t in _equity_day(*day)]
    n = len(ts)
    closes = [100 + (i % 11) * 0.1 for i in range(n)]
    return OHLCV(ts, closes, [c + 0.2 for c in closes], [c - 0.2 for c in closes], closes, [1000.0] * n,
                 market="us_equity")


@pytest.mark.parametrize("day,open_utc_hour", [((2026, 3, 6), 14), ((2026, 3, 9), 13)])   # EST, then EDT (DST 3/8)
def test_equity_session_is_dst_correct(day, open_utc_hour):
    data = _equity([day])
    end = datetime(*day, 16, 0, tzinfo=ET).timestamp()
    r = prev_day.prev_day_levels(data, "5m", now=end + 3600)
    assert r.status == "OK", r.reasons
    assert datetime.fromtimestamp(r.session_start, timezone.utc).hour == open_utc_hour
    assert r.session_bars == 78


def test_equity_monday_morning_uses_friday_and_monday_evening_uses_monday():
    data = _equity([(2026, 10, 9), (2026, 10, 12)])               # Fri, Mon
    mon_1000 = datetime(2026, 10, 12, 10, 0, tzinfo=ET).timestamp()
    r = prev_day.prev_day_levels(_equity([(2026, 10, 9)]), "5m", now=mon_1000)
    assert datetime.fromtimestamp(r.session_start, ET).date().isoformat() == "2026-10-09"
    r2 = prev_day.prev_day_levels(data, "5m", now=datetime(2026, 10, 12, 17, 0, tzinfo=ET).timestamp())
    assert datetime.fromtimestamp(r2.session_start, ET).date().isoformat() == "2026-10-12"
    assert r2.status == "OK"
