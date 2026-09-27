# VP-BOS (Volume Profile Break of Structure) — Change Summary

Date: 2026-09-27
Commit: 7d0934a (pushed to patches5020/backtrader master)
Repo touched: `cdcx-cli/` only. Advisory/informational — no gate, entry,
SL, TP, R:R or sizing change.

## Definition
- Raw BOS = structural event (market_structure.py flag)
- VP-BOS = CLOSED break of a swing level + volume-profile acceptance beyond it
- BOS-FAILED = break that closed back through the level (rejection)
- Volume is never required to detect the raw BOS.

## Acceptance evidence (closed bars only; forming candle dropped)
- E1 sustained (required): 3+ closed bars since break, >= 2/3 closing beyond
- E2 new HVN: post-break bars' own volume-profile POC beyond the level
- E3 POC migration: rolling POC moved > 0.5x ATR in the break direction
- E4 retest held (existing bos_state)
- VP-BOS = E1 and (E2 or E3 or E4)

## States
VP-BOS-BULL/BEAR · BOS-RETEST · BOS-UNCONFIRMED · BOS-FAILED ·
BOS-BULL/BEAR (raw flag, no closed break) · NONE

## Files
- New `cdcx/vp_bos.py`
- `cdcx/cli.py`: VP-BOS section after SETUP GRADE (cdcx-ai --structure)
- `cdcx/cli_equity.py`: VP-BOS section after VP hierarchy (--structure-report)
- New `tests/test_vp_bos.py` (7 tests incl. guard: no gate/risk file imports vp_bos)
- `tests/test_baseline_xrp_mtf.py`: pins VP-BOS rows for the XRP baseline

## Notes
- Timestamps: detects ms (Crypto.com) vs seconds (Robinhood).
  engine.py's own forming-bar check assumes ms — pre-existing, not changed.
- Thresholds (3 bars, 2/3, 0.5x ATR) are first-pass defaults; whether
  VP-BOS adds edge over raw BOS is an open backtest question.
- Full suite: 405 passed.
