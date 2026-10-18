# vwap-watch-1 shadow watcher + RQ6 analysis script — 2026-10-18

Commit: `72e247b` (monitor-only research code; no gate, plan, sizing, execution default or protected parameter changed).

- `cdcx/volume_profile/vwap_watch.py` (new): closed-bar AVWAP early-warning watcher, per direction
  IDLE → WATCH → SETUP → CONFIRMATION_CANDIDATE / INVALIDATED / EXPIRED, built on the existing
  `vwap_confluence` classifier (no duplicate calculations, no composite score). First-run BASELINE (not alerted),
  catch-up up to 48 missed bars (49+ re-baselines), append-only JSONL journal with dedup keys, atomic state file,
  at-least-once delivery (notify → journal → state). Every record: `execution_authorized: false`, no position read.
  Not scheduled. Run: `python -m cdcx.volume_profile.vwap_watch --symbol XRP/USD --timeframe 1h` (in `cdcx-cli/`).
- `vwap_confluence.py`: `VwapVpResult` gains `bos_state`, `bos_direction`, `bos_level` (read-only fields).
- `cdcx/backtest/vwap_watch_rq6.py` (new): RQ6 sections 3–10. Refuses any fetch/run while RQ6 is not FROZEN, and the
  confirmatory period before E + 24 h. `--freeze-hashes` prints the SHA-256 values for the FROZEN line.
  Tested on synthetic data only; never run on real or locked data.
- `.ai/SHARED/research_questions.md`: RQ6 draft rev 3 — **NOT FROZEN**. Clarified: pooled retest uses each event
  type's own rule; 2-day-block sensitivity is a separate seeded run.
- Tests: `test_vwap_watch.py` (34), `test_vwap_watch_rq6.py` (23); full suite 812 passed; handoff PASS.
  Earlier heavily-loaded run: 1 failed / 788 (unidentified, not reproduced) — kept in the record.

Still not done (needs the user's go-ahead): freeze RQ6, schedule the watcher, any run on real data.
