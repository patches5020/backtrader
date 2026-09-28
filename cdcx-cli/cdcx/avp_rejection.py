"""
avp_rejection.py
----------------
AVP Bullish Rejection -- ANALYSIS / PAPER signal only (stage 1 of the
validation plan). Never read by confluence.py, entry_checklist.py,
no_trade_gate.py, risk sizing or execution, and it never overrides a
cdcx NO TRADE. It exists to be backtested and paper-tracked separately from
POC Bounce, Value Area Reversal and bullish VP-BOS.

Definition: price trades into/below an Anchored Volume Profile level (VAL or
POC), fails to establish acceptance below it, and CLOSES back above it --
confirmed by the next closed candle holding the level.

    AVP anchor   the top the current decline started from (highest high of
                 the last ANCHOR_LOOKBACK bars), so the profile shows where
                 volume was accepted during the sell-off and stays stable
                 while price makes new lows.
    RECLAIM      a closed candle with low <= level and close > level
    PENDING      reclaim is the newest closed candle (hold not seen yet)
    CONFIRMED    the next closed candle closes >= level, and no close since
                 has lost it
    FAILED       a close back below the level after the reclaim
    REJECTED     confirmed, but the rejection low sits at/below the 1.5x ATR
                 stop -- the protected stop would be inside the rejection
                 zone, so no hypothetical trade (the stop is never widened)

Evidence (reported, not required): reclaim volume >= 1.0x the trailing
average, close in the upper 40% of the reclaim candle, RSI turning up,
AVP POC not migrating lower, a failed bearish VP-BOS, a held retest.

Hypothetical plan (the EXISTING risk model, unchanged):
    entry  retest close if a retest held, else the hold candle's close
    stop   entry - risk.resolve_atr_multiplier(symbol) x ATR  (1.5x)
    TPs    entry + risk.resolve_tp_ratios() x R  (2.2 / 2.6 / 3.2 / 4.5 R),
           closing risk.resolve_tp_close_pcts() at each (25% each)
    after  trade_manager rules: TP1 -> stop to breakeven with the rule-I
           giveback exit (20% of BE->TP1 above BE); TP2 -> stop TP1;
           TP3 -> stop TP2; TP4 closes the rest.
simulate_outcome() replays that plan bar by bar (if a bar touches both the
stop and a target, the stop is assumed first -- conservative).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, Sequence

from . import no_trade_gate
from . import risk
from . import vp_bos as vp_bos_module
from .config import settings
from .indicators import atr_ema_variant1
from .indicators import rsi as rsi_module
from .indicators import volume_profile_fixed

ANCHOR_LOOKBACK = 100         # bars searched for the decline's low and its starting swing high
REJECTION_LOOKBACK = 12       # how recent the reclaim must be to be reported
RETEST_PROXIMITY_ATR = 0.5    # same proximity structure_levels uses for retests
VOLUME_CONFIRM_RATIO = 1.0
UPPER_CLOSE_FRACTION = 0.6
POC_MIGRATION_BARS = 3

TIMEFRAMES = ("4h", "1h")


@dataclass
class AvpProfile:
    anchor_index: int
    poc: float
    vah: float
    val: float


@dataclass
class TradePlan:
    entry_type: str               # "retest" | "confirmation"
    entry_index: int
    entry: float
    stop: float
    take_profits: list[float]
    tp_ratios: list[float]
    close_pcts: list[float]
    atr: float
    atr_multiplier: float


@dataclass
class Outcome:
    status: str                   # "open" | "stopped" | "tp4"
    r_multiple: float             # realized so far (open trades: closed portions only)
    tps_hit: int
    exit_index: Optional[int] = None


@dataclass
class AvpRejection:
    state: str                    # NONE | PENDING | CONFIRMED | FAILED | REJECTED
    level_name: Optional[str] = None   # "VAL" | "POC"
    level: Optional[float] = None
    profile: Optional[AvpProfile] = None
    reclaim_index: Optional[int] = None
    rejection_low: Optional[float] = None
    evidence: dict = field(default_factory=dict)
    plan: Optional[TradePlan] = None
    outcome: Optional[Outcome] = None
    reasons: list[str] = field(default_factory=list)


def anchor_at_decline_start(highs: Sequence[float], lows: Sequence[float],
                            lookback: int = ANCHOR_LOOKBACK) -> int:
    """The top the current decline started from: the highest high of the
    lookback. (First version used "last swing high before the lowest low";
    live XRP showed the lowest low can predate the rally -- 4H anchored at a
    mid-September high instead of the Sep 25 top the sell-off came from.)"""
    n = len(highs)
    start = max(0, n - lookback)
    return max(range(start, n), key=lambda i: (highs[i], i))  # latest bar wins a tie


def anchored_profile(highs, lows, volumes, anchor: int, end: Optional[int] = None) -> Optional[AvpProfile]:
    end = len(highs) if end is None else end
    if end - anchor < 3:
        return None
    try:
        hist = volume_profile_fixed.build_volume_profile(highs[anchor:end], lows[anchor:end], volumes[anchor:end])
    except ValueError:
        return None
    poc, vah, val = volume_profile_fixed.calculate_poc_vah_val(hist)
    return AvpProfile(anchor_index=anchor, poc=poc, vah=vah, val=val)


def build_plan(symbol: str, entry_index: int, entry: float, atr: float, entry_type: str) -> TradePlan:
    mult = risk.resolve_atr_multiplier(symbol)
    ratios = list(risk.resolve_tp_ratios())
    pcts = list(risk.resolve_tp_close_pcts())
    stop = entry - mult * atr
    r = entry - stop
    return TradePlan(entry_type=entry_type, entry_index=entry_index, entry=entry, stop=stop,
                     take_profits=[entry + k * r for k in ratios], tp_ratios=ratios, close_pcts=pcts,
                     atr=atr, atr_multiplier=mult)


def simulate_outcome(plan: TradePlan, highs: Sequence[float], lows: Sequence[float]) -> Outcome:
    """Replay trade_manager rules G/H/I on the bars after the entry."""
    r = plan.entry - plan.stop
    remaining, realized, hit, stop = 1.0, 0.0, 0, plan.stop
    tp1 = plan.take_profits[0]
    for i in range(plan.entry_index + 1, len(highs)):
        if lows[i] <= stop:  # stop first when a bar touches both (conservative)
            realized += remaining * (stop - plan.entry) / r
            return Outcome("stopped", round(realized, 3), hit, i)
        while hit < 4 and highs[i] >= plan.take_profits[hit]:
            frac = remaining if hit == 3 else min(remaining, plan.close_pcts[hit] / 100.0)
            realized += frac * plan.tp_ratios[hit]
            remaining -= frac
            hit += 1
            if hit == 1:   # rule G + rule I: breakeven, tightened by the giveback exit
                stop = plan.entry + settings.giveback_exit_pct * (tp1 - plan.entry)
            elif hit in (2, 3):  # rule H
                stop = plan.take_profits[hit - 2]
        if hit == 4 or remaining <= 1e-9:
            return Outcome("tp4", round(realized, 3), hit, i)
    return Outcome("open", round(realized, 3), hit)


def classify_avp_rejection(
    timestamps: Sequence[int], highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
    volumes: Sequence[float], timeframe: str, symbol: str = "", now: Optional[float] = None,
    market: str = no_trade_gate.MARKET_24X7,
) -> AvpRejection:
    now = time.time() if now is None else now
    h, l, c, v = list(highs), list(lows), list(closes), list(volumes)
    if no_trade_gate.last_bar_is_forming(timestamps, timeframe, now, market=market):
        h, l, c, v = h[:-1], l[:-1], c[:-1], v[:-1]
    n = len(c)
    if n < atr_ema_variant1.ATR_LENGTH + 5:
        return AvpRejection(state="NONE", reasons=["Not enough closed bars."])

    anchor = anchor_at_decline_start(h, l)
    profile = anchored_profile(h, l, v, anchor)
    if profile is None:
        return AvpRejection(state="NONE", reasons=["Anchored profile too short."])
    atr_series = atr_ema_variant1.calculate_atr(h, l, c)

    # Most recent reclaim of VAL or POC within the lookback.
    event = None
    for i in range(n - 1, max(anchor, n - REJECTION_LOOKBACK) - 1, -1):
        for name, level in (("VAL", profile.val), ("POC", profile.poc)):
            if l[i] <= level < c[i]:
                event = (i, name, level)
                break
        if event:
            break
    if event is None:
        return AvpRejection(state="NONE", profile=profile,
                            reasons=[f"No closed candle reclaimed AVP VAL {profile.val:.6g} or POC {profile.poc:.6g} "
                                     f"in the last {REJECTION_LOOKBACK} bars."])

    r_idx, name, level = event
    base = dict(level_name=name, level=level, profile=profile, reclaim_index=r_idx)
    if r_idx == n - 1:
        return AvpRejection(state="PENDING", rejection_low=l[r_idx], **base,
                            reasons=[f"Reclaimed AVP {name} {level:.6g} on the newest closed candle; "
                                     "waiting for the next candle to hold it."])
    lost = next((j for j in range(r_idx + 1, n) if c[j] < level), None)
    if lost is not None:
        return AvpRejection(state="FAILED", rejection_low=l[r_idx], **base,
                            reasons=[f"Reclaimed AVP {name} {level:.6g}, then closed back below it "
                                     f"({c[lost]:.6g}) -- not accepted."])

    hold = r_idx + 1
    rejection_low = min(l[max(anchor, r_idx - 2):hold + 1])
    avg_vol = sum(v[max(0, r_idx - atr_ema_variant1.ATR_LENGTH):r_idx]) / max(1, min(r_idx, atr_ema_variant1.ATR_LENGTH))
    rng = h[r_idx] - l[r_idx]
    rsi = rsi_module.calculate_rsi(c[:hold + 1])
    poc_before = anchored_profile(h, l, v, anchor, end=max(anchor + 3, n - POC_MIGRATION_BARS))
    vb = vp_bos_module.classify_vp_bos(timestamps[:n], h, l, c, v, timeframe, now=float("inf"), market=market)
    retest = next((j for j in range(hold + 1, n)
                   if l[j] <= level + RETEST_PROXIMITY_ATR * atr_series[j] and c[j] >= level), None)
    evidence = {
        "volume_confirmed": avg_vol > 0 and v[r_idx] >= VOLUME_CONFIRM_RATIO * avg_vol,
        "upper_close": rng > 0 and (c[r_idx] - l[r_idx]) / rng >= UPPER_CLOSE_FRACTION,
        "rsi_turning_up": len(rsi) > 1 and rsi[-1] > rsi[-2],
        "avp_poc_not_lower": poc_before is None or profile.poc >= poc_before.poc,
        "bearish_vpbos_failed": vb.signal == "BOS-FAILED" and vb.direction == "down",
        "retest_held": retest is not None,
    }

    entry_index, entry_type = (retest, "retest") if retest is not None else (hold, "confirmation")
    plan = build_plan(symbol, entry_index, c[entry_index], atr_series[entry_index], entry_type)
    if rejection_low <= plan.stop:
        return AvpRejection(state="REJECTED", rejection_low=rejection_low, evidence=evidence, **base,
                            reasons=[f"Rejection low {rejection_low:.6g} is at/below the {plan.atr_multiplier}x ATR stop "
                                     f"{plan.stop:.6g}: the stop would sit inside the rejection zone. Not widened -- no trade."])
    outcome = simulate_outcome(plan, h, l)
    return AvpRejection(state="CONFIRMED", rejection_low=rejection_low, evidence=evidence, plan=plan,
                        outcome=outcome, **base,
                        reasons=[f"Reclaimed AVP {name} {level:.6g} and the next candle held it; "
                                 f"{sum(evidence.values())}/6 confirmations."])


def format_avp_section(symbol: str, by_tf: dict[str, Optional[AvpRejection]]) -> str:
    width = 81
    bar = "-" * width
    lines = [bar, f"AVP BULLISH REJECTION -- {symbol} (paper / advisory only)".center(width), bar]
    for tf, r in by_tf.items():
        if r is None:
            lines.append(f"{tf.upper()}: ERROR")
            continue
        p = r.profile
        lines.append(f"{tf.upper()} AVP (anchored at decline start):"
                     + (f"  POC {p.poc:.6g}  VAH {p.vah:.6g}  VAL {p.val:.6g}" if p else "  n/a"))
        level = f" at {r.level_name} {r.level:.6g}" if r.level_name else ""
        lines.append(f"    Setup: {r.state}{level}")
        if r.evidence:
            e = r.evidence
            yes = lambda k: "YES" if e.get(k) else "no"
            lines.append(f"    Level reclaimed: YES   Volume: {yes('volume_confirmed')}   Upper close: {yes('upper_close')}"
                         f"   RSI up: {yes('rsi_turning_up')}")
            lines.append(f"    AVP POC not lower: {yes('avp_poc_not_lower')}   Bearish VP-BOS failed: "
                         f"{yes('bearish_vpbos_failed')}   Retest held: {yes('retest_held')}")
        if r.plan:
            pl = r.plan
            tps = " / ".join(f"{t:.6g}" for t in pl.take_profits)
            lines.append(f"    Paper plan ({pl.entry_type}): entry {pl.entry:.6g}  stop {pl.stop:.6g} "
                         f"({pl.atr_multiplier}x ATR)  TP1-4 {tps}")
            o = r.outcome
            lines.append(f"    Paper outcome: {o.status}, {o.tps_hit} TP(s) hit, {o.r_multiple:+.2f}R so far")
        for reason in r.reasons:
            lines.append(f"    {reason}")
    lines.append(bar)
    lines.append("Closed candles only. PAPER/ANALYSIS -- never overrides cdcx NO TRADE or the execution gate.")
    lines.append(bar)
    return "\n".join(lines)


def build_avp_by_tf(symbol: str, data_by_tf: dict, now: Optional[float] = None) -> dict[str, Optional[AvpRejection]]:
    out: dict[str, Optional[AvpRejection]] = {}
    for tf in TIMEFRAMES:
        data = data_by_tf.get(tf)
        if data is None:
            continue
        try:
            out[tf] = classify_avp_rejection(data.timestamps, data.highs, data.lows, data.closes, data.volumes,
                                             tf, symbol=symbol, now=now,
                                             market=getattr(data, "market", no_trade_gate.MARKET_24X7))
        except Exception:
            out[tf] = None
    return out
