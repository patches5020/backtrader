# --vwap-vp Context / STATUS / Next / Invalidates (2026-10-17) -- commit 27f3171

Display only. Files: cdcx-cli/cdcx/volume_profile/vwap_confluence.py (+150/-9), cdcx-cli/cdcx/cli.py (+10/-2),
cdcx-cli/tests/test_vwap_vp_context.py (16 tests). cdcx_equity.py unchanged (shared build_section).
No gate, plan, watcher, ledger, sizing, config or execution change. Protected params: unchanged.

## What it adds (end of the existing section)
- Context: engine.analyze_ohlcv + calculate_adx re-run on CLOSED bars of the section timeframe
  (regime, ADX(17) + DI lead, RSI(17), VOL ratio). "context only, not scored" (RQ5: no filter evidence).
  Fails closed: < 60 closed bars, stale data (24x7), or any error -> UNKNOWN.
- STATUS: relabels DECISION (NONE->MONITOR, CANDIDATE->SETUP DEVELOPING, QUALIFIED->CONFIRMED -- evaluate the
  existing gates, CONFLICT, UNKNOWN->DATA UNKNOWN).
- Next / Invalidates: only the classifier's swing high/low (stored on VwapVpResult), the AVWAP and the HTF
  requirement; missing levels print "level unknown"; the AVWAP clause only while price is on the thesis side.
- Crypto: one fetch of max(section bars, 200); the section reads the same last N bars as before.

## Verification
- Full suite 748 passed; handoff PASS.
- Replay of 2026-10-16 22:55Z reproduces the original section exactly (POC 1.30765, AVWAP 1.31659,
  sigma 0.0153977, CANDIDATE bearish) plus: Next "1H close below 1.2877 (bearish BOS) AND cdcx 2-of-4
  confluence turns bearish"; Invalidates "1H close back above AVWAP 1.31659 or bullish BOS: 1H close above 1.3519".
- Known, pre-existing: equity 1H prev-day profile reads UNKNOWN (Robinhood gives 6 of 7 hourly bars); 15m/5m work.

## Live output (2026-10-17)
```
          PREV-DAY AVWAP + AFVP -- XRP/USD 1h (analysis only, vwap-vp-1)         
---------------------------------------------------------------------------------
Prior session 10-16 00:00Z -> 10-17 00:00Z (24 bars), frozen:
  POC 1.33719 | VAH 1.34521 | VAL 1.30509 | HVN 1.33451 | LVN 1.34789
AVWAP from 10-16 00:00Z (ohlc4): 1.31675  sigma 0.016343  (last closed bar 10-17 12:00Z)
  +/-1: 1.30041 / 1.3331 | +/-2: 1.28407 / 1.34944 | +/-3: 1.26772 / 1.36578
Price 1.2967 = -1.40 sigma | Condition: UNCLEAR -- VWAP slope -0.18 sigma over 12 bars, 0 crosses, 0% of closes above

VP-01 POC reaction         NONE        no reaction at 1.33719 in the last 6 bars
VP-02 Heavy-volume zone    TESTED      prior value area 1.30509-1.34521 entered 2 time(s) today
VP-03 Trend continuation   NONE        needs a TREND condition
VP-04 Value-area breakout  PENDING     broke 1.30509, 1/3 closes so far
VP-05 Band exhaustion      NONE        no +/-2 sigma touch in the last 6 bars

  vwap          --        UNCLEAR: VWAP slope -0.18 sigma over 12 bars, 0 crosses, 0% of closes above
  volume        --        VP-04 PENDING, VP-01 NONE
  structure     bearish   BOS continuation bearish at 1.3013
  price_action  --        no unfilled FVG formed today
  cdcx HTF      none      0 non-transitional timeframe(s) of 1H/4H/1D/1W -- need 2

Context (1h, closed bars): regime TRANSITIONAL | ADX(17) 25.6 -DI leads | RSI(17) 35.3 | VOL 3.8x of 17-bar avg -- context only, not scored

DECISION: NONE -- one family only: structure
STATUS: MONITOR
  Next:        2+ evidence families agree in one direction
  Invalidates: -- (no thesis yet)
Execution: NOT AUTHORIZED (analysis only)
---------------------------------------------------------------------------------

           PREV-DAY AVWAP + AFVP -- SPY 15m (analysis only, vwap-vp-1)           
---------------------------------------------------------------------------------
Prior session 10-16 13:30Z -> 10-16 20:00Z (26 bars), frozen:
  POC 762.478 | VAH 767.728 | VAL 761.428 | HVN 763.003 | LVN 770.353
AVWAP from 10-16 13:30Z (ohlc4): 765.629  sigma 3.62616  (last closed bar 10-16 19:45Z)
  +/-1: 762.003 / 769.255 | +/-2: 758.376 / 772.881 | +/-3: 754.75 / 776.507
Price 763.295 = -0.64 sigma | Condition: TREND (bearish) -- VWAP slope -1.19 sigma over 12 bars, 0 crosses, 0% of closes above

VP-01 POC reaction         NONE        no bars today yet
VP-02 Heavy-volume zone    UNTESTED    prior value area 761.428-767.728, no bars today yet
VP-03 Trend continuation   NONE        no pullback to the VWAP in the last 6 bars
VP-04 Value-area breakout  NONE        no close beyond the prior VAH/VAL today
VP-05 Band exhaustion      NONE        no +/-2 sigma touch in the last 6 bars

  vwap          bearish   TREND: VWAP slope -1.19 sigma over 12 bars, 0 crosses, 0% of closes above
  volume        --        VP-04 NONE, VP-01 NONE
  structure     --        BOS no_break
  price_action  --        no unfilled FVG formed today
  cdcx HTF      none      0 non-transitional timeframe(s) of 1H/4H/1D/1W -- need 2

Context (15m, closed bars): regime TRANSITIONAL | ADX(17) 31.0 -DI leads | RSI(17) 38.0 | VOL 2.6x of 17-bar avg -- context only, not scored

DECISION: NONE -- one family only: vwap
STATUS: MONITOR
  Next:        2+ evidence families agree in one direction
  Invalidates: -- (no thesis yet)
Execution: NOT AUTHORIZED (analysis only)
---------------------------------------------------------------------------------
```
