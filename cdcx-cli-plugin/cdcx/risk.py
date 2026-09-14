"""
risk.py
-------
Money management: ATR-based stop-loss placement and account-risk-based
position sizing.

Rules (as specified):
    - Stop loss = 1.5x ATR away from entry price (the "ATR magic number").
      Long:  stop = entry - 1.5*ATR
      Short: stop = entry + 1.5*ATR
    - Risk 2% of account balance per trade.
    - position_size = risk_amount / stop_distance
      (stop_distance = 1.5*ATR = the price-risk per unit; the forex "pip
      value" concept generalizes to "per-unit price risk" for crypto pairs,
      since crypto has no fixed pip size).
    - Never risk more than 2% of the account on the same currency pair at
      once -- enforced by refusing to size a new trade if a symbol already
      has an open tracked position (see trade_manager.py, which also
      enforces "ride the first entry" / no pyramiding).

This module only computes numbers -- it never places orders. There is no
live broker/order-routing connection in this project; any "execution" is a
locally tracked paper trade (see trade_manager.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .config import settings

Direction = Literal["long", "short"]

ATR_STOP_MULTIPLIER = settings.atr_stop_multiplier  # 1.5x ATR "magic number"
RISK_PCT_PER_TRADE = settings.risk_pct_per_trade    # 2% of account balance
MAX_RISK_PCT_PER_SYMBOL = settings.risk_pct_per_trade  # same cap, enforced per pair


@dataclass
class PositionPlan:
    symbol: str
    direction: Direction
    entry_price: float
    atr: float
    stop_price: float
    stop_distance: float          # = ATR_STOP_MULTIPLIER * atr
    account_balance: float
    risk_pct: float
    risk_amount: float            # dollars risked at the stop
    position_size: float          # units of the base asset to buy/sell
    notional_value: float         # position_size * entry_price


def calculate_stop_loss(entry_price: float, atr: float, direction: Direction) -> float:
    """
    Price - ATR = long stop loss (below entry)
    Price + ATR = short stop loss (above entry)
    both scaled by ATR_STOP_MULTIPLIER (1.5x).
    """
    distance = atr * ATR_STOP_MULTIPLIER
    if direction == "long":
        return entry_price - distance
    return entry_price + distance


def calculate_position_size(
    account_balance: float,
    entry_price: float,
    stop_price: float,
    risk_pct: float = RISK_PCT_PER_TRADE,
) -> tuple[float, float, float]:
    """
    Returns (risk_amount, stop_distance, position_size).

    risk_amount    = account_balance * risk_pct / 100
    stop_distance  = |entry_price - stop_price|   (== 1.5x ATR)
    position_size  = risk_amount / stop_distance  -- so that if the stop is
                     hit, the loss equals exactly risk_amount (risk_pct% of
                     the account), never more.
    """
    stop_distance = abs(entry_price - stop_price)
    if stop_distance <= 0:
        raise ValueError("stop_distance must be > 0 -- entry and stop can't be equal")

    risk_amount = account_balance * (risk_pct / 100)
    position_size = risk_amount / stop_distance
    return risk_amount, stop_distance, position_size


def build_position_plan(
    symbol: str,
    direction: Direction,
    entry_price: float,
    atr: float,
    account_balance: float,
    risk_pct: float = RISK_PCT_PER_TRADE,
) -> PositionPlan:
    stop_price = calculate_stop_loss(entry_price, atr, direction)
    risk_amount, stop_distance, position_size = calculate_position_size(
        account_balance, entry_price, stop_price, risk_pct
    )

    return PositionPlan(
        symbol=symbol,
        direction=direction,
        entry_price=entry_price,
        atr=atr,
        stop_price=round(stop_price, 8),
        stop_distance=round(stop_distance, 8),
        account_balance=account_balance,
        risk_pct=risk_pct,
        risk_amount=round(risk_amount, 2),
        position_size=round(position_size, 8),
        notional_value=round(position_size * entry_price, 2),
    )


def format_position_plan(plan: PositionPlan) -> str:
    lines = [
        "-" * 49,
        "POSITION SIZING (paper plan -- not a live order)".center(49),
        "-" * 49,
        f"Symbol:          {plan.symbol}",
        f"Direction:       {plan.direction.upper()}",
        f"Entry Price:     {plan.entry_price}",
        f"ATR:             {plan.atr}",
        f"Stop Loss:       {plan.stop_price}  ({ATR_STOP_MULTIPLIER}x ATR away)",
        f"Account Balance: {plan.account_balance}",
        f"Risk %:          {plan.risk_pct}%",
        f"Risk Amount:     {plan.risk_amount}",
        f"Position Size:   {plan.position_size} units",
        f"Notional Value:  {plan.notional_value}",
        "-" * 49,
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    plan = build_position_plan(
        symbol="BTC/USDT", direction="long", entry_price=65000.0, atr=850.0, account_balance=10000.0,
    )
    print(format_position_plan(plan))
