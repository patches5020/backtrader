"""vwap-vp-2 display levels (prev_day_v2.py) -- synthetic data only."""
import pathlib

from cdcx.exchange.cryptocom import OHLCV
from cdcx.indicators.volume_profile_fixed import build_volume_profile, calculate_poc_vah_val
from cdcx.volume_profile import prev_day_v2 as v2

ROOT = pathlib.Path(__file__).resolve().parents[1]
DAY = 86400
S = 1_790_000_000 - 1_790_000_000 % DAY


def _fine(n=288, start=S, drop=None):
    ts = [start + i * 300 for i in range(n) if i != drop]
    c = [1.3 + 0.01 * ((i * 7) % 13) / 13 for i in range(len(ts))]
    return OHLCV([t * 1000 for t in ts], c, [x + 0.002 for x in c], [x - 0.002 for x in c], c,
                 [100.0 + (i % 5) for i in range(len(ts))])


def test_levels_match_the_unchanged_profile_math_at_400_rows():
    d = _fine()
    got = v2.levels_v2(d, S, S + DAY)
    want = calculate_poc_vah_val(build_volume_profile(d.highs, d.lows, d.volumes, buckets=400))
    assert got.status == "OK" and (got.poc, got.vah, got.val) == want and got.bars == 288


def test_missing_bar_fails_closed():
    out = v2.levels_v2(_fine(drop=50), S, S + DAY)
    assert out.status == "UNKNOWN" and "287/288" in out.reason


def test_no_data_is_unknown_and_line_says_so():
    from types import SimpleNamespace
    out = v2.levels_v2(None, S, S + DAY)
    assert out.status == "UNKNOWN"
    assert "UNKNOWN" in v2.format_line(out, SimpleNamespace(poc=1, vah=2, val=0))


def test_line_shows_the_difference_from_vwap_vp_1():
    from types import SimpleNamespace
    line = v2.format_line(v2.LevelsV2("OK", poc=1.30, vah=1.32, val=1.28), SimpleNamespace(poc=1.31, vah=1.32, val=1.27))
    assert "vwap-vp-2 (5m @ 400 rows, display only)" in line and "POC -0.01" in line and "VAL +0.01" in line


def test_nothing_that_scores_or_trades_reads_vwap_vp_2():
    for rel in ("cdcx/volume_profile/vwap_watch.py", "cdcx/backtest/vwap_vp_research.py", "cdcx/no_trade_gate.py",
                "cdcx/confluence.py", "cdcx/risk.py"):
        assert "prev_day_v2" not in (ROOT / rel).read_text(encoding="utf-8"), rel
    src = (ROOT / "cdcx/volume_profile/vwap_confluence.py").read_text(encoding="utf-8")
    assert "prev_day_v2" not in src.split("def classify(")[1].split("\ndef ")[0]
