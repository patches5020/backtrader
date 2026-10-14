# XRP bounce-zone rejection watcher (2026-10-14) -- commit 359f6ac

## `cdcx-cli/trading/alerts/xrp_bounce_zone_watch.py` + `xrp_bounce_zone_config.json` (new)
Alert-only, send-only monitor of the 1.3316-1.3385 resistance (broken 1H VAL .. bottom of the 1H bearish FVG
1.3385-1.3479). It sits below the anchored VWAP (~1.356), so `xrp_vwap_retest_watch.py` cannot see it.

| Check | Rule (closed candles only) |
|---|---|
| Z1 touch | a 5m candle after arming (19:00Z) reaches >= 1.3316 |
| Z2 rejection | it closes back below 1.3316 and close < open |
| Z3 confirmation | a later 15m close below the rejection candle's low |
| Z4 no reclaim | no 5m close above 1.3385 since the rejection |
| Invalidation | 15m close > 1.3479 -> one alert, watcher stops |

- Alerts: touch (re-arms after 1h untouched), rejection heads-up, CONDITIONS MET once per rejection and only if the
  confirming 15m close is <= 15 min old (older -> logged as stale), invalidated, DATA UNAVAILABLE after 3 failures.
- Levels reuse the VWAP watcher's `levels()`: entry = confirming 15m close, stop = entry + 2.0x ATR(5m, 11)
  (user-chosen; cdcx protected default 1.5x), TP1-4 2.2/2.6/3.2/4.5 R, breakeven after TP1. Each alert also prints the
  rejection high, because an ATR stop can sit inside the tested zone (structure vs ATR protection). Rule unchanged.
- Expires 2026-10-15 09:00 UTC. No order code; cannot touch cdcx gates.

## `scripts/cdcx_autostart.sh`
Adds a `start_once` entry, skipped once the log ends "watcher finished" (expired/invalidated).

## Tests
667 passed; handoff validation PASS; `bash -n` OK; `--once` dry run; replay on a past zone (1.3300-1.3340 from 16:00Z)
found the 17:55Z rejection + 15m confirmation and correctly marked it stale.

Protected params, risk settings and the existing watchers: unchanged. Not included: unrelated local edit to
`trading/alerts/xrp_vp_plan_watch.py`.
