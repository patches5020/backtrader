"""
Integration tests for cli.py's regime-gated --execute pipeline. These call
the internal _handle_trending_path / _handle_ranging_path functions directly
with constructed inputs (rather than through fake ccxt market data, which is
unreliable for hitting exact regime/setup conditions) -- this verifies the
real wiring between regime -> checklist/setup -> no-trade filter -> weighted
confidence -> position sizing -> trade_manager.open_trade all fits together
correctly, using the same code path the real CLI calls.
"""

import os
import pytest
from types import SimpleNamespace

from cdcx.config import settings
from cdcx import cli, trade_manager
from cdcx.confluence import evaluate_confluence
from cdcx.indicators.candlestick_patterns import PatternMatch


@pytest.fixture(autouse=True)
def isolated_trade_state(tmp_path):
    original = settings.trade_state_path
    settings.trade_state_path = str(tmp_path / "trades_test.json")
    yield
    settings.trade_state_path = original


def test_trending_path_opens_trade_when_everything_confirms():
    entry_signal = SimpleNamespace(
        entry=65000.0, atr=850.0,
        take_profits={"TP1": 67600.0, "TP2": 68500.0, "TP3": 69800.0, "TP4": 72000.0},
        scores={
            "ema_trend": 15, "fib_retracement": 9, "fair_value_gap": 15,
            "fixed_volume_profile": 10, "anchored_volume_profile": 10,
            "rsi_momentum": 12, "adx_trend_strength": 10,
        },
        labels={"bollinger_bands": "Riding Upper Band (Bullish Continuation)"},
    )
    signals_by_tf = {"1h": "STRONG BUY", "4h": "STRONG BUY", "1d": "BUY", "1w": "BUY"}
    confluence = evaluate_confluence(signals_by_tf)
    atr_series = [800 + i for i in range(20)]

    code = cli._handle_trending_path(
        "BTC/USDT", "long", entry_signal, 10000.0, 2.0,
        signals_by_tf, confluence, atr_series, adx_value=30.0, news_imminent=False,
        live=False, instrument_name_override=None,
    )
    assert code == 0
    trades = trade_manager.load_trades()
    assert len(trades) == 1
    assert trades[0].status == "open"
    assert trades[0].tp_levels == [67600.0, 68500.0, 69800.0, 72000.0]


def test_trending_path_blocked_by_failing_checklist():
    entry_signal = SimpleNamespace(
        entry=65000.0, atr=850.0,
        take_profits={"TP1": 67600.0, "TP2": 68500.0, "TP3": 69800.0, "TP4": 72000.0},
        scores={
            "ema_trend": 15, "fib_retracement": 0, "fair_value_gap": 15,  # fib NOT confirming
            "fixed_volume_profile": 10, "anchored_volume_profile": 10,
        },
        labels={"bollinger_bands": "Riding Upper Band (Bullish Continuation)"},
    )
    signals_by_tf = {"1h": "STRONG BUY", "4h": "STRONG BUY"}
    confluence = evaluate_confluence(signals_by_tf)

    code = cli._handle_trending_path(
        "BTC/USDT", "long", entry_signal, 10000.0, 2.0,
        signals_by_tf, confluence, [800] * 20, adx_value=30.0, news_imminent=False,
        live=False, instrument_name_override=None,
    )
    assert code == 0
    assert trade_manager.load_trades() == []


def test_trending_path_blocked_by_overextension_guard():
    entry_signal = SimpleNamespace(
        entry=65000.0, atr=850.0,
        take_profits={"TP1": 67600.0, "TP2": 68500.0, "TP3": 69800.0, "TP4": 72000.0},
        scores={
            "ema_trend": 15, "fib_retracement": 9, "fair_value_gap": 15,
            "fixed_volume_profile": 10, "anchored_volume_profile": 10,
        },
        labels={"bollinger_bands": "Above Upper Band (Extended)"},  # overextended
    )
    signals_by_tf = {"1h": "STRONG BUY", "4h": "STRONG BUY"}
    confluence = evaluate_confluence(signals_by_tf)

    code = cli._handle_trending_path(
        "BTC/USDT", "long", entry_signal, 10000.0, 2.0,
        signals_by_tf, confluence, [800] * 20, adx_value=30.0, news_imminent=False,
        live=False, instrument_name_override=None,
    )
    assert code == 0
    assert trade_manager.load_trades() == []


def test_trending_path_blocked_by_no_trade_filter_low_rr():
    entry_signal = SimpleNamespace(
        entry=65000.0, atr=850.0,
        take_profits={"TP1": 65500.0, "TP2": 65800.0, "TP3": 66000.0, "TP4": 66200.0},  # too close -> RR < 2
        scores={
            "ema_trend": 15, "fib_retracement": 9, "fair_value_gap": 15,
            "fixed_volume_profile": 10, "anchored_volume_profile": 10,
        },
        labels={"bollinger_bands": "Riding Upper Band (Bullish Continuation)"},
    )
    signals_by_tf = {"1h": "STRONG BUY", "4h": "STRONG BUY"}
    confluence = evaluate_confluence(signals_by_tf)

    code = cli._handle_trending_path(
        "BTC/USDT", "long", entry_signal, 10000.0, 2.0,
        signals_by_tf, confluence, [800] * 20, adx_value=30.0, news_imminent=False,
        live=False, instrument_name_override=None,
    )
    assert code == 0
    assert trade_manager.load_trades() == []


def test_ranging_path_opens_trade_with_poc_and_edge_targets():
    entry_signal = SimpleNamespace(entry=59500.0, atr=400.0)
    rsi_series = [45, 38, 32, 30, 34]
    vp_result = SimpleNamespace(poc=61000.0, vah=62500.0, val=59400.0)
    pattern_matches = [PatternMatch("Hammer", "bullish", 2)]

    code = cli._handle_ranging_path(
        "BTC/USDT", entry_signal, 10000.0, 2.0,
        rsi_series, vp_result, pattern_matches, [400] * 20, adx_value=15.0, news_imminent=False,
        live=False, instrument_name_override=None,
    )
    assert code == 0
    trades = trade_manager.load_trades()
    assert len(trades) == 1
    assert trades[0].tp_levels == [61000.0, 62500.0]  # POC, then opposite edge
    assert trades[0].direction == "long"


def test_ranging_path_no_trade_when_setup_invalid():
    entry_signal = SimpleNamespace(entry=61000.0, atr=400.0)  # mid-range, no setup
    rsi_series = [50, 51, 52]
    vp_result = SimpleNamespace(poc=61000.0, vah=62500.0, val=59400.0)

    code = cli._handle_ranging_path(
        "BTC/USDT", entry_signal, 10000.0, 2.0,
        rsi_series, vp_result, [], [400] * 20, adx_value=15.0, news_imminent=False,
        live=False, instrument_name_override=None,
    )
    assert code == 0
    assert trade_manager.load_trades() == []


def test_news_imminent_flag_blocks_an_otherwise_valid_trending_trade():
    entry_signal = SimpleNamespace(
        entry=65000.0, atr=850.0,
        take_profits={"TP1": 67600.0, "TP2": 68500.0, "TP3": 69800.0, "TP4": 72000.0},
        scores={
            "ema_trend": 15, "fib_retracement": 9, "fair_value_gap": 15,
            "fixed_volume_profile": 10, "anchored_volume_profile": 10,
        },
        labels={"bollinger_bands": "Riding Upper Band (Bullish Continuation)"},
    )
    signals_by_tf = {"1h": "STRONG BUY", "4h": "STRONG BUY"}
    confluence = evaluate_confluence(signals_by_tf)

    code = cli._handle_trending_path(
        "BTC/USDT", "long", entry_signal, 10000.0, 2.0,
        signals_by_tf, confluence, [800] * 20, adx_value=30.0, news_imminent=True,
        live=False, instrument_name_override=None,
    )
    assert code == 0
    assert trade_manager.load_trades() == []
