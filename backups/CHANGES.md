# ATR-Transition Entry Timing — Change Summary

Date: 2026-08-24
Repos touched: `cdcx-cli/` and `cdcx-cli-plugin/` (mirrored, identical logic)

## New file
- `cdcx/indicators/atr_state.py` — classifies ATR as a per-bar sequence
  (expansion/contraction/flat) and detects two entry-timing transitions:
  - `contraction_to_expansion` — Mode 1 breakout trigger
  - `second_expansion` — expansion, cooldown, expansion again (the
    higher-quality "don't chase the first move" entry)
  - everything else reports as `expansion_continuation` / `contraction` /
    `flat` / `none`, none of which are treated as a trigger

## Modified files (additive only — no existing behavior changed)
- `cdcx/entry_checklist.py` — new optional `atr_series` param on
  `evaluate_entry_checklist()`; when supplied, adds one advisory
  `ChecklistItem` ("ATR transition timing"). Advisory items are excluded
  from `all_passed`, so this cannot block a setup that already satisfies
  every existing required item (EMA/ATR trend, Fibonacci, FVG, Volume
  Profile, risk %, no existing position).
- `cdcx/structure_strategy.py` — `evaluate_structure_setup()`'s header now
  includes a 4H ATR-transition line alongside the existing 1W-bias line.
  Informational only; does not affect `valid`/`direction`.
- `cdcx/cli.py` — `_handle_trending_path` passes `atr_series` through to
  the checklist; `_handle_ranging_path` prints the ATR-transition read as
  a standalone heads-up after the ranging setup (Mode 2 expects a flat
  ATR; an early expansion read is a warning the range may be breaking).

## Tests
- `tests/test_atr_state.py` (new) — 14 cases covering series
  classification and every transition kind.
- `tests/test_entry_checklist.py` — 3 new tests for the optional
  `atr_series` param (omitted / triggered / not-triggered), appended
  after the existing tests.
- `tests/test_structure_strategy.py` — 1 new test asserting the header
  line is present, appended after the existing tests.

## Verification
- `cdcx-cli`: `pytest -q` → 282 passed
- `cdcx-cli-plugin`: `pytest -q` → 178 passed
- No existing test was modified or removed.

## Contents of this backup
- `atr-transition-entry-timing.diff` — full unified diff of every touched
  file in both repos (apply with `git apply` from the `backtrader-repo`
  root, or read directly).
- `FLOWCHART.md` — Mermaid flowchart of the full decision pipeline with
  the new pieces marked `NEW`.
- `src/` — full snapshot of every new/changed file (both repo copies), for
  restoring individual files without needing `git apply`.
