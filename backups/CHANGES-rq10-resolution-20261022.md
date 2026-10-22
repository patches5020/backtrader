# RQ10 profile resolution x source bars — steps 1 + 3 (calculation study) — 2026-10-22

Approved by the user ("Yes to all"). A calculation study, not a signal test. DEFAULT_BUCKETS stays 24, because RQ6–RQ9 are frozen on it.

- `cdcx/backtest/vp_resolution_rq10.py` (new). For the last 20 completed UTC sessions per symbol it computes POC/VAH/VAL at rows {24, 100, 400}
  x source bars {1h, 15m, 5m}, using `build_volume_profile` / `calculate_poc_vah_val` unchanged. It reports:
  - the error vs 5m@400 (an INTERNAL PROXY, not TradingView);
  - stability when the window shifts by one bar, and when rows change by +/-10%;
  - the difference from a TradingView-style (two rows at a time) value area.
- `tests/test_vp_resolution_rq10.py`: 5 tests (synthetic). They cover a known profile answer, the documented lowest-bucket tie-break, the
  TV-style value area holding >= 70%, failing closed on a missing bar, and every cell running. Full suite 900 passed.
- Data was fetched once into `cdcx-cli/trading/research/rq10/` (gitignored, so it is included in this zip); the SHA-256s are in `rq10_result.json`.
- Result (median worst level, ATR units):
  - 1H@24 err 0.32 / 0.40 (XRP / XLM); rows +/-10% moves it 0.19 / 0.29.
  - 1H@400 isn't better (0.21 / 0.43).
  - 5m@100 err 0.03 / 0.05.
  - Leading candidate: 5m @ 100–400 rows.
  - Not decided: step 2 (TradingView parity) is needed.
