"""
prev_day_v3.py
----------------
vwap-vp-3 previous-session levels (2026-10-22) -- DISPLAY ONLY. The RQ10
follow-up found TradingView's Fixed Range VP is built from 1m intrabar data:
1m @ 400 rows matches it to a median 0.018 (XRP) / 0.044 (XLM) ATR, where
5m (vwap-vp-2) is 0.09 / 0.53 and 1h / 24 rows (vwap-vp-1) is 0.30 / 0.95.
This module computes POC / VAH / VAL of the SAME frozen session from 1m bars
at 400 rows, through prev_day_v2.levels_v2 (frozen in RQ11, called unchanged
with fine_tf="1m").

A third, parallel ruleset: vwap-vp-1 stays the one classify(), VP-01..VP-06,
VP-04P, VP-01F, the DECISION, vwap_watch (RQ6) and RQ3-RQ11 use; vwap-vp-2
stays its own frozen display line. Nothing reads vwap-vp-3 except the printed
line. Fails closed: a missing 1m bar -> UNKNOWN.
"""
from __future__ import annotations

from .prev_day_v2 import LevelsV2, levels_v2

RULESET_V3 = "vwap-vp-3"
FINE_TF = "1m"
ROWS = 400


def levels_v3(fine, session_start: float, session_end: float) -> LevelsV2:
    """POC / VAH / VAL from the 1m bars that opened in [session_start, session_end)."""
    if fine is None:
        return LevelsV2("UNKNOWN", "no 1m data")
    return levels_v2(fine, session_start, session_end, fine_tf=FINE_TF, rows=ROWS)


def format_line(v3: LevelsV2, v1) -> str:
    """One line under the vwap-vp-1 / vwap-vp-2 levels: the v3 levels and their difference from v1."""
    from ..utils.color import colorize_poc, colorize_vah, colorize_val

    head = f"  {RULESET_V3} ({FINE_TF} @ {ROWS} rows, TradingView-matched, display only):"
    if v3.status != "OK":
        return f"{head} UNKNOWN -- {v3.reason}"
    d = lambda a, b: f"{a - b:+.4g}" if b is not None else "n/a"
    return (f"{head} {colorize_poc(f'POC {v3.poc:.6g}')} | {colorize_vah(f'VAH {v3.vah:.6g}')} | "
            f"{colorize_val(f'VAL {v3.val:.6g}')}  (vs vwap-vp-1: POC {d(v3.poc, v1.poc)}, "
            f"VAH {d(v3.vah, v1.vah)}, VAL {d(v3.val, v1.val)})")
