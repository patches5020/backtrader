"""RQ12 driver (vwap_vp_rq12.py) -- synthetic data only."""
import random

from cdcx.backtest import vwap_vp_rq12 as rq12
from cdcx.exchange.cryptocom import OHLCV
from cdcx.volume_profile.prev_day_v2 import LevelsV2

DAY = 86400
T0 = 1_790_000_000 - 1_790_000_000 % DAY


def _pair(days=5, seed=5):
    """A 1m series and the 1h series aggregated from it (consistent data)."""
    rng = random.Random(seed)
    n = days * 1440
    start = T0 - (days - 1) * DAY
    c, p = [], 1.30
    for _ in range(n):
        p *= 1 + rng.uniform(-0.0018, 0.0018)
        c.append(p)
    o = [c[0]] + c[:-1]
    h = [max(a, b) * 1.0005 for a, b in zip(o, c)]
    l = [min(a, b) * 0.9995 for a, b in zip(o, c)]
    v = [rng.uniform(10, 100) for _ in range(n)]
    m1 = OHLCV([(start + i * 60) * 1000 for i in range(n)], o, h, l, c, v)
    g = range(0, n, 60)
    h1 = OHLCV([(start + i * 60) * 1000 for i in g], [o[i] for i in g], [max(h[i:i + 60]) for i in g],
               [min(l[i:i + 60]) for i in g], [c[i + 59] for i in g], [sum(v[i:i + 60]) for i in g])
    return h1, m1


def test_without_the_level_swap_it_reproduces_vwap_vp_1_signals(monkeypatch):
    h1, m1 = _pair()
    monkeypatch.setattr(rq12, "levels_v3", lambda *a, **k: LevelsV2("OK", poc=0, vah=0, val=0))
    monkeypatch.setattr(rq12, "replace", lambda lv, **kw: lv)            # keep the vwap-vp-1 levels
    v3, skipped = rq12.find_signals_v3(h1, m1)
    v1 = [s for s in rq12.vr.find_signals(h1, "1h") if s[1] in rq12.TRIGGERS]
    assert v1 and v3 == v1 and skipped == 0


def test_real_v3_levels_walk_forward_no_lookahead():
    h1, m1 = _pair(seed=8)
    full, skipped = rq12.find_signals_v3(h1, m1)
    assert skipped == 0
    cut = len(h1.closes) - 15
    pre, _ = rq12.find_signals_v3(rq12.vr._slice(h1, 0, cut), m1)
    assert [s for s in full if s[0] < cut] == pre


def test_incomplete_1m_session_gives_no_v3_signals_and_is_counted():
    h1, _ = _pair(seed=8)
    sigs, skipped = rq12.find_signals_v3(h1, OHLCV([], [], [], [], [], []))
    assert sigs == [] and skipped > 0


def test_rq12_verdict():
    assert rq12.verdict(10, (0.1, 0.2), 10, (0.1, 0.2))["primary"].startswith("insufficient")
    v = rq12.verdict(40, (0.02, 0.3), 40, (-0.05, 0.2))
    assert v["primary"].startswith("VP-04 on vwap-vp-3") and v["vs_v1"].startswith("no evidence")


def test_summary_and_report_run_end_to_end():
    h1, m1 = _pair(seed=8)
    s = rq12.summarize([rq12.run_symbol("XRP/USD", h1, m1, 0, 2**40)])
    assert set(s["pooled"]) == {"VP-04v3", "VP-04v1", "VP-01v3", "VP-01v1"}
    assert "RQ12" in rq12.format_report(s, {"XRP/USD 1h": "0" * 64}, "a", "b")


def test_rq12_frozen_files_unchanged():
    import hashlib
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[1]
    frozen = re.search(r"prev_day_v3\.py=([0-9a-f]{64}) vwap_vp_rq12\.py=([0-9a-f]{64})",
                       (root.parent / ".ai/SHARED/research_questions.md").read_text(encoding="utf-8"))
    for rel, want in (("cdcx/volume_profile/prev_day_v3.py", frozen.group(1)),
                      ("cdcx/backtest/vwap_vp_rq12.py", frozen.group(2))):
        assert hashlib.sha256((root / rel).read_bytes()).hexdigest() == want, rel
