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

## RQ6 — Are vwap-watch-1 closed-bar warnings informative? (rev 3 — FROZEN 2026-10-19T15:21:06Z, not run)
Research only. Nothing here changes the watcher, a live plan, sizing, permission or protected parameter, and no
result authorizes execution.

**0. Freeze.** Binding only when the user freezes it. Preconditions: the watcher is committed, and the analysis
script `cdcx/backtest/vwap_watch_rq6.py` (implementing sections 3-10 exactly) is written, unit-tested on
synthetic data only, and committed. The freeze line then records: date/time (UTC), commit hash, and SHA-256 of
`vwap_watch.py`, of `vwap_watch_rq6.py`, and of this RQ6 text from its heading to the end of section 10. After
the freeze nothing in this block is edited; a correction is a new question with a new period.
- `FROZEN: 2026-10-19T15:21:06Z commit f19e1c0 vwap_watch.py=815325516f6d43718db77f44be288c3cc73c5225e87a77ccabd4d271159f0cdf vwap_watch_rq6.py=34c8d309c40529f1c4362691a22dc7c069af01c58d7b2f338ec6ea4556d40707 rq6_text=d154c94f76a938819787b75c4f0eb1855ac835d92bb4440d4939e8ae5cc0c631`
  (rq6_text = this block as committed in f19e1c0, before this line and the heading were filled in.
  S = 2026-10-21 00:00Z, E = 2026-12-16 00:00Z; fetch/analyse once, at or after 2026-12-17 00:00Z.)

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

## RQ7 — Does VP-06 value-area re-entry have an edge after costs? (FROZEN 2026-10-22T14:13:03Z, not run)
Research only. Source: the Trading Notes "3 volume-profile setups" video, setup 2 (assessed 2026-10-22). Nothing here
changes `classify()`, an evidence family, the DECISION, the watcher (RQ6 stays frozen), sizing, a gate or a protected
parameter, and no result authorizes execution.

**0. Freeze.** Binding only when the user freezes it. Preconditions:
`cdcx/volume_profile/vp_reentry.py` and `cdcx/backtest/vwap_vp_rq7.py` are written, unit-tested on synthetic data only
(`tests/test_vp_reentry.py`), and committed. The FROZEN line records the date and time (UTC), the commit, and the SHA-256 of both files and of this block (heading
through section 6). After the freeze nothing in this block is edited.
- `FROZEN: 2026-10-22T14:13:03Z commit 4dd7a09 vp_reentry.py=9cccf5003f546b560bff472483ab2967be9bf59393e274664c877bd70a514f79 vwap_vp_rq7.py=e82651c18c9ec60247fa021e2a5016f7214cbe1e035bf8f8926a441664307844 rq7_text=71e20c267d7a1e1a26fdc6548a5fb76fb54ca5c7df29ea72c44725ee0f74be4e`
  (rq7_text = this block as committed in 4dd7a09, from its heading up to the RQ8 heading, before this line and the
  heading were filled in. S = 2026-10-24 00:00Z, E = 2027-01-16 00:00Z; fetch/analyse once, at or after 2027-01-17 00:00Z.)

**1. Signal (vp_reentry.evaluate, exact).** 1H, previous-day levels from `prev_day_levels` (70% VA, 24 buckets,
unchanged). Precondition: the last closed bar before today closed inside [VAL, VAH], inclusive. Excursion: a close
today > VAH or < VAL (wicks don't count). Signal bar: the first later close back inside [VAL, VAH]. Direction: bullish
after a close below VAL, bearish after a close above VAH. Repeatable within the session. Walk-forward per
`vwap_vp_rq7.find_reentry_signals` (bars <= t only at each t).
- **VP-06** = precondition met (the hypothesis). **VP-06x** = the same re-entry with the prior close outside (comparator).

**2. Trade model and costs (unchanged, not tuned).** `vwap_vp_research.replay`: entry at the next bar's open,
stop 1.5 × ATR, TP1–TP4 2.2/2.6/3.2/4.5 R at 25% each, a bar touching both stop and target counts as the stop,
one open trade per setup. Costs 7.5 + 2 bps per side. Trades still open at the end of the data are excluded.

**3. Data and periods.** XRP/USD and XLM/USD, Crypto.com 1H via `CryptoComExchange.fetch_ohlcv`. Each series is fetched
once, saved, and identified by its SHA-256.
- **Confirmatory (prospective), the only period that can give a verdict:** S = 00:00Z of the first UTC day starting at
  least 24 h after the FROZEN timestamp; E = S + 84 days. A signal counts if its bar opened in [S, E). The data is fetched once, at or after
  E + 24 h, from S − 60 days, then analysed once. No interim looks.
- **Exploratory (development) 2025-06-01 → 2026-05-31:** descriptive and debugging evidence only, never a verdict. This
  period's VP-04 outcomes have been seen (RQ3/RQ5); VP-06 outcomes have not been computed anywhere as of this draft.

**4. Statistics.** Pooled across both symbols: mean net R per trade, with a 97.5% bootstrap interval (10,000 resamples,
`random.Random(20261022)`, one generator for the whole run, in this order: VP-06, VP-06x, then the difference). Also
reported: the interval of mean(VP-06) − mean(VP-06x), resampled within each group; trade count, win rate, max
drawdown in R, and the same figures per symbol.
- **Far-edge (descriptive only, the video's own trade):** entry at the next open, target at the far edge of the value area,
  stop at the excursion extreme, 24-bar horizon, a bar touching both counts as the stop. The report gives the target rate and the
  average gross R.

**5. Decision rule (confirmatory only).**
- **Primary:** VP-06 has "positive expectancy after costs" only if it has ≥ 30 trades and the lower bound of its interval is > 0.
- **Secondary:** "the precondition adds information" only if both groups have ≥ 30 trades and the lower bound of the
  difference is > 0.

Anything else = no or inconclusive. After any result is seen, nothing above changes; a change is a new question on new
data. A positive result only allows a separate, user-approved proposal (e.g. an advisory line). It never adds
weight, a vote or execution by itself.

**6. Known limits.**
- 12 weeks × 2 symbols probably gives ~100 trades or fewer, which can detect only a large effect.
- The protected ATR stop and TP ladder are not the video's trade. That is why the far-edge result is reported but never decides.
- 24-bucket profiles are coarse; resolution is RQ10.

## RQ8 — VP-04P breakout → pullback hold → BOS (FROZEN 2026-10-22T14:27:54Z, not run)
Research only. Source: the Trading Notes video, setup 3. VP-04P is a separate variant beside VP-04; VP-04, `classify()`, the
evidence families, the DECISION, the watcher (RQ6), sizing, gates and protected parameters are unchanged. No result
authorizes execution.

**0. Freeze.** Binding only when the user approves the values in section 1 and freezes RQ8. Preconditions:
`cdcx/volume_profile/vp_breakout_pullback.py` and `cdcx/backtest/vwap_vp_rq8.py` are written, unit-tested on synthetic data only
(`tests/test_vp_breakout_pullback.py`), and committed. The FROZEN line records the date and time (UTC), the commit, and the SHA-256 of both files and
of this block (heading through section 6). After the freeze nothing in this block is edited.
- `FROZEN: 2026-10-22T14:27:54Z commit 5fcbcc4 vp_breakout_pullback.py=e68de1bfe58b0eda7654864cbcbaec31397d57d64776f19d31a6c70432bd2bdb vwap_vp_rq8.py=34645d1b7457c39f27749fc5382c39fd0608559be5f1c1c0df18a5e393fbae44 rq8_text=4a2f0eba0366815426ed8e826cd2a89bf6e4ef181ee0e0cd611e6c4c82a218cb`
  (rq8_text = this block as committed in 5fcbcc4, from its heading up to the RQ9 heading, before this line and the
  heading were filled in. Values approved by the user as proposed. S = 2026-10-24 00:00Z, E = 2027-04-24 00:00Z; fetch/analyse once,
  at or after 2027-04-25 00:00Z.)

**1. Signal (vp_breakout_pullback.scan, exact; PROPOSED values = `Params()` defaults).** 1H previous-day levels
(`prev_day_levels`, unchanged). ATR = `atr_ema_variant1` ATR(11) at the break bar. The bullish case is shown; bearish mirrors it at VAL.
- **Break:** the first close above VAH today (previous close ≤ VAH).
- **Effort / result:** effort = break-bar volume ÷ mean volume of the 20 bars before it; result = break-bar range ÷ ATR.
  - HEALTHY: effort ≥ **1.5** and result ≥ **1.0**.
  - ABSORPTION: effort ≥ 1.5 and result < **0.6**.
  - NO SUPPLY: effort < **0.8**.
  - NORMAL: anything else.
  - UNKNOWN: fewer than 20 bars of volume history. Only HEALTHY can trigger.
- **Pullback:** the first later bar with low ≤ VAH + **0.25** × ATR.
- **Hold:** FAILED as soon as a close < VAH − **0.25** × ATR, or a low < VAH − **0.5** × ATR.
- **BOS:** after the pullback bar, a close > (the highest high from the break bar to the bar before the pullback) + **0.25** × ATR
  (the same 0.25 × ATR break margin cdcx already uses). The signal fires on that close.
- **Expiry:** no BOS within **12** bars of the break → EXPIRED. After an episode resolves, the next break starts a new one.

**2. Comparator, trade model and costs.** The comparator is VP-04 = `vwap_vp_research.find_signals` VP-04 fires (RQ3, unchanged).
Both are replayed with `vwap_vp_research.replay`: entry at the next open, stop 1.5 × ATR, TP1–TP4 2.2/2.6/3.2/4.5 R at 25% each,
a bar touching stop and target counts as the stop, one open trade per setup, costs 7.5 + 2 bps per side. Not tuned.

**3. Data and periods.** XRP/USD and XLM/USD, Crypto.com 1H, each series fetched once and identified by SHA-256.
- **Confirmatory (prospective):** S = 00:00Z of the first UTC day starting at least 24 h after the FROZEN timestamp; E = S + **182 days**.
  This is longer than RQ7's 84 days because VP-04P needs a HEALTHY break, a pullback and a BOS, so it will be rare. The data is fetched once at
  or after E + 24 h and analysed once. No interim looks.
- **Exploratory (development) 2025-06-01 → 2026-05-31:** descriptive only, never a verdict. VP-04 outcomes there are
  already known (RQ3); VP-04P outcomes have not been computed as of this draft.

**4. Statistics.** Pooled across both symbols: mean net R per trade, with a 97.5% bootstrap interval (10,000 resamples,
`random.Random(20261023)`, one generator, in this order: VP-04P, VP-04, then the difference). Also reported: the interval of
mean(VP-04P) − mean(VP-04), resampled within each group; trade count, win rate, max drawdown in R, and the figures per symbol.
- **Sensitivity (descriptive only):** VP-04P re-run with one parameter moved at a time:
  - effort_high 1.2 / 2.0
  - result_big 0.8 / 1.2
  - touch_atr 0.10 / 0.50
  - hold_wick_atr 0.25 / 0.75
  - bos_atr 0 / 0.5
  - max_bars 8 / 24

**5. Decision rule (confirmatory only).**
- **Primary:** "positive expectancy after costs" only if VP-04P has ≥ 30 trades and the lower bound of its interval is > 0.
- **Secondary:** "the sequence beats VP-04" only if both groups have ≥ 30 trades and the lower bound of the difference is > 0.

Anything else = no or inconclusive. The sensitivity runs never change the verdict and no value is re-chosen after a result is seen.
A positive result only allows a separate, user-approved proposal.

**6. Known limits.**
- VP-04P may still be too rare for 30 trades in 26 weeks. The result would then be "insufficient sample", not a failure.
- The video's own stop (just beyond the BOS) is not tested; the protected ATR stop is used.
- 24-bucket profiles are coarse (RQ10).

## RQ9 — Does the first-touch filter add information to VP-01? (FROZEN 2026-10-22T14:43:42Z, not run)
Research only. Source: the Trading Notes video, setup 1. VP-01 itself, `classify()`, the families, the DECISION, the
watcher (RQ6), sizing, gates and protected parameters are unchanged. No result authorizes execution.

**0. Freeze.** Binding only when the user approves the values in section 1 and freezes RQ9. Preconditions:
`cdcx/volume_profile/vp_first_touch.py` and `cdcx/backtest/vwap_vp_rq9.py` are written, unit-tested on synthetic data only
(`tests/test_vp_first_touch.py`), and committed. The FROZEN line records the date and time (UTC), the commit, and the SHA-256 of both files and
of this block (heading through section 6). After the freeze nothing in this block is edited.
- `FROZEN: 2026-10-22T14:43:42Z commit 762fc0e vp_first_touch.py=d573024f24a8504a98d3d5f3ebc626ce459a875cd62c7d0ba454458ebe49b0bd vwap_vp_rq9.py=2dbced8da8e17ed9e3e6406b50e447a4c6c55cbed035ac4972f8da846134eb8b rq9_text=6b9891d2538ca5d5c4396e0751c393714f7f282ddf119dee0c2e315e7f697e47`
  (rq9_text = this block as committed in 762fc0e, from its heading up to the RQ10 heading, before this line and the
  heading were filled in. Values approved by the user as proposed. S = 2026-10-24 00:00Z, E = 2027-04-24 00:00Z; fetch/analyse once,
  at or after 2027-04-25 00:00Z.)

**1. Filter (vp_first_touch.checks, exact; PROPOSED values).** Sampled at each VP-01 signal bar t from bars ≤ t only.
The reaction is the newest bar among today's last 6 with low ≤ POC < close (bullish) or high ≥ POC > close (bearish).
This is VP-01's own rule; a test checks that the two agree.
- **F1:** the prior session's last close was outside the value area (< VAL or > VAH).
- **F2 (first touch):** no bar of today before the reaction bar overlapped the POC zone, POC ± **0.25** × ATR(11) at the
  reaction bar (the video's "POC is a zone").
- **F3:** the reaction bar's volume is greater than the previous bar's.
- **PASS:** F1 and F2 and F3. FAIL otherwise. A signal whose filter reaction disagrees with the VP-01 direction is excluded
  from the split and counted.

**2. Signals, trade model, costs.** The VP-01 baseline = `vwap_vp_research.find_signals` VP-01 CONFIRMED fires, replayed with
`vwap_vp_research.replay` (protected 1.5 × ATR stop, TP1–TP4 2.2/2.6/3.2/4.5 R at 25% each, 7.5 + 2 bps per side), unchanged.
The filtered strategy is the PASS signals re-replayed on their own.

**3. Data and periods.** XRP/USD and XLM/USD, Crypto.com 1H, fetched once and identified by SHA-256.
- **Confirmatory (prospective):** S = 00:00Z of the first UTC day starting at least 24 h after the FROZEN timestamp; E = S + **182 days**,
  because the PASS group may be small. Fetched once at or after E + 24 h and analysed once. No interim looks.
- **Exploratory 2025-06-01 → 2026-05-31:** descriptive only. VP-01 outcomes there were part of RQ3's table; the
  filter split has not been computed as of this draft.

**4. Statistics.** Pooled across both symbols, `random.Random(20261024)`, one generator, 10,000 resamples, 97.5% intervals:
- the interval of mean net R (PASS − FAIL), resampled within each group;
- the filtered strategy's mean net R interval.
- **Descriptive only:** F1, F2 and F3 each alone (PASS / FAIL means), the baseline figures, the mismatch count, and the
  filtered strategy's drawdown.

**5. Decision rule (RQ5's rule, confirmatory only).** The filter "adds information" only if PASS and FAIL each have ≥ 30 trades and the
lower bound of PASS − FAIL is > 0. It is "worth proposing" as an advisory line only if, in addition, the filtered strategy has ≥ 30
trades and a lower bound > 0. Anything else = no or inconclusive. The F1–F3 components never decide. No re-choice of a value after a result.

**6. Known limits.**
- F1 requires the prior close to be outside the value area, which is less common. With PASS needing all three checks, the PASS group may be small.
- The protected stop is not the video's "just above the POC cluster" stop.
- POC precision is limited by 24 buckets (RQ10).

## RQ10 — Profile resolution: 24 rows vs. 400 rows (PLAN 2026-10-22 — calculation study, not a signal test)
Same safeguards as RQ7–RQ9. A calculation-validation study: it can recommend a resolution, but the 24-bucket default
(`volume_profile_fixed.DEFAULT_BUCKETS`) changes only if the user approves afterwards. Any change would also be a
new ruleset version, because RQ6–RQ9 are frozen on the 24-bucket profile.
- **What is known (RQ4, 2026-10-16):**
  - cdcx at 24 rows on 1H matches TradingView's 400-row Fixed Range VP within about one 24-row bucket.
  - cdcx at **400 rows on 1H bars is unstable** (POC 1.3365 against TradingView's 1.3071): TradingView fills its rows from finer intrabar data, while
    `build_volume_profile` spreads each bar's volume evenly over every bucket whose centre lies in the bar's high–low range.
  - So with 24 one-hour bars and 400 rows, each bar is a flat block across many rows, and the POC lands where the most blocks overlap.
  - Ties go to the lowest price (`max` order), and the value area grows one bucket at a time.
- **The question is therefore resolution AND source bars**, not just 24 vs. 400.
- **Plan:**
  1. **Algorithm audit:** how volume is distributed, the edge rounding, tie-breaking, and the value-area expansion (TradingView compares two
     rows at a time). Unit tests on synthetic profiles with known answers.
  2. **Parity grid:** for N = 20 completed XRP/USD and XLM/USD sessions, compute POC/VAH/VAL at {24, 100, 400} rows × source bars
     {1H, 15m, 5m}. Compare against TradingView's Fixed Range VP (400 rows, 70% VA) read through the TradingView MCP on the
     same session (chart time = UTC). Report the absolute error, in price and in ATR, for each cell.
  3. **Stability:** how far each level moves when the session window shifts by one source bar, and when the bucket count changes by ±10%.
  4. **Downstream effect (descriptive):** how often VP-01/VP-04/VP-06/VP-04P states change on the exploratory period if the
     best-parity cell replaced the 24-row 1H profile. No trade outcomes; outcomes would need a new pre-registered question.
- **Acceptance:** a cell is "better" only if its median error against TradingView is below the 24-row 1H error on
  both symbols and it is at least as stable. The finer source data also costs API calls (5m = 12× the bars), which is reported.
- **RESULT steps 1 + 3 (run 2026-10-22, last 20 completed UTC sessions, `cdcx/backtest/vp_resolution_rq10.py`; data in
  `cdcx-cli/trading/research/rq10/`, SHA-256 in `rq10_result.json`).** Median over sessions of the worst of POC/VAH/VAL, in
  ATR(11, 1H) units. Error is measured against 5m @ 400 rows, an INTERNAL PROXY, not TradingView:

  | cell | XRP err | XRP rows ±10% | XLM err | XLM rows ±10% |
  |---|---|---|---|---|
  | 1H @ 24 (current) | 0.32 | 0.19 | 0.40 | 0.29 |
  | 1H @ 400 | 0.21 | 0.01 | 0.43 | 0.01 |
  | 15m @ 400 | 0.10 | 0.01 | 0.37 | 0.01 |
  | 5m @ 100 | 0.03 | 0.04 | 0.05 | 0.05 |

  - **Current setting:** on 1H at 24 rows, a level moves about 0.2–0.3 ATR when the row count changes by ±10%, so it is coarse.
  - **More rows alone don't help:** 400 rows on 1H candles is stable, but it isn't closer to the 5m proxy. This agrees with RQ4.
  - **Value-area method:** growing the value area two rows at a time (TradingView-style) vs one row (cdcx) changes VAH/VAL by about 0.2 ATR at 24 rows and about 0.01 ATR at 400.
  - **Leading candidate:** 5m candles at 100–400 rows.
  - **Not decided:** the reference is a proxy built from the same 5m data, so step 2 (TradingView parity) is required before any recommendation. Step 4 hasn't been run.
  - **Nothing changed:** DEFAULT_BUCKETS stays 24.
- **RESULT step 2, TradingView parity (run 2026-10-22).** TradingView Fixed Range VP (400 rows, 70% VA, 15m chart) was read
  through the TradingView MCP for the same 20 sessions per symbol, using temporary drawings (created, read, removed; the user's
  drawings were verified unchanged). The readings are in `rq10_tv_xrp.json` / `rq10_tv_xlm.json`. A check that the method works: XRP 2026-10-15 reads
  1.3079 / 1.3252 / 1.2924, identical to RQ4. Figures are the median of the worst of POC/VAH/VAL vs TV, in ATR(11, 1H), with the share
  of sessions within 0.10 ATR:

  | cell | XRP median | XRP ≤ 0.10 | XLM median | XLM ≤ 0.10 |
  |---|---|---|---|---|
  | 1H @ 24 (current) | 0.30 | 5% | 0.95 | 0% |
  | 1H @ 400 | 0.30 | 15% | 0.85 | 15% |
  | 15m @ 400 | 0.16 | 40% | 1.41 | 15% |
  | 5m @ 100 | 0.13 | 45% | 0.52 | 40% |
  | 5m @ 400 | 0.09 | 50% | 0.53 | 35% |

  - **Current setting:** cdcx's 1H/24 levels sit a median 0.3 ATR (XRP) to 0.95 ATR (XLM) from TradingView's.
  - **Rows alone:** 400 rows on 1H candles doesn't help.
  - **Best:** 5m candles roughly halve the error.
  - **Two-peak days:** even at 5m, on about half the sessions the POC lands on a different volume node than TradingView's. On XLM, TradingView's
    VAL is often the day's low, which suggests days with two volume peaks, where small data differences flip the winning node.
  - **Value-area method:** growing it TradingView-style (two rows at a time) doesn't reduce the VAH/VAL error (5m@400: 0.031 vs 0.034 XRP, 0.249 vs 0.247 XLM).
  - **Interpretation:** the source-bar resolution is the main factor; the row count and the value-area method are minor. On two-peak days the POC is fragile for
    any method.
  - **Status:** step 4 (downstream state changes) is not run. No default changed.
  - **Recommendation for the user to decide:**
    - 5m @ 100–400 as a NEW ruleset version (vwap-vp-2), never edited into the frozen vwap-vp-1 that RQ6–RQ9 test.
    - Optionally, a "two-peak day" flag (POC unstable) as context.
- **RESULT step 4, downstream state changes (run 2026-10-22, the same saved data, 481 closed 1H bars per symbol).** For each bar,
  the setup states were computed with the current 1H/24 levels and with the frozen session's POC/VAH/VAL from 5m bars. This is
  descriptive only; there are no trade outcomes. Share of bars whose state:direction differs:
  - **XRP, 5m@400:** VP-01 12%, VP-04 14%, VP-06 11%, VP-04P 17%, VP-01F 9%, DECISION 2%.
  - **XLM, 5m@400:** VP-01 20%, VP-04 20%, VP-06 18%, VP-04P 15%, VP-01F 16%, DECISION 10%.
  - **5m@100:** similar.
  - **VP-03 / VP-05:** 0%, because they are VWAP-based.
  - **Trigger counts:** totals stay similar (e.g. XRP VP-04 ACCEPTED bars 111 → 130, XLM VP-01 CONFIRMED 108 → 91), but they land on different bars.
  - **Conclusion:** the level source materially changes WHICH bars signal. A vwap-vp-2 on 5m levels is therefore a different
    strategy, not a cosmetic fix. RQ3's outcomes don't carry over, so preferring it for anything beyond display would need its own
    pre-registered outcome question on new data. RQ10 is complete. A display-only vwap-vp-2 next to vwap-vp-1 is the user's decision.

## RQ11 — Do VP-04 signals do better on vwap-vp-2 levels? (FROZEN 2026-10-22T15:54:00Z, not run)
Research only. Follows RQ10: vwap-vp-2 (`prev_day_v2.py`, the same frozen session from 5m bars at 400 rows) is closer to
TradingView but moves 11–25% of setup states, so it is a different strategy. vwap-vp-1, `classify()`, the families, the DECISION,
the watcher (RQ6), RQ7–RQ9, sizing, gates and protected parameters are unchanged. The vwap-vp-2 line in the report is display only.
No result authorizes execution or a switch of rulesets.

**0. Freeze.** Binding only when the user approves section 1 and freezes RQ11. Preconditions: `cdcx/volume_profile/prev_day_v2.py`
and `cdcx/backtest/vwap_vp_rq11.py` are written, unit-tested on synthetic data only (`tests/test_prev_day_v2.py`,
`tests/test_vwap_vp_rq11.py`), and committed. The FROZEN line records the date and time (UTC), the commit, and the SHA-256 of both files and of this block
(heading through section 6). After the freeze nothing in this block is edited.
- `FROZEN: 2026-10-22T15:54:00Z commit 9ca50d6 prev_day_v2.py=2e2fcceb0f59ac56eb9d82fce1eae6f31f5b921083349b20edc0a8c4512a0d1b vwap_vp_rq11.py=24e2c127bd9c3debbbaada9d27f647d689527c82037b270b53c6df48fcc9f990 rq11_text=7ead4b3ed2279dd1c6a894db0205d6bd3f1097dc6f12cfbb01d70727d5764f0b`
  (rq11_text = this block as committed in 9ca50d6, from its heading to the end of the file, before this line and the
  heading were filled in. Values approved by the user as proposed. S = 2026-10-24 00:00Z, E = 2027-04-24 00:00Z; fetch/analyse once,
  at or after 2027-04-25 00:00Z.)

**1. Signals (PROPOSED).** 1H walk-forward exactly as `vwap_vp_research.find_signals`. At each bar t, `prev_day_levels` (vwap-vp-1)
gives the session and its AVWAP; POC/VAH/VAL are replaced by `levels_v2` from that session's 5m bars at **400** rows (HVN/LVN
unchanged; they only affect VP-05 text). `classify()` is run unchanged. A session with an incomplete set of 5m bars gives no
vwap-vp-2 signals that day, and is counted. **VP-04v2** = VP-04 ACCEPTED fires (primary); **VP-01v2** = VP-01 CONFIRMED (descriptive).
The comparators VP-04v1 / VP-01v1 are `vwap_vp_research.find_signals` on the same bars. A test proves the driver reproduces vwap-vp-1 exactly
when the levels aren't swapped.

**2. Trade model and costs.** `vwap_vp_research.replay`, unchanged: stop 1.5 × ATR, TP1–TP4 2.2/2.6/3.2/4.5 R at 25% each, a bar touching
both counts as the stop, one open trade per setup label, costs 7.5 + 2 bps per side.

**3. Data and periods.** XRP/USD and XLM/USD, Crypto.com 1H **and 5m**, each series fetched once and identified by SHA-256.
- **Confirmatory (prospective):** S = 00:00Z of the first UTC day starting at least 24 h after the FROZEN timestamp; E = S + **182 days**. The data is fetched once at or
  after E + 24 h, from S − 60 days, and analysed once. No interim looks.
- **Exploratory 2025-06-01 → 2026-05-31:** descriptive only. vwap-vp-1 VP-04 outcomes there are known (RQ3); vwap-vp-2 outcomes have
  not been computed.

**4. Statistics.** Pooled across both symbols, `random.Random(20261025)`, one generator, 10,000 resamples, 97.5% intervals, in this order:
VP-04v2, VP-04v1, VP-01v2, VP-01v1 (each mean net R), then VP-04 v2 − v1, then VP-01 v2 − v1 (resampled within each group). Also
reported: trade count, win rate, max drawdown in R, the figures per symbol, and skipped sessions.

**5. Decision rule (confirmatory only).**
- **Primary:** "VP-04 on vwap-vp-2 has positive expectancy after costs" only if it has ≥ 30 trades and the lower bound is > 0.
- **Secondary:** "vwap-vp-2 VP-04 beats vwap-vp-1 VP-04" only if both groups have ≥ 30 trades and the lower bound of the difference is > 0.

The VP-01 figures never decide. Anything else = no or inconclusive. A positive result only allows a separate, user-approved proposal
(e.g. to make vwap-vp-2 the levels the section scores on), which would itself be a new version.

**6. Known limits.**
- vwap-vp-2 still misses TradingView by about 0.5 ATR (median) on XLM. That looks like volume-data differences between the Crypto.com API and
  TradingView's feed rather than method, and it is unresolved.
- Two-peak days were tested as an explanation and rejected: the peak ratio doesn't predict mismatches.
- 5m history is 12× the bars to fetch.
