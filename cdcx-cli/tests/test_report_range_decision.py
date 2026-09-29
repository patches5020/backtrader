"""
engine.format_report() must not print the trend-scoring signal as the
DECISION on a ranging timeframe. Seen live on XRP/USD 1H (2026-09-29): a
+13 (bullish-leaning) ranging read printed "DECISION: STRONG SELL / 74%"
while the range-boundary strategy rated it NO TRADE. The fix is display-only:
execution_signal / decision on the TradeSignal must stay unchanged.
"""

from dataclasses import replace

from cdcx.engine import analyze_ohlcv, format_report
from cdcx.exchange.cryptocom import OHLCV
from cdcx.regime import RegimeResult


def _signal(regime: str, **overrides):
    closes = [100 + i * 0.1 for i in range(60)]
    data = OHLCV(timestamps=list(range(60)), opens=closes, highs=[c + 1 for c in closes],
                 lows=[c - 1 for c in closes], closes=closes, volumes=[100.0] * 60)
    base = analyze_ohlcv("XRP/USD", data)
    forced = RegimeResult(regime=regime, trend_score=0, range_score=9, icon="🟡", label="RANGING")
    return replace(base, regime=forced, **overrides)


def test_ranging_report_shows_range_mode_not_strong_sell(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    signal = _signal("ranging", signal="STRONG SELL", execution_signal="STRONG SELL",
                     decision="STRONG SELL", execution_reason="", confidence=74.0)
    report = format_report(signal)
    assert "DECISION: RANGE MODE" in report
    assert "DECISION: STRONG SELL" not in report
    assert "DECISION CONFIDENCE" not in report
    assert "TREND-SCORE SIGNAL: STRONG SELL" in report
    # display-only: the gate-driving fields are untouched
    assert signal.execution_signal == "STRONG SELL"
    assert signal.decision == signal.execution_signal


def test_ranging_report_with_rr_veto_still_shows_no_trade(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    signal = _signal("ranging", execution_signal="NO TRADE", decision="NO TRADE",
                     execution_reason="Risk/Reward 1.50 is below the 2.0:1 minimum.")
    report = format_report(signal)
    assert "DECISION: NO TRADE" in report
    assert "RANGE MODE" not in report


def test_non_ranging_report_keeps_decision_line(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    signal = _signal("trending", signal="BUY", execution_signal="BUY", decision="BUY", execution_reason="")
    report = format_report(signal)
    assert "DECISION: BUY" in report
    assert "DECISION CONFIDENCE:" in report
