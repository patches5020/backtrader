# Advisory sections extended to lower timeframes (2026-10-04) -- commit 24eff09

## Request
"All the add-on (advisory) info has not been updated or extended to the lower timeframe."

## Changes (additive, display-only)
For requested timeframes below 1h, each section gets separate lines labelled "context only" or "advisory":

| Section | What lower timeframes get |
|---|---|
| ATR ALIGNMENT | their own list and expanding count |
| VOLUME PROFILE HIERARCHY | their own entries |
| per-timeframe STRUCTURE block | the block, labelled advisory |
| STRUCTURE SETUP | condition/POC/support/resistance + ATR TIMING lines |
| SETUP GRADE | a "not graded" note |
| VP-BOS | rows below a divider, with their own count |
| AVP | evaluated too |
| RANGE MODE PREVIEW | a preview for each one that is ranging |

Files: `cdcx/mtf_context.py` (`lower_timeframes()`), `cdcx/vp_bos.py`, `cdcx/avp_rejection.py`
(optional `timeframes`), `cdcx/cli.py`.

## Protected
These are unchanged and never use lower-timeframe data:
- ATR x/4;
- the VP-BOS 2-of-4 direction;
- the 1W/1D/4H/1H setup roles and grade;
- confluence and the execution gate.

## Verification
- Live run `XRP/USD --timeframes 5m,15m,45m,1h,4h,1d,1w --structure`:
  - all sections show 45M/15M/5M;
  - protected lines unchanged (0/4 ATR, VP-BOS 0/4, setup NO TRADE);
  - 15M/5M ATR timing show a second-expansion trigger;
  - 15M/5M AVP need more history (`--limit 500`).
- Tests: **639 passed** (+8 new). Updated 2 tests that encoded the old "no block for 15m" behaviour, and a stub
  signature. `test_baseline_xrp_mtf.py` 6 passed. `validate_handoff.py`: PASS.
