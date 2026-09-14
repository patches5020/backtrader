"""
regime.py
---------
Step 1 of the strategy: classify the market as TRENDING, RANGING, or
TRANSITIONAL *before* looking for an entry. Every --execute run starts
here; a TRANSITIONAL read is a hard "No Trade" regardless of what
confluence/the entry checklist would otherwise say.

Scoring -- points awarded to whichever side each condition favors:

    Condition                          Trending   Ranging
    ADX > 25                              +2         0
    ADX < 20                               0        +2
    EMA(17) has a strong slope             +2         0
    EMA(17) is flat                        0        +2
    Price stays outside the Value Area     +2         0
    Price oscillates around POC            0        +2
    ATR expanding                          +2         0
    ATR contracting                        0        +2
    2+ higher timeframes aligned           +3         0
    Multiple reversals between S/R         0        +3

Decision:
    Trend score >= 8  -> TRENDING
    Range score >= 8  -> RANGING
    Neither reaches 8 -> TRANSITIONAL (No Trade)

Deliberate dead zones (favor neither side, matching the no-trade filter's
own "ADX between 20-25" gap): ADX 20-25, an EMA slope that's neither
strong nor flat, price inside the Value Area but not close enough to POC
to call "oscillating," and ATR that's flat rather than clearly expanding
or contracting. These aren't oversights -- forcing every reading into one
camp or the other would make TRANSITIONAL nearly unreachable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional, Sequence

Regime = Literal["trending", "ranging", "transitional"]

TREND_SCORE_THRESHOLD = 8
RANGE_SCORE_THRESHOLD = 8

ADX_TREND_MIN = 25
ADX_RANGE_MAX = 20

EMA_SLOPE_LOOKBACK = 5
EMA_SLOPE_STRONG_PCT = 0.5   # |slope| over the lookback, as % of EMA -- "strong" above this
EMA_SLOPE_FLAT_PCT = 0.15    # at or below this counts as "flat"

POC_PROXIMITY_FRACTION = 0.5  # fraction of the VA half-width counted as "near POC"
REVERSAL_COUNT_THRESHOLD = 4  # swing points in the lookback window to call "multiple reversals"
REVERSAL_LOOKBACK = 30


@dataclass
class RegimeResult:
    regime: Regime
    trend_score: int
    range_score: int
    breakdown: list[str] = field(default_factory=list)  # human-readable line per condition
    icon: str = ""
    label: str = ""


def classify_ema_slope(ema_series: Sequence[float], lookback: int = EMA_SLOPE_LOOKBACK) -> tuple[str, float]:
    """Returns (state, slope_pct). state is 'strong', 'flat', or 'neutral'
    (neither strong nor flat -- a deliberate dead zone, see module docstring)."""
    if len(ema_series) < lookback + 1 or ema_series[-1 - lookback] == 0:
        return "neutral", 0.0

    slope_pct = (ema_series[-1] - ema_series[-1 - lookback]) / abs(ema_series[-1 - lookback]) * 100
    if abs(slope_pct) >= EMA_SLOPE_STRONG_PCT:
        return "strong", slope_pct
    if abs(slope_pct) <= EMA_SLOPE_FLAT_PCT:
        return "flat", slope_pct
    return "neutral", slope_pct


def classify_value_area_position(price: float, poc: float, vah: float, val: float) -> str:
    """Returns 'outside' (trending signal), 'oscillating' (ranging signal,
    close enough to POC), or 'inside' (neither -- inside the value area but
    not close to POC). Proximity is scaled to the value area's own width
    (half the VAH-VAL span), not a fixed % of price -- a fixed price-%
    threshold would swallow almost the entire value area for typical VA
    widths, making 'inside' nearly unreachable."""
    if price > vah or price < val:
        return "outside"

    half_width = (vah - val) / 2
    if half_width > 0 and abs(price - poc) <= half_width * POC_PROXIMITY_FRACTION:
        return "oscillating"
    return "inside"


def count_recent_reversals(swings, lookback_bars: int = REVERSAL_LOOKBACK) -> int:
    """Counts swing points (highs + lows) within the most recent `lookback_bars`
    -- a simple proxy for 'multiple reversals between support/resistance'.
    `swings` is the list returned by market_structure.find_swings/classify_structure."""
    if not swings:
        return 0
    max_index = swings[-1].index
    return sum(1 for s in swings if s.index >= max_index - lookback_bars)


def detect_regime(
    adx_value: float,
    ema_slope_state: str,           # "strong" | "flat" | "neutral"
    value_area_position: str,       # "outside" | "oscillating" | "inside"
    atr_state: str,                 # "expansion" | "contraction" | "flat"
    higher_timeframes_aligned: bool,
    reversal_count: int,
    reversal_threshold: int = REVERSAL_COUNT_THRESHOLD,
) -> RegimeResult:
    trend_score = 0
    range_score = 0
    breakdown = []

    if adx_value > ADX_TREND_MIN:
        trend_score += 2
        breakdown.append(f"ADX {adx_value:.1f} > {ADX_TREND_MIN} -> Trend +2")
    elif adx_value < ADX_RANGE_MAX:
        range_score += 2
        breakdown.append(f"ADX {adx_value:.1f} < {ADX_RANGE_MAX} -> Range +2")
    else:
        breakdown.append(f"ADX {adx_value:.1f} in {ADX_RANGE_MAX}-{ADX_TREND_MIN} dead zone -> 0")

    if ema_slope_state == "strong":
        trend_score += 2
        breakdown.append("EMA(17) slope strong -> Trend +2")
    elif ema_slope_state == "flat":
        range_score += 2
        breakdown.append("EMA(17) slope flat -> Range +2")
    else:
        breakdown.append("EMA(17) slope neither strong nor flat -> 0")

    if value_area_position == "outside":
        trend_score += 2
        breakdown.append("Price outside Value Area -> Trend +2")
    elif value_area_position == "oscillating":
        range_score += 2
        breakdown.append("Price oscillating around POC -> Range +2")
    else:
        breakdown.append("Price inside Value Area, not near POC -> 0")

    if atr_state == "expansion":
        trend_score += 2
        breakdown.append("ATR expanding -> Trend +2")
    elif atr_state == "contraction":
        range_score += 2
        breakdown.append("ATR contracting -> Range +2")
    else:
        breakdown.append("ATR flat -> 0")

    if higher_timeframes_aligned:
        trend_score += 3
        breakdown.append("2+ higher timeframes aligned -> Trend +3")
    else:
        breakdown.append("Higher timeframes not aligned -> 0 (trend side only)")

    if reversal_count >= reversal_threshold:
        range_score += 3
        breakdown.append(f"{reversal_count} reversals in lookback (>= {reversal_threshold}) -> Range +3")
    else:
        breakdown.append(f"{reversal_count} reversals in lookback (< {reversal_threshold}) -> 0 (range side only)")

    if trend_score >= TREND_SCORE_THRESHOLD:
        regime: Regime = "trending"
        icon, label = "\U0001F7E2", "TRENDING"
    elif range_score >= RANGE_SCORE_THRESHOLD:
        regime = "ranging"
        icon, label = "\U0001F7E1", "RANGING"
    else:
        regime = "transitional"
        icon, label = "\U0001F534", "NO TRADE (TRANSITION)"

    return RegimeResult(
        regime=regime, trend_score=trend_score, range_score=range_score,
        breakdown=breakdown, icon=icon, label=label,
    )


def analyze(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], volumes: Sequence[float],
    higher_timeframes_aligned: bool = False,
) -> RegimeResult:
    """Convenience wrapper: computes everything from raw OHLCV using the
    existing indicator modules, for real usage against live/fetched data."""
    from .indicators import atr_ema_variant1, adx as adx_module, volume_profile_fixed, market_structure

    ema_series = atr_ema_variant1.calculate_ema(closes)
    ema_slope_state, _ = classify_ema_slope(ema_series)

    adx_series, plus_di, minus_di = adx_module.calculate_adx(highs, lows, closes)
    adx_value = adx_series[-1]

    atr_series = atr_ema_variant1.calculate_atr(highs, lows, closes)
    _, atr_label = atr_ema_variant1.score_atr_expansion(atr_series)
    atr_state = {"Expansion": "expansion", "Contraction": "contraction"}.get(atr_label, "flat")

    vp_result = volume_profile_fixed.analyze(highs, lows, volumes, price=closes[-1])
    value_area_position = classify_value_area_position(closes[-1], vp_result.poc, vp_result.vah, vp_result.val)

    swings = market_structure.classify_structure(market_structure.find_swings(highs, lows))
    reversal_count = count_recent_reversals(swings)

    return detect_regime(
        adx_value=adx_value,
        ema_slope_state=ema_slope_state,
        value_area_position=value_area_position,
        atr_state=atr_state,
        higher_timeframes_aligned=higher_timeframes_aligned,
        reversal_count=reversal_count,
    )


def format_regime(result: RegimeResult) -> str:
    lines = [
        "=" * 49,
        f"MARKET REGIME: {result.icon} {result.label}".center(49),
        "=" * 49,
        f"Trend score: {result.trend_score}/10 (need >= {TREND_SCORE_THRESHOLD})",
        f"Range score: {result.range_score}/10 (need >= {RANGE_SCORE_THRESHOLD})",
        "-" * 49,
    ]
    lines.extend(result.breakdown)
    lines.append("=" * 49)
    return "\n".join(lines)


if __name__ == "__main__":
    # Strong uptrend example
    result = detect_regime(
        adx_value=32, ema_slope_state="strong", value_area_position="outside",
        atr_state="expansion", higher_timeframes_aligned=True, reversal_count=1,
    )
    print(format_regime(result))
    print()

    # Choppy range example
    result2 = detect_regime(
        adx_value=15, ema_slope_state="flat", value_area_position="oscillating",
        atr_state="contraction", higher_timeframes_aligned=False, reversal_count=5,
    )
    print(format_regime(result2))
    print()

    # Transitional example
    result3 = detect_regime(
        adx_value=22, ema_slope_state="neutral", value_area_position="inside",
        atr_state="flat", higher_timeframes_aligned=False, reversal_count=2,
    )
    print(format_regime(result3))
