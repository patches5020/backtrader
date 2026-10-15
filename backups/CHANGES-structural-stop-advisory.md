# Retest watchers: advisory structural stop (2026-10-15) -- commit 2929de2

## `cdcx-cli/trading/alerts/xrp_vwap_retest_watch.py` (`levels()`, shared) + `xrp_bounce_zone_watch.py`
- Alerts and `--once` now add, after the 2x ATR levels:
  - **Structural stop** = rejection-candle high + 0.25 x ATR(5m), with its distance as a multiple of the ATR stop distance.
  - Whether the ATR stop sits **below the rejection high (inside the tested zone)**.
- **Advisory only, user-approved 2026-10-15.** The 2x ATR stop, TP1-4, breakeven, sizing and every cdcx gate are unchanged.
- Why: the 00:45Z bounce-zone alert (entry 1.3266) had its ATR stop 1.3316 hit by a 1.3323 high that never exceeded the
  1.3328 rejection high; the advisory structural stop (1.3334, 1.37x) would not have been hit. The 00:00Z alert
  (entry 1.3301) filled all four TPs. Two cases -- research evidence, not a rule change.
- Both watchers restarted at 05:45Z on the new code; state files kept, so no alert repeats.

## Tests
667 passed; handoff validation PASS; `levels()` checked for an ATR stop below / above the rejection high and with no
rejection; `--once` dry runs of both watchers.

Protected params: unchanged. Not included: unrelated local edit to `trading/alerts/xrp_vp_plan_watch.py`.
