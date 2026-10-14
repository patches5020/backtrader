# Intraday watcher de-dup + XRP bearish VWAP retest watcher (2026-10-14) -- commit 4a8a609

Alert-only, send-only watchers in `cdcx-cli/trading/alerts/`. Neither trades; neither is a cdcx gate.

## `xrp_intraday_range_watch.py`: no duplicate edge alerts
- Before: a side re-armed when a 5m close was in the middle of the **live** 30m range. After the 12:30Z flush the
  range shifted, so the LONG edge alert fired at 12:35Z and again at 13:00Z for the same visit.
- Now: when an edge/4-of-4 alert fires, the range midpoint at that moment is stored (`rearm_at`); that side re-arms
  only when a 5m close crosses back past it. Offline replay of 2026-10-14: one alert, not two.

## `xrp_vwap_retest_watch.py` + `xrp_vwap_retest_config.json` (new)
The user's 5m bearish anchored-VWAP retest checklist (from the 2026-10-14 analysis), on closed candles:
| # | Condition |
|---|---|
| C1 | 5m candle high >= anchored VWAP, close < min(VWAP, 1.3615) |
| C2 | its high < the prior bounce high and < 1.3646 |
| C3 | a later 15m close < 1.3607 |
| C4 | rejection candle volume > SMA(17) of prior 5m volume |
| C5 | no 5m close > 1.3646 from the rejection on |
Invalidated: a 15m close > 1.3690, or two 15m closes in a row > 1.3646.
- VWAP: anchored 2026-10-13 00:00Z, ohlc4, on Crypto.com 5m -- matches TradingView (1.3623).
- All met -> entry = confirming 15m close; stop = entry + **2.0 x ATR(5m, 11)** (user-chosen for this one-off paper
  calculation); TP1-4 = 2.2/2.6/3.2/4.5 R (25% each); breakeven = entry after TP1; size capped at paper equity.
- Alerts: 5m rejection (heads-up), all met (levels), invalidated (stops), data unavailable. Expires 2026-10-15 09:00Z.

## What happened live
13:50Z rejection (high 1.3638, close 1.3586) and 14:00Z 15m close 1.3482: C1/C2/C3/C5 passed, **C4 failed**
(47.9K vs SMA17 117.2K, inflated by the 972K 12:30Z flush), so no all-met alert. Levels at 1.3482: SL 1.3596,
TP1 1.3231, TP2 1.3185, TP3 1.3117, TP4 1.2969, BE 1.3482. cdcx: 1H/4H/1D NO TRADE (transitional); no trade made.
Whether C4 should exclude outliers / be advisory is an open user decision; unchanged here.

## Tests
667 passed; offline alert-path checks (incl. the duplicate replay) passed; live `--once` dry runs.

Protected params: unchanged (2.0x ATR is a watcher-only paper calculation; risk_parameters.json and cdcx's 1.5x untouched).
Not included: unrelated local edit to `trading/alerts/xrp_vp_plan_watch.py`.
