# Webull Weekly Bar Stamp Fix — Change Summary

Date: 2026-09-27
Commit: 0ecbe76 (pushed to patches5020/backtrader master)
Repo touched: `cdcx-cli/` only.

## Finding
- Webull's weekly series does NOT lag (checked live via the Webull
  connector): its latest week is Sep 21-25, identical to the week built
  from Robinhood daily data. The Robinhood build-from-daily fix was not
  needed here.
- Different bug: Webull stamps a weekly bar with the week's LAST session
  (Sep 21-25 -> "2026-09-25T04:00:00.000+0000", Friday). cdcx treats
  timestamps as bar OPENS (forming = open + 1 week > now), so a finished
  week counted as forming until the following Friday; the 1W VOL(17)
  used two-week-old volume all the next week.

## Fix (`cdcx/exchange/webull_equity.py`)
- New `_restamp_weekly_to_monday`: "1w" bars re-stamped to Monday
  00:00 UTC of their week (same as robinhood_equity). OHLCV untouched;
  1h/4h/1d untouched.
- 3 tests in `tests/test_exchange_webull_equity.py` using the real
  Webull SPY response shape; the 2 weekly tests fail on the old code.

## Caveat
- WEBULL_APP_KEY / WEBULL_APP_SECRET aren't in .env, so the cdcx-equity
  Webull source (OpenAPI SDK) couldn't be run end to end. Data was
  checked via the Claude Webull connector, a different client.
- Full suite: 417 passed.
