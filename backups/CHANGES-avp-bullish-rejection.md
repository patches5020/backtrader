# AVP Bullish Rejection (paper / analysis, stage 1) — Change Summary

Date: 2026-09-28
Commit: c5bec3e (pushed to patches5020/backtrader master)
Repo touched: `cdcx-cli/` only. Protected parameters unchanged; not read by any gate.

## Definition
Price trades into/below an Anchored Volume Profile level (VAL or POC), fails to
hold below it, and CLOSES back above it; the next closed candle must hold the level.
- NONE · PENDING (reclaim on newest closed candle) · CONFIRMED (next candle held,
  no close since lost it) · FAILED (closed back below) · REJECTED (rejection low
  at/below the 1.5x ATR stop — stop never widened, no paper trade).
- Closed candles only; an intrabar wick never counts.

## Decisions (user)
- AVP anchor: start of the decline = top the current down-move started from
  (highest high of the last 100 bars). First version ("last swing high before
  the lowest low") anchored live XRP 4H at a mid-September high — fixed; 4H now
  anchors at the 1.6577 top.
- Wide structural stop: REJECT the setup (protected 1.5x ATR stop is never widened).
- TP ladder: the protected 2.2 / 2.6 / 3.2 / 4.5 R (25% each). The brief's
  "TP4 ~ 2.2R" did not match the system and was not used.

## Evidence (reported, not required)
Volume >= 1.0x trailing average · close in upper 40% of the reclaim candle ·
RSI turning up · AVP POC not lower · failed bearish VP-BOS · held retest.

## Paper plan / outcome
Entry: retest close if a retest held, else the hold candle's close.
Stop/TPs/close %: risk.resolve_atr_multiplier / resolve_tp_ratios / resolve_tp_close_pcts.
simulate_outcome replays trade_manager rules G (TP1 -> BE), I (20% giveback exit),
H (TP2 -> stop TP1, TP3 -> stop TP2), TP4 closes rest; stop assumed first when a
bar touches both.

## Where it shows
cdcx-ai --structure and cdcx-equity --structure-report (after the VP-BOS table),
Telegram bot /analyze (bot restarted, still sole reader).

## Live XRP at 1:19 AM CDT
4H AVP POC 1.52459 / VAH 1.57612 / VAL 1.49024 -> PENDING at VAL 1.49024.
1H AVP POC 1.56652 / VAH 1.59312 / VAL 1.51998 -> FAILED (closed back below, 1.5079).

## Validation roadmap (user's plan)
1 analysis signal (this) -> 2 historical backtest (1H/4H separately; separate from
POC Bounce / VA Reversal / VP-BOS; fees+slippage) -> 3 out-of-sample -> 4 live paper
-> 5 only then consider the trade gate. Never override NO TRADE meanwhile.

## Tests
18 in tests/test_avp_rejection.py (mutation-checked: 2.0x stop, removed FAILED
check). Full suite 506 passed; handoff validator PASS.
