# vwap-vp-2 display levels (5m @ 400 rows) + RQ11 draft — 2026-10-22

Follows RQ10. The user said "Yes to all" (option 1 display, option 2 outcome test).

- `cdcx/volume_profile/prev_day_v2.py` (new):
  - POC/VAH/VAL of the same frozen session from 5m bars at 400 rows (`volume_profile_fixed` math unchanged).
  - Fails closed on a missing 5m bar.
- PREV-DAY AVWAP + AFVP prints one extra line under the vwap-vp-1 levels:
  `vwap-vp-2 (5m @ 400 rows, display only): POC .. | VAH .. | VAL ..  (vs vwap-vp-1: ...)`.
  - cdcx-ai fetches about 2 days of 5m; cdcx-equity fetches 5m from its source.
  - It is never read by `classify()`, the families, the DECISION, the watcher, RQ3–RQ9, the gates or execution.
- Live XRP 10-21 session:
  - vwap-vp-1 POC 1.38537.
  - vwap-vp-2 POC 1.3566.
  - TradingView (RQ10 step 2) POC 1.3575.
- **Two-peak warning: tested and NOT shipped.** The peak ratio doesn't predict TradingView mismatches (XLM misses at ratios
  0.19–0.37; XRP matches at 1.00). The XLM gaps look like volume-data differences between the Crypto.com API and TradingView's feed (open question).
- `cdcx/backtest/vwap_vp_rq11.py` (new): VP-04 / VP-01 on vwap-vp-2 vs vwap-vp-1 levels.
  - Walk-forward, protected trade model and costs, seed 20261025, 97.5% CIs.
  - A test proves it reproduces vwap-vp-1's signals exactly when the levels aren't swapped.
- RQ11 DRAFT in `research_questions.md` (not frozen; it awaits the user's approval of section 1).
- Tests: `test_prev_day_v2.py` (5), `test_vwap_vp_rq11.py` (4), plus the `test_vwap_vp_context.py` stub updated for `fine_data`. Full suite 911 passed.
- Protected params unchanged. RQ6–RQ9 frozen files and texts untouched.
