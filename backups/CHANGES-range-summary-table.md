# Summary table: RANGE / neutral for ranging rows — Change Summary

Date: 2026-09-29
Commit: ebbf867 (pushed to patches5020/backtrader master)
Repo touched: `cdcx-cli/` only. Protected parameters and execution gate unchanged.
Follows: dae2a2a (`DECISION: RANGE MODE`, see CHANGES-range-mode-decision-label.md).

## Problem
MULTI-TIMEFRAME SUMMARY printed the 0-100 trend label in the Signal column and
the bias derived from it (`_market_bias`) in the Market column. Live XRP/USD 1H
(ranging, direction +13) read `STRONG SELL / bearish`, contradicting the
report's `DECISION: RANGE MODE` and the range strategy's NO TRADE.

## Fix (display-only)
`cdcx/cli.py` and `cdcx/cli_equity.py` (kept in sync):
- `_summary_signal`: "RANGE" for a ranging row, else `signal.signal`.
- `_summary_market`: "neutral" for a ranging row, else `_market_bias`.
- `_print_summary_table` uses both.

NOT changed: `signal.signal`, `_market_bias` (both pinned by the protected
XRP baseline test), `classify_signal` thresholds (confluence gate). A
transitional row keeps its trend label (e.g. 4H STRONG SELL at -27);
reworking the thresholds needs user approval.

## Live XRP after the fix
```
1w  79.0   WATCH        neutral  ... no
1d  100.0  STRONG BUY   bullish  ... no
4h  0.0    STRONG SELL  bearish  ... no
1h  13.0   RANGE        neutral  ... yes
```

## Verification
- tests/test_report_range_decision.py: new test runs both tables
  (ranging row -> RANGE/neutral, transitional row unchanged; asserts
  signal.signal and _market_bias untouched). File now has 4 tests.
- Full suite: 546 passed (incl. XRP baseline test).
