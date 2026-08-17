"""backtrader Cerebro runners for the ATR_EMA_VARIANT1 and TrendRange strategies.

Fetches historical candles from the Crypto.com Exchange public API and
backtests a strategy against them.
"""
import backtrader as bt

from api.cryptocom import CryptocomClient
from strategy.atr_ema_variant1_strategy import ATREMAVariant1Strategy
from strategy.trend_range_strategy import (
    TrendRangeStrategy,
    DEFAULT_RISK_REWARD,
    DEFAULT_ATR_SL_MULT,
    DEFAULT_RISK_PCT,
)
from indicators.regime import DEFAULT_ADX_LENGTH, DEFAULT_TREND_THRESHOLD


def _run_cerebro(instrument, timeframe, count, cash, commission, strategy_cls, strategy_kwargs, plot):
    """Fetch candles, run ``strategy_cls`` through Cerebro, and return a summary dict."""
    client = CryptocomClient()
    df = client.get_candles_dataframe(instrument, timeframe=timeframe, count=count)
    if df.empty:
        raise ValueError(f"No candle data returned for {instrument} ({timeframe})")

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=commission)

    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)

    cerebro.addstrategy(strategy_cls, **strategy_kwargs)

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


def run_backtest(instrument="BTC_USDT", timeframe="1h", count=500, cash=10000.0,
                  commission=0.001, ema_period=17, atr_period=11, sr_length=2.6, plot=False):
    """Backtest ATREMAVariant1Strategy: buy on a support touch, close on resistance."""
    return _run_cerebro(
        instrument, timeframe, count, cash, commission,
        strategy_cls=ATREMAVariant1Strategy,
        strategy_kwargs=dict(ema_period=ema_period, atr_period=atr_period, sr_length=sr_length),
        plot=plot,
    )


def run_trend_range_backtest(instrument="BTC_USDT", timeframe="1h", count=500, cash=10000.0,
                              commission=0.001, ema_period=17, atr_period=11, sr_length=2.6,
                              adx_period=DEFAULT_ADX_LENGTH, adx_threshold=DEFAULT_TREND_THRESHOLD,
                              risk_reward=DEFAULT_RISK_REWARD, atr_sl_mult=DEFAULT_ATR_SL_MULT,
                              risk_pct=DEFAULT_RISK_PCT, plot=False):
    """Backtest TrendRangeStrategy: trend-regime breakouts + range-regime mean
    reversion, both sized off a single ATR stop-loss / take-profit /
    risk-to-reward framework."""
    return _run_cerebro(
        instrument, timeframe, count, cash, commission,
        strategy_cls=TrendRangeStrategy,
        strategy_kwargs=dict(
            ema_period=ema_period, atr_period=atr_period, sr_length=sr_length,
            adx_period=adx_period, adx_threshold=adx_threshold,
            risk_reward=risk_reward, atr_sl_mult=atr_sl_mult, risk_pct=risk_pct,
        ),
        plot=plot,
    )


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
