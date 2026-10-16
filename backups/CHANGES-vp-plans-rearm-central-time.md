# VP plan watcher: Central time + XRP re-arm + XLM one-shot re-arm (2026-10-16) -- commit d01b892

No requirement, gate, sizing or protected parameter changed.

## Watcher display (`trading/alerts/xrp_vp_plan_watch.py`)
- Times in messages show UTC plus US Central, e.g. `2026-10-11 07:00Z = Oct 11 2:00 AM CDT`. Stored config values
  stay pure UTC (`utc_only` for swing timestamps).
- R3 detail now says "checklist passed, but blocked by R2 (regime)" instead of a bare "all passed" when R2 fails.

## XRP/USD plans re-armed 2026-10-16 14:31Z (arming 202610161431, expires 2026-10-23 14:31Z)
- Previous arming expired 2026-10-16 09:21Z. New levels from closed 4H swings: swing high 1.3462 (10-15 16:00Z),
  swing low 1.3222 (10-16 00:00Z), VWAP anchor 2026-10-16 00:00Z (1.3365). Retest margin 0.0026.
- At arming: bull 2/12 (R7, R12), bear 1/12 (R12); 1H RANGING, so R1-R3 fail on both sides.
- Paper equity $960 (cdcx trade 7315265d stopped out 2026-10-15 15:00Z, -$20); circuit breaker 2/3 losses.

## XLM/USD one-shot re-arm (`trading/alerts/rearm_xlm_vp_once.sh`)
- Waits for the current XLM arming to expire (2026-10-17 15:22:50Z) and the watcher to log "watcher finished",
  then runs `--symbol XLM/USD --arm`; cdcx_autostart.sh restarts the watcher. Log: `rearm_xlm_vp_once.log`.
- Started detached (setsid nohup). If WSL restarts before then, it does not survive -- re-arm manually.

## Tests
670 passed; handoff validation PASS.
