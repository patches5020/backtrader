# VP-BOS Terminology Lock + Temporal Causality Invariant — Change Summary

Date: 2026-09-27
Commit: 2f0a040 (pushed to patches5020/backtrader master)
Repo touched: `cdcx-cli/` only. Advisory/informational — no gate change.

## States (locked)
- NONE: no legitimate structural break. Closes past the swing by less
  than 0.25x ATR (margin kept by user decision) = raw-flag NOTE, not a state.
- BOS-PENDING: legitimate break, VP acceptance not confirmed
  (was BOS-UNCONFIRMED; BOS-RETEST folded in).
- VP-BOS: legitimate break + volume acceptance.
- BOS-FAILED: legitimate break, then reclaimed.

## Display
MULTI-TIMEFRAME STRUCTURE / VP SUMMARY:
TF | SWING | BOS | LEVEL | VP ACCEPTANCE | POC | RESULT
+ counts: VP-BOS CONFIRMED n/4 (bull/bear, direction), BOS-PENDING n/4,
BOS-FAILED n/4, and a raw-flag notes list.

## Temporal causality invariant
break_index > swing_index. BosState and VpBos carry both indexes.
Tests: after-direction, before-direction (test_bos_state regression),
300-series randomized check (123/300 violate under pre-fix behaviour).

## Live XRP (2:39 AM)
All four NONE; 4H raw bearish flag noted (closed 0.0013 below 1.5168,
needs 0.008325). VP-BOS CONFIRMED 0/4, PENDING 0/4, FAILED 0/4.

Full suite: 430 passed. Baseline verdict unchanged.
