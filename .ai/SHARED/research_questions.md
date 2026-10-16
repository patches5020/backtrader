# Open research questions (shared by ChatGPT and Claude Code)

Ideas to test OFFLINE. Nothing here changes a live plan, watcher or protected parameter; adopting any of them is
the user's decision after the test.

## RQ1 — VP plan R10 window vs. the breakdown (raised 2026-10-15)
- **Observed:** XRP bear VP plan reached 9/12 at 2026-10-15 06:02Z (R6 breakdown + R11 retest HELD) but R10 failed.
  R10 had passed from 2026-10-14 15:00Z (1H POC 1.3652 rejected at 13:00Z) and aged out of its 12-bar window around
  03:00Z, before the breakdown.
- **Cause:** temporal alignment, not a logical contradiction. R10 (`bear_poc_rejection`, `xrp_vp_plan_watch.py`) only
  counts a rejection in the last 12 closed bars; R6/R11 depend on a later breakdown + retest about 0.05 below the POC.
  Note: the POC is rolling (last 200 bars), so it can migrate toward price.
- **Test:** on the same history, compare (a) the current rolling 12-bar rule with (b) an R10 window started or
  refreshed at a defined breakdown event. Measure: how often each reaches 12/12, time to confirmation, how often a
  valid rejection goes stale, and out-of-sample trade outcomes after fees and slippage. More completed setups alone is
  not evidence that (b) is better. R10 must keep requiring the actual price action, not POC proximity.

## RQ2 — ATR stop vs. structural stop on retest alerts (raised 2026-10-15)
- **Observed:** 2026-10-15 00:45Z bounce-zone alert, entry 1.3266: 2x ATR stop 1.3316 was hit by a 1.3323 high that
  never exceeded the 1.3328 rejection high; the advisory structural stop (rejection high + 0.25 ATR = 1.3334) survived.
  The 00:00Z alert (entry 1.3301) filled all four TPs with the ATR stop. Two cases only.
- **Data being collected:** alerts now print the structural stop and whether the ATR stop sits inside the tested zone
  (commit b7996b0).
- **Test:** across many alerts, compare outcomes with the ATR stop vs. the structural stop at equal dollar risk
  (the wider stop means a smaller position), after fees and slippage. The 2x ATR rule stays until then.

## RQ3 — VP-04 1H (prior-day value-area breakout) after costs (raised 2026-10-16)
- **Tested:** `cdcx/backtest/vwap_vp_htf_followup.py` (commit a6486cd). Walk-forward, protected trade model, 7.5 + 2 bps
  per side; test period 2025-06-01 -> 2026-05-30.
- **Result:** unfiltered, pooled XRP + XLM: +0.034 R/trade, bootstrap 95% CI [-0.115, +0.186], P(>0) 67%, n = 463
  (XRP CI [-0.194, +0.234], XLM CI [-0.159, +0.261]). With cdcx's 2-of-4 HTF filter: n = 10 (XRP) / 5 (XLM),
  CIs ~2-3 R wide -> no information. All 5m/15m setups (phase 5) were net-negative out of sample.
- **Status:** not tradable. `--vwap-vp` stays display only. Ruling zero out at this edge would take roughly 10,000+
  trades; reopen only with a new, pre-registered hypothesis tested on unseen data.

## RQ4 — Previous-day AVWAP / AFVP parity with TradingView (checked 2026-10-16 22:45Z, XRP/USD 1H)
- **AVWAP** (anchor 2026-10-15 00:00 UTC, ohlc4, Standard Deviation bands, forming bar included like TV):
  TV 1.316547 / +-1 sigma 1.301170-1.331924; cdcx (1H bars) 1.316549 / 1.301172-1.331926. Match (<= 0.000002).
  On 5m bars cdcx gives 1.316779 / sigma 0.016020: the bar size changes the result, so compare on the chart's timeframe.
- **AFVP**: the chart's Fixed Range VP is anchored 2026-10-15 00:00 UTC and extends to now (400 rows, 70% VA), so it
  is the anchored profile, not cdcx's frozen previous-day profile. On that same window:
  TV POC 1.3071 / VAH 1.3310 / VAL 1.2888; cdcx 1H 24 rows 1.3070 / 1.3302 / 1.2896; 5m 400 rows 1.3061 / 1.3318 /
  1.2912. POC within 0.001, VAH/VAL within ~0.001-0.003 (about one 24-row bucket). cdcx 1H at 400 rows is unstable
  (POC 1.3365): 1H bars are too coarse for 400 rows. TV builds the profile from finer intrabar data.
- **Frozen previous-day profile (closed 2026-10-16 23:05Z):** TV Fixed Range VP 2026-10-15 00:00 -> 23:00 UTC bar,
  not extended, 400 rows, 70% VA: POC 1.3079 / VAH 1.3252 / VAL 1.2924. cdcx 1H (24 rows): 1.30765 / 1.32626 /
  1.2917; cdcx 5m: 1.3077 / 1.3263 / 1.2944. All within one 24-row bucket (~0.0027). Accepted; no code change.
