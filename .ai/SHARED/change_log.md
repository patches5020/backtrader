# Change Log (newest first)

Each entry: date, commit, what changed, whether any protected parameter changed.
Claude Code appends here after each handoff task. Full detail: `backups/CHANGES-*.md` and `git log`.

## 2026-10-03
- `3c83ab6` CDCX-AI TRADE ANALYSIS shows Long/Short entry, stop, breakeven, TP1-TP4 and R:R under the existing
  lines, using the same 1.5x ATR + 2.2/2.6/3.2/4.5 R ladder (user's choice over 1R-4R). Display-only; existing
  lines unchanged. Protected params: unchanged.

## 2026-10-02
- `e9ad14f` Telegram inbox now stores sent reports (direction=outbound) tagged with source/symbol/message_type;
  new read-only `telegram_latest_report` MCP tool; opt-in localhost+bearer HTTP transport for an OpenAI Secure MCP
  Tunnel. Still one getUpdates reader. Local release gate passed (reports 153 -> 154). Protected params: unchanged.

## 2026-09-29
- `ebbf867` MULTI-TIMEFRAME SUMMARY: ranging rows show Signal `RANGE` / Market `neutral` (crypto + equity).
  Display-only; signal.signal and _market_bias unchanged. Protected params: unchanged.
- `dae2a2a` Ranging timeframes print `DECISION: RANGE MODE` instead of the 0-100 trend label (was "STRONG SELL"
  on XRP 1H at +13). Display-only; execution_signal unchanged. Protected params: unchanged.

## 2026-09-28
- `a290752` Telegram inbox (SQLite) + read-only inbox MCP server; the cdcx bot stays the sole Telegram reader.
  Informational only, no execution path. Protected params: unchanged.
- `600bb1d` Stage-2 setup backtest harness; XRP result: no setup beats the baseline (AVP not supported yet).
  Out-of-sample split locked. Protected params: unchanged.
- `c5bec3e` AVP Bullish Rejection added as a paper/analysis-only signal (stage 1 of 5). Protected params:
  unchanged; never read by the gate.

## 2026-09-27
- `cc613bb` Telegram single-reader: cdcx bot is the only @patches5020bot reader; send-only
  cdcx-telegram CLI; Claude Code Telegram plugin disabled. Protected params: unchanged.
- `88305f0` Read-only cdcx Telegram bot (/status /analyze /chart /report /help); never executes.
  Protected params: unchanged.
- ChatGPT <-> Claude Code handoff layer added (`.ai/`, `CLAUDE.md`); validator checks 15 protected values
  against the live code. Protected params: unchanged.
- `2f0a040` VP-BOS terminology locked (NONE / BOS-PENDING / VP-BOS / BOS-FAILED); summary table split into
  SWING / BOS / VP ACCEPTANCE / RESULT; temporal causality invariant tests. Protected params: unchanged.
- `b021961` bos_state: only closes AFTER a swing formed can break it (false 1D/4H/1H "failed breaks" removed).
  Baseline VP-BOS rows updated with user approval; baseline verdict unchanged. Protected params: unchanged.
- `c867591` Equity weekly bars close Friday 16:00 ET (crypto weeks still 7 days). Protected params: unchanged.
- `0ecbe76` Webull weekly bars re-stamped to Monday. Protected params: unchanged.
- `7d448bf` Robinhood weekly bars built from daily data. Protected params: unchanged.
- `da9bbdb` Forming-candle check handles second-resolution equity timestamps. Protected params: unchanged.
- `7d0934a` Advisory VP-BOS added. Protected params: unchanged.

## 2026-09-26
- `dedee18` XRP multi-timeframe baseline regression test. Protected params: unchanged.
- `efd87be` EMA + FVG columns in the MULTI-TIMEFRAME SUMMARY. Protected params: unchanged.
