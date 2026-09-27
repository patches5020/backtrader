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

No --live path exists here at all (no equity broker order-placement
exists in this project) -- --execute always opens a locally tracked PAPER
trade, on both paths below.

Two distinct --execute paths, chosen by which flag was given:

  --timeframe (single) --execute
      The ORIGINAL, simpler path: opens a paper trade straight off that one
      timeframe's own engine.py execution_signal (which already gates on
      regime + R:R -- see engine.py's "Execution signal" section). No
      confluence or checklist involved -- there's only one timeframe's data
      to use. See _handle_execute().

  --timeframes (plural, 2+) --execute
      Reuses cli.py's confluence.py + entry_checklist.py + entry_location.py
      pipeline UNCHANGED (same modules, same functions, not reimplemented)
      -- multi-timeframe majority-vote confluence, then a per-component
      entry checklist (trend/Fibonacci/FVG/Volume Profile/risk/position) on
      the confluence-selected entry timeframe, then entry_location.py's
      INVALID/DEVELOPING/CONFIRMED classification + the shared ENTRY
      LOCATION ASSESSMENT report. A trade only opens on CONFIRMED (checklist
      fully passed). This was deliberately NOT built when this module was
      first written (see below) -- built now as a direct, explicit request
      to give equities the same MTF rigor as crypto. See
      _handle_execute_confluence().

Because vp_setup.py (Volume Profile setup classification) and bos_state.py
(BOS retest/continuation state) live inside engine.py/structure_report.py
themselves, both already print here automatically (the "VP SETUP:" /
"BOS STATE:" lines under --structure-report) -- nothing equity-specific was
needed for those. mtf_context.py's ATR alignment + Volume Profile hierarchy
(cli.py section 15/FLOWCHART.md) are pure `dict[tf, TradeSignal] -> display`
functions with no confluence/checklist dependency, and were already wired
into --timeframes output before either --execute path below existed.

What's still crypto-only, on purpose, even after this: circuit_breaker.py,
no_trade_filter.py, no_trade_gate.py, journal.py's live-trading audit
trail, and confidence_scoring.py -- none of cli.py's live-order safety
layers exist here, because there is no live order path for equities to
protect. --execute here only ever opens a PAPER trade via
trade_manager.open_trade(), same as before this update.

Usage:
    cdcx-equity --source robinhood --symbol SPCX --timeframe 1h
    cdcx-equity --source webull --symbol AAPL --timeframes 1h,4h,1d,1w
    cdcx-equity --source robinhood --symbol AAPL --timeframe 1d --execute --balance 10000
    cdcx-equity --source robinhood --symbol AAPL --timeframes 1h,4h,1d,1w --execute --balance 10000
    cdcx-equity --source robinhood --symbol AAPL --timeframe 1d --structure-report
"""

from __future__ import annotations

import argparse
import sys

from .confluence import evaluate_confluence
from .entry_checklist import evaluate_entry_checklist, format_checklist
from . import entry_location
from . import mtf_context
from . import regime as regime_module
from . import risk
from . import trade_manager
from .config import settings

BUY_SIGNALS = {"STRONG BUY", "BUY"}
SELL_SIGNALS = {"STRONG SELL", "SELL"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cdcx-equity",
        description="CDCX AI Trade Analysis for equities/ETFs/indexes via Robinhood or Webull -- "
                     "same report format and scoring engine as cdcx-ai, different data source. "
                     "STOCKS/ETFS ONLY -- there is no crypto path here. A crypto shorthand like "
                     "XRP/BTC/ETH as --symbol may silently resolve to a same-ticker spot-crypto ETF "
                     "instead of erroring (e.g. NYSE Arca \"XRP\" = Bitwise XRP ETF, whose share price "
                     "is NOT 1:1 with spot XRP). For real crypto, use cdcx-ai with a pair symbol "
                     "like XRPUSD instead.",
    )
    parser.add_argument("--source", choices=["robinhood", "webull"], required=True, help="data source")
    parser.add_argument("--symbol", required=True, help="e.g. SPCX, AAPL, SPY -- stocks/ETFs only, see warning above")
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
        help="With a single --timeframe: opens a PAPER trade straight off that timeframe's own "
             "execution_signal (engine.py's regime + R:R gate). With 2+ --timeframes: runs the SAME "
             "confluence + entry-checklist + entry-location pipeline as cdcx-ai's --execute (see module "
             "docstring) and only opens a PAPER trade when entry location is CONFIRMED. No --live path "
             "either way -- always a locally tracked paper trade, 1.5x ATR stop, 2%% account risk.",
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


def _fvg_bias(signal) -> str:
    """bullish/bearish/neutral from the same fair_value_gap score already
    computed for this timeframe's own indicator breakdown. Same convention
    as cli.py's own _fvg_bias -- kept in sync deliberately."""
    score = signal.scores.get("fair_value_gap", 0.0)
    if score > 0:
        return "bullish"
    if score < 0:
        return "bearish"
    return "neutral"


def _ema_bias(signal) -> str:
    """bullish/bearish/neutral from the same ema_trend score already shown in
    this timeframe's own indicator breakdown ("Ema Trend") -- not a second,
    independently-derived EMA read. Same convention as cli.py's own
    _ema_bias -- kept in sync deliberately."""
    score = signal.scores.get("ema_trend", 0.0)
    if score > 0:
        return "bullish"
    if score < 0:
        return "bearish"
    return "neutral"


def _print_summary_table(symbol: str, results: dict[str, object]) -> None:
    bar = "=" * 113
    print(bar)
    print(f"MULTI-TIMEFRAME SUMMARY -- {symbol}".center(113))
    print(bar)
    print(
        f"{'Timeframe':<12}{'Score':<8}{'Signal':<14}{'Market':<10}"
        f"{'ADX(17)':<10}{'RSI(17)':<10}{'VOL(17)':<10}{'ATR':<12}{'Range':<7}{'FVG':<10}{'EMA':<10}"
    )
    print("-" * 113)
    for tf, signal in results.items():
        if signal is None:
            print(
                f"{tf:<12}{'--':<8}{'ERROR':<14}{'--':<10}"
                f"{'--':<10}{'--':<10}{'--':<10}{'--':<12}{'--':<7}{'--':<10}{'--':<10}"
            )
        else:
            is_range = "yes" if signal.regime.regime == "ranging" else "no"
            # This engine.py (the crypto-path fork) has no standalone
            # atr_regime field on TradeSignal -- reuse the same ATR-expansion
            # label already shown in the per-timeframe indicator breakdown
            # ("Atr Expansion  +8  (Expansion)") rather than adding a new
            # calculation, so this can't drift from that row.
            atr_state = signal.labels.get("atr_expansion", "n/a").lower()
            # ADX(17)/RSI(17)/VOL(17): same raw-reading convention as cli.py's
            # own _print_summary_table -- kept in sync deliberately.
            adx_str = f"{signal.adx_value:.1f}"
            rsi_str = f"{signal.rsi_value:.1f}"
            vol_str = f"{signal.volume_ratio:.1f}x"
            print(
                f"{tf:<12}{signal.total_score:<8}{signal.signal:<14}"
                f"{_market_bias(signal):<10}{adx_str:<10}{rsi_str:<10}{vol_str:<10}"
                f"{atr_state:<12}{is_range:<7}{_fvg_bias(signal):<10}{_ema_bias(signal):<10}"
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


def _handle_execute_confluence(
    symbol: str, results: dict[str, object], raw_data_by_tf: dict[str, object],
    balance: float, risk_pct: float,
) -> int:
    """The --timeframes (plural) --execute path -- reuses cli.py's
    confluence.py / entry_checklist.py / entry_location.py pipeline exactly
    as-is (same functions, not reimplemented), the same way _handle_execute
    above already reuses risk.py / trade_manager.py. `raw_data_by_tf` is the
    OHLCV already fetched for each timeframe by main()'s --timeframes loop
    -- reused here for the entry timeframe's regime recompute and BOS state,
    rather than an extra live refetch."""
    signals_by_tf = {
        tf: sig.signal for tf, sig in results.items()
        if sig is not None and sig.regime is not None and sig.regime.regime != "transitional"
    }
    if len(signals_by_tf) < 2:
        print(
            "Not enough tradeable timeframe reads to evaluate trend confluence "
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
        entry_location_state = entry_location.classify_entry_location(confluence, regime=None)
        print(entry_location.format_entry_location(entry_location_state))
        return 0

    entry_signal = results[confluence.entry_timeframe]
    direction = confluence.direction  # "long" | "short"
    raw_data = raw_data_by_tf.get(confluence.entry_timeframe)
    if raw_data is None:
        print(
            f"\nNo OHLCV retained for the confluence-selected entry timeframe ({confluence.entry_timeframe}) "
            "-- cannot recompute regime. No trade planned.",
            file=sys.stderr,
        )
        return 1

    # Same recomputation cli.py's own _handle_execute does: regime with the
    # real, now-known higher-timeframe alignment, not the False default used
    # when each timeframe was analyzed standalone in main()'s report loop.
    regime_result = regime_module.analyze(
        raw_data.highs, raw_data.lows, raw_data.closes, raw_data.volumes,
        higher_timeframes_aligned=True,
    )
    print()
    print(regime_module.format_regime(regime_result))

    # --- FVP shadow analysis (Phase 1, research only) ---------------------
    # INFORMATION ONLY -- same scope statement as cli.py's own hook: never
    # consulted by the checklist/confluence/regime gate or entry/SL/TP/risk
    # logic. Wrapped so a bug here can never interrupt the real decision flow.
    try:
        from .volume_profile.fvp_analysis import build_fvp_shadow_report, format_fvp_shadow
        fvp_report = build_fvp_shadow_report(
            raw_data.highs, raw_data.lows, raw_data.closes, raw_data.volumes,
            price=raw_data.closes[-1], timeframe=confluence.entry_timeframe,
        )
        print()
        print(format_fvp_shadow(fvp_report))
    except Exception as exc:
        print(f"\n[FVP shadow analysis skipped: {exc}]", file=sys.stderr)

    if regime_result.regime == "transitional":
        print("\nMarket Regime is TRANSITIONAL -- No Trade, regardless of confluence/checklist.")
        entry_location_state = entry_location.classify_entry_location(confluence, regime=regime_result.regime)
        print(entry_location.format_entry_location(entry_location_state))
        return 0

    account_balance = balance if balance is not None else settings.default_account_balance
    effective_risk_pct = risk_pct if risk_pct is not None else settings.risk_pct_per_trade

    from .indicators import atr_ema_variant1

    atr_series = atr_ema_variant1.calculate_atr(raw_data.highs, raw_data.lows, raw_data.closes)
    checklist = evaluate_entry_checklist(
        entry_signal, direction, risk_pct=effective_risk_pct, symbol=symbol, atr_series=atr_series,
    )
    print()
    print(format_checklist(checklist))

    entry_location_state = entry_location.classify_entry_location(confluence, regime="trending", checklist_result=checklist)
    print()
    print(entry_location.format_entry_location(entry_location_state))

    from . import bos_state as bos_state_module
    from .indicators import market_structure

    atr_alignment = mtf_context.build_atr_alignment(results)
    vp_hierarchy = mtf_context.build_vp_hierarchy(results)
    structure_result = market_structure.analyze(raw_data.highs, raw_data.lows, price=raw_data.closes[-1])
    bos_state_result = bos_state_module.classify_bos_state(
        structure_result, raw_data.highs, raw_data.lows, raw_data.closes, raw_data.volumes,
    )
    print()
    print(entry_location.format_entry_assessment(
        direction, confluence, "trending", atr_alignment, vp_hierarchy,
        checklist, entry_signal, bos_state_result, entry_location_state,
    ))

    if not checklist.all_passed:
        print("\nEntry checklist not fully satisfied -- no trade planned.")
        return 0

    # CONFIRMED -- open the paper trade, same sizing/tracking _handle_execute
    # above already uses (no --live path here either).
    plan = risk.build_position_plan(
        symbol=symbol, direction=direction, entry_price=entry_signal.entry, atr=entry_signal.atr,
        account_balance=account_balance, risk_pct=effective_risk_pct,
    )
    print()
    print(risk.format_position_plan(plan))

    tp_levels = [entry_signal.take_profits[f"TP{i}"] for i in range(1, 5)]
    trade, message = trade_manager.open_trade(
        symbol=symbol, direction=direction, entry_price=plan.entry_price, atr=plan.atr,
        stop_price=plan.stop_price, tp_levels=tp_levels, position_size=plan.position_size,
        risk_amount=plan.risk_amount, account_balance=plan.account_balance,
        confluence_timeframes=confluence.agreeing_timeframes, confluence_score=confluence.confidence_pct,
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
        raw_data_by_tf = {}
        any_success = False
        for tf in timeframes:
            outcome = _run_single(exchange, args.symbol, tf, args.limit)
            signal = outcome[0] if outcome else None
            results[tf] = signal
            if signal is not None:
                any_success = True
                raw_data_by_tf[tf] = outcome[1]
                print(engine.format_report(signal))
                print()
                if args.structure_report:
                    _print_structure(args.symbol, tf, outcome[1])
                    print()
        _print_summary_table(args.symbol, results)
        print()
        print(mtf_context.format_atr_alignment(mtf_context.build_atr_alignment(results)))
        print(mtf_context.format_vp_hierarchy(mtf_context.build_vp_hierarchy(results)))
        if args.structure_report and raw_data_by_tf:
            # Advisory-only VP-BOS (vp_bos.py) -- same section as cdcx-ai's
            # --structure, from the series already fetched above.
            from . import vp_bos
            print()
            print(vp_bos.format_vp_bos_section(args.symbol, vp_bos.build_vp_bos_by_tf(raw_data_by_tf)))

        if not any_success:
            return 1
        if args.execute:
            # 2+ timeframes -> the confluence-gated pipeline (see module
            # docstring); a single successfully-analyzed timeframe can't
            # form confluence, so it falls back to the direct single-signal
            # path the same way it always has.
            if len(timeframes) >= 2:
                return _handle_execute_confluence(args.symbol, results, raw_data_by_tf, args.balance, args.risk_pct)
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
