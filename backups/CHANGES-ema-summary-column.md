# EMA Summary Column — Change Summary

Date: 2026-09-26
Repo touched: `cdcx-cli/` only (canonical, pip-installed copy).

## Change
Added an `EMA` column (bullish / bearish / neutral) to the
MULTI-TIMEFRAME SUMMARY table in both `cdcx-ai` (`cdcx/cli.py`) and
`cdcx-equity` (`cdcx/cli_equity.py`), after the `FVG` column.

- New `_ema_bias(signal)` helper in each file: reads the sign of the
  existing `signal.scores["ema_trend"]` (the same "Ema Trend" score shown
  in each timeframe's indicator breakdown) — no new EMA calculation.
  `>0` bullish, `<0` bearish, `0` neutral. ERROR rows show `--`.
- Table still fits the 113-char bar exactly.
- Display only — no effect on scoring, confluence, entries, SL/TP or sizing.

Tests: full suite 392 passed.
