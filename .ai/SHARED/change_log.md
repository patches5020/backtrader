# Change Log (newest first)

Each entry: date, commit, what changed, whether any protected parameter changed.
Claude Code appends here after each handoff task. Full detail: `backups/CHANGES-*.md` and `git log`.

## 2026-10-22
- RQ10 follow-up: TradingView 15m bars identical to the Crypto.com API (data not the cause); 1m@400 profiles match TradingView to 0.018/0.044 ATR (XRP/XLM) -- TradingView uses 1m intrabar data; a 1m vwap-vp-3 is the user's decision. Protected params: unchanged.
- RQ11 FROZEN 2026-10-22T15:54:00Z (commit 9ca50d6; S 2026-10-24, E 2027-04-24, analyse once on or after 2027-04-25); prev_day_v2.py now frozen. Protected params: unchanged.
- vwap-vp-2 display line (5m @ 400 rows POC/VAH/VAL, cdcx-ai + cdcx-equity, display only) + RQ11 draft and driver vwap_vp_rq11.py; two-peak warning tested and rejected; 911 passed. RQ6-RQ9 untouched. Protected params: unchanged.
- RQ10 step 4: 5m-based levels change VP-01/04/06/04P states on 11-25% of 1H bars and the DECISION on 2-11%; a vwap-vp-2 would be a different strategy needing its own outcome RQ; RQ10 complete; 902 passed. Protected params: unchanged.
- RQ10 step 2: TradingView parity for 20 sessions x 2 symbols (temporary FRVP drawings, user drawings verified unchanged); 1H@24 is 0.30/0.95 ATR from TV (XRP/XLM), 5m@100-400 roughly halves it; value-area method not the cause; no default changed; 901 passed. Protected params: unchanged.
- RQ10 steps 1 + 3: profile resolution x source-bar calculation study (vp_resolution_rq10.py); 1H@24 is coarse (0.2-0.3 ATR sensitivity), 5m@100-400 the leading candidate pending TradingView parity; no default changed; 900 passed. Protected params: unchanged.
- RQ9 FROZEN 2026-10-22T14:43:42Z (commit 762fc0e; S 2026-10-24, E 2027-04-24, analyse once on or after 2027-04-25). Protected params: unchanged.
- VP-01F first-touch POC filter (research-only display row, LTF + HTF, cdcx-ai + cdcx-equity; VP-01 unchanged) + RQ9 pre-registration and driver vwap_vp_rq9.py + RQ10 plan; 894 passed. RQ6/RQ7/RQ8 untouched. Protected params: unchanged.
- RQ8 FROZEN 2026-10-22T14:27:54Z (commit 5fcbcc4; S 2026-10-24, E 2027-04-24, analyse once on or after 2027-04-25). Protected params: unchanged.
- VP-04P breakout -> pullback hold -> BOS (research-only display row, LTF + HTF, cdcx-ai + cdcx-equity; VP-04 unchanged) + RQ8 pre-registration and driver vwap_vp_rq8.py; 883 passed. RQ6/RQ7 untouched. Protected params: unchanged.
- RQ7 FROZEN 2026-10-22T14:13:03Z (commit 4dd7a09; S 2026-10-24, E 2027-01-16, analyse once on or after 2027-01-17). Protected params: unchanged.
- VP-06 value-area re-entry (research-only display row, LTF + HTF, cdcx-ai + cdcx-equity; not in classify()/families/DECISION/watcher) + RQ7 pre-registration and driver vwap_vp_rq7.py; RQ8-RQ10 planned; 866 passed. RQ6 untouched. Protected params: unchanged.

## 2026-10-21
- HTF AVWAP CONTEXT gets the LTF setup block (VP-01..VP-05, evidence families, Context, DECISION/STATUS/Next/Invalidates, Execution NOT AUTHORIZED) per 4H/1D/1W context, cdcx-ai + cdcx-equity; nothing removed; 848 passed. Analysis only; RQ6 frozen files untouched. Protected params: unchanged.

## 2026-10-20
- AVWAP line + sigma bands in TradingView colours (VWAP #1E88E5, +1..3 #F23645, -1..3 #4CAF50) in HTF AVWAP CONTEXT and PREV-DAY AVWAP + AFVP, cdcx-ai + cdcx-equity (TTY only); 844 passed. Display only; RQ6 frozen files untouched. Protected params: unchanged.
- PREV-DAY AVWAP + AFVP section: AVWAP line blue (next to yellow POC / red VAH / green VAL; TTY only); 844 passed. Display only; RQ6 frozen files untouched. Protected params: unchanged.
- HTF AVWAP context colours (cdcx-ai + cdcx-equity): POC yellow, VAH red, VAL green, AVWAP blue (TTY only; NO_COLOR/piped stays plain); 843 passed. Display only. Protected params: unchanged.
- HTF AVWAP context (cdcx-ai --structure, cdcx-equity --structure-report): 4H/1D/1W AVWAP anchored at each AVP's own anchor bar (+ 4H decline-start), closed bars, explicit unknowns; existing report byte-identical above the new section; 840 passed. Analysis only. Protected params: unchanged.

## 2026-10-19
- RQ6 test fix: draft-only assertion (failed after the freeze) replaced by a frozen-time + frozen-code-hash check; 812 passed. Test only. Protected params: unchanged.
- `80fc625` RQ6 FROZEN 2026-10-19T15:21:06Z (user approved): commit f19e1c0 + SHA-256 of vwap_watch.py, vwap_watch_rq6.py, RQ6 text. Confirmatory 2026-10-21 -> 2026-12-16; single analysis at/after 2026-12-17 00:00Z. Research only. Protected params: unchanged.
- `f19e1c0` tests: telegram-inbox import probes 60 -> 300 s (most likely cause of the 1/789 loaded-run failure). Test only. Protected params: unchanged.
- vwap-watch-1 first live run (XRP/USD + XLM/USD 1h, journal only, monitor only); hourly Windows task "cdcx vwap-watch hourly" registered and verified (scheduler run exit 0, no duplicates).

## 2026-10-18
- `72e247b` vwap-watch-1 AVWAP shadow watcher (monitor-only, closed bars, journal, not scheduled) + RQ6 analysis script (refuses to run until RQ6 is FROZEN; synthetic tests only); RQ6 draft rev 3 NOT frozen. Research only. Protected params: unchanged.

## 2026-10-17
- `e7ea89f` --vwap-vp accepts several timeframes (one section each; daily/weekly skipped) in cdcx-ai + cdcx-equity; Telegram digest covers each. Display only. Protected params: unchanged.
- `46c8685` XLM VP plans re-armed 2026-10-17 15:26Z (swing high 0.18557 / low 0.17865, expires 2026-10-24 15:26Z); bull 1/12, bear 4/12, approval not given. Plan data only. Protected params: unchanged.
- `01ed186` PREV-DAY AVWAP + AFVP section on by default (cdcx-ai 1h, cdcx-equity 15m, --no-vwap-vp); Telegram /status gets a 5-line digest. Display only. Protected params: unchanged.
- `27f3171` --vwap-vp adds Context (closed-bar regime/ADX/DI/RSI/VOL, not scored), STATUS, Next / Invalidates; cdcx-ai + cdcx-equity. Display only. Protected params: unchanged.
- `6376736` RQ5 pre-registered ADX / RSI filter test on VP-04 1H: neither filter meets the rule (inconclusive); --vwap-vp stays display only. Research only. Protected params: unchanged.

## 2026-10-16
- `ac5e2c1` RQ4: frozen previous-day profile matches TradingView within one bucket; live chart export (page, PNG, TV drawing). Docs only. Protected params: unchanged.
- `527986e` research_questions RQ3 (VP-04 1H CIs include zero) + RQ4 (AVWAP matches TradingView; AFVP within ~1 bucket). Docs only. Protected params: unchanged.
- `a6486cd` VP-04 1H + HTF follow-up research: unfiltered ~break-even after costs, filtered sample too small. Research only. Protected params: unchanged.
- `0c2652e` Prev-day AVWAP/AFVP phase 5 research harness; all setups net-negative OOS (XRP/XLM 5m/15m). Research only. Protected params: unchanged.
- `6a29dd6` --vwap-vp section in cdcx-ai + cdcx-equity (analysis only, off by default) and POC yellow. Protected params: unchanged.
- `a04729c` Prev-day AVWAP/AFVP phase 3: condition, VP-01..05 setups, one-vote evidence families; analysis only, not wired in. Protected params: unchanged.
- `fe57e3c` Anchored VWAP (1/2/3 sigma, matches TradingView) + frozen previous-day volume profile; analysis only, not wired in. Protected params: unchanged.
- `d01b892` VP plan watcher shows US Central time; R3 notes an R2 block; XRP VP plans re-armed (expire 2026-10-23); one-shot XLM re-arm after 2026-10-17 15:22Z. Protected params: unchanged.

## 2026-10-15
- `4ad0d88` cdcx-ai / cdcx-equity display: VAH red, VAL green (STRUCTURE map labels were inverted). Display only.
  Protected params: unchanged.
- `cea9c4c` New `.ai/SHARED/research_questions.md`: RQ1 R10 window vs. breakdown, RQ2 ATR vs. structural stop (offline
  tests only). Protected params: unchanged.
- `b7996b0` VWAP-retest and bounce-zone alerts add an ADVISORY structural stop (rejection high + 0.25 ATR) and flag an ATR
  stop inside the tested zone; 2x ATR stop rule unchanged. Protected params: unchanged.

## 2026-10-14
- `359f6ac` New alert-only XRP bounce-zone rejection watcher (1.3316-1.3385, closed 5m/15m, stale guard, expires
  2026-10-15 09:00 UTC) + autostart entry. Protected params: unchanged.
- `c2a06e5` VWAP retest watcher: volume grades the alert (A strict SMA / B median / C none) instead of blocking it;
  15-min freshness guard; intraday XRP watchers added to cdcx_autostart.sh. Protected params: unchanged.
- `4a8a609` Intraday range watcher: no duplicate edge alerts (re-arm at the midpoint stored when the alert fired).
  New alert-only XRP bearish anchored-VWAP retest watcher (5 conditions on closed 5m/15m; levels use a user-chosen
  2.0x ATR stop for this paper calculation). Protected params: unchanged.
- `a36e433` Range mode (`--execute` + preview, cdcx-equity preview) computes range/RSI/rejection on **closed candles only**
  (`cli._closed_bars`); one forming 30m bar had moved XRP's VAH 1.3833 -> 1.3748. Execution-gate input changed WITH user
  approval; stop/TPs/sizing/trend path unchanged. Plus alert-only XRP intraday range watcher (expires 2026-10-15 09:00 UTC).
  Protected params: unchanged.

## 2026-10-10
- `c0f5849` VP plans: calculated open-risk guard (remaining stop risk of all open trades + proposed <= 2% of equity,
  fail-closed, re-checked under the approval lock) and a real-path sizing test (cdcx sizing at 1% = $9.80 on $980,
  live_execution tripwire). Code only. Protected params: unchanged.
- `7743a6e` VP plans risk 2% -> **1% per trade** on XRP and XLM; one open paper trade per coin (max 2% total).
  Protected parameter lowered for these plans WITH user approval; cdcx global default unchanged.
- `25aa7c6` XLM/USD bull + bear VP paper plans (same 12 rules as XRP) via `--symbol XLM/USD`; XRP verified unchanged on
  identical data. Shared paper account, one open paper trade across XRP/XLM, one approval at a time. XLM armed
  0.19709 / 0.19131 until Oct 17. Monitor-only. Protected params: unchanged.

## 2026-10-09
- `e3f4c67` VP plan display: the plan line is now labelled a sizing preview (not an order/entry), with an
  illustration at the R6 trigger; PERMISSION NEEDED alert says levels come from the live price at approval.
  Display only. Protected params: unchanged.
- `73abe7c` VP plan execution-safety audit: approval lock (one at a time), final expiry/state/open-trade/fresh-bar
  rechecks right before execution; offline (22) + end-to-end (7 scenarios, real cdcx open path, temp ledger)
  harnesses added. Ledger snapshots backed up to D:\cdcx-paper-trades\ledger. Protected params: unchanged.
- `1382183` Circuit breaker drawdown now uses a cumulative equity curve from the first trade's balance (first loss
  and compounding losses counted; was stuck at 0-2%); paper closes stamped with the touching 5m candle (5a75fd5f:
  15:10 UTC). Protected area changed WITH user approval; thresholds 3 losses / 10% unchanged.
- `b799744` XRP bullish + bearish VP paper-trade plans in one watcher (xrp_vp_plan_watch.py, replaces the bull-only
  watcher): 12 closed-bar requirements each, levels armed from fresh 4H swings (1.5237 / 1.3176), per-plan
  `--approve` with expiry, one-shot, conflict, data-failure and live range-path/direction preflight. Alert-only
  until approved, paper only. Protected params: unchanged.
- `029104e` XRP bullish paper-trade plan watcher: 12 closed-bar requirements, Telegram progress/permission/
  invalidation alerts, `--approve` with expiry, one-shot, live range-path/LONG preflight; autostart supervised.
  Alert-only until approved, paper only. Protected params: unchanged.
- `3e1df90` Paper stops/TPs fill at their level from 5m candle ranges (gap -> bar open); 5a75fd5f re-recorded at
  -1R instead of -1.20R. Protected params: unchanged.

## 2026-10-05
- `7781c03` tests/conftest.py: every test's journal + trade log go to tmp_path -- the suite had been writing fixture
  BTC/USDT "trades" into the real trading/paper/ (486 files). Protected params: unchanged.
- `6685587` XRP watcher config-driven (xrp_bos_watch_config.json), cdcx-style ATR-margin retests, re-armed with
  break-even 1.532 / weekly VAL 1.5379 / 1.5096 retest / 4H-fail 1.4913. Alert-only. Protected params: unchanged.

## 2026-10-04
- `8c60342` cdcx-equity below 1h: Robinhood 5m/10m native (15m/30m/45m built), Webull 1m/5m/15m/30m native
  (10m/45m built), session-anchored to 9:30 ET; VP-BOS/AVP lower-TF rows; read-only range preview. Confluence
  and --execute still 1h/4h/1d/1w. Protected params: unchanged.
- `24eff09` Advisory sections (ATR alignment, VP hierarchy, STRUCTURE blocks, setup context/ATR timing, grade note,
  VP-BOS, AVP, range preview) extended to requested lower timeframes as "context only" lines. Protected counts
  (ATR x/4, VP-BOS 2-of-4, 1W/1D/4H/1H roles, gate) unchanged. Protected params: unchanged.
- `bbe08a2` Telegram bot: `/status` and `/analyze` take timeframes (1m 5m 10m 15m 30m 45m 1h 4h 1d 1w; default
  1w,1d,4h,1h); `/chart` adds 1M/10M/30M/45M. Whitelisted tokens only, never --execute. Protected params: unchanged.
- `fce5dff` Timeframes below 1h: 10m/45m built from native 5m/15m candles (UTC-aligned); 1m/5m/15m/30m native.
  Reported only -- confluence still 1h/4h/1d/1w. Protected params: unchanged.
- `c6b2aa6` Windows logon task + WSL supervisor keeping the Telegram bot (single reader) and the XRP watcher
  running. Protected params: unchanged.
- `137ab1f` Read-only RANGE MODE PREVIEW without --execute (shares inputs with --execute); VP-BOS PENDING note.
  Display-only. Protected params: unchanged.
- `a15e764` Committed the Sep 29–30 leftovers: dated `.ai/SHARED/reports/` (XRP MTF report + trade status), the
  archived stray trade log, and their change notes/zips. Data and notes only. Protected params: unchanged.
- `b26455d` XRP/USD BOS trigger-map watcher (`trading/alerts/xrp_bos_trigger_watch.py`): Telegram alert once per
  closed-bar 15m/1H/4H/1D break, 1H retest held/failed, and paper stop/TP1 touch. Send-only, alert-only.
  Protected params: unchanged.

## 2026-10-03
- `3c83ab6` CDCX-AI TRADE ANALYSIS shows Long/Short entry, stop, breakeven, TP1-TP4 and R:R under the existing
  lines, using the same 1.5x ATR + 2.2/2.6/3.2/4.5 R ladder (user's choice over 1R-4R). Display-only; existing
  lines unchanged. Protected params: unchanged.

## 2026-10-02
- `e9ad14f` Telegram inbox now stores sent reports (direction=outbound) tagged with source/symbol/message_type;
  new read-only `telegram_latest_report` MCP tool; opt-in localhost+bearer HTTP transport for an OpenAI Secure MCP
  Tunnel. Still one getUpdates reader. Local release gate passed (reports 153 -> 154). Protected params: unchanged.

## 2026-09-29
- `ebbf867` MULTI-TIMEFRAME SUMMARY: ranging rows show Signal `RANGE` / Market `neutral` (crypto + equity).
  Display-only; signal.signal and _market_bias unchanged. Protected params: unchanged.
- `dae2a2a` Ranging timeframes print `DECISION: RANGE MODE` instead of the 0-100 trend label (was "STRONG SELL"
  on XRP 1H at +13). Display-only; execution_signal unchanged. Protected params: unchanged.

## 2026-09-28
- `a290752` Telegram inbox (SQLite) + read-only inbox MCP server; the cdcx bot stays the sole Telegram reader.
  Informational only, no execution path. Protected params: unchanged.
- `600bb1d` Stage-2 setup backtest harness; XRP result: no setup beats the baseline (AVP not supported yet).
  Out-of-sample split locked. Protected params: unchanged.
- `c5bec3e` AVP Bullish Rejection added as a paper/analysis-only signal (stage 1 of 5). Protected params:
  unchanged; never read by the gate.

## 2026-09-27
- `cc613bb` Telegram single-reader: cdcx bot is the only @patches5020bot reader; send-only
  cdcx-telegram CLI; Claude Code Telegram plugin disabled. Protected params: unchanged.
- `88305f0` Read-only cdcx Telegram bot (/status /analyze /chart /report /help); never executes.
  Protected params: unchanged.
- ChatGPT <-> Claude Code handoff layer added (`.ai/`, `CLAUDE.md`); validator checks 15 protected values
  against the live code. Protected params: unchanged.
- `2f0a040` VP-BOS terminology locked (NONE / BOS-PENDING / VP-BOS / BOS-FAILED); summary table split into
  SWING / BOS / VP ACCEPTANCE / RESULT; temporal causality invariant tests. Protected params: unchanged.
- `b021961` bos_state: only closes AFTER a swing formed can break it (false 1D/4H/1H "failed breaks" removed).
  Baseline VP-BOS rows updated with user approval; baseline verdict unchanged. Protected params: unchanged.
- `c867591` Equity weekly bars close Friday 16:00 ET (crypto weeks still 7 days). Protected params: unchanged.
- `0ecbe76` Webull weekly bars re-stamped to Monday. Protected params: unchanged.
- `7d448bf` Robinhood weekly bars built from daily data. Protected params: unchanged.
- `da9bbdb` Forming-candle check handles second-resolution equity timestamps. Protected params: unchanged.
- `7d0934a` Advisory VP-BOS added. Protected params: unchanged.

## 2026-09-26
- `dedee18` XRP multi-timeframe baseline regression test. Protected params: unchanged.
- `efd87be` EMA + FVG columns in the MULTI-TIMEFRAME SUMMARY. Protected params: unchanged.
