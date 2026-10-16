import pytest

from cdcx.backtest import vwap_vp_research as vr
from cdcx.exchange.cryptocom import OHLCV

H = 3600
D0 = 1_792_022_400


def _ohlcv(closes, spread=0.1, start=D0, step=H):
    opens = [closes[0]] + closes[:-1]
    highs = [max(o, c) + spread for o, c in zip(opens, closes)]
    lows = [min(o, c) - spread for o, c in zip(opens, closes)]
    return OHLCV([(start + i * step) * 1000 for i in range(len(closes))], opens, highs, lows, closes,
                 [100.0] * len(closes))


def _walk():
    prior = [100 + (0.5 if i % 4 == 1 else -0.5 if i % 4 == 3 else 0.0) for i in range(24)]
    today = [100.4, 99.6, 100.6, 101.2, 100.8, 101.6, 102.0, 101.5, 100.2, 99.4, 100.1, 100.9, 101.4, 100.6]
    return _ohlcv(prior + today)


def test_no_lookahead_signals_identical_on_truncated_history():
    full = _walk()
    sig_full = vr.find_signals(full, "1h")
    for k in (30, 33, 36):
        cut = vr._slice(full, 0, k)
        assert vr.find_signals(cut, "1h") == [s for s in sig_full if s[0] < k]


def test_baseline_fires_on_vwap_crosses():
    sigs = vr.find_signals(_walk(), "1h")
    assert any(s[1] == "B0" for s in sigs)
    assert all(s[2] in ("bullish", "bearish") for s in sigs)


def _flat_then(move, n=40):
    base = [100.0 + (0.05 if i % 2 else -0.05) for i in range(30)]
    return _ohlcv(base + [100.0 + move * (k + 1) for k in range(n)], spread=0.05)


def test_replay_long_runs_all_four_targets():
    d = _flat_then(+0.5)
    tr = vr.replay(d, [(29, "B0", "bullish")], "XRP/USD", fee_bps=0, slippage_bps=0)[0]
    assert tr.status == "tp4" and tr.gross_r == pytest.approx(0.25 * (2.2 + 2.6 + 3.2 + 4.5), abs=1e-3)
    assert tr.cost_r == 0 and tr.net_r == tr.gross_r


def test_replay_short_is_the_mirror_image():
    d = _flat_then(-0.5)
    tr = vr.replay(d, [(29, "B0", "bearish")], "XRP/USD", fee_bps=0, slippage_bps=0)[0]
    assert tr.stop > tr.entry
    assert tr.status == "tp4" and tr.gross_r == pytest.approx(3.125, abs=1e-3)


def test_replay_stop_and_costs():
    d = _flat_then(-0.5)
    tr = vr.replay(d, [(29, "B0", "bullish")], "XRP/USD", fee_bps=7.5, slippage_bps=2.0)[0]
    assert tr.status == "stopped" and tr.gross_r <= -1.0
    dist = tr.entry - tr.stop
    assert tr.cost_r == pytest.approx(2 * 9.5 / 10_000 * tr.entry / dist, abs=1e-4)
    assert tr.net_r == pytest.approx(tr.gross_r - tr.cost_r, abs=1e-4)
    assert tr.mae_r >= 1.0


def test_one_open_trade_per_setup():
    d = _flat_then(+0.5)
    trades = vr.replay(d, [(29, "B0", "bullish"), (31, "B0", "bullish"), (31, "VP-04", "bullish")], "XRP/USD")
    assert [t.setup for t in trades] == ["B0", "VP-04"]


def test_stats():
    t = [vr.Trade("B0", "bullish", 0, 0, 1, 0.9, status="stopped", net_r=-1.0, gross_r=-0.9, cost_r=0.1, exit_index=2),
         vr.Trade("B0", "bullish", 3, 1, 1, 0.9, status="tp4", net_r=3.0, gross_r=3.1, cost_r=0.1, exit_index=9),
         vr.Trade("B0", "bullish", 10, 2, 1, 0.9, status="open")]
    s = vr.stats(t)
    assert s.trades == 2 and s.win_rate == 0.5 and s.total_net_r == 2.0
    assert s.profit_factor == 3.0 and s.max_drawdown_r == 1.0 and s.avg_bars_held == 4.0
