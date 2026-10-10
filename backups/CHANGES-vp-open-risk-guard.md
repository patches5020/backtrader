# VP plans: calculated open-risk guard + real-path sizing test (2026-10-10) -- commit c0f5849

Code-only safeguards before any plan approval. No plan activated, no setting changed; all plans monitor-only.

## Open-risk guard (`xrp_vp_plan_watch.py`; R12 and `--approve`)
- Sums each open paper trade's **remaining planned loss** (remaining size x distance from entry to its current stop;
  0 once the stop is at/through breakeven) across all symbols, adds the proposed trade's risk (equity x risk_pct),
  refuses above `max_open_risk_pct` (2%) of paper equity. Realized losses shrink equity, so the cap shrinks with them.
- **Fails closed** on missing/NaN/invalid stop, entry or size, and on a stale open trade (no `--update-trades` in 6h).
- Re-checked **under the shared approval lock** immediately before execution; a recorded risk above plan is logged.
- A stop is not a loss cap: gaps/slippage (cdcx rule J) can exceed planned risk; correlation between XRP and XLM is not
  limited separately (that would be a strategy change needing approval).

## Real-path test (`check_vp_plan_e2e.py REAL_SIZING=1`)
cdcx's real `risk.build_position_plan` + real `_open_trade_and_maybe_go_live` on a temp ledger; every public
`live_execution` function raises if called (tripwire).

| Step (temp equity $980) | Result |
|---|---|
| XRP approval | risk $9.80 = 1%; 535.519 x 0.0183 = $9.80 = recorded risk_amount |
| XLM approval | risk $9.80; 5833.33 x 0.00168 = $9.80; guard $9.80 + $9.80 = $19.60 vs cap $19.60 -> allowed |
| Second XRP | refused (one per coin) |
| XLM while XRP holds the lock | refused; 1 trade recorded |
| Tripwire | never fired |

Offline 43/43 (10 new guard checks); 664 passed; real ledger and state untouched (hash checked).
Both watchers restarted onto the new code (16:20 UTC).

## Market note at the time
The XLM 4H candle closing 16:00 UTC finished above 0.19709: xlm-bull-vp 5/12 (R5, R6, R7, R9, R12); xlm-bear-vp
invalidated (alert sent). Nothing executed.

Protected params: unchanged.
