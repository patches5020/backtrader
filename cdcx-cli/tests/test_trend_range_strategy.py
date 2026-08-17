import numpy as np
import pandas as pd
import pytest
import backtrader as bt

from strategy.trend_range_strategy import TrendRangeStrategy


def make_range_then_trend_ohlcv(n_range=60, n_trend=60, seed=11):
    """A ranging (oscillating, no-drift) segment followed by a strongly
    trending (steady-drift) segment, so both entry branches of
    TrendRangeStrategy get a chance to fire within one backtest."""
    rng = np.random.default_rng(seed)

    t_range = np.linspace(0, 8 * np.pi, n_range)
    range_close = 100 + 3.0 * np.sin(t_range) + rng.normal(0, 0.05, n_range)

    trend_close = range_close[-1] + np.cumsum(np.full(n_trend, 0.8) + rng.normal(0, 0.05, n_trend))

    close = np.concatenate([range_close, trend_close])
    n = len(close)
    high = close + rng.uniform(0.05, 0.3, n)
    low = close - rng.uniform(0.05, 0.3, n)
    open_ = close + rng.normal(0, 0.05, n)
    volume = rng.uniform(10, 100, n)
    index = pd.date_range("2024-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=index
    )


def run_strategy(df, **params):
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(10000.0)
    cerebro.broker.setcommission(commission=0.0)
    cerebro.adddata(bt.feeds.PandasData(dataname=df))
    cerebro.addstrategy(TrendRangeStrategy, **params)
    results = cerebro.run()
    return results[0]


def test_strategy_runs_without_error_and_enters_trades():
    df = make_range_then_trend_ohlcv()
    strat = run_strategy(
        df, ema_period=5, atr_period=5, sr_length=1.5,
        adx_period=5, adx_threshold=20.0, risk_reward=2.0, atr_sl_mult=1.5, risk_pct=1.0,
    )
    assert len(strat.entry_context) >= 1


def test_entries_honor_configured_risk_reward_ratio():
    df = make_range_then_trend_ohlcv()
    risk_reward = 2.0
    strat = run_strategy(
        df, ema_period=5, atr_period=5, sr_length=1.5,
        adx_period=5, adx_threshold=20.0, risk_reward=risk_reward, atr_sl_mult=1.5, risk_pct=1.0,
    )
    assert strat.entry_context, "expected at least one entry to inspect"
    for ctx in strat.entry_context.values():
        assert ctx["stop_loss"] < ctx["entry"] < ctx["take_profit"]
        risk = ctx["entry"] - ctx["stop_loss"]
        reward = ctx["take_profit"] - ctx["entry"]
        assert reward / risk == pytest.approx(risk_reward, rel=1e-6)
        assert ctx["regime"] in ("trend", "range")


def test_position_sizing_respects_risk_pct():
    df = make_range_then_trend_ohlcv()
    risk_pct = 1.0
    starting_cash = 10000.0
    strat = run_strategy(
        df, ema_period=5, atr_period=5, sr_length=1.5,
        adx_period=5, adx_threshold=20.0, risk_reward=2.0, atr_sl_mult=1.5, risk_pct=risk_pct,
    )
    assert strat.entry_context

    max_risk_amount = starting_cash * (risk_pct / 100.0)
    filled = [ctx for ctx in strat.entry_context.values() if "size" in ctx]
    assert filled, "expected at least one entry to actually fill"
    for ctx in filled:
        risk_per_unit = ctx["entry"] - ctx["stop_loss"]
        actual_risk = ctx["size"] * risk_per_unit
        assert 0 < ctx["size"]
        # Equity only grows/shrinks with prior trades, so the very first fill
        # is the tightest check; later ones are sized off compounded equity.
        assert actual_risk <= max_risk_amount * 1.5
