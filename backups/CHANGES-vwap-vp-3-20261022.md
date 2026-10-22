# vwap-vp-3 display levels (1m @ 400 rows, TradingView-matched) — 2026-10-22

Follows the RQ10 1m follow-up. The user said "Yes to all" (add the vwap-vp-3 display line).

- `cdcx/volume_profile/prev_day_v3.py` (new):
  - POC/VAH/VAL of the same frozen session from 1m bars at 400 rows.
  - Calls the frozen `prev_day_v2.levels_v2` unchanged with `fine_tf="1m"`, so the profile math is the same.
  - Fails closed on a missing 1m bar.
- PREV-DAY AVWAP + AFVP prints one extra line under the vwap-vp-2 line:
  `vwap-vp-3 (1m @ 400 rows, TradingView-matched, display only): POC .. | VAH .. | VAL ..  (vs vwap-vp-1: ...)`.
  - cdcx-ai fetches about 2 days of 1m (2,900 candles, paginated).
  - cdcx-equity fetches 1,200 1m candles from Webull. Robinhood has no 1m, so the line reads UNKNOWN there.
  - It is never read by `classify()`, the families, the DECISION, the watcher, RQ3–RQ11, the gates or execution.
- Live XRP 10-21 session:
  - vwap-vp-1 POC 1.38537 / VAH 1.39103 / VAL 1.35425.
  - vwap-vp-2 POC 1.3566 / VAH 1.38715 / VAL 1.35201.
  - **vwap-vp-3 POC 1.35744 / VAH 1.38715 / VAL 1.35167.**
  - TradingView FRVP (RQ10 step 2) POC 1.3575 / VAH 1.387 / VAL 1.3516.
- Display only: no outcome test yet. Scoring setups on vwap-vp-3 would need its own pre-registered RQ (like RQ11).
- Tests: `test_prev_day_v3.py` (6), plus the `test_vwap_vp_context.py` stub updated for `minute_data`. Full suite 918 passed.
- Protected params unchanged. RQ6–RQ11 frozen files and texts untouched.
