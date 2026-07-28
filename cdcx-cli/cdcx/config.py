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

    default_symbol: str = os.getenv("DEFAULT_SYMBOL", "BTC/USDT")
    default_timeframe: str = os.getenv("DEFAULT_TIMEFRAME", "1h")
    default_limit: int = int(os.getenv("DEFAULT_LIMIT", "200"))

    swing_lookback: int = int(os.getenv("SWING_LOOKBACK", "50"))

    # Money management (see cdcx/risk.py)
    # 1.5x ATR is the "magic number" stop-loss distance from entry.
    atr_stop_multiplier: float = float(os.getenv("ATR_STOP_MULTIPLIER", "1.5"))
    # % of account balance risked per trade (and the cap per currency pair).
    risk_pct_per_trade: float = float(os.getenv("RISK_PCT_PER_TRADE", "2.0"))
    # Account size used for position sizing when --balance isn't passed on the CLI.
    default_account_balance: float = float(os.getenv("DEFAULT_ACCOUNT_BALANCE", "10000"))
    # Fraction of the breakeven-to-TP1 distance used for the give-back protective exit.
    giveback_exit_pct: float = float(os.getenv("GIVEBACK_EXIT_PCT", "0.20"))

    # Local (paper) trade-state file -- this tool does not place live orders.
    trade_state_path: str = os.getenv("TRADE_STATE_PATH", "cdcx_trades.json")


settings = Settings()
