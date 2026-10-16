# RQ3 + RQ4: VP-04 result and AVWAP/AFVP parity with TradingView (2026-10-16) -- commit 527986e

Docs only. No code, protected parameter, gate, watcher or execution change. TradingView chart left as found
(a test Anchored VWAP was added and removed; the user's drawings and paper short untouched).

## RQ3 -- VP-04 1H after costs
Pooled XRP + XLM, test period 2025-06-01 -> 2026-05-30: +0.034 R/trade, bootstrap 95% CI [-0.115, +0.186],
P(>0) 67%, n = 463. HTF-filtered n = 10 / 5, no information. Not tradable; --vwap-vp stays display only.

## RQ4 -- parity on XRP/USD 1H, anchor 2026-10-15 00:00 UTC, 2026-10-16 22:45Z
| | TradingView | cdcx |
|---|---|---|
| AVWAP (ohlc4, 1H bars) | 1.316547 | 1.316549 |
| +-1 sigma | 1.301170 / 1.331924 | 1.301172 / 1.331926 |
| FRVP anchor->now POC | 1.3071 | 1.3070 (1H, 24 rows) / 1.3061 (5m, 400 rows) |
| VAH | 1.3310 | 1.3302 / 1.3318 |
| VAL | 1.2888 | 1.2896 / 1.2912 |

- AVWAP matches. 5m bars give a slightly different VWAP (1.316779) -- compare on the chart's timeframe.
- The chart's FRVP extends to the right, so it is the anchored profile, not cdcx's frozen previous-day profile
  (cdcx 5m prev-day only: POC 1.3077 / VAH 1.3263 / VAL 1.2944). Profile agreement ~one 24-row bucket.
- Open: a non-extended FRVP over 2026-10-15 00:00 -> 2026-10-16 00:00 UTC would check the frozen profile.

Script: `cdcx-cli/trading/research/vwap_vp/tv_parity_20261016.py` (run from cdcx-cli/).
