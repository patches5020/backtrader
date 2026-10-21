# HTF AVWAP CONTEXT: LTF-style setup block (VP-01..VP-05 + DECISION) — 2026-10-21

Added at the user's request, with nothing removed ("Add not to delete the type of info LTF format to the info of the
HTF format! I need the VP-01-04, etc! Also to CDCX-EQUITY"). Every existing HTF line (anchor, AVWAP, bands,
closed/forming close, same-anchor AVP, strict BOS, Confluence) is unchanged. Under each valid
4H/1D/1W context there is now the same block the PREV-DAY AVWAP + AFVP (LTF) section prints:
VP-01 POC reaction .. VP-05 band exhaustion, the evidence families (vwap / volume / structure / price_action / cdcx HTF),
Context (closed bars), DECISION / STATUS / Next / Invalidates, and `Execution: NOT AUTHORIZED (analysis only)`.

- `cdcx/volume_profile/vwap_confluence.py`: the setup/evidence/decision lines are moved into
  `format_setup_lines()`, which the LTF section and the HTF section both call. The LTF output is unchanged (its tests pass), and
  `classify()` is untouched.
- `cdcx/htf_avwap.py`: `_attach_setups()` runs `vwap_confluence.classify` unchanged on that context's own AVWAP
  and its same-anchor AVP POC/VAH/VAL. The LTF "today" window becomes the last `VP_WINDOW_BARS` (6) closed bars of
  the timeframe, and the wording reads "in the last 6 4H bars" and "AVP value area" instead of "today" / "prior". `build_htf_avwap()`
  takes `symbol` and works out cdcx's 2-of-4 HTF direction once (`htf_direction`, the same filter as the LTF section) and the
  Context once per timeframe. If there are no AVP levels it prints an explicit `VP-01..VP-05: unknown`.
- `cdcx/cli.py`, `cdcx/cli_equity.py`: pass `symbol`. cdcx-equity uses the same renderer.
- Tests: 4 new in `tests/test_htf_avwap.py`. Full suite: 848 passed (pre-existing 700 warnings).
- Live: `cdcx-ai --symbol TRUMP/USD --timeframes 1w,1d,4h,1h --structure` -> e.g. 4H cdcx AVP:
  "VP-01 POC reaction CONFIRMED bullish reaction at 1.79446", "DECISION: CANDIDATE (bullish)", "STATUS: SETUP DEVELOPING".
  `cdcx-equity --source robinhood --symbol AAPL --timeframes 1w,1d,4h,1h --structure-report` -> 10 VP-01 rows across the HTF
  section, e.g. 4H "VP-04 Value-area breakout FAILED broke 344.7, closed back inside (sweep)". (No Webull keys in .env.)
- Display only: not read by the gate, the grade, sizing or --execute. RQ6 frozen files are untouched. Protected params are unchanged.
