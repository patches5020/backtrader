"""
CDCX-AI TRADE ANALYSIS shows LONG and SHORT entry / stop / breakeven / TP1-TP4 /
R:R alongside the existing levels. Additive and display-only: every existing
line and value is unchanged, both directions come from the engine's own plan
builder (same entry, ATR, 1.5x multiplier, protected 2.2/2.6/3.2/4.5 R ladder
and tp_mode), and nothing that scores, gates or executes reads them.
"""
import pytest

from cdcx import engine
from cdcx.engine import analyze_ohlcv, format_report
from cdcx.exchange.cryptocom import OHLCV


def _data(step):
    closes = [100 + i * step for i in range(60)]
    return OHLCV(timestamps=list(range(60)), opens=closes, highs=[c + 1 for c in closes],
                 lows=[c - 1 for c in closes], closes=closes, volumes=[100.0] * 60)


@pytest.fixture(params=[0.1, -0.1], ids=["uptrend", "downtrend"])
def signal(request):
    return analyze_ohlcv("XRP/USD", _data(request.param))


def test_long_and_short_follow_the_1_5x_atr_and_protected_tp_ladder(signal):
    dist = signal.atr * signal.atr_multiplier
    assert signal.atr_multiplier == 1.5 and signal.tp_ratios == [2.2, 2.6, 3.2, 4.5]
    long, short = signal.directional_levels["long"], signal.directional_levels["short"]
    assert long["entry"] == short["entry"] == signal.entry
    assert long["breakeven"] == short["breakeven"] == signal.entry
    assert long["stop"] == pytest.approx(signal.entry - dist, abs=1e-6)
    assert short["stop"] == pytest.approx(signal.entry + dist, abs=1e-6)
    for i, ratio in enumerate(signal.tp_ratios, start=1):
        assert long["take_profits"][f"TP{i}"] == pytest.approx(signal.entry + dist * ratio, abs=1e-6)
        assert short["take_profits"][f"TP{i}"] == pytest.approx(signal.entry - dist * ratio, abs=1e-6)
    assert long["rr"] == short["rr"] == 2.2


def test_the_side_cdcx_picked_matches_the_existing_levels_exactly(signal):
    side = "long" if signal.stop_loss < signal.entry else "short"
    picked = signal.directional_levels[side]
    assert picked["stop"] == signal.stop_loss
    assert picked["take_profits"] == signal.take_profits
    assert picked["rr"] == signal.risk_reward_ratio


def test_report_keeps_every_existing_line_and_adds_long_short_under_each(signal, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    lines = format_report(signal).splitlines()
    added = [l for l in lines if l.startswith(("  Long:", "  Short:")) or l.startswith("Breakeven:")]
    original = [l for l in lines if l not in added]
    # every existing level line, verbatim and in its original order
    expected = [f"Entry:       {signal.entry:.6f}", f"ATR:         {signal.atr:.6f}",
                f"Stop Loss:   {signal.stop_loss}",
                *[f"{k}: {v}" for k, v in signal.take_profits.items()],
                f"Risk/Reward: 1 : {signal.risk_reward_ratio}"]
    positions = [original.index(e) for e in expected]
    assert positions == sorted(positions)
    # each existing level line is followed by its Long / Short pair
    for head in ("Entry:", "Stop Loss:", "Breakeven:", "TP1:", "TP2:", "TP3:", "TP4:", "Risk/Reward:"):
        i = next(n for n, l in enumerate(lines) if l.startswith(head))
        assert lines[i + 1].startswith("  Long:") and lines[i + 2].startswith("  Short:"), head
    long, short = signal.directional_levels["long"], signal.directional_levels["short"]
    i = lines.index(f"Stop Loss:   {signal.stop_loss}")
    assert lines[i + 1] == f"  Long:      {long['stop']}" and lines[i + 2] == f"  Short:     {short['stop']}"
    i = lines.index(f"TP4: {signal.take_profits['TP4']}")
    assert lines[i + 1] == f"  Long:      {long['take_profits']['TP4']}"
    assert lines[i + 2] == f"  Short:     {short['take_profits']['TP4']}"
    assert sum(1 for l in added if l.startswith("  Long:")) == 8  # entry, stop, BE, TP1-4, R:R


def test_report_without_directional_levels_is_exactly_the_old_layout(signal, monkeypatch):
    from dataclasses import replace
    monkeypatch.setenv("NO_COLOR", "1")
    report = format_report(replace(signal, directional_levels={}))
    assert "  Long:" not in report and "  Short:" not in report and "Breakeven:" not in report


def test_structural_tp_mode_builds_both_sides_with_the_same_mode(monkeypatch):
    sig = analyze_ohlcv("XRP/USD", _data(0.1), tp_mode_override="structural")
    side = "long" if sig.stop_loss < sig.entry else "short"
    assert sig.directional_levels[side]["take_profits"] == sig.take_profits
    long_tps = list(sig.directional_levels["long"]["take_profits"].values())
    short_tps = list(sig.directional_levels["short"]["take_profits"].values())
    assert all(tp > sig.entry for tp in long_tps) and all(tp < sig.entry for tp in short_tps)


def test_directional_levels_are_display_only():
    import pathlib
    src_dir = pathlib.Path(engine.__file__).parent
    readers = sorted(p.name for p in src_dir.rglob("*.py") if "directional_levels" in p.read_text())
    assert readers == ["engine.py"]  # nothing outside the report reads them (no gate, no execution)
