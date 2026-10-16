# --vwap-vp report section (Phase 4) + yellow POC (2026-10-16) -- commit 6a29dd6

No protected parameter, gate, sizing or execution change.

## Phase 4: `--vwap-vp [TF]` in cdcx-ai and cdcx-equity (default 5m, off unless passed)
- Prints the PREV-DAY AVWAP + AFVP section (prev_day + vwap_confluence) after the MULTI-TIMEFRAME SUMMARY.
- cdcx-ai fetches 2 days of TF bars from Crypto.com; cdcx-equity uses its own source (regular-hours bars,
  last completed 09:30-16:00 ET session).
- Higher-timeframe check `htf_direction()`: cdcx's own evaluate_confluence on 1H/4H/1D/1W with the SAME
  filter as --execute (transitional excluded). QUALIFIED requires it to point the same way.
- Data errors / daily TF -> UNKNOWN line, never a crash. Never read by confluence, checklist, sizing, --execute.

## Yellow POC (user's choice)
`colorize_poc` (YELLOW) in `cdcx/utils/color.py`, used in the MARKET STRUCTURE report ("(point of control,
yellow)"), the STRUCTURE map ("POC (yellow)", was "POC (white)"), the AVP section and the new section.
Same TTY / NO_COLOR / FORCE_COLOR rules. `tests/fixtures/xrp_cdcx_ai_report.txt` (old recorded input) unchanged.

## Live (XRP/USD 5m, 15:50Z)
Prev day POC 1.3077 / VAH 1.3263 / VAL 1.2944; AVWAP 1.3194; price -0.82 sigma, BALANCE; VP-01 PENDING bearish;
cdcx HTF none -> CANDIDATE (bearish). FORCE_COLOR run shows POC yellow, VAH red, VAL green.

## Tests
715 passed + 1 failure in test_telegram_inbox_bridge.py (subprocess import timing on a slow machine; passed
3/3 reruns, untouched by this change). 10 new tests. Handoff validation PASS.
