# Telegram Single-Reader Architecture — Change Summary

Date: 2026-09-27
Commit: cc613bb (pushed to patches5020/backtrader master)
Also changed OUTSIDE the repo: ~/.claude/settings.json
  "enabledPlugins": {"telegram@claude-plugins-official": false}
  (and the running plugin processes were stopped).

## Why
Telegram allows exactly one getUpdates reader per bot. The Claude Code
Telegram plugin (server.ts) has no receive-off mode; its 409 retry resets
to 0 delay, so it won every message and dropped them (its inbound never
reached the session). The user chose to keep the one bot @patches5020bot.

## Architecture
Incoming: Telegram -> cdcx bot (TelegramReader, sole getUpdates) -> command
router -> cdcx-ai / cdcx-equity (read-only, never --execute).
Outgoing: anything -> cdcx.telegram_send (send-only) -> @patches5020bot.

## Files
- cdcx/telegram_send.py (new): config (CDCX_TELEGRAM_BOT_TOKEN,
  CDCX_TELEGRAM_ALLOWED_CHAT_IDS), send_message/send_photo/send_document,
  refuses getUpdates; cdcx-telegram CLI (send|photo|document|bot).
- cdcx/telegram_bot.py: TelegramReader; plugin guard (refuses to start);
  409 backoff 5s->300s + one alert; error backoff to 60s; startup logs;
  commands /status /analyze /chart [SYMBOL] [TF] /report [SYMBOL] /help;
  per-update logging; forgiving symbol typing.
- pyproject.toml: cdcx-telegram entry point.
- CLAUDE.md, .env.example: single-reader rule, send commands.

## Verified
- 28 new tests; full suite 488 passed; handoff validator PASS.
- Process check: only 'cdcx-telegram bot' reads the bot.
- Manual from Telegram: /status 22:11, /analyze 22:25, /chart 22:28,
  /report 22:40 — all passed. Survived an 11-min network drop.

## Notes
- The bot runs only while its process is alive (started from a Claude
  session). Restart: cdcx-telegram bot (in cdcx-cli).
- One command at a time; others wait at Telegram.
