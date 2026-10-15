# VAH red, VAL green in cdcx-ai and cdcx-equity (2026-10-15) -- commit 4ad0d88

User's colour choice. Display only: no level, gate, signal or protected parameter changes.

| Where | Before | Now |
|---|---|---|
| MARKET STRUCTURE report (`structure_report.py`, cdcx-ai and cdcx-equity) | plain `VAH:` / `VAL:` | **VAH red**, **VAL green**, label "(value area high, red)" / "(value area low, green)"; the RANGE line too |
| STRUCTURE map (`structure_levels.py`, cdcx-ai) | "Resistance (green)" / "Support (red)" -- inverted | "Resistance / VAH (red)" / "Support / VAL (green)", coloured |
| AVP section (`avp_rejection.py`) | plain | VAH red, VAL green |

- New helpers `colorize_vah` / `colorize_val` in `cdcx/utils/color.py`; same rules as the regime colours (colour only
  on a TTY, `NO_COLOR` disables, `FORCE_COLOR=1` forces). Telegram/log output stays plain text with the labels.
- `cdcx-cli-plugin/` (packaged copy) not changed.

## Tests
670 passed (3 new in `tests/test_vah_val_color.py`); handoff validation PASS. Live cdcx-ai XRP/USD 1H output shows the
red/green codes. cdcx-equity uses the same `format_structure_report`; a live run needs Robinhood app approval
(Webull OpenAPI keys are not set).

Not included: unrelated local edit to `trading/alerts/xrp_vp_plan_watch.py`.
