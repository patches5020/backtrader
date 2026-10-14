# VWAP retest watcher: graded volume + freshness; intraday watchers in autostart (2026-10-14) -- commit c2a06e5

## `cdcx-cli/trading/alerts/xrp_vwap_retest_watch.py`
- The user chose all three C4 variants, so volume now **grades** the alert instead of blocking it:
  | Grade | Rule |
  |---|---|
  | A | rejection volume > SMA of the 17 prior 5m volumes (strict) |
  | B | > MEDIAN of those 17 only (one flush candle can't inflate it) |
  | C | neither -- no volume confirmation |
- Fires on C1 rejection + C2 lower high + C3 15m break + C5 no reclaim, once per rejection candle.
- **Freshness guard:** alerts only if the confirming 15m close is <= 15 min old; older ones are logged, not alerted
  (on restart the 13:50Z setup, confirmed 14:00Z, was correctly logged as stale).
- Fixed an off-by-one that skipped the earliest scannable rejection bar (no live impact; 1,000-bar history).
- The 13:50Z rejection grades C (47.9K vs median 56.8K / SMA 117.2K).

## `scripts/cdcx_autostart.sh`
Starts `xrp_intraday_range_watch.py` and `xrp_vwap_retest_watch.py` (alert-only, send-only) unless their log ends
"watcher finished" (expired/invalidated). Takes effect at the next logon; both are running now.

## Tests
667 passed; offline grade A/B/C, freshness and failed-C3 checks passed; `bash -n` OK.

Protected params: unchanged. Not included: unrelated local edit to `trading/alerts/xrp_vp_plan_watch.py`.
