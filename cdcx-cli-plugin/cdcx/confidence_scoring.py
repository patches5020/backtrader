"""
confidence_scoring.py
------------------------
Step 5 of the strategy: a weighted confidence score for the --execute flow,
distinct from both:
    - engine.py's per-signal `confidence` field (distance from the neutral
      midpoint on a single timeframe's blended score -- unrelated, still
      used for standalone single-timeframe reports).
    - confluence.py's `confidence_pct` (purely timeframe-weighted: 1h=10,
      4h=20, 1d=30, 1w=40 -- the simpler scheme used for the regime-neutral
      confluence check itself).

This scheme adds indicator-level confirmation on top of timeframe weight,
so a setup where the timeframes agree but the underlying indicators don't
actually confirm scores lower than one where everything lines up:

    Component        Weight
    Weekly              25
    Daily               20
    4H                  15
    1H                  10
    EMA/ATR             10
    RSI                  5
    ADX                  5
    FVG                  5
    Volume Profiles      5
    -----------------------
    Total              100

Timeframe weights count only if that timeframe's signal agrees with the
direction being evaluated. Indicator weights count only if that
component's score on the *entry timeframe's* TradeSignal actively confirms
the same direction (a neutral/zero reading does not count -- same
convention as entry_checklist.py).

Interpretation:
    90-100  Very Strong
    75-89   Strong
    60-74   Moderate
    40-59   Weak
    < 40    No Trade
"""

from __future__ import annotations

from dataclasses import dataclass, field

TIMEFRAME_WEIGHTS = {"1w": 25, "1d": 20, "4h": 15, "1h": 10}
INDICATOR_WEIGHTS = {"ema_atr": 10, "rsi": 5, "adx": 5, "fvg": 5, "volume_profiles": 5}

BULLISH_SIGNALS = {"STRONG BUY", "BUY"}
BEARISH_SIGNALS = {"STRONG SELL", "SELL"}


@dataclass
class WeightedConfidenceResult:
    score: int
    tier: str
    breakdown: list[str] = field(default_factory=list)


def _direction_of(signal_label: str) -> str | None:
    if signal_label in BULLISH_SIGNALS:
        return "bullish"
    if signal_label in BEARISH_SIGNALS:
        return "bearish"
    return None


def _confirms(score: float, direction: str) -> bool:
    return score > 0 if direction == "long" else score < 0


def _tier(score: int) -> str:
    if score >= 90:
        return "Very Strong"
    if score >= 75:
        return "Strong"
    if score >= 60:
        return "Moderate"
    if score >= 40:
        return "Weak"
    return "No Trade"


def calculate_weighted_confidence(
    signals_by_timeframe: dict[str, str], direction: str, entry_signal,
) -> WeightedConfidenceResult:
    """
    signals_by_timeframe: e.g. {"1h": "BUY", "4h": "STRONG BUY", "1d": "WATCH"}
    direction: "long" or "short" -- the direction being evaluated (from confluence)
    entry_signal: the entry timeframe's TradeSignal (see engine.py), used to
                  check individual indicator confirmation
    """
    score = 0
    breakdown: list[str] = []
    wanted_direction = "bullish" if direction == "long" else "bearish"

    for tf, weight in TIMEFRAME_WEIGHTS.items():
        signal = signals_by_timeframe.get(tf)
        if signal is None:
            breakdown.append(f"{tf.upper()}: not available -> +0")
            continue
        if _direction_of(signal) == wanted_direction:
            score += weight
            breakdown.append(f"{tf.upper()} agrees ({signal}) -> +{weight}")
        else:
            breakdown.append(f"{tf.upper()} does not agree ({signal}) -> +0")

    scores = entry_signal.scores

    if _confirms(scores.get("ema_trend", 0), direction):
        score += INDICATOR_WEIGHTS["ema_atr"]
        breakdown.append(f"EMA/ATR confirms -> +{INDICATOR_WEIGHTS['ema_atr']}")
    else:
        breakdown.append("EMA/ATR does not confirm -> +0")

    if _confirms(scores.get("rsi_momentum", 0), direction):
        score += INDICATOR_WEIGHTS["rsi"]
        breakdown.append(f"RSI confirms -> +{INDICATOR_WEIGHTS['rsi']}")
    else:
        breakdown.append("RSI does not confirm -> +0")

    if _confirms(scores.get("adx_trend_strength", 0), direction):
        score += INDICATOR_WEIGHTS["adx"]
        breakdown.append(f"ADX confirms -> +{INDICATOR_WEIGHTS['adx']}")
    else:
        breakdown.append("ADX does not confirm -> +0")

    if _confirms(scores.get("fair_value_gap", 0), direction):
        score += INDICATOR_WEIGHTS["fvg"]
        breakdown.append(f"FVG confirms -> +{INDICATOR_WEIGHTS['fvg']}")
    else:
        breakdown.append("FVG does not confirm -> +0")

    vp_confirms = _confirms(scores.get("fixed_volume_profile", 0), direction) or _confirms(
        scores.get("anchored_volume_profile", 0), direction
    )
    if vp_confirms:
        score += INDICATOR_WEIGHTS["volume_profiles"]
        breakdown.append(f"Volume Profile confirms (fixed or anchored) -> +{INDICATOR_WEIGHTS['volume_profiles']}")
    else:
        breakdown.append("Volume Profile does not confirm -> +0")

    return WeightedConfidenceResult(score=score, tier=_tier(score), breakdown=breakdown)


def format_weighted_confidence(result: WeightedConfidenceResult) -> str:
    lines = [
        "-" * 49,
        "WEIGHTED CONFIDENCE SCORE (Step 5)".center(49),
        "-" * 49,
    ]
    lines.extend(result.breakdown)
    lines.append("-" * 49)
    lines.append(f"Total: {result.score}/100 -- {result.tier}")
    lines.append("-" * 49)
    return "\n".join(lines)
