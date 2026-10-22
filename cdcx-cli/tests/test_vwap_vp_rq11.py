"""RQ11 driver (vwap_vp_rq11.py) -- synthetic data only."""
import random

from cdcx.backtest import vwap_vp_rq11 as rq11
from cdcx.exchange.cryptocom import OHLCV
from cdcx.volume_profile.prev_day_v2 import LevelsV2

DAY = 86400
T0 = 1_790_000_000 - 1_790_000_000 % DAY


def _pair(days=6, seed=5):
    """A 5m series and the 1h series aggregated from it (consistent data)."""
    rng = random.Random(seed)
    n = days * 288
    start = T0 - (days - 1) * DAY
    c, p = [], 1.30
    for _ in range(n):
        p *= 1 + rng.uniform(-0.004, 0.004)
        c.append(p)
    o = [c[0]] + c[:-1]
    h = [max(a, b) * 1.001 for a, b in zip(o, c)]
    l = [min(a, b) * 0.999 for a, b in zip(o, c)]
    v = [rng.uniform(100, 1000) for _ in range(n)]
    m5 = OHLCV([(start + i * 300) * 1000 for i in range(n)], o, h, l, c, v)
    g = range(0, n, 12)
    h1 = OHLCV([(start + i * 300) * 1000 for i in g], [o[i] for i in g], [max(h[i:i + 12]) for i in g],
               [min(l[i:i + 12]) for i in g], [c[i + 11] for i in g], [sum(v[i:i + 12]) for i in g])
    return h1, m5


def test_without_the_level_swap_it_reproduces_vwap_vp_1_signals(monkeypatch):
    h1, m5 = _pair()
    monkeypatch.setattr(rq11, "levels_v2", lambda *a, **k: LevelsV2("OK", poc=0, vah=0, val=0))
    monkeypatch.setattr(rq11, "replace", lambda lv, **kw: lv)            # keep the vwap-vp-1 levels
    v2, skipped = rq11.find_signals_v2(h1, m5)
    v1 = [s for s in rq11.vr.find_signals(h1, "1h") if s[1] in rq11.TRIGGERS]
    assert v1 and v2 == v1 and skipped == 0


def test_real_v2_levels_walk_forward_no_lookahead():
    h1, m5 = _pair(seed=8)
    full, _ = rq11.find_signals_v2(h1, m5)
    cut = len(h1.closes) - 15
    pre, _ = rq11.find_signals_v2(rq11.vr._slice(h1, 0, cut), m5)
    assert [s for s in full if s[0] < cut] == pre


def test_incomplete_5m_session_gives_no_v2_signals_and_is_counted():
    h1, m5 = _pair(seed=8)
    empty = OHLCV([], [], [], [], [], [])
    sigs, skipped = rq11.find_signals_v2(h1, empty)
    assert sigs == [] and skipped > 0


def test_rq11_verdict():
    assert rq11.verdict(10, (0.1, 0.2), 10, (0.1, 0.2))["primary"].startswith("insufficient")
    v = rq11.verdict(40, (0.02, 0.3), 40, (-0.05, 0.2))
    assert v["primary"].startswith("VP-04 on vwap-vp-2") and v["vs_v1"].startswith("no evidence")


def test_rq11_frozen_files_unchanged():
    import hashlib
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[1]
    frozen = re.search(r"prev_day_v2\.py=([0-9a-f]{64}) vwap_vp_rq11\.py=([0-9a-f]{64})",
                       (root.parent / ".ai/SHARED/research_questions.md").read_text(encoding="utf-8"))
    for rel, want in (("cdcx/volume_profile/prev_day_v2.py", frozen.group(1)),
                      ("cdcx/backtest/vwap_vp_rq11.py", frozen.group(2))):
        assert hashlib.sha256((root / rel).read_bytes()).hexdigest() == want, rel
