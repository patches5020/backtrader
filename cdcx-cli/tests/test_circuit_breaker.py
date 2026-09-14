import pytest

from cdcx.config import settings
from cdcx import trade_manager, circuit_breaker


@pytest.fixture(autouse=True)
def isolated_trade_state(tmp_path):
    original = settings.trade_state_path
    settings.trade_state_path = str(tmp_path / "trades_test.json")
    yield
    settings.trade_state_path = original


# --- pure check_circuit_breaker() ------------------------------------------

def test_clear_when_no_losses_and_no_drawdown():
    result = circuit_breaker.check_circuit_breaker(
        realized_pnls=[100, 50, 200], peak_equity=10000, current_equity=10350,
    )
    assert result.tripped is False
    assert result.consecutive_losses == 0


def test_trips_on_consecutive_losses():
    result = circuit_breaker.check_circuit_breaker(
        realized_pnls=[100, -50, -60, -70], peak_equity=10000, current_equity=9820,
        max_consecutive_losses=3, max_drawdown_pct=50.0,
    )
    assert result.tripped is True
    assert result.consecutive_losses == 3
    assert "consecutive losses" in result.reason


def test_a_win_resets_the_consecutive_streak():
    result = circuit_breaker.check_circuit_breaker(
        realized_pnls=[-50, -60, 10, -70], peak_equity=10000, current_equity=9830,
        max_consecutive_losses=3, max_drawdown_pct=50.0,
    )
    assert result.tripped is False  # only 1 loss since the last win
    assert result.consecutive_losses == 1


def test_breakeven_close_counts_as_a_loss_for_streak_purposes():
    result = circuit_breaker.check_circuit_breaker(
        realized_pnls=[0, 0, 0], peak_equity=10000, current_equity=10000,
        max_consecutive_losses=3, max_drawdown_pct=50.0,
    )
    assert result.tripped is True
    assert result.consecutive_losses == 3


def test_trips_on_drawdown_from_peak():
    result = circuit_breaker.check_circuit_breaker(
        realized_pnls=[500, -200], peak_equity=10500, current_equity=9300,
        max_consecutive_losses=10, max_drawdown_pct=10.0,
    )
    assert result.tripped is True
    assert result.current_drawdown_pct == pytest.approx(11.43, abs=0.01)
    assert "Drawdown" in result.reason


def test_does_not_trip_below_both_thresholds():
    result = circuit_breaker.check_circuit_breaker(
        realized_pnls=[-10, -20], peak_equity=10000, current_equity=9970,
        max_consecutive_losses=5, max_drawdown_pct=10.0,
    )
    assert result.tripped is False


def test_disabled_trigger_via_infinite_threshold():
    """Callers disable one trigger by passing float('inf') (see
    backtest/engine.py's _circuit_breaker_tripped and cli.py's use of a
    None -> inf mapping)."""
    result = circuit_breaker.check_circuit_breaker(
        realized_pnls=[-10, -20, -30, -40], peak_equity=10000, current_equity=9900,
        max_consecutive_losses=float("inf"), max_drawdown_pct=10.0,
    )
    assert result.tripped is False  # consecutive-loss trigger disabled, drawdown still under 10%


# --- check_circuit_breaker_for_symbol() (reads trade_manager state) -------

def _open_and_close(symbol, entry_price, stop_price, exit_price, account_balance=10000.0):
    """Opens a trade, immediately closes it at `exit_price` (via a real
    trade_manager.update_trade call -- exercises the actual stop/TP
    machinery, not a hand-rolled closed Trade), and persists the close."""
    trade, _ = trade_manager.open_trade(
        symbol=symbol, direction="long", entry_price=entry_price, atr=100.0,
        stop_price=stop_price, tp_levels=[entry_price + 200, entry_price + 400, entry_price + 600, entry_price + 800],
        position_size=1.0, risk_amount=200.0, account_balance=account_balance,
    )
    trade_manager.update_trade(trade, exit_price)  # mutates `trade` in place
    all_trades = trade_manager.load_trades()
    all_trades = [trade if t.id == trade.id else t for t in all_trades]
    trade_manager.save_trades(all_trades)


def test_for_symbol_clear_with_no_trades():
    result = circuit_breaker.check_circuit_breaker_for_symbol("BTC/USDT")
    assert result.tripped is False


def test_for_symbol_trips_after_real_losing_streak():
    # each losing trade: entry 65000, stop 64000 (loss), exit below stop
    for _ in range(3):
        _open_and_close("BTC/USDT", entry_price=65000.0, stop_price=64000.0, exit_price=63500.0)

    result = circuit_breaker.check_circuit_breaker_for_symbol(
        "BTC/USDT", max_consecutive_losses=3, max_drawdown_pct=100.0,
    )
    assert result.tripped is True
    assert result.consecutive_losses == 3


def test_for_symbol_only_considers_the_given_symbol():
    for _ in range(3):
        _open_and_close("ETH/USDT", entry_price=3000.0, stop_price=2900.0, exit_price=2800.0)

    result = circuit_breaker.check_circuit_breaker_for_symbol(
        "BTC/USDT", max_consecutive_losses=3, max_drawdown_pct=100.0,
    )
    assert result.tripped is False  # losses were on a different symbol


# --- formatting -------------------------------------------------------------

def test_format_circuit_breaker_shows_tripped_status():
    result = circuit_breaker.CircuitBreakerResult(
        tripped=True, reason="3 consecutive losses (limit 3)",
        consecutive_losses=3, current_drawdown_pct=5.0, peak_equity=10000.0, current_equity=9500.0,
    )
    text = circuit_breaker.format_circuit_breaker(result)
    assert "TRIPPED" in text
    assert "3 consecutive losses (limit 3)" in text


def test_format_circuit_breaker_shows_clear_status():
    result = circuit_breaker.CircuitBreakerResult(
        tripped=False, reason="", consecutive_losses=0, current_drawdown_pct=0.0,
        peak_equity=10000.0, current_equity=10000.0,
    )
    text = circuit_breaker.format_circuit_breaker(result)
    assert "clear" in text
