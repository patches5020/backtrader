# VP plan: sizing preview labelled (2026-10-09) -- commit e3f4c67

Display-only change to `cdcx-cli/trading/alerts/xrp_vp_plan_watch.py`; no rule, level, gate or execution change.

- **The problem.** Each plan printed "Plan (1H, cdcx levels now): entry 1.3789 ..." -- cdcx's generic entry-TF levels at
  the last closed 1H price. It read like the plan's entry, but the bear plan can only fire after a 4H close below the
  armed 1.3176 swing low (R6) and a retest (R11), and cdcx recomputes entry/stop/TPs from the live price at approval.
- **Now:** "Sizing preview at last 1H close (NOT an order or entry level)", the same stop distance and TP R-multiples
  shown at the R6 trigger as an illustration, and a line that the plan only fires after R6 + R11. The PERMISSION NEEDED
  alert says the same.
- **1.3176 confirmed not stale:** the frozen arming level (4H swing low, 2026-10-08 16:00Z); R6 and R11 both use it.
- **Checks:** offline 22/22; permission alert rendered with stubs (temp log, no Telegram); 664 passed; live watcher
  restarted via the supervisor (14:13Z) and resumed without duplicate alerts.
- **Status at the change:** bull 2/12 (R7, R12); bear 3/12 (R8, R9, R12); cdcx gate fails both ways.

Protected params: unchanged.
