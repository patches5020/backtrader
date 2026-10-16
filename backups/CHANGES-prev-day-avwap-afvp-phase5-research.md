# Previous-day AVWAP + AFVP, Phase 5: walk-forward research (2026-10-16) -- commit 0c2652e

Research only: reads history, never places/plans/journals a trade. No protected parameter changed.

## Method (rules frozen at vwap-vp-1, nothing tuned)
- Walk-forward bar by bar; at each bar only bars <= t (test proves truncated history gives identical signals).
- Fires on state changes: VP-01 CONFIRMED, VP-03 CONFIRMED, VP-04 ACCEPTED, VP-05 RETURNED, CANDIDATE,
  baseline B0 = close crossing the anchored VWAP. VP-02 not traded. HTF filter NOT replayed.
- Replay with cdcx's protected model: entry next bar open, 1.5x ATR stop, TP 2.2/2.6/3.2/4.5 R 25% each,
  rules G/H/I (avp_rejection.simulate_outcome; stop wins a same-bar tie). One open trade per setup.
- Costs: 7.5 bps fee + 2 bps slippage per side (fee is an assumption). Split 70% development / 30% OOS.

## Result: every setup net-negative out-of-sample (avg net R per trade)
| Setup | XRP 5m | XRP 15m | XLM 5m | XLM 15m |
|---|---|---|---|---|
| B0 VWAP cross | -0.37 | -0.14 | -0.63 | -0.30 |
| VP-01 | -0.42 | -0.39 | -0.49 | -0.27 |
| VP-04 | -0.60 | -0.19 | -0.54 | -0.12 |
| VP-05 | -0.65 | -0.35 | -0.51 | -0.33 |
| CANDIDATE | -0.52 | -0.27 | -0.52 | -0.35 |
Costs 0.3-0.8 R/trade vs a gross edge of at most ~+0.2 R that did not hold between periods. VP-03 fired 0-7 times.
Recommendation: keep --vwap-vp display only; no Phase 6 shadow alerts on these rules.

## Full reports

```
VWAP-VP RESEARCH (vwap-vp-1) -- XRP/USD 5m, 39999 bars 2026-05-30 -> 2026-10-16
Costs 7.5 bps fee + 2 bps slippage per side | development < 2026-09-05 <= out-of-sample | research only, no trades placed

Setup  Split           Trades   Win%  GrossR  CostR    NetR   TotalR     PF  MaxDD R  MAE R
B0     development        247    29%  -0.032  0.800  -0.832  -205.48   0.33   205.48   1.06
B0     out_of_sample      103    37%   0.276  0.644  -0.367   -37.81   0.65    41.65   1.01
VP-01  development        286    33%   0.131  0.856  -0.725  -207.27   0.41   213.40   1.01
VP-01  out_of_sample      130    32%   0.112  0.532  -0.420   -54.63   0.58    63.10   0.99
VP-03  development          1     0%  -1.000  0.036  -1.036    -1.04   0.00     1.04   1.23
VP-03  out_of_sample        0     0%   0.000  0.000   0.000     0.00      -     0.00   0.00
VP-04  development        272    35%   0.218  0.719  -0.501  -136.24   0.55   155.22   1.00
VP-04  out_of_sample       97    29%  -0.058  0.544  -0.602   -58.43   0.43    59.83   1.14
VP-05  development        354    30%   0.066  0.569  -0.503  -177.98   0.53   180.35   1.05
VP-05  out_of_sample      155    26%  -0.153  0.495  -0.647  -100.32   0.42   108.80   1.21
CAND   development       1148    29%   0.022  0.773  -0.750  -861.12   0.38   864.22   1.02
CAND   out_of_sample      411    33%   0.069  0.585  -0.515  -211.70   0.51   212.20   1.05

6034 signals, 0 data gaps, 697s
```

```
VWAP-VP RESEARCH (vwap-vp-1) -- XRP/USD 15m, 12999 bars 2026-06-03 -> 2026-10-16
Costs 7.5 bps fee + 2 bps slippage per side | development < 2026-09-06 <= out-of-sample | research only, no trades placed

Setup  Split           Trades   Win%  GrossR  CostR    NetR   TotalR     PF  MaxDD R  MAE R
B0     development        138    28%  -0.071  0.432  -0.503   -69.44   0.51    69.44   1.09
B0     out_of_sample       56    38%   0.175  0.312  -0.137    -7.66   0.83    20.97   1.01
VP-01  development        153    26%  -0.144  0.420  -0.564   -86.31   0.46    88.73   1.17
VP-01  out_of_sample       80    29%  -0.095  0.294  -0.389   -31.13   0.58    35.29   1.10
VP-03  development          7    14%  -0.529  0.209  -0.738    -5.16   0.28     6.09   1.18
VP-03  out_of_sample        3    67%   0.253  0.175   0.078     0.23   1.18     1.27   0.81
VP-04  development        143    33%   0.114  0.401  -0.287   -41.09   0.70    50.83   1.00
VP-04  out_of_sample       51    33%   0.102  0.291  -0.189    -9.65   0.78    15.59   1.06
VP-05  development        211    32%   0.056  0.343  -0.288   -60.68   0.68    66.76   1.07
VP-05  out_of_sample       89    29%  -0.072  0.272  -0.345   -30.69   0.61    35.49   1.17
CAND   development        294    33%   0.112  0.393  -0.281   -82.48   0.70    88.61   1.03
CAND   out_of_sample      143    34%   0.061  0.326  -0.265   -37.86   0.70    39.27   1.01

2750 signals, 0 data gaps, 190s
```

```
VWAP-VP RESEARCH (vwap-vp-1) -- XLM/USD 5m, 39999 bars 2026-05-30 -> 2026-10-16
Costs 7.5 bps fee + 2 bps slippage per side | development < 2026-09-05 <= out-of-sample | research only, no trades placed

Setup  Split           Trades   Win%  GrossR  CostR    NetR   TotalR     PF  MaxDD R  MAE R
B0     development        336    32%   0.045  0.644  -0.599  -201.37   0.47   204.70   1.07
B0     out_of_sample      121    28%  -0.012  0.620  -0.632   -76.47   0.44    80.33   1.05
VP-01  development        288    28%  -0.022  0.545  -0.567  -163.22   0.48   167.11   1.10
VP-01  out_of_sample      145    32%   0.084  0.576  -0.491   -71.24   0.54    75.20   1.04
VP-03  development          0     0%   0.000  0.000   0.000     0.00      -     0.00   0.00
VP-03  out_of_sample        1     0%  -1.000  0.140  -1.140    -1.14   0.00     1.14   1.04
VP-04  development        302    33%   0.119  0.653  -0.533  -161.02   0.51   162.79   1.03
VP-04  out_of_sample      125    30%   0.072  0.611  -0.539   -67.41   0.52    70.08   1.09
VP-05  development        344    30%  -0.033  0.551  -0.584  -200.90   0.46   200.90   1.09
VP-05  out_of_sample      139    29%   0.019  0.531  -0.513   -71.25   0.52    74.19   1.09
CAND   development       1416    31%   0.088  0.673  -0.585  -828.66   0.48   841.35   1.06
CAND   out_of_sample      610    32%   0.126  0.645  -0.520  -316.99   0.52   317.38   1.06

7295 signals, 0 data gaps, 778s
```

```
VWAP-VP RESEARCH (vwap-vp-1) -- XLM/USD 15m, 12999 bars 2026-06-03 -> 2026-10-16
Costs 7.5 bps fee + 2 bps slippage per side | development < 2026-09-06 <= out-of-sample | research only, no trades placed

Setup  Split           Trades   Win%  GrossR  CostR    NetR   TotalR     PF  MaxDD R  MAE R
B0     development        168    29%  -0.051  0.320  -0.371   -62.26   0.61    67.30   1.09
B0     out_of_sample       70    31%   0.018  0.313  -0.295   -20.66   0.67    22.39   1.09
VP-01  development        182    31%  -0.034  0.308  -0.342   -62.18   0.62    70.02   1.07
VP-01  out_of_sample       94    30%   0.005  0.276  -0.271   -25.51   0.70    29.50   1.09
VP-03  development          5     0%  -1.000  0.292  -1.292    -6.46   0.00     6.46   1.21
VP-03  out_of_sample        3    33%   0.100  0.145  -0.045    -0.13   0.94     2.20   1.07
VP-04  development        155    32%   0.019  0.314  -0.295   -45.75   0.67    51.04   1.04
VP-04  out_of_sample       56    34%   0.159  0.276  -0.117    -6.53   0.86    14.25   1.01
VP-05  development        203    28%  -0.133  0.292  -0.426   -86.39   0.55    93.31   1.13
VP-05  out_of_sample       81    28%  -0.069  0.258  -0.327   -26.53   0.64    32.58   1.01
CAND   development        405    31%   0.005  0.311  -0.306  -123.94   0.66   127.42   1.06
CAND   out_of_sample      173    27%  -0.034  0.316  -0.350   -60.58   0.64    64.56   1.09

3076 signals, 0 data gaps, 199s
```

## Tests
723 passed (7 new in test_vwap_vp_research.py); handoff validation PASS.
