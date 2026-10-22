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
- **Step 2, TradingView parity** (same day). The TradingView Fixed Range VP (400 rows, 70%) was read through the MCP for all 20 sessions per symbol,
  using temporary drawings that were created, read and removed. The user's drawings were verified identical afterwards: XRP 8, XLM 6, studies 3, chart back on
  XRPUSD 15m. XRP 2026-10-15 matches RQ4 exactly. `vp_resolution_rq10.py` gains `tv_parity` / `--tv`, plus 1 test; 901 passed.
  - **Median worst-level error vs TV:**
    - 1H@24 (current): 0.30 ATR XRP / 0.95 ATR XLM.
    - 5m@400: 0.09 / 0.53.
    - 5m@100: 0.13 / 0.52.
  - **Within 0.10 ATR:** about half the sessions at 5m; the rest are two-peak days where the POC node flips.
  - **Value-area method:** the TV-style method doesn't help.
  - **Recommendation for the user to decide:** 5m source bars as a new ruleset version (vwap-vp-2), never edited into the frozen vwap-vp-1.
- **Step 4, downstream state changes** (same day). `vp_resolution_rq10.py` gains `downstream` / `--step4`, plus 1 test; 902 passed.
  - Using 5m levels changes VP-01/VP-04/VP-06/VP-04P states on 11–25% of 1H bars and the DECISION on 2–3% (XRP) / 10–11% (XLM).
  - VP-03/VP-05 are unaffected.
  - A vwap-vp-2 would be a different strategy and would need its own outcome RQ. RQ10 is complete.
- **Follow-up: data check + 1m parity** (same day).
  - TradingView's 15m candles are identical to the Crypto.com API's (XRP 1920/1920, XLM 1918/1918), so the data is not the cause.
  - 1m@400 profiles match TradingView's FRVP to 0.018 / 0.044 ATR median (XRP / XLM), with the POC within 0.10 ATR on 16/20 and 18/20 days.
  - TradingView uses 1m intrabar data. A 1m "vwap-vp-3" is possible as a new file (vwap-vp-2 is frozen in RQ11); that is the user's decision.
  - The chart was restored (XRPUSD 15m, 3 studies, the same 8 drawings).
