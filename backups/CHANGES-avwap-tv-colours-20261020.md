# AVWAP line + sigma bands: TradingView colours (HTF + LTF, cdcx-ai + cdcx-equity) — 2026-10-20

Display only, at the user's request ("bands 1-3 +=red/-=green", "make it the same as the TV 1 day
chart", "also do the same AVWAP bands on the LTFs", "do the same on the CDCX-EQUITY"). Colours read
over CDP from both Anchored VWAP drawings on the CRYPTOCOM:XRPUSD 1D chart:
UpperBand/_2/_3 #F23645, LowerBand/_2/_3 #4CAF50, VWAP #1E88E5.

- `cdcx/utils/color.py`: new `rgb()` (24-bit SGR), `colorize_avwap_upper` (#F23645),
  `colorize_avwap_lower` (#4CAF50); `VWAP_COLOR` now `rgb("#1E88E5")` (was ANSI 34 blue).
- `cdcx/htf_avwap.py`: HTF AVWAP CONTEXT "Bands:" line, lower value green / upper value red.
- `cdcx/volume_profile/vwap_confluence.py`: PREV-DAY AVWAP + AFVP (LTF) band line, same colours.
- cdcx-equity prints through the same two renderers, so it is covered with no equity-specific code.
- Tests: 3 colour tests now compare against `VWAP_COLOR` instead of ANSI `BLUE`.
- Same TTY / NO_COLOR / FORCE_COLOR rules: piped output, logs and Telegram stay plain.
- RQ6 freeze: untouched (vwap_watch.py / vwap_watch_rq6.py not modified).
- Evidence: `FORCE_COLOR=1` render -> "ESC[1mESC[38;2;30;136;229mAVWAP 1.30156ESC[0m
  ESC[1mESC[38;2;76;175;80m1.28503ESC[0m / ESC[1mESC[38;2;242;54;69m1.31809ESC[0m".
  Live cdcx-equity (after Robinhood re-login, session cached to ~/.tokens/robinhood.pickle):
  `FORCE_COLOR=1 cdcx-equity --source robinhood --symbol SPY --timeframes 1w,1d,4h,1h,15m --structure-report`
  -> HTF "ESC[38;2;30;136;229mAVWAP 768.498" / "Bands: +/-1: ESC[38;2;76;175;80m762.827 / ESC[38;2;242;54;69m774.169";
  LTF "ESC[38;2;30;136;229mAVWAP from 10-20 13:30Z (ohlc4): 769.037" / "+/-1: ESC[38;2;76;175;80m767.417 /
  ESC[38;2;242;54;69m770.656". The HTF section prints only in --timeframes (MTF) mode.
- Full suite: 844 passed; 700 warnings (pre-existing). Protected params unchanged.
