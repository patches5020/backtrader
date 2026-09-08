"""
config.py
---------
Loads environment variables (.env) and holds default settings for the
CDCX AI trading engine.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    cryptocom_api_key: str = os.getenv("CRYPTOCOM_API_KEY", "")
    cryptocom_api_secret: str = os.getenv("CRYPTOCOM_API_SECRET", "")

    # Optional Market Data License (MDLA) key for the Crypto.com Predictions
    # API (see cdcx/predictions.py) -- raises the anonymous rate limits.
    # Every --predictions* command works fine with this left blank.
    predictions_api_key: str = os.getenv("PREDICTIONS_API_KEY", "")

    default_symbol: str = os.getenv("DEFAULT_SYMBOL", "BTC/USDT")
    default_timeframe: str = os.getenv("DEFAULT_TIMEFRAME", "1h")
    default_limit: int = int(os.getenv("DEFAULT_LIMIT", "200"))

    swing_lookback: int = int(os.getenv("SWING_LOOKBACK", "50"))

    # Money management (see cdcx/risk.py)
    # 1.5x ATR is the "magic number" stop-loss distance from entry -- the
    # GLOBAL fallback default, used for any base currency not listed in
    # atr_multiplier_overrides below.
    atr_stop_multiplier: float = float(os.getenv("ATR_STOP_MULTIPLIER", "1.5"))
    # Per-symbol ATR multiplier overrides, keyed by BASE currency (not the
    # full pair -- "BTC" matches BTC/USDT, BTC/USD, etc.), format
    # "BASE:MULT,BASE:MULT,...". A real 1000-bar 1h backtest sweep (see
    # README's "ATR-multiplier sensitivity" section) found XRP's *empirical*
    # optimum was a tighter 1.0x -- deliberately overridden back to the
    # 1.5x global default here at the user's request, trading that
    # backtested edge for one consistent multiplier across both traded
    # symbols. See risk.resolve_atr_multiplier() for the full resolution
    # order (explicit override > this per-symbol table > atr_stop_multiplier).
    atr_multiplier_overrides: str = os.getenv("ATR_MULTIPLIER_OVERRIDES", "BTC:1.5,XRP:1.5")
    # TP1-4 R-multiples (of stop_distance = atr * atr_multiplier), e.g.
    # "2.2,2.6,3.2,4.5" -- selectable at input (--tp-ratios), not hardcoded.
    # See risk.resolve_tp_ratios().
    tp_ratios: str = os.getenv("TP_RATIOS", "2.2,2.6,3.2,4.5")
    # % of the ORIGINAL position size closed at each TP1-4 as it's reached
    # (must be 4 values, each 0-100, summing to <= 100). Default closes the
    # position in four equal slices. See risk.resolve_tp_close_pcts() and
    # trade_manager.py's partial-close handling. --tp-close-pcts overrides.
    tp_close_pcts: str = os.getenv("TP_CLOSE_PCTS", "25,25,25,25")
    # How TP1-4 are computed: "atr" (default, fixed R-multiples of
    # stop_distance -- see tp_ratios above) or "structural" (nearest real
    # resistance/support -- volume-profile VAH/VAL/HVN/LVN, a Fibonacci
    # extension rung, a swing high/low, or an active FVG edge -- ahead of
    # price in the trade's direction, one per rung, nearest first; any rung
    # without a real structural candidate falls back to its ATR level so
    # structural mode never returns fewer than 4 targets). Opt-in: the ATR
    # ladder remains the default so existing tuning (per-symbol ATR
    # multipliers, TP_RATIOS) is unaffected unless you ask for this.
    # See risk.resolve_tp_mode() / risk.build_structural_tp_levels().
    tp_mode: str = os.getenv("TP_MODE", "atr")
    # % of account balance risked per trade (and the cap per currency pair).
    risk_pct_per_trade: float = float(os.getenv("RISK_PCT_PER_TRADE", "2.0"))
    # Account size used for position sizing when --balance isn't passed on the CLI.
    default_account_balance: float = float(os.getenv("DEFAULT_ACCOUNT_BALANCE", "10000"))
    # Fraction of the breakeven-to-TP1 distance used for the give-back protective exit.
    giveback_exit_pct: float = float(os.getenv("GIVEBACK_EXIT_PCT", "0.20"))

    # Local (paper) trade-state file -- this tool does not place live orders.
    trade_state_path: str = os.getenv("TRADE_STATE_PATH", "cdcx_trades.json")

    # Root directory for the on-disk audit trail (see cdcx/journal.py):
    # trading/paper/{signals,simulated_orders,simulated_results,rejected}/
    # trading/live/{approved,orders,executions,results}/
    trading_journal_dir: str = os.getenv("TRADING_JOURNAL_DIR", "trading")

    # Software-level paper/live separation (see cdcx/no_trade_gate.py) --
    # independent of the --live CLI flag and the typed-YES prompt. --live
    # refuses to send anything real unless TRADING_MODE=LIVE is ALSO set in
    # the environment, so a stray --live on a machine still configured for
    # paper testing can't accidentally place a real order. "PAPER" (default)
    # or "LIVE" -- anything else is treated as PAPER (fail-safe).
    trading_mode: str = os.getenv("TRADING_MODE", "PAPER").strip().upper()

    # How many candles' worth of age the last fetched bar is allowed to have
    # before market data is considered stale for the final no-trade gate
    # (see no_trade_gate.py) -- e.g. 3.0 means "the newest candle must be
    # within 3 timeframe-lengths of now."
    max_data_staleness_bars: float = float(os.getenv("MAX_DATA_STALENESS_BARS", "3.0"))


settings = Settings()
