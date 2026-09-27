# Change Log (newest first)

Each entry: date, commit, what changed, whether any protected parameter changed.
Claude Code appends here after each handoff task. Full detail: `backups/CHANGES-*.md` and `git log`.

## 2026-09-27
- ChatGPT <-> Claude Code handoff layer added (`.ai/`, `CLAUDE.md`); validator checks 15 protected values
  against the live code. Protected params: unchanged.
- `2f0a040` VP-BOS terminology locked (NONE / BOS-PENDING / VP-BOS / BOS-FAILED); summary table split into
  SWING / BOS / VP ACCEPTANCE / RESULT; temporal causality invariant tests. Protected params: unchanged.
- `b021961` bos_state: only closes AFTER a swing formed can break it (false 1D/4H/1H "failed breaks" removed).
  Baseline VP-BOS rows updated with user approval; baseline verdict unchanged. Protected params: unchanged.
- `c867591` Equity weekly bars close Friday 16:00 ET (crypto weeks still 7 days). Protected params: unchanged.
- `0ecbe76` Webull weekly bars re-stamped to Monday. Protected params: unchanged.
- `7d448bf` Robinhood weekly bars built from daily data. Protected params: unchanged.
- `da9bbdb` Forming-candle check handles second-resolution equity timestamps. Protected params: unchanged.
- `7d0934a` Advisory VP-BOS added. Protected params: unchanged.

## 2026-09-26
- `dedee18` XRP multi-timeframe baseline regression test. Protected params: unchanged.
- `efd87be` EMA + FVG columns in the MULTI-TIMEFRAME SUMMARY. Protected params: unchanged.
