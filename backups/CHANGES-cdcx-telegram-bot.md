# cdcx Telegram Bot (read-only) — Change Summary

Date: 2026-09-27
Commit: 88305f0 (pushed to patches5020/backtrader master)
Repo touched: `cdcx-cli/` only. No protected parameter or gate changed.

## What
`python -m cdcx.telegram_bot` (cdcx-cli/cdcx/telegram_bot.py), stdlib only.
- /status SYMBOL — multi-timeframe summary + per-TF regime/direction/decision
- /analyze SYMBOL — summary, STRUCTURE SETUP, STRUCTURE / VP SUMMARY, full
  report (.txt), TradingView 1H chart (tv CLI via Windows node.exe, Alt+R,
  full-window capture)
- /chart SYMBOL · /report (ChatGPT handoff packet) · /help
- Crypto pairs (XRP/USD) -> cdcx-ai; tickers (SPY) -> cdcx-equity robinhood

## Safety
Never --execute/--live; no /paper, /execute, /claude or arbitrary commands.
Regex-validated symbols passed as argv (no shell). Unlisted chats ignored.

## Setup (not done yet — needs the user)
1. @BotFather -> /newbot (a NEW bot, not the Claude Code plugin's bot).
2. cdcx-cli/.env: CDCX_TELEGRAM_BOT_TOKEN=<token>,
   CDCX_TELEGRAM_ALLOWED_CHAT_IDS=8814026148 (.env is git-ignored).
3. Run from cdcx-cli: python -m cdcx.telegram_bot

## Tests
29 in tests/test_telegram_bot.py (real report fixture). Found and fixed a
message-chunk ordering bug. Live check: real /status + real chart capture.
Full suite: 459 passed.
