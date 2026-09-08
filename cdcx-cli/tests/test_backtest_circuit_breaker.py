"""
Integration coverage: the circuit breaker (cdcx/circuit_breaker.py) actually
blocks new entries inside run_single_tf_backtest once it trips, and can be
disabled via max_consecutive_losses=None / max_drawdown_pct=None.
"""

import pytest

from cdcx.backtest import engine as bt_engine
from cdcx.backtest.synthetic import generate_ohlcv
from cdcx.regime import RegimeResult


def _fake_bullish_signal(**overrides):
    """A TradeSignal that clears the raw signal/score filter, the regime
    gate, and the entry checklist every single bar it's asked about."""
    from cdcx.engine import TradeSignal

    regime = RegimeResult(regime="trending", trend_score=9, range_score=1, label="TRENDING")
    defaults = dict(
        symbol="BTC/USDT", total_score=95.0, signal="STRONG BUY", stars="*****",
        scores={
            "ema_trend": 15, "fib_retracement": 12, "fair_value_gap": 15,
            "fixed_volume_profile": 10, "anchored_volume_profile": 10,
        },
        labels={"bollinger_bands": "Riding Upper Band (Bullish Continuation)"},
        entry=65000.0, atr=850.0, stop_loss=63725.0,
        take_profits={"TP1": 66870.0, "TP2": 67210.0, "TP3": 67720.0, "TP4": 68825.0},
        risk_reward_ratio=2.2, confidence=90.0, regime=regime,
        execution_signal="STRONG BUY", timeframe="1h",
    )
    defaults.update(overrides)
    return TradeSignal(**defaults)


@pytest.fixture
def losing_signal_sequence(monkeypatch):
    """Every trade this drives immediately loses -- entry always the same,
    stop always hit on the very next bar (update_trade sees a lower low
    than the stop on real synthetic data, so trades close fast)."""
    signal = _fake_bullish_signal()
    monkeypatch.setattr(bt_engine, "analyze_ohlcv", lambda symbol, window, **kwargs: signal)
    return signal


def test_circuit_breaker_blocks_further_entries_after_losing_streak(losing_signal_sequence):
    # Sharp, sustained downtrend so every LONG entry immediately stops out.
    data = generate_ohlcv(n_bars=400, start_price=65000.0, seed=3, timeframe="1h")
    for i in range(len(data.closes)):
        data.lows[i] = min(data.lows[i], 63000.0 - i)  # guarantees the stop is hit fast, every time
        data.closes[i] = min(data.closes[i], 63000.0 - i)
        data.highs[i] = max(data.highs[i], data.closes[i] + 1)
        data.opens[i] = data.closes[i]

    result = bt_engine.run_single_tf_backtest(
        data, symbol="BTC/USDT", timeframe="1h",
        require_regime_gate=False, require_checklist=False,
        max_consecutive_losses=3, max_drawdown_pct=None,
    )

    assert result.n_trades_opened >= 3
    # After 3 losses in a row, the breaker should have refused further
    # entries -- opened count must stop growing well short of every signal.
    assert result.n_trades_opened < result.n_signals_seen
    assert "circuit breaker: 3 losses" in result.notes


def test_circuit_breaker_disabled_allows_unrestricted_entries(losing_signal_sequence):
    data = generate_ohlcv(n_bars=400, start_price=65000.0, seed=3, timeframe="1h")
    for i in range(len(data.closes)):
        data.lows[i] = min(data.lows[i], 63000.0 - i)
        data.closes[i] = min(data.closes[i], 63000.0 - i)
        data.highs[i] = max(data.highs[i], data.closes[i] + 1)
        data.opens[i] = data.closes[i]

    result = bt_engine.run_single_tf_backtest(
        data, symbol="BTC/USDT", timeframe="1h",
        require_regime_gate=False, require_checklist=False,
        max_consecutive_losses=None, max_drawdown_pct=None,
    )

    assert "circuit breaker DISABLED" in result.notes
    # every signal that clears the entry gates becomes a trade -- no throttle
    assert result.n_trades_opened == result.n_signals_seen
