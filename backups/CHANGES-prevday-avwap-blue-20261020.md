# PREV-DAY AVWAP + AFVP: AVWAP line blue — 2026-10-20

Display only, at the user's request ("Do the same for AVWAP VWAP=BLUE"). In the
"PREV-DAY AVWAP + AFVP -- <symbol> <tf> (analysis only, vwap-vp-1)" section the line
"AVWAP from <anchor> (<source>): <vwap>" is now blue (`colorize_vwap`, added in 410d451), next to the
existing yellow POC / red VAH / green VAL. Same TTY / NO_COLOR / FORCE_COLOR rules: piped output, logs
and Telegram stay plain.

- Files: `cdcx/volume_profile/vwap_confluence.py` (format_vwap_vp only), `tests/test_vwap_confluence.py` (+1 test).
- RQ6 freeze: untouched. The freeze hashes only vwap_watch.py / vwap_watch_rq6.py / RQ6 text, and
  vwap_watch prints through its own formatters, not format_vwap_vp.
- Evidence: live `FORCE_COLOR=1 cdcx-ai --symbol XRP/USD --timeframe 5m --vwap-vp 5m` ->
  "ESC[34mAVWAP from 10-19 00:00Z (ohlc4): 1.30912ESC[0m".
- Full suite: 844 passed (843 before); 700 warnings (pre-existing). Protected params unchanged.
