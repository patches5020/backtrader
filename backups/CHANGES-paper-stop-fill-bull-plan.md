# Paper stop fills + XRP bull plan watcher (2026-10-09) -- commits 3e1df90, 029104e

## 1. Paper stops/TPs fill at their level (3e1df90)
- **The bug.** `--update-trades` compared only the live ticker to the stop and filled at that price. XRP trade
  5a75fd5f (stop 1.38430654) was recorded at 1.3549: -$23.98 / -1.20R instead of the planned -1R. A wick through
  the stop that recovered before the next run would never have triggered.
- **The fix.** `update_trade_bar(s)` uses each candle's high/low. The fill is the level, or the bar open when the
  bar gapped past it (rule J). A bar touching both a TP and the stop counts as a stop-out. `--update-trades`
  replays 5m candles since `last_checked_at` (new field, old rows still load). `update_trade(trade, price)` unchanged.
- **Verified:** 7 new tests; 657 passed. Ledger restored from backup and re-run: 5a75fd5f closed at 1.38430654,
  -$20.00 / -1R / -2.0%; a second run did not double-close.
- **Not fixed (flagged):** `closed_at` is the run time, not the candle that hit the stop; circuit breaker drawdown
  starts its equity curve after the first trade (shows 0.00% instead of 2.0%). The breaker is protected; awaiting
  approval.

## 2. XRP bullish paper-trade plan watcher (029104e)
- **Plan** `xrp-bull-20261009`, armed 2026-10-09 08:30 UTC, expires 2026-10-16. 12 requirements on closed bars:
  confluence, regime, checklist, ATR, BOS, reversal (4H > 1.4225), VWAP, VP, FVG, POC bounce, retest, risk.
  Invalidation: a 4H close below 1.3900. Levels in `xrp_bull_plan_config.json`.
- **Alerts (send-only):** progress, PERMISSION NEEDED, INVALIDATED. Never trades by itself.
- **Approval** (`--approve`): refuses an expired or already-approved plan; re-checks all 12; preflights live data
  and refuses the range path (could go short) or non-LONG confluence; then runs cdcx's own `_handle_execute`
  in-process on that data, paper only. One execution per plan.
- **Verified:** 6 approval-safeguard and 2 invalidation-window checks (offline, execute stubbed); live restart
  resumed without a duplicate alert; status at arming 2/12 met.
- **Autostart:** `scripts/cdcx_autostart.sh` now supervises it. The supervisor running on 2026-10-09 still uses the
  old copy until the next logon; the watcher was started by hand.

Protected params: unchanged.
