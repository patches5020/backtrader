import pytest

from cdcx.exchange.robinhood_equity import _parse_historicals, _aggregate, _tail


def _row(begins_at, o, h, l, c, v):
    return {
        "begins_at": begins_at, "open_price": o, "high_price": h, "low_price": l,
        "close_price": c, "volume": v, "session": "reg", "interpolated": False,
    }


def test_parse_historicals_maps_the_verified_robin_stocks_keys():
    rows = [
        _row("2026-09-08T13:30:00Z", "150.0", "151.0", "149.5", "150.8", "1000000"),
        _row("2026-09-08T14:30:00Z", "150.8", "152.0", "150.5", "151.9", "900000"),
    ]
    data = _parse_historicals(rows)
    assert data.opens == [150.0, 150.8]
    assert data.highs == [151.0, 152.0]
    assert data.lows == [149.5, 150.5]
    assert data.closes == [150.8, 151.9]
    assert data.volumes == [1000000.0, 900000.0]
    assert data.timestamps[1] > data.timestamps[0]  # chronological


def test_parse_historicals_drops_none_gap_entries():
    rows = [None, _row("2026-09-08T13:30:00Z", "1", "1", "1", "1", "1"), None]
    data = _parse_historicals(rows)
    assert len(data.closes) == 1


def test_parse_historicals_raises_on_all_gaps():
    with pytest.raises(RuntimeError, match="no historical bars"):
        _parse_historicals([None, None])


def test_aggregate_groups_hourly_bars_into_4h_ohlc():
    rows = [
        _row("2026-09-08T13:00:00Z", "100", "105", "99", "102", "10"),
        _row("2026-09-08T14:00:00Z", "102", "106", "101", "103", "20"),
        _row("2026-09-08T15:00:00Z", "103", "104", "98", "99", "30"),
        _row("2026-09-08T16:00:00Z", "99", "101", "97", "100", "40"),
        _row("2026-09-08T17:00:00Z", "100", "108", "100", "107", "50"),  # 5th bar -- dropped (not a full group)
    ]
    data = _aggregate(_parse_historicals(rows), factor=4)
    assert len(data.closes) == 1
    assert data.opens[0] == 100.0     # open of the first bar in the group
    assert data.closes[0] == 100.0    # close of the last (4th) bar in the group
    assert data.highs[0] == 106.0     # max high across the group
    assert data.lows[0] == 97.0       # min low across the group
    assert data.volumes[0] == 100.0   # summed volume


def test_tail_keeps_only_the_last_limit_bars():
    rows = [_row(f"2026-09-0{i}T13:00:00Z", "1", "1", "1", "1", "1") for i in range(1, 6)]
    data = _tail(_parse_historicals(rows), limit=2)
    assert len(data.closes) == 2


def test_tail_is_a_noop_when_limit_exceeds_available_bars():
    rows = [_row("2026-09-08T13:00:00Z", "1", "1", "1", "1", "1")]
    data = _tail(_parse_historicals(rows), limit=200)
    assert len(data.closes) == 1
