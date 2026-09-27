# Robinhood Weekly Bars From Daily Data — Change Summary

Date: 2026-09-27
Commit: 7d448bf (pushed to patches5020/backtrader master)
Repo touched: `cdcx-cli/` only.

## Problem
Robinhood's native weekly series (interval="week") lags. On Sat
2026-09-26 it ended at the week of Sep 14; the daily series already had
all of Sep 21-25. cdcx-equity's 1W row was one week behind.

## Fix (`cdcx/exchange/robinhood_equity.py`)
- "1w" now fetches DAILY bars (5year span) and groups them into calendar
  weeks via new `_aggregate_weekly` (open of first session, close of last,
  max high, min low, summed volume), stamped Monday 00:00 UTC — same as
  the native series, including holiday-shortened weeks.
- Verified vs native weekly over 60 completed weeks: OHLCV matched exactly.
- 3 new tests in `tests/test_exchange_robinhood_equity.py`.

## Effect (SPY 1W)
- Before: last week Sep 14, price 761.69, score 93 BUY, RSI 60.6
- After:  last week Sep 21-25, price 771.35, score 100 STRONG BUY, RSI 63.0
- Regime still transitional; 200 weekly bars available.

## Notes
- Weekend: the finished week is stamped Monday, so it counts as "forming"
  until next Monday and VOL(17) uses the prior week — same as native.
- Webull weekly not touched/checked.
- Full suite: 414 passed.
