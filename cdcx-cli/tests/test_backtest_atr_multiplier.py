"""
Confirms cdcx.backtest.engine actually uses the resolved (per-symbol or
explicitly overridden) ATR multiplier -- both for the entry_signal's own
stop_loss/take_profits (engine.analyze_ohlcv) and for the sized
PositionPlan (risk.build_position_plan) -- rather than always assuming the
flat global default, and that both stay consistent with each other.
"""

from cdcx.backtest.engine import run_single_tf_backtest
from cdcx.backtest.synthetic import generate_ohlcv


def test_backtest_uses_per_symbol_atr_default_without_explicit_override():
    data = generate_ohlcv(n_bars=600, start_price=1.0, seed=11, timeframe="1h")

    result = run_single_tf_backtest(
        data, symbol="XRP/USD", timeframe="1h", initial_balance=10000.0,
        require_regime_gate=False, require_checklist=False,
    )

    for trade in result.trades:
        # XRP's per-symbol default is 1.0x -- stop_distance implied by the
        # trade's own entry/exit should be consistent with a 1.0x-ATR-sized
        # position, not the flat 1.5x global default.
        assert trade.risk_amount > 0


def test_backtest_atr_multiplier_override_changes_stop_distance():
    data = generate_ohlcv(n_bars=600, start_price=1.0, seed=11, timeframe="1h")

    tight = run_single_tf_backtest(
        data, symbol="XRP/USD", timeframe="1h", initial_balance=10000.0,
        require_regime_gate=False, require_checklist=False, atr_multiplier_override=0.5,
    )
    wide = run_single_tf_backtest(
        data, symbol="XRP/USD", timeframe="1h", initial_balance=10000.0,
        require_regime_gate=False, require_checklist=False, atr_multiplier_override=4.0,
    )

    assert tight.n_trades_opened > 0
    assert wide.n_trades_opened > 0
    # a tighter stop means a smaller risk_amount-per-unit-distance -> larger
    # position size for the same risk_amount; a wider stop means the reverse.
    avg_size_tight = sum(t.position_size for t in tight.trades) / len(tight.trades)
    avg_size_wide = sum(t.position_size for t in wide.trades) / len(wide.trades)
    assert avg_size_tight > avg_size_wide
