# PREV-DAY AVWAP + AFVP section on by default (2026-10-17) -- commit 01ed186

User request: the section was missing from `cdcx-ai --symbol XRP/USD --timeframes ... --execute --structure`
(off by default). Now on by default. Display only; no gate, plan, watcher, ledger, sizing, config or execution
change. Protected params: unchanged.

## Changes
- cdcx-ai: default --vwap-vp 1h; cdcx-equity: default 15m (1h reads UNKNOWN: Robinhood gives 6 of 7 hourly
  bars). Bare --vwap-vp = 5m as before. New --no-vwap-vp turns it off.
- Telegram bot (cdcx/telegram_bot.py): extract_summary stops before the section (old /status content unchanged);
  new extract_vwap_vp digest (title, Context, STATUS, Next, Invalidates) appended to /status and /analyze;
  the full section is in the report document. Real /status message: 2,217 chars (< 4,096).
- tests/conftest.py: autouse fixture stubs the section printers outside the section's own test modules, so
  tests running cli.main() don't hit Crypto.com (one test had gone 0.06s -> 7s).
- New fixture tests/fixtures/xrp_cdcx_ai_report_vwap_vp.txt (real default output, no credentials).

## Verification
- Full suite 751 passed; handoff PASS.
- Live: `cdcx-ai --symbol XRP/USD --timeframes 1w,1d,4h,1h` prints the 1h section; with --no-vwap-vp it doesn't;
  `cdcx-equity --source robinhood --symbol SPY --timeframes 1w,1d,4h,1h` prints the 15m section.
- extract_decisions unaffected (the section's DECISION line sits outside any timeframe block).
- The running bot (PID 1700) uses the new digest only after a restart; until then /status includes the
  whole section in its summary (longer message, still delivered in chunks).

## Live default XRP section (2026-10-17 ~14:15Z)
```
          PREV-DAY AVWAP + AFVP -- XRP/USD 1h (analysis only, vwap-vp-1)         
---------------------------------------------------------------------------------
Prior session 10-16 00:00Z -> 10-17 00:00Z (24 bars), frozen:
  POC 1.33719 | VAH 1.34521 | VAL 1.30509 | HVN 1.33451 | LVN 1.34789
AVWAP from 10-16 00:00Z (ohlc4): 1.31614  sigma 0.016505  (last closed bar 10-17 13:00Z)
  +/-1: 1.29964 / 1.33265 | +/-2: 1.28313 / 1.34915 | +/-3: 1.26663 / 1.36566
Price 1.3002 = -1.16 sigma | Condition: UNCLEAR -- VWAP slope -0.21 sigma over 12 bars, 0 crosses, 0% of closes above

VP-01 POC reaction         NONE        no reaction at 1.33719 in the last 6 bars
VP-02 Heavy-volume zone    TESTED      prior value area 1.30509-1.34521 entered 2 time(s) today
VP-03 Trend continuation   NONE        needs a TREND condition
VP-04 Value-area breakout  PENDING     broke 1.30509, 2/3 closes so far
VP-05 Band exhaustion      NONE        no +/-2 sigma touch in the last 6 bars

  vwap          --        UNCLEAR: VWAP slope -0.21 sigma over 12 bars, 0 crosses, 0% of closes above
  volume        --        VP-04 PENDING, VP-01 NONE
  structure     bearish   BOS continuation bearish at 1.3013
  price_action  bearish   unfilled bearish FVG 1.2982-1.3043
  cdcx HTF      none      0 non-transitional timeframe(s) of 1H/4H/1D/1W -- need 2

Context (1h, closed bars): regime TRANSITIONAL | ADX(17) 26.4 -DI leads | RSI(17) 38.4 | VOL 1.6x of 17-bar avg -- context only, not scored

DECISION: CANDIDATE (bearish) -- structure, price_action agree; still needs 3 families incl. structure and cdcx 2-of-4 confluence (none right now) to be bearish
STATUS: SETUP DEVELOPING (bearish) -- monitor only
  Next:        cdcx 2-of-4 confluence turns bearish AND a third evidence family agrees
  Invalidates: 1H close back above AVWAP 1.31614 or bullish BOS: 1H close above 1.3087
Execution: NOT AUTHORIZED (analysis only)
---------------------------------------------------------------------------------
```
