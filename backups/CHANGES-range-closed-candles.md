# Range check on closed candles + XRP intraday range watcher (2026-10-14) -- commit a36e433

## Range check reads closed candles only (`cdcx/cli.py`, `cdcx/cli_equity.py`)
- New `cli._closed_bars(raw_data, timeframe)` drops the still-forming last candle (`no_trade_gate.last_bar_is_forming`).
- `_range_setup_inputs` uses it, so **`cdcx-ai --execute` range mode and the read-only RANGE MODE PREVIEW** both compute
  the range (fixed VP VAH/VAL/POC), RSI and the rejection pattern from closed bars; the cdcx-equity preview does too.
- Why: one forming 30m candle moved XRP/USD's range VAH 1.3833 -> 1.3748 (2026-10-14 ~09:00 UTC), and the RSI/pattern on
  a forming bar can still change.
- **Execution-gate input change, approved by the user 2026-10-14.** Unchanged: entry price (live), 1.5 x ATR stop,
  range TPs (POC / opposite edge), sizing, the trend/confluence path.
- Trade-off: a range setup can confirm up to one candle later.

## XRP intraday range watcher (`cdcx-cli/trading/alerts/xrp_intraday_range_watch.py` + `_config.json`)
Alert-only, send-only (`cdcx.telegram_send`), never trades. For the 2026-10-14 intraday paper plan; expires 2026-10-15 09:00 UTC.
| Alert | When |
|---|---|
| Edge zone reached | closed 5m bar trades into the outer 15% of cdcx's live closed-candle 30m range |
| Setup 4/4 | closed 30m candle passes all 4 `ranging_strategy` conditions |
| Range break / failed breakout | 30m close beyond plan range 1.3522 / 1.3833, then back inside |
| Data unavailable | 3 failed checks in a row (status UNKNOWN, no signal) |
Once per visit, re-armed when price returns to the middle; candle timestamps only advance on a successful fetch.
Started manually (not in `scripts/cdcx_autostart.sh`; that edit was blocked by the permission check).

## Tests
667 passed (3 new: `tests/test_range_closed_bars.py`); offline alert-path checks for the watcher passed; after the change
`cdcx-ai --timeframes 30m` and the watcher report the same range (1.3522 / 1.3700 / 1.3833 at 09:16 UTC).

Not included: an unrelated local edit to `trading/alerts/xrp_vp_plan_watch.py` (local-time display), left uncommitted.

Protected params: unchanged (execution-gate range input changed with user approval).
