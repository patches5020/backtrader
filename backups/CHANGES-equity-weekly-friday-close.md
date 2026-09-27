# Equity Weekly Bars Close Friday 16:00 ET — Change Summary

Date: 2026-09-27
Commit: c867591 (pushed to patches5020/backtrader master)
Repo touched: `cdcx-cli/` only.

## Problem
Equity weekly bars are stamped Monday 00:00 UTC; the forming check was
open + 7 days, so a finished week stayed "forming" all weekend and the
1W VOL(17) used the week before.

## Fix
- `cdcx/exchange/cryptocom.py`: OHLCV gains `market` (default "24x7").
- `cdcx/exchange/robinhood_equity.py`, `webull_equity.py`: tag "us_equity".
- `cdcx/no_trade_gate.py`: new `bar_close_time()` — us_equity 1w closes
  Friday 16:00 America/New_York (EDT 20:00 UTC / EST 21:00 UTC); all
  else open + length. `last_bar_is_forming()` takes `market`.
- `cdcx/engine.py`, `cdcx/vp_bos.py`: pass market through.
- Crypto unchanged (weeks still 7 days).

## Effect
SPY, Sat 2026-09-26: 1W VOL(17) 1.23x -> 1.02x (finished Sep 21-25 week).

## Tests
8 new (DST/EST close, weekend closed, 15:59 Fri forming, crypto 7 days,
other equity TFs unchanged, engine uses finished week, both sources tag).
Full suite: 425 passed.

## Known limits
- Holiday Friday: week counts as forming until Fri 16:00 (1-day delay).
- Equity 1D still closes at next UTC midnight, not 16:00 ET session end.
