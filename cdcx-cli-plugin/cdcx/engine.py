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

# Indicator weights as specified. Note: these already summed to 120 (not
# 100) before ADX and Bollinger Bands were added -- see README.md for why
# the total is intentionally clamped rather than rescaled.
WEIGHTS = {
    "ema_trend": 15,
    "atr_expansion": 8,
    "adx_trend_strength": 10,
    "bollinger_bands": 10,
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


def analyze(symbol: str = None, timeframe: str = None, limit: int = None) -> TradeSignal:
    symbol = symbol or settings.default_symbol
    timeframe = timeframe or settings.default_timeframe
    limit = limit or settings.default_limit

    exchange = CryptoComExchange(settings.cryptocom_api_key, settings.cryptocom_api_secret)
    data: OHLCV = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    return analyze_ohlcv(symbol, data)


def analyze_ohlcv(symbol: str, data: OHLCV) -> TradeSignal:
    price = data.closes[-1]
    lookback = min(settings.swing_lookback, len(data.closes) - 1)

    # --- EMA / ATR / trend -------------------------------------------------
    ema_result = atr_ema_variant1.analyze(data.highs, data.lows, data.closes)
    trend = ema_result.trend
    direction = "up" if trend == "bullish" else "down"

    # --- ADX (trend strength) ---------------------------------------------
    adx_result = adx_module.analyze(data.highs, data.lows, data.closes, trend=trend)

    # --- Bollinger Bands -----------------------------------------------
    bb_result = bollinger_bands.analyze(data.closes, trend=trend)

    # --- RSI -----------------------------------------------------------
    rsi_series = rsi_module.calculate_rsi(data.closes)
    rsi_result = rsi_module.score_rsi(rsi_series[-1], trend=trend)

    # --- Fibonacci retracement + extension --------------------------------
    swing_high = max(data.highs[-lookback:])
    swing_low = min(data.lows[-lookback:])
    retr_result = fibonacci.score_retracement(price, swing_high, swing_low, trend=trend)
    ext_result = fibonacci.score_extension(
        price, swing_high, swing_low, direction=direction, trend_confirmed=(trend != "neutral")
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

    # --- Stop loss / take profit -----------------------------------------
    stop_loss = (
        price - ema_result.atr * settings.atr_stop_multiplier
        if direction == "up"
        else price + ema_result.atr * settings.atr_stop_multiplier
    )
    ext_levels = fibonacci.calculate_extension(swing_high, swing_low, direction)
    take_profits = {
        "TP1": ext_levels["1.272"],
        "TP2": ext_levels["1.414"],
        "TP3": ext_levels["1.618"],
        "TP4": ext_levels["2.618"],
    }
    rr_score = risk_reward_score(price, stop_loss, take_profits["TP1"])
    rr_ratio = abs(take_profits["TP1"] - price) / abs(price - stop_loss) if price != stop_loss else None

    scores = {
        "ema_trend": ema_result.ema_score,
        "atr_expansion": ema_result.atr_score,
        "adx_trend_strength": adx_result.score,
        "bollinger_bands": bb_result.score,
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
        "rsi_momentum": rsi_result.label,
        "fib_retracement": retr_result.label,
        "fib_extension": ext_result.label,
        "fair_value_gap": fvg_result.label,
        "fixed_volume_profile": fixed_vp_result.label,
        "anchored_volume_profile": anchored_vp_result.label,
        "market_structure": structure_result.label,
        "risk_reward": f"1 : {rr_ratio:.1f}" if rr_ratio else "N/A",
    }

    # Clamp each contribution to its weight, then clamp the total to 0-100
    clamped = {k: max(-WEIGHTS[k], min(WEIGHTS[k], v)) for k, v in scores.items()}
    total = max(0.0, min(100.0, sum(clamped.values())))
    signal, stars = classify_signal(total)

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
        confidence=round(total, 1),
    )


def format_report(signal: TradeSignal) -> str:
    lines = []
    bar = "=" * 49
    lines.append(bar)
    lines.append("CDCX AI TRADE ANALYSIS".center(49))
    lines.append(bar)
    lines.append("")
    lines.append(f"Symbol: {signal.symbol}")
    lines.append("")

    for key, weight in WEIGHTS.items():
        score = signal.scores[key]
        label = signal.labels.get(key, "")
        sign = "+" if score >= 0 else ""
        lines.append(f"{key.replace('_', ' ').title():<24} {sign}{score:g}  ({label})")

    lines.append("")
    lines.append("-" * 49)
    lines.append(f"AI SCORE = {signal.total_score}")
    lines.append(signal.stars)
    lines.append("")
    lines.append(f"SIGNAL: {signal.signal}")
    lines.append("")
    lines.append(f"Entry: {signal.entry}")
    lines.append(f"Stop Loss: {signal.stop_loss}")
    for tp_name, tp_price in signal.take_profits.items():
        lines.append(f"{tp_name}: {tp_price}")
    lines.append("")
    lines.append(f"Risk/Reward: 1 : {signal.risk_reward_ratio}")
    lines.append(f"Confidence: {signal.confidence}%")
    lines.append(bar)
    return "\n".join(lines)
