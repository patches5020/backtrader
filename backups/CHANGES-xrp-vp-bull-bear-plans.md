# XRP bullish + bearish VP paper-trade plans (2026-10-09) -- commit b799744

## What changed
- **One watcher, two plans.** `cdcx-cli/trading/alerts/xrp_vp_plan_watch.py` runs `xrp-bull-vp` (long) and
  `xrp-bear-vp` (short). It replaces `xrp_bull_plan_watch.py` (removed from git and disk; its config, plan text,
  state and log stay on disk as a record; its log ends "watcher finished (superseded ...)").
- **12 requirements per plan, closed candles only:** confluence, trending regime (1H not ranging), entry checklist,
  ATR expansion, 1H+4H BOS, reversal/breakdown, anchored VWAP, VP acceptance, FVG, POC bounce/rejection, retest,
  risk/position conflict.
- **Levels from fresh data:** `--arm` takes the nearest confirmed 4H swing high above / low below price and freezes
  them until re-armed. Armed 2026-10-09 09:18 UTC: 1.5237 / 1.3176, VWAP anchor 2026-10-08 16:00, expires Oct 16.
- **Watcher-defined rules (not cdcx):** the bearish POC rejection (traded up to the POC, closed below, next bar held
  below); R8 differs by side (bull: 4H >= 1D VAH; bear: 4H < 4H VAL).
- **Alerts (send-only):** progress, PERMISSION NEEDED, INVALIDATED, DATA UNAVAILABLE. Never trades by itself.
- **Approval** (`--approve <plan-id>`): refuses if not armed, expired, already used, an XRP trade is open, data is
  missing, any requirement fails on fresh bars, or the live gate is the range path or the other direction. Then
  cdcx's own `_handle_execute` runs on that same live data, paper only, 2% of paper equity. One execution per arming.
- **Autostart:** `scripts/cdcx_autostart.sh` supervises the new watcher. The supervisor running on 2026-10-09 uses
  the old copy until next logon; the watcher was started by hand.

## Verified
- 657 passed (cdcx-cli suite).
- 22 offline checks with execution stubbed: unknown/expired/not-met/duplicate approvals, range path refused both
  ways, wrong-direction confluence refused both ways, data failure, open-trade conflict, each side executes once,
  retest held/failed/waiting both sides, bearish POC rejection confirmed/pending/none.
- Live: armed; first check 2/12 met for each plan; plan and progress alerts delivered to Telegram.

## Status at arming
- Bull: R7 VWAP, R12 risk met. Bear: R10 POC rejection, R12 risk met. Live execution gate fails for both
  (all four TFs transitional).
- The bull trigger 1.5237 is far: the slide to 1.3176 left no confirmed 4H swing high (2-bar rule).

Protected params: unchanged.
