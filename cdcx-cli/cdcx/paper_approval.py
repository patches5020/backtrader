"""
paper_approval.py
------------------
Formats the "PAPER TRADE APPROVAL" report: one consolidated snapshot of
every gate a paper trade already cleared -- multi-timeframe direction,
market state, POC/FVG/HVN/LVN, the Fibonacci retracement ladder, the
ATR-based stop/TP ladder, and position sizing -- followed by the
APPROVE/REJECT prompt that gates sending the same trade live.

This assembles data that's already computed elsewhere in the pipeline
(engine.TradeSignal, risk.PositionPlan) into one printable report; it
doesn't compute anything new itself, except mapping each timeframe's
Strong Buy/Buy/Watch/Neutral/Sell/Strong Sell read into BULLISH / BEARISH /
NEUTRAL for display.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .config import settings
from . import risk as risk_module

_DIRECTION_LABELS = {
    "STRONG BUY": "BULLISH", "BUY": "BULLISH",
    "STRONG SELL": "BEARISH", "SELL": "BEARISH",
    "WATCH": "NEUTRAL", "NEUTRAL": "NEUTRAL",
}

# Display order for the Fibonacci ladder -- the four "significant" levels
# from fibonacci.py's retracement ratios (0.236/0.786 are shallow/deep
# outliers already de-weighted there; this report shows the core four).
_FIB_DISPLAY_ORDER = ("0.382", "0.5", "0.618", "0.786")


def direction_label(signal: Optional[str]) -> str:
    """Maps an indicator SIGNAL string (STRONG BUY, WATCH, ...) to
    BULLISH/BEARISH/NEUTRAL for the timeframe-direction rows. Unknown or
    missing input reports as 'N/A' rather than guessing."""
    if not signal:
        return "N/A"
    return _DIRECTION_LABELS.get(signal.upper(), "N/A")


@dataclass
class PaperTradeApproval:
    symbol: str
    direction: str  # "long" | "short"
    timeframe_directions: dict = field(default_factory=dict)  # {"1h": "BULLISH", ...}, "N/A" if not evaluated
    market_state: str = ""
    poc: float = 0.0
    fvg_top: Optional[float] = None
    fvg_bottom: Optional[float] = None
    hvn: float = 0.0
    lvn: float = 0.0
    fib_levels: dict = field(default_factory=dict)
    atr: float = 0.0
    atr_stop_multiplier: float = 1.5
    entry: float = 0.0
    stop: float = 0.0
    tp_levels: list = field(default_factory=list)  # [TP1, TP2, ...], whatever the strategy produced
    tp_close_pcts: list = field(default_factory=list)  # % of ORIGINAL size closed at each TP -- see
                                                         # trade_manager.py's partial-close rules (G/H)
    risk_pct: float = 2.0
    position_size: float = 0.0
    notional_value: float = 0.0
    result: str = "PASS"  # "PASS" | "FAIL" -- whether this paper trade cleared every gate


def build_paper_trade_approval(
    symbol: str,
    direction: str,
    signal,                       # engine.TradeSignal for the entry timeframe
    plan,                         # risk.PositionPlan
    tp_levels: list,
    timeframe_directions: Optional[dict] = None,
    market_state: Optional[str] = None,
    risk_pct: Optional[float] = None,
    tp_close_pcts: Optional[list] = None,
    result: str = "PASS",
) -> PaperTradeApproval:
    """
    Assembles a PaperTradeApproval from objects the pipeline already
    computed -- `signal` supplies POC/FVG/HVN/LVN/Fibonacci/ATR (see
    engine.TradeSignal's raw-structural-level fields), `plan` supplies
    entry/stop/size (see risk.PositionPlan). Every `signal.*` read below
    uses getattr() with a safe default rather than assuming the full
    TradeSignal shape, so this still degrades gracefully if it's ever
    passed a partial/mock signal instead.
    """
    tf_directions = dict(timeframe_directions or {})
    # Always make sure the actual entry timeframe's own read is represented,
    # even if the caller didn't pass a full 1h/4h/1d/1w map (e.g. the ranging
    # path, which doesn't require multi-timeframe confluence).
    entry_tf = getattr(signal, "timeframe", "") or ""
    if entry_tf:
        tf_directions.setdefault(entry_tf, direction_label(getattr(signal, "signal", None)))

    regime = getattr(signal, "regime", None)
    default_market_state = getattr(regime, "label", "") if regime is not None else ""

    return PaperTradeApproval(
        symbol=symbol,
        direction=direction,
        timeframe_directions=tf_directions,
        market_state=market_state if market_state is not None else default_market_state,
        poc=getattr(signal, "poc", 0.0),
        fvg_top=getattr(signal, "fvg_top", None),
        fvg_bottom=getattr(signal, "fvg_bottom", None),
        hvn=getattr(signal, "hvn", 0.0),
        lvn=getattr(signal, "lvn", 0.0),
        fib_levels=getattr(signal, "fib_levels", {}) or {},
        atr=getattr(signal, "atr", 0.0),
        # plan.atr_multiplier (risk.PositionPlan) is what actually determined
        # this trade's stop/size -- the authoritative value, not the flat
        # global default (per-symbol overrides mean these can differ).
        atr_stop_multiplier=getattr(plan, "atr_multiplier", settings.atr_stop_multiplier),
        entry=plan.entry_price,
        stop=plan.stop_price,
        tp_levels=list(tp_levels),
        tp_close_pcts=list(tp_close_pcts) if tp_close_pcts is not None else risk_module.resolve_tp_close_pcts(),
        risk_pct=risk_pct if risk_pct is not None else settings.risk_pct_per_trade,
        position_size=plan.position_size,
        notional_value=plan.notional_value,
        result=result,
    )


def _fmt_price(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"${value:,.2f}"


def format_paper_trade_approval(a: PaperTradeApproval) -> str:
    lines = [
        "=" * 60,
        "PAPER TRADE APPROVAL".center(60),
        "=" * 60,
        f"Symbol:    {a.symbol}",
        f"Direction: {a.direction.upper()}",
        "",
    ]

    for tf in ("1h", "4h", "1d", "1w"):
        lines.append(f"{tf.upper():<4} {a.timeframe_directions.get(tf, 'N/A')}")

    lines += [
        "",
        f"Market State: {a.market_state}",
        "",
        f"POC:  {_fmt_price(a.poc)}",
    ]
    if a.fvg_top is not None and a.fvg_bottom is not None:
        lines.append(f"FVG:  {_fmt_price(a.fvg_bottom)} - {_fmt_price(a.fvg_top)}")
    else:
        lines.append("FVG:  no active aligned gap")
    lines.append(f"HVN:  {_fmt_price(a.hvn)}")
    lines.append(f"LVN:  {_fmt_price(a.lvn)}")

    lines += ["", "FIBONACCI:"]
    any_fib = False
    for ratio in _FIB_DISPLAY_ORDER:
        level = a.fib_levels.get(ratio)
        if level is not None:
            any_fib = True
            lines.append(f"  {float(ratio):.3f} = {_fmt_price(level)}")
    if not any_fib:
        lines.append("  n/a")

    lines += [
        "",
        f"ATR:        {_fmt_price(a.atr)}",
        f"Entry:      {_fmt_price(a.entry)}",
        f"Stop Loss:  {_fmt_price(a.stop)}  ({a.atr_stop_multiplier}x ATR)",
    ]
    last_index = len(a.tp_levels) - 1
    for i, tp in enumerate(a.tp_levels):
        if i == last_index:
            action = "close 100% of remainder -- position fully closed"
        else:
            close_pct = a.tp_close_pcts[i] if i < len(a.tp_close_pcts) else None
            close_str = f"close {close_pct:g}%" if close_pct is not None else "close --"
            stop_note = "stop to breakeven" if i == 0 else f"stop to TP{i}"
            action = f"{close_str} -> {stop_note}"
        lines.append(f"TP{i + 1}:        {_fmt_price(tp)}   ({action})")

    lines += [
        "",
        f"Portfolio Risk: {a.risk_pct:.1f}% maximum",
        f"Position Size:  {a.position_size:g} units (~{_fmt_price(a.notional_value)} notional)",
        "",
        f"PAPER RESULT: {a.result}",
        "",
        "LIVE EXECUTION:",
        "[ APPROVE ]   [ REJECT ]",
        "(pass --live to be prompted for this before anything real is sent)",
        "=" * 60,
    ]
    return "\n".join(lines)
