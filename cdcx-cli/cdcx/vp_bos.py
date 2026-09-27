"""
vp_bos.py
---------
VP-BOS -- Volume Profile Break of Structure.

    Raw BOS  = structural event        (market_structure.py's flag)
    VP-BOS   = structural event + volume-profile acceptance beyond the level
    BOS-FAILED = structural event + rejection (closed back through the level)

A Break of Structure becomes Volume-Profile-confirmed when price CLOSES
beyond a validated swing level and then shows acceptance in the new price
area. A break that quickly returns through the level is a failed BOS, not
a VP-BOS. Volume is never required to detect the raw break itself.

Reuses, unchanged:
  - market_structure.analyze          -> swings + raw BOS flag
  - bos_state.classify_bos_state      -> confirmed break / continuation /
                                         retest held / retest failed
  - volume_profile_fixed              -> POC of the pre-break auction vs
                                         the post-break auction

Acceptance evidence (all on CLOSED bars only -- the still-forming candle
is dropped, so a mid-candle poke through a level is never "confirmed"):
  E1 sustained  -- >= MIN_POST_BARS closed bars since the break, and at
                   least SUSTAIN_RATIO of them closed beyond the level
                   (REQUIRED)
  E2 new HVN    -- the post-break bars' own volume profile has its POC
                   beyond the broken level (business is being done there)
  E3 POC shift  -- the rolling profile's POC migrated in the break
                   direction by more than POC_SHIFT_ATR x ATR
  E4 retest     -- bos_state reports the broken level retested and held
  VP-BOS = E1 and (E2 or E3 or E4)

INFORMATIONAL ONLY, like bos_state.py / structure_report.py: never read by
confluence.py, entry_checklist.py, no_trade_gate.py or any entry / SL / TP
/ R:R / sizing calculation. Its own "VP-BOS confluence" count is advisory.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, Sequence

from . import bos_state as bos_state_module
from . import no_trade_gate
from .indicators import atr_ema_variant1
from .indicators import market_structure
from .indicators import volume_profile_fixed

MIN_POST_BARS = 3
SUSTAIN_RATIO = 2 / 3
POC_SHIFT_ATR = 0.5
PROFILE_BARS = volume_profile_fixed.DEFAULT_LOOKBACK
NO_BREAK_MIGRATION_BARS = 10  # POC-direction baseline when there is no break

TIMEFRAMES = ("1w", "1d", "4h", "1h")


@dataclass
class VpBos:
    signal: str                   # VP-BOS-BULL/BEAR, BOS-RETEST, BOS-UNCONFIRMED,
                                  # BOS-FAILED, BOS-BULL/BEAR (raw, no close), NONE
    vp: str                       # ACCEPT | HOLD | PENDING | REJECT | --
    status: str                   # BULLISH | BEARISH | TRANSITIONAL
    structure: str                # e.g. "LL/LH/HL/LH"
    poc_direction: str            # "up" | "down" | "flat"
    direction: Optional[str] = None      # "up" | "down" for a confirmed break
    level_price: Optional[float] = None
    evidence: dict = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


def _drop_forming_bar(timestamps, highs, lows, closes, volumes, timeframe, now, market):
    if no_trade_gate.last_bar_is_forming(timestamps, timeframe, now, market=market):
        return highs[:-1], lows[:-1], closes[:-1], volumes[:-1]
    return highs, lows, closes, volumes


def _poc(highs, lows, volumes) -> Optional[float]:
    if len(highs) < 2:
        return None
    try:
        histogram = volume_profile_fixed.build_volume_profile(highs, lows, volumes)
    except ValueError:
        return None
    poc, _, _ = volume_profile_fixed.calculate_poc_vah_val(histogram)
    return poc


def _poc_direction(highs, lows, volumes, baseline_end: int, atr: float) -> str:
    """POC of the latest PROFILE_BARS vs the PROFILE_BARS ending at
    `baseline_end` -- same window length, so a shift is migration, not a
    different lookback."""
    n = len(highs)
    now_poc = _poc(highs[max(0, n - PROFILE_BARS):], lows[max(0, n - PROFILE_BARS):], volumes[max(0, n - PROFILE_BARS):])
    start = max(0, baseline_end - PROFILE_BARS)
    then_poc = _poc(highs[start:baseline_end], lows[start:baseline_end], volumes[start:baseline_end])
    if now_poc is None or then_poc is None:
        return "flat"
    shift = now_poc - then_poc
    if shift > POC_SHIFT_ATR * atr:
        return "up"
    if shift < -POC_SHIFT_ATR * atr:
        return "down"
    return "flat"


def _first_break_index(highs, lows, closes, swings, direction: str, level: float) -> Optional[int]:
    """FIRST closed bar (after the swing formed, inside the breakout
    lookback) that closed beyond the level by the same 0.25x ATR margin
    bos_state/detect_breakout use. detect_breakout returns the MOST RECENT
    such bar, which would make a long-running break look only 1 bar old."""
    from . import structure_levels

    kind = "high" if direction == "up" else "low"
    swing_idx = max((s.index for s in swings if s.kind == kind and s.price == level), default=-1)
    atr_series = atr_ema_variant1.calculate_atr(highs, lows, closes)
    n = len(closes)
    start = max(swing_idx + 1, atr_ema_variant1.ATR_LENGTH, n - structure_levels.BREAKOUT_LOOKBACK)
    margin = structure_levels.BREAKOUT_ATR_MULTIPLE
    for i in range(start, n):
        if direction == "up" and closes[i] > level + margin * atr_series[i]:
            return i
        if direction == "down" and closes[i] < level - margin * atr_series[i]:
            return i
    return None


def classify_vp_bos(
    timestamps: Sequence[int], highs: Sequence[float], lows: Sequence[float],
    closes: Sequence[float], volumes: Sequence[float], timeframe: str, now: Optional[float] = None,
    market: str = no_trade_gate.MARKET_24X7,
) -> VpBos:
    now = time.time() if now is None else now
    highs, lows, closes, volumes = _drop_forming_bar(
        list(timestamps), list(highs), list(lows), list(closes), list(volumes), timeframe, now, market,
    )

    ms = market_structure.analyze(highs, lows, price=closes[-1])
    structure = "/".join(s.label for s in ms.swings[-4:] if s.label) or "--"
    atr = atr_ema_variant1.calculate_atr(highs, lows, closes)[-1]
    bos = bos_state_module.classify_bos_state(ms, highs, lows, closes, volumes)

    if bos.state == "no_break":
        poc_dir = _poc_direction(highs, lows, volumes, len(highs) - NO_BREAK_MIGRATION_BARS, atr)
        raw = {"Bullish BOS": "BOS-BULL", "Bearish BOS": "BOS-BEAR"}.get(ms.bos, "NONE")
        reason = (
            f"Raw {ms.bos} flag, but no closed bar beyond the swing level by 0.25x ATR yet."
            if raw != "NONE" else "No confirmed swing break in the lookback window."
        )
        return VpBos(signal=raw, vp="--", status="TRANSITIONAL", structure=structure,
                     poc_direction=poc_dir, reasons=[reason])

    direction, level = bos.direction, bos.level_price
    side = "BULL" if direction == "up" else "BEAR"
    beyond = (lambda c: c > level) if direction == "up" else (lambda c: c < level)

    b = _first_break_index(highs, lows, closes, ms.swings, direction, level)
    if b is None:  # bos_state fell back to the other side's window -- treat as unconfirmed
        b = len(closes) - 1
    poc_dir = _poc_direction(highs, lows, volumes, b, atr)

    if bos.state == "retest_failed":
        return VpBos(signal="BOS-FAILED", vp="REJECT", status="TRANSITIONAL", structure=structure,
                     poc_direction=poc_dir, direction=direction, level_price=level,
                     reasons=[f"{side} break of {level:.6f} closed back through the level -- rejected."] + bos.reasons)

    post_closes = closes[b:]
    post_n = len(post_closes)
    sustained = post_n >= MIN_POST_BARS and sum(1 for c in post_closes if beyond(c)) / post_n >= SUSTAIN_RATIO
    post_poc = _poc(highs[b:], lows[b:], volumes[b:]) if post_n >= MIN_POST_BARS else None
    new_hvn = post_poc is not None and beyond(post_poc)
    poc_shift = poc_dir == direction
    retest_held = bos.state == "retest_held"

    evidence = {"sustained": sustained, "new_hvn_beyond": new_hvn, "poc_shift": poc_shift, "retest_held": retest_held}
    reasons = [
        f"{side} break of {level:.6f}, {post_n} closed bar(s) since.",
        f"Sustained beyond level: {'yes' if sustained else 'no'} (need {MIN_POST_BARS}+ bars, "
        f"{SUSTAIN_RATIO:.0%} closing beyond).",
        f"Post-break POC {'beyond' if new_hvn else 'not beyond'} the level"
        + (f" ({post_poc:.6f})." if post_poc is not None else " (too few bars)."),
        f"POC migration: {poc_dir}.",
        f"Retest: {'held' if retest_held else 'none yet' if bos.state == 'continuation' else bos.state}.",
    ]

    if sustained and (new_hvn or poc_shift or retest_held):
        return VpBos(signal=f"VP-BOS-{side}", vp="ACCEPT", status="BULLISH" if direction == "up" else "BEARISH",
                     structure=structure, poc_direction=poc_dir, direction=direction, level_price=level,
                     evidence=evidence, reasons=reasons)
    if retest_held:
        return VpBos(signal="BOS-RETEST", vp="HOLD", status="TRANSITIONAL", structure=structure,
                     poc_direction=poc_dir, direction=direction, level_price=level, evidence=evidence, reasons=reasons)
    return VpBos(signal="BOS-UNCONFIRMED", vp="PENDING", status="TRANSITIONAL", structure=structure,
                 poc_direction=poc_dir, direction=direction, level_price=level, evidence=evidence, reasons=reasons)


_ARROWS = {"up": "↑", "down": "↓", "flat": "→"}


def format_vp_bos_section(symbol: str, by_tf: dict[str, VpBos]) -> str:
    bar = "-" * 81
    lines = [
        bar,
        f"VP-BOS -- VOLUME PROFILE BREAK OF STRUCTURE -- {symbol} (advisory)".center(81),
        bar,
        f"{'TF':<6}{'STRUCTURE':<16}{'VP-BOS':<18}{'LEVEL':<12}{'VP':<9}{'POC':<5}{'STATUS':<14}",
    ]
    for tf, r in by_tf.items():
        if r is None:
            lines.append(f"{tf:<6}{'--':<16}{'ERROR':<18}{'--':<12}{'--':<9}{'--':<5}{'--':<14}")
            continue
        level = f"{r.level_price:.6g}" if r.level_price is not None else "--"
        lines.append(
            f"{tf:<6}{r.structure:<16}{r.signal:<18}{level:<12}{r.vp:<9}"
            f"{_ARROWS[r.poc_direction]:<5}{r.status:<14}"
        )
    bull = sum(1 for r in by_tf.values() if r is not None and r.signal == "VP-BOS-BULL")
    bear = sum(1 for r in by_tf.values() if r is not None and r.signal == "VP-BOS-BEAR")
    n = len(by_tf)
    if bull >= 2 and bull > bear:
        direction = "BULLISH"
    elif bear >= 2 and bear > bull:
        direction = "BEARISH"
    else:
        direction = "NONE (insufficient VP-BOS agreement)"
    lines.append(bar)
    lines.append(f"VP-BOS CONFLUENCE: bull {bull}/{n}, bear {bear}/{n}  ->  DIRECTION: {direction}")
    lines.append("Closed bars only. Informational -- not used by the confluence/execution gate.")
    lines.append(bar)
    return "\n".join(lines)


def build_vp_bos_by_tf(data_by_tf: dict, now: Optional[float] = None) -> dict[str, Optional[VpBos]]:
    """`data_by_tf`: {tf: OHLCV}. Best-effort per timeframe -- one bad
    series becomes an ERROR row, never an exception out of the report."""
    out: dict[str, Optional[VpBos]] = {}
    for tf in TIMEFRAMES:
        data = data_by_tf.get(tf)
        if data is None:
            continue
        try:
            out[tf] = classify_vp_bos(
                data.timestamps, data.highs, data.lows, data.closes, data.volumes, tf, now=now,
                market=getattr(data, "market", no_trade_gate.MARKET_24X7),
            )
        except Exception:
            out[tf] = None
    return out
