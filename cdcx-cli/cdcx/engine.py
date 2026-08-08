"""
engine.py
---------
Orchestrates the full CDCX pipeline end to end:

    fetch OHLCV -> run every indicator module -> combine into the AI
    weighted score -> classify signal -> compute stop loss / take profits.

See indicators/*.py for each module's own scoring rules, and README.md for
the full flow diagram and weight table.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from .config import settings
from .exchange.cryptocom import CryptoComExchange, OHLCV
from .indicators import atr_ema_variant1
from .indicators import adx as adx_module
from .indicators import bollinger_bands
from .indicators import rsi as rsi_module
from .indicators import fibonacci
from .indicators import fair_value_gap
from .indicators import volume_profile_fixed
from .indicators import volume_profile_anchor
from .indicators import market_structure
from .indicators import candlestick_patterns
from . import regime as regime_module
from .utils.color import REGIME_TAGS, colorize_regime

# Indicator weights as specified. Note: these already summed to 120 (not
# 100) before ADX, Bollinger Bands, and Candlestick Patterns were added --
# see README.md for why the total is intentionally clamped rather than
# rescaled.
WEIGHTS = {
    "ema_trend": 15,
    "atr_expansion": 8,
    "adx_trend_strength": 10,
    "bollinger_bands": 10,
    "candlestick_patterns": 10,
    "rsi_momentum": 12,
    "fib_retracement": 12,
    "fib_extension": 8,
    "fair_value_gap": 15,
    "fixed_volume_profile": 10,
    "anchored_volume_profile": 10,
    "market_structure": 10,
    "risk_reward": 10,
}


@dataclass
class TradeSignal:
    symbol: str
    total_score: float
    signal: str
    stars: str
    scores: dict[str, float]
    labels: dict[str, str]
    entry: float
    atr: float
    stop_loss: float
    take_profits: dict[str, float]
    risk_reward_ratio: Optional[float]
    confidence: float
    regime: "regime_module.RegimeResult"
    # Decomposed scoring (see README "AI Score decomposition") -- total_score/
    # signal/stars above are kept unchanged for backward compatibility with
    # confluence.py, entry_checklist.py, and existing tests, which all expect
    # the 0-100 scale. These are additive, not replacements:
    direction_score: float = 0.0   # -100 (extremely bearish) .. +100 (extremely bullish), UNCLAMPED at 0
    trade_quality: float = 0.0     # 0-100: breadth of indicator confirmation (how many fired, not which way)
    execution_signal: str = ""     # the signal that should actually drive execution -- "NO TRADE" overrides
    execution_reason: str = ""     # why execution_signal differs from `signal`, if it does
    computed_at: float = 0.0       # unix timestamp -- proof entry/atr/stop/TP all came from one snapshot
    timeframe: str = ""            # which timeframe this ATR/entry/stop/TP snapshot was computed on
    atr_length: int = atr_ema_variant1.ATR_LENGTH  # actual ATR period; EMA and ATR periods are intentionally independent
    setup_score: float = 0.0       # 0-100: regime validity + direction strength + R:R + structure + confirmation
    decision: str = ""             # alias of execution_signal -- shown paired with `confidence`, reframed as
    # "Decision Confidence" in the report so a NO TRADE decision reads as "confident this ISN'T a trade,"
    # not "confident the trade will win" -- same underlying number, honest relabeling of what it measures.


def classify_signal(total_score: float) -> tuple[str, str]:
    if total_score >= 96:
        return "STRONG BUY", "*****"
    if total_score >= 80:
        return "BUY", "****."
    if total_score >= 60:
        return "WATCH", "***.."
    if total_score >= 40:
        return "NEUTRAL", "**..."
    if total_score >= 20:
        return "SELL", "*...."
    return "STRONG SELL", "....."


def risk_reward_score(entry: float, stop_loss: float, take_profit: float, max_weight: int = 10) -> float:
    risk = abs(entry - stop_loss)
    reward = abs(take_profit - entry)
    if risk == 0:
        return 0.0
    rr = reward / risk
    if rr < 1.5:
        return 0.0
    if rr < 2:
        return 5.0
    if rr < 3:
        return 8.0
    return float(max_weight)


def analyze(
    symbol: str = None, timeframe: str = None, limit: int = None, higher_timeframes_aligned: bool = False,
) -> TradeSignal:
    symbol = symbol or settings.default_symbol
    timeframe = timeframe or settings.default_timeframe
    limit = limit or settings.default_limit

    exchange = CryptoComExchange(settings.cryptocom_api_key, settings.cryptocom_api_secret)
    data: OHLCV = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    return analyze_ohlcv(symbol, data, higher_timeframes_aligned=higher_timeframes_aligned, timeframe=timeframe)


def analyze_ohlcv(
    symbol: str, data: OHLCV, higher_timeframes_aligned: bool = False, timeframe: str = "",
) -> TradeSignal:
    price = data.closes[-1]
    lookback = min(settings.swing_lookback, len(data.closes) - 1)

    # --- EMA / ATR / trend -------------------------------------------------
    ema_result = atr_ema_variant1.analyze(data.highs, data.lows, data.closes)
    trend = ema_result.trend
    # EMA trend can legitimately be neutral. Never coerce neutral into a
    # bearish/down direction; that silently contaminates Fibonacci extension
    # context and (previously) the stop/TP direction.
    extension_direction = "up" if trend == "bullish" else "down"

    # --- ADX (trend strength) ---------------------------------------------
    adx_result = adx_module.analyze(data.highs, data.lows, data.closes, trend=trend)

    # --- Bollinger Bands -----------------------------------------------
    bb_result = bollinger_bands.analyze(data.closes, trend=trend)

    # --- Candlestick patterns -----------------------------------------------
    pattern_matches = candlestick_patterns.detect_patterns(data.highs, data.lows, data.opens, data.closes)
    pattern_score, pattern_label = candlestick_patterns.score_patterns(pattern_matches, trend=trend)

    # --- RSI -----------------------------------------------------------
    rsi_series = rsi_module.calculate_rsi(data.closes)
    rsi_result = rsi_module.score_rsi(rsi_series[-1], trend=trend)

    # --- Fibonacci retracement + extension --------------------------------
    swing_high = max(data.highs[-lookback:])
    swing_low = min(data.lows[-lookback:])
    retr_result = fibonacci.score_retracement(price, swing_high, swing_low, trend=trend)
    ext_result = fibonacci.score_extension(
        price, swing_high, swing_low, direction=extension_direction, trend_confirmed=(trend != "neutral")
    )

    # --- Fair Value Gap ------------------------------------------------
    gaps = fair_value_gap.detect_fvgs(data.highs, data.lows, data.closes)
    fvg_result = fair_value_gap.score_fvg(gaps, price=price, trend=trend)

    # --- Volume profiles -------------------------------------------------
    fixed_vp_result = volume_profile_fixed.analyze(data.highs, data.lows, data.volumes, price=price)
    anchored_vp_result = volume_profile_anchor.analyze(
        data.highs, data.lows, data.closes, data.volumes, price=price, anchor_lookback=lookback
    )

    # --- Market structure ------------------------------------------------
    structure_result = market_structure.analyze(data.highs, data.lows, price=price)

    # --- Market Regime (Step 1 -- computed for every report) ---------------
    regime_result = regime_module.analyze(
        data.highs, data.lows, data.closes, data.volumes,
        higher_timeframes_aligned=higher_timeframes_aligned,
    )

    # --- Stop loss / take profit -----------------------------------------
    # TP1-4 are derived from the SAME stop_distance (ATR * 1.5 by default)
    # used for the stop loss. Never derive execution levels from an unrelated
    # historical swing.
    stop_distance = ema_result.atr * settings.atr_stop_multiplier
    TP_RATIOS = [2.2, 2.6, 3.2, 4.5]

    def _build_plan(plan_direction: str | None):
        if plan_direction is None:
            return price, {f"TP{i + 1}": price for i in range(4)}, 0.0, None
        stop = price - stop_distance if plan_direction == "up" else price + stop_distance
        tps = {}
        for i, ratio in enumerate(TP_RATIOS):
            raw_tp = price + stop_distance * ratio if plan_direction == "up" else price - stop_distance * ratio
            tps[f"TP{i + 1}"] = max(raw_tp, price * 0.01)
        rr = abs(tps["TP1"] - price) / abs(price - stop) if price != stop else None
        return stop, tps, risk_reward_score(price, stop, tps["TP1"]), rr

    # EMA trend is preferred. A neutral EMA is genuinely neutral; it must not
    # be coerced into "down". If the aggregate signal later proves clearly
    # directional, a second pass builds the directional ATR plan from that
    # signal instead.
    trade_direction = "up" if trend == "bullish" else "down" if trend == "bearish" else None
    stop_loss, take_profits, rr_score, rr_ratio = _build_plan(trade_direction)

    scores = {
        "ema_trend": ema_result.ema_score,
        "atr_expansion": ema_result.atr_score,
        "adx_trend_strength": adx_result.score,
        "bollinger_bands": bb_result.score,
        "candlestick_patterns": pattern_score,
        "rsi_momentum": rsi_result.score,
        "fib_retracement": retr_result.score,
        "fib_extension": ext_result.score,
        "fair_value_gap": fvg_result.score,
        "fixed_volume_profile": fixed_vp_result.score,
        "anchored_volume_profile": anchored_vp_result.score,
        "market_structure": structure_result.score,
        "risk_reward": rr_score,
    }
    labels = {
        "ema_trend": ema_result.ema_label,
        "atr_expansion": ema_result.atr_label,
        "adx_trend_strength": adx_result.label,
        "bollinger_bands": bb_result.label,
        "candlestick_patterns": pattern_label,
        "rsi_momentum": rsi_result.label,
        "fib_retracement": retr_result.label,
        "fib_extension": ext_result.label,
        "fair_value_gap": fvg_result.label,
        "fixed_volume_profile": fixed_vp_result.label,
        "anchored_volume_profile": anchored_vp_result.label,
        "market_structure": structure_result.label,
        "risk_reward": f"1 : {rr_ratio:.1f}" if rr_ratio else "N/A",
    }

    # Clamp each contribution to its weight, then clamp the total to 0-100.
    clamped = {k: max(-WEIGHTS[k], min(WEIGHTS[k], v)) for k, v in scores.items()}
    raw_total = sum(clamped.values())
    total = max(0.0, min(100.0, raw_total))
    signal, stars = classify_signal(total)

    # If EMA is neutral but the aggregate indicator score is clearly
    # directional, use that direction for the ATR plan and refresh only the
    # R:R contribution. This avoids inventing a bearish plan while preserving
    # a legitimate non-EMA directional setup.
    if trade_direction is None:
        if signal in {"STRONG BUY", "BUY"}:
            trade_direction = "up"
        elif signal in {"STRONG SELL", "SELL"}:
            trade_direction = "down"
        if trade_direction is not None:
            stop_loss, take_profits, rr_score, rr_ratio = _build_plan(trade_direction)
            scores["risk_reward"] = rr_score
            labels["risk_reward"] = f"1 : {rr_ratio:.1f}" if rr_ratio else "N/A"
            clamped = {k: max(-WEIGHTS[k], min(WEIGHTS[k], v)) for k, v in scores.items()}
            raw_total = sum(clamped.values())
            total = max(0.0, min(100.0, raw_total))
            signal, stars = classify_signal(total)

    # Confidence measures conviction strength -- how far the score sits from
    # the neutral midpoint (50), in either direction -- NOT the raw score
    # itself. Using the raw score directly was actively misleading: a
    # maximally bearish reading clamps total_score to 0, which would have
    # displayed as "0% confidence" right next to "SIGNAL: STRONG SELL" --
    # reading as "no conviction" when it actually means "maximum bearish
    # conviction." This fixes that: confidence is symmetric and highest at
    # either extreme (Strong Buy or Strong Sell), lowest near Neutral.
    confidence = round(abs(total - 50) * 2, 1)

    # --- Decomposed scoring (AI Score rebuild) ------------------------------
    # total_score/signal above stay 0-100 (unchanged, still used everywhere
    # else in the codebase), but that scale has a real flaw on its own: a
    # deeply bearish raw_total clamps to 0, which looks identical to "no
    # information at all" even though every indicator actively fired. These
    # three fields are the fix -- reported alongside, not instead of, the
    # existing ones:
    #   direction_score: signed -100..+100, clamped only in MAGNITUDE, never
    #       floored to 0 -- a strongly bearish setup now correctly shows a
    #       large negative number instead of colliding with "neutral."
    #   trade_quality: 0-100, breadth of confirmation (how many of the
    #       weighted indicators fired a nonzero score at all) -- distinct
    #       from direction_score, which measures net conviction in one
    #       direction, not how many indicators weighed in.
    direction_score = round(max(-100.0, min(100.0, raw_total)), 1)
    nonzero_count = sum(1 for v in clamped.values() if v != 0)
    trade_quality = round(nonzero_count / len(clamped) * 100, 1) if clamped else 0.0

    # --- Execution signal (regime is an absolute gate, not another vote) ---
    # `signal` above is purely indicator-derived and says nothing about
    # whether a trade should actually be taken -- printing "SIGNAL: STRONG
    # SELL" right next to "Market Regime: NO TRADE (TRANSITION)" was a real,
    # actively misleading contradiction. execution_signal is the field that
    # should drive any real decision: it force-overrides to "NO TRADE" when
    # the regime is transitional or the R:R doesn't clear the 2:1 minimum,
    # and only otherwise falls back to the indicator signal.
    execution_signal = signal
    execution_reason = ""
    if regime_result.regime == "transitional":
        execution_signal = "NO TRADE"
        execution_reason = "Market regime is transitional -- no trend or range edge to trade."
    elif rr_ratio is not None and rr_ratio < 2.0:
        execution_signal = "NO TRADE"
        execution_reason = f"Risk/Reward {rr_ratio:.2f} is below the 2.0:1 minimum."

    # --- Setup Score (replaces "AI SCORE" as the headline number) ----------
    # AI SCORE stayed genuinely broken even after the direction_score/
    # trade_quality split: it's still shown as one number that can sit at
    # 0.0 for a setup with nine indicators actively firing. Rather than
    # keep displaying a number that needs a caveat every time, Setup Score
    # is built from what actually determines whether a trade is worth
    # taking -- regime validity, direction strength, R:R quality, market
    # structure agreement, and indicator confirmation breadth -- not raw
    # indicator arithmetic. total_score/signal are kept internally
    # (confluence.py and entry_checklist.py still use them), just no longer
    # the headline number in the report.
    regime_validity_points = (
        0.0 if regime_result.regime == "transitional"
        else (max(regime_result.trend_score, regime_result.range_score) / 10) * 30
    )
    direction_points = (abs(direction_score) / 100) * 30
    if rr_ratio is None or rr_ratio < 1.5:
        rr_points = 0.0
    elif rr_ratio < 2.0:
        rr_points = 10.0
    else:
        rr_points = 20.0
    structure_score = clamped.get("market_structure", 0)
    structure_points = 10.0 if (structure_score > 0 and direction_score > 0) or (
        structure_score < 0 and direction_score < 0
    ) else 0.0
    quality_points = (trade_quality / 100) * 10
    setup_score = round(regime_validity_points + direction_points + rr_points + structure_points + quality_points, 1)

    return TradeSignal(
        symbol=symbol,
        total_score=round(total, 1),
        signal=signal,
        stars=stars,
        scores=clamped,
        labels=labels,
        entry=price,
        atr=round(ema_result.atr, 8),
        stop_loss=round(stop_loss, 2),
        take_profits={k: round(v, 2) for k, v in take_profits.items()},
        risk_reward_ratio=round(rr_ratio, 2) if rr_ratio else None,
        confidence=confidence,
        regime=regime_result,
        direction_score=direction_score,
        trade_quality=trade_quality,
        execution_signal=execution_signal,
        execution_reason=execution_reason,
        computed_at=time.time(),
        timeframe=timeframe,
        atr_length=atr_ema_variant1.ATR_LENGTH,
        setup_score=setup_score,
        decision=execution_signal,
    )


def format_report(signal: TradeSignal) -> str:
    lines = []
    bar = "=" * 49
    lines.append(bar)
    lines.append("CDCX AI TRADE ANALYSIS".center(49))
    lines.append(bar)
    lines.append("")
    lines.append(f"Symbol: {signal.symbol}   Timeframe: {signal.timeframe or 'n/a'}")
    lines.append(f"Snapshot: {signal.computed_at:.0f}  (entry/atr/stop/TP all computed from this single pull)")
    lines.append("")

    # --- Regime -> Direction -> Quality -> Decision, in that order. This
    # is the fix for showing "SIGNAL: STRONG SELL" right next to "Market
    # Regime: NO TRADE" -- regime is checked FIRST and is an absolute gate;
    # everything below it is diagnostic context, not itself a trade call.
    # Emoji icon (🟢/🟡/🔴) is the primary indicator; the bracketed tag +
    # ANSI color are a fallback for terminals/fonts that don't render the
    # emoji glyph (seen in some WSL/mintty setups) -- colorize_regime() is a
    # no-op (plain text) when stdout isn't a TTY or NO_COLOR is set.
    regime_tag = REGIME_TAGS.get(signal.regime.regime, "")
    regime_text = f"{signal.regime.icon} [{regime_tag}] {signal.regime.label}"
    lines.append(f"MARKET REGIME: {colorize_regime(regime_text, signal.regime.regime)}")
    lines.append(f"  Trend: {signal.regime.trend_score}/10   Range: {signal.regime.range_score}/10")
    lines.append("")

    if signal.direction_score > 10:
        bias = "BULLISH"
    elif signal.direction_score < -10:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"
    lines.append(f"DIRECTION BIAS: {bias}  (direction score: {signal.direction_score:+.1f} / 100)")
    lines.append(f"TRADE QUALITY: {signal.trade_quality:.0f}/100  (breadth of indicator confirmation)")
    lines.append(f"SETUP SCORE: {signal.setup_score:.0f}/100  (regime validity + direction + R:R + structure + confirmation)")
    lines.append("")

    lines.append(f"DECISION: {signal.decision}")
    # Decision Confidence is confidence IN THE DECISION shown above -- for a
    # NO TRADE decision that means "how clearly this isn't a trade," not
    # "how likely a trade would win." Same number as before (distance from
    # the neutral midpoint), reframed so it doesn't contradict a NO TRADE
    # call the way a bare "Confidence: 100%" used to.
    lines.append(f"DECISION CONFIDENCE: {signal.confidence}%")
    if signal.execution_reason:
        lines.append(f"REASON: {signal.execution_reason}")
    lines.append("")
    lines.append("-" * 49)

    for key, weight in WEIGHTS.items():
        score = signal.scores[key]
        label = signal.labels.get(key, "")
        sign = "+" if score >= 0 else ""
        lines.append(f"{key.replace('_', ' ').title():<24} {sign}{score:g}  ({label})")

    lines.append("")
    lines.append("-" * 49)
    lines.append(f"ATR Timeframe: {signal.timeframe or 'n/a'}   ATR Length: {signal.atr_length}")
    lines.append(f"Entry:       {signal.entry:.6f}")
    lines.append(f"ATR:         {signal.atr:.6f}")
    atr_x_multiplier = abs(signal.entry - signal.stop_loss)
    lines.append(f"ATR x mult:  {atr_x_multiplier:.6f}  (multiplier x ATR -- the distance added/subtracted for the stop)")
    lines.append(f"Stop Loss:   {signal.stop_loss}")
    for tp_name, tp_price in signal.take_profits.items():
        lines.append(f"{tp_name}: {tp_price}")
    lines.append("")
    lines.append(f"Risk/Reward: 1 : {signal.risk_reward_ratio}")
    lines.append(bar)
    return "\n".join(lines)
