"""
cli_equity.py
--------------
Command-line entry point for running the SAME CDCX AI Trade Analysis engine
(cdcx/engine.py: EMA/ATR, ADX, Bollinger Bands, RSI, Fibonacci, FVG, Volume
Profile, Market Structure, candlestick patterns -> one weighted score,
identical report format) against equities/ETFs/indexes sourced from
Robinhood or Webull, instead of crypto via Crypto.com.

Only the DATA SOURCE differs from `cli.py` -- engine.analyze_ohlcv() and
engine.format_report() run completely unchanged; see cdcx/exchange/
robinhood_equity.py and cdcx/exchange/webull_equity.py. This file is
entirely additive: nothing in cli.py, engine.py, or any other existing
cdcx-cli module was touched to build it.

This deliberately does NOT reuse cli.py's confluence / entry-checklist /
no-trade-filter trending-vs-ranging state machine, nor its circuit-breaker
/ no-trade-gate / journal live-trading-safety layer -- that machinery was
built and tuned against crypto ATR/regime behavior and hasn't been
validated for equities. --execute here is intentionally simpler: it opens
a paper trade straight off engine.py's own execution_signal (which already
gates on regime + R:R -- see engine.py's "Execution signal" section) --
no separate confluence/checklist layer, and no --live path at all (no
equity broker order-placement exists here). If that turns out to need the
same rigor as the crypto path, it can be added later; this is honest about
not having it yet rather than faking parity.

Usage:
    cdcx-equity --source robinhood --symbol SPCX --timeframe 1h
    cdcx-equity --source webull --symbol AAPL --timeframes 1h,4h,1d,1w
    cdcx-equity --source robinhood --symbol AAPL --timeframe 1d --execute --balance 10000
    cdcx-equity --source robinhood --symbol AAPL --timeframe 1d --structure-report
"""

from __future__ import annotations

import argparse
import sys

from . import risk
from . import trade_manager
from .config import settings

BUY_SIGNALS = {"STRONG BUY", "BUY"}
SELL_SIGNALS = {"STRONG SELL", "SELL"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cdcx-equity",
        description="CDCX AI Trade Analysis for equities/ETFs/indexes via Robinhood or Webull -- "
                     "same report format and scoring engine as cdcx-ai, different data source.",
    )
    parser.add_argument("--source", choices=["robinhood", "webull"], required=True, help="data source")
    parser.add_argument("--symbol", required=True, help="e.g. SPCX, AAPL, SPY")
    parser.add_argument(
        "--timeframe", default="1h",
        help="single timeframe: 1h, 4h, 1d, or 1w (default: 1h). Ignored if --timeframes is given.",
    )
    parser.add_argument(
        "--timeframes", default=None,
        help="comma-separated list, e.g. 1h,4h,1d,1w -- prints a report for each plus a summary table.",
    )
    parser.add_argument("--limit", type=int, default=settings.default_limit, help="number of bars to fetch")
    parser.add_argument(
        "--structure-report", action="store_true", dest="structure_report",
        help="Also print the market-structure/range picture (regime, POC/VAH/VAL, FVG, swing structure "
             "+ BOS) right after each timeframe's report. NOT the same thing as cli.py's --structure "
             "(the 1W/1D/4H/1H structural trigger system) -- this equity path has no multi-role "
             "structural-trigger system of its own; this is the simpler single-timeframe read.",
    )
    parser.add_argument(
        "--execute", action="store_true",
        help="If the entry timeframe's execution_signal is BUY/STRONG BUY/SELL/STRONG SELL (engine.py's "
             "own regime + R:R gate -- see module docstring for why this skips cli.py's separate "
             "confluence/checklist layer), size a position (1.5x ATR stop, 2%% account risk) and open it "
             "as a locally tracked PAPER trade. Uses the LAST timeframe in --timeframes, or --timeframe.",
    )
    parser.add_argument("--balance", type=float, default=None, help=f"default: {settings.default_account_balance}")
    parser.add_argument("--risk-pct", type=float, default=None, help=f"default: {settings.risk_pct_per_trade}")
    return parser


def _make_exchange(source: str):
    if source == "robinhood":
        from .exchange.robinhood_equity import RobinhoodEquityExchange

        return RobinhoodEquityExchange()
    from .exchange.webull_equity import WebullEquityExchange

    return WebullEquityExchange()


def _run_single(exchange, symbol: str, timeframe: str, limit: int):
    from . import engine

    try:
        data = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    except Exception as exc:
        print(f"Error fetching {symbol} @ {timeframe} from this source: {exc}", file=sys.stderr)
        return None
    try:
        return engine.analyze_ohlcv(symbol, data, timeframe=timeframe), data
    except Exception as exc:
        print(f"Error analyzing {symbol} @ {timeframe}: {exc}", file=sys.stderr)
        return None


def _print_structure(symbol: str, timeframe: str, data) -> None:
    from .structure_report import build_structure_report, format_structure_report

    try:
        report = build_structure_report(symbol, timeframe, data.highs, data.lows, data.closes, data.volumes)
    except Exception as exc:
        print(f"Error building structure report for {symbol} @ {timeframe}: {exc}", file=sys.stderr)
        return
    print(format_structure_report(report))


def _market_bias(signal) -> str:
    """Derived from the same `signal.signal` column shown next to it (not
    the separate unclamped direction_score) so a row never shows a Signal
    and a Market that visibly contradict each other."""
    if signal.signal in BUY_SIGNALS:
        return "bullish"
    if signal.signal in SELL_SIGNALS:
        return "bearish"
    return "neutral"


def _print_summary_table(symbol: str, results: dict[str, object]) -> None:
    bar = "=" * 85
    print(bar)
    print(f"MULTI-TIMEFRAME SUMMARY -- {symbol}".center(85))
    print(bar)
    print(f"{'Timeframe':<12}{'Score':<8}{'Signal':<14}{'Market':<10}{'ATR':<12}{'Range':<7}")
    print("-" * 85)
    for tf, signal in results.items():
        if signal is None:
            print(f"{tf:<12}{'--':<8}{'ERROR':<14}{'--':<10}{'--':<12}{'--':<7}")
        else:
            is_range = "yes" if signal.regime.regime == "ranging" else "no"
            # This engine.py (the crypto-path fork) has no standalone
            # atr_regime field on TradeSignal -- reuse the same ATR-expansion
            # label already shown in the per-timeframe indicator breakdown
            # ("Atr Expansion  +8  (Expansion)") rather than adding a new
            # calculation, so this can't drift from that row.
            atr_state = signal.labels.get("atr_expansion", "n/a").lower()
            print(
                f"{tf:<12}{signal.total_score:<8}{signal.signal:<14}"
                f"{_market_bias(signal):<10}{atr_state:<12}{is_range:<7}"
            )
    print(bar)


def _handle_execute(symbol: str, signal, balance: float, risk_pct: float) -> int:
    direction = "long" if signal.execution_signal in BUY_SIGNALS else "short" if signal.execution_signal in SELL_SIGNALS else None
    if direction is None:
        print(
            f"\nexecution_signal is '{signal.execution_signal}' -- not a BUY/SELL. No trade planned."
            + (f" ({signal.execution_reason})" if signal.execution_reason else ""),
        )
        return 0

    account_balance = balance if balance is not None else settings.default_account_balance
    effective_risk_pct = risk_pct if risk_pct is not None else settings.risk_pct_per_trade

    plan = risk.build_position_plan(
        symbol=symbol, direction=direction, entry_price=signal.entry, atr=signal.atr,
        account_balance=account_balance, risk_pct=effective_risk_pct,
    )
    print()
    print(risk.format_position_plan(plan))

    tp_levels = [signal.take_profits[f"TP{i}"] for i in range(1, 5)]
    trade, message = trade_manager.open_trade(
        symbol=symbol, direction=direction, entry_price=plan.entry_price, atr=plan.atr,
        stop_price=plan.stop_price, tp_levels=tp_levels, position_size=plan.position_size,
        risk_amount=plan.risk_amount, account_balance=plan.account_balance,
        confluence_timeframes=[signal.timeframe], confluence_score=int(signal.total_score),
    )
    print()
    print(message)
    if trade is not None:
        print(trade_manager.format_trade(trade))
        print(
            "\nNote: this is a locally tracked PAPER trade only -- no live order was placed. "
            "Run `cdcx-ai --update-trades` to check it (trade state is shared with the crypto CLI)."
        )

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        exchange = _make_exchange(args.source)
    except Exception as exc:
        print(f"Could not connect to {args.source}: {exc}", file=sys.stderr)
        return 1

    from . import engine

    if args.timeframes:
        timeframes = [tf.strip() for tf in args.timeframes.split(",") if tf.strip()]
        results = {}
        any_success = False
        for tf in timeframes:
            outcome = _run_single(exchange, args.symbol, tf, args.limit)
            signal = outcome[0] if outcome else None
            results[tf] = signal
            if signal is not None:
                any_success = True
                print(engine.format_report(signal))
                print()
                if args.structure_report:
                    _print_structure(args.symbol, tf, outcome[1])
                    print()
        _print_summary_table(args.symbol, results)

        if not any_success:
            return 1
        if args.execute:
            entry_signal = next(s for tf, s in reversed(list(results.items())) if s is not None)
            return _handle_execute(args.symbol, entry_signal, args.balance, args.risk_pct)
        return 0

    outcome = _run_single(exchange, args.symbol, args.timeframe, args.limit)
    if outcome is None:
        return 1
    signal, data = outcome
    print(engine.format_report(signal))

    if args.structure_report:
        print()
        _print_structure(args.symbol, args.timeframe, data)

    if args.execute:
        return _handle_execute(args.symbol, signal, args.balance, args.risk_pct)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
