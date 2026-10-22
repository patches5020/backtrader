"""
vp_reentry.py
---------------
VP-06 value-area re-entry (2026-10-22) -- RESEARCH ONLY (RQ7, see
.ai/SHARED/research_questions.md). Printed under VP-05 in the PREV-DAY
AVWAP + AFVP section and the HTF AVWAP context; it is NOT part of
vwap_confluence.classify(), so it never enters res.setups, an evidence
family, the DECISION, vwap_watch (RQ6 frozen) or vwap_vp_research (RQ3/RQ5).
No gate, grade, sizing or execution path reads it.

Hypothesis (from the Trading Notes "3 setups" video, setup 2): when the
prior session CLOSED INSIDE its value area, a move out of the value area
that closes back inside tends to travel to the far edge.

Rules (closed bars only; "today" = bars after the frozen session, exactly
as classify() defines it -- on the HTF block, the last VP_WINDOW_BARS):

    precondition   prior close (last closed bar before today) inside
                   [VAL, VAH], inclusive. Otherwise N/A.
    excursion      a close today above VAH (bearish case) or below VAL
                   (bullish case). Wicks don't count.
    re-entry       the first later close back inside [VAL, VAH] -- the
                   signal bar. Direction: bullish after a close below VAL,
                   bearish after a close above VAH.
    after it       TARGET REACHED   a later high >= VAH (bullish) / low <= VAL
                                    (bearish): the far edge
                   FAILED           a later close back outside on the
                                    excursion side, before the target
                   ACTIVE           neither yet
    repeatable     the newest excursion/re-entry episode is the one reported.

States: UNKNOWN / N/A / NONE / OUTSIDE / PENDING (re-entry on the newest
closed bar) / ACTIVE / TARGET REACHED / FAILED. The excursion extreme is
shown as a structural reference only -- the cdcx stop stays 1.5 x ATR.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .vwap_confluence import Setup, _closed_window

CODE = "VP-06"
NAME = "Value-area re-entry"
TAG = "[research only, RQ7]"


def reentry_events(closes: list[float], val: float, vah: float, start: int = 0) -> list[tuple[int, str, int]]:
    """Every re-entry in closes[start:]: [(signal index, direction, excursion start index)]. A re-entry needs
    a close outside the value area at or after `start`, then the first close back inside."""
    out = []
    side = None          # "above" / "below" while outside
    exc_start = None
    for k in range(start, len(closes)):
        x = closes[k]
        if x > vah or x < val:
            now = "above" if x > vah else "below"
            if side != now:
                side, exc_start = now, k
        elif side is not None:
            out.append((k, "bullish" if side == "below" else "bearish", exc_start))
            side, exc_start = None, None
    return out


@dataclass
class Reentry:
    setup: Setup
    target: Optional[float] = None       # far edge (VAH bullish / VAL bearish) of the newest episode
    extreme: Optional[float] = None      # excursion low (bullish) / high (bearish) -- reference only
    prior_inside: Optional[bool] = None  # prior close inside [VAL, VAH]; None = unknown


def evaluate(levels, data, require_inside_prior: bool = True) -> Reentry:
    """VP-06 for one PrevDayLevels-shaped input and the SAME OHLCV series classify() reads.
    require_inside_prior=False skips the precondition (research comparator only, RQ7 VP-06x)."""
    def r(state, detail, d=None, **kw):
        return Reentry(Setup(CODE, NAME, state, d, detail), **kw)

    if getattr(levels, "status", None) != "OK" or levels.avwap is None:
        return r("UNKNOWN", "levels unavailable")
    ts, idx = _closed_window(levels, data)
    if not idx:
        return r("UNKNOWN", "no closed bars in the window")
    h = [data.highs[i] for i in idx]
    l = [data.lows[i] for i in idx]
    c = [data.closes[i] for i in idx]
    t0 = next((k for k, i in enumerate(idx) if ts[i] >= levels.session_end), len(idx))
    val, vah = levels.val, levels.vah
    if t0 == 0:
        return r("UNKNOWN", "no closed bar before the window -- prior close unknown")
    prior = c[t0 - 1]
    inside = val <= prior <= vah
    if require_inside_prior and not inside:
        where = "above VAH" if prior > vah else "below VAL"
        return r("N/A", f"prior close {prior:.6g} {where} -- needs a close inside the value area", prior_inside=False)
    if t0 >= len(c):
        return r("NONE", f"prior close {prior:.6g} inside; no bars yet", prior_inside=inside)
    events = reentry_events(c, val, vah, start=t0)
    last = c[-1]
    if last > vah or last < val:
        side = "above VAH" if last > vah else "below VAL"
        return r("OUTSIDE", f"closed {side} at {last:.6g} -- waiting for a close back inside", prior_inside=inside)
    if not events:
        return r("NONE", f"prior close {prior:.6g} inside; no close outside {val:.6g}-{vah:.6g} yet",
                 prior_inside=inside)
    k, d, e0 = events[-1]
    bull = d == "bullish"
    target = vah if bull else val
    extreme = min(l[e0:k + 1]) if bull else max(h[e0:k + 1])
    entry = c[k]
    risk = abs(entry - extreme)
    rr = f", {abs(target - entry) / risk:.1f}R to the far edge" if risk > 0 else ""
    ref = (f"re-entered at {entry:.6g} after a close {'below VAL' if bull else 'above VAH'}; "
           f"target {'VAH' if bull else 'VAL'} {target:.6g}; excursion {'low' if bull else 'high'} "
           f"{extreme:.6g} (reference only){rr}")
    kw = dict(target=target, extreme=extreme, prior_inside=inside)
    after = list(zip(h[k + 1:], l[k + 1:], c[k + 1:]))
    if not after:
        return r("PENDING", ref, d, **kw)
    for hi, lo, x in after:
        if (hi >= target) if bull else (lo <= target):
            return r("TARGET REACHED", ref, d, **kw)
        if (x < val) if bull else (x > vah):
            return r("FAILED", ref + "; closed back outside", d, **kw)
    return r("ACTIVE", ref, d, **kw)


def value_area_reentry(levels, data) -> Setup:
    """The VP-06 row printed under VP-05."""
    return evaluate(levels, data).setup


def format_line(s: Setup) -> str:
    """Same column layout as VP-01..VP-05 (vwap_confluence.format_setup_lines)."""
    return f"{s.code} {s.name:<20} {s.state:<11} {s.detail} {TAG}"
