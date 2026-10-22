# RQ12 draft — VP-04 on vwap-vp-3 (1m, TradingView-matched) levels — 2026-10-22

The user said "Yes to all" (draft the outcome test for vwap-vp-3).

- `cdcx/backtest/vwap_vp_rq12.py` (new): VP-04 / VP-01 on vwap-vp-3 levels vs vwap-vp-1.
  - Same design as RQ11, with 1m bars instead of 5m.
  - Walk-forward, protected trade model and costs, seed 20261026, 97.5% CIs.
  - A test proves it reproduces vwap-vp-1's signals exactly when the levels aren't swapped.
  - The frozen RQ11 driver is not imported for its signal logic and is unchanged.
- RQ12 DRAFT in `research_questions.md`, appended after RQ11. It is NOT frozen; it awaits the user's approval of section 1.
  - On freeze, `prev_day_v3.py` is frozen with it.
  - Proposed confirmatory period: S = first UTC day ≥ 24 h after the freeze; E = S + 182 days.
- Checked: Crypto.com serves 1m candles at least 400 days back.
- Tests: `test_vwap_vp_rq12.py` (5). Full suite 923 passed.
- Protected params unchanged. RQ6–RQ11 frozen files and texts untouched.
