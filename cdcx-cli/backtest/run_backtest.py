"""backtrader Cerebro runner for the ATR_EMA_VARIANT1 strategy.

Fetches historical candles from the Crypto.com Exchange public API and
backtests ATREMAVariant1Strategy against them.
"""
import backtrader as bt

from api.cryptocom import CryptocomClient
from strategy.atr_ema_variant1_strategy import ATREMAVariant1Strategy


def run_backtest(instrument="BTC_USDT", timeframe="1h", count=500, cash=10000.0,
                  commission=0.001, ema_period=17, atr_period=11, sr_length=2.6, plot=False):
    client = CryptocomClient()
    df = client.get_candles_dataframe(instrument, timeframe=timeframe, count=count)
    if df.empty:
        raise ValueError(f"No candle data returned for {instrument} ({timeframe})")

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=commission)

    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)

    cerebro.addstrategy(
        ATREMAVariant1Strategy,
        ema_period=ema_period,
        atr_period=atr_period,
        sr_length=sr_length,
    )

    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", timeframe=bt.TimeFrame.Days)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")

    start_value = cerebro.broker.getvalue()
    results = cerebro.run()
    end_value = cerebro.broker.getvalue()

    strat = results[0]
    summary = {
        "instrument": instrument,
        "timeframe": timeframe,
        "bars": len(df),
        "start_value": start_value,
        "end_value": end_value,
        "pnl": end_value - start_value,
        "return_pct": (end_value / start_value - 1.0) * 100.0,
        "trades": strat.analyzers.trades.get_analysis(),
        "drawdown": strat.analyzers.drawdown.get_analysis(),
    }

    if plot:
        cerebro.plot()

    return summary


def format_summary(summary):
    total_trades = summary["trades"].get("total", {}).get("total", 0)
    won = summary["trades"].get("won", {}).get("total", 0)
    lost = summary["trades"].get("lost", {}).get("total", 0)
    max_dd = summary["drawdown"].get("max", {}).get("drawdown", 0.0)

    lines = [
        f"Instrument:    {summary['instrument']} ({summary['timeframe']}, {summary['bars']} bars)",
        f"Start value:   {summary['start_value']:.2f}",
        f"End value:     {summary['end_value']:.2f}",
        f"PnL:           {summary['pnl']:.2f} ({summary['return_pct']:.2f}%)",
        f"Trades:        {total_trades} (won={won}, lost={lost})",
        f"Max drawdown:  {max_dd:.2f}%",
    ]
    return "\n".join(lines)
