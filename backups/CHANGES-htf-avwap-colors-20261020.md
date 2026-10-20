# HTF AVWAP context level colours (cdcx-ai + cdcx-equity) — 2026-10-20

Display only, at the user's request. In the "HTF AVWAP CONTEXT -- <symbol> (analysis only, AVP-matched
anchors)" section: POC yellow, VAH red, VAL green (the existing colorize_poc/vah/val helpers already used
by MARKET STRUCTURE, STRUCTURE map, AVP rejection and VWAP confluence), and the AVWAP value blue
(new `BLUE` + `colorize_vwap` in `cdcx/utils/color.py`).

- One shared renderer (`htf_avwap.format_htf_avwap_section`) -> cdcx-ai `--structure` and
  cdcx-equity `--structure-report` both get the colours.
- Same TTY / NO_COLOR / FORCE_COLOR rules as every other colour: piped output, logs and Telegram text
  stay plain (no ANSI codes), so saved reports and tests are unchanged.
- Files: `cdcx/utils/color.py`, `cdcx/htf_avwap.py`, `tests/test_htf_avwap.py` (+3 tests: colours forced,
  plain without colour, equity path coloured).
- Evidence: live `FORCE_COLOR=1 cdcx-ai --symbol XRP/USD --structure` -> AVWAP ESC[34m, POC ESC[33m,
  VAH ESC[31m, VAL ESC[32m. cdcx-equity live run not possible here (Webull keys unset, Robinhood login
  failed) -> verified through the mocked equity report test.
- Full suite: 843 passed (840 before); 700 warnings (pre-existing).
- Not changed: any calculation, gate, grade, sizing or execution. Protected params unchanged.
