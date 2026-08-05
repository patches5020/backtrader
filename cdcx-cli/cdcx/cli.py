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
from . import regime as regime_module
from . import ranging_strategy
from . import no_trade_filter
from . import confidence_scoring
from .indicators import candlestick_patterns
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
             "Trending --execute needs 2+ tradeable timeframes; range mode can execute "
             "from the fastest available ranging timeframe without trend confluence.",
    )
    parser.add_argument("--limit", type=int, default=settings.default_limit, help="number of candles to fetch")

    parser.add_argument(
        "--execute", action="store_true",
        help="For trending markets, check multi-timeframe confluence (2+ tradeable "
             "timeframes required); for a validated ranging entry timeframe, use the "
             "dedicated range-boundary strategy without trend confluence. Compute a sized "
             "trade plan (1.5x ATR stop, 2%% account risk) and open it as a locally "
             "tracked PAPER trade by default. Add --live to also offer sending the real "
             "bracket order via the separately-installed `cdcx` exchange CLI.",
    )
    parser.add_argument(
        "--live", action="store_true",
        help="DANGER: after a paper trade would be opened, also build the real "
             "entry+stop+TP1 bracket order (via `cdcx advanced create-otoco`), show "
             "a --dry-run preview, and ask for explicit interactive confirmation "
             "before sending anything real. Never auto-sends. Requires --execute. "
             "Only covers the first bracket -- TP2-TP4 trailing needs manual "
             "follow-up (see README).",
    )
    parser.add_argument(
        "--instrument-name", default=None,
        help="Override the derived exchange instrument name for --live (e.g. "
             "BTCUSD-PERP). Without this, it's guessed from --symbol as "
             "'{BASE}USD-PERP' -- verified correct for BTC/USDT, not confirmed "
             "for every pair. Always shown for review before anything is sent.",
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
        "--news-imminent", action="store_true",
        help="Manually flag that major scheduled news is imminent -- this project has no "
             "news/economic-calendar feed, so the no-trade filter can't detect this on its "
             "own. Pass this yourself when you know the calendar; it forces a No Trade.",
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
    parser.add_argument(
        "--backtrader", action="store_true",
        help="Backtest via this repository's own backtrader Cerebro engine "
             "(CDCXSignalStrategy: bracket-order entry/stop/TP1, backtrader's own "
             "broker/commission model) instead of the standalone paper trade-manager "
             "simulation in `python -m cdcx.backtest`. Uses --symbol, --timeframe, "
             "--limit, --balance, --risk-pct.",
    )
    parser.add_argument(
        "--synthetic", action="store_true",
        help="With --backtrader: use synthetic multi-regime OHLCV instead of fetching "
             "real candles (no network/API keys needed).",
    )
    parser.add_argument(
        "--commission", type=float, default=0.001,
        help="Backtrader broker commission rate for --backtrader (default: 0.001 = 10 bps).",
    )
    parser.add_argument(
        "--plot", action="store_true",
        help="With --backtrader: show a backtrader plot after the run.",
    )
    return parser


def _handle_backtrader(args: argparse.Namespace) -> int:
    from .backtrader_runner import fetch_ohlcv, format_summary, run_backtrader_backtest

    timeframe = args.timeframe or settings.default_timeframe

    if args.synthetic:
        from .backtest.synthetic import generate_ohlcv

        data = generate_ohlcv(n_bars=max(args.limit, 800), start_price=50_000.0, seed=42, timeframe=timeframe)
    else:
        try:
            data = fetch_ohlcv(args.symbol, timeframe, args.limit)
        except Exception as exc:
            print(f"Error fetching candles for {args.symbol} @ {timeframe}: {exc}", file=sys.stderr)
            return 1

    if not data.closes:
        print(f"No candle data returned for {args.symbol} ({timeframe})", file=sys.stderr)
        return 1

    summary = run_backtrader_backtest(
        data,
        symbol=args.symbol,
        timeframe=timeframe,
        cash=args.balance or settings.default_account_balance,
        commission=args.commission,
        risk_pct=args.risk_pct,
        plot=args.plot,
    )
    print(format_summary(summary))
    return 0


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


def _handle_execute(
    symbol: str, balance: float, risk_pct: float, results: dict[str, object], limit: int,
    live: bool = False, instrument_name_override: str = None, news_imminent: bool = False,
) -> int:
    # A standalone timeframe marked TRANSITIONAL is diagnostic, not an
    # executable directional confirmation. Exclude those raw signals from
    # trend confluence so a higher-timeframe "NO TRADE" cannot silently
    # contribute bearish/bullish weight. The entry timeframe regime is
    # recomputed below with higher-timeframe alignment once confluence is known.
    signals_by_tf = {
        tf: sig.signal
        for tf, sig in results.items()
        if sig is not None and sig.regime.regime != "transitional"
    }

    # Range mode is intentionally independent of multi-timeframe trend
    # confluence. If the fastest available execution timeframe is already a
    # validated range, evaluate the dedicated range-boundary setup directly.
    allowed = ["1h", "4h", "1d", "1w"]
    available_tfs = [tf for tf in allowed if results.get(tf) is not None]
    if available_tfs:
        range_tf = available_tfs[0]
        range_signal = results[range_tf]
        if range_signal.regime.regime == "ranging":
            from .exchange.cryptocom import CryptoComExchange
            from .indicators import atr_ema_variant1, adx as adx_module, rsi as rsi_module, volume_profile_fixed

            account_balance = balance if balance is not None else settings.default_account_balance
            effective_risk_pct = risk_pct if risk_pct is not None else settings.risk_pct_per_trade
            exchange = CryptoComExchange(settings.cryptocom_api_key, settings.cryptocom_api_secret)
            raw_data = exchange.fetch_ohlcv(symbol, timeframe=range_tf, limit=limit)
            atr_series = atr_ema_variant1.calculate_atr(raw_data.highs, raw_data.lows, raw_data.closes)
            adx_series, _, _ = adx_module.calculate_adx(raw_data.highs, raw_data.lows, raw_data.closes)
            rsi_series = rsi_module.calculate_rsi(raw_data.closes)
            vp_result = volume_profile_fixed.analyze(raw_data.highs, raw_data.lows, raw_data.volumes, price=raw_data.closes[-1])
            pattern_matches = candlestick_patterns.detect_patterns(raw_data.highs, raw_data.lows, raw_data.opens, raw_data.closes)
            print()
            print("RANGE MODE: multi-timeframe trend confluence is not required.")
            return _handle_ranging_path(
                symbol, range_signal, account_balance, effective_risk_pct,
                rsi_series, vp_result, pattern_matches, atr_series, adx_series[-1], news_imminent,
                live, instrument_name_override,
            )

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
        return 0

    entry_signal = results[confluence.entry_timeframe]
    direction = confluence.direction  # "long" | "short"
    account_balance = balance if balance is not None else settings.default_account_balance
    effective_risk_pct = risk_pct if risk_pct is not None else settings.risk_pct_per_trade

    # --- Step 1: Market Regime (recomputed here with the real, now-known
    # higher-timeframe alignment, rather than the False default used when
    # each timeframe was analyzed standalone in the report loop above) ---
    from .exchange.cryptocom import CryptoComExchange
    from .indicators import atr_ema_variant1, adx as adx_module, rsi as rsi_module, volume_profile_fixed

    exchange = CryptoComExchange(settings.cryptocom_api_key, settings.cryptocom_api_secret)
    raw_data = exchange.fetch_ohlcv(symbol, timeframe=confluence.entry_timeframe, limit=limit)

    regime_result = regime_module.analyze(
        raw_data.highs, raw_data.lows, raw_data.closes, raw_data.volumes,
        higher_timeframes_aligned=True,  # confluence.should_execute already guaranteed above
    )
    print()
    print(regime_module.format_regime(regime_result))

    if regime_result.regime == "transitional":
        print("\nMarket Regime is TRANSITIONAL -- No Trade, regardless of confluence/checklist.")
        return 0

    # Shared raw data needed by the no-trade filter and (for ranging) the
    # strategy setup itself -- computed once here rather than re-derived
    # from TradeSignal's already-summarized scores.
    atr_series = atr_ema_variant1.calculate_atr(raw_data.highs, raw_data.lows, raw_data.closes)
    adx_series, _, _ = adx_module.calculate_adx(raw_data.highs, raw_data.lows, raw_data.closes)
    adx_value = adx_series[-1]

    if regime_result.regime == "trending":
        return _handle_trending_path(
            symbol, direction, entry_signal, account_balance, effective_risk_pct,
            signals_by_tf, confluence, atr_series, adx_value, news_imminent,
            live, instrument_name_override,
        )

    # regime_result.regime == "ranging"
    rsi_series = rsi_module.calculate_rsi(raw_data.closes)
    vp_result = volume_profile_fixed.analyze(raw_data.highs, raw_data.lows, raw_data.volumes, price=raw_data.closes[-1])
    pattern_matches = candlestick_patterns.detect_patterns(raw_data.highs, raw_data.lows, raw_data.opens, raw_data.closes)

    return _handle_ranging_path(
        symbol, entry_signal, account_balance, effective_risk_pct,
        rsi_series, vp_result, pattern_matches, atr_series, adx_value, news_imminent,
        live, instrument_name_override,
    )


def _handle_trending_path(
    symbol, direction, entry_signal, account_balance, effective_risk_pct,
    signals_by_tf, confluence, atr_series, adx_value, news_imminent,
    live, instrument_name_override,
) -> int:
    checklist = evaluate_entry_checklist(entry_signal, direction, risk_pct=effective_risk_pct, symbol=symbol)
    print()
    print(format_checklist(checklist))

    if not checklist.all_passed:
        print("\nEntry checklist not fully satisfied -- no trade planned.")
        return 0

    # "Avoid entering after an extended move" -- bollinger_bands.py already
    # labels this exact condition ("... (Extended)") when price is stretched
    # beyond the band, so reuse that instead of re-deriving %B here.
    bb_label = entry_signal.labels.get("bollinger_bands", "")
    if "Extended" in bb_label:
        print(f"\nOverextension guard tripped: Bollinger Bands reads '{bb_label}'.")
        print("Avoiding entry after an extended move -- no trade planned. Wait for a pullback.")
        return 0

    plan = risk.build_position_plan(
        symbol=symbol, direction=direction, entry_price=entry_signal.entry, atr=entry_signal.atr,
        account_balance=account_balance, risk_pct=effective_risk_pct,
    )
    tp_levels = [entry_signal.take_profits[f"TP{i}"] for i in range(1, 5)]

    nt_result = no_trade_filter.check_no_trade_filter(
        adx_value=adx_value,
        higher_timeframes_agree=True,  # confluence.should_execute already guaranteed this
        price_in_middle_of_range=False,  # not meaningful on the trending path
        risk_reward_ratio=abs(tp_levels[0] - plan.entry_price) / abs(plan.entry_price - plan.stop_price),
        atr_unusually_low=no_trade_filter.is_atr_unusually_low(atr_series),
        news_imminent=news_imminent,
    )
    print()
    print(no_trade_filter.format_no_trade_filter(nt_result))
    if nt_result.blocked:
        print("\nNo-trade filter blocked this setup -- no trade planned.")
        return 0

    confidence_result = confidence_scoring.calculate_weighted_confidence(signals_by_tf, direction, entry_signal)
    print()
    print(confidence_scoring.format_weighted_confidence(confidence_result))

    print()
    print(risk.format_position_plan(plan))

    return _open_trade_and_maybe_go_live(
        symbol, direction, plan, tp_levels, confluence.agreeing_timeframes, confluence.confluence_score,
        live, instrument_name_override,
    )


def _handle_ranging_path(
    symbol, entry_signal, account_balance, effective_risk_pct,
    rsi_series, vp_result, pattern_matches, atr_series, adx_value, news_imminent,
    live, instrument_name_override,
) -> int:
    setup = ranging_strategy.evaluate_ranging_setup(
        price=entry_signal.entry, rsi_series=rsi_series, poc=vp_result.poc,
        vah=vp_result.vah, val=vp_result.val, pattern_matches=pattern_matches,
    )
    print()
    print(ranging_strategy.format_ranging_setup(setup))

    if not setup.valid:
        print("\nNo qualifying ranging setup -- no trade planned.")
        return 0

    direction = setup.direction
    plan = risk.build_position_plan(
        symbol=symbol, direction=direction, entry_price=entry_signal.entry, atr=entry_signal.atr,
        account_balance=account_balance, risk_pct=effective_risk_pct,
    )
    # Ranging targets replace the ATR-extension Fibonacci ladder: TP1 = POC, TP2 = opposite range edge.
    tp_levels = [setup.tp1, setup.tp2]

    # The ranging path doesn't require multi-timeframe agreement (per spec),
    # so higher_timeframes_agree is deliberately not part of its no-trade
    # check -- a qualifying setup already means price is AT a boundary, not
    # in the middle of the range, by construction.
    nt_result = no_trade_filter.check_no_trade_filter(
        adx_value=adx_value,
        higher_timeframes_agree=True,
        price_in_middle_of_range=False,
        risk_reward_ratio=abs(tp_levels[0] - plan.entry_price) / abs(plan.entry_price - plan.stop_price),
        atr_unusually_low=no_trade_filter.is_atr_unusually_low(atr_series),
        news_imminent=news_imminent,
    )
    print()
    print(no_trade_filter.format_no_trade_filter(nt_result))
    if nt_result.blocked:
        print("\nNo-trade filter blocked this setup -- no trade planned.")
        return 0

    print()
    print(risk.format_position_plan(plan))

    return _open_trade_and_maybe_go_live(
        symbol, direction, plan, tp_levels, [], 0, live, instrument_name_override,
    )


def _open_trade_and_maybe_go_live(
    symbol, direction, plan, tp_levels, confluence_timeframes, confluence_score,
    live, instrument_name_override,
) -> int:
    trade, message = trade_manager.open_trade(
        symbol=symbol, direction=direction, entry_price=plan.entry_price, atr=plan.atr,
        stop_price=plan.stop_price, tp_levels=tp_levels, position_size=plan.position_size,
        risk_amount=plan.risk_amount, account_balance=plan.account_balance,
        confluence_timeframes=confluence_timeframes, confluence_score=confluence_score,
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
        if live:
            _handle_live_order(symbol, direction, plan, tp_levels[0], instrument_name_override)

    return 0


def _handle_live_order(symbol, direction, plan, tp1_price, instrument_name_override) -> None:
    from . import live_execution

    instrument_name = instrument_name_override or live_execution.derive_instrument_name(symbol)
    order_list = live_execution.build_otoco_order_list(
        instrument_name=instrument_name,
        direction=direction,
        quantity=plan.position_size,
        stop_price=plan.stop_price,
        take_profit_price=tp1_price,
    )

    print()
    print("Checking `cdcx` (the real exchange CLI) is reachable and previewing the order (--dry-run)...")
    try:
        result = live_execution.preview_bracket(order_list)
    except FileNotFoundError:
        print(
            "\nCould not find the `cdcx` binary on PATH -- install/verify the real "
            "Crypto.com Exchange CLI first. No order was attempted.",
            file=sys.stderr,
        )
        return

    print(live_execution.format_bracket_preview(instrument_name, order_list, result))

    if result.dry_run_returncode != 0:
        print(
            "\nThe dry-run itself did not return success -- fix the issue above "
            "before proceeding. Nothing was sent.",
            file=sys.stderr,
        )
        return

    print(
        "\nThis is your last chance to stop. Type exactly YES (all caps) to send "
        "this REAL order to the exchange, or anything else to cancel:"
    )
    try:
        confirmation = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        confirmation = ""

    if confirmation != "YES":
        print("Not confirmed -- no live order sent.")
        return

    print("\nSending live order...")
    result = live_execution.send_bracket_live(result)
    print(f"Command: {' '.join(result.live_command)}")
    print(result.live_stdout or "(empty stdout)")
    if result.live_stderr:
        print("stderr:", result.live_stderr)
    print(f"Exit code: {result.live_returncode}")
    if result.live_returncode == 0:
        print(
            "\nLive bracket order sent. This covers entry + stop-loss + TP1 only. "
            "Once TP1 fills, you'll need to place a follow-up bracket manually to "
            "trail the stop through TP2-TP4 (not automated yet)."
        )
    else:
        print("\nThe live order may not have gone through cleanly -- check your exchange account directly.")


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

    if args.live and not args.execute:
        print("--live requires --execute (and --timeframes with 2+ of 1h/4h/1d/1w).", file=sys.stderr)
        return 1

    if args.list_trades:
        return _handle_list_trades()

    if args.update_trades:
        return _handle_update_trades()

    if args.backtrader:
        return _handle_backtrader(args)

    from . import engine  # deferred: requires ccxt, not needed for the branches above

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
            return _handle_execute(
                args.symbol, args.balance, args.risk_pct, results, args.limit,
                live=args.live, instrument_name_override=args.instrument_name,
                news_imminent=args.news_imminent,
            )

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
