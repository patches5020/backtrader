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

## RQ6 — Are vwap-watch-1 closed-bar warnings informative? (DRAFT 2026-10-18, rev 3 — NOT FROZEN, not run)
Research only. Nothing here changes the watcher, a live plan, sizing, permission or protected parameter, and no
result authorizes execution.

**0. Freeze.** Binding only when the user freezes it. Preconditions: the watcher is committed, and the analysis
script `cdcx/backtest/vwap_watch_rq6.py` (implementing sections 3-10 exactly) is written, unit-tested on
synthetic data only, and committed. The freeze line then records: date/time (UTC), commit hash, and SHA-256 of
`vwap_watch.py`, of `vwap_watch_rq6.py`, and of this RQ6 text from its heading to the end of section 10. After
the freeze nothing in this block is edited; a correction is a new question with a new period.
- `FROZEN: <empty = draft>`

**1. What is tested.** `cdcx/volume_profile/vwap_watch.py`, WATCH_VERSION `vwap-watch-1`, ruleset `vwap-vp-1`,
through `replay()` only (the same `evaluate` -> `step` path as the live run; HTF 2-of-4 from CLOSED bars of
1H/4H/1D/1W via `htf_from_history`). A test of the implemented warning policy, closed-bar events only; intrabar
warnings would be a separate versioned experiment. The watcher's closed-bar HTF and `--execute`'s forming-bar HTF
differ by design; neither changes for or during RQ6, and a disagreement between them is not a watcher defect.

**2. Data and periods.** XRP/USD and XLM/USD; events on 1H; 4H/1D/1W only for the HTF read. Source: Crypto.com
public candles as returned by cdcx's `CryptoComExchange.fetch_ohlcv` (bar open time UTC, OHLC, volume). Each
series is fetched once, saved, identified by SHA-256; the run reads only those files.
- **Confirmatory (prospective), the only period that can give a verdict:** S = 00:00Z of the first UTC day that
  begins at least 24 h after the FROZEN timestamp; E = S + 56 days. Counted events: bar open in [S, E).
  Fetched once at or after E + 24 h: 1H from S - 60 days to E + 1 day; 4H/1D/1W from S - 400 days to E + 1 day.
  The live watcher is not scheduled for this.
- **Exploratory (historical) 2025-06-01 00:00Z -> 2026-05-31 00:00Z:** already used for VP-04 outcomes in RQ3/RQ5.
  Same procedure, reported as descriptive/debugging evidence only, never a verdict.
- 2026-10-01 -> S never counts.
- **Warm-up:** each replay starts at S - 7 days. The first valid bar is the watcher's BASELINE (pre-existing
  conditions, not counted).

**3. Eligibility.** Bar t is eligible if the watcher's snapshot at t is VALID and bars t+1..t+12 all exist with no
timestamp gap (each step exactly 3600 s). Events at non-eligible bars are dropped and the same bars are dropped from
the comparator. Dropped counts are reported.

**4. Outcome (identical for events and comparator).**
- C_t = close of bar t.
- A_t = cdcx `atr_ema_variant1.calculate_atr(highs, lows, closes, length=11)` (11 = cdcx `ATR_LENGTH`) on the frozen
  1H series from its first bar: TR_0 = H_0 - L_0; TR_i = max(H_i - L_i, |H_i - C_(i-1)|, |L_i - C_(i-1)|);
  ATR_10 = (TR_0 + ... + TR_10) / 11 (the first ATR value; ATR before index 10 is undefined);
  ATR_i = (ATR_(i-1) x 10 + TR_i) / 11 for i >= 11 (Wilder / Pine `ta.rma`). Value at index t (bars <= t only;
  the 60-day lead-in makes the seed irrelevant).
- U = C_t + A_t, D = C_t - A_t. For k = 1..12 in order with bar t+k's high H and low L: H >= U and L <= D ->
  AMBIGUOUS, stop; H >= U -> UP, stop; L <= D -> DOWN, stop. No touch in 12 bars -> NONE.
- favourable for d = UP if d bullish, DOWN if bearish; adverse = the other.
- AMBIGUOUS and NONE are never excluded: they stay in every denominator (events and comparator) as non-hits, and
  their counts and rates are reported per family, so a family cannot look better by dropping hard cases.

**5. Hits per family.**
- entry: hit = favourable for d. Primary event: ENTRY_SETUP. Secondary: ENTRY_WATCH, ENTRY_CONFIRMATION_CANDIDATE.
- retest: RETEST_HOLD hit = favourable for d; RETEST_FAILURE hit = adverse for d; pooled for the primary test.
  A test of the implemented retest policy (VP-03 at most once per anchor per state), not a count of all
  pullbacks or retests.
- deterioration: SETUP_DETERIORATION, AVWAP_LOST, STRUCTURAL_INVALIDATION; hit = adverse for d; pooled.
- Counted only, not tested: WATCH_CLEARED, EXPIRED, DATA_*, BASELINE; catch-up records cannot occur in replay.
- Lead time (descriptive, no test): bars from an episode's first ENTRY_WATCH to its ENTRY_SETUP and
  ENTRY_CONFIRMATION_CANDIDATE (same symbol, direction, anchor); median and IQR.

**6. De-duplication.** Primary: the first event of each event type per (symbol, direction, UTC day of its bar).
Secondary: all events.

**7. Comparator and statistic.** For family f, symbol s, direction d: b(s,d,f) = share of all eligible bars of the
period (in s) whose outcome is a hit under f's rule for direction d. With E_f the primary events of f:
Delta_f = (1/|E_f|) x sum over e in E_f of (hit_e - b(s_e, d_e, f)).
In the pooled retest family each event uses its own type's rule (RETEST_HOLD favourable, RETEST_FAILURE
adverse), for its hit and for its b.

**8. Inference (exact procedure).** Blocks = (symbol, UTC day) pairs of the period; each eligible bar and each
event belongs to the block of its own bar t. N = 10,000 resamples with `random.Random(20261018)`, one generator
for the whole run, families processed in the order entry, retest, deterioration. Each resample: draw B blocks
with replacement (`rng.choices(blocks, k=B)`, B = number of blocks); take, with multiplicity, all eligible bars
and all primary events of the drawn blocks; recompute every b from those bars and Delta*_f from those events.
Event and comparator bars come from the same drawn blocks (paired), so dependence within a block is kept.
A resample with no events of f leaves Delta*_f undefined; if more than 100 of 10,000 are undefined, f is
"insufficient sample". Interval: sort the defined Delta* values (n of them); lower = value at index
int(n x 0.05/6), upper = value at index int(n x (1 - 0.05/6)) - 1 (Bonferroni: 5% family-wise over 3 tests,
same indexing convention as RQ5's `bootstrap_diff_ci`). Sensitivity (reported, not decisive): the same with
2-day blocks (pairs of UTC days counted from S), because 12-bar outcomes can cross midnight; it is a separate
run with its own `random.Random(20261018)`, so it never shifts the primary draws.
- **Minimum sample:** a primary test runs only if f has >= 30 primary events in >= 10 distinct blocks; otherwise
  "insufficient sample" (descriptive only).

**9. Decision rule (confirmatory period only).** f is "informative" only if lower > 0. Anything else = inconclusive /
no. After any result is seen: no change to horizon (12), barrier (1.0 x ATR(11)), state rules, de-duplication,
comparator or procedure; a change is a new version and a new question on new data. "Informative" adds no weight or
alert by itself -- that needs a separate user-approved proposal. No interim looks: the confirmatory data is
fetched and analysed once, after E + 24 h.

**10. Reported.** Per family and event type: counts (raw, primary, dropped), UP/DOWN/AMBIGUOUS/NONE rates, hit
rates, base rates, Delta, interval, undefined-resample count; per symbol and the exploratory period as reference;
false-warning rate = adverse share (entry, retest-hold) or favourable share (deterioration). Every counted event
keeps its journal key, bar and evidence (audit trail).

**Known limits.** ENTRY_CONFIRMATION_CANDIDATE needs the HTF 2-of-4, which read "none" through most of October
2026, so it may be too rare to test. 8 weeks x 2 symbols detects only large differences.
