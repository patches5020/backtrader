"""
vp_breakout_pullback.py
-------------------------
VP-04P breakout -> pullback hold -> BOS (2026-10-22) -- RESEARCH ONLY
(RQ8, .ai/SHARED/research_questions.md). A separate variant BESIDE VP-04:
VP-04 itself is unchanged. Like VP-06 it is printed under VP-05 and is NOT
part of vwap_confluence.classify(), so it never enters res.setups, an
evidence family, the DECISION, vwap_watch (RQ6 frozen) or
vwap_vp_research (RQ3/RQ5). No gate, grade, sizing or execution reads it.

Hypothesis (Trading Notes "3 setups" video, setup 3): a strong close
outside the value area, a pullback that holds near the broken edge, then a
break of structure, continues in the breakout direction.

Rules (closed bars only; ATR = atr_ema_variant1 ATR(11) at the break bar;
"today" as classify() defines it). Bullish shown; bearish mirrors it at VAL.

    break       the first close above VAH today (previous close <= VAH)
    effort      break-bar volume / mean volume of the VOL_LOOKBACK bars before it
    result      break-bar range (high - low) / ATR
    label       HEALTHY     effort >= effort_high and result >= result_big
                ABSORPTION  effort >= effort_high and result <  result_small
                NO SUPPLY   effort <  effort_low
                NORMAL      anything else
                Only a HEALTHY break can trigger; the others show WEAK BREAK.
    pullback    the first later bar with low <= VAH + touch_atr x ATR
    hold        FAILED as soon as a close < VAH - hold_close_atr x ATR or a
                low < VAH - hold_wick_atr x ATR ("not deep back inside")
    BOS         after the pullback bar, a close > (highest high from the
                break bar up to the bar before the pullback) + bos_atr x ATR
    expiry      no BOS within max_bars bars of the break -> EXPIRED

States: UNKNOWN / NONE / WEAK BREAK / BREAK (waiting for the pullback) /
PULLBACK (holding, waiting for the BOS) / PENDING (BOS on the newest closed
bar) / TRIGGERED (earlier) / FAILED / EXPIRED. The newest episode is the
one reported; after one resolves, the next break starts a new one.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..indicators import atr_ema_variant1
from .vwap_confluence import Setup, _closed_window

CODE = "VP-04P"
NAME = "Breakout pullback"
TAG = "[research only, RQ8]"
VOL_LOOKBACK = 20


@dataclass(frozen=True)
class Params:
    effort_high: float = 1.5
    effort_low: float = 0.8
    result_big: float = 1.0
    result_small: float = 0.6
    touch_atr: float = 0.25
    hold_close_atr: float = 0.25
    hold_wick_atr: float = 0.5
    bos_atr: float = 0.25
    max_bars: int = 12


DEFAULT = Params()


@dataclass
class Episode:
    break_index: int
    direction: str                     # "bullish" | "bearish"
    label: str                         # HEALTHY / ABSORPTION / NO SUPPLY / NORMAL / UNKNOWN
    effort: Optional[float]
    result: Optional[float]
    state: str                         # WEAK BREAK / BREAK / PULLBACK / TRIGGERED / FAILED / EXPIRED
    level: float
    atr: Optional[float] = None
    pullback_index: Optional[int] = None
    bos_level: Optional[float] = None
    end_index: Optional[int] = None    # bar that resolved it (trigger / fail / expiry)


def effort_result(h, l, v, atr, k: int, p: Params = DEFAULT) -> tuple[str, Optional[float], Optional[float]]:
    if k < VOL_LOOKBACK or atr[k] is None or atr[k] != atr[k] or atr[k] <= 0:
        return "UNKNOWN", None, None
    avg = sum(v[k - VOL_LOOKBACK:k]) / VOL_LOOKBACK
    if avg <= 0:
        return "UNKNOWN", None, None
    effort, result = v[k] / avg, (h[k] - l[k]) / atr[k]
    if effort >= p.effort_high and result >= p.result_big:
        return "HEALTHY", effort, result
    if effort >= p.effort_high and result < p.result_small:
        return "ABSORPTION", effort, result
    if effort < p.effort_low:
        return "NO SUPPLY", effort, result
    return "NORMAL", effort, result


def scan(h, l, c, v, atr, val: float, vah: float, start: int, p: Params = DEFAULT) -> list[Episode]:
    """Episodes from breaks at bars >= start (start >= 1). Arrays end at the newest CLOSED bar."""
    n = len(c)
    out: list[Episode] = []
    k = max(start, 1)
    while k < n:
        bull = c[k] > vah and c[k - 1] <= vah
        bear = c[k] < val and c[k - 1] >= val
        if not (bull or bear):
            k += 1
            continue
        d, level = ("bullish", vah) if bull else ("bearish", val)
        label, effort, result = effort_result(h, l, v, atr, k, p)
        ep = Episode(k, d, label, effort, result, "BREAK", level, atr[k] if label != "UNKNOWN" else None)
        out.append(ep)
        if label != "HEALTHY":
            ep.state, ep.end_index = "WEAK BREAK", k
            k += 1
            continue
        a, sign = atr[k], 1 if bull else -1
        hi_since = h[k] if bull else l[k]         # extreme from the break bar up to the bar before the pullback
        last = min(k + p.max_bars, n - 1)
        for j in range(k + 1, last + 1):
            deep_close = (c[j] < level - p.hold_close_atr * a) if bull else (c[j] > level + p.hold_close_atr * a)
            deep_wick = (l[j] < level - p.hold_wick_atr * a) if bull else (h[j] > level + p.hold_wick_atr * a)
            if deep_close or deep_wick:
                ep.state, ep.end_index = "FAILED", j
                break
            if ep.pullback_index is None:
                if (l[j] <= level + p.touch_atr * a) if bull else (h[j] >= level - p.touch_atr * a):
                    ep.pullback_index, ep.state = j, "PULLBACK"
                    ep.bos_level = hi_since + sign * p.bos_atr * a
                else:
                    hi_since = max(hi_since, h[j]) if bull else min(hi_since, l[j])
                continue
            if (c[j] > ep.bos_level) if bull else (c[j] < ep.bos_level):
                ep.state, ep.end_index = "TRIGGERED", j
                break
        else:
            if last == k + p.max_bars:
                ep.state, ep.end_index = "EXPIRED", last
        k = (ep.end_index + 1) if ep.end_index is not None else n
    return out


def _window(levels, data):
    """(h, l, c, v, atr, t0) over all bars up to the newest closed bar of the window; t0 = first bar of 'today'."""
    ts, idx = _closed_window(levels, data)
    if not idx:
        return None
    end = idx[-1] + 1
    h, l, c, v = (list(x[:end]) for x in (data.highs, data.lows, data.closes, data.volumes))
    atr = atr_ema_variant1.calculate_atr(h, l, c)
    t0 = next((i for i in idx if ts[i] >= levels.session_end), end)
    return h, l, c, v, atr, t0


def evaluate(levels, data, p: Params = DEFAULT) -> tuple[Setup, Optional[Episode], bool]:
    """(row, newest episode, triggered on the newest closed bar)."""
    if getattr(levels, "status", None) != "OK" or levels.avwap is None:
        return Setup(CODE, NAME, "UNKNOWN", None, "levels unavailable"), None, False
    try:
        w = _window(levels, data)
    except ValueError as exc:                 # too few bars for ATR(11)
        return Setup(CODE, NAME, "UNKNOWN", None, str(exc)), None, False
    if w is None:
        return Setup(CODE, NAME, "UNKNOWN", None, "no closed bars in the window"), None, False
    h, l, c, v, atr, t0 = w
    eps = scan(h, l, c, v, atr, levels.val, levels.vah, t0, p)
    if not eps:
        return Setup(CODE, NAME, "NONE", None, f"no close beyond VAH {levels.vah:.6g} / VAL {levels.val:.6g} yet"), None, False
    ep = eps[-1]
    newest = len(c) - 1
    edge = "VAH" if ep.direction == "bullish" else "VAL"
    er = f"effort {ep.effort:.1f}x vol, result {ep.result:.1f}x ATR" if ep.effort is not None else "effort/result unknown"
    detail = f"{edge} {ep.level:.6g} break: {ep.label} ({er})"
    state = ep.state
    if state == "BREAK":
        detail += " -- waiting for a pullback that holds"
    elif state == "PULLBACK":
        detail += f" -- pullback held; BOS needs a close {'above' if ep.direction == 'bullish' else 'below'} {ep.bos_level:.6g}"
    elif state == "TRIGGERED":
        state = "PENDING" if ep.end_index == newest else "TRIGGERED"
        detail += f" -- pullback held, BOS close beyond {ep.bos_level:.6g}"
    elif state == "FAILED":
        detail += " -- pullback went deep back inside"
    elif state == "EXPIRED":
        detail += f" -- no BOS within {p.max_bars} bars"
    d = ep.direction if ep.label == "HEALTHY" else None
    return Setup(CODE, NAME, state, d, detail), ep, state == "PENDING"


def breakout_pullback(levels, data) -> Setup:
    """The VP-04P row printed under VP-05."""
    return evaluate(levels, data)[0]


def format_line(s: Setup) -> str:
    return f"{s.code} {s.name:<19} {s.state:<11} {s.detail} {TAG}"   # same columns as VP-01..06
