"""
trade_manager.py
------------------
Locally tracked (paper) trade lifecycle. This project has no live broker or
order-routing connection -- opening a trade here means writing a row to a
local JSON file (`cdcx_trades.json` by default) with the full plan (entry,
stop, size, TP ladder). "Updating" a trade means re-checking the latest
price against that plan and applying the trailing-stop rules below. Nothing
here sends a real order anywhere.

Rules implemented:
    C. Only the first entry per symbol is taken -- no pyramiding / no second
       entry while a trade on that symbol is still open.
    G. When TP1 is reached, move the stop to breakeven (entry price).
    H. When each subsequent TP is reached, move the stop to the *previous*
       TP level, ratcheting all the way to close.
    I. If price gives back from TP1 toward breakeven, close the trade once
       it reaches a level 20% of the way (from breakeven towards TP1)
       above breakeven, rather than riding it all the way back to
       breakeven -- a tighter protective exit than the hard stop.
    J. Planned max loss per trade is 2% of account equity (enforced by
       position sizing in risk.py). If a close happens to realize a larger
       loss than planned -- e.g. the stop level is jumped over on a gap/
       fast market rather than filled exactly at the stop price -- this
       module records the true realized loss honestly rather than
       assuming the plan held, and raises an explicit warning if the
       realized loss exceeds a 5% hard ceiling. Nothing here can force a
       real fill at the stop price (no live broker connection); this is
       strictly an honest-accounting safeguard, not a guarantee.
    Reaching the final TP (TP4) closes the trade outright.
    The hard stop (wherever it currently sits) closes the trade if crossed
    against the position, at any time.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Literal, Optional

from .config import settings

Direction = Literal["long", "short"]


@dataclass
class Trade:
    id: str
    symbol: str
    direction: Direction
    entry_price: float
    atr: float
    initial_stop: float
    current_stop: float
    tp_levels: list[float]              # [TP1, TP2, TP3, TP4], in trade direction order
    position_size: float
    risk_amount: float
    account_balance: float
    confluence_timeframes: list[str] = field(default_factory=list)
    confluence_score: int = 0
    tp_index_reached: int = -1          # -1 = none yet, 0 = TP1 hit, 1 = TP2 hit, ...
    status: str = "open"                # "open" | "closed"
    close_price: Optional[float] = None
    close_reason: Optional[str] = None
    realized_pnl: Optional[float] = None
    realized_pnl_pct: Optional[float] = None   # % of account_balance, negative = loss
    safety_warning: Optional[str] = None       # set if realized loss exceeded the 5% ceiling (rule J)
    opened_at: float = field(default_factory=time.time)
    closed_at: Optional[float] = None


def _state_path() -> str:
    return settings.trade_state_path


def load_trades() -> list[Trade]:
    path = _state_path()
    if not os.path.exists(path):
        return []
    with open(path) as f:
        raw = json.load(f)
    return [Trade(**row) for row in raw]


def save_trades(trades: list[Trade]) -> None:
    path = _state_path()
    with open(path, "w") as f:
        json.dump([asdict(t) for t in trades], f, indent=2)


def get_open_trade(symbol: str, trades: Optional[list[Trade]] = None) -> Optional[Trade]:
    trades = trades if trades is not None else load_trades()
    for t in trades:
        if t.symbol == symbol and t.status == "open":
            return t
    return None


def open_trade(
    symbol: str,
    direction: Direction,
    entry_price: float,
    atr: float,
    stop_price: float,
    tp_levels: list[float],
    position_size: float,
    risk_amount: float,
    account_balance: float,
    confluence_timeframes: Optional[list[str]] = None,
    confluence_score: int = 0,
) -> tuple[Optional[Trade], str]:
    """
    Returns (trade_or_none, message). Refuses to open a second trade on a
    symbol that already has one open (rule C: ride the first entry; this
    also enforces the "never risk more than 2% on the same pair" rule,
    since each trade is already sized to exactly the per-trade risk cap).
    """
    trades = load_trades()

    existing = get_open_trade(symbol, trades)
    if existing is not None:
        return None, (
            f"Refused: {symbol} already has an open trade (id={existing.id[:8]}) -- "
            "riding the first entry per rule C, no pyramiding/second entry."
        )

    trade = Trade(
        id=str(uuid.uuid4()),
        symbol=symbol,
        direction=direction,
        entry_price=entry_price,
        atr=atr,
        initial_stop=stop_price,
        current_stop=stop_price,
        tp_levels=tp_levels,
        position_size=position_size,
        risk_amount=risk_amount,
        account_balance=account_balance,
        confluence_timeframes=confluence_timeframes or [],
        confluence_score=confluence_score,
    )
    trades.append(trade)
    save_trades(trades)
    return trade, f"Opened {direction.upper()} {symbol} @ {entry_price}, stop {stop_price}, size {position_size}"


def _giveback_exit_level(trade: Trade) -> float:
    """20% of the breakeven-to-TP1 distance, above breakeven (rule I)."""
    tp1 = trade.tp_levels[0]
    breakeven = trade.entry_price
    offset = settings.giveback_exit_pct * abs(tp1 - breakeven)
    if trade.direction == "long":
        return breakeven + offset
    return breakeven - offset


MAX_LOSS_PCT_CEILING = 5.0  # rule J: never intentionally allow more than this


def _close_trade(trade: Trade, price: float, reason: str, events: list[str]) -> None:
    """Shared close path: records realized P&L honestly (not assumed-planned
    P&L) and flags a rule-J warning if the actual loss exceeds the 5% ceiling
    -- e.g. because the price gapped past the stop rather than filling there."""
    trade.status = "closed"
    trade.close_price = price
    trade.close_reason = reason
    trade.closed_at = time.time()

    direction_sign = 1 if trade.direction == "long" else -1
    pnl = (price - trade.entry_price) * trade.position_size * direction_sign
    pnl_pct = (pnl / trade.account_balance) * 100 if trade.account_balance else 0.0

    trade.realized_pnl = round(pnl, 2)
    trade.realized_pnl_pct = round(pnl_pct, 4)

    if pnl_pct <= -MAX_LOSS_PCT_CEILING:
        trade.safety_warning = (
            f"Realized loss {pnl_pct:.2f}% exceeded the {MAX_LOSS_PCT_CEILING}% safety ceiling "
            f"(planned risk was {round((trade.risk_amount / trade.account_balance) * 100, 2) if trade.account_balance else '?'}%) "
            "-- likely slippage/gap past the stop in fast-moving market conditions. Recorded honestly per rule J."
        )
        events.append(trade.safety_warning)

    events.append(reason)


def update_trade(trade: Trade, current_price: float) -> list[str]:
    """
    Mutates `trade` in place according to the current price. Returns a list
    of human-readable event messages (empty if nothing changed). Caller is
    responsible for saving the trade list afterward.
    """
    if trade.status != "open":
        return []

    events: list[str] = []
    is_long = trade.direction == "long"

    def reached(level: float) -> bool:
        return current_price >= level if is_long else current_price <= level

    def breached_stop() -> bool:
        return current_price <= trade.current_stop if is_long else current_price >= trade.current_stop

    # --- rule I: protective give-back exit, only while sitting at breakeven
    # (i.e. TP1 hit but TP2 not yet), before checking TP progression further ---
    if trade.tp_index_reached == 0:
        exit_level = _giveback_exit_level(trade)
        gave_back = current_price <= exit_level if is_long else current_price >= exit_level
        if gave_back:
            reason = (
                f"Give-back protective exit: price returned to {round(exit_level, 8)} "
                f"(20% above breakeven) after TP1 -- rule I"
            )
            _close_trade(trade, current_price, reason, events)
            return events

    # --- rules G/H: ratchet stop through the TP ladder ---
    for i, tp in enumerate(trade.tp_levels):
        if i <= trade.tp_index_reached:
            continue
        if not reached(tp):
            break  # TP levels are ordered; can't reach tp[i] without tp[i-1] first in practice

        if i == 0:
            trade.current_stop = trade.entry_price
            events.append(f"TP1 reached @ {tp} -- stop moved to breakeven ({trade.entry_price})")
        else:
            trade.current_stop = trade.tp_levels[i - 1]
            events.append(f"TP{i + 1} reached @ {tp} -- stop trailed to TP{i} ({trade.tp_levels[i - 1]})")

        trade.tp_index_reached = i

        if i == len(trade.tp_levels) - 1:
            _close_trade(trade, current_price, f"Final target TP{i + 1} reached -- full close", events)
            return events

    # --- hard stop check (only relevant if not already closed above) ---
    if trade.status == "open" and breached_stop():
        reason = "Stopped out at breakeven" if trade.current_stop == trade.entry_price else "Stopped out"
        _close_trade(trade, current_price, f"{reason} ({trade.current_stop})", events)

    return events


def update_all_open_trades(prices_by_symbol: dict[str, float]) -> dict[str, list[str]]:
    """Convenience wrapper: update every open trade whose symbol has a price
    supplied, save the results, and return {symbol: [events]}."""
    trades = load_trades()
    results: dict[str, list[str]] = {}

    for trade in trades:
        if trade.status != "open":
            continue
        price = prices_by_symbol.get(trade.symbol)
        if price is None:
            continue
        events = update_trade(trade, price)
        if events:
            results[trade.symbol] = events

    save_trades(trades)
    return results


def format_trade(trade: Trade) -> str:
    lines = [
        "-" * 49,
        f"TRADE {trade.id[:8]} -- {trade.symbol} ({trade.status.upper()})",
        "-" * 49,
        f"Direction:       {trade.direction.upper()}",
        f"Entry:           {trade.entry_price}",
        f"Current Stop:    {trade.current_stop}",
        f"TP Levels:       {trade.tp_levels}",
        f"TP Reached:      {'none' if trade.tp_index_reached < 0 else f'TP{trade.tp_index_reached + 1}'}",
        f"Position Size:   {trade.position_size}",
        f"Risk Amount:     {trade.risk_amount}",
        f"Confluence:      {', '.join(trade.confluence_timeframes) or 'n/a'} (score {trade.confluence_score})",
    ]
    if trade.status == "closed":
        lines.append(f"Closed @:        {trade.close_price}")
        lines.append(f"Close Reason:    {trade.close_reason}")
        lines.append(f"Realized P&L:    {trade.realized_pnl} ({trade.realized_pnl_pct}% of account)")
        if trade.safety_warning:
            lines.append(f"** WARNING **:   {trade.safety_warning}")
    lines.append("-" * 49)
    return "\n".join(lines)


if __name__ == "__main__":
    # Self-contained smoke test using a temp state file, doesn't touch the
    # real cdcx_trades.json.
    settings.trade_state_path = "/tmp/cdcx_trades_demo.json"
    if os.path.exists(settings.trade_state_path):
        os.remove(settings.trade_state_path)

    trade, msg = open_trade(
        symbol="BTC/USDT", direction="long", entry_price=65000.0, atr=850.0,
        stop_price=63725.0, tp_levels=[66000, 67000, 68500, 71000],
        position_size=0.157, risk_amount=200.0, account_balance=10000.0,
        confluence_timeframes=["1h", "4h", "1d"], confluence_score=16,
    )
    print(msg)
    print(format_trade(trade))

    for price in [65500, 66100, 65300, 67200, 68600, 71200]:
        events = update_trade(trade, price)
        for e in events:
            print(f"[price={price}] {e}")

    print(format_trade(trade))
