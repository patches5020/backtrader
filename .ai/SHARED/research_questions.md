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

## RQ5 — Do ADX or RSI add information to VP-04 1H? (PRE-REGISTERED 2026-10-17, before any RQ5 result exists)
Research only. Nothing here changes a live plan, watcher, sizing, permission or protected parameter.
- **Question:** among the VP-04 1H trades of RQ3, do trades that pass filter A or filter B do better after costs
  than the trades that fail it? Two tests only; no other thresholds, lengths or combinations will be tried.
- **Signals and replay (unchanged from RQ3):** `vwap_vp_research.find_signals` on XRP/USD and XLM/USD 1H, setup
  VP-04, `replay()` with the protected model (1.5 x ATR stop, 2.2/2.6/3.2/4.5 R at 25%, rules G/H/I), costs
  7.5 bps fee + 2 bps slippage per side, one open trade at a time. Signal = closed bar t; entry = open of t+1.
- **Indicators, sampled at the signal bar t (closed), from 1H bars up to and including t:** cdcx's own Wilder
  `calculate_adx` and `calculate_rsi`, length 17 (cdcx default). No new indicator code.
  - **A (ADX):** ADX[t] > ADX[t-3] (rising over 3 bars) AND the trade's DI leads at t (long: +DI > -DI;
    short: -DI > +DI). Ties count as fail.
  - **B (RSI):** long: RSI[t] > 50; short: RSI[t] < 50. Ties count as fail.
- **Data:** the 1H series fetched once from Crypto.com is saved with its SHA-256; the run reads only that file.
  Test period = signals 2025-06-01 -> 2026-05-30 (FRESH). After 2026-05-30 (SEEN) is reported separately and
  doesn't count.
- **Primary test (per filter):** split the baseline trades into PASS and FAIL (complement). Pooled XRP + XLM, FRESH:
  difference of mean net R (PASS - FAIL) with a **97.5%** bootstrap interval (two tests -> alpha 0.05/2), 10,000
  resamples within each group, seed 20261017.
- **Secondary:** the filtered strategy re-replayed on its own signals vs the baseline: trades, net R, total R,
  max drawdown, 97.5% CI of mean net R. Also per symbol and the SEEN period, reference only.
- **Reported for baseline, PASS and FAIL:** trades, win rate, mean gross/cost/net R, total net R, PF, max drawdown,
  bootstrap interval of the mean.
- **Decision rule:** a filter "adds information" only if the PRIMARY 97.5% interval of PASS - FAIL lies entirely
  above 0. It is worth proposing as an advisory `--vwap-vp` line only if, in addition, the re-replayed filtered
  strategy's 97.5% interval of mean net R lies above 0. Anything else = inconclusive / no; no follow-up threshold
  search. Known limit: ~150-250 trades per subset can detect only a large difference.
- **RESULT (run once, 2026-10-17 13:3xZ, after the pre-registration above; frozen data XRP sha256 f0bf4475...,
  XLM 592333ba...; `cdcx/backtest/vwap_vp_rq5.py`):** baseline reproduces RQ3 (463 trades, +0.034 R).
  - **A (ADX rising + DI):** PASS 277 trades +0.078 R vs FAIL 186 trades -0.031 R; PASS - FAIL +0.11 R,
    97.5% CI [-0.241, +0.453] -> **no evidence** (interval includes 0). XRP points positive (+0.26 R) and
    XLM doesn't (-0.02 R). The re-replayed filtered strategy: 312 trades, +0.079 R, CI [-0.126, +0.290].
    Its lower max drawdown (12.6 vs 33.7 R) comes mostly from taking fewer trades.
  - **B (RSI side of 50):** **no evidence**, and the filter is close to a tautology: 452 of 463 VP-04 trades
    already pass (an accepted value-area break almost always has RSI on that side), leaving only 11 FAIL trades.
    In the SEEN period, the "significant" B result (3 FAIL trades, all losers) is an artifact of a tiny sample.
  - **Interpretation:** "no evidence" means inconclusive, not proof that ADX or RSI has no predictive value; the
    intervals are too wide to rule out a small effect either way.
  - **Decision (pre-registered rule):** neither filter is proposed. No threshold or length search follows.
    `--vwap-vp` stays display only. The A difference on XRP could only be reopened as a new pre-registered
    question on data after 2026-10-17.
