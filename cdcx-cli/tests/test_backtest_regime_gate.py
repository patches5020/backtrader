"""
Regression coverage for the regime gate added to cdcx.backtest.engine.

Before this fix, run_single_tf_backtest / run_confluence_backtest happily
opened trades during a TRANSITIONAL regime read -- exactly the choppy
condition cli.py's live --execute path refuses outright (Step 1: regime is
an absolute gate). These tests prove the backtester now matches that.
"""

import os

import pytest

from cdcx.config import settings
from cdcx.backtest import engine as bt_engine
from cdcx.backtest.synthetic import generate_ohlcv
from cdcx.confluence import ConfluenceResult
from cdcx.regime import RegimeResult


@pytest.fixture(autouse=True)
def isolated_trade_state(tmp_path):
    original = settings.trade_state_path
    settings.trade_state_path = str(tmp_path / "trades_test.json")
    yield
    settings.trade_state_path = original
    # run_single_tf_backtest/run_confluence_backtest restore the original
    # path themselves on the happy path, but be defensive on failure too.


def _fake_transitional_but_otherwise_tradeable_signal(**overrides):
    """A TradeSignal that would clear the raw signal/score filter (STRONG
    BUY, score 95) but whose execution_signal is NO TRADE -- exactly what
    engine.analyze_ohlcv produces when regime.regime == 'transitional'."""
    from cdcx.engine import TradeSignal

    regime = RegimeResult(
        regime="transitional", trend_score=4, range_score=3,
        breakdown=["fake"], icon="🔴", label="NO TRADE (TRANSITION)",
    )
    defaults = dict(
        symbol="BTC/USDT", total_score=95.0, signal="STRONG BUY", stars="*****",
        scores={}, labels={}, entry=65000.0, atr=850.0, stop_loss=63725.0,
        take_profits={"TP1": 66870.0, "TP2": 67210.0, "TP3": 67720.0, "TP4": 68825.0},
        risk_reward_ratio=2.2, confidence=90.0, regime=regime,
        execution_signal="NO TRADE", execution_reason="Market regime is transitional.",
        timeframe="1h",
    )
    defaults.update(overrides)
    return TradeSignal(**defaults)


def test_single_tf_backtest_regime_gate_blocks_transitional_signals(monkeypatch):
    signal = _fake_transitional_but_otherwise_tradeable_signal()
    monkeypatch.setattr(bt_engine, "analyze_ohlcv", lambda symbol, window, **kwargs: signal)

    data = generate_ohlcv(n_bars=300, start_price=62000.0, seed=1, timeframe="1h")
    result = bt_engine.run_single_tf_backtest(
        data, symbol="BTC/USDT", timeframe="1h", require_regime_gate=True,
    )

    assert result.n_signals_seen == 0  # blocked before ever counting as a candidate
    assert result.n_trades_opened == 0
    assert "regime-gated" in result.notes


def test_single_tf_backtest_can_disable_regime_gate_for_comparison(monkeypatch):
    signal = _fake_transitional_but_otherwise_tradeable_signal()
    monkeypatch.setattr(bt_engine, "analyze_ohlcv", lambda symbol, window, **kwargs: signal)

    data = generate_ohlcv(n_bars=300, start_price=62000.0, seed=1, timeframe="1h")
    result = bt_engine.run_single_tf_backtest(
        data, symbol="BTC/USDT", timeframe="1h", require_regime_gate=False,
    )

    # With the gate off, the same "NO TRADE" execution_signal no longer
    # blocks it -- the raw STRONG BUY / score 95 signal is now a candidate.
    assert result.n_signals_seen > 0
    assert "regime gate DISABLED" in result.notes


def test_confluence_backtest_regime_gate_blocks_transitional_signals(monkeypatch):
    always_bullish_confluence = ConfluenceResult(
        direction="long", should_execute=True, tier="strong",
        agreeing_timeframes=["1h", "4h", "1d", "1w"], entry_timeframe="1h",
        confluence_score=100, label="fake bullish confluence",
    )
    monkeypatch.setattr(bt_engine, "evaluate_confluence", lambda signals: always_bullish_confluence)
    monkeypatch.setattr(
        bt_engine.regime_module, "analyze",
        lambda *a, **kw: RegimeResult(regime="transitional", trend_score=4, range_score=3),
    )

    signal = _fake_transitional_but_otherwise_tradeable_signal()
    monkeypatch.setattr(bt_engine, "analyze_ohlcv", lambda symbol, window, **kwargs: signal)

    data = generate_ohlcv(n_bars=400, start_price=62000.0, seed=2, timeframe="1h")
    result = bt_engine.run_confluence_backtest(
        data, symbol="BTC/USDT", require_regime_gate=True,
    )

    assert result.n_trades_opened == 0
    assert "regime-gated" in result.notes
