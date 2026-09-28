# Stage 2 Setup Backtest (AVP Bullish Rejection + peers) — Change Summary

Date: 2026-09-28
Commit: 600bb1d (pushed to patches5020/backtrader master)
Repo touched: `cdcx-cli/` only. Research only; no gate, risk or execution change.

## Harness (cdcx/backtest/setup_backtest.py)
- Strategies (long, paper): avp_confirm (hold-close entry), avp_retest (retest entry),
  poc_bounce, va_reversal (vp_setup, up), vpbos_bull, baseline (long every 24 bars = control).
- Same for all: entry on first appearance only; one open trade at a time (rule C);
  protected 1.5x ATR stop; TP 2.2/2.6/3.2/4.5R, 25% each; trade_manager G/H/I exits;
  stop assumed first if a bar touches both; costs 7.5 bps fee + 5 bps slippage per
  side (cdcx.backtest.engine defaults) charged in R.
- No lookahead: classifiers see bars [0..e] only (tested; test confirmed non-vacuous).
- Frozen data: trading/backtest_data/XRPUSD_1h_8760.json (sha256 e19bc0948324...),
  XRPUSD_4h_4380.json (sha256 26577f11eda1...). Not in git (trading/ is ignored);
  a copy of the result report is below.
- Splits (chronological): development 60% / validation 20% / out-of-sample 20%.
  OOS LOCKED: not computed, trades not stored; --include-oos reserved for stage 3.

## Result summary (net R/trade, dev+validation, +/- standard error)
| setup | 1H (n) | 4H (n) |
|---|---|---|
| avp_confirm | -0.26 +/- 0.12 (159) | -0.11 +/- 0.19 (67) |
| avp_retest  | -0.36 +/- 0.15 (91)  | +0.18 +/- 0.24 (50) |
| poc_bounce  | -0.53 +/- 0.20 (42)  | -0.16 +/- 0.37 (19) |
| va_reversal | -0.26 +/- 0.14 (118) | +0.10 +/- 0.23 (53) |
| vpbos_bull  | -0.26 +/- 0.16 (99)  | +0.14 +/- 0.23 (52) |
| baseline    | -0.30 +/- 0.10 (215) | +0.05 +/- 0.16 (106) |

- No setup distinguishable from the baseline (all within ~1 SE).
- 1H: costs ~0.19-0.21R/trade; everything negative after costs.
- AVP hold-close (primary definition) underperforms baseline on 4H.
- 4H avp_retest only positive in both splits (+0.13 dev, +0.31 val) — noise level.
- Entry overlap across setups only 1-12% (AVP variants overlap by construction):
  labels are distinct; none shows an edge on this data.
- Split instability (e.g. 1H va_reversal best in dev, worst in validation).

## Recommendation / next
Do not open the OOS split yet. Re-run the SAME frozen definitions on more data
(BTC, ETH, longer XRP) for samples in the hundreds. If 4H avp_retest still holds,
pre-register it as the single stage-3 hypothesis; otherwise park AVP as report-only.

## Tests
11 in tests/test_setup_backtest.py. Full suite 517 passed; handoff validator PASS.

---
## Full result report (setup_backtest_XRPUSD_20260928_0141.txt)
```
SETUP BACKTEST -- XRP/USD (stage 2, paper research; costs 0.075% fee + 0.05% slippage per side)

=== 1H  8760 bars  2025-09-28 -> 2026-09-28  data sha256 e19bc0948324 ===
  development    2025-10-03 -> 2026-05-07
  validation     2026-05-07 -> 2026-07-18
  out_of_sample  2026-07-18 -> 2026-09-28
  -- development --
  strategy        n open   win%   exp R  gross R     PF  total R  maxDD R L-strk  cost R
  avp_confirm   123    0  31.7%  -0.252   -0.058   0.69   -31.02    41.19      9   0.194
  avp_retest     65    0  27.7%  -0.306   -0.112   0.64   -19.89    29.02      9   0.194
  poc_bounce     35    0  25.7%  -0.452   -0.240   0.50   -15.83    22.47     12   0.213
  va_reversal    82    0  31.7%  -0.132   +0.036   0.83   -10.83    28.79     10   0.168
  vpbos_bull     75    0  24.0%  -0.357   -0.161   0.61   -26.74    32.34     12   0.195
  baseline      158    0  27.8%  -0.291   -0.096   0.66   -45.95    53.28     14   0.194
  -- validation --
  strategy        n open   win%   exp R  gross R     PF  total R  maxDD R L-strk  cost R
  avp_confirm    36    0  30.6%  -0.276   -0.045   0.68    -9.93    15.02      7   0.231
  avp_retest     26    0  26.9%  -0.510   -0.262   0.44   -13.25    18.41      7   0.248
  poc_bounce      7    0  14.3%  -0.937   -0.731   0.10    -6.56     6.56      5   0.206
  va_reversal    36    0  22.2%  -0.557   -0.352   0.40   -20.06    26.46      9   0.205
  vpbos_bull     24    0  37.5%  +0.026   +0.246   1.03    +0.62     6.36      5   0.220
  baseline       57    0  28.1%  -0.321   -0.097   0.63   -18.27    22.39      7   0.224
  -- out_of_sample --
  strategy        n open   win%   exp R  gross R     PF  total R  maxDD R L-strk  cost R
  avp_confirm  LOCKED (out-of-sample is reserved for stage 3)
  avp_retest   LOCKED (out-of-sample is reserved for stage 3)
  poc_bounce   LOCKED (out-of-sample is reserved for stage 3)
  va_reversal  LOCKED (out-of-sample is reserved for stage 3)
  vpbos_bull   LOCKED (out-of-sample is reserved for stage 3)
  baseline     LOCKED (out-of-sample is reserved for stage 3)

=== 4H  4380 bars  2024-09-28 -> 2026-09-28  data sha256 26577f11eda1 ===
  development    2024-10-18 -> 2025-12-18
  validation     2025-12-18 -> 2026-05-09
  out_of_sample  2026-05-09 -> 2026-09-28
  -- development --
  strategy        n open   win%   exp R  gross R     PF  total R  maxDD R L-strk  cost R
  avp_confirm    52    0  30.8%  +0.000   +0.072   1.00    +0.01     7.16      6   0.072
  avp_retest     37    0  37.8%  +0.129   +0.203   1.19    +4.78     7.35      7   0.074
  poc_bounce     13    0  30.8%  +0.035   +0.106   1.05    +0.46     3.21      3   0.071
  va_reversal    40    0  32.5%  +0.027   +0.101   1.04    +1.09     6.35      6   0.074
  vpbos_bull     40    0  35.0%  +0.055   +0.125   1.08    +2.20     8.71      8   0.070
  baseline       81    0  32.1%  +0.062   +0.134   1.08    +4.99    13.39      8   0.073
  -- validation --
  strategy        n open   win%   exp R  gross R     PF  total R  maxDD R L-strk  cost R
  avp_confirm    15    0  20.0%  -0.492   -0.388   0.44    -7.39     9.82      6   0.104
  avp_retest     13    0  38.5%  +0.309   +0.423   1.46    +4.02     3.55      3   0.114
  poc_bounce      6    0  16.7%  -0.567   -0.450   0.39    -3.40     5.58      5   0.117
  va_reversal    13    0  38.5%  +0.318   +0.423   1.47    +4.14     3.38      3   0.105
  vpbos_bull     12    0  41.7%  +0.406   +0.502   1.64    +4.87     3.19      3   0.096
  baseline       25    0  36.0%  +0.009   +0.112   1.01    +0.22     6.24      4   0.103
  -- out_of_sample --
  strategy        n open   win%   exp R  gross R     PF  total R  maxDD R L-strk  cost R
  avp_confirm  LOCKED (out-of-sample is reserved for stage 3)
  avp_retest   LOCKED (out-of-sample is reserved for stage 3)
  poc_bounce   LOCKED (out-of-sample is reserved for stage 3)
  va_reversal  LOCKED (out-of-sample is reserved for stage 3)
  vpbos_bull   LOCKED (out-of-sample is reserved for stage 3)
  baseline     LOCKED (out-of-sample is reserved for stage 3)

R = multiples of the 1.5x ATR stop distance, after costs unless labelled gross. Small samples (n < 30) are not evidence either way.```
