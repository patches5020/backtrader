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
