import math

import pytest

from cdcx.indicators.anchored_vwap import anchored_vwap, band_position

T0 = 1_792_022_400  # 2026-10-14 00:00 UTC


def _bars(prices_vols, start=T0, step=3600):
    ts = [start + i * step for i in range(len(prices_vols))]
    p = [x[0] for x in prices_vols]
    v = [x[1] for x in prices_vols]
    return ts, p, p, p, p, v   # o = h = l = c, so every source equals the price


def test_vwap_and_volume_weighted_sigma_by_hand():
    ts, o, h, l, c, v = _bars([(10.0, 1.0), (20.0, 3.0)])
    r = anchored_vwap(ts, o, h, l, c, v, anchor_ts=T0)
    assert r.vwap == pytest.approx(17.5)                              # (10*1 + 20*3) / 4
    assert r.sigma == pytest.approx(math.sqrt((100 + 1200) / 4 - 17.5 ** 2))   # volume-weighted, = 4.330
    for k in (1, 2, 3):
        assert r.bands[k] == pytest.approx((17.5 - k * r.sigma, 17.5 + k * r.sigma))
    assert r.series == pytest.approx([10.0, 17.5])
    assert r.bars_used == 2


def test_bars_before_anchor_are_ignored_and_ms_timestamps_work():
    ts, o, h, l, c, v = _bars([(99.0, 50.0), (10.0, 1.0), (20.0, 3.0)], start=T0 - 3600)
    r = anchored_vwap([t * 1000 for t in ts], o, h, l, c, v, anchor_ts=T0 * 1000)
    assert r.vwap == pytest.approx(17.5)
    assert r.anchor_ts == T0 and r.last_bar_ts == T0 + 3600


@pytest.mark.parametrize("source,expected", [("ohlc4", 2.25), ("hlcc4", 2.75), ("hlc3", 8 / 3), ("close", 3.0)])
def test_sources(source, expected):
    r = anchored_vwap([T0], [1.0], [4.0], [1.0], [3.0], [5.0], anchor_ts=T0, source=source)
    assert r.vwap == pytest.approx(expected)
    assert r.sigma == pytest.approx(0.0, abs=1e-6)


def test_unknown_source_raises():
    with pytest.raises(ValueError):
        anchored_vwap([T0], [1.0], [1.0], [1.0], [1.0], [1.0], anchor_ts=T0, source="vwap")


def test_fails_closed():
    ts, o, h, l, c, v = _bars([(10.0, 1.0)])
    assert anchored_vwap(ts, o, h, l, c, v, anchor_ts=T0 - 3600) is None          # history starts after the anchor
    assert anchored_vwap(ts, o, h, l, c, v, anchor_ts=T0 + 7200) is None          # no bar after the anchor
    assert anchored_vwap(ts, o, h, l, c, [0.0], anchor_ts=T0) is None             # zero volume
    assert anchored_vwap([], [], [], [], [], [], anchor_ts=T0) is None


def test_band_position():
    ts, o, h, l, c, v = _bars([(10.0, 1.0), (20.0, 3.0)])
    r = anchored_vwap(ts, o, h, l, c, v, anchor_ts=T0)
    assert band_position(r.vwap + 1.5 * r.sigma, r) == pytest.approx(1.5)
