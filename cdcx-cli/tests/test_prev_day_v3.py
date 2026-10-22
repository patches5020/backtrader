"""vwap-vp-3 display levels (prev_day_v3.py) -- synthetic data only."""
import pathlib
from types import SimpleNamespace

from cdcx.exchange.cryptocom import OHLCV
from cdcx.indicators.volume_profile_fixed import build_volume_profile, calculate_poc_vah_val
from cdcx.volume_profile import prev_day_v3 as v3
from cdcx.volume_profile import vwap_confluence as vc

ROOT = pathlib.Path(__file__).resolve().parents[1]
DAY = 86400
S = 1_790_000_000 - 1_790_000_000 % DAY


def _minute(n=1440, start=S, drop=None):
    ts = [start + i * 60 for i in range(n) if i != drop]
    c = [1.3 + 0.01 * ((i * 7) % 13) / 13 for i in range(len(ts))]
    return OHLCV([t * 1000 for t in ts], c, [x + 0.002 for x in c], [x - 0.002 for x in c], c,
                 [100.0 + (i % 5) for i in range(len(ts))])


def test_levels_match_the_unchanged_profile_math_on_1m_at_400_rows():
    d = _minute()
    got = v3.levels_v3(d, S, S + DAY)
    want = calculate_poc_vah_val(build_volume_profile(d.highs, d.lows, d.volumes, buckets=400))
    assert got.status == "OK" and (got.poc, got.vah, got.val) == want and got.bars == 1440


def test_missing_1m_bar_fails_closed():
    out = v3.levels_v3(_minute(drop=700), S, S + DAY)
    assert out.status == "UNKNOWN" and "1439/1440 1m" in out.reason


def test_no_data_is_unknown_and_line_says_so():
    out = v3.levels_v3(None, S, S + DAY)
    assert out.status == "UNKNOWN" and "no 1m data" in v3.format_line(out, SimpleNamespace(poc=1, vah=2, val=0))


def test_line_shows_the_difference_from_vwap_vp_1():
    line = v3.format_line(v3.LevelsV2("OK", poc=1.30, vah=1.32, val=1.28), SimpleNamespace(poc=1.31, vah=1.32, val=1.27))
    assert "vwap-vp-3 (1m @ 400 rows" in line and "POC -0.01" in line and "VAL +0.01" in line


def test_section_prints_v3_under_v2_and_leaves_setups_unchanged():
    from test_vp_reentry import _series
    d = _series(days=3, seed=5)
    now = d.timestamps[-1] / 1000 + 3600
    base = vc.build_section("XRP/USD", d, "1h", now=now)
    lv = vc.prev_day_levels(d, "1h", now=now)
    with_v3 = vc.build_section("XRP/USD", d, "1h", now=now, minute_data=_minute(start=int(lv.session_start)))
    assert "vwap-vp-3" in with_v3 and "UNKNOWN" not in with_v3 and "vwap-vp-3" not in base
    assert [x for x in with_v3.splitlines() if "vwap-vp-3" not in x] == base.splitlines()


def test_nothing_that_scores_or_trades_reads_vwap_vp_3():
    for rel in ("cdcx/volume_profile/vwap_watch.py", "cdcx/backtest/vwap_vp_research.py", "cdcx/no_trade_gate.py",
                "cdcx/confluence.py", "cdcx/risk.py", "cdcx/backtest/vwap_vp_rq11.py"):
        assert "prev_day_v3" not in (ROOT / rel).read_text(encoding="utf-8"), rel
    src = (ROOT / "cdcx/volume_profile/vwap_confluence.py").read_text(encoding="utf-8")
    assert "prev_day_v3" not in src.split("def classify(")[1].split("\ndef ")[0]
