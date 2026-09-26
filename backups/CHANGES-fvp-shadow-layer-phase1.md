# FVP Shadow Layer (Phase 1) + FVG Summary Column — Change Summary

Date: 2026-09-25
Repo touched: `cdcx-cli/` only (canonical, pip-installed copy — see
[[cdcx-cli-fork-merge]]). `cdcx-cli-plugin` was NOT touched this session.

## New package: `cdcx/volume_profile/`
Phase 1 of the FVP (Fixed/Anchored Volume Profile) intelligence layer
requested as a research extension. INFORMATION ONLY — nothing in this
package is read by `entry_checklist.py`, `confluence.py`, `regime.py`, or
any entry/SL/TP/R:R/position-sizing calculation. Reuses the existing
`volume_profile_fixed.py`/`volume_profile_anchor.py` POC/VAH/VAL math
verbatim; no volume-profile calculation is reimplemented.

- `zone_state.py` — `VolumeZone` dataclass (Phase 1 fields: timeframe,
  zone_type, lower/upper/poc price, tested, test_count, first_test; Phase
  2+ fields present but unset: origin_price, setup_type, confluence
  booleans) + `compute_tested_state()`, which walks price action after a
  zone forms and counts touches. `first_test` means the *current* bar is
  the zone's only touch so far, not merely "touched exactly once at some
  point in the past."
- `zone_detector.py` — `detect_fixed_zone()` / `detect_anchored_zone()`,
  each a thin wrapper: the zone boundary is the existing indicator's own
  [VAL, VAH], POC carried through unchanged.
- `zone_lifecycle.py` — `classify_lifecycle()`: DISCOVERED / QUALIFIED /
  UNTESTED / PRICE_APPROACHING / FIRST_TEST / REACTION / TESTED_DEGRADED,
  based on `tested`/`first_test` plus current price's distance from the
  zone (within one zone-height counts as "nearby").
- `fvp_analysis.py` — `build_fvp_shadow_report()` (one fixed + one
  anchored zone for the given timeframe's own OHLCV, never raises past a
  bad indicator read) and `format_fvp_shadow()`. `execution_impact` is
  hardcoded to `"INFORMATION_ONLY"`.

## Modified files (additive only — no existing behavior changed)
- `cdcx/cli.py`:
  - `_print_summary_table()` — new `FVG` column (bullish/bearish/neutral)
    on the MULTI-TIMEFRAME SUMMARY table, derived from the same
    `fair_value_gap` score already computed for that timeframe (new
    `_fvg_bias()` helper, same pattern as the existing `_market_bias()`).
  - `_handle_execute()` — two additive hooks, both wrapped in
    `try/except Exception` so a bug in the new layer can never interrupt
    the real decision flow: one right after the confluence-path regime
    print, one in the separate "RANGE MODE" fastest-timeframe-is-ranging
    shortcut branch. Each prints `format_fvp_shadow()`'s output using the
    `raw_data` already fetched for the real decision — no extra API call.
- `cdcx/cli_equity.py`: identical `_fvg_bias()` addition to its own
  `_print_summary_table()`, and the same single FVP shadow hook on its
  confluence path (no separate RANGE MODE branch exists in this file).
- `tests/test_cli_structure_combination.py`: fixed a pre-existing test-
  fixture gap unrelated to FVP — `_fake_signal()`'s `SimpleNamespace` was
  missing `.scores`, which the FVG-column change (`_fvg_bias()`) reads.
  This was a latent bug from the FVG-column work earlier in the same
  session, caught by running the full suite before finalizing FVP.

## Tests
- `tests/test_volume_profile_zone.py` (new) — 11 tests: zone containment,
  untested/first-test/degraded state transitions, `detect_fixed_zone`/
  `detect_anchored_zone` reusing real POC/VAH/VAL, and the hardcoded
  `INFORMATION_ONLY` guarantee (including on degenerate/single-bar input,
  which must degrade to an empty zone list rather than raise).

## Verification
- `pytest -q` (full suite): 392 passed, 0 failed, 0 regressions.
- Live-confirmed on `cdcx-ai` (XRP/USD): FVP SHADOW ANALYSIS section
  printed correctly on both the confluence path and the RANGE MODE path.
- `cli_equity.py`'s hook is code-identical to `cli.py`'s confluence-path
  hook; not separately live-confirmed against a real Robinhood pull (the
  one live attempt hit SPY's own pre-existing "fewer than 2 tradeable
  timeframes" early-return, which sits upstream of the hook and is
  unrelated to this change) — unit tests + the crypto-path confirmation
  are considered sufficient evidence for Phase 1.

## Not yet built (Phase 2+, per the phased rollout agreed on)
Setup classification (Accumulation/Trend/Rejection), zone origin
detection, the individual FVG/Fib/BOS/AVP/S-R-flip/VWAP confluence
booleans, multi-timeframe (1D/4H/1H) roll-up, and the full sample report
layout from the original spec.

## Contents of this backup
- `fvp-shadow-layer-phase1-tracked.diff` — unified diff of the 3 tracked
  files this session touched (`git diff` scoped to just those paths, from
  the `backtrader-repo` root — apply with `git apply` from that root).
- `src/cdcx-cli/...` — full snapshot of every new/changed file, for
  restoring individually without needing `git apply`.
