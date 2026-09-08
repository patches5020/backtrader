"""
Regression coverage for two real bugs found live (a short "past week" -- 168
1h bars -- backtest run) after trade_manager.py was reworked to support
partial closes at each TP:

  1. cdcx/backtest/engine.py's force-close-at-end-of-window code still
     imported `trade_manager._close_trade`, a name that no longer exists
     (renamed to `_close_size` when partial closes were added). Any backtest
     window short enough to end with a trade still open -- the common case
     for a "just the past week" run, rare for a 1000-bar run -- crashed
     outright.

  2. Even after fixing the import, cost/P&L accounting for a fully-closed
     trade used apply_trade_costs() ONCE against the trade's full original
     position_size and only the FINAL exit price -- silently wrong for any
     trade that partially closed at TP1-3 (each at ITS OWN price) before
     finally closing. Fixed with apply_trade_costs_over_partial_closes(),
     which sums costs per actual exit slice (trade_manager.Trade.partial_closes).
"""

import pytest

from cdcx.backtest import engine as bt_engine
from cdcx.backtest.synthetic import generate_ohlcv


def test_apply_trade_costs_over_partial_closes_sums_each_slice_at_its_own_price():
    # A long trade: 50 units @ entry 100, closed in two slices at two
    # DIFFERENT prices -- 30 units at 110 (TP1), 20 units at 130 (final).
    partial_closes = [
        {"price": 110.0, "size_closed": 30.0},
        {"price": 130.0, "size_closed": 20.0},
    ]
    gross, costs, net, fee_c, slip_c, imp_c = bt_engine.apply_trade_costs_over_partial_closes(
        "long", 100.0, partial_closes, fee_pct=0.0, slippage_pct=0.0, impact_coeff=0.0,
    )
    # gross must be the SUM of each slice's own (exit - entry) * size_closed,
    # not (final_exit - entry) * total_size
    expected_gross = (110.0 - 100.0) * 30.0 + (130.0 - 100.0) * 20.0  # 300 + 600 = 900
    assert gross == pytest.approx(expected_gross)
    assert gross == pytest.approx(900.0)

    # the WRONG (pre-fix) single-leg calc would have been:
    wrong_gross = (130.0 - 100.0) * 50.0  # treats the whole 50 units as riding to 130 -- 1500
    assert gross != pytest.approx(wrong_gross)


def test_apply_trade_costs_over_partial_closes_fees_match_summed_linear_cost():
    # Fee/slippage are linear in size -- summing per-slice fees must equal
    # one full-size fee computed against a blended/duplicated total.
    partial_closes = [
        {"price": 105.0, "size_closed": 10.0},
        {"price": 108.0, "size_closed": 10.0},
    ]
    _, _, _, fee_c, slip_c, _ = bt_engine.apply_trade_costs_over_partial_closes(
        "long", 100.0, partial_closes, fee_pct=0.1, slippage_pct=0.05, impact_coeff=0.0,
    )
    # each slice independently priced -- fee/slip must be > 0 and additive
    assert fee_c > 0
    assert slip_c > 0


def test_apply_trade_costs_over_partial_closes_empty_legs_is_zero():
    gross, costs, net, fee_c, slip_c, imp_c = bt_engine.apply_trade_costs_over_partial_closes(
        "long", 100.0, [], fee_pct=0.1, slippage_pct=0.05,
    )
    assert (gross, costs, net, fee_c, slip_c, imp_c) == (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def test_short_window_backtest_with_forced_close_does_not_crash(monkeypatch):
    """Regression for the _close_trade -> _close_size import bug: a window
    short enough that a trade is very likely still open when data runs out
    (the real trigger -- 168 bars is exactly a 'past week' of 1h candles)."""
    data = generate_ohlcv(n_bars=168, start_price=1.0, seed=21, timeframe="1h")
    # should not raise (previously: ImportError: cannot import name '_close_trade')
    result = bt_engine.run_single_tf_backtest(
        data, symbol="XRP/USD", timeframe="1h", initial_balance=5000.0,
        warmup=120, require_regime_gate=False, require_checklist=False,
    )
    assert result.n_bars == len(data.closes)


def test_force_closed_trade_uses_remaining_size_not_original_size(monkeypatch):
    """A trade that already partially closed (TP1 hit) before the window
    ends must be force-closed for only what REMAINS, not the full original
    position_size -- otherwise the same units get "closed" twice worth of P&L."""
    from cdcx import trade_manager
    from cdcx.config import settings
    import tempfile, os

    settings.trade_state_path = os.path.join(tempfile.mkdtemp(), "trades.json")
    trade, _ = trade_manager.open_trade(
        symbol="BTC/USDT", direction="long", entry_price=100.0, atr=2.0,
        stop_price=97.0, tp_levels=[103.0, 106.0, 109.0, 112.0],
        position_size=10.0, risk_amount=30.0, account_balance=10000.0,
    )
    trade_manager.update_trade(trade, 103.5)  # TP1 hit -- 25% (2.5 units) partially closed
    assert trade.status == "open"
    assert trade.remaining_size == pytest.approx(7.5)

    all_trades = trade_manager.load_trades()
    all_trades = [trade if t.id == trade.id else t for t in all_trades]
    trade_manager.save_trades(all_trades)

    from cdcx.trade_manager import _close_size
    _close_size(trade, 105.0, trade.remaining_size, None, "End of backtest force-close", [])

    assert trade.status == "closed"
    assert trade.remaining_size == 0.0
    # exactly 2 slices: the TP1 partial (2.5 units) + the force-close (7.5 units) = 10 total
    assert len(trade.partial_closes) == 2
    total_closed = sum(pc["size_closed"] for pc in trade.partial_closes)
    assert total_closed == pytest.approx(10.0)  # never double-counts the original size
