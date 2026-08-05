"""
confluence.py
--------------
Multi-timeframe confluence check, restricted to exactly four timeframes:
1H, 4H, 1D, 1W. Executes only when two or more of these four are giving
concurrent bullish or bearish signals -- with a percentage confidence score
that weights higher timeframes more heavily:

    1H = 10%   4H = 20%   1D = 30%   1W = 40%   (sums to 100%)

Confidence tiers (symmetric for both directions):
    >= 70%        -> Strong Buy / Strong Sell
    50% - 69%     -> Buy / Sell
    30% - 49%     -> Buy (Lower Confidence) / Sell (Lower Confidence)
    (< 30% isn't reachable with 2+ agreeing timeframes under these weights --
    the weakest possible qualifying pair, 1H+4H, is exactly 30%.)

A tie (2 timeframes bullish vs 2 bearish) is reported as WATCH -- flagged,
but no trade is planned. Fewer than 2 timeframes agreeing on either side is
NO TRADE.

Any timeframe outside {1h, 4h, 1d, 1w} passed in is ignored for this check
(it can still appear in the plain multi-timeframe report -- restricting to
these four is specific to the execution/confluence decision).

Note: an illustrative decision-matrix example (1H bullish, 4H/1D/1W
bearish) works out to 90% bearish confidence under this formula, which by
the symmetric tiers above lands in the Strong Sell tier, not the "Sell"
tier some example tables suggest for that exact row. This implementation
uses the symmetric percentage formula as the single source of truth rather
than a separately hand-labeled matrix, since the two disagree on that one
row -- flag it if you want the asymmetric labeling instead.

Entry timeframe (whose price/ATR actually get used for stop-loss and
position sizing) is always 1H when 1H is part of the agreeing set (fastest
timeframe = tightest, most current entry detail); otherwise the fastest
timeframe that IS part of the agreeing set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

BULLISH_SIGNALS = {"STRONG BUY", "BUY"}
BEARISH_SIGNALS = {"STRONG SELL", "SELL"}

MIN_CONFLUENCE_COUNT = 2

ALLOWED_TIMEFRAMES = ["1h", "4h", "1d", "1w"]  # order = fastest to slowest

# Simple integer weight (as specified: 1H=1, 4H=2, 1D=3, 1W=4) -- kept for
# reference/logging alongside the percentage confidence score below.
TIMEFRAME_WEIGHTS = {"1h": 1, "4h": 2, "1d": 3, "1w": 4}

# Percentage confidence contribution per timeframe -- the primary driver of
# the Strong Buy / Buy / Lower-Confidence tiering.
CONFIDENCE_PCT = {"1h": 10, "4h": 20, "1d": 30, "1w": 40}


@dataclass
class ConfluenceResult:
    direction: Optional[str]                    # "long" | "short" | None
    should_execute: bool
    tier: str                                   # "strong" | "normal" | "lower_confidence" | "watch" | "none"
    agreeing_timeframes: list[str] = field(default_factory=list)
    ignored_timeframes: list[str] = field(default_factory=list)
    entry_timeframe: Optional[str] = None
    confluence_score: int = 0                   # sum of TIMEFRAME_WEIGHTS for agreeing tfs
    confidence_pct: int = 0                      # sum of CONFIDENCE_PCT for agreeing tfs
    label: str = ""


def _direction_of(signal_label: str) -> Optional[str]:
    if signal_label in BULLISH_SIGNALS:
        return "bullish"
    if signal_label in BEARISH_SIGNALS:
        return "bearish"
    return None


def _confidence_label(direction: str, confidence_pct: int) -> tuple[str, str]:
    """Returns (tier, label_text) for a qualifying (>=2, majority) direction."""
    side = "Buy" if direction == "long" else "Sell"
    if confidence_pct >= 70:
        return "strong", f"Strong {side}"
    if confidence_pct >= 50:
        return "normal", side
    return "lower_confidence", f"{side} (Lower Confidence)"


def evaluate_confluence(signals_by_timeframe: dict[str, str]) -> ConfluenceResult:
    """
    signals_by_timeframe: e.g. {"1h": "BUY", "4h": "STRONG BUY", "1d": "WATCH", "1w": "SELL"}
    (pass each TradeSignal's `.signal` string, keyed by its timeframe. Keys
    are matched case-insensitively against 1h/4h/1d/1w; anything else is
    ignored for this decision.)
    """
    normalized = {tf.lower(): sig for tf, sig in signals_by_timeframe.items()}
    ignored = [tf for tf in signals_by_timeframe if tf.lower() not in ALLOWED_TIMEFRAMES]
    restricted = {tf: sig for tf, sig in normalized.items() if tf in ALLOWED_TIMEFRAMES}

    bullish_tfs = [tf for tf, sig in restricted.items() if _direction_of(sig) == "bullish"]
    bearish_tfs = [tf for tf, sig in restricted.items() if _direction_of(sig) == "bearish"]

    def _sorted(tfs: list[str]) -> list[str]:
        return sorted(tfs, key=lambda tf: ALLOWED_TIMEFRAMES.index(tf))

    if len(bullish_tfs) >= MIN_CONFLUENCE_COUNT and len(bullish_tfs) > len(bearish_tfs):
        agreeing = _sorted(bullish_tfs)
        confidence_pct = sum(CONFIDENCE_PCT[tf] for tf in agreeing)
        score = sum(TIMEFRAME_WEIGHTS[tf] for tf in agreeing)
        tier, side_label = _confidence_label("long", confidence_pct)
        return ConfluenceResult(
            direction="long", should_execute=True, tier=tier,
            agreeing_timeframes=agreeing, ignored_timeframes=ignored,
            entry_timeframe=agreeing[0], confluence_score=score, confidence_pct=confidence_pct,
            label=f"{side_label} -- {confidence_pct}% confidence ({', '.join(tf.upper() for tf in agreeing)} bullish)",
        )

    if len(bearish_tfs) >= MIN_CONFLUENCE_COUNT and len(bearish_tfs) > len(bullish_tfs):
        agreeing = _sorted(bearish_tfs)
        confidence_pct = sum(CONFIDENCE_PCT[tf] for tf in agreeing)
        score = sum(TIMEFRAME_WEIGHTS[tf] for tf in agreeing)
        tier, side_label = _confidence_label("short", confidence_pct)
        return ConfluenceResult(
            direction="short", should_execute=True, tier=tier,
            agreeing_timeframes=agreeing, ignored_timeframes=ignored,
            entry_timeframe=agreeing[0], confluence_score=score, confidence_pct=confidence_pct,
            label=f"{side_label} -- {confidence_pct}% confidence ({', '.join(tf.upper() for tf in agreeing)} bearish)",
        )

    if len(bullish_tfs) == len(bearish_tfs) and len(bullish_tfs) >= 1:
        return ConfluenceResult(
            direction=None, should_execute=False, tier="watch",
            agreeing_timeframes=[], ignored_timeframes=ignored,
            label=f"WATCH -- mixed signals, no majority ({len(bullish_tfs)} bullish vs {len(bearish_tfs)} bearish)",
        )

    return ConfluenceResult(
        direction=None, should_execute=False, tier="none",
        agreeing_timeframes=[], ignored_timeframes=ignored,
        label="NO TRADE -- fewer than 2 of {1H, 4H, 1D, 1W} in agreement",
    )


if __name__ == "__main__":
    for example in [
        {"1w": "STRONG BUY", "1d": "BUY"},                              # 70% -> Strong Buy
        {"1d": "BUY", "4h": "BUY"},                                     # 50% -> Buy
        {"4h": "BUY", "1h": "BUY"},                                     # 30% -> Buy (Lower Confidence)
        {"1h": "BUY", "4h": "SELL", "1d": "SELL", "1w": "SELL"},        # 90% bearish -> Strong Sell (see docstring note)
        {"1h": "BUY", "4h": "BUY", "1d": "SELL", "1w": "SELL"},         # tie -> WATCH
        {"1h": "BUY", "15m": "BUY", "1d": "WATCH"},                     # 15m ignored, only 1 qualifying -> NO TRADE
    ]:
        result = evaluate_confluence(example)
        print(example, "->", result.label, f"(ignored: {result.ignored_timeframes})" if result.ignored_timeframes else "")
