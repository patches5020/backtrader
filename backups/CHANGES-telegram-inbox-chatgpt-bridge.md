# Telegram inbox → ChatGPT bridge (2026-10-02) -- commit e9ad14f

## Problem
ChatGPT couldn't get the newest CDCX-AI XRP/USD report from @patches5020bot. There were two causes:
1. **The reports were never in the inbox.** Telegram never delivers a bot's own messages to its
   reader, so `data/telegram_inbox.db` held only what the user typed (9 rows, newest Sep 29). It had
   none of the reports cdcx sent.
2. **No route from ChatGPT to the local MCP.** ChatGPT can't reach an MCP server that only runs on
   this machine. It needs OpenAI's Secure MCP Tunnel or an MCP server it can reach remotely.

## Changes (connectivity/integration only)
1. `cdcx/telegram_inbox.py`
   - `direction` column (`inbound`/`outbound`, default `inbound`); the writer migrates existing inboxes.
   - `TelegramInbox.store_outbound()`.
   - A `direction` filter on every reader query.
   - Search matches every word in any order, and `CDCX-AI` also matches `CDCX AI`.
   - The read-only reader still works on an inbox that hasn't been migrated.
2. `cdcx/telegram_send.py`
   - Every message Telegram confirms as sent (`sendMessage`/`sendPhoto`/`sendDocument`) is copied
     into the inbox with `direction='outbound'`.
   - A failed copy is printed and never blocks the send.
   - The sender still never reads (`getUpdates` refused).
3. `cdcx/telegram_bot.py`: the bot's sender now gets the inbox, so its replies are copied too.
   The single reader, 409 back-off and plugin guard are unchanged.
4. `cdcx/telegram_inbox_mcp.py`
   - A `direction` argument on all the tools.
   - Server instructions tell ChatGPT to use `telegram_search(query='XRP/USD', direction='outbound')`
     for the newest report.
   - Read-only tools only (five after the refinement below), and still no network code.
5. **New** `cdcx/telegram_inbox_http.py`: opt-in Streamable-HTTP transport for the same MCP server.
   - Loopback only (any other host is refused).
   - Requires a bearer token of at least 32 characters (`CDCX_INBOX_MCP_AUTH_TOKEN` or `--token-file`,
     never `.env`), checked in constant time.
   - Open `GET /healthz`; `/mcp` needs the token; any other path is 404.
   - Stateless JSON responses.
6. **New** `docs/TELEGRAM_INBOX_CHATGPT_BRIDGE.md`: running it locally, setting up Secure MCP Tunnel
   (stdio profile recommended), setting up the ChatGPT web developer-mode app, and the live release gate.
7. **New** `tests/test_telegram_inbox_bridge.py`: 28 tests.

Not touched: trading/execution logic, risk/reward, entry, stop, TP1–TP4, BOS, VP, FVP/AVP, the
protected risk parameters, and `cdcx_trades.json`.

## Verification
- `python -m pytest -q` in `cdcx-cli/`: **574 passed** (546 before + 28 new).
- Live: started `python -m cdcx.telegram_inbox_http --port 8799` against the real inbox and queried it
  with curl.
  - `/healthz` returned 200 `"inbox":"present"`; `POST /mcp` with no token returned 401.
  - With the token, `telegram_latest` returned the newest real rows (Sep 29, inbound).
  - `telegram_search("CDCX-AI XRP/USD", direction="outbound")` returned 0, as expected: nothing has
    been sent since the change.
  - The server listened on `127.0.0.1:8799` only.
  - The real inbox was unchanged afterwards: 9 rows, old schema.
- The tunnel and ChatGPT steps aren't done yet. They need the user's OpenAI tunnel ID, API key and
  ChatGPT developer mode.

## Refinement: report tags + deterministic lookup (2026-10-02, after ChatGPT review)
ChatGPT's review: a sent row needs enough metadata to tell a real CDCX-AI report apart from bot chatter,
so "latest XRP/USD report" doesn't depend on text search.
- **Inbox schema:** new `message_type` (`text`/`photo`/`document`), `caption`, `source` and `symbol` columns.
  - Migration now adds any missing column, plus an index on (direction, source, symbol, timestamp).
  - The reader reports defaults on an inbox that hasn't been migrated.
- **`source` values:**
  - `cdcx-ai` / `cdcx-equity`: an analysis report;
  - `cdcx-bot`: bot chatter;
  - `cdcx-telegram`: an untagged manual send (the default);
  - `telegram-user`: inbound.

  An unknown source is refused, and a refused copy never blocks the send.
- **Bot:** `/status`, `/analyze`, `/report SYMBOL` and `/chart` sends are tagged with the engine
  (`report_source(symbol)`) and the symbol. Everything else the bot sends is `cdcx-bot`.
- **Sender:** `source=`/`symbol=` on every send method; `cdcx-telegram --source/--symbol`; `.txt`/`.md`
  documents up to 256 KB are copied in full.
- **MCP:** 5th tool `telegram_latest_report(symbol, source=None, limit=1)` (direction=outbound + source +
  symbol, text/document, newest first); `source`/`symbol` filters on search and history. The instructions
  now point ChatGPT at `telegram_latest_report` first.
- **Docs:** tag table, CLI tagging examples, tunnel/workspace association and permission note, refreshing
  the ChatGPT connection after schema changes, and the 10-step live release gate.
- **Tests:** `python -m pytest -q`: **584 passed** (574 + 10 new tagging tests, including a local
  report-1 → report-2 release-gate test and the bot tagging end to end through the real sender).
- **Still to do on the user's side:** the live release gate (tunnel + ChatGPT web, steps 4–10 in the doc).

## Live release gate, local half (2026-10-02 07:2x UTC)
- **Step 1:** `cdcx-telegram bot` started as the sole reader. Banner: `Telegram inbox: ENABLED (... inbound + outbound)`.
  The real inbox was migrated on start (direction, message_type, caption, source and symbol columns added).
- **Steps 2–3:** report 1 was the `/status XRP/USD` summary, sent through the shared sender tagged cdcx-ai / XRP/USD.
  Inbox: msg 153, 07:23:44 UTC, `latest_report('XRP/USD')` returns it.
- **Step 8:** report 2 → msg 154, 07:24:27 UTC. `telegram_latest_report('XRP/USD')`, the MCP tool ChatGPT calls,
  returns 154; order is [154, 153].
- **Remaining:**
  - the bot's own `/status` path, typed from Telegram;
  - steps 4–7 and 9–10 (tunnel + ChatGPT web).
