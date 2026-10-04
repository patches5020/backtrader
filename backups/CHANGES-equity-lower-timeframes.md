# cdcx-equity: timeframes below 1h + advisory sections (2026-10-04) -- commit 8c60342

## Request
"Update cdcx-equity", with the same lower-timeframe and advisory work as cdcx-ai.

## Changes
- **Timeframes**

  | Source | Native | Built | Not available |
  |---|---|---|---|
  | Robinhood | 5m, 10m (span "week", ~1 week of history) | 15m and 45m from 5m, 30m from 10m | 1m |
  | Webull | 1m, 5m, 15m, 30m | 10m from 5m, 45m from 15m | — |

- **`cdcx/exchange/equity_bars.py` (new)**
  - Session-anchored bar builder: groups start at each trading day's first bar (9:30 ET).
  - A session's short last bar is kept, like TradingView.
  - Works with timestamps in seconds or milliseconds.
- **`cdcx/cli_equity.py`**
  - VP-BOS and AVP include requested lower timeframes (extra rows; the 2-of-4 count is unchanged).
  - Read-only RANGE MODE PREVIEW for every ranging timeframe, from bars already fetched. Advisory only:
    cdcx-equity's `--execute` has no range mode.
  - Help text lists the lower timeframes.
- **`cdcx/cli.py`**: `_range_inputs_from_data` split out of `_range_setup_inputs` (shared; behaviour unchanged).

## Protected
Confluence and `--execute` still use only 1h/4h/1d/1w. Protected params: unchanged.

## Verification
- Live Robinhood SPY `--timeframes 5m,15m,45m,1h,4h,1d,1w --structure-report`:
  - bar counts: 5m 200, 10m 195, 15m 130, 30m 65, 45m 45;
  - session times: 45m bars at 9:30, 10:15, …, 15:30;
  - a built 45m bar equals its 5m ×9 exactly;
  - all advisory sections show the lower timeframes.
- Webull: not configured here (no app key), so unit tests only.
- Tests: **650 passed** (+11). `test_baseline_xrp_mtf.py` 6 passed. `validate_handoff.py`: PASS.
