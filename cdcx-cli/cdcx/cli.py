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
from . import journal
from . import paper_approval
from . import circuit_breaker
from .confluence import evaluate_confluence
from .entry_checklist import evaluate_entry_checklist, format_checklist
from . import regime as regime_module
from . import ranging_strategy
from . import no_trade_filter
from . import confidence_scoring
from . import structure_levels
from . import structure_strategy
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
        "--confirmed-no-withdraw-permission", action="store_true",
        help="Required for --live to proceed past the final no-trade gate "
             "(cdcx/no_trade_gate.py). This project cannot query Crypto.com API key "
             "permissions automatically -- pass this only after manually confirming, "
             "in your Crypto.com account's API-key settings, that the key used here "
             "does NOT have withdrawal permission enabled. Without it, --live is "
             "refused at the final gate, fail-closed, every time.",
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
        "--atr-multiplier", type=float, default=None,
        help="Override the ATR stop-loss multiplier for this run, for any symbol -- "
             f"always wins over the per-symbol table below. Default resolution (see "
             f"cdcx/risk.py's resolve_atr_multiplier): per-symbol override from "
             f"ATR_MULTIPLIER_OVERRIDES in .env (ships with '{settings.atr_multiplier_overrides}', "
             f"backtested empirically), else {settings.atr_stop_multiplier} (ATR_STOP_MULTIPLIER).",
    )
    parser.add_argument(
        "--tp-ratios", type=str, default=None,
        help="Override TP1-4 R-multiples of stop_distance for this run, e.g. '2,3,4,5' -- "
             f"selectable at input, not hardcoded (default: TP_RATIOS in .env, "
             f"currently '{settings.tp_ratios}'). See cdcx/risk.py's resolve_tp_ratios.",
    )
    parser.add_argument(
        "--tp-mode", type=str, default=None, choices=["atr", "structural"],
        help="How TP1-4 are computed: 'atr' (default -- fixed R-multiples of stop_distance, "
             "see --tp-ratios) or 'structural' (nearest real resistance/support -- volume-profile "
             f"VAH/VAL/HVN/LVN, a Fibonacci extension rung, a swing high/low, or an active FVG edge; "
             "any rung without a real candidate falls back to its ATR level). Default: TP_MODE in "
             f".env, currently '{settings.tp_mode}'. See cdcx/risk.py's build_structural_tp_levels.",
    )
    parser.add_argument(
        "--tp-close-pcts", type=str, default=None,
        help="Override what %% of the ORIGINAL position size closes at each of TP1-4, e.g. "
             f"'50,25,25,0' -- selectable at input (default: TP_CLOSE_PCTS in .env, currently "
             f"'{settings.tp_close_pcts}'). TP4 always closes 100%% of whatever remains "
             "regardless of its own configured share. See trade_manager.py's partial-close rules.",
    )
    parser.add_argument(
        "--max-consecutive-losses", type=int, default=None,
        help="Circuit breaker (cdcx/circuit_breaker.py): pause new entries for this symbol "
             f"after this many closed losing trades in a row (default: "
             f"{circuit_breaker.DEFAULT_MAX_CONSECUTIVE_LOSSES}). Pass 0 to disable this trigger.",
    )
    parser.add_argument(
        "--max-drawdown-pct", type=float, default=None,
        help="Circuit breaker: pause new entries once this symbol's realized equity has drawn "
             f"down more than this %% from its running peak (default: "
             f"{circuit_breaker.DEFAULT_MAX_DRAWDOWN_PCT}). Pass 0 to disable this trigger.",
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
        "--record-live-close", action="store_true",
        help="Manually record the realized outcome of a CLOSED live position into "
             "trading/live/results/ (see cdcx/journal.py) -- nothing in this project "
             "polls the exchange for fills/closes automatically, so this has to be "
             "supplied by you. Feeds --export-tax. Requires --symbol, --direction, "
             "--quantity, --entry-price, --exit-price, --opened-at, --closed-at.",
    )
    parser.add_argument(
        "--direction", choices=["long", "short"], default=None,
        help="Position direction, for --record-live-close.",
    )
    parser.add_argument(
        "--quantity", type=float, default=None, help="Position size, for --record-live-close.",
    )
    parser.add_argument(
        "--entry-price", type=float, default=None, help="Fill price at open, for --record-live-close.",
    )
    parser.add_argument(
        "--exit-price", type=float, default=None, help="Fill price at close, for --record-live-close.",
    )
    parser.add_argument(
        "--opened-at", default=None,
        help="Date/time the position was opened, e.g. 2026-08-01 or 2026-08-01T14:30:00 "
             "(UTC). For --record-live-close.",
    )
    parser.add_argument(
        "--closed-at", default=None,
        help="Date/time the position was closed, same format as --opened-at. "
             "For --record-live-close.",
    )
    parser.add_argument(
        "--fees", type=float, default=0.0, help="Total fees paid on the round trip, for --record-live-close.",
    )
    parser.add_argument(
        "--notes", default="", help="Free-text notes to attach, for --record-live-close.",
    )
    parser.add_argument(
        "--export-tax", action="store_true",
        help="Read every closed live trade from trading/live/results/ (written by "
             "--record-live-close) and write a Form-8949-style CSV, a Schedule D "
             "short/long-term summary, a CPA summary report, and an SSA documentary "
             "activity record into trading/tax_records/ and trading/ssa_records/. "
             "NOT tax or legal advice -- have a CPA review every export.",
    )
    parser.add_argument(
        "--backtrader", action="store_true",
        help="Backtest via this repository's own backtrader Cerebro engine "
             "(CDCXSignalStrategy: bracket-order entry/stop/TP1, backtrader's own "
             "broker/commission model) instead of the standalone paper trade-manager "
             "simulation in `python -m cdcx.backtest`. Uses --symbol, --timeframe, "
             "--limit, --balance, --risk-pct, --bt-leverage.",
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
        "--bt-leverage", type=float, default=10.0,
        help="Backtrader broker leverage for --backtrader (default: 10.0). Position "
             "sizing is risk-based (like a real leveraged perp account), so a cash-only "
             "broker (1.0) will silently margin-reject most sized orders -- especially on "
             "tight-stop timeframes like 1h/4h -- showing 0 trades instead of the real "
             "signal flow. Does not reflect this exchange's actual per-symbol leverage "
             "limits (see --leverage); it's purely a backtest-broker setting.",
    )
    parser.add_argument(
        "--plot", action="store_true",
        help="With --backtrader: show a backtrader plot after the run.",
    )
    parser.add_argument(
        "--structure", action="store_true",
        help="Merge the POC/FVG/volume structure system into the same run's report: "
             "any requested timeframe that is one of 1w/1d/4h/1h gets its structure "
             "block (POC/resistance/support/condition) printed right after that "
             "timeframe's own indicator report, and a final 1W (major structure) / "
             "1D (major volume structure) / 4H (primary setup) / 1H (entry "
             "confirmation) LONG/SHORT trigger evaluation is appended at the end -- "
             "fetching whichever of those four roles wasn't already covered by "
             "--timeframe/--timeframes.",
    )
    parser.add_argument(
        "--predictions", metavar="KIND", nargs="?", const="__all__", default=None,
        help="Query the public Crypto.com Predictions Market Data API "
             "(data-api.crypto.com) for prediction-market events -- sports, crypto "
             "price-threshold, and other binary-outcome markets. No API key needed "
             "for anonymous read-only access (Crypto.com rate-limits it to 100 "
             "req/min / 50,000 req/day per IP). Pass a category to filter, e.g. "
             "--predictions NFL, or bare --predictions for all kinds. Independent "
             "of --symbol/--timeframe -- this queries prediction markets, not OHLCV "
             "candles.",
    )
    parser.add_argument(
        "--predictions-search", metavar="QUERY", default=None,
        help="Full-text search prediction-market events, "
             "e.g. --predictions-search 'super bowl'.",
    )
    parser.add_argument(
        "--predictions-contract", metavar="TICKER", default=None,
        help="Real-time pricing for one prediction contract. TICKER must be a real "
             "contract `symbol` copied from --predictions/--predictions-search output "
             "(e.g. NFL-00002-260813-M-Packers-011_270301-2300_1_PM.NPO) -- short "
             "asset-style codes like BTC-YES are not real tickers and 404. A YES "
             "share's price is the market's implied probability of that outcome "
             "(0.63 ~= 63%%).",
    )
    parser.add_argument(
        "--predictions-limit", type=int, default=20,
        help="Max events returned by --predictions / --predictions-search (default: 20).",
    )
    parser.add_argument(
        "--leverage", action="store_true",
        help="Look up the exchange's real min/max leverage for --symbol's USD-margined "
             "perpetual (e.g. BTC/USDT -> BTCUSD-PERP) and exit. Useful before --live, "
             "since this tool never sets leverage itself -- see live_execution.py.",
    )
    return parser


# The four timeframe roles the structural setup system is built around (see
# structure_strategy.py). Keyed by the same lowercase strings --timeframe/
# --timeframes already use, so a requested timeframe that happens to be one
# of these gets its structure block merged right into that timeframe's own
# report, instead of the two systems only ever appearing in separate sections.
_STRUCTURE_ROLES = {
    "1w": "major structure",
    "1d": "major volume structure",
    "4h": "primary setup",
    "1h": "entry confirmation",
}


def _fetch_structure_map(symbol: str, timeframe: str, limit: int):
    """Fetch OHLCV for one timeframe and return (StructureMap, raw OHLCV data).
    Returns (None, None), after printing the error, on a fetch failure."""
    from .exchange.cryptocom import CryptoComExchange

    exchange = CryptoComExchange(settings.cryptocom_api_key, settings.cryptocom_api_secret)
    try:
        data = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    except Exception as exc:
        print(f"Error fetching candles for structure analysis of {symbol} @ {timeframe}: {exc}", file=sys.stderr)
        return None, None

    smap = structure_levels.compute_structure_map(data.highs, data.lows, data.closes, data.volumes)
    return smap, data


def _print_merged_structure_block(symbol: str, timeframe: str, limit: int, cache: dict) -> None:
    """If `timeframe` is one of the four structural roles (1W/1D/4H/1H), fetch
    and print its STRUCTURE block immediately after that timeframe's own
    indicator report -- one merged block per timeframe, rather than a
    separate section for the whole structure system. Populates `cache` so
    `_print_structure_setup_section` below can reuse this fetch instead of
    hitting the exchange again for the same timeframe."""
    role = _STRUCTURE_ROLES.get(timeframe)
    if role is None:
        return

    smap, data = _fetch_structure_map(symbol, timeframe, limit)
    if smap is None:
        return

    cache[timeframe] = (smap, data)
    print()
    print(structure_levels.format_structure_map(f"{timeframe.upper()} ({role})", smap))


def _print_structure_setup_section(symbol: str, limit: int, cache: dict) -> bool:
    """Print the combined 1W/1D/4H/1H LONG/SHORT trigger evaluation, reusing
    whatever per-timeframe structure data the report loop already fetched
    (via `_print_merged_structure_block`) and only fetching what's still
    missing -- e.g. when --structure is used with a --timeframe/--timeframes
    set that doesn't already cover all four roles. Returns True on success,
    False (after printing the error) if any required timeframe couldn't be
    fetched."""
    for tf in ("1w", "1d", "4h", "1h"):
        if tf not in cache:
            smap, data = _fetch_structure_map(symbol, tf, limit)
            if smap is None:
                return False
            cache[tf] = (smap, data)

    w1_map, _ = cache["1w"]
    d1_map, _ = cache["1d"]
    h4_map, h4_data = cache["4h"]
    _, h1_data = cache["1h"]

    setup = structure_strategy.evaluate_structure_setup(
        w1_map, d1_map, h4_map,
        h4_data.highs, h4_data.lows, h4_data.closes, h4_data.volumes,
        h1_data.highs, h1_data.lows, h1_data.opens, h1_data.closes,
    )
    print()
    print(structure_strategy.format_structure_setup(setup))

    # Advisory-only A+ grade (setup_grade.py) -- labels setup quality for
    # this printed report; never consulted by no_trade_gate.py. Best-effort:
    # any failure here (e.g. too few bars for a fresh ATR read) just skips
    # this section rather than breaking the structure-setup report above it.
    try:
        from . import setup_grade as setup_grade_module
        from .indicators import atr_state as atr_state_module

        atr_transition = atr_state_module.analyze(h4_data.highs, h4_data.lows, h4_data.closes)
        print()
        print(setup_grade_module.format_setup_grade(setup_grade_module.grade_setup(setup, atr_transition)))
    except Exception as exc:
        print(f"(setup grade unavailable: {exc})", file=sys.stderr)

    return True


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
        leverage=args.bt_leverage,
        risk_pct=args.risk_pct,
        plot=args.plot,
    )
    print(format_summary(summary))
    return 0


def _run_single(
    symbol: str, timeframe: str, limit: int,
    atr_multiplier_override: float = None, tp_ratios_override: str = None, tp_mode_override: str = None,
):
    """Run analysis for one timeframe. Returns the TradeSignal, or None on error
    (after printing the error to stderr)."""
    from . import engine  # deferred: requires ccxt, not needed for trade-listing commands

    try:
        return engine.analyze(
            symbol=symbol, timeframe=timeframe, limit=limit,
            atr_multiplier_override=atr_multiplier_override, tp_ratios_override=tp_ratios_override,
            tp_mode_override=tp_mode_override,
        )
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
    max_consecutive_losses: int = None, max_drawdown_pct: float = None,
    atr_multiplier_override: float = None, tp_ratios_override: str = None, tp_close_pcts_override: str = None,
    confirmed_no_withdraw_permission: bool = False,
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

            journal.write_signal(symbol, range_tf, range_signal)
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
                max_consecutive_losses=max_consecutive_losses, max_drawdown_pct=max_drawdown_pct,
                atr_multiplier_override=atr_multiplier_override, tp_close_pcts_override=tp_close_pcts_override,
                confirmed_no_withdraw_permission=confirmed_no_withdraw_permission,
            )

    if len(signals_by_tf) < 2:
        reason = (
            "Not enough tradeable timeframe reads to evaluate trend confluence "
            f"(got {len(signals_by_tf)}, need at least 2 of 1h/4h/1d/1w)."
        )
        print(f"{reason} No trade planned.", file=sys.stderr)
        journal.write_rejected(symbol, "confluence", reason)
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
        journal.write_rejected(symbol, "confluence", confluence.label, confluence)
        return 0

    entry_signal = results[confluence.entry_timeframe]
    journal.write_signal(symbol, confluence.entry_timeframe, entry_signal)
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
        journal.write_rejected(symbol, "regime", "transitional", regime_result)
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
            max_consecutive_losses=max_consecutive_losses, max_drawdown_pct=max_drawdown_pct,
            atr_multiplier_override=atr_multiplier_override, tp_close_pcts_override=tp_close_pcts_override,
            confirmed_no_withdraw_permission=confirmed_no_withdraw_permission,
        )

    # regime_result.regime == "ranging"
    rsi_series = rsi_module.calculate_rsi(raw_data.closes)
    vp_result = volume_profile_fixed.analyze(raw_data.highs, raw_data.lows, raw_data.volumes, price=raw_data.closes[-1])
    pattern_matches = candlestick_patterns.detect_patterns(raw_data.highs, raw_data.lows, raw_data.opens, raw_data.closes)

    return _handle_ranging_path(
        symbol, entry_signal, account_balance, effective_risk_pct,
        rsi_series, vp_result, pattern_matches, atr_series, adx_value, news_imminent,
        live, instrument_name_override,
        max_consecutive_losses=max_consecutive_losses, max_drawdown_pct=max_drawdown_pct,
        atr_multiplier_override=atr_multiplier_override, tp_close_pcts_override=tp_close_pcts_override,
        confirmed_no_withdraw_permission=confirmed_no_withdraw_permission,
    )


def _handle_trending_path(
    symbol, direction, entry_signal, account_balance, effective_risk_pct,
    signals_by_tf, confluence, atr_series, adx_value, news_imminent,
    live, instrument_name_override,
    max_consecutive_losses=None, max_drawdown_pct=None, atr_multiplier_override=None,
    tp_close_pcts_override=None, confirmed_no_withdraw_permission=False,
) -> int:
    checklist = evaluate_entry_checklist(
        entry_signal, direction, risk_pct=effective_risk_pct, symbol=symbol, atr_series=atr_series,
    )
    print()
    print(format_checklist(checklist))

    if not checklist.all_passed:
        print("\nEntry checklist not fully satisfied -- no trade planned.")
        journal.write_rejected(symbol, "entry_checklist", "entry checklist not fully satisfied", checklist)
        return 0

    # "Avoid entering after an extended move" -- bollinger_bands.py already
    # labels this exact condition ("... (Extended)") when price is stretched
    # beyond the band, so reuse that instead of re-deriving %B here.
    bb_label = entry_signal.labels.get("bollinger_bands", "")
    if "Extended" in bb_label:
        print(f"\nOverextension guard tripped: Bollinger Bands reads '{bb_label}'.")
        print("Avoiding entry after an extended move -- no trade planned. Wait for a pullback.")
        journal.write_rejected(symbol, "overextension_guard", bb_label)
        return 0

    plan = risk.build_position_plan(
        symbol=symbol, direction=direction, entry_price=entry_signal.entry, atr=entry_signal.atr,
        account_balance=account_balance, risk_pct=effective_risk_pct,
        atr_multiplier_override=atr_multiplier_override,
    )
    tp_levels = [entry_signal.take_profits[f"TP{i}"] for i in range(1, 5)]
    journal.write_simulated_order(symbol, direction, plan, tp_levels)

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
        journal.write_rejected(symbol, "no_trade_filter", "no-trade filter blocked this setup", nt_result)
        return 0

    confidence_result = confidence_scoring.calculate_weighted_confidence(signals_by_tf, direction, entry_signal)
    print()
    print(confidence_scoring.format_weighted_confidence(confidence_result))

    print()
    print(risk.format_position_plan(plan))

    timeframe_directions = {tf: paper_approval.direction_label(sig) for tf, sig in signals_by_tf.items()}

    return _open_trade_and_maybe_go_live(
        symbol, direction, plan, tp_levels, confluence.agreeing_timeframes, confluence.confluence_score,
        live, instrument_name_override, entry_signal=entry_signal, risk_pct=effective_risk_pct,
        timeframe_directions=timeframe_directions,
        max_consecutive_losses=max_consecutive_losses, max_drawdown_pct=max_drawdown_pct,
        tp_close_pcts_override=tp_close_pcts_override,
        confirmed_no_withdraw_permission=confirmed_no_withdraw_permission,
    )


def _handle_ranging_path(
    symbol, entry_signal, account_balance, effective_risk_pct,
    rsi_series, vp_result, pattern_matches, atr_series, adx_value, news_imminent,
    live, instrument_name_override,
    max_consecutive_losses=None, max_drawdown_pct=None, atr_multiplier_override=None,
    tp_close_pcts_override=None, confirmed_no_withdraw_permission=False,
) -> int:
    setup = ranging_strategy.evaluate_ranging_setup(
        price=entry_signal.entry, rsi_series=rsi_series, poc=vp_result.poc,
        vah=vp_result.vah, val=vp_result.val, pattern_matches=pattern_matches,
    )
    print()
    print(ranging_strategy.format_ranging_setup(setup))

    # Advisory only -- Mode 2 (rotation) expects a flat ATR read; this is
    # just an early heads-up if ATR is already turning (e.g. toward
    # expansion), which would mean the range may be about to break rather
    # than hold. It does not gate the ranging setup itself.
    from .indicators import atr_state

    atr_transition = atr_state.detect_transition(atr_state.classify_atr_series(atr_series))
    print(atr_state.format_atr_transition(atr_transition))

    if not setup.valid:
        print("\nNo qualifying ranging setup -- no trade planned.")
        journal.write_rejected(symbol, "ranging_setup", "no qualifying ranging setup", setup)
        return 0

    direction = setup.direction
    plan = risk.build_position_plan(
        symbol=symbol, direction=direction, entry_price=entry_signal.entry, atr=entry_signal.atr,
        account_balance=account_balance, risk_pct=effective_risk_pct,
        atr_multiplier_override=atr_multiplier_override,
    )
    # Ranging targets replace the ATR-extension Fibonacci ladder: TP1 = POC, TP2 = opposite range edge.
    tp_levels = [setup.tp1, setup.tp2]
    journal.write_simulated_order(symbol, direction, plan, tp_levels)

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
        journal.write_rejected(symbol, "no_trade_filter", "no-trade filter blocked this setup", nt_result)
        return 0

    print()
    print(risk.format_position_plan(plan))

    return _open_trade_and_maybe_go_live(
        symbol, direction, plan, tp_levels, [], 0, live, instrument_name_override,
        entry_signal=entry_signal, risk_pct=effective_risk_pct,
        max_consecutive_losses=max_consecutive_losses, max_drawdown_pct=max_drawdown_pct,
        tp_close_pcts_override=tp_close_pcts_override,
        confirmed_no_withdraw_permission=confirmed_no_withdraw_permission,
    )


def _open_trade_and_maybe_go_live(
    symbol, direction, plan, tp_levels, confluence_timeframes, confluence_score,
    live, instrument_name_override, entry_signal=None, risk_pct=None, timeframe_directions=None,
    max_consecutive_losses=None, max_drawdown_pct=None, tp_close_pcts_override=None,
    confirmed_no_withdraw_permission=False,
) -> int:
    # Portfolio-level throttle (circuit_breaker.py), checked BEFORE opening
    # -- distinct from trade_manager's own per-trade rules. --max-*-losses/
    # --max-drawdown-pct of 0 explicitly disables that trigger; unset uses
    # circuit_breaker.py's defaults.
    cb_max_losses = None if max_consecutive_losses == 0 else (
        max_consecutive_losses if max_consecutive_losses is not None
        else circuit_breaker.DEFAULT_MAX_CONSECUTIVE_LOSSES
    )
    cb_max_drawdown = None if max_drawdown_pct == 0 else (
        max_drawdown_pct if max_drawdown_pct is not None
        else circuit_breaker.DEFAULT_MAX_DRAWDOWN_PCT
    )
    if cb_max_losses is not None or cb_max_drawdown is not None:
        cb_result = circuit_breaker.check_circuit_breaker_for_symbol(
            symbol,
            max_consecutive_losses=cb_max_losses if cb_max_losses is not None else float("inf"),
            max_drawdown_pct=cb_max_drawdown if cb_max_drawdown is not None else float("inf"),
        )
        print()
        print(circuit_breaker.format_circuit_breaker(cb_result))
        if cb_result.tripped:
            print("\nCircuit breaker tripped -- no trade opened.")
            journal.write_rejected(symbol, "circuit_breaker", cb_result.reason, cb_result)
            return 0

    trade, message = trade_manager.open_trade(
        symbol=symbol, direction=direction, entry_price=plan.entry_price, atr=plan.atr,
        stop_price=plan.stop_price, tp_levels=tp_levels, position_size=plan.position_size,
        risk_amount=plan.risk_amount, account_balance=plan.account_balance,
        confluence_timeframes=confluence_timeframes, confluence_score=confluence_score,
        tp_close_pcts=risk.resolve_tp_close_pcts(tp_close_pcts_override),
    )
    print()
    print(message)
    if trade is not None:
        if entry_signal is not None:
            approval = paper_approval.build_paper_trade_approval(
                symbol, direction, entry_signal, plan, tp_levels,
                timeframe_directions=timeframe_directions, risk_pct=risk_pct,
                tp_close_pcts=trade.tp_close_pcts, result="PASS",
            )
            print()
            print(paper_approval.format_paper_trade_approval(approval))
        print(trade_manager.format_trade(trade))
        print(
            "\nNote: this is a locally tracked PAPER trade only -- no live order "
            "was placed. Run `python -m cdcx --update-trades` to check it against "
            "fresh prices and apply the trailing-stop rules."
        )
        journal.write_simulated_result(symbol, trade, result="PASS")
        if live:
            _handle_live_order(
                symbol, direction, plan, tp_levels, instrument_name_override,
                entry_signal=entry_signal, timeframe_confirmed=True,
                confirmed_no_withdraw_permission=confirmed_no_withdraw_permission,
            )
    else:
        journal.write_rejected(symbol, "trade_manager", message)

    return 0


def _detect_duplicate_live_order(symbol: str, window_seconds: float = 300.0) -> bool:
    """True if a live order was already sent for this symbol within the last
    `window_seconds` -- catches an accidental double-submission (e.g. the
    same command run twice in quick succession) before it becomes a second
    real order. Reads the journal (trading/live/executions/), not the
    exchange -- see journal.py."""
    import time as _time
    now = _time.time()
    for record in journal.load_stage("live_execution"):
        if record.get("symbol") == symbol and (now - record.get("written_at", 0)) <= window_seconds:
            return True
    return False


def _handle_live_order(
    symbol, direction, plan, tp_levels, instrument_name_override,
    entry_signal=None, timeframe_confirmed=True, confirmed_no_withdraw_permission=False,
) -> None:
    from . import live_execution
    from . import no_trade_gate
    from .exchange.cryptocom import CryptoComExchange
    import time as _time

    instrument_name = instrument_name_override or live_execution.derive_instrument_name(symbol)

    # Crypto.com's stock/RWA perpetuals (AAPLUSD-PERP, SPYUSD-PERP, etc.)
    # reject a plain cross-margin order outright (error 623
    # INSTRUMENT_MUST_USE_ISOLATED_MARGIN) -- detect that up front from the
    # public instrument list so the dry-run below reflects what will
    # actually happen, rather than surfacing the rejection only on send.
    # Fails closed to cross-margin (False) if the lookup can't run at all
    # (e.g. no network); a wrong guess either way is still caught by
    # --dry-run before anything real is sent.
    try:
        isolated_margin = CryptoComExchange(
            settings.cryptocom_api_key, settings.cryptocom_api_secret,
        ).requires_isolated_margin(symbol)
    except Exception as exc:
        print(f"Warning: could not determine isolated-margin requirement ({exc}); assuming cross margin.")
        isolated_margin = False
    if isolated_margin:
        print(f"{instrument_name} requires isolated margin -- attaching exec_inst: [ISOLATED_MARGIN].")

    order_list = live_execution.build_otoco_order_list(
        instrument_name=instrument_name,
        direction=direction,
        quantity=plan.position_size,
        stop_price=plan.stop_price,
        take_profit_price=tp_levels[0],
        isolated_margin=isolated_margin,
    )

    journal.write_live_order(symbol, instrument_name, order_list)

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
        journal.write_rejected(symbol, "live_dry_run", "cdcx binary not found on PATH")
        return

    print(live_execution.format_bracket_preview(instrument_name, order_list, result))

    if result.dry_run_returncode != 0:
        print(
            "\nThe dry-run itself did not return success -- fix the issue above "
            "before proceeding. Nothing was sent.",
            file=sys.stderr,
        )
        journal.write_rejected(symbol, "live_dry_run", "dry-run did not return success", result)
        return

    print(
        "\nThis is your last chance to stop. Type exactly YES (all caps) to send "
        "this REAL order to the exchange, or anything else to cancel:"
    )
    try:
        confirmation = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        confirmation = ""

    # --- FINAL NO-TRADE GATE (no_trade_gate.py) -- the absolute last check,
    # re-validating everything from scratch right at the point of no return
    # rather than trusting every earlier gate still holds. ANY single
    # failure blocks the order outright; every reason is always shown. ---
    data_age_seconds = (_time.time() - entry_signal.computed_at) if entry_signal is not None else None
    gate_result = no_trade_gate.check_no_trade_gate(
        paper_trade_result="PASS",  # a paper trade was already opened successfully to reach this point
        human_approval=(confirmation == "YES"),
        risk_pct=plan.risk_pct,
        stop_loss=plan.stop_price,
        take_profits=tp_levels,
        timeframe_confirmed=timeframe_confirmed,
        withdrawal_permission_confirmed_disabled=confirmed_no_withdraw_permission,
        duplicate_order_detected=_detect_duplicate_live_order(symbol),
        data_age_seconds=data_age_seconds,
        timeframe=getattr(entry_signal, "timeframe", "") or "",
        max_risk_pct=settings.risk_pct_per_trade,
        max_data_staleness_bars=settings.max_data_staleness_bars,
        required_tp_count=len(tp_levels),
    )
    print()
    print(no_trade_gate.format_no_trade_gate(gate_result))

    if not gate_result.passed:
        journal.write_rejected(symbol, "no_trade_gate", "; ".join(gate_result.failures), gate_result)
        return

    journal.write_approved(symbol, order_list, confirmed_by="human_cli")

    print("\nSending live order...")
    result = live_execution.send_bracket_live(result)
    journal.write_live_execution(symbol, result)
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


def _parse_datetime_arg(value: str) -> float:
    """Accepts 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS' (UTC), or a raw unix
    timestamp, and returns a unix timestamp (seconds)."""
    from datetime import datetime, timezone

    try:
        return float(value)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    raise ValueError(
        f"Could not parse '{value}' -- use YYYY-MM-DD, YYYY-MM-DDTHH:MM:SS, or a unix timestamp."
    )


def _handle_record_live_close(args: argparse.Namespace) -> int:
    missing = [
        name for name, value in [
            ("--direction", args.direction), ("--quantity", args.quantity),
            ("--entry-price", args.entry_price), ("--exit-price", args.exit_price),
            ("--opened-at", args.opened_at), ("--closed-at", args.closed_at),
        ] if value is None
    ]
    if missing:
        print(f"--record-live-close requires: {', '.join(missing)}", file=sys.stderr)
        return 1

    try:
        opened_at = _parse_datetime_arg(args.opened_at)
        closed_at = _parse_datetime_arg(args.closed_at)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1

    path = journal.write_live_result(
        symbol=args.symbol, direction=args.direction, quantity=args.quantity,
        entry_price=args.entry_price, exit_price=args.exit_price,
        opened_at=opened_at, closed_at=closed_at, fees=args.fees, notes=args.notes,
    )
    print(f"Recorded closed live trade -> {path}")
    print("Run --export-tax to regenerate the Form 8949 / Schedule D / CPA / SSA exports.")
    return 0


def _handle_export_tax() -> int:
    from . import tax_export

    paths = tax_export.export_all()
    trades = tax_export.load_closed_trades()
    print(tax_export.format_schedule_d_summary(trades))
    print()
    print(tax_export.format_cpa_summary(trades))
    print()
    print(tax_export.format_ssa_record(trades))
    print()
    print("Wrote:")
    for kind, path in paths.items():
        print(f"  {kind:<20} {path}")
    return 0


def _handle_predictions_list(kind: str, limit: int) -> int:
    from .predictions import PredictionsClient, PredictionsNotFound, PredictionsRateLimited, format_events

    client = PredictionsClient(api_key=settings.predictions_api_key)
    kind_filter = None if kind == "__all__" else kind
    try:
        events = client.list_events(kind=kind_filter, limit=limit)
    except (PredictionsRateLimited, PredictionsNotFound) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error fetching prediction events: {exc}", file=sys.stderr)
        return 1

    label = f"kind={kind_filter}" if kind_filter else "all kinds"
    print(format_events(f"PREDICTION MARKET EVENTS ({label})", events))
    return 0


def _handle_predictions_search(query: str, limit: int) -> int:
    from .predictions import PredictionsClient, PredictionsNotFound, PredictionsRateLimited, format_events

    client = PredictionsClient(api_key=settings.predictions_api_key)
    try:
        events = client.search_events(query, limit=limit)
    except (PredictionsRateLimited, PredictionsNotFound) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error searching prediction events: {exc}", file=sys.stderr)
        return 1

    print(format_events(f'PREDICTION MARKET SEARCH -- "{query}"', events))
    return 0


def _handle_predictions_contract(ticker: str) -> int:
    from .predictions import PredictionsClient, PredictionsNotFound, PredictionsRateLimited, format_contract_price

    client = PredictionsClient(api_key=settings.predictions_api_key)
    try:
        price = client.get_contract_price(ticker)
    except (PredictionsRateLimited, PredictionsNotFound) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error fetching contract price for {ticker}: {exc}", file=sys.stderr)
        return 1

    print(format_contract_price(price))
    return 0


def _handle_leverage(symbol: str) -> int:
    from .exchange.cryptocom import CryptoComExchange

    exchange = CryptoComExchange(settings.cryptocom_api_key, settings.cryptocom_api_secret)
    try:
        limits = exchange.fetch_perp_leverage_limits(symbol)
    except KeyError:
        print(f"No USD-margined perpetual listed for {symbol} on Crypto.com.", file=sys.stderr)
        return 1

    print(f"{limits.instrument_id}: {limits.min_leverage:g}x - {limits.max_leverage:g}x leverage")
    print(
        "Reminder: this tool never sets leverage itself (create-otoco has no leverage "
        "field) -- configure it on your account via `cdcx trade leverage` before --live."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.live and not args.execute:
        print("--live requires --execute (and --timeframes with 2+ of 1h/4h/1d/1w).", file=sys.stderr)
        return 1

    if args.live and settings.trading_mode != "LIVE":
        print(
            "--live refused: TRADING_MODE is not set to LIVE (currently "
            f"'{settings.trading_mode}'). This is a software-level switch, independent "
            "of --live and the typed-YES confirmation -- set TRADING_MODE=LIVE in .env "
            "(or the environment) if you actually intend to send a real order. This "
            "exists specifically so a stray --live on a machine still configured for "
            "paper testing can't accidentally place one.",
            file=sys.stderr,
        )
        return 1

    if args.list_trades:
        return _handle_list_trades()

    if args.update_trades:
        return _handle_update_trades()

    if args.record_live_close:
        return _handle_record_live_close(args)

    if args.export_tax:
        return _handle_export_tax()

    if args.predictions is not None:
        return _handle_predictions_list(args.predictions, args.predictions_limit)

    if args.predictions_search:
        return _handle_predictions_search(args.predictions_search, args.predictions_limit)

    if args.predictions_contract:
        return _handle_predictions_contract(args.predictions_contract)

    if args.leverage:
        return _handle_leverage(args.symbol)

    if args.backtrader:
        result = _handle_backtrader(args)
        if args.structure:
            structure_cache: dict = {}
            backtrader_timeframe = args.timeframe or settings.default_timeframe
            _print_merged_structure_block(args.symbol, backtrader_timeframe, args.limit, structure_cache)
            _print_structure_setup_section(args.symbol, args.limit, structure_cache)
        return result

    from . import engine  # deferred: requires ccxt, not needed for the branches above

    if args.timeframes:
        timeframes = [tf.strip() for tf in args.timeframes.split(",") if tf.strip()]
        results = {}
        any_success = False
        structure_cache = {}

        for tf in timeframes:
            signal = _run_single(
                args.symbol, tf, args.limit,
                atr_multiplier_override=args.atr_multiplier, tp_ratios_override=args.tp_ratios,
                tp_mode_override=args.tp_mode,
            )
            results[tf] = signal
            if signal is not None:
                any_success = True
                print(engine.format_report(signal))
                # Merged right into this timeframe's own block -- if `tf` is one
                # of 1w/1d/4h/1h, its structure section prints here instead of
                # in a separate section for the whole structure system.
                if args.structure:
                    _print_merged_structure_block(args.symbol, tf, args.limit, structure_cache)
                print()

        _print_summary_table(args.symbol, results)

        if args.execute:
            result = _handle_execute(
                args.symbol, args.balance, args.risk_pct, results, args.limit,
                live=args.live, instrument_name_override=args.instrument_name,
                news_imminent=args.news_imminent,
                max_consecutive_losses=args.max_consecutive_losses, max_drawdown_pct=args.max_drawdown_pct,
                atr_multiplier_override=args.atr_multiplier,
                tp_ratios_override=args.tp_ratios, tp_close_pcts_override=args.tp_close_pcts,
            )
        else:
            result = 0 if any_success else 1

        # Final combined LONG/SHORT trigger evaluation across all four roles,
        # reusing whatever the per-timeframe blocks above already fetched.
        if args.structure:
            _print_structure_setup_section(args.symbol, args.limit, structure_cache)

        return result

    # single-timeframe path (backwards compatible)
    timeframe = args.timeframe or settings.default_timeframe
    signal = _run_single(
        args.symbol, timeframe, args.limit,
        atr_multiplier_override=args.atr_multiplier, tp_ratios_override=args.tp_ratios,
        tp_mode_override=args.tp_mode,
    )
    if signal is None:
        return 1

    print(engine.format_report(signal))

    structure_cache = {}
    if args.structure:
        _print_merged_structure_block(args.symbol, timeframe, args.limit, structure_cache)

    result = 0
    if args.execute:
        print(
            "\n--execute needs --timeframes with at least 2 timeframes to check "
            "confluence (e.g. --timeframes 1h,4h,1d,1w). No trade planned.",
            file=sys.stderr,
        )
        result = 1

    if args.structure:
        _print_structure_setup_section(args.symbol, args.limit, structure_cache)

    return result


if __name__ == "__main__":
    raise SystemExit(main())
