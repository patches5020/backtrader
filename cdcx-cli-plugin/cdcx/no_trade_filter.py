"""
no_trade_filter.py
---------------------
Step 4 of the strategy: a final safety gate, applied after regime
detection and the trending/ranging strategy setup, before any trade is
planned. Any single tripped condition blocks the trade outright.

Conditions checked:
    - ADX between 20 and 25 (the regime dead zone -- normally regime.py
      already keeps this out of both TRENDING and RANGING, but checked
      again here directly in case this filter is ever called on its own).
    - Higher timeframes disagree (redundant with confluence's own
      requirement, checked again here for defense in depth).
    - Price is in the middle of the range (only meaningful for a RANGING
      setup -- not near either boundary).
    - Risk-to-reward is below 2:1 -- a hard cutoff, stricter than
      risk_reward_score's partial-credit tiers in engine.py.
    - ATR is unusually low (current ATR well below its own recent average
      -- a proxy for "nothing is happening, don't force a trade").
    - Major scheduled news is imminent.

The news check CANNOT be automated here -- this project has no economic
calendar / news feed integration. `news_imminent` defaults to False (i.e.
"assumed clear") and must be set explicitly (e.g. a CLI flag) by whoever
actually knows the calendar. This is a real, acknowledged gap, not a
silent assumption.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

ADX_DEAD_ZONE = (20, 25)
MIN_RISK_REWARD = 2.0
ATR_LOW_THRESHOLD_PCT = -0.20  # current ATR this much below its recent average counts as "unusually low"


@dataclass
class NoTradeResult:
    blocked: bool
    reasons: list[str] = field(default_factory=list)


def is_atr_unusually_low(atr_series, lookback: int = 10) -> bool:
    if len(atr_series) < lookback + 1:
        return False
    recent_avg = sum(atr_series[-lookback - 1:-1]) / lookback
    if recent_avg == 0:
        return False
    change_pct = (atr_series[-1] - recent_avg) / recent_avg
    return change_pct <= ATR_LOW_THRESHOLD_PCT


def check_no_trade_filter(
    adx_value: float,
    higher_timeframes_agree: bool,
    price_in_middle_of_range: bool,
    risk_reward_ratio: Optional[float],
    atr_unusually_low: bool,
    news_imminent: bool = False,
) -> NoTradeResult:
    reasons = []

    if ADX_DEAD_ZONE[0] <= adx_value <= ADX_DEAD_ZONE[1]:
        reasons.append(f"ADX {adx_value:.1f} is in the {ADX_DEAD_ZONE[0]}-{ADX_DEAD_ZONE[1]} dead zone")

    if not higher_timeframes_agree:
        reasons.append("Higher timeframes disagree")

    if price_in_middle_of_range:
        reasons.append("Price is in the middle of the range")

    if risk_reward_ratio is not None and risk_reward_ratio < MIN_RISK_REWARD:
        reasons.append(f"Risk/Reward {risk_reward_ratio:.2f} is below the {MIN_RISK_REWARD}:1 minimum")

    if atr_unusually_low:
        reasons.append("ATR is unusually low")

    if news_imminent:
        reasons.append("Major scheduled news is imminent (manually flagged)")

    return NoTradeResult(blocked=len(reasons) > 0, reasons=reasons)


def format_no_trade_filter(result: NoTradeResult) -> str:
    lines = ["-" * 49, "NO-TRADE FILTER (Step 4)".center(49), "-" * 49]
    if not result.reasons:
        lines.append("No blocking conditions -- filter passed.")
    else:
        for reason in result.reasons:
            lines.append(f"[BLOCKED] {reason}")
    lines.append("-" * 49)
    return "\n".join(lines)
