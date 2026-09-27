# cdcx Strategy Spec (shared by ChatGPT and Claude Code)

Source of truth is the code in `cdcx-cli/cdcx/`. This file explains it; `risk_parameters.json` pins
the protected numbers and `validate_handoff.py` checks them against the code.

## Tools
- `cdcx-ai` — crypto via Crypto.com (`cdcx/cli.py`). `cdcx-equity` — stocks/ETFs via Robinhood or
  Webull (`cdcx/cli_equity.py`). Same engine, same report format.
- Standard analysis: `--timeframes 1w,1d,4h,1h --structure` (cdcx-ai) or `--structure-report` (cdcx-equity).

## Decision pipeline (in order — each stage can only refuse, never force a trade)
1. **Per-timeframe engine** (`engine.py`) — 13 scored components (EMA, ATR, ADX, Bollinger, candles,
   RSI, Fib retracement/extension, FVG, fixed/anchored volume profile, market structure, R:R).
2. **Regime** (`regime.py`) — TRENDING / RANGING / TRANSITIONAL per timeframe. TRANSITIONAL = NO TRADE.
3. **Confluence** (`confluence.py`) — at least 2 of 1H/4H/1D/1W must agree on direction.
   Transitional timeframes are excluded, so a NO TRADE never adds bullish or bearish weight.
4. **Entry checklist + entry location** (`entry_checklist.py`, `entry_location.py`).
5. **No-trade filter / final gate** (`no_trade_filter.py`, `no_trade_gate.py`) — R:R >= 2, risk <= 2%,
   stop and all four TPs present, fresh data, no duplicate order, withdrawal permission attested.
6. **Circuit breaker** (`circuit_breaker.py`) — 3 losses in a row or 10% drawdown halts trading.
7. **Execution** — PAPER by default. A real order needs `TRADING_MODE=LIVE` + `--live` + a human YES.

## Risk model (protected)
Entry = current price; stop = 1.5 x ATR; TP1–TP4 = 2.2 / 2.6 / 3.2 / 4.5 R, closing 25% each;
2% account risk per trade.

## Design principles (user's standing rules)
1. **NO TRADE = insufficient confirmation, never a bearish signal.**
2. **Scenarios are conditional pathways, not predictions.** The engine never picks which will happen.
3. **ATR is a confirmation component, never a standalone entry trigger.**
   Valid: ATR contraction -> expansion + BOS + multi-timeframe agreement. Invalid: ATR expansion -> trade.
4. **Additive only.** New ideas (volume profile, Trader Dale concepts) layer on top of the regime and
   confluence gates; they don't replace them, and they don't touch entry / SL / TP / R:R / sizing.
5. Keep the path legible: directional bias -> setup formation -> confluence -> execution permission.

## Break of structure and VP-BOS (advisory, `bos_state.py`, `vp_bos.py`)
- **Temporal causality invariant:** a bar can only break a swing that already exists —
  `break_index > swing_index`. Tested; must never regress (fixed in commit b021961).
- **Legitimate break:** a CLOSED candle beyond the swing by 0.25 x ATR. Smaller pokes are a
  raw-flag note, never a state. The still-forming candle is ignored.
- States: **NONE** (no legitimate break) · **BOS-PENDING** (break, volume acceptance not confirmed) ·
  **VP-BOS** (break + acceptance) · **BOS-FAILED** (break, then closed back through).
- Acceptance: at least 3 closed bars since the break with 2/3 closing beyond the level (required),
  plus one of: post-break POC beyond the level, POC migration > 0.5 x ATR in the break direction,
  or a held retest.
- VP-BOS is informational only. No gate reads it. Whether it ever should is an open backtest question.

## Data handling
- Crypto.com timestamps are milliseconds; Robinhood/Webull are seconds (`no_trade_gate.timestamp_to_seconds`).
- Equity weekly bars are stamped Monday 00:00 UTC and close Friday 16:00 New York time.
- Robinhood weekly bars are built from daily bars (its native weekly series lags a week).

## Regression guards
- `tests/test_baseline_xrp_mtf.py` replays a frozen XRP snapshot and pins the baseline verdict
  (1W trending, 1D/4H/1H transitional, confluence 1/4, NO TRADE) and the risk model.
  Changing its expectations is the user's decision, never a side effect.
