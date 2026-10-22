"""
vp_first_touch.py
-------------------
VP-01F first-touch POC filter (2026-10-22) -- RESEARCH ONLY (RQ9,
.ai/SHARED/research_questions.md). A filter on the EXISTING VP-01 reaction,
not a replacement: VP-01 itself is unchanged. Like VP-06 / VP-04P it prints
under VP-05 and is NOT part of vwap_confluence.classify(), so it never
enters res.setups, an evidence family, the DECISION, vwap_watch (RQ6
frozen) or vwap_vp_research (RQ3/RQ5). Nothing that trades reads it.

Hypothesis (Trading Notes "3 setups" video, setup 1): a POC reaction is
better when (F1) the prior session closed OUTSIDE its value area, (F2) it
is the first touch of the POC today, and (F3) the reaction candle has more
volume than the candle before it.

    reaction   the newest bar of today's last REACTION_BARS with
               low <= POC < close (bullish) or high >= POC > close
               (bearish) -- the same rule as vwap_confluence._level_reaction
    F1         prior close (last closed bar before today) < VAL or > VAH
    F2         no bar of today BEFORE the reaction bar overlapped the POC
               zone [POC - zone_atr x ATR, POC + zone_atr x ATR]
    F3         reaction-bar volume > previous bar's volume
    PASS       F1 and F2 and F3; FAIL otherwise; NONE without a reaction

ATR = atr_ema_variant1 ATR(11) at the reaction bar.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..indicators import atr_ema_variant1
from .vwap_confluence import REACTION_BARS, Setup, _closed_window

CODE = "VP-01F"
NAME = "First-touch POC"
TAG = "[research only, RQ9]"
ZONE_ATR = 0.25


@dataclass
class FirstTouch:
    setup: Setup
    reaction_index: Optional[int] = None   # index into the series passed in
    direction: Optional[str] = None        # reaction direction (set even on FAIL)
    f1: Optional[bool] = None
    f2: Optional[bool] = None
    f3: Optional[bool] = None

    @property
    def passed(self) -> bool:
        return bool(self.f1 and self.f2 and self.f3)


def reaction_index(h, l, c, level: float, start: int) -> Optional[tuple[int, str]]:
    """Newest reaction in bars max(start, n - REACTION_BARS) .. n-1 -- mirrors _level_reaction's scan."""
    n = len(c)
    for i in range(n - 1, max(n - 1 - REACTION_BARS, start - 1), -1):
        if l[i] <= level < c[i]:
            return i, "bullish"
        if h[i] >= level > c[i]:
            return i, "bearish"
    return None


def checks(h, l, c, v, atr, poc: float, val: float, vah: float, t0: int,
           zone_atr: float = ZONE_ATR) -> Optional[tuple[int, str, bool, bool, bool]]:
    """(reaction index, direction, F1, F2, F3) on series ending at the newest closed bar; t0 = first bar of today."""
    if t0 < 1 or t0 >= len(c):
        return None
    r = reaction_index(h, l, c, poc, t0)
    if r is None:
        return None
    i, d = r
    a = atr[i] if atr[i] == atr[i] and atr[i] else 0.0
    lo, hi = poc - zone_atr * a, poc + zone_atr * a
    f1 = c[t0 - 1] < val or c[t0 - 1] > vah
    f2 = not any(l[k] <= hi and h[k] >= lo for k in range(t0, i))
    f3 = i >= 1 and v[i] > v[i - 1]
    return i, d, f1, f2, f3


def evaluate(levels, data) -> FirstTouch:
    if getattr(levels, "status", None) != "OK" or levels.avwap is None:
        return FirstTouch(Setup(CODE, NAME, "UNKNOWN", None, "levels unavailable"))
    ts, idx = _closed_window(levels, data)
    if not idx:
        return FirstTouch(Setup(CODE, NAME, "UNKNOWN", None, "no closed bars in the window"))
    end = idx[-1] + 1
    h, l, c, v = (list(x[:end]) for x in (data.highs, data.lows, data.closes, data.volumes))
    try:
        atr = atr_ema_variant1.calculate_atr(h, l, c)
    except ValueError as exc:
        return FirstTouch(Setup(CODE, NAME, "UNKNOWN", None, str(exc)))
    t0 = next((i for i in idx if ts[i] >= levels.session_end), end)
    r = checks(h, l, c, v, atr, levels.poc, levels.val, levels.vah, t0)
    if r is None:
        return FirstTouch(Setup(CODE, NAME, "NONE", None,
                                f"no POC {levels.poc:.6g} reaction in the last {REACTION_BARS} bars"))
    i, d, f1, f2, f3 = r
    mark = lambda ok: "yes" if ok else "NO"
    detail = (f"{d} reaction at POC {levels.poc:.6g}: prior close outside VA {mark(f1)}, "
              f"first touch {mark(f2)}, volume up {mark(f3)}")
    ft = FirstTouch(Setup(CODE, NAME, "PASS" if (f1 and f2 and f3) else "FAIL", None, detail), i, d, f1, f2, f3)
    if ft.passed:
        ft.setup.direction = d
    return ft


def first_touch(levels, data) -> Setup:
    """The VP-01F row printed under VP-05."""
    return evaluate(levels, data).setup


def format_line(s: Setup) -> str:
    return f"{s.code} {s.name:<19} {s.state:<11} {s.detail} {TAG}"   # same columns as VP-01..06
