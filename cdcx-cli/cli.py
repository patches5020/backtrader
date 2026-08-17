#!/usr/bin/env python3
"""cdcx-cli: Crypto.com Exchange CLI for the ATR_EMA_VARIANT1 indicator.

Subcommands: run, chart, scan, backtest. See README.md for examples.
"""
import argparse
import json
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_THIS_DIR)
for path in (_THIS_DIR, _REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from api.cryptocom import CryptocomClient, CryptocomAPIError
from indicators.atr_ema_variant1 import compute_atr_ema_variant1, DEFAULT_EMA_LENGTH, DEFAULT_ATR_LENGTH, DEFAULT_SR_LENGTH
from indicators.regime import DEFAULT_ADX_LENGTH, DEFAULT_TREND_THRESHOLD
from strategy.trend_range_strategy import DEFAULT_RISK_REWARD, DEFAULT_ATR_SL_MULT, DEFAULT_RISK_PCT
from integrations.tvremix_mcp import MCPClient, MCPError, DEFAULT_MCP_URL


def add_indicator_args(parser):
    parser.add_argument("--instrument", default="BTC_USDT", help="e.g. BTC_USDT")
    parser.add_argument("--timeframe", default="1h", help="e.g. 1m,5m,15m,30m,1h,4h,1D")
    parser.add_argument("--count", type=int, default=200, help="number of candles to fetch")
    parser.add_argument("--ema-length", type=int, default=DEFAULT_EMA_LENGTH)
    parser.add_argument("--atr-length", type=int, default=DEFAULT_ATR_LENGTH)
    parser.add_argument("--sr-length", type=float, default=DEFAULT_SR_LENGTH)


def cmd_run(args):
    client = CryptocomClient()
    df = client.get_candles_dataframe(args.instrument, timeframe=args.timeframe, count=args.count)
    if df.empty:
        print(f"No candle data returned for {args.instrument}", file=sys.stderr)
        return 1

    signal = compute_atr_ema_variant1(
        df, ema_length=args.ema_length, atr_length=args.atr_length, sr_length=args.sr_length,
    )
    latest = signal.iloc[-1]
    print(f"{args.instrument} ({args.timeframe}) latest bar: {df.index[-1]}")
    print(f"  close:      {df['close'].iloc[-1]:.6f}")
    print(f"  ema:        {latest['ema']:.6f}")
    print(f"  support:    {latest['support']:.6f}")
    print(f"  resistance: {latest['resistance']:.6f}")
    print(f"  support_hit:    {bool(latest['support_hit'])}")
    print(f"  resistance_hit: {bool(latest['resistance_hit'])}")
    return 0


def cmd_chart(args):
    from charts.atr_ema_variant1_chart import plot_atr_ema_variant1

    client = CryptocomClient()
    df = client.get_candles_dataframe(args.instrument, timeframe=args.timeframe, count=args.count)
    if df.empty:
        print(f"No candle data returned for {args.instrument}", file=sys.stderr)
        return 1

    output = plot_atr_ema_variant1(
        df, args.output, ema_length=args.ema_length, atr_length=args.atr_length,
        sr_length=args.sr_length, title=f"{args.instrument} ({args.timeframe})",
    )
    print(f"Chart written to {output}")
    return 0


def cmd_scan(args):
    from scanner.sr_scanner import scan_instruments, format_scan_results

    instruments = [s.strip() for s in args.instruments.split(",") if s.strip()]
    results = scan_instruments(
        instruments, timeframe=args.timeframe, count=args.count,
        ema_length=args.ema_length, atr_length=args.atr_length, sr_length=args.sr_length,
    )
    print(format_scan_results(results))
    return 0


def cmd_backtest(args):
    from backtest.run_backtest import run_backtest, format_summary

    summary = run_backtest(
        instrument=args.instrument, timeframe=args.timeframe, count=args.count,
        cash=args.cash, commission=args.commission,
        ema_period=args.ema_length, atr_period=args.atr_length, sr_length=args.sr_length,
        plot=args.plot,
    )
    print(format_summary(summary))
    return 0


def cmd_trend_range(args):
    from backtest.run_backtest import run_trend_range_backtest, format_summary

    summary = run_trend_range_backtest(
        instrument=args.instrument, timeframe=args.timeframe, count=args.count,
        cash=args.cash, commission=args.commission,
        ema_period=args.ema_length, atr_period=args.atr_length, sr_length=args.sr_length,
        adx_period=args.adx_length, adx_threshold=args.adx_threshold,
        risk_reward=args.risk_reward, atr_sl_mult=args.atr_sl_mult, risk_pct=args.risk_pct,
        plot=args.plot,
    )
    print(format_summary(summary))
    return 0


def _mcp_client_from_args(args):
    return MCPClient(url=args.url, api_key=args.api_key)


def cmd_mcp_list_tools(args):
    client = _mcp_client_from_args(args)
    tools = client.list_tools()
    if not tools:
        print("No tools reported by the MCP server.")
        return 0
    for tool in tools:
        name = tool.get("name", "?")
        description = tool.get("description", "")
        print(f"- {name}: {description}")
    return 0


def cmd_mcp_call(args):
    try:
        arguments = json.loads(args.args) if args.args else {}
    except json.JSONDecodeError as exc:
        print(f"--args must be valid JSON: {exc}", file=sys.stderr)
        return 1

    client = _mcp_client_from_args(args)
    content = client.call_tool(args.tool, arguments)
    print(json.dumps(content, indent=2, default=str))
    return 0


def add_mcp_connection_args(parser):
    parser.add_argument("--url", default=os.environ.get("TVREMIX_MCP_URL", DEFAULT_MCP_URL),
                         help="MCP server endpoint (env: TVREMIX_MCP_URL)")
    parser.add_argument("--api-key", default=os.environ.get("TVREMIX_API_KEY"),
                         help="Bearer token, if the server requires auth (env: TVREMIX_API_KEY)")


def build_parser():
    parser = argparse.ArgumentParser(prog="cdcx-cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_run = subparsers.add_parser("run", help="Fetch candles and print the latest ATR_EMA_VARIANT1 signal")
    add_indicator_args(p_run)
    p_run.set_defaults(func=cmd_run)

    p_chart = subparsers.add_parser("chart", help="Render a chart mirroring the Pine Script plots")
    add_indicator_args(p_chart)
    p_chart.add_argument("--output", default="chart.png")
    p_chart.set_defaults(func=cmd_chart)

    p_scan = subparsers.add_parser("scan", help="Scan multiple instruments for support/resistance hits")
    p_scan.add_argument("--instruments", required=True, help="Comma-separated, e.g. BTC_USDT,ETH_USDT")
    p_scan.add_argument("--timeframe", default="1h")
    p_scan.add_argument("--count", type=int, default=200)
    p_scan.add_argument("--ema-length", type=int, default=DEFAULT_EMA_LENGTH)
    p_scan.add_argument("--atr-length", type=int, default=DEFAULT_ATR_LENGTH)
    p_scan.add_argument("--sr-length", type=float, default=DEFAULT_SR_LENGTH)
    p_scan.set_defaults(func=cmd_scan)

    p_backtest = subparsers.add_parser("backtest", help="Backtest the ATR_EMA_VARIANT1 strategy with backtrader")
    add_indicator_args(p_backtest)
    p_backtest.add_argument("--cash", type=float, default=10000.0)
    p_backtest.add_argument("--commission", type=float, default=0.001)
    p_backtest.add_argument("--plot", action="store_true")
    p_backtest.set_defaults(func=cmd_backtest)

    p_trend_range = subparsers.add_parser(
        "trend-range",
        help="Backtest the regime-adaptive strategy (trend breakouts + range mean-reversion, "
             "ATR stop-loss/take-profit sized to a fixed risk-to-reward ratio)",
    )
    add_indicator_args(p_trend_range)
    p_trend_range.add_argument("--adx-length", type=int, default=DEFAULT_ADX_LENGTH,
                                help="ADX lookback used for trend/range classification")
    p_trend_range.add_argument("--adx-threshold", type=float, default=DEFAULT_TREND_THRESHOLD,
                                help="ADX value at/above which the market is classified as trending")
    p_trend_range.add_argument("--risk-reward", type=float, default=DEFAULT_RISK_REWARD,
                                help="Take-profit distance as a multiple of the stop-loss distance")
    p_trend_range.add_argument("--atr-sl-mult", type=float, default=DEFAULT_ATR_SL_MULT,
                                help="Stop-loss distance from entry, in multiples of ATR")
    p_trend_range.add_argument("--risk-pct", type=float, default=DEFAULT_RISK_PCT,
                                help="Percent of account equity risked per trade (position sizing)")
    p_trend_range.add_argument("--cash", type=float, default=10000.0)
    p_trend_range.add_argument("--commission", type=float, default=0.001)
    p_trend_range.add_argument("--plot", action="store_true")
    p_trend_range.set_defaults(func=cmd_trend_range)

    p_mcp = subparsers.add_parser("mcp", help="Talk to the tvremix.ai MCP (Model Context Protocol) server")
    mcp_subparsers = p_mcp.add_subparsers(dest="mcp_command", required=True)

    p_mcp_list = mcp_subparsers.add_parser("list-tools", help="List the tools the MCP server exposes")
    add_mcp_connection_args(p_mcp_list)
    p_mcp_list.set_defaults(func=cmd_mcp_list_tools)

    p_mcp_call = mcp_subparsers.add_parser("call", help="Call a tool on the MCP server")
    add_mcp_connection_args(p_mcp_call)
    p_mcp_call.add_argument("--tool", required=True, help="Tool name, as reported by 'mcp list-tools'")
    p_mcp_call.add_argument("--args", default=None, help="Tool arguments as a JSON object, e.g. '{\"symbol\": \"BTCUSD\"}'")
    p_mcp_call.set_defaults(func=cmd_mcp_call)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CryptocomAPIError as exc:
        print(f"Crypto.com API error: {exc}", file=sys.stderr)
        return 1
    except MCPError as exc:
        print(f"tvremix MCP error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
