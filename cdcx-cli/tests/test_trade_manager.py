import os
import pytest

from cdcx.config import settings
from cdcx import trade_manager


@pytest.fixture(autouse=True)
def isolated_trade_state(tmp_path):
    """Point trade_manager at a throwaway file for every test so tests never
    touch a real cdcx_trades.json."""
    original = settings.trade_state_path
    settings.trade_state_path = str(tmp_path / "trades_test.json")
    yield
    settings.trade_state_path = original


def _open_sample_long():
    trade, message = trade_manager.open_trade(
        symbol="BTC/USDT", direction="long", entry_price=65000.0, atr=850.0,
        stop_price=63725.0, tp_levels=[66000, 67000, 68500, 71000],
        position_size=0.157, risk_amount=200.0, account_balance=10000.0,
    )
    return trade, message


def test_open_trade_creates_and_persists():
    trade, message = _open_sample_long()
    assert trade is not None
    assert trade.status == "open"
    reloaded = trade_manager.load_trades()
    assert len(reloaded) == 1
    assert reloaded[0].symbol == "BTC/USDT"


def test_duplicate_symbol_is_refused():
    _open_sample_long()
    trade2, message2 = trade_manager.open_trade(
        symbol="BTC/USDT", direction="long", entry_price=65100.0, atr=850.0,
        stop_price=63825.0, tp_levels=[66100, 67100, 68600, 71100],
        position_size=0.157, risk_amount=200.0, account_balance=10000.0,
    )
    assert trade2 is None
    assert "Refused" in message2


def test_tp1_moves_stop_to_breakeven():
    trade, _ = _open_sample_long()
    events = trade_manager.update_trade(trade, 66100)
    assert trade.current_stop == trade.entry_price
    assert trade.tp_index_reached == 0
    assert any("breakeven" in e for e in events)


def test_tp2_trails_stop_to_tp1():
    trade, _ = _open_sample_long()
    trade_manager.update_trade(trade, 66100)   # TP1
    trade_manager.update_trade(trade, 67200)   # TP2
    assert trade.current_stop == trade.tp_levels[0]
    assert trade.tp_index_reached == 1


def test_final_tp_closes_trade():
    trade, _ = _open_sample_long()
    for price in [66100, 67200, 68600, 71200]:
        trade_manager.update_trade(trade, price)
    assert trade.status == "closed"
    assert "Final target" in trade.close_reason


def test_giveback_exit_fires_before_full_retrace_to_breakeven():
    trade, _ = _open_sample_long()
    trade_manager.update_trade(trade, 66100)  # TP1 hit, breakeven = 65000
    # threshold = 65000 + 0.20*(66000-65000) = 65200
    events = trade_manager.update_trade(trade, 65150)
    assert trade.status == "closed"
    assert "Give-back" in trade.close_reason


def test_hard_stop_closes_trade_before_any_tp():
    trade, _ = _open_sample_long()
    trade_manager.update_trade(trade, 63700)  # below initial stop of 63725
    assert trade.status == "closed"
    assert "Stopped out" in trade.close_reason


# --- partial-close-at-each-TP (configurable %) ------------------------------

def test_default_tp_close_pcts_is_four_equal_slices():
    trade, _ = _open_sample_long()
    assert trade.tp_close_pcts == [25.0, 25.0, 25.0, 25.0]
    assert trade.remaining_size == trade.position_size


def test_tp1_partially_closes_25pct_of_original_size_by_default():
    trade, _ = _open_sample_long()
    original_size = trade.position_size
    trade_manager.update_trade(trade, 66100)  # TP1

    assert trade.status == "open"  # NOT fully closed -- only a partial close
    assert trade.remaining_size == pytest.approx(original_size * 0.75)
    assert len(trade.partial_closes) == 1
    assert trade.partial_closes[0]["tp_index"] == 0
    assert trade.partial_closes[0]["size_closed"] == pytest.approx(original_size * 0.25)
    assert trade.realized_pnl > 0  # TP1 was a winning slice


def test_realized_pnl_accumulates_across_partial_closes():
    trade, _ = _open_sample_long()
    trade_manager.update_trade(trade, 66100)  # TP1
    pnl_after_tp1 = trade.realized_pnl
    trade_manager.update_trade(trade, 67200)  # TP2

    assert trade.realized_pnl > pnl_after_tp1  # cumulative, not overwritten
    assert len(trade.partial_closes) == 2


def test_tp4_closes_100_percent_of_remaining_regardless_of_its_own_pct():
    """Even if TP4's configured slot in tp_close_pcts isn't 100 (or is 0),
    reaching the final TP must close whatever remains outright."""
    trade, message = trade_manager.open_trade(
        symbol="BTC/USDT", direction="long", entry_price=65000.0, atr=850.0,
        stop_price=63725.0, tp_levels=[66000, 67000, 68500, 71000],
        position_size=1.0, risk_amount=200.0, account_balance=10000.0,
        tp_close_pcts=[10.0, 10.0, 10.0, 0.0],  # TP4 slot deliberately 0
    )
    for price in [66100, 67200, 68600, 71200]:
        trade_manager.update_trade(trade, price)

    assert trade.status == "closed"
    assert trade.remaining_size == 0.0
    # 10% + 10% + 10% = 30% closed at TP1-3, TP4 must close the other 70%
    assert trade.partial_closes[-1]["size_closed"] == pytest.approx(0.70)


def test_custom_tp_close_pcts_are_honored():
    trade, _ = trade_manager.open_trade(
        symbol="BTC/USDT", direction="long", entry_price=65000.0, atr=850.0,
        stop_price=63725.0, tp_levels=[66000, 67000, 68500, 71000],
        position_size=1.0, risk_amount=200.0, account_balance=10000.0,
        tp_close_pcts=[50.0, 25.0, 25.0, 25.0],
    )
    trade_manager.update_trade(trade, 66100)  # TP1
    assert trade.partial_closes[0]["size_closed"] == pytest.approx(0.50)
    assert trade.remaining_size == pytest.approx(0.50)


def test_giveback_exit_closes_only_the_remaining_size_after_tp1_partial():
    trade, _ = _open_sample_long()
    original_size = trade.position_size
    trade_manager.update_trade(trade, 66100)  # TP1: 25% closed, 75% remains
    trade_manager.update_trade(trade, 65150)  # give-back exit on the remainder

    assert trade.status == "closed"
    assert len(trade.partial_closes) == 2
    assert trade.partial_closes[1]["size_closed"] == pytest.approx(original_size * 0.75)


def test_safety_warning_flags_a_bad_slice_not_just_cumulative_loss():
    # A large TP1 win followed by a catastrophic gap-through-stop on the
    # remainder must still flag the warning for that bad slice.
    trade, _ = trade_manager.open_trade(
        symbol="BTC/USDT", direction="long", entry_price=65000.0, atr=850.0,
        stop_price=63725.0, tp_levels=[66000, 67000, 68500, 71000],
        position_size=10.0, risk_amount=200.0, account_balance=1000.0,
    )
    trade_manager.update_trade(trade, 66100)  # TP1: big win slice
    trade_manager.update_trade(trade, 50000)  # catastrophic gap on the remainder
    assert trade.safety_warning is not None
    assert "safety ceiling" in trade.safety_warning
