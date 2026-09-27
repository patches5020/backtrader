# Equity Timestamp Fix (forming-candle check) — Change Summary

Date: 2026-09-27
Commit: da9bbdb (pushed to patches5020/backtrader master)
Repo touched: `cdcx-cli/` only.

## Bug
engine.py's volume-ratio (VOL(17)) forming-candle check did
`timestamps[-1] / 1000`, assuming Crypto.com milliseconds. Robinhood and
Webull (cdcx-equity) return SECONDS, so the last equity candle's open
landed in 1970 and always looked CLOSED. During market hours VOL(17) read
the still-forming candle's partial volume (understated).

## Fix
- `cdcx/no_trade_gate.py`: new `timestamp_to_seconds()` (>1e11 = ms) and
  `last_bar_is_forming(timestamps, timeframe, now)`.
- `cdcx/engine.py`: VOL(17) check uses `last_bar_is_forming`.
- `cdcx/vp_bos.py`: uses the same helper (was its own copy).
- New `tests/test_forming_bar_timestamps.py` (6 tests). The engine test
  fails on the old engine.py and passes with the fix.

## Verified
- Full suite: 411 passed; XRP baseline (crypto path) unchanged.
- SPY VOL(17) identical before/after on the weekend (all bars closed);
  the difference shows during market hours.

## Not changed (noted)
- Robinhood's native weekly series (interval="week") ends at the week of
  Sep 14 — the completed Sep 21–25 week is missing, so cdcx-equity's 1W
  row lags a week. Data-source issue; could be fixed by building weekly
  bars from daily.
