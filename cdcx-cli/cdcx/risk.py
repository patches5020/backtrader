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
from typing import Literal, Optional

from .config import settings

Direction = Literal["long", "short"]

ATR_STOP_MULTIPLIER = settings.atr_stop_multiplier  # 1.5x ATR "magic number" -- the
# GLOBAL fallback only; see resolve_atr_multiplier() for the real per-symbol-aware
# resolution every function below actually uses. Kept as a module constant for
# backward compatibility (existing callers/tests that import it directly).
RISK_PCT_PER_TRADE = settings.risk_pct_per_trade    # 2% of account balance
MAX_RISK_PCT_PER_SYMBOL = settings.risk_pct_per_trade  # same cap, enforced per pair


@dataclass
class PositionPlan:
    symbol: str
    direction: Direction
    entry_price: float
    atr: float
    stop_price: float
    stop_distance: float          # = atr_multiplier * atr
    account_balance: float
    risk_pct: float
    risk_amount: float            # dollars risked at the stop
    position_size: float          # units of the base asset to buy/sell
    notional_value: float         # position_size * entry_price
    atr_multiplier: float = ATR_STOP_MULTIPLIER  # the actual multiplier resolved/used


def _parse_multiplier_overrides(raw: str) -> dict[str, float]:
    """Parses "BASE:MULT,BASE:MULT,..." into {"BASE": MULT}. Silently skips
    malformed entries rather than raising -- a typo in .env shouldn't crash
    every report; it just falls back to the global default for that symbol."""
    overrides: dict[str, float] = {}
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        base, _, mult = chunk.partition(":")
        try:
            overrides[base.strip().upper()] = float(mult.strip())
        except ValueError:
            continue
    return overrides


def resolve_atr_multiplier(symbol: Optional[str] = None, override: Optional[float] = None) -> float:
    """
    Resolves the ATR stop-loss multiplier to actually use, in priority order:

        1. `override` if given (e.g. --atr-multiplier on the CLI) -- always wins.
        2. A per-symbol default from settings.atr_multiplier_overrides, keyed
           by BASE currency (symbol.split("/")[0]) -- ships pre-configured
           with BTC:1.5, XRP:1.5 (a backtest sweep found XRP's empirical
           optimum was 1.0x; deliberately set to 1.5 here at the user's
           request, see config.py's docstring). Skipped entirely if
           `symbol` isn't given.
        3. settings.atr_stop_multiplier -- the flat global default (1.5x).

    `symbol=None` (as in existing calculate_stop_loss() callers that never
    passed a symbol) always falls through to (3), preserving the original
    flat-1.5x behavior for anything that doesn't opt into per-symbol lookup.
    """
    if override is not None:
        return override
    if symbol:
        base = symbol.split("/")[0].upper()
        overrides = _parse_multiplier_overrides(settings.atr_multiplier_overrides)
        if base in overrides:
            return overrides[base]
    return settings.atr_stop_multiplier


DEFAULT_TP_RATIOS = (2.2, 2.6, 3.2, 4.5)       # R-multiples of stop_distance
DEFAULT_TP_CLOSE_PCTS = (25.0, 25.0, 25.0, 25.0)  # % of ORIGINAL size closed at each TP


def _parse_float_list(raw: str, expected_len: int, fallback: tuple[float, ...]) -> list[float]:
    """Parses "a,b,c,d" into [a, b, c, d]. Falls back to `fallback` whole-sale
    (not per-item) if the count is wrong or any item doesn't parse -- a
    malformed TP_RATIOS/TP_CLOSE_PCTS in .env should degrade to the known-good
    default, not silently produce a 3-rung or NaN-laced TP ladder."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) != expected_len:
        return list(fallback)
    try:
        return [float(p) for p in parts]
    except ValueError:
        return list(fallback)


def resolve_tp_ratios(override: Optional[str | list[float]] = None) -> list[float]:
    """
    Resolves the TP1-4 R-multiples (of stop_distance), selectable at input:

        1. `override` if given -- either a list of 4 floats, or a "a,b,c,d"
           string (e.g. --tp-ratios on the CLI) -- always wins.
        2. settings.tp_ratios (TP_RATIOS in .env), default "2.2,2.6,3.2,4.5".

    Falls back to DEFAULT_TP_RATIOS on any malformed input rather than
    raising -- a typo shouldn't crash every report.
    """
    if override is not None:
        if isinstance(override, str):
            return _parse_float_list(override, 4, DEFAULT_TP_RATIOS)
        return list(override)
    return _parse_float_list(settings.tp_ratios, 4, DEFAULT_TP_RATIOS)


def resolve_tp_close_pcts(override: Optional[str | list[float]] = None) -> list[float]:
    """
    Resolves what %% of the ORIGINAL position size to close at each of
    TP1-4, selectable at input (see trade_manager.py's partial-close
    handling) -- same resolution order as resolve_tp_ratios(). Ships
    default 25/25/25/25 (four equal slices, matches the original
    all-or-nothing-at-TP4 behavior's total exposure but exits gradually).
    Does NOT enforce the four values sum to exactly 100 -- summing to less
    than 100 deliberately leaves a runner past TP4; validate the sum
    yourself if you want a hard "must fully close by TP4" invariant.
    """
    if override is not None:
        if isinstance(override, str):
            return _parse_float_list(override, 4, DEFAULT_TP_CLOSE_PCTS)
        return list(override)
    return _parse_float_list(settings.tp_close_pcts, 4, DEFAULT_TP_CLOSE_PCTS)


VALID_TP_MODES = {"atr", "structural"}
DEFAULT_TP_MODE = "atr"


def resolve_tp_mode(override: Optional[str] = None) -> str:
    """
    Resolves whether TP1-4 come from the ATR R-multiple ladder ("atr",
    default) or real structural levels ("structural" -- see
    build_structural_tp_levels()). Same override > settings resolution
    order as resolve_tp_ratios(); an unrecognized value (typo in .env or
    --tp-mode) degrades to DEFAULT_TP_MODE rather than raising.
    """
    if override is not None:
        candidate = override.strip().lower()
        return candidate if candidate in VALID_TP_MODES else DEFAULT_TP_MODE
    candidate = (settings.tp_mode or "").strip().lower()
    return candidate if candidate in VALID_TP_MODES else DEFAULT_TP_MODE


def build_structural_tp_levels(
    direction: Direction,
    entry_price: float,
    stop_distance: float,
    candidate_levels: list[float],
    fallback_tps: list[float],
    min_r_multiple: float = 0.5,
    max_r_multiple: float = 50.0,
) -> list[float]:
    """
    Builds a TP1-4 ladder from real structural price levels -- nearest
    meaningful resistance/support ahead of price in the trade's direction --
    instead of fixed ATR R-multiples. This function only filters/sorts/fills;
    it doesn't know what a POC or FVG *is* -- the caller (engine.py) supplies
    whatever raw candidate prices it already computed (VAH/VAL/HVN/LVN,
    Fibonacci extension rungs, a swing high/low, an active FVG edge, ...).

    candidate_levels: every structural price worth considering as a target,
        regardless of source or whether it's actually ahead of price -- this
        function does that filtering itself (direction + min_r_multiple).
    fallback_tps: the normal ATR R-multiple TP1-4 (already computed by the
        caller), used to fill any of the 4 rungs that don't have a real
        structural candidate available -- structural mode never returns
        fewer than 4 targets or silently leaves a rung unset.
    min_r_multiple: a candidate closer than this many R (multiples of
        stop_distance) from entry is discarded as too close to be a
        meaningful target (likely just noise/spread), not because it's
        behind price.
    max_r_multiple: a candidate farther than this many R from entry is
        discarded too -- a backstop against a degenerate/clamped value from
        an upstream indicator masquerading as real structure (confirmed
        live: a Fibonacci extension's own "never return <= 0" floor once
        produced a "target" >99% below entry on a wide-range weekly swing --
        see engine.py's _real_down_extension_levels for the source-level
        fix; this is a second, source-agnostic line of defense). Default
        50R is generous -- far past any sane TP_RATIOS configuration --
        specifically so it never clips a real, if aggressive, target.

    Nearest-first fill order: TP1 is the closest qualifying candidate, TP4
    the farthest -- matching the ATR ladder's own near-to-far convention.
    """
    min_distance = stop_distance * min_r_multiple
    max_distance = stop_distance * max_r_multiple
    ahead: list[float] = []
    for level in candidate_levels:
        distance = abs(level - entry_price)
        if distance > max_distance:
            continue
        if direction == "long" and level > entry_price + min_distance:
            ahead.append(level)
        elif direction == "short" and level < entry_price - min_distance:
            ahead.append(level)

    ahead = sorted(set(ahead), key=lambda lvl: abs(lvl - entry_price))

    tps: list[float] = []
    for i in range(4):
        if i < len(ahead):
            tps.append(ahead[i])
        elif fallback_tps:
            tps.append(fallback_tps[min(i, len(fallback_tps) - 1)])
        else:
            tps.append(entry_price)

    # candidates and fallback rungs can interleave out of near-to-far order
    # once merged -- re-sort so TP1<TP2<TP3<TP4 (long) / TP1>TP2>TP3>TP4
    # (short) always holds, matching the ATR ladder's own invariant.
    tps.sort(reverse=(direction == "short"))
    return tps


def calculate_stop_loss(
    entry_price: float, atr: float, direction: Direction,
    symbol: Optional[str] = None, atr_multiplier_override: Optional[float] = None,
) -> float:
    """
    Price - ATR = long stop loss (below entry)
    Price + ATR = short stop loss (above entry)
    both scaled by the resolved ATR multiplier (see resolve_atr_multiplier;
    defaults to 1.5x if `symbol` isn't given and no override is set).
    """
    multiplier = resolve_atr_multiplier(symbol, atr_multiplier_override)
    distance = atr * multiplier
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
    atr_multiplier_override: Optional[float] = None,
) -> PositionPlan:
    atr_multiplier = resolve_atr_multiplier(symbol, atr_multiplier_override)
    stop_price = calculate_stop_loss(entry_price, atr, direction, symbol=symbol, atr_multiplier_override=atr_multiplier)
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
        atr_multiplier=atr_multiplier,
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
        f"Stop Loss:       {plan.stop_price}  ({plan.atr_multiplier}x ATR away)",
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
