"""
cdcx.backtest
-------------
Offline backtesting for the CDCX AI trade analysis engine.

Usage:
    python -m cdcx.backtest          # synthetic-data demo
    from cdcx.backtest.engine import run_single_tf_backtest, run_confluence_backtest
    from cdcx.backtest.synthetic import generate_ohlcv
"""

from .engine import (
    BacktestResult,
    BacktestTrade,
    run_single_tf_backtest,
    run_confluence_backtest,
    format_backtest_report,
)
from .synthetic import generate_ohlcv, resample_ohlcv

__all__ = [
    "BacktestResult",
    "BacktestTrade",
    "run_single_tf_backtest",
    "run_confluence_backtest",
    "format_backtest_report",
    "generate_ohlcv",
    "resample_ohlcv",
]

# Execution models (optional import)
try:
    from .execution import (
        execute_market,
        execute_twap,
        compare_market_vs_twap,
        format_execution_comparison,
    )
except ImportError:
    pass
