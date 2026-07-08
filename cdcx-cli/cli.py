#!/usr/bin/env python3
"""cdcx-cli: Crypto.com Exchange CLI for the ATR_EMA_VARIANT1 indicator.

Subcommands: run, chart, scan, backtest. See README.md for examples.
"""
import argparse
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_THIS_DIR)
for path in (_THIS_DIR, _REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from api.cryptocom import CryptocomClient, CryptocomAPIError
from indicators.atr_ema_variant1 import compute_atr_ema_variant1, DEFAULT_EMA_LENGTH, DEFAULT_ATR_LENGTH, DEFAULT_SR_LENGTH


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

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CryptocomAPIError as exc:
        print(f"Crypto.com API error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
