"""RQ10 calculation study (vp_resolution_rq10.py) -- synthetic data only."""
import pytest

from cdcx.backtest import vp_resolution_rq10 as rq10
from cdcx.exchange.cryptocom import OHLCV
from cdcx.indicators.volume_profile_fixed import build_volume_profile, calculate_poc_vah_val

DAY = 86400
T0 = 1_790_000_000 - 1_790_000_000 % DAY


def test_known_profile_answer():
    # three bars stacked at 10-11, one at 12-13: POC in the heavy zone, VA covers it
    h, l, v = [11, 11, 11, 13], [10, 10, 10, 12], [100, 100, 100, 100]
    poc, vah, val = calculate_poc_vah_val(build_volume_profile(h, l, v, buckets=6))
    assert 10 <= poc <= 11 and val <= 10.5 and vah <= 11.5


def test_flat_profile_tie_goes_to_the_lowest_bucket():
    hist = build_volume_profile([20.0], [10.0], [100.0], buckets=10)
    poc, _, _ = calculate_poc_vah_val(hist)
    assert poc == min(hist)                   # documented tie-break of the production code


def test_tv_style_value_area_contains_70_percent_and_the_poc():
    hist = {float(p): w for p, w in enumerate([1, 2, 5, 9, 20, 9, 4, 3, 2, 1])}
    vah, val = rq10.tv_value_area(hist)
    inside = sum(w for p, w in hist.items() if val <= p <= vah)
    assert val <= 4.0 <= vah and inside >= 0.7 * sum(hist.values())


def _series(tf_s, days, seed=1):
    import random
    rng = random.Random(seed)
    n = days * DAY // tf_s
    start = T0 - days * DAY
    c, p = [], 1.3
    for _ in range(n):
        p *= 1 + rng.uniform(-0.004, 0.004)
        c.append(p)
    o = [c[0]] + c[:-1]
    return OHLCV(timestamps=[(start + i * tf_s) * 1000 for i in range(n)], opens=o,
                 highs=[max(a, b) * 1.001 for a, b in zip(o, c)], lows=[min(a, b) * 0.999 for a, b in zip(o, c)],
                 closes=c, volumes=[rng.uniform(100, 1000) for _ in range(n)])


def test_session_bars_fail_closed_on_a_missing_bar():
    d = _series(3600, 3)
    start = T0 - 2 * DAY
    assert len(rq10.session_bars(d, "1h", start, start + DAY)[0]) == 24
    gap = OHLCV(d.timestamps[:30] + d.timestamps[31:], d.opens[:30] + d.opens[31:], d.highs[:30] + d.highs[31:],
                d.lows[:30] + d.lows[31:], d.closes[:30] + d.closes[31:], d.volumes[:30] + d.volumes[31:])
    assert rq10.session_bars(gap, "1h", start, start + DAY) is None


def test_study_runs_every_cell_and_reference_has_zero_error():
    series = {"1h": _series(3600, 6), "15m": _series(900, 6, 2), "5m": _series(300, 6, 3)}
    rows = rq10.study_symbol(series, n_sessions=3)
    cells = {(r["source"], r["rows"]) for r in rows}
    assert cells == {(s, n) for s in rq10.SOURCES for n in rq10.ROWS}
    ref = [r for r in rows if (r["source"], r["rows"]) == rq10.REFERENCE]
    assert ref and all(max(r["err"].values()) == pytest.approx(0) for r in ref)
    summ = rq10.summarize(rows)
    assert summ["5m@400"]["median_err_atr"] == pytest.approx(0)
