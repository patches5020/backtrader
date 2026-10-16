# RQ4 frozen-profile parity + live prev-day AVWAP/AFVP chart export (2026-10-16) -- commit ac5e2c1

Docs + research tooling only. No code in cdcx, protected parameter, gate, watcher or execution change.

## RQ4 closed
TradingView Fixed Range VP over 2026-10-15 00:00 -> 23:00 UTC bar (not extended, 400 rows, 70% VA):
POC 1.3079 / VAH 1.3252 / VAL 1.2924. cdcx 1H: 1.30765 / 1.32626 / 1.2917; cdcx 5m: 1.3077 / 1.3263 / 1.2944.
All within one 24-row bucket (~0.0027). AVWAP already matched (RQ4). No code change.

## Chart outputs (live data, closed 1H bars, 2026-10-16 22:55 UTC)
- Web page (private artifact): https://claude.ai/artifact/R4S6KqR6TQgwgUzbGhquN8
- PNG sent to Telegram via cdcx-telegram photo.
- TradingView: one Fixed Range VP drawing added (prior UTC day, not extended, yellow POC). User's other drawings and
  the paper short untouched.
- Snapshot: CANDIDATE (bearish), BALANCE, -0.81 sigma, BOS no_break, cdcx HTF none. Execution NOT AUTHORIZED.

## Regenerate (from cdcx-cli/, files in the gitignored trading/research/vwap_vp/)
1. `cdcx-ai --symbol XRP/USD --timeframes 1h,4h,1d,1w --vwap-vp 1h` -> save the PREV-DAY AVWAP section to section.txt
2. `python trading/research/vwap_vp/chart_export.py out.json out.png section.txt`
3. Replace __DATA__ in chart_page_template.html with out.json for the web page.
