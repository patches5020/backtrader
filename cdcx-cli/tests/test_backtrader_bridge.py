"""
Exercises the backtrader bridge (backtrader_strategy.CDCXSignalStrategy +
backtrader_runner.run_backtrader_backtest) end to end against synthetic
OHLCV, through this repository's own backtrader Cerebro engine.
"""

import backtrader as bt

from cdcx.backtest.synthetic import generate_ohlcv
from cdcx.backtrader_runner import format_summary, run_backtrader_backtest
from cdcx.backtrader_strategy import CDCXSignalStrategy, _execution_direction
from cdcx.engine import analyze_ohlcv


def _synthetic_data(n_bars=400, seed=7):
    return generate_ohlcv(n_bars=n_bars, start_price=40_000.0, seed=seed, timeframe="1h")


def test_execution_direction_reads_execution_signal_not_raw_signal():
    signal = analyze_ohlcv("BTC/USDT", _synthetic_data(120, seed=1))
    # Force a mismatch to prove the execution (override-aware) field wins.
    signal.signal = "STRONG BUY"
    signal.execution_signal = "NO TRADE"
    assert _execution_direction(signal) is None

    signal.execution_signal = "STRONG SELL"
    assert _execution_direction(signal) == "short"


def test_run_backtrader_backtest_completes_and_reports_a_summary():
    data = _synthetic_data(500, seed=7)

    summary = run_backtrader_backtest(
        data,
        symbol="BTC/USDT",
        timeframe="1h",
        cash=10_000.0,
        warmup=120,
        require_checklist=False,   # loosen gating so the synthetic run has a chance to trade
        printlog=False,
    )

    assert summary["symbol"] == "BTC/USDT"
    assert summary["bars"] == 500
    assert summary["start_value"] == 10_000.0
    assert summary["end_value"] > 0
    assert "total" in summary["trades"].get("total", {}) or summary["trades"] == {}
    report = format_summary(summary)
    assert "Symbol:" in report
    assert "Max drawdown:" in report


def test_window_is_oldest_to_newest_and_matches_the_feed():
    import os

    from cdcx.backtrader_runner import _ohlcv_to_csv

    data = _synthetic_data(200, seed=3)

    captured = {}

    class _Capture(CDCXSignalStrategy):
        def next(self):
            if len(self) == self.p.warmup:  # first bar with a full window
                captured["window"] = self._window()
            # skip the real signal/order logic entirely for this test
            return

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(10_000.0)

    csv_path = _ohlcv_to_csv(data)
    try:
        feed = bt.feeds.GenericCSVData(
            dataname=csv_path, dtformat=2, headers=False,
            open=1, high=2, low=3, close=4, volume=5, openinterest=6,
        )
        cerebro.adddata(feed)
        cerebro.addstrategy(_Capture, symbol="BTC/USDT", warmup=50, printlog=False)
        cerebro.run()
    finally:
        if os.path.exists(csv_path):
            os.remove(csv_path)

    window = captured["window"]
    assert len(window.closes) == 50
    # bar 49 (0-indexed) of the source series is the last (newest) bar of a
    # 50-bar window ending there
    assert window.closes[-1] == data.closes[49]
    assert window.closes[0] == data.closes[0]
