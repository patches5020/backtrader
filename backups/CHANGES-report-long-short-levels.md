# CDCX-AI TRADE ANALYSIS: Long/Short levels beside the existing ones (2026-10-03) -- commit 3c83ab6

## Request
Keep every existing number in the CDCX-AI TRADE ANALYSIS block and add Long and Short entry, stop, breakeven,
TP1–TP4 and R:R alongside them. Additive, output only.

## Decision (user, 2026-10-03)
Long/Short TPs use the **protected 2.2 / 2.6 / 3.2 / 4.5 R ladder**, the same as the existing TPs, not 1R/2R/3R/4R.
1R/2R/3R/4R would have contradicted the protected TP ratios and put TP1 below the 1:2 minimum R:R.

## Changes
- `cdcx/engine.py`
  - New `TradeSignal.directional_levels` (display only):
    `{"long"|"short": {entry, stop, breakeven, take_profits, rr}}`.
  - It's built by calling the engine's own `_build_plan("up")` / `_build_plan("down")` on the same snapshot, so it
    uses the same entry, ATR, 1.5× multiplier, `tp_ratios` and `tp_mode` (ATR or structural) as the existing levels.
  - Breakeven = entry: where the trade manager moves the stop once TP1 is hit (rule G).
- `format_report`
  - Every existing line is printed verbatim and in its original order.
  - `  Long:` / `  Short:` lines are added under Entry, Stop Loss, each TP1–TP4 and Risk/Reward.
  - A new `Breakeven:` line, also with its Long/Short pair.
  - cdcx-equity shares `format_report`, so it gets the same additive lines.
- **New** `tests/test_report_directional_levels.py`, 10 tests:
  - the 1.5× ATR math and the protected ladder on both sides;
  - the side cdcx picked equals the existing levels exactly;
  - existing lines are kept verbatim and in order, each followed by its Long/Short pair;
  - no Long/Short lines when the field is empty;
  - structural TP mode;
  - nothing outside engine.py reads the field.

Not touched: scoring, signals, regime, confluence, gates, execution, risk sizing, trade_manager, every protected
parameter, and the XRP baseline verdict.

## Verification
- Live `cdcx-ai --symbol XRP/USD --timeframe 1h`. The 1H EMA was bearish, so the existing levels are the short side,
  and the Short lines equal them.
  - Long stop 1.46852 = 1.486 − 1.5 × 0.011653.
  - Long TP1 1.52445 = 1.486 + 2.2 × 0.01748.
- `python -m pytest -q`: **594 passed** (584 + 10 new); `tests/test_baseline_xrp_mtf.py` 6 passed.
- `python .ai/validate_handoff.py`: PASS (protected parameters match the code).
