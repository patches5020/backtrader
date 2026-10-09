# VP plan execution-safety audit (2026-10-09) -- commit 73abe7c

## Findings and fixes (cdcx-cli/trading/alerts/xrp_vp_plan_watch.py)
- **Restart replay:** not possible. `approve()` is only reachable via `--approve`; the watch loop never calls it, and
  approval is recorded before executing. Verified in separate processes.
- **Concurrent approvals (fixed):** an exclusive lock (`xrp_vp_plan_approve.lock`, gitignored) allows one approval at
  a time; a second is refused, not queued.
- **Expiry / stale data right before execution (fixed):** expiry, approval state and open XRP trades are re-read from
  disk immediately before executing; refused if a new 1H bar closed during the approval or it took over 10 minutes.
- **Conflicting positions:** refused while any XRP paper trade is open (and cdcx's one-entry-per-symbol rule behind it).

## End-to-end (check_vp_plan_e2e.py, temp ledger, one scenario per process)
| Scenario | Result |
|---|---|
| Approve bull (all 12 stubbed as met) | 1 LONG paper trade via cdcx's real open path; 1 Telegram message; audit log |
| Same approval, new process (restart) | Refused: already approved |
| Bear while the bull trade is open | Refused: XRP trade open |
| Bear while bull holds the lock | Refused: another approval in progress |
| Requirements checked on an old 1H bar | Refused: new 1H bar closed |
| Plan expires during the approval | Refused: expired during approval |
| 3 prior XRP losses in the ledger | cdcx's breaker refused (7.99% drawdown, 3 losses); no trade; ⚪ alert |

Offline: check_vp_plan_offline.py 22/22. Suite: 664 passed. Real ledger and plan state untouched (hash checked).

## Ledger backup
`cdcx-cli/cdcx_trades.json` is gitignored by design. Snapshots with a README are in `D:\cdcx-paper-trades\ledger\`:
corrected (current, hash 0c385a1366f5), before the close-time fix, and before the stop close.

## Live
The running watcher was killed; the supervisor restarted it within a minute and it resumed without duplicate alerts.

Protected params: unchanged.
