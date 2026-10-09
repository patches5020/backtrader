# Circuit breaker equity curve + paper close time (2026-10-09) -- commit 1382183

Circuit breaker is a protected area; this change was approved by the user on 2026-10-09. Thresholds unchanged
(3 consecutive losses / 10% drawdown).

## 1. Drawdown is computed on a cumulative equity curve
- **The bug.** `check_circuit_breaker_for_symbol` used each trade's own `account_balance + realized_pnl` as its
  equity point. With a constant `--balance`, every point was `1000 - loss`:
  - the starting balance was never the peak, so the first loss showed 0.00% drawdown;
  - losses never compounded: 3 x -$20 read as 2%, so the 10% trigger could not trip on a losing run.
- **The fix.** The curve starts at the first trade's `account_balance` and adds each closed trade's realized P&L in
  close order. 3 x -$20 on $1,000 now reads 6%.
- **Blocks trades, verified at both layers:**
  - cdcx `--execute` path: new test, 3 losses -> "Circuit breaker tripped -- no trade opened.", ledger unchanged;
  - VP watcher: with the breaker forced to trip, R12 fails for both plans and all_met is false (live check).

## 2. Paper closes are stamped with the candle that touched the level
- `update_trade_bars(..., times)` stamps `closed_at` and `partial_closes[].at`; `--update-trades` passes each 5m
  candle's open time. A single-price `update_trade()` still stamps "now".
- XRP 5a75fd5f re-recorded from the pre-close ledger: closed 2026-10-08 15:10 UTC (was 16:42, the run time),
  -$20.00 / -1R. Breaker now: 1/3 losses, 2.0% drawdown (peak 1000 -> 980), clear.

## Also done (no code change)
- **Autostart:** the new supervisor script was tested in a sandbox with stub services: it started the VP watcher and
  restarted it about 2 s after a `kill -9`. The live `cdcx-autostart` task was then ended and re-run; the new
  supervisor (pid 22429) found the bot, BOS watcher and VP watcher running and started no duplicates. The old
  supervisor loop was stopped.
- **Approval safeguards** re-run: 22/22 offline checks pass.

## Verified
- 664 passed (7 new tests).
