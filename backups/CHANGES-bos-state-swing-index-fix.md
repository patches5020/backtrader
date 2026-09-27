# BOS State Fix: Breaks Only Count After the Swing Forms — Change Summary

Date: 2026-09-27
Commit: b021961 (pushed to patches5020/backtrader master)
Repo touched: `cdcx-cli/` only.

## Bug
`bos_state` used `structure_levels.detect_breakout` over the whole 20-bar
lookback, so a close from BEFORE a swing high/low existed counted as a
"break" of it.
- Live XRP 1H 2026-09-27: "bullish break of 1.5298" cited a 12:00 close;
  the swing high formed at 21:00.
- XRP baseline 1D "failed bearish break of 1.4516": cited Sep 19; swing Sep 23.
- XRP baseline 4H "failed bearish break of 1.5168": cited 03:00; swing 23:00.
Tonight's "XRP's 3rd failed bearish break" narrative was wrong — only the
1H 1.5145 break (11 PM) and its midnight rejection were real. A
correction was sent to Telegram.

## Fix
- `cdcx/structure_levels.py`: `detect_breakout(..., min_index=0)`.
  Default 0 keeps fixed-level callers (vp_setup, structure_strategy) unchanged.
- `cdcx/bos_state.py`: passes `swing.index + 1`.
- `tests/test_bos_state.py`: 2 regression tests.
- `tests/test_baseline_xrp_mtf.py`: VP-BOS 1D/4H expect NONE (user
  approved). Baseline verdict unchanged.

## Scope
Display-only: BOS STATE text + advisory VP-BOS. entry_location only
prints the text; no gate reads bos_state.

Full suite: 427 passed.
