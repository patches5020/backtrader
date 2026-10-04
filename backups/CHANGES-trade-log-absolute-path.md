# Trade log: absolute path + stray log archived (2026-09-30)

## Problem
`TRADE_STATE_PATH=cdcx_trades.json` in `cdcx-cli/.env` was relative, so the paper-trade log
landed in whatever directory cdcx was run from. A second log had built up in
`cdcx-cli/tradingview-mcp/cdcx_trades.json` that cdcx was no longer reading.

## Changes
1. **`cdcx-cli/.env` line 75** (gitignored, not committed):
   `TRADE_STATE_PATH=/mnt/c/Users/patch/my-trade/backtrader-repo/cdcx-cli/cdcx_trades.json`
   No other `.env` line changed (verified by hashing the other lines before and after).
2. **Stray log archived** (moved, not deleted):
   `cdcx-cli/tradingview-mcp/cdcx_trades.json` ->
   `backups/archived-trade-logs/cdcx_trades.stray-tradingview-mcp.20260930.json`
   sha256 `685a58e908b46cda9ebfea498698353d33466ba2e54f2a8812a08abb307bca8d` (same before and after the move).
   Contents: 3 stale "open" trades that cdcx wasn't tracking -- XRP/USDT long (Aug 20, $10k account),
   SPCX short (Sep 18), and a zero-size duplicate of the XRP/USD long.

No code changes. Protected risk parameters untouched.

## Canonical log (unchanged)
`cdcx-cli/cdcx_trades.json` -- 1 open trade: XRP/USD long `5a75fd5f`, entry 1.532, $1,000 account.

## Verification
- `settings.trade_state_path` resolves to the absolute path when run from `cdcx-cli/` and from
  `cdcx-cli/tradingview-mcp/`.
- `cdcx-ai --list-trades` from `/tmp` shows trade `5a75fd5f`, and no new log file was created there.
- `python -m pytest -q` in `cdcx-cli/`: **546 passed**. The canonical log's sha256 was the same before
  and after the run, so the tests didn't write to it.

## Caveat
`python -c "..."` run from a directory outside `cdcx-cli/` doesn't find `.env` (dotenv searches from
the current directory in that mode), so it falls back to the default relative path. The installed
entry points (`cdcx-ai`, `cdcx-telegram`, `python -m cdcx...`) do find it. If this ever matters,
make the default in `cdcx/config.py` absolute (anchored to the package directory). That would be a
code change and needs tests.

## Rollback
Set `.env` line 75 back to `TRADE_STATE_PATH=cdcx_trades.json`, and move the archived file back if needed.
