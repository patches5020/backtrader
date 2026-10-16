from cdcx.backtest import vwap_vp_htf_followup as fu
from cdcx.exchange.cryptocom import OHLCV

H = 3600
T0 = 1_750_000_000 // H * H


def _series(n, step=H, start=T0):
    closes = [100 + (i % 9) * 0.3 for i in range(n)]
    return OHLCV([(start + i * step) * 1000 for i in range(n)], closes, [c + 0.2 for c in closes],
                 [c - 0.2 for c in closes], closes, [10.0] * n)


def test_closed_upto_never_includes_a_forming_bar():
    d = _series(300)
    now = T0 + 250 * H + 1800              # bar 250 opened 30 min ago and is still forming
    sub = fu._closed_upto(d, "1h", now, limit=200)
    assert len(sub.closes) == 200
    assert sub.timestamps[-1] // 1000 == T0 + 249 * H


def test_closed_upto_needs_full_history():
    assert fu._closed_upto(_series(150), "1h", T0 + 150 * H, limit=200) is None


def test_htf_unknown_when_a_timeframe_is_short():
    frames = {"1h": _series(300), "4h": _series(300, 4 * H), "1d": _series(50, 86400), "1w": _series(300, 7 * 86400)}
    htf, label = fu.htf_at("XRP/USD", frames, T0 + 299 * H)
    assert htf == "unknown" and label.endswith("history too short")
