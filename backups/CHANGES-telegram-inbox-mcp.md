# Telegram Inbox + Read-Only MCP — Change Summary

Date: 2026-09-28
Commit: a290752 (master, not pushed)
Also changed OUTSIDE the repo: ~/.claude.json (user scope)
  telegram-inbox MCP server registered:
  /mnt/c/Users/patch/my-trade/bin/python -m cdcx.telegram_inbox_mcp

## Why
Let Claude Code (and later ChatGPT, if its plan supports custom MCP) read
messages sent to @patches5020bot WITHOUT a second Telegram reader. A
ChatGPT-proposed bridge that polled the Bot API itself was rejected: it
would compete with the cdcx bot for messages (409 Conflict / lost messages)
and put the token in a second .env.

## Architecture
Telegram -> cdcx bot (TelegramReader, still the sole getUpdates reader)
-> Bot.handle_update: allowlist check -> TelegramInbox.store_message
-> cdcx-cli/data/telegram_inbox.db (SQLite, WAL, gitignored)
-> InboxReader (mode=ro + PRAGMA query_only) -> cdcx.telegram_inbox_mcp (stdio)
-> telegram_latest / telegram_unread / telegram_search / telegram_history

The MCP server has no token, no Telegram/network code, no cdcx execution,
and cannot write the database.

## Files
- cdcx/telegram_inbox.py (new): writer TelegramInbox + read-only InboxReader.
  Stdlib only; WAL, 5s busy timeout, parameterized SQL, CREATE IF NOT EXISTS,
  UNIQUE (chat_id, telegram_message_id), indexes on timestamp and
  (chat_id, timestamp).
- cdcx/telegram_inbox_mcp.py (new): MCP server, four read-only tools.
  "Unread" is time-based (received_at > since, default last 24h, returns a
  cursor) -- nothing is marked read.
- cdcx/telegram_bot.py: Bot(inbox=...); handle_update stores allowlisted
  text messages (commands and plain text) right after the allowlist check,
  in try/except -- a DB failure never stops the command. main() creates the
  inbox and prints "Telegram inbox: ENABLED/DISABLED"; bot runs without it.
- tests/test_telegram_inbox.py (new): 17 tests (storage, dedup, allowlist,
  DB failure, reader queries, read-only, missing DB, concurrent read).
- tests/test_telegram_single_reader.py: 8 guard tests -- inbox modules have
  no Telegram/network/token code, import allowlist, MCP import loads no
  Telegram client, exactly four read-only tools, no network + DB unchanged.
- .gitignore: data/.  pyproject.toml: optional extra inbox-mcp = ["mcp>=2"].

## Verified
- Full suite 542 passed (517 existing + 25 new).
- Live: bot restarted 22:54 with "Telegram inbox: ENABLED"; queued
  /help, /status, /start, "TEST FROM PATCHES5020", "TEST FROM TELEGRAM"
  stored and still answered normally. A non-text update was ignored.
- telegram_latest via MCP stdio (no TELEGRAM_* env) returned
  "TEST FROM TELEGRAM" (update 267944194). One bot process, no 409s.
- "CHATGPT MCP TEST" had not arrived at commit time (not yet sent/delivered).

## Notes
- Bot runs detached (PID 49991 at start), log: cdcx-cli/trading/telegram_bot.log.
- ChatGPT Free cannot attach custom MCP servers; Claude Code can now.
- Protected params / trading logic: unchanged.
