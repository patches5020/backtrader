# VP-04P breakout -> pullback hold -> BOS (display, research only) + RQ8 pre-registration — 2026-10-22

Video setup 3 (Trading Notes "3 volume-profile setups"). The user approved the proposed values as drafted ("Yes to all").

- `cdcx/volume_profile/vp_breakout_pullback.py` (new): VP-04P, a variant beside VP-04 (VP-04 unchanged).
  - **Healthy break:** effort >= 1.5x the 20-bar average volume and result >= 1.0x ATR(11). ABSORPTION / NO SUPPLY / NORMAL breaks can't trigger.
  - **Pullback:** a low within 0.25 ATR of the broken edge.
  - **Hold:** fails on a close more than 0.25 ATR back inside, or a wick more than 0.5 ATR back inside.
  - **BOS:** a close more than 0.25 ATR beyond the highest high since the break.
  - **Expiry:** 12 bars.
- `vwap_confluence.py` / `htf_avwap.py`: the VP-04P row prints under VP-06 (LTF + HTF, cdcx-ai + cdcx-equity), `[research only, RQ8]`.
  The research-row formatter is picked by setup code (VP-06's frozen formatter is unchanged). `classify()` is unchanged.
- `cdcx/backtest/vwap_vp_rq8.py` (new):
  - Walk-forward VP-04P against the current VP-04 (RQ3 signals).
  - Protected trade model and costs (`vwap_vp_research.replay`).
  - Bootstrap seed 20261023, 97.5% CI.
  - One-at-a-time sensitivity grid (descriptive only).
- `tests/test_vp_breakout_pullback.py`: 16 tests (synthetic). Full suite 883 passed.
- `research_questions.md`: RQ8 block inserted after RQ7; the RQ7 text hash was verified unchanged. RQ9–RQ10 are still planned.
- Live XRP: 4H "VP-04P Breakout pullback FAILED VAH 1.35926 break: HEALTHY (effort 2.5x vol, result 1.6x ATR)".
- Protected params unchanged. RQ6/RQ7 frozen files untouched.
