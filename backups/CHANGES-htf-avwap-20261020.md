# HTF AVWAP context (cdcx-ai + cdcx-equity) — 2026-10-20

Analysis only. Adds an "HTF AVWAP CONTEXT" section, printed LAST (after AVP BULLISH REJECTION) in
`cdcx-ai --structure` and `cdcx-equity --timeframes ... --structure-report`. Never read by confluence,
entry checklist, no-trade gate, setup grade, sizing, journal or execution.

- Anchors = the matching AVP's own anchor bar (no separate AVWAP rule):
  - 4H / 1D / 1W: engine "Anchored Volume Profile" (`volume_profile_anchor`, lowest close of the last
    min(swing_lookback, n-1) bars). Taken from the TradeSignal (new additive fields
    `anchored_vp_anchor_ts`, `anchored_vp_poc/vah/val`); re-derived with the same call when that
    timeframe has no signal (cdcx-ai fetches 1W/1D/4H for the structure setup even if not requested).
  - 4H also: `avp_rejection` decline-start anchor (highest high of the last 100 closed bars).
- AVWAP = existing `anchored_vwap.anchored_vwap` unchanged (ohlc4, volume-weighted sigma, +/-1/2/3 sigma),
  CLOSED bars only; the forming bar is a "[provisional]" line only.
- Reports price vs AVWAP (above/below/at + sigma), RECLAIMED / LOST on the last closed bar, provisional
  crosses, same-anchor AVP POC side, strict BOS (0.25 x ATR), AVP rejection state, and confluence
  aligned / mixed / AVWAP only / unknown. Engine AVP levels include the forming bar -> confluence is tagged
  "[mixed basis: ...]". Missing timestamps, zero volume, anchor not in series / on the forming bar,
  stale data (> 2 periods; +3 days for equities) or any exception -> explicit unknown.
- Files: new `cdcx/htf_avwap.py`, `tests/test_htf_avwap.py` (28 tests); `cdcx/engine.py` (4 additive
  TradeSignal fields, not scored, not printed), `cdcx/cli.py` + `cdcx/cli_equity.py` (section appended,
  try/except, exit status unaffected), `tests/test_cli_structure_combination.py` (stub accepts `**kwargs`).
- Evidence: deterministic synthetic end-to-end reports, before vs after: cdcx-ai first 490 lines and
  cdcx-equity first 431 lines byte-identical (new section only appended). TradingView parity (1D, anchor
  2026-09-15, closed bars to 2026-10-19): VWAP 1.429089 vs 1.429100 from TV's own bars, 35 bars, 0 closes
  differ — data + math only, not TV's built-in AVWAP at this anchor.
- Full suite: 840 passed (812 before); 700 warnings, same count as before (pre-existing).
- Not changed: scoring, regime, structure setup, setup grade, VP-BOS, AVP rejection, LTF logic, risk,
  approvals, frozen RQ6 files. Protected params unchanged.
- Related (not in git, `trading/` is ignored): the "cdcx XRP 4H status" task prompt is now a closed-candle
  structure check (`trading/status/closed_swings.py`; old prompt kept as `xrp_4h_status_prompt.open_trade.md`);
  its "Working dir" line made headless runs `cd` first, which the allowlist denies — replaced by a
  run-commands-exactly rule, verified headless.
