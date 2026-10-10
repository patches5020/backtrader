# XLM/USD VP paper plans added (2026-10-10) -- commit 25aa7c6

## What changed
- **Per-symbol watcher.** `cdcx-cli/trading/alerts/xrp_vp_plan_watch.py --symbol XLM/USD` runs `xlm-bull-vp` /
  `xlm-bear-vp` with the same 12 requirements as XRP. XLM has its own `xlm_vp_plan_*` config/state/log/plan files.
  XRP (default) keeps its files, plan ids and commands. `--approve` infers the symbol from the plan id.
- **XRP unchanged (verified):** old and new code evaluated on the same fetched data gave identical pass/fail on all 12
  requirements and identical sizing previews for both plans; only the R12 label text changed.
- **Shared across symbols** (risk tightening, no parameter change):
  - one paper account: equity = $1,000 + realized P&L of all closed paper trades ($980 today);
  - at most one open paper trade across XRP/XLM (R12 and both approval conflict checks);
  - one approval at a time (shared `vp_plan_approve.lock`).
  The circuit breaker stays per symbol (cdcx).
- **Autostart:** one watcher process per symbol; the XRP pattern is end-anchored so the XLM process can't satisfy it.

## XLM arming (2026-10-10 15:22 UTC, expires 2026-10-17)
- Levels from closed 4H swings: high **0.19709**, low **0.19131** (both from the 2026-10-09 16:00 bar); VWAP anchor
  2026-10-09 16:00.
- Status: bull 2/12 (R7, R12), bear 1/12 (R12); live execution gate fails both ways (all TFs transitional).
- Note: XLM's range is tight (about 3%), so R6 can pass soon; R1-R5 still gate.

## Verified
- Offline 31/31 (9 new), E2E in separate processes on a temp ledger (XLM approval opens 1 XLM trade; XRP refused while
  it is open and vice versa; duplicate refused), 664 passed.
- Live: autostart task restarted; new supervisor (pid 73839) started the XLM watcher; XRP watcher restarted onto the new
  code; both resumed; first XLM progress alerts and the plan text delivered to Telegram.

Protected params: unchanged.
