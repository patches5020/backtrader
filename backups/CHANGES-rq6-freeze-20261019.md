# RQ6 frozen + flaky-test fix + vwap-watch-1 live run — 2026-10-19

Commits: `f19e1c0` (tests), `80fc625` (RQ6 freeze). User approved all three steps. No gate, plan, sizing,
execution default or protected parameter changed.

- **Intermittent 1/789 failure (2026-10-18, heavy load):** most likely one of the two telegram-inbox import probes,
  not the vwap_watch probe the bundle blamed. Idle import times: `cdcx.telegram_inbox_mcp` 13 s,
  `cdcx.telegram_inbox_http` 10 s, `vwap_watch` 0.6 s; that run was ~7x slower, putting the first two at ~70-95 s
  against a 60 s limit. Both raised to 300 s (`tests/test_telegram_single_reader.py`,
  `tests/test_telegram_inbox_bridge.py`). Not reproduced: 4 concurrent full runs, 812 passed each. Without the
  original output this stays the most likely cause, not a confirmed one.
- **RQ6 FROZEN 2026-10-19T15:21:06Z** (`.ai/SHARED/research_questions.md`). FROZEN line records commit `f19e1c0` and
  SHA-256 of `vwap_watch.py` (8153255…0cdf), `vwap_watch_rq6.py` (34c8d30…0707) and the RQ6 block as committed in
  `f19e1c0` (d154c94…c631; reproducible with `git show f19e1c0:.ai/SHARED/research_questions.md`).
  Confirmatory S = 2026-10-21 00:00Z, E = 2026-12-16 00:00Z. One fetch + analysis at or after 2026-12-17 00:00Z;
  `vwap_watch_rq6.guard` refuses earlier. From now on `vwap_watch.py` and `vwap_watch_rq6.py` must not change
  before the analysis (a change = a new question).
- **vwap-watch-1 live:** first run 2026-10-19 15:23Z, XRP/USD + XLM/USD 1h, journal only (no `--notify`), BASELINE
  written to `cdcx-cli/trading/vwap_watch/`. Runner: `cdcx-cli/trading/status/vwap_watch_hourly.sh` (gitignored,
  in the zip). Windows task registration was NOT done by Claude (blocked by its permission classifier) — the user
  registers it.
