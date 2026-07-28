"""
cli.py
------
Command-line entry point for the CDCX AI trading engine.

Usage:
    python -m cdcx --symbol BTC/USDT --timeframe 1h --limit 200
    python -m cdcx --symbol ETH/USDT --timeframe 4h

    # multiple timeframes in one run:
    python -m cdcx --symbol BTC/USDT --timeframes 1h,4h,1d,1w --limit 200

    # multi-timeframe confluence + paper trade plan (see risk.py, confluence.py,
    # trade_manager.py -- this does NOT place a live order, it only computes
    # and locally tracks a plan):
    python -m cdcx --symbol BTC/USDT --timeframes 1h,4h,1d,1w --execute --balance 10000

    # re-check open (paper) trades against the latest price and apply the
    # break-even / trailing-stop / give-back rules:
    python -m cdcx --update-trades

    # just print current state of all tracked (paper) trades:
    python -m cdcx --list-trades
"""

from __future__ import annotations

import argparse
import sys

from . import risk
from . import trade_manager
from .confluence import evaluate_confluence
from .entry_checklist import evaluate_entry_checklist, format_checklist
from .config import settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cdcx",
        description="CDCX AI Trade Analysis -- EMA/ATR, ADX, Bollinger Bands, RSI, "
                     "Fibonacci, FVG, Volume Profile, and Market Structure combined "
                     "into one score, plus optional multi-timeframe confluence "
                     "execution planning and paper trade tracking.",
    )
    parser.add_argument("--symbol", default=settings.default_symbol, help="e.g. BTC/USDT")
    parser.add_argument(
        "--timeframe", default=None,
        help=f"single timeframe, e.g. 1h, 4h, 1d (default: {settings.default_timeframe}). "
             "Ignored if --timeframes is given.",
    )
    parser.add_argument(
        "--timeframes", default=None,
        help="comma-separated list of timeframes to run in one command, "
             "e.g. 1h,4h,1d,1w -- prints a report for each plus a combined summary. "
             "Required for --execute (confluence needs 2+ timeframes).",
    )
    parser.add_argument("--limit", type=int, default=settings.default_limit, help="number of candles to fetch")

    parser.add_argument(
        "--execute", action="store_true",
        help="Check multi-timeframe confluence (needs --timeframes with 2+ entries); "
             "if 2+ timeframes agree, compute a sized trade plan (1.5x ATR stop, 2%% "
             "account risk) and open it as a locally tracked PAPER trade. This does "
             "NOT place a live order -- there is no broker connection in this project.",
    )
    parser.add_argument(
        "--balance", type=float, default=None,
        help=f"account balance for position sizing (default: {settings.default_account_balance}, "
             "or DEFAULT_ACCOUNT_BALANCE in .env).",
    )
    parser.add_argument(
        "--risk-pct", type=float, default=None,
        help=f"risk %% per trade (default: {settings.risk_pct_per_trade}, or RISK_PCT_PER_TRADE in .env; "
             "must be <= 2.0 to pass the entry checklist).",
    )
    parser.add_argument(
        "--update-trades", action="store_true",
        help="Fetch the latest price for every open paper trade and apply the "
             "break-even / TP-ladder trailing-stop / give-back exit rules.",
    )
    parser.add_argument(
        "--list-trades", action="store_true",
        help="Print the current state of every tracked paper trade (open and closed), "
             "without fetching new prices.",
    )
    return parser


def _run_single(symbol: str, timeframe: str, limit: int):
    """Run analysis for one timeframe. Returns the TradeSignal, or None on error
    (after printing the error to stderr)."""
    from . import engine  # deferred: requires ccxt, not needed for trade-listing commands

    try:
        return engine.analyze(symbol=symbol, timeframe=timeframe, limit=limit)
    except Exception as exc:  # surface a clean error instead of a raw traceback
        print(f"Error running analysis for {symbol} @ {timeframe}: {exc}", file=sys.stderr)
        return None


def _print_summary_table(symbol: str, results: dict[str, object]) -> None:
    bar = "=" * 49
    print(bar)
    print(f"MULTI-TIMEFRAME SUMMARY -- {symbol}".center(49))
    print(bar)
    print(f"{'Timeframe':<12}{'Score':<10}{'Signal':<15}")
    print("-" * 49)
    for tf, signal in results.items():
        if signal is None:
            print(f"{tf:<12}{'--':<10}{'ERROR':<15}")
        else:
            print(f"{tf:<12}{signal.total_score:<10}{signal.signal:<15}")
    print(bar)


def _handle_execute(symbol: str, balance: float, risk_pct: float, results: dict[str, object]) -> int:
    signals_by_tf = {tf: sig.signal for tf, sig in results.items() if sig is not None}
    if len(signals_by_tf) < 2:
        print(
            "Not enough successful timeframe reads to evaluate confluence "
            f"(got {len(signals_by_tf)}, need at least 2 of 1h/4h/1d/1w). No trade planned.",
            file=sys.stderr,
        )
        return 1

    confluence = evaluate_confluence(signals_by_tf)
    print()
    print("=" * 49)
    print("CONFLUENCE CHECK (1H / 4H / 1D / 1W only)".center(49))
    print("=" * 49)
    print(confluence.label)
    if confluence.ignored_timeframes:
        print(f"(ignored for confluence purposes: {', '.join(confluence.ignored_timeframes)})")

    if not confluence.should_execute:
        print("No trade planned.")
        return 0

    entry_signal = results[confluence.entry_timeframe]
    direction = confluence.direction  # "long" | "short"
    account_balance = balance if balance is not None else settings.default_account_balance
    effective_risk_pct = risk_pct if risk_pct is not None else settings.risk_pct_per_trade

    checklist = evaluate_entry_checklist(entry_signal, direction, risk_pct=effective_risk_pct, symbol=symbol)
    print()
    print(format_checklist(checklist))

    if not checklist.all_passed:
        print("\nEntry checklist not fully satisfied -- no trade planned.")
        return 0

    plan = risk.build_position_plan(
        symbol=symbol,
        direction=direction,
        entry_price=entry_signal.entry,
        atr=entry_signal.atr,
        account_balance=account_balance,
        risk_pct=effective_risk_pct,
    )
    print()
    print(risk.format_position_plan(plan))

    tp_levels = [entry_signal.take_profits[f"TP{i}"] for i in range(1, 5)]
    trade, message = trade_manager.open_trade(
        symbol=symbol,
        direction=direction,
        entry_price=plan.entry_price,
        atr=plan.atr,
        stop_price=plan.stop_price,
        tp_levels=tp_levels,
        position_size=plan.position_size,
        risk_amount=plan.risk_amount,
        account_balance=plan.account_balance,
        confluence_timeframes=confluence.agreeing_timeframes,
        confluence_score=confluence.confluence_score,
    )
    print()
    print(message)
    if trade is not None:
        print(trade_manager.format_trade(trade))
        print(
            "\nNote: this is a locally tracked PAPER trade only -- no live order "
            "was placed. Run `python -m cdcx --update-trades` to check it against "
            "fresh prices and apply the trailing-stop rules."
        )
    return 0


def _handle_update_trades() -> int:
    from .exchange.cryptocom import CryptoComExchange  # deferred: requires ccxt

    trades = trade_manager.load_trades()
    open_trades = [t for t in trades if t.status == "open"]

    if not open_trades:
        print("No open paper trades to update.")
        return 0

    symbols = sorted({t.symbol for t in open_trades})
    exchange = CryptoComExchange(settings.cryptocom_api_key, settings.cryptocom_api_secret)

    prices_by_symbol: dict[str, float] = {}
    for sym in symbols:
        try:
            prices_by_symbol[sym] = exchange.fetch_ticker_price(sym)
        except Exception as exc:
            print(f"Could not fetch price for {sym}: {exc}", file=sys.stderr)

    results = trade_manager.update_all_open_trades(prices_by_symbol)

    if not results:
        print("Checked open trades -- no rule triggers (no TP/stop/give-back events).")
    else:
        for symbol, events in results.items():
            print(f"--- {symbol} ---")
            for event in events:
                print(f"  {event}")

    print()
    print("Current trade state:")
    for trade in trade_manager.load_trades():
        print(trade_manager.format_trade(trade))
    return 0


def _handle_list_trades() -> int:
    trades = trade_manager.load_trades()
    if not trades:
        print("No tracked paper trades yet.")
        return 0
    for trade in trades:
        print(trade_manager.format_trade(trade))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_trades:
        return _handle_list_trades()

    if args.update_trades:
        return _handle_update_trades()

    from . import engine  # deferred: requires ccxt, not needed for the two branches above

    if args.timeframes:
        timeframes = [tf.strip() for tf in args.timeframes.split(",") if tf.strip()]
        results = {}
        any_success = False

        for tf in timeframes:
            signal = _run_single(args.symbol, tf, args.limit)
            results[tf] = signal
            if signal is not None:
                any_success = True
                print(engine.format_report(signal))
                print()

        _print_summary_table(args.symbol, results)

        if args.execute:
            return _handle_execute(args.symbol, args.balance, args.risk_pct, results)

        return 0 if any_success else 1

    # single-timeframe path (backwards compatible)
    timeframe = args.timeframe or settings.default_timeframe
    signal = _run_single(args.symbol, timeframe, args.limit)
    if signal is None:
        return 1

    print(engine.format_report(signal))

    if args.execute:
        print(
            "\n--execute needs --timeframes with at least 2 timeframes to check "
            "confluence (e.g. --timeframes 1h,4h,1d,1w). No trade planned.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
