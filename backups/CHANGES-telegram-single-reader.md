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

## Operational test history (2026-09-27, from the bot's own log)
All times CDT. Chat 8814026148, bot @patches5020bot, reader = `cdcx-telegram bot`.

| Time | Event |
|---|---|
| 21:58 | Claude Code Telegram plugin processes stopped (pid 10461 `bun server.ts` + wrapper 10454); plugin disabled in ~/.claude/settings.json |
| 21:59 | cdcx bot started as sole reader; process check: only `cdcx-telegram bot` reads the bot |
| 22:0x | First /status attempts never reached the bot: Telegram pending_update_count = 0, no 409 -> they were sent in a different chat, not @patches5020bot |
| 22:09 | Bot restarted with per-message logging (every update logged: id, type, chat id) |
| 22:10 | Probe message sent from the bot ("🔎 cdcx bot check") so the user could reply in the right chat |
| 22:11:44 | update 267944182 -> /status XRP/USD -> summary sent. PASS |
| 22:23:55 | update 267944183 -> /analyze rejected "Usage: /analyze [SYMBOL]": phone keyboard split the symbol (e.g. "XRP / USD") |
| 22:25:08 | update 267944184 -> /analyze XRP/USD -> summary + STRUCTURE SETUP + VP-BOS tables, report file (22:25:35), 1H chart (22:26). PASS |
| 22:28:00 | update 267944185 -> /chart XRP/USD 1H (waited ~1 min at Telegram while /analyze uploads finished; pending_update_count was 1) -> chart 22:28:21. PASS |
| 22:29:33 | Network outage begins: getUpdates TimeoutError, then URLError |
| 22:29–22:40 | Backoff: retry in 5s, 10s, 15s ... 55s, then capped at 60s (13 failed attempts, never a tight loop; no 409 at any point) |
| 22:40:24 | "Telegram receive: recovered" -> immediately received update 267944186 (/report XRP/USD), which Telegram had held during the outage |
| 22:41:02 | /report XRP/USD -> full report file built and sent. PASS |
| ~22:45 | Bot restarted with the symbol-parser fix; full suite 488 passed |

Error backoff (non-409): 5s x consecutive failures, capped at 60s (as observed above).
409 backoff (another reader): 5s doubling to a 300s cap, plus one Telegram alert after 3 in a row (tested; no 409 occurred live).

### Fixes that came out of this test (all in cc613bb)
- **Symbol-parser fix:** "/analyze XRP / USD", "XRP/ USD", "XRP /USD.", "SPY," now parse; junk such as
  "XRP/USD;rm -rf ~" and "$(whoami)" is still refused. Tests: test_forgiving_symbol_typing,
  test_forgiving_parse_still_refuses_junk.
- **Per-message logging:** each update logs `HH:MM:SS update <id>: <type> chat=<id>`, and each command logs
  `HH:MM:SS /<command> <symbol> <tf> [-> error]`. This is what exposed the wrong-chat problem.

### External machine setting (NOT in the repo)
`~/.claude/settings.json` -> `"enabledPlugins": {"telegram@claude-plugins-official": false}`.
Re-enabling it makes the plugin a second getUpdates reader; the cdcx bot then refuses to start.
