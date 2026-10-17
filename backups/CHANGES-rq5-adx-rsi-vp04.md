# RQ5: ADX / RSI filters on VP-04 1H (2026-10-17) -- commit 6376736

Research only. Files: cdcx-cli/cdcx/backtest/vwap_vp_rq5.py, cdcx-cli/tests/test_vwap_vp_rq5.py,
.ai/SHARED/research_questions.md (RQ5 pre-registration + result). No live plan, watcher, trade ledger, config,
sizing, permission, execution setting or protected parameter changed.

## Pre-registration
Written 2026-10-17 13:19:54Z (file sha256 7cad95073198eaaf...) before any RQ5 run. Two filters, sampled at the
signal bar t: A = ADX(17)[t] > ADX[t-3] and the trade's DI leads; B = RSI(17)[t] on the trade's side of 50.
Primary: baseline trades split PASS/FAIL, pooled XRP+XLM, 2025-06-01 -> 2026-05-30, 97.5% bootstrap CI of
PASS - FAIL (10,000 resamples, seed 20261017). Replay and costs unchanged from RQ3.

## Result (run once on frozen data)
| | Trades | Net R | 97.5% CI |
|---|---|---|---|
| Baseline | 463 | +0.034 | [-0.130, +0.203] |
| A pass / fail | 277 / 186 | +0.078 / -0.031 | diff +0.11 [-0.241, +0.453] |
| B pass / fail | 452 / 11 | +0.023 / +0.490 | diff -0.47 [-1.698, +0.742] |
Decision: neither filter proposed; no threshold search. "No evidence" = inconclusive, not proof of no value.
ADX lift is XRP-only (+0.26 R) and absent on XLM. RSI passes 452/463 trades, so it barely discriminates.

## Verification
- Full suite at commit 6376736: 732 passed.
- Frozen data: rq5_xrp_1h.json sha256 f0bf4475698ad94658679f16514fabfb30bc76c1794d613f7cd9d3514d5db37b,
  rq5_xlm_1h.json sha256 592333ba9bbae1aa929a3ef12f61ab855943c72403ef764728c58c1f6140b30d (match the report).
- Reproduce: `python -m cdcx.backtest.vwap_vp_rq5 --data trading/research/vwap_vp/rq5` from cdcx-cli/.
