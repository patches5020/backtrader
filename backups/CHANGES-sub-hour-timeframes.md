# Timeframes below 1h: cdcx-ai + Telegram bot (2026-10-04) -- commits fce5dff, bbe08a2

## Request
"CDCX AI TRADE ANALYSIS doesn't allow me below 1hr: 1h, 45m, 30m, 15m, 10m, 5m, 1m" (screen recording of a
1h/4h/1d/1w run).

## Findings
- cdcx-ai already handled the native 1m/5m/15m/30m.
- 10m and 45m failed: Crypto.com has no candles of those sizes.
- The Telegram bot hard-coded 1w,1d,4h,1h for /status and /analyze, and /chart only accepted 5M/15M/1H/4H/1D/1W.

## Changes
- **fce5dff, `cdcx/exchange/cryptocom.py`**
  - A minute/hour size the exchange doesn't serve is built from the largest native size that divides it
    (10m = 5m ×2, 45m = 15m ×3).
  - Groups are aligned to the epoch / UTC midnight, like TradingView.
  - OHLCV rules: open = first, high = max, low = min, close = last, volume = sum.
  - An incomplete oldest group is dropped; the forming newest group is kept.
  - Day/week sizes are never built. An exchange that doesn't list its sizes is fetched as before.
  - `cli.py` help text now lists 1m–45m.
- **bbe08a2, `cdcx/telegram_bot.py`**
  - `/status` and `/analyze` take optional trailing timeframes: 1m 5m 10m 15m 30m 45m 1h 4h 1d 1w, comma- or
    space-separated, any case ("1M" = one minute).
  - The default is still 1w,1d,4h,1h. `/analyze`'s chart uses the fastest requested timeframe.
  - `/chart` adds 1M 10M 30M 45M.
  - Only whitelisted tokens reach argv; still never `--execute`.

## Protected
Confluence still counts only 1h/4h/1d/1w (`confluence.ALLOWED_TIMEFRAMES`, now covered by a test). ATR alignment,
the VP hierarchy, the structure setup, VP-BOS, AVP and the range preview stay on the four. Protected params: unchanged.

## Verification
- **Live XRP/USD:**
  - 45m vs an independent 5m ×9 rebuild: 39/39 closed bars identical.
  - 10m vs 1m ×10: high/low/close identical on 39/39. 3 opens differ by 1–5 ticks (Crypto.com's own 5m opens).
  - A full `--timeframes 1m,5m,10m,15m,30m,45m,1h,4h,1d,1w` run and `--structure` on 5m/45m both OK.
  - Works from any working directory (the console script always loads the canonical copy).
- **Tests:** 631 passed (+11 timeframe tests, +11 bot tests). `validate_handoff.py`: PASS.
- **Bot:** restarted by the autostart supervisor on the new code, still a single reader.
