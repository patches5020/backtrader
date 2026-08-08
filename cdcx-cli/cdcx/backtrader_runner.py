"""
backtrader_runner.py
---------------------
Cerebro runner for `CDCXSignalStrategy` (see `backtrader_strategy.py`):
fetches (or accepts already-loaded) OHLCV candles and backtests the CDCX
AI signal engine against them through backtrader's own engine, broker, and
analyzers -- this repository's native backtesting stack.

No pandas dependency: candles are fed to backtrader via a temporary
`GenericCSVData` file (Unix-timestamp seconds), so this only adds `ccxt`
(already a `cdcx-cli` dependency) on top of `backtrader` itself.
"""

from __future__ import annotations

import csv
import os
import tempfile
from typing import Optional

import backtrader as bt

from .backtrader_strategy import CDCXSignalStrategy
from .config import settings
from .exchange.cryptocom import OHLCV, CryptoComExchange


def fetch_ohlcv(symbol: str, timeframe: str, limit: int) -> OHLCV:
    exchange = CryptoComExchange(settings.cryptocom_api_key, settings.cryptocom_api_secret)
    return exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)


def _ohlcv_to_csv(data: OHLCV) -> str:
    """Write an OHLCV series to a temp CSV consumable by bt.feeds.GenericCSVData
    (dtformat=2 => Unix timestamp in seconds, float)."""
    path = tempfile.mktemp(suffix="_cdcx_bt_feed.csv")
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        for i in range(len(data.closes)):
            writer.writerow([
                data.timestamps[i] / 1000.0,
                data.opens[i],
                data.highs[i],
                data.lows[i],
                data.closes[i],
                data.volumes[i],
                -1,
            ])
    return path


def run_backtrader_backtest(
    data: OHLCV,
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    cash: float = 10_000.0,
    commission: float = 0.001,
    warmup: int = 120,
    risk_pct: Optional[float] = None,
    min_score_long: float = 60.0,
    min_score_short: float = 40.0,
    require_checklist: bool = True,
    plot: bool = False,
    printlog: bool = True,
) -> dict:
    """
    Run `CDCXSignalStrategy` through a backtrader `Cerebro` over `data`.
    Returns a summary dict; see `format_summary`.
    """
    symbol = symbol or settings.default_symbol
    timeframe = timeframe or settings.default_timeframe

    csv_path = _ohlcv_to_csv(data)
    try:
        cerebro = bt.Cerebro()
        cerebro.broker.setcash(cash)
        cerebro.broker.setcommission(commission=commission)

        feed = bt.feeds.GenericCSVData(
            dataname=csv_path,
            dtformat=2,
            headers=False,  # the temp CSV has no header row -- don't drop the first bar
            open=1, high=2, low=3, close=4, volume=5, openinterest=6,
        )
        cerebro.adddata(feed)

        cerebro.addstrategy(
            CDCXSignalStrategy,
            symbol=symbol,
            warmup=warmup,
            risk_pct=risk_pct,
            min_score_long=min_score_long,
            min_score_short=min_score_short,
            require_checklist=require_checklist,
            printlog=printlog,
        )

        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")

        start_value = cerebro.broker.getvalue()
        results = cerebro.run()
        end_value = cerebro.broker.getvalue()

        strat = results[0]
        summary = {
            "symbol": symbol,
            "timeframe": timeframe,
            "bars": len(data.closes),
            "start_value": start_value,
            "end_value": end_value,
            "pnl": end_value - start_value,
            "return_pct": (end_value / start_value - 1.0) * 100.0 if start_value else 0.0,
            "trades": strat.analyzers.trades.get_analysis(),
            "drawdown": strat.analyzers.drawdown.get_analysis(),
        }

        if plot:
            cerebro.plot()

        return summary
    finally:
        if os.path.exists(csv_path):
            os.remove(csv_path)


def format_summary(summary: dict) -> str:
    total_trades = summary["trades"].get("total", {}).get("total", 0)
    won = summary["trades"].get("won", {}).get("total", 0)
    lost = summary["trades"].get("lost", {}).get("total", 0)
    max_dd = summary["drawdown"].get("max", {}).get("drawdown", 0.0)

    lines = [
        f"Symbol:        {summary['symbol']} ({summary['timeframe']}, {summary['bars']} bars)",
        f"Start value:   {summary['start_value']:.2f}",
        f"End value:     {summary['end_value']:.2f}",
        f"PnL:           {summary['pnl']:.2f} ({summary['return_pct']:.2f}%)",
        f"Trades:        {total_trades} (won={won}, lost={lost})",
        f"Max drawdown:  {max_dd:.2f}%",
    ]
    return "\n".join(lines)
