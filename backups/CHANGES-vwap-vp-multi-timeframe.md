# --vwap-vp accepts several timeframes (2026-10-17) -- commit e7ea89f

User request after `--vwap-vp 1w,1d,4h,1h,45m,30m,15m,5m` printed "needs an intraday timeframe".
Display only; no gate, plan, watcher, ledger, sizing, config or execution change. Protected params: unchanged.

## Changes
- vwap_confluence.split_timeframes(): intraday timeframes in the given order (deduplicated) + skipped ones
  (daily or longer, unrecognised).
- cdcx-ai: _print_vwap_vp loops over them (_print_vwap_vp_one per timeframe); one "skipped" line for 1w/1d.
- cdcx-equity: same; a failed fetch shows UNKNOWN for that timeframe only.
- telegram_bot.extract_vwap_vp: one digest block per section (each bounded at the next title).
- Single timeframe, default (1h / equity 15m) and --no-vwap-vp unchanged.

## Verification
- Full suite 755 passed (4 new tests); handoff PASS.
- Live XRP (`--vwap-vp 1w,1d,4h,1h,45m,30m,15m,5m`, ~25 s): skipped 1w, 1d; 4h MONITOR; 1h SETUP DEVELOPING
  (bearish); 45m SETUP DEVELOPING (bearish); 30m/15m/5m CONFLICT. All NOT AUTHORIZED.
- Live SPY (`--vwap-vp 1d,1h,15m,5m`): skipped 1d; 1h DATA UNKNOWN (known Robinhood 6-of-7 bars); 15m/5m MONITOR.

## Live XRP digest lines
```
PREV-DAY AVWAP + AFVP: skipped 1w, 1d -- the previous-day profile needs intraday bars
PREV-DAY AVWAP + AFVP -- XRP/USD 4h (analysis only, vwap-vp-1)         
Context (4h, closed bars): regime TRANSITIONAL | ADX(17) 44.6 -DI leads | RSI(17) 39.1 | VOL 0.3x of 17-bar avg -- context only, not scored
STATUS: MONITOR
Next:        2+ evidence families agree in one direction
Invalidates: -- (no thesis yet)
PREV-DAY AVWAP + AFVP -- XRP/USD 1h (analysis only, vwap-vp-1)         
Context (1h, closed bars): regime TRANSITIONAL | ADX(17) 26.4 -DI leads | RSI(17) 38.4 | VOL 1.6x of 17-bar avg -- context only, not scored
STATUS: SETUP DEVELOPING (bearish) -- monitor only
Next:        cdcx 2-of-4 confluence turns bearish AND a third evidence family agrees
Invalidates: 1H close back above AVWAP 1.31614 or bullish BOS: 1H close above 1.3087
PREV-DAY AVWAP + AFVP -- XRP/USD 45m (analysis only, vwap-vp-1)         
Context (45m, closed bars): regime TRANSITIONAL | ADX(17) 22.2 -DI leads | RSI(17) 38.4 | VOL 1.1x of 17-bar avg -- context only, not scored
STATUS: SETUP DEVELOPING (bearish) -- monitor only
Next:        cdcx 2-of-4 confluence turns bearish
Invalidates: 45M close back above AVWAP 1.31654 or bullish BOS: 45M close above 1.3087
PREV-DAY AVWAP + AFVP -- XRP/USD 30m (analysis only, vwap-vp-1)         
Context (30m, closed bars): regime TRANSITIONAL | ADX(17) 19.0 -DI leads | RSI(17) 43.4 | VOL 0.9x of 17-bar avg -- context only, not scored
STATUS: CONFLICT -- monitor only
Next:        the evidence families stop disagreeing (bullish: price_action vs bearish: volume)
Invalidates: -- (no single thesis)
PREV-DAY AVWAP + AFVP -- XRP/USD 15m (analysis only, vwap-vp-1)         
Context (15m, closed bars): regime TRANSITIONAL | ADX(17) 20.3 -DI leads | RSI(17) 47.1 | VOL 0.4x of 17-bar avg -- context only, not scored
STATUS: CONFLICT -- monitor only
Next:        the evidence families stop disagreeing (bullish: price_action vs bearish: volume)
Invalidates: -- (no single thesis)
PREV-DAY AVWAP + AFVP -- XRP/USD 5m (analysis only, vwap-vp-1)         
Context (5m, closed bars): regime TRANSITIONAL | ADX(17) 20.6 +DI leads | RSI(17) 55.7 | VOL 0.4x of 17-bar avg -- context only, not scored
STATUS: CONFLICT -- monitor only
Next:        the evidence families stop disagreeing (bullish: structure, price_action vs bearish: volume)
Invalidates: -- (no single thesis)
```
