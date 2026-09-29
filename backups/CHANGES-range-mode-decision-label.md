# Ranging DECISION label (RANGE MODE) — Change Summary

Date: 2026-09-29
Commit: dae2a2a (master, not pushed)
Repo touched: `cdcx-cli/` only. Protected parameters and execution gate unchanged.

## Problem
Live `cdcx-ai --symbol XRP/USD --timeframes 1w,1d,4h,1h --structure --execute --balance 1000`:
the 1H timeframe (regime RANGING, direction +13, bias BULLISH) printed
`DECISION: STRONG SELL` / `DECISION CONFIDENCE: 74.0%`, while the RANGING STRATEGY
SETUP said `RANGE TRADE: NO TRADE`.

Cause: `classify_signal` maps the signed indicator sum, clamped to 0-100, where
< 20 = STRONG SELL. A weak +13 therefore labels as STRONG SELL. For a ranging
regime `format_report` printed that trend label as the DECISION, but in range
mode the trade call belongs to the range-boundary strategy.

## Fix (display-only)
`cdcx/engine.py` `format_report`: when regime is `ranging` and there is no
execution_reason (no R:R veto), print
```
DECISION: RANGE MODE
REASON: Ranging regime -- the trade call comes from the RANGING STRATEGY SETUP, not the trend score.
TREND-SCORE SIGNAL: <signal>  (context only, not a trade call in range mode)
```
and drop DECISION CONFIDENCE (it measured the trend label). A ranging R:R veto
still prints `DECISION: NO TRADE`. Trending/transitional output unchanged.

NOT changed: `execution_signal` / `decision` (feed backtest regime gate,
backtrader strategy, cdcx-equity direction), `classify_signal` thresholds
(feed confluence gate — protected; needs user approval).

## Known remaining
MULTI-TIMEFRAME SUMMARY `Signal` column still shows the trend label
(1H STRONG SELL at +13, 4H STRONG SELL at -27). Options: relabel ranging rows
as RANGE (display-only), or rework classify_signal thresholds (protected).

## Verification
- tests/test_report_range_decision.py: 3 new tests (range mode shown, R:R veto
  still NO TRADE, non-ranging unchanged; asserts execution_signal untouched).
- Full suite: 545 passed (incl. XRP baseline test).
- Live re-run: 1H now `DECISION: RANGE MODE`; 1W/1D/4H still NO TRADE (transitional).
- Telegram bot `extract_decisions` parses `DECISION:` lines -> shows `RANGE MODE`.
