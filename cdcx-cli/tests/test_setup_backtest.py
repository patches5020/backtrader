import json
import math

import pytest

from cdcx.backtest import setup_backtest as sb
from cdcx.exchange.cryptocom import OHLCV


def _trade(net_r, status="stopped", entry_time=0, cost=0.1):
    return sb.Trade("x", "1h", 0, 0, entry_time, 1.0, 0.9, status, 0, net_r + cost, cost, net_r, 1)


def test_metrics_math():
    rs = [1.0, -1.0, -1.0, 2.0, -1.0]
    m = sb.metrics([_trade(r) for r in rs] + [_trade(0.0, status="open")])
    assert m["trades"] == 5 and m["open"] == 1
    assert m["win_rate"] == 0.4
    assert m["expectancy_r"] == 0.0
    assert m["profit_factor"] == 1.0
    assert m["max_drawdown_r"] == 2.0          # +1 -> -1 peak-to-trough
    assert m["max_losing_streak"] == 2
    assert m["gross_expectancy_r"] == pytest.approx(0.1)
    assert m["avg_cost_r"] == 0.1


def test_metrics_empty():
    assert sb.metrics([])["trades"] == 0


def test_cost_in_r():
    # 25 bps round trip on a 1.0 entry with a 0.02 stop distance = 0.125 R
    assert sb.cost_in_r(1.0, 0.98, 0.075, 0.05) == pytest.approx(0.125)


def _synthetic(n=400, seed=3):
    import random
    rnd = random.Random(seed)
    price, closes = 100.0, []
    for _ in range(n):
        price *= math.exp(rnd.gauss(0, 0.01))
        closes.append(price)
    highs = [c * 1.004 for c in closes]
    lows = [c * 0.996 for c in closes]
    return OHLCV(timestamps=[i * 3_600_000 for i in range(n)], opens=closes, highs=highs, lows=lows,
                 closes=closes, volumes=[rnd.uniform(500, 1500) for _ in range(n)])


def test_split_bounds_are_chronological_and_cover_everything():
    data = _synthetic()
    b = sb.split_bounds(data)
    assert list(b) == ["development", "validation", "out_of_sample"]
    assert b["development"][0] == data.timestamps[sb.WARMUP]
    assert b["development"][1] <= b["validation"][0] and b["validation"][1] <= b["out_of_sample"][0]
    assert b["out_of_sample"][1] == data.timestamps[-1] + 1


@pytest.mark.parametrize("detector", [
    lambda d, e: sb.detect_avp(d, e, "1h", "XRP/USD", "confirm"),
    lambda d, e: sb.detect_vp_setup(d, e, "poc_bounce"),
    lambda d, e: sb.detect_vp_setup(d, e, "value_area_reversal"),
    lambda d, e: sb.detect_vpbos_bull(d, e, "1h"),
])
def test_no_lookahead(detector):
    data = _synthetic(seed=6)  # seed 6: every detector fires in bars 250-300, so this isn't vacuous
    e = 300
    before = [detector(data, i) for i in range(250, e + 1)]
    assert any(before), "detector never fired in the window -- the test would prove nothing"
    future = OHLCV(timestamps=data.timestamps, opens=data.opens,
                   highs=data.highs[:e + 1] + [h * 3 for h in data.highs[e + 1:]],
                   lows=data.lows[:e + 1] + [l * 0.3 for l in data.lows[e + 1:]],
                   closes=data.closes[:e + 1] + [c * 2 for c in data.closes[e + 1:]],
                   volumes=data.volumes[:e + 1] + [v * 9 for v in data.volumes[e + 1:]])
    assert [detector(future, i) for i in range(250, e + 1)] == before


def test_one_open_trade_at_a_time_and_first_appearance_only():
    data = _synthetic(n=600)
    trades = sb.run_strategy(data, "1h", "XRP/USD", "baseline")
    for a, b in zip(trades, trades[1:]):
        assert b.signal_index > a.exit_index  # never overlapping
    assert all(t.signal_index % sb.BASELINE_EVERY == 0 for t in trades)


def test_every_trade_uses_the_protected_risk_model():
    data = _synthetic(n=600)
    for t in sb.run_strategy(data, "1h", "XRP/USD", "baseline"):
        atr = (t.entry - t.stop) / 1.5
        assert t.stop == pytest.approx(t.entry - 1.5 * atr)
        assert t.net_r == pytest.approx(t.gross_r - t.cost_r, abs=1e-3)


def test_out_of_sample_is_locked_by_default(tmp_path, monkeypatch):
    data = _synthetic(n=400)
    path = tmp_path / "XRPUSD_1h_400.json"
    from dataclasses import asdict
    path.write_text(json.dumps(asdict(data)))
    monkeypatch.setattr(sb, "DATA_DIR", tmp_path)
    monkeypatch.setattr(sb, "STRATEGIES", ("baseline",))
    report = sb.run("XRP/USD", {"1h": 400})
    res = report["timeframes"]["1h"]["results"]["baseline"]
    assert res["by_split"]["out_of_sample"] == {"locked": True}
    oos_start = report["timeframes"]["1h"]["splits"]["out_of_sample"][0]
    assert all(t["entry_time"] < oos_start for t in res["trades"])  # OOS trades not even stored
    assert "LOCKED" in sb.format_report(report)
