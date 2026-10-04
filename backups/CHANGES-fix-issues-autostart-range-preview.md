# "Fix the issues" (2026-10-04) -- commits 137ab1f, c6b2aa6 (+ a15e764 / 2f4aeeb, already pushed)

The user chose all four: GitHub, leftovers, keep things running, analysis caveats.

## 1. GitHub (patches5020/backtrader): nothing to fix
- Secret scanning: 0 alerts. Dependabot and code scanning aren't enabled. No Actions runs.
- The "2 open issues" are draft PRs:
  - #2 is superseded: every file it adds already exists in master.
  - #4 is stale (old flat layout). The only unique parts are a Pine port of its strategy and a `tvremix_mcp` integration.
- Closing them is waiting on the user.

## 2. Leftovers: committed and pushed earlier (a15e764, 2f4aeeb)

## 3. Auto-start at logon (c6b2aa6)
- `scripts/register_cdcx_autostart.ps1` registers the per-user task `cdcx-autostart`:
  at logon +30 s, hidden (`conhost --headless`), no time limit.
- `scripts/cdcx_autostart.sh` is the supervisor:
  - starts the bot and the watcher only if they aren't running, checking real processes, so there's never a
    second Telegram reader;
  - re-checks every 60 s, with at most one restart per 5 min per service;
  - leaves the watcher stopped once it has finished;
  - keeps the WSL distro alive.
- Tested with fake services (start, restart after kill, no restart once finished).
- Registered and running. The supervisor did restart the real bot after it was stopped on purpose, 2026-10-04 05:33Z.
- `cdcx-cli/.gitignore` now ignores the nested `tradingview-mcp/` clone.

## 4. Analysis caveats
- **Range check only ran with --execute (137ab1f).** Plain runs now print a read-only RANGE MODE PREVIEW that shares
  `_range_setup_inputs` and `_range_entry_timeframe` with `--execute`. It writes no journal and opens no trade:
  verified live (journal file count and trade-log sha256 unchanged).
- **VP-BOS vs BOS STATE (137ab1f).** A one-line PENDING explanation prints only when a row is pending.
- **Stale TradingView indicator readings (tradingview-mcp repo, local branch `fix/study-values-last-bar`, 418920a).**
  `data_get_study_values` now also returns `last_bar_values` / `last_bar_time` from each study's series, independent
  of the crosshair. Unit tests: 89/91, the same as main (2 failures already on main). Not pushed; an upstream PR is
  waiting on the user.

Tests: 598 passed at the time (594 + 4). Protected params: unchanged.
