"""
structure_report.py
--------------------
`--structure-report` (also included automatically by plain `--structure`):
the narrative MARKET STRUCTURE picture -- regime, POC/VAH/VAL and where
price sits relative to them, an FVG read, swing structure + Break of
Structure -- independent of --execute. This is a READ, not a trade
signal: it doesn't size a position, open a paper trade, or say buy/sell.

Different from --structure's own POC/resistance/support + 1W/1D/4H/1H
trigger system (structure_levels.py / structure_strategy.py) -- that one
stays as-is; this is a plain single-timeframe narrative read layered on
top of it, not a replacement.

Deliberately reuses regime.py / volume_profile_fixed.py / market_structure.py
/ fair_value_gap.py as-is; computes nothing new.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import regime as regime_module
from .indicators import volume_profile_fixed, market_structure, fair_value_gap

# This engine.py predates the significant-figure price rounding
# (_round_price) the current tool uses -- format_report here already
# prints prices with plain 6-decimal formatting (see Entry:/ATR: lines),
# so match that convention rather than importing a helper that doesn't exist.
_PRICE_DECIMALS = 6


@dataclass
class StructureReport:
    symbol: str
    timeframe: str
    price: float
    regime: "regime_module.RegimeResult"
    vp: "volume_profile_fixed.VolumeProfileResult"
    structure: "market_structure.MarketStructureResult"
    fvgs: list  # fair_value_gap.FVG, all detected (filled and unfilled) -- see _format_fvg_line


def build_structure_report(
    symbol: str, timeframe: str, highs, lows, closes, volumes,
) -> StructureReport:
    price = closes[-1]
    regime_result = regime_module.analyze(highs, lows, closes, volumes, higher_timeframes_aligned=False)
    vp_result = volume_profile_fixed.analyze(highs, lows, volumes, price=price)
    structure_result = market_structure.analyze(highs, lows, price=price)
    fvgs = fair_value_gap.detect_fvgs(highs, lows, closes)
    return StructureReport(
        symbol=symbol, timeframe=timeframe, price=price,
        regime=regime_result, vp=vp_result, structure=structure_result, fvgs=fvgs,
    )


def _format_fvg_line(fvgs: list) -> str:
    """Most recent UNFILLED gap, either direction -- this report is a plain
    read of what's real on the chart, not a trade call, so (unlike
    fair_value_gap.score_fvg) it doesn't filter to only the gap aligned with
    trend direction."""
    unfilled = [g for g in fvgs if not g.filled]
    if not unfilled:
        return "FVG: No unfilled gap"
    gap = unfilled[-1]
    kind = "Bullish" if gap.kind == "bullish" else "Bearish"
    top, bottom = round(gap.top, _PRICE_DECIMALS), round(gap.bottom, _PRICE_DECIMALS)
    return f"FVG: {kind} gap [{bottom}, {top}], unfilled"


def _price_location(price: float, poc: float, vah: float, val: float) -> str:
    if price > vah:
        return "ABOVE the value area (beyond VAH) -- outside the accepted range"
    if price < val:
        return "BELOW the value area (beyond VAL) -- outside the accepted range"
    if price > poc:
        return "inside the value area, above POC"
    if price < poc:
        return "inside the value area, below POC"
    return "at POC"


def format_structure_report(report: StructureReport) -> str:
    bar = "=" * 55
    lines = [bar, f"MARKET STRUCTURE -- {report.symbol} {report.timeframe}".center(55), bar, ""]

    lines.append(f"REGIME: {report.regime.icon} {report.regime.label}")
    lines.append(f"  Trend: {report.regime.trend_score}/10   Range: {report.regime.range_score}/10")
    lines.append("")

    vp = report.vp
    price = round(report.price, _PRICE_DECIMALS)
    poc, vah, val = round(vp.poc, _PRICE_DECIMALS), round(vp.vah, _PRICE_DECIMALS), round(vp.val, _PRICE_DECIMALS)
    lines.append(f"PRICE:  {price}")
    lines.append(f"POC:    {poc}")
    lines.append(f"VAH:    {vah}   (value area high)")
    lines.append(f"VAL:    {val}   (value area low)")
    lines.append(f"  -> price is {_price_location(report.price, vp.poc, vp.vah, vp.val)}")
    lines.append("")

    if report.regime.regime == "ranging":
        range_width = vp.vah - vp.val
        pct_through = ((report.price - vp.val) / range_width * 100) if range_width else 0.0
        lines.append("RANGE (market is classified RANGING):")
        lines.append(f"  {val}  <---- VAL ... POC {poc} ... VAH ---->  {vah}")
        lines.append(f"  Price is {pct_through:.0f}% through the range (0% = VAL, 100% = VAH)")
        lines.append("")
    elif report.regime.regime == "transitional":
        lines.append("Regime is TRANSITIONAL -- neither a clean range nor a clean trend right now.")
        lines.append("The POC/VAH/VAL levels above are still real, just don't read them as a settled range yet.")
        lines.append("")

    lines.append(_format_fvg_line(report.fvgs))
    lines.append("")

    st = report.structure
    lines.append(f"SWING STRUCTURE: {st.structure}")
    lines.append(f"BREAK OF STRUCTURE: {st.bos}")
    lines.append(bar)
    return "\n".join(lines)
