# XRP Multi-Timeframe Baseline Regression Test — Change Summary

Date: 2026-09-26
Commit: dedee18 (pushed to patches5020/backtrader master)
Repo touched: `cdcx-cli/tests/` only — no engine/CLI code changed.

## Added
- `tests/fixtures/xrp_usd_mtf_baseline.json` — real Crypto.com XRP/USD
  OHLCV, 200 bars each for 1W/1D/4H/1H, captured ~7:50 PM CDT.
- `tests/fixtures/capture_mtf_snapshot.py` — captures a new snapshot:
  `python tests/fixtures/capture_mtf_snapshot.py XRP/USD tests/fixtures/<name>.json`
- `tests/test_baseline_xrp_mtf.py` — 5 offline tests replaying the snapshot:
  1. Regime: 1W trending; 1D/4H/1H transitional
  2. Summary columns (Market/EMA/FVG/Signal) per timeframe
  3. NO TRADE = insufficient confirmation, not bearish
  4. Risk model: 1.5x ATR stop, 1:2.2 R:R
  5. `--execute`: confluence 1/4 refuses, no paper trade, rejection journaled

## Why
Baseline for the next cdcx-ai cycle (Volume Profile / Trader Dale ideas):
new features must layer on top of the regime/confluence gates, not
replace them, and must not touch entry/SL/TP/R:R.

## Verified
- Full suite: 397 passed.
- Mutation checks: confluence minimum 2→1, XRP ATR 1.5x→2.0x, and
  TP ratios changed each made the baseline tests fail.
