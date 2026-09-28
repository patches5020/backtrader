# ChatGPT <-> Claude Code Handoff Layer — Change Summary

Date: 2026-09-27
Commit: 88bab46 (pushed to patches5020/backtrader master)
Repo touched: `backtrader-repo/` root (`CLAUDE.md`, `.ai/`). No cdcx code changed.

## Why
ChatGPT can't read the repo and Claude Code can't read ChatGPT. The user
relays two small files between them. ChatGPT's own package couldn't be
downloaded to the PC, so this was built from the real cdcx code instead.

## Files
- `CLAUDE.md` — act on a ChatGPT task only when the user asks; protected
  changes need the user's explicit approval; standing design rules;
  test/commit/push/D: conventions.
- `.ai/SHARED/risk_parameters.json` — 15 protected values, each tied to
  the cdcx attribute it must match.
- `.ai/validate_handoff.py` — imports cdcx, compares every protected value
  with the LIVE code (incl. .env overrides), checks handoff JSON, warns on
  protected-touching tasks. Prints "AI handoff validation: PASS/FAIL".
- `.ai/prepare_handoff.py` — writes `.ai/HANDOFF/packet_for_chatgpt.md`
  (one paste-ready file; `--tests` adds the test count).
- `.ai/SHARED/strategy_spec.md`, `change_log.md`, `.ai/README.md`,
  `.ai/HANDOFF/*.json` templates, `.ai/.gitignore` (generated files).

## Verified
- Clean: PASS (all 15 values match the code).
- File drift (stop 2.0 in file): FAIL. Env override ATR_STOP_MULTIPLIER=1.0: FAIL.
- ChatGPT task touching protected values: PASS + approval WARNING.
- Corrupted handoff JSON: FAIL.

## Use
1. `python .ai/prepare_handoff.py` -> paste `.ai/HANDOFF/packet_for_chatgpt.md` into ChatGPT.
2. Paste ChatGPT's filled `chatgpt_to_claude.json` into `.ai/HANDOFF/`, tell Claude "process the handoff".
