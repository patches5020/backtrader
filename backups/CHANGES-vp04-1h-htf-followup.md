# VP-04 1H + cdcx HTF filter follow-up (2026-10-16) -- commit a6486cd

Research only. No protected parameter, gate, report or execution change.

## Pre-registered hypothesis (written before the run, chosen after Phase 5 -> judged on unseen data)
VP-04 (prior-day value-area breakout ACCEPTED) on 1H bars, taken only when cdcx's own 2-of-4 confluence on
1H/4H/1D/1W (transitional excluded, the --execute filter) agrees. Reference: unfiltered VP-04 1H.
Test period 2025-06-01 -> 2026-05-30 (FRESH); 2026-05-30 -> now reported separately (SEEN).
HTF replay: last 200 CLOSED bars per timeframe at the signal bar, engine.analyze_ohlcv as cdcx-ai runs it.
Trade model and costs identical to Phase 5.

## Result
| Variant | Period | XRP trades | XRP net R | XLM trades | XLM net R |
|---|---|---|---|---|---|
| VP-04 1H | fresh | 224 | +0.02 (PF 1.03) | 239 | +0.05 (PF 1.07) |
| VP-04 1H | seen | 89 | -0.02 | 89 | +0.10 |
| VP-04 1H + HTF | fresh | 10 | +0.32 | 5 | -0.09 |
| VP-04 1H + HTF | seen | 10 | +0.74 | 4 | -1.09 |
- 1H cuts costs to ~0.15 R; gross edge ~+0.17-0.23 R, consistent; net ~break-even. Not tradable.
- HTF agreed on ~5% of signals (XRP 22/435, XLM 9/472) -> sample far too small.
- XLM 1W history starts 2022-02, so 200 weekly bars exist only from ~2025-12: 174 XLM signals had HTF unknown.
Recommendation: keep --vwap-vp display only; no alerts/trades.

## Full reports

```
VP-04 1H + cdcx HTF filter -- XRP/USD | 435 VP-04 signals since 2025-06-01, 22 with HTF agreeing | research only
FRESH = 2025-06-01 -> 2026-05-30 (the test) | SEEN = 2026-05-30 -> now (reference only)

Variant   Period  Trades   Win%  GrossR  CostR    NetR   TotalR     PF  MaxDD R
VP04      fresh      224    35%   0.170  0.151   0.019     4.20   1.03    19.94
VP04      seen        89    35%   0.153  0.170  -0.017    -1.56   0.98    14.81
VP04+HTF  fresh       10    40%   0.485  0.161   0.324     3.24   1.46     3.77
VP04+HTF  seen        10    50%   0.885  0.149   0.736     7.36   2.30     2.33

history starts {'1h': '2025-05-20', '4h': '2025-04-15', '1d': '2024-08-26', '1w': '2021-07-26'}; 150s
```

```
VP-04 1H + cdcx HTF filter -- XLM/USD | 472 VP-04 signals since 2025-06-01, 9 with HTF agreeing | research only
FRESH = 2025-06-01 -> 2026-05-30 (the test) | SEEN = 2026-05-30 -> now (reference only)

Variant   Period  Trades   Win%  GrossR  CostR    NetR   TotalR     PF  MaxDD R
VP04      fresh      239    35%   0.183  0.135   0.049    11.65   1.07    28.76
VP04      seen        89    36%   0.232  0.131   0.102     9.05   1.14    11.19
VP04+HTF  fresh        5    40%   0.106  0.192  -0.086    -0.43   0.88     3.05
VP04+HTF  seen         4     0%  -1.000  0.093  -1.093    -4.37   0.00     4.37

history starts {'1h': '2025-05-20', '4h': '2025-04-15', '1d': '2024-08-26', '1w': '2022-02-07'}; 150s
```

## Tests
726 passed (3 new in test_vwap_vp_htf_followup.py); handoff validation PASS.
