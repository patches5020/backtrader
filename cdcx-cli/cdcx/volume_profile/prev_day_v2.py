"""
prev_day_v2.py
----------------
vwap-vp-2 previous-session levels (2026-10-22) -- DISPLAY ONLY. RQ10 found
that cdcx's 1h / 24-row profile sits a median 0.30 (XRP) - 0.95 (XLM) ATR from
TradingView's Fixed Range VP, and that 5m source bars roughly halve that.
This module computes POC / VAH / VAL of the SAME frozen session as
prev_day.prev_day_levels, from 5m bars at 400 rows, with
volume_profile_fixed's math unchanged.

It is a second, parallel ruleset: vwap-vp-1 (prev_day.py, 1h / 24 rows) stays
the one classify(), VP-01..VP-06, VP-04P, VP-01F, the DECISION, vwap_watch
(RQ6) and RQ3-RQ9 use. Nothing reads vwap-vp-2 except the printed line and
the RQ11 research driver. Fails closed: a missing 5m bar -> UNKNOWN.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .. import no_trade_gate
from ..indicators.volume_profile_fixed import build_volume_profile, calculate_poc_vah_val

RULESET_V2 = "vwap-vp-2"
FINE_TF = "5m"
ROWS = 400


@dataclass
class LevelsV2:
    status: str                       # "OK" | "UNKNOWN"
    reason: str = ""
    poc: Optional[float] = None
    vah: Optional[float] = None
    val: Optional[float] = None
    bars: int = 0


def levels_v2(fine, session_start: float, session_end: float, fine_tf: str = FINE_TF, rows: int = ROWS) -> LevelsV2:
    """POC / VAH / VAL from the `fine_tf` bars that opened in [session_start, session_end)."""
    if fine is None or session_start is None or session_end is None:
        return LevelsV2("UNKNOWN", "no 5m data")
    tf_s = no_trade_gate.timeframe_to_seconds(fine_tf)
    ts = [no_trade_gate.timestamp_to_seconds(t) for t in fine.timestamps]
    idx = [i for i, t in enumerate(ts) if session_start <= t < session_end]
    want = int((session_end - session_start) // tf_s)
    if len(idx) != want:
        return LevelsV2("UNKNOWN", f"{len(idx)}/{want} {fine_tf} bars in the session", bars=len(idx))
    h = [fine.highs[i] for i in idx]
    l = [fine.lows[i] for i in idx]
    v = [fine.volumes[i] for i in idx]
    try:
        poc, vah, val = calculate_poc_vah_val(build_volume_profile(h, l, v, buckets=rows))
    except ValueError as exc:
        return LevelsV2("UNKNOWN", str(exc), bars=len(idx))
    return LevelsV2("OK", poc=poc, vah=vah, val=val, bars=len(idx))


def format_line(v2: LevelsV2, v1) -> str:
    """One line under the vwap-vp-1 levels: the v2 levels and their difference from v1."""
    from ..utils.color import colorize_poc, colorize_vah, colorize_val

    head = f"  {RULESET_V2} ({FINE_TF} @ {ROWS} rows, display only):"
    if v2.status != "OK":
        return f"{head} UNKNOWN -- {v2.reason}"
    d = lambda a, b: f"{a - b:+.4g}" if b is not None else "n/a"
    return (f"{head} {colorize_poc(f'POC {v2.poc:.6g}')} | {colorize_vah(f'VAH {v2.vah:.6g}')} | "
            f"{colorize_val(f'VAL {v2.val:.6g}')}  (vs vwap-vp-1: POC {d(v2.poc, v1.poc)}, "
            f"VAH {d(v2.vah, v1.vah)}, VAL {d(v2.val, v1.val)})")
