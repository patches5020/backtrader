# HTF AVWAP context for short-history symbols (SPCX/USD) — 2026-10-23

The user reported: "There is no HTF AVWAP/AVP CONTEXT on SPCX/USD. Apply to all symbols on both CDCX-AI/CDCX-EQUITY".

- **Cause:**
  - SPCX/USD has only 22 1W candles (listed around June 2026); the 1W structure map needs 34 for ADX(17).
  - `_print_structure_setup_section` returned early on that failure, so the HTF AVWAP context, printed last, was skipped.
- **cdcx-ai (`cdcx/cli.py`):**
  - When the 1W/1D/4H/1H trigger can't run, `_print_htf_avwap_fallback` prints the HTF AVWAP context from cached or raw bars, with a note.
  - The trigger, grade, VP-BOS/AVP sections and gates are unchanged; the trigger still fails closed.
  - The section print was extracted into `_print_htf_avwap`.
- **cdcx-equity (`cdcx/cli_equity.py`):** a requested 4H/1D/1W whose analysis failed is re-fetched as raw bars for the HTF AVWAP context only.
- Live SPCX/USD: 4H (both anchors), 1D and 1W contexts now print with the setup block.
- **Tests:** 2 new in `test_htf_avwap.py` (both fail without the fix). Full suite 926 passed.
- Protected params unchanged. RQ6–RQ12 frozen files untouched.
