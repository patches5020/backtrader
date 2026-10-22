# VP-01F first-touch POC filter (display, research only) + RQ9 pre-registration + RQ10 plan — 2026-10-22

Video setup 1 (Trading Notes "3 volume-profile setups"). The user approved the proposed values ("Yes to all").

- `cdcx/volume_profile/vp_first_touch.py` (new): VP-01F, a filter on the existing VP-01 reaction (VP-01 unchanged).
  - **F1:** the prior close was outside the value area.
  - **F2:** first touch of the POC zone (POC +/- 0.25 x ATR(11)) today.
  - **F3:** reaction volume > the previous bar's.
  - **PASS:** all three.
  - The reaction scan mirrors `_level_reaction`, checked on 300 random cases.
- `vwap_confluence.py` / `htf_avwap.py`: the VP-01F row prints under VP-04P (LTF + HTF, cdcx-ai + cdcx-equity), `[research only, RQ9]`.
  `classify()` is unchanged.
- `cdcx/backtest/vwap_vp_rq9.py` (new): RQ5-style design.
  - The VP-01 baseline trades are split PASS / FAIL, plus the filtered strategy re-replayed.
  - Seed 20261024, 97.5% CIs.
  - F1/F2/F3 alone are descriptive only.
- `tests/test_vp_first_touch.py`: 10 tests (synthetic). Full suite 894 passed.
- `research_questions.md`: RQ9 block, and the RQ10 plan (a resolution AND source-bar calculation study; RQ4 showed 400 rows on 1H is
  unstable). The RQ7/RQ8 text hashes were verified unchanged.
- Protected params unchanged. RQ6/RQ7/RQ8 frozen files untouched.
- **RQ9 FROZEN 2026-10-22T14:43:42Z** against commit 762fc0e, with `test_rq9_frozen_files_unchanged` guarding both files. S = 2026-10-24, E = 2027-04-24;
  the analysis runs once, on or after 2027-04-25:
  `python -m cdcx.backtest.vwap_vp_rq9 --fetch DIR --start 2026-10-24 --end 2027-04-24`, then the same with `--data DIR`.
