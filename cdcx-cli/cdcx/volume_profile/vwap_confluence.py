"""
vwap_confluence.py
--------------------
Phase 3 of the previous-day AVWAP + AFVP framework (2026-10-16): market
condition, five setup families and grouped evidence, on top of
prev_day.prev_day_levels(). INFORMATION ONLY -- see fvp_analysis.py's
module docstring for scope. `execution` is always "NOT AUTHORIZED".

Every rule reads CLOSED bars only, and a past bar is judged against the
VWAP and sigma bands as they stood at that bar (AnchoredVWAP.series /
sigma_series), never against today's final values. "Today" = bars that
opened at or after the frozen profile's session end.

Market condition (last SLOPE_BARS closed bars):
    EXPANSION  latest close at or beyond +/-EXPANSION_Z sigma -- no mean
               reversion is assumed; wait for continuation vs failure
    TREND      VWAP moved >= TREND_SLOPE_SIGMA sigma over the window AND
               >= TREND_SIDE_FRACTION of closes sat on the slope's side
    BALANCE    VWAP moved <= BALANCE_SLOPE_SIGMA sigma, or price crossed the
               VWAP >= BALANCE_CROSSES times
    UNCLEAR    none of the above

Setups (each reports a state, never a trade):
    VP-01 POC reaction        prior POC: reclaim (low <= POC < close) or
                              rejection (high >= POC > close) in the last
                              REACTION_BARS bars -> PENDING (newest bar) /
                              CONFIRMED (next close held, none lost it) /
                              FAILED
    VP-02 heavy-volume zone   prior value area [VAL, VAH]: UNTESTED /
                              APPROACHING (untested, close within 1 sigma
                              of the nearer edge) / TESTED (n entries today)
    VP-03 trend continuation  TREND only: a pullback bar touched the VWAP
                              (within PULLBACK_SIGMA) and closed on the trend
                              side -> PENDING; CONFIRMED once a later close
                              clears that bar's extreme
    VP-04 value-area breakout first close beyond VAH/VAL today -> PENDING;
                              ACCEPTED after ACCEPT_BARS closes outside;
                              FAILED (a sweep) on a close back inside
    VP-05 band exhaustion     a bar's high/low reached +/-2 sigma in the last
                              REACTION_BARS -> EXTENDED (still outside) /
                              RETURNED (closed back inside +/-2 sigma). A
                              touch is never a reversal by itself.

Evidence families -- one vote each, so related readings aren't counted twice:
    vwap         TREND direction (EXPANSION/BALANCE/UNCLEAR vote nothing)
    volume       VP-04 ACCEPTED and/or VP-01 CONFIRMED (disagreeing -> nothing)
    structure    existing bos_state on the same bars: continuation / retest_held
    price_action most recent unfilled FVG that formed today
VP-02, VP-05 and Fibonacci are context only (no vote).

Qualification:
    UNKNOWN    prior-day levels unavailable (missing/stale data)
    CONFLICT   families vote both ways
    QUALIFIED  >= 3 families agree incl. structure, none oppose, AND the
               caller confirmed 2+ non-transitional higher timeframes agree
               (htf_aligned=True; None = not evaluated -> cannot qualify)
    CANDIDATE  >= 2 families agree, none oppose
    NONE       otherwise
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .. import bos_state as bos_state_module
from ..indicators import fair_value_gap, market_structure
from .prev_day import PrevDayLevels

RULESET_VERSION = "vwap-vp-1"
SLOPE_BARS = 12
TREND_SLOPE_SIGMA = 0.25
TREND_SIDE_FRACTION = 0.8
BALANCE_SLOPE_SIGMA = 0.10
BALANCE_CROSSES = 3
EXPANSION_Z = 2.0
REACTION_BARS = 6
PULLBACK_SIGMA = 0.25
ACCEPT_BARS = 2
PROFILE_NEAR_SIGMA = 0.5


@dataclass
class Setup:
    code: str
    name: str
    state: str                       # NONE / PENDING / CONFIRMED / FAILED / ACCEPTED / ...
    direction: Optional[str] = None  # "bullish" | "bearish" | None
    detail: str = ""


@dataclass
class VwapVpResult:
    status: str                                  # "OK" | "UNKNOWN"
    reasons: list[str] = field(default_factory=list)
    condition: str = "UNKNOWN"                   # TREND / BALANCE / EXPANSION / UNCLEAR
    condition_direction: Optional[str] = None
    condition_detail: str = ""
    z: Optional[float] = None                    # latest close in sigmas from the VWAP
    setups: list[Setup] = field(default_factory=list)
    families: dict[str, Optional[str]] = field(default_factory=dict)   # family -> direction or None
    family_detail: dict[str, str] = field(default_factory=dict)
    qualification: str = "UNKNOWN"
    qualification_direction: Optional[str] = None
    qualification_reason: str = ""
    execution: str = "NOT AUTHORIZED (analysis only)"
    ruleset_version: str = RULESET_VERSION


def _closed_window(levels: PrevDayLevels, data):
    """Indices into `data` of the bars the AVWAP used (anchor .. last closed), aligned with
    levels.avwap.series / sigma_series."""
    a = levels.avwap
    ts = [t / 1000 if t > 1e11 else t for t in data.timestamps]
    idx = [i for i, t in enumerate(ts) if a.anchor_ts <= t <= a.last_bar_ts]
    return ts, idx


def _condition(c, vw, sg) -> tuple[str, Optional[str], str]:
    z = (c[-1] - vw[-1]) / sg[-1] if sg[-1] > 0 else 0.0
    if abs(z) >= EXPANSION_Z:
        d = "bullish" if z > 0 else "bearish"
        return "EXPANSION", d, f"close {z:+.2f} sigma from VWAP (>= {EXPANSION_Z:g})"
    n = min(SLOPE_BARS, len(c) - 1)
    if n < 2 or sg[-1] <= 0:
        return "UNCLEAR", None, "not enough bars since the anchor"
    slope = (vw[-1] - vw[-1 - n]) / sg[-1]
    sides = [ci - vi for ci, vi in zip(c[-n:], vw[-n:])]
    crosses = sum(1 for a, b in zip(sides, sides[1:]) if (a > 0) != (b > 0))
    up_frac = sum(1 for s in sides if s > 0) / n
    detail = f"VWAP slope {slope:+.2f} sigma over {n} bars, {crosses} crosses, {up_frac:.0%} of closes above"
    if abs(slope) >= TREND_SLOPE_SIGMA:
        if slope > 0 and up_frac >= TREND_SIDE_FRACTION:
            return "TREND", "bullish", detail
        if slope < 0 and (1 - up_frac) >= TREND_SIDE_FRACTION:
            return "TREND", "bearish", detail
    if abs(slope) <= BALANCE_SLOPE_SIGMA or crosses >= BALANCE_CROSSES:
        return "BALANCE", None, detail
    return "UNCLEAR", None, detail


def _level_reaction(code, name, level, h, l, c) -> Setup:
    n = len(c)
    for i in range(n - 1, max(n - 1 - REACTION_BARS, -1), -1):
        if l[i] <= level < c[i]:
            d, held = "bullish", lambda x: x >= level
        elif h[i] >= level > c[i]:
            d, held = "bearish", lambda x: x <= level
        else:
            continue
        after = c[i + 1:]
        if not after:
            return Setup(code, name, "PENDING", d, f"{d} reaction at {level:.6g} on the newest closed bar")
        if all(held(x) for x in after):
            return Setup(code, name, "CONFIRMED", d, f"{d} reaction at {level:.6g}, held for {len(after)} bar(s)")
        return Setup(code, name, "FAILED", d, f"{d} reaction at {level:.6g} lost on a later close")
    return Setup(code, name, "NONE", None, f"no reaction at {level:.6g} in the last {REACTION_BARS} bars")


def _zone(levels, h, l, c, sigma) -> Setup:
    inside = [hi >= levels.val and lo <= levels.vah for hi, lo in zip(h, l)]
    entries = sum(1 for k, x in enumerate(inside) if x and (k == 0 or not inside[k - 1]))
    zone = f"prior value area {levels.val:.6g}-{levels.vah:.6g}"
    if entries:
        return Setup("VP-02", "Heavy-volume zone", "TESTED", None, f"{zone} entered {entries} time(s) today")
    if not c:
        return Setup("VP-02", "Heavy-volume zone", "UNTESTED", None, f"{zone}, no bars today yet")
    dist = min(abs(c[-1] - levels.vah), abs(c[-1] - levels.val))
    state = "APPROACHING" if sigma > 0 and dist <= sigma else "UNTESTED"
    return Setup("VP-02", "Heavy-volume zone", state, None, f"{zone} untested today, {dist:.6g} away")


def _continuation(cond, cdir, h, l, c, vw, sg) -> Setup:
    name = "Trend continuation"
    if cond != "TREND":
        return Setup("VP-03", name, "NONE", None, "needs a TREND condition")
    n = len(c)
    for i in range(n - 1, max(n - 1 - REACTION_BARS, -1), -1):
        if cdir == "bullish" and l[i] <= vw[i] + PULLBACK_SIGMA * sg[i] and c[i] > vw[i]:
            later = c[i + 1:]
            if any(x > h[i] for x in later):
                return Setup("VP-03", name, "CONFIRMED", cdir, f"pullback to VWAP held, later close above {h[i]:.6g}")
            return Setup("VP-03", name, "PENDING", cdir, f"pullback to VWAP held, waiting for a close above {h[i]:.6g}")
        if cdir == "bearish" and h[i] >= vw[i] - PULLBACK_SIGMA * sg[i] and c[i] < vw[i]:
            later = c[i + 1:]
            if any(x < l[i] for x in later):
                return Setup("VP-03", name, "CONFIRMED", cdir, f"pullback to VWAP rejected, later close below {l[i]:.6g}")
            return Setup("VP-03", name, "PENDING", cdir, f"pullback to VWAP rejected, waiting for a close below {l[i]:.6g}")
    return Setup("VP-03", name, "NONE", cdir, f"no pullback to the VWAP in the last {REACTION_BARS} bars")


def _breakout(levels, c, prev_close) -> Setup:
    name = "Value-area breakout"
    last = None
    for k, x in enumerate(c):
        before = c[k - 1] if k else prev_close
        if x > levels.vah and (before is None or before <= levels.vah):
            last = (k, "bullish")
        elif x < levels.val and (before is None or before >= levels.val):
            last = (k, "bearish")
    if last is None:
        return Setup("VP-04", name, "NONE", None, "no close beyond the prior VAH/VAL today")
    k, d = last
    level = levels.vah if d == "bullish" else levels.val
    after = c[k + 1:]
    outside = (lambda x: x > level) if d == "bullish" else (lambda x: x < level)
    if not all(outside(x) for x in after):
        return Setup("VP-04", name, "FAILED", d, f"broke {level:.6g}, closed back inside (sweep)")
    if len(after) >= ACCEPT_BARS:
        return Setup("VP-04", name, "ACCEPTED", d, f"{len(after) + 1} closes beyond {level:.6g}")
    return Setup("VP-04", name, "PENDING", d, f"broke {level:.6g}, {len(after) + 1}/{ACCEPT_BARS + 1} closes so far")


def _exhaustion(levels, h, l, c, vw, sg) -> Setup:
    name = "Band exhaustion"
    n = len(c)
    for i in range(n - 1, max(n - 1 - REACTION_BARS, -1), -1):
        if sg[i] <= 0:
            continue
        up, dn = (h[i] - vw[i]) / sg[i], (l[i] - vw[i]) / sg[i]
        if up >= 2 or dn <= -2:
            upper = up >= 2
            extreme = h[i] if upper else l[i]
            prof = [nm for nm, v in (("POC", levels.poc), ("VAH", levels.vah), ("VAL", levels.val),
                                     ("HVN", levels.hvn), ("LVN", levels.lvn))
                    if v is not None and abs(v - extreme) <= PROFILE_NEAR_SIGMA * sg[i]]
            band = f"{'+' if upper else '-'}{3 if abs(up if upper else dn) >= 3 else 2} sigma"
            back = (lambda k: c[k] < vw[k] + 2 * sg[k]) if upper else (lambda k: c[k] > vw[k] - 2 * sg[k])
            d = "bearish" if upper else "bullish"
            note = f"reached {band} at {extreme:.6g}" + (f", near prior {'/'.join(prof)}" if prof else "")
            if back(n - 1):
                return Setup("VP-05", name, "RETURNED", d, note + "; closed back inside +/-2 sigma (needs structure)")
            return Setup("VP-05", name, "EXTENDED", None, note + "; still outside -- not a reversal signal")
    return Setup("VP-05", name, "NONE", None, f"no +/-2 sigma touch in the last {REACTION_BARS} bars")


def classify(levels: PrevDayLevels, data, htf_aligned: Optional[bool] = None) -> VwapVpResult:
    """Condition, setups and evidence from prev_day_levels() output and the SAME OHLCV series."""
    out = VwapVpResult(status="UNKNOWN")
    if levels.status != "OK" or levels.avwap is None:
        out.reasons = ["prior-day levels unavailable: " + "; ".join(levels.reasons or ["unknown"])]
        out.qualification_reason = out.reasons[0]
        return out
    ts, idx = _closed_window(levels, data)
    vw, sg = levels.avwap.series, levels.avwap.sigma_series
    if len(idx) != len(vw):
        out.reasons = ["bar window does not match the VWAP series"]
        return out
    h = [data.highs[i] for i in idx]
    l = [data.lows[i] for i in idx]
    c = [data.closes[i] for i in idx]

    out.status = "OK"
    out.condition, out.condition_direction, out.condition_detail = _condition(c, vw, sg)
    out.z = (c[-1] - vw[-1]) / sg[-1] if sg[-1] > 0 else 0.0

    t0 = next((k for k, i in enumerate(idx) if ts[i] >= levels.session_end), len(idx))   # first bar of today
    th, tl, tc = h[t0:], l[t0:], c[t0:]
    prev_close = c[t0 - 1] if t0 > 0 else None

    poc = _level_reaction("VP-01", "POC reaction", levels.poc, th[-REACTION_BARS:], tl[-REACTION_BARS:],
                          tc[-REACTION_BARS:]) if tc else Setup("VP-01", "POC reaction", "NONE", None, "no bars today yet")
    out.setups = [
        poc,
        _zone(levels, th, tl, tc, sg[-1]),
        _continuation(out.condition, out.condition_direction, h, l, c, vw, sg),
        _breakout(levels, tc, prev_close),
        _exhaustion(levels, h, l, c, vw, sg),
    ]
    by_code = {s.code: s for s in out.setups}

    # --- evidence families (one vote each) ---
    fam: dict[str, Optional[str]] = {}
    det: dict[str, str] = {}
    fam["vwap"] = out.condition_direction if out.condition == "TREND" else None
    det["vwap"] = f"{out.condition}: {out.condition_detail}"

    vol_votes = {s.direction for s in (by_code["VP-04"], by_code["VP-01"])
                 if s.state in ("ACCEPTED", "CONFIRMED") and s.direction}
    fam["volume"] = vol_votes.pop() if len(vol_votes) == 1 else None
    det["volume"] = f"VP-04 {by_code['VP-04'].state}, VP-01 {by_code['VP-01'].state}"

    all_c = list(data.closes[:idx[-1] + 1])
    all_h, all_l = list(data.highs[:idx[-1] + 1]), list(data.lows[:idx[-1] + 1])
    ms = market_structure.analyze(all_h, all_l, price=all_c[-1])
    bos = bos_state_module.classify_bos_state(ms, all_h, all_l, all_c, list(data.volumes[:idx[-1] + 1]))
    bos_dir = {"up": "bullish", "down": "bearish"}.get(bos.direction or "")
    fam["structure"] = bos_dir if bos.state in ("continuation", "retest_held") else None
    det["structure"] = f"BOS {bos.state}" + (f" {bos_dir} at {bos.level_price:.6g}" if bos_dir else "")

    gaps = []
    if t0 < len(idx):
        gaps = [g for g in fair_value_gap.detect_fvgs(all_h, all_l, all_c) if not g.filled and g.index >= idx[t0]]
    fam["price_action"] = gaps[-1].kind if gaps else None
    det["price_action"] = (f"unfilled {gaps[-1].kind} FVG {gaps[-1].bottom:.6g}-{gaps[-1].top:.6g}"
                           if gaps else "no unfilled FVG formed today")
    out.families, out.family_detail = fam, det

    out.qualification, out.qualification_direction, out.qualification_reason = qualify(fam, htf_aligned)
    return out


def qualify(families: dict[str, Optional[str]], htf_aligned: Optional[bool]) -> tuple[str, Optional[str], str]:
    """(qualification, direction, reason) from the family votes -- see the module docstring."""
    bull = [k for k, v in families.items() if v == "bullish"]
    bear = [k for k, v in families.items() if v == "bearish"]
    if bull and bear:
        return "CONFLICT", None, f"bullish: {', '.join(bull)} vs bearish: {', '.join(bear)}"
    agree, d = (bull, "bullish") if bull else (bear, "bearish")
    if len(agree) >= 3 and "structure" in agree and htf_aligned is True:
        return "QUALIFIED", d, f"{len(agree)} families agree ({', '.join(agree)}) and higher timeframes align"
    if len(agree) >= 2:
        missing = []
        if len(agree) < 3 or "structure" not in agree:
            missing.append("3 families incl. structure")
        if htf_aligned is not True:
            missing.append("2+ aligned non-transitional higher timeframes"
                           + (" (not evaluated)" if htf_aligned is None else ""))
        return "CANDIDATE", d, f"{', '.join(agree)} agree; still needs {' and '.join(missing)}"
    if agree:
        return "NONE", None, "one family only: " + agree[0]
    return "NONE", None, "no family has a directional vote"


def format_vwap_vp(symbol: str, timeframe: str, levels: PrevDayLevels, res: VwapVpResult, price: float) -> str:
    from datetime import datetime, timezone

    bar = "-" * 81
    lines = [bar, f"PREV-DAY AVWAP + AFVP -- {symbol} {timeframe} (analysis only, {RULESET_VERSION})".center(81), bar]
    if levels.status != "OK":
        lines += [f"UNKNOWN -- {'; '.join(levels.reasons)}", bar]
        return "\n".join(lines)
    f = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%m-%d %H:%MZ")
    a = levels.avwap
    lines += [
        f"Prior session {f(levels.session_start)} -> {f(levels.session_end)} ({levels.session_bars} bars), frozen:",
        f"  POC {levels.poc:.6g} | VAH {levels.vah:.6g} | VAL {levels.val:.6g} | HVN {levels.hvn:.6g} | LVN {levels.lvn:.6g}",
        f"AVWAP from {f(a.anchor_ts)} ({a.source}): {a.vwap:.6g}  sigma {a.sigma:.6g}  (last closed bar {f(a.last_bar_ts)})",
        "  " + " | ".join(f"+/-{k}: {lo:.6g} / {hi:.6g}" for k, (lo, hi) in a.bands.items()),
        f"Price {price:.6g} = {res.z:+.2f} sigma | Condition: {res.condition}"
        + (f" ({res.condition_direction})" if res.condition_direction else "") + f" -- {res.condition_detail}",
        "",
    ]
    for s in res.setups:
        lines.append(f"{s.code} {s.name:<20} {s.state:<11} {s.detail}")
    lines.append("")
    for k in ("vwap", "volume", "structure", "price_action"):
        lines.append(f"  {k:<13} {res.families.get(k) or '--':<9} {res.family_detail.get(k, '')}")
    lines += ["", f"DECISION: {res.qualification}"
              + (f" ({res.qualification_direction})" if res.qualification_direction else "")
              + f" -- {res.qualification_reason}", f"Execution: {res.execution}", bar]
    return "\n".join(lines)
