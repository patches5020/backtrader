"""
Integration tests for cli_equity.py's _handle_execute_confluence -- the
--timeframes (plural) --execute path added as a direct follow-on to
cli.py's confluence + entry_checklist + entry_location pipeline (see
cli_equity.py's module docstring). Mirrors tests/test_execute_integration.py's
approach: real TradeSignal / RegimeResult instances, not mocks, calling the
actual function cli_equity.main() calls.
"""

from types import SimpleNamespace

import pytest

from cdcx import cli_equity, engine, trade_manager
from cdcx.config import settings
from cdcx.regime import RegimeResult


@pytest.fixture(autouse=True)
def isolated_trade_state(tmp_path):
    original = settings.trade_state_path
    settings.trade_state_path = str(tmp_path / "trades_test.json")
    yield
    settings.trade_state_path = original


def _raw_data(n=40, base=350.0):
    closes = [base + i * 1.5 for i in range(n)]
    highs = [c + 3 for c in closes]
    lows = [c - 3 for c in closes]
    volumes = [10000.0] * n
    return SimpleNamespace(highs=highs, lows=lows, closes=closes, volumes=volumes)


def _signal(tf: str, regime_state: str, fib_score: float = 9.0, symbol="AAPL") -> engine.TradeSignal:
    return engine.TradeSignal(
        symbol=symbol, total_score=100.0, signal="STRONG BUY", stars="*****",
        scores={
            "ema_trend": 15, "fib_retracement": fib_score, "fair_value_gap": 15,
            "fixed_volume_profile": 10, "anchored_volume_profile": 10,
        },
        labels={"bollinger_bands": "Riding Upper Band (Bullish Continuation)", "fair_value_gap": "Bullish FVG"},
        entry=350.0, atr=8.0, stop_loss=338.0,
        take_profits={"TP1": 367.6, "TP2": 368.5, "TP3": 369.8, "TP4": 372.0},
        risk_reward_ratio=2.2, confidence=90.0,
        regime=RegimeResult(regime=regime_state, trend_score=8, range_score=3),
        execution_signal="STRONG BUY", timeframe=tf,
    )


def _trending_results():
    return {tf: _signal(tf, "trending") for tf in ("1h", "4h", "1d", "1w")}


def test_confluence_path_opens_trade_when_everything_confirms():
    results = _trending_results()
    raw_data_by_tf = {tf: _raw_data() for tf in results}

    code = cli_equity._handle_execute_confluence("AAPL", results, raw_data_by_tf, balance=10000.0, risk_pct=2.0)
    assert code == 0
    trades = trade_manager.load_trades()
    assert len(trades) == 1
    assert trades[0].status == "open"
    assert trades[0].direction == "long"


def test_confluence_path_blocked_by_failing_fib_checklist_item():
    results = _trending_results()
    for signal in results.values():
        signal.scores["fib_retracement"] = 0  # Fibonacci NOT confirming
    raw_data_by_tf = {tf: _raw_data() for tf in results}

    code = cli_equity._handle_execute_confluence("AAPL", results, raw_data_by_tf, balance=10000.0, risk_pct=2.0)
    assert code == 0
    assert trade_manager.load_trades() == []


def test_confluence_path_no_trade_when_fewer_than_two_tradeable_timeframes():
    results = {"1h": _signal("1h", "transitional")}  # only one, and it's transitional -> excluded
    raw_data_by_tf = {"1h": _raw_data()}

    code = cli_equity._handle_execute_confluence("AAPL", results, raw_data_by_tf, balance=10000.0, risk_pct=2.0)
    assert code == 1
    assert trade_manager.load_trades() == []


def test_confluence_path_blocked_when_entry_timeframe_regime_recomputes_transitional():
    results = _trending_results()
    # A flat, unmoving raw series (min-min triggers no swing structure/ADX
    # trend at all) reliably recomputes as transitional once
    # higher_timeframes_aligned=True is applied on refetch.
    raw_data_by_tf = {tf: SimpleNamespace(
        highs=[350.0 + 0.001 * i for i in range(40)],
        lows=[349.99 + 0.001 * i for i in range(40)],
        closes=[349.995 + 0.001 * i for i in range(40)],
        volumes=[10000.0] * 40,
    ) for tf in results}

    code = cli_equity._handle_execute_confluence("AAPL", results, raw_data_by_tf, balance=10000.0, risk_pct=2.0)
    assert code == 0
    assert trade_manager.load_trades() == []
