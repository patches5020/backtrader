# Previous-day AVWAP + AFVP, Phase 3: classification (2026-10-16) -- commit a04729c

Analysis only. Not wired into any report, gate, checklist, sizing, watcher or execution path.
No protected parameter changed.

## `cdcx/volume_profile/vwap_confluence.py` (ruleset `vwap-vp-1`)
- Condition over the last 12 closed bars: EXPANSION (close >= +/-2 sigma), TREND (VWAP moved >= 0.25 sigma and
  >= 80% of closes on that side), BALANCE (VWAP moved <= 0.10 sigma or >= 3 VWAP crosses), UNCLEAR.
- Setups: VP-01 POC reaction (PENDING/CONFIRMED/FAILED), VP-02 heavy-volume zone (UNTESTED/APPROACHING/TESTED),
  VP-03 trend continuation (pullback to VWAP + later close beyond the bar), VP-04 value-area breakout
  (ACCEPTED after 3 closes outside / FAILED sweep / PENDING), VP-05 band exhaustion (EXTENDED/RETURNED).
- Evidence families, one vote each: vwap (TREND direction), volume (VP-04 ACCEPTED / VP-01 CONFIRMED),
  structure (existing bos_state continuation/retest_held), price_action (unfilled FVG formed today).
- QUALIFIED = 3+ families incl. structure, none opposing, higher timeframes aligned (caller-supplied; None ->
  cannot qualify). CANDIDATE = 2+. CONFLICT / NONE / UNKNOWN. Execution always NOT AUTHORIZED.
- Past bars are judged against the VWAP/sigma at that bar (new `AnchoredVWAP.sigma_series`).

## Live (5m, 2026-10-16 15:10Z)
XRP/USD and XLM/USD: BALANCE, structure + price action bearish -> CANDIDATE (bearish); XLM VP-04 FAILED sweep
above prior VAH 0.18543.

## Tests
706 passed (16 new in test_vwap_confluence.py); handoff validation PASS.
