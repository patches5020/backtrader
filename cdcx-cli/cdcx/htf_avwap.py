"""
htf_avwap.py
------------
HTF AVWAP context -- ANALYSIS ONLY. An Anchored VWAP on each higher
timeframe (4H / 1D / 1W) anchored at EXACTLY the bar the matching Anchored
Volume Profile uses, so the AVWAP and the AVP always describe the same
period. Never read by confluence.py, entry_checklist.py, no_trade_gate.py,
setup_grade.py, risk sizing or execution; it never changes a grade, a gate
or a NO TRADE.

Anchors (the AVP's own anchor is authoritative -- no separate AVWAP rule):

    cdcx AVP        volume_profile_anchor (the engine's "Anchored Volume
                    Profile" score): the lowest close of the last
                    min(settings.swing_lookback, n - 1) bars. Taken from the
                    TradeSignal (anchored_vp_anchor_ts) when that timeframe
                    was analysed; otherwise re-derived with the same call on
                    the same series and labelled "derived".
    decline-start   avp_rejection (4H only, as in the AVP BULLISH REJECTION
                    section): the highest high of the last ANCHOR_LOOKBACK
                    closed bars.

The VWAP itself is anchored_vwap.anchored_vwap unchanged (ohlc4,
volume-weighted sigma, +/-1/2/3 sigma bands), computed on CLOSED bars only.
The still-forming bar only appears as a "provisional" price line.

    price vs AVWAP  above / below / at -- no "near" band (none is configured);
                    the sigma position is printed instead.
    event           the last closed bar RECLAIMED (prev close <= VWAP then,
                    close > VWAP now) or LOST it; a forming bar on the other
                    side of the closed-bar relationship is a PROVISIONAL cross.
    confluence      AVWAP side vs the AVP side (closed close above/below that
                    AVP's POC), the strict BOS state (bos_state, 0.25 x ATR
                    margin) and, for decline-start, the AVP rejection state.
                    aligned / mixed / AVWAP only / unknown. Disagreement is
                    reported, never resolved.
    data            valid / insufficient (history doesn't reach the anchor,
                    too few closed bars) / invalid (zero volume, anchor bar
                    missing) / stale (newest closed bar ended more than
                    STALE_AFTER_BARS periods ago). Anything but valid -> unknown.

Setup block (2026-10-21, same format as PREV-DAY AVWAP + AFVP): for each valid
context with same-anchor AVP levels, vwap_confluence.classify runs unchanged on
this AVWAP and that AVP's POC/VAH/VAL -- VP-01..VP-05, the evidence families,
Context (closed bars), DECISION / STATUS / Next / Invalidates / Execution. The
LTF "today" window becomes the last VP_WINDOW_BARS closed bars of the
timeframe. Display only; execution stays NOT AUTHORIZED.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Sequence

from . import avp_rejection
from . import bos_state as bos_state_module
from . import no_trade_gate
from .config import settings
from .indicators import anchored_vwap as avwap_module
from .indicators import market_structure, volume_profile_anchor
from .utils.color import (colorize_avwap_lower, colorize_avwap_upper, colorize_poc, colorize_vah,
                          colorize_val, colorize_vwap)

TIMEFRAMES = ("4h", "1d", "1w")
STALE_AFTER_BARS = 2          # newest closed bar ended > 2 periods ago -> a bar is missing
EQUITY_WEEKEND_SLACK = 3 * 86400  # equity sessions skip weekends/holidays

ANCHOR_CDCX_AVP = "cdcx AVP (lowest close, swing lookback)"
ANCHOR_DECLINE_START = "AVP rejection (decline start, highest high)"
VP_WINDOW_BARS = 6            # HTF stand-in for the LTF section's "today"


@dataclass
class HtfAvwapContext:
    timeframe: str
    anchor_type: str
    anchor_source: str                       # "engine signal" | "derived (same rule)" | "avp_rejection"
    anchor_ts: Optional[float] = None
    last_closed_ts: Optional[float] = None   # open time of the newest closed bar
    data_status: str = "unknown"             # valid | insufficient | invalid | stale | unknown
    avwap: Optional[avwap_module.AnchoredVWAP] = None
    closed_close: Optional[float] = None
    relation: str = "unknown"                # above | below | at | unknown
    sigma_pos: Optional[float] = None
    event: str = "none"                      # reclaimed | lost | none
    provisional_price: Optional[float] = None
    provisional: str = "none"                # "provisional cross above" | "provisional cross below" | none
    avp_levels: Optional[tuple[float, float, float]] = None   # (poc, vah, val)
    avp_includes_forming: bool = False       # engine AVP levels were built with the forming bar in them
    avp_side: str = "unknown"
    structure_side: str = "none"
    rejection_state: Optional[str] = None
    confluence: str = "unknown"
    reasons: list[str] = field(default_factory=list)
    vp: Optional[object] = None              # vwap_confluence.VwapVpResult (setup block), None = not run
    vp_levels: Optional[object] = None       # the PrevDayLevels-shaped input it ran on
    vp_context: Optional[object] = None      # vwap_confluence.Context (closed bars)
    vp_error: str = ""
    vp_research: list = field(default_factory=list)   # VP-06 (vp_reentry.py) -- research only, never voted


def _sec(ts: float) -> float:
    return ts / 1000 if ts > 1e11 else ts


def _fmt_ts(ts: Optional[float]) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%MZ") if ts is not None else "unknown"


def _closed_count(timestamps: Sequence[float], timeframe: str, now: float, market: str) -> int:
    n = len(timestamps)
    return n - 1 if no_trade_gate.last_bar_is_forming(timestamps, timeframe, now, market=market) else n


def derive_cdcx_avp(timestamps: Sequence[float], highs, lows, closes, volumes):
    """Same call and lookback the engine makes for its Anchored Volume Profile
    (engine.analyze_ohlcv), on the same full series -- used only when no
    TradeSignal for this timeframe is available. Returns (anchor_ts, result)."""
    if len(closes) < 2:
        return None, None
    lookback = min(settings.swing_lookback, len(closes) - 1)
    res = volume_profile_anchor.analyze(highs, lows, closes, volumes, price=closes[-1], anchor_lookback=lookback)
    return _sec(timestamps[res.anchor_index]), res


def _side_vs_profile(price: float, poc: float, vah: float, val: float) -> str:
    if price > poc:
        return "bullish"
    if price < poc:
        return "bearish"
    return "neutral"


def _is_stale(last_closed_open: float, timeframe: str, now: float, market: str) -> bool:
    close = no_trade_gate.bar_close_time(last_closed_open, timeframe, market)
    tf_s = no_trade_gate.timeframe_to_seconds(timeframe)
    if close is None or not tf_s:
        return False
    slack = STALE_AFTER_BARS * tf_s + (EQUITY_WEEKEND_SLACK if market != no_trade_gate.MARKET_24X7 else 0)
    return now - close > slack


def build_context(
    timeframe: str, data, anchor_type: str = ANCHOR_CDCX_AVP, signal=None, now: Optional[float] = None,
    htf: Optional[str] = None, htf_detail: str = "",
) -> HtfAvwapContext:
    """One HTF AVWAP context. `data` is the timeframe's OHLCV (forming bar may be
    included); `signal` the engine TradeSignal for the same timeframe, if any."""
    now = time.time() if now is None else now
    market = getattr(data, "market", no_trade_gate.MARKET_24X7)
    ctx = HtfAvwapContext(timeframe=timeframe, anchor_type=anchor_type, anchor_source="unknown")
    ts_all = [_sec(t) for t in (getattr(data, "timestamps", None) or [])]
    if not ts_all or len(ts_all) != len(data.closes):
        ctx.data_status, ctx.reasons = "invalid", ["No bar timestamps -- cannot place the anchor."]
        return ctx
    n = _closed_count(ts_all, timeframe, now, market)
    if n < 3:
        ctx.data_status, ctx.reasons = "insufficient", ["Fewer than 3 closed bars."]
        return ctx
    o, h, l, c, v = (list(x[:n]) for x in (data.opens, data.highs, data.lows, data.closes, data.volumes))
    ts = ts_all[:n]
    ctx.last_closed_ts, ctx.closed_close = ts[-1], c[-1]
    if n < len(ts_all):
        ctx.provisional_price = data.closes[-1]

    # --- anchor: the matching AVP's own anchor -------------------------------
    if anchor_type == ANCHOR_CDCX_AVP:
        sig_ts = getattr(signal, "anchored_vp_anchor_ts", None) if signal is not None else None
        if sig_ts is not None:
            ctx.anchor_ts, ctx.anchor_source = sig_ts, "engine signal"
            if all(getattr(signal, k, 0.0) for k in ("anchored_vp_poc", "anchored_vp_vah", "anchored_vp_val")):
                ctx.avp_levels = (signal.anchored_vp_poc, signal.anchored_vp_vah, signal.anchored_vp_val)
        else:
            ctx.anchor_ts, avp = derive_cdcx_avp(ts_all, data.highs, data.lows, data.closes, data.volumes)
            ctx.anchor_source = "derived (same rule)"
            if avp is not None:
                ctx.avp_levels = (avp.poc, avp.vah, avp.val)
    elif anchor_type == ANCHOR_DECLINE_START:
        idx = avp_rejection.anchor_at_decline_start(h, l)
        ctx.anchor_ts, ctx.anchor_source = ts[idx], "avp_rejection"
        prof = avp_rejection.anchored_profile(h, l, v, idx)
        if prof is not None:
            ctx.avp_levels = (prof.poc, prof.vah, prof.val)
        try:
            ctx.rejection_state = avp_rejection.classify_avp_rejection(
                data.timestamps, data.highs, data.lows, data.closes, data.volumes, timeframe,
                now=now, market=market).state
        except Exception:
            ctx.rejection_state = None
    else:
        raise ValueError(f"unknown anchor type {anchor_type!r}")

    if ctx.anchor_ts is None or ctx.anchor_ts not in ts_all:
        ctx.data_status, ctx.reasons = "invalid", ["AVP anchor bar is not in this series."]
        return ctx
    if ctx.anchor_ts > ts[-1]:
        ctx.data_status, ctx.reasons = "insufficient", ["AVP anchor is the forming bar -- no closed bars since it."]
        return ctx

    # --- AVWAP on closed bars (existing calculation, unchanged) ----------------
    res = avwap_module.anchored_vwap(ts, o, h, l, c, v, anchor_ts=ctx.anchor_ts)
    if res is None:
        ctx.data_status = "invalid" if sum(v[ts.index(ctx.anchor_ts):]) <= 0 else "insufficient"
        ctx.reasons = ["AVWAP unavailable (zero volume since the anchor, or history doesn't reach it)."]
        return ctx
    ctx.avwap = res
    if _is_stale(ts[-1], timeframe, now, market):
        ctx.data_status = "stale"
        ctx.reasons = [f"Newest closed bar ({_fmt_ts(ts[-1])}) is more than {STALE_AFTER_BARS} periods old."]
        return ctx
    ctx.data_status = "valid"

    close = c[-1]
    ctx.relation = "above" if close > res.vwap else "below" if close < res.vwap else "at"
    ctx.sigma_pos = avwap_module.band_position(close, res)
    if res.bars_used >= 2:
        prev_close, prev_vwap = c[-2], res.series[-2]
        if prev_close <= prev_vwap and close > res.vwap:
            ctx.event = "reclaimed"
        elif prev_close >= prev_vwap and close < res.vwap:
            ctx.event = "lost"
    if ctx.provisional_price is not None:
        if ctx.relation != "above" and ctx.provisional_price > res.vwap:
            ctx.provisional = "provisional cross above"
        elif ctx.relation != "below" and ctx.provisional_price < res.vwap:
            ctx.provisional = "provisional cross below"

    # --- confluence with the existing AVP / structure evidence -----------------
    if ctx.avp_levels:
        ctx.avp_side = _side_vs_profile(close, *ctx.avp_levels)
        # the engine's AVP (signal or same-rule derivation) runs on the full series, forming bar included
        ctx.avp_includes_forming = anchor_type == ANCHOR_CDCX_AVP and ctx.provisional_price is not None
    ms = market_structure.analyze(h, l, price=close)
    bs = bos_state_module.classify_bos_state(ms, h, l, c, v)
    ctx.structure_side = {"up": "bullish", "down": "bearish"}.get(bs.direction, "none")
    ctx.confluence = _confluence(ctx)
    _attach_setups(ctx, data, timeframe, ts, htf, htf_detail)
    return ctx


def _attach_setups(ctx: HtfAvwapContext, data, timeframe: str, closed_ts: list[float],
                   htf: Optional[str], htf_detail: str) -> None:
    """VP-01..VP-05 + evidence + DECISION on this AVWAP and the same-anchor AVP levels. The
    LTF section's "today" (bars after the frozen session) is the last VP_WINDOW_BARS closed bars."""
    if not ctx.avp_levels or ctx.avwap is None:
        ctx.vp_error = "no same-anchor AVP levels"
        return
    from .volume_profile import vwap_confluence
    from .volume_profile.prev_day import PrevDayLevels

    poc, vah, val = ctx.avp_levels
    window_start = closed_ts[max(len(closed_ts) - VP_WINDOW_BARS, 0)]
    levels = PrevDayLevels(status="OK", timeframe=timeframe, session_start=ctx.anchor_ts,
                           session_end=window_start, poc=poc, vah=vah, val=val, avwap=ctx.avwap)
    try:
        res = vwap_confluence.classify(levels, data, htf=htf, htf_detail=htf_detail)
    except Exception as exc:   # display only: never break the HTF section
        ctx.vp_error = f"setup block failed: {exc}"
        return
    window = f"in the last {VP_WINDOW_BARS} {timeframe.upper()} bars"
    for s in res.setups:
        s.detail = s.detail.replace("prior value area", "AVP value area").replace(
            "prior VAH/VAL", "AVP VAH/VAL").replace("near prior ", "near AVP ").replace("no bars today yet", f"no bars {window}").replace("today", window)
    res.family_detail = {k: v.replace("today", window) for k, v in res.family_detail.items()}
    ctx.vp, ctx.vp_levels = res, levels
    from .volume_profile.vp_breakout_pullback import breakout_pullback   # RQ8 } display only
    from .volume_profile.vp_first_touch import first_touch               # RQ9 }
    from .volume_profile.vp_reentry import value_area_reentry            # RQ7 }
    ctx.vp_research = []
    for fn in (value_area_reentry, breakout_pullback, first_touch):
        try:
            ctx.vp_research.append(fn(levels, data))
        except Exception as exc:
            ctx.vp_error = f"{fn.__name__} failed: {exc}"


def _confluence(ctx: HtfAvwapContext) -> str:
    if ctx.relation not in ("above", "below"):
        return "unknown (price at AVWAP)" if ctx.relation == "at" else "unknown"
    side = "bullish" if ctx.relation == "above" else "bearish"
    others = {"AVP": ctx.avp_side, "structure": ctx.structure_side}
    if ctx.rejection_state in ("CONFIRMED", "PENDING"):
        others["AVP rejection"] = "bullish"
    votes = {k: s for k, s in others.items() if s in ("bullish", "bearish")}
    if not votes:
        return f"AVWAP only ({side}; no AVP/structure side)"
    # closed-bar AVWAP/structure compared with AVP levels that contain the forming bar: say so
    basis = " [mixed basis: AVP levels include the forming bar]" if "AVP" in votes and ctx.avp_includes_forming else ""
    against = [k for k, s in votes.items() if s != side]
    if not against:
        return f"aligned {side} (AVWAP + {' + '.join(votes)}){basis}"
    return f"mixed (AVWAP {side}; {', '.join(f'{k} {votes[k]}' for k in against)}){basis}"


def build_htf_avwap(data_by_tf: dict, signals: Optional[dict] = None, now: Optional[float] = None,
                    timeframes: Sequence[str] = TIMEFRAMES, symbol: str = "") -> list[HtfAvwapContext]:
    from .volume_profile import vwap_confluence

    signals = signals or {}
    try:   # cdcx's own 2-of-4 confluence -- the same filter the LTF section and --execute use
        htf, htf_detail = vwap_confluence.htf_direction(signals) if signals else (None, "")
    except Exception:
        htf, htf_detail = None, ""
    out = []
    for tf in timeframes:
        data = data_by_tf.get(tf)
        if data is None:
            continue
        context = vwap_confluence.context_from_closed(symbol, data, tf, now=now)
        anchors = [ANCHOR_CDCX_AVP] + ([ANCHOR_DECLINE_START] if tf in avp_rejection.TIMEFRAMES else [])
        for anchor_type in anchors:
            try:
                ctx = build_context(tf, data, anchor_type, signal=signals.get(tf), now=now,
                                    htf=htf, htf_detail=htf_detail)
                ctx.vp_context = context
                out.append(ctx)
            except Exception as exc:   # fail closed: an explicit unknown, never a side
                out.append(HtfAvwapContext(timeframe=tf, anchor_type=anchor_type, anchor_source="unknown",
                                           data_status="invalid", reasons=[f"calculation failed: {exc}"]))
    return out


def _p(x: Optional[float]) -> str:
    return f"{x:.6g}" if x is not None else "unknown"


def format_htf_avwap_section(symbol: str, contexts: list[HtfAvwapContext]) -> str:
    width = 73
    bar = "=" * width
    lines = [bar, f"HTF AVWAP CONTEXT -- {symbol} (analysis only, AVP-matched anchors)".center(width), bar]
    if not contexts:
        lines.append("No HTF data available.")
    for ctx in contexts:
        lines.append(f"{ctx.timeframe.upper()} | anchor: {ctx.anchor_type} [{ctx.anchor_source}]")
        lines.append(f"  Anchor start: {_fmt_ts(ctx.anchor_ts)}   Last closed bar: {_fmt_ts(ctx.last_closed_ts)}"
                     f"   Data: {ctx.data_status}")
        if ctx.data_status != "valid" or ctx.avwap is None:
            lines.append("  AVWAP: unknown -- " + "; ".join(ctx.reasons or ["no data"]))
            lines.append("  Confluence: unknown")
            continue
        r = ctx.avwap
        # POC yellow / VAH red / VAL green (as elsewhere) and VWAP blue -- user's choice, 2026-10-20
        lines.append(f"  {colorize_vwap(f'AVWAP {_p(r.vwap)}')}  sigma {_p(r.sigma)}  ({r.bars_used} closed bars, {r.source})")
        lines.append("  Bands: " + "  ".join(f"+/-{k}: {colorize_avwap_lower(_p(lo))} / {colorize_avwap_upper(_p(hi))}" for k, (lo, hi) in sorted(r.bands.items())))
        ev = f", {ctx.event} on this close" if ctx.event != "none" else ""
        lines.append(f"  Closed close {_p(ctx.closed_close)} is {ctx.relation.upper()} AVWAP "
                     f"({ctx.sigma_pos:+.2f} sigma){ev}  [closed]")
        if ctx.provisional_price is not None:
            pv = f" -> {ctx.provisional}" if ctx.provisional != "none" else ""
            lines.append(f"  Forming bar {_p(ctx.provisional_price)}{pv}  [provisional]")
        if ctx.avp_levels:
            poc, vah, val = ctx.avp_levels
            basis = "closed bars" if ctx.anchor_type == ANCHOR_DECLINE_START else "engine AVP, incl. forming bar"
            lines.append(f"  Same-anchor AVP ({basis}): {colorize_poc(f'POC {_p(poc)}')}  "
                         f"{colorize_vah(f'VAH {_p(vah)}')}  {colorize_val(f'VAL {_p(val)}')}"
                         f" -> close vs POC: {ctx.avp_side}")
        rej = f" | AVP rejection: {ctx.rejection_state}" if ctx.rejection_state else ""
        lines.append(f"  Strict BOS: {ctx.structure_side}{rej}")
        lines.append(f"  Confluence: {ctx.confluence}")
        if ctx.vp is not None:
            from .volume_profile.vwap_confluence import format_setup_lines
            lines.append("")
            lines += [f"  {x}" if x else "" for x in format_setup_lines(ctx.vp, ctx.vp_levels, ctx.timeframe,
                                                                        ctx.vp_context, research=ctx.vp_research)]
            lines.append("")
        else:
            lines.append(f"  VP-01..VP-05: unknown -- {ctx.vp_error or 'not evaluated'}")
    lines.append("-" * width)
    lines.append("Existing setup grade changed: NO | Existing trade gates changed: NO | Trade action: NONE")
    lines.append(bar)
    return "\n".join(lines)
