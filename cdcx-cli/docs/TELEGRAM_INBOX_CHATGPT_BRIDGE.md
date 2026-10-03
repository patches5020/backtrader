# Telegram inbox → ChatGPT bridge

Lets ChatGPT read the cdcx Telegram chat (@patches5020bot) through the existing
read-only inbox MCP server. ChatGPT can't reach a server that runs only on this
machine, so the connection goes through OpenAI's **Secure MCP Tunnel**. The tunnel
client connects *out* to OpenAI, so nothing listens on the network.

```
INBOUND   you type in Telegram ─► cdcx bot (TelegramReader, the ONLY getUpdates reader) ─┐
OUTBOUND  cdcx-telegram send/photo/document, bot replies ─► Telegram                      │
          └─ the sent message Telegram returns ─► local copy (direction='outbound') ──────┤
                                                                                          ▼
                                                                    data/telegram_inbox.db (SQLite)
                                                                                          │ read-only
                                                                    cdcx.telegram_inbox_mcp (4 tools)
                                                                                          │ stdio, or
                                                                    cdcx.telegram_inbox_http (127.0.0.1 + bearer)
                                                                                          │
                                                       tunnel-client ──outbound──► OpenAI Secure MCP Tunnel
                                                                                          │
                                                                           ChatGPT (web, developer mode)
```

## What changed, and what didn't

- **Outbound copies (new).** Telegram never delivers the bot's own messages to its
  reader, so reports cdcx *sent* never reached the inbox. ChatGPT had nothing to find
  but your own typed messages. Now every message Telegram confirms as sent is copied
  into the inbox with `direction='outbound'`:
  - a text message's text;
  - `[photo]` plus the caption;
  - `[document: name]` plus the caption.

  This happens in `TelegramSender._request`, the one place every send goes through
  (CLI sends and the bot's replies). A failed copy is printed and never blocks the send.
- **Report tags (new).** Each outbound row records `telegram_message_id`, `timestamp` (Telegram's
  creation time; `time_utc` is the readable form), `direction`, `chat_id`, `text`, `caption`,
  `message_type` (`text`/`photo`/`document`), `source` and `symbol`. `source` values:

  | `source` | Set by |
  |---|---|
  | `cdcx-ai` / `cdcx-equity` | an analysis report on a crypto pair / a stock: the bot's `/status`, `/analyze`, `/report SYMBOL` and `/chart`, or `--source` on the CLI |
  | `cdcx-bot` | the bot's own chatter ("Running XRP/USD summary...", help, errors, disclaimers) |
  | `cdcx-telegram` | any `cdcx-telegram` send that doesn't pass `--source` |
  | `telegram-user` | inbound: what you typed |

  `.txt`/`.md`/`.csv`/`.json`/`.log` documents up to 256 KB are copied in full, so a full report
  file sent with `/report SYMBOL` is readable through the MCP.
- **`direction` filter (new)** on every tool: `"inbound"`, `"outbound"`, or omit for both.
- **Search** now matches every word in any order. A hyphenated word also matches with
  a space, so `"CDCX-AI XRP/USD"` finds both `CDCX AI TRADE ANALYSIS … XRP/USD` and
  `CDCX-AI (1h/4h/1d/1w)`.
- **Schema.** A `direction` column (default `'inbound'`) is added. An existing inbox is
  migrated the next time a writer starts: the bot, or any `cdcx-telegram send`. Until
  then the read-only reader treats every row as inbound.
- **HTTP transport (new, opt-in):** `cdcx/telegram_inbox_http.py`. It's a separate module
  so the stdio MCP module keeps its "no network code" guard.
- **Unchanged:**
  - the single reader, the 409 back-off and the plugin guard;
  - the bot's commands; the sender stays send-only (it refuses `getUpdates`);
  - the stdio MCP server;
  - all trading, risk, entry/stop/TP, BOS, VP, FVP/AVP and execution logic.

## The MCP surface (identical over stdio and HTTP)

| Tool | Purpose |
|---|---|
| `telegram_latest_report(symbol, source=None, limit=1)` | **the newest tagged report on a symbol**: matches `direction='outbound'` + `source` (cdcx-ai or cdcx-equity) + `symbol`, text or document, newest first, not text search |
| `telegram_latest(limit=1, direction=None)` | newest message(s) |
| `telegram_search(query, limit=20, direction=None, source=None, symbol=None)` | every word must appear, newest first |
| `telegram_history(limit=50, before=None, chat_id=None, direction=None, source=None, symbol=None)` | paging |
| `telegram_unread(since=None, limit=50, direction=None)` | newer than a cursor (nothing is marked read) |

All five are annotated read-only. There's nothing that sends, writes, trades or runs
analysis. The SQLite file is opened `mode=ro` + `query_only`.

To get "the latest CDCX-AI XRP/USD report", the server's instructions tell ChatGPT to call
`telegram_latest_report(symbol="XRP/USD")`. That's the deterministic query: direction=outbound,
source=cdcx-ai, symbol=XRP/USD, newest first, limit 1. ChatGPT falls back to
`telegram_search(query="XRP/USD", direction="outbound")` only for untagged sends, and always quotes
`time_utc`.

When you send a report by hand, tag it so it counts as a report:
```
cdcx-telegram send - --source cdcx-ai --symbol XRP/USD < xrp_report.txt
cdcx-telegram photo chart.png --caption "XRPUSD 1H" --source cdcx-ai --symbol XRP/USD
```
In Python: `send_message(text, source="cdcx-ai", symbol="XRP/USD")`.

## Run it locally

Install once: `pip install -e ".[inbox-mcp]"` (from `cdcx-cli/`).

**stdio** (Claude Code, and the tunnel's stdio mode):
```
python -m cdcx.telegram_inbox_mcp
```

**HTTP** (localhost only, bearer token required):
```
python -m cdcx.telegram_inbox_http --new-token > ~/.cdcx_inbox_mcp_token     # once; keep it private
chmod 600 ~/.cdcx_inbox_mcp_token
python -m cdcx.telegram_inbox_http --token-file ~/.cdcx_inbox_mcp_token       # http://127.0.0.1:8765/mcp
curl http://127.0.0.1:8765/healthz                                           # {"status":"ok",...,"inbox":"present"}
```
- It refuses to start without a token of at least 32 characters, or on any host other
  than 127.0.0.1, ::1 or localhost.
- The token is read from `CDCX_INBOX_MCP_AUTH_TOKEN` or `--token-file`, never from
  `cdcx-cli/.env`, which holds the Telegram credentials.
- `/healthz` is open. `/mcp` needs `Authorization: Bearer <token>`. Every other path is 404.

Database path: `CDCX_TELEGRAM_INBOX_DB`, default `cdcx-cli/data/telegram_inbox.db`.

## Expose it to ChatGPT through Secure MCP Tunnel

You do these steps yourself: they need your OpenAI organization's API key and ChatGPT
account settings. References:
[Secure MCP Tunnels guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels),
[Connect and test in ChatGPT](https://developers.openai.com/plugins/deploy/connect-chatgpt),
[Developer mode help](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt).

1. **Create the tunnel** at platform.openai.com → Settings → Organization → Tunnels
   (needs the Tunnels *Manage* permission). **Associate it with the ChatGPT workspace you'll
   use.** A tunnel that isn't linked to that workspace won't show up in ChatGPT. Copy its `tunnel_id`.
2. **Create an API key** for running the tunnel, with Tunnels *Read* + *Use* only. Separately,
   the ChatGPT account that creates the app needs Tunnels *Read* + *Use* on the tunnel, plus
   developer mode. Platform tunnel permissions and ChatGPT developer-mode access are separate grants.
3. **Install `tunnel-client`** in WSL. Use the download link on the tunnel settings page,
   or the latest release of `openai/tunnel-client`.
4. **Pick a profile.** stdio is recommended: no listener at all, and the tunnel client
   starts the server itself.
   ```
   export CONTROL_PLANE_API_KEY="sk-..."          # the Read+Use key from step 2; don't commit it
   tunnel-client init --sample sample_mcp_stdio_local --profile cdcx-inbox \
     --tunnel-id tunnel_XXXX \
     --mcp-command "/mnt/c/Users/patch/my-trade/bin/python -m cdcx.telegram_inbox_mcp"
   tunnel-client doctor --profile cdcx-inbox --explain
   tunnel-client run --profile cdcx-inbox
   ```
   To use the HTTP server instead, start it as shown above and swap `--mcp-command`
   for `--mcp-server-url http://127.0.0.1:8765/mcp`. The tunnel client must then send
   the bearer header. If your `tunnel-client` version can't add one, use the stdio profile.
5. **Add the app in ChatGPT web**, not the mobile app:
   - turn on Settings → Security and login → **Developer mode**;
   - go to Settings → Plugins (chatgpt.com/plugins) → **+**;
   - name it "CDCX Telegram Inbox";
   - under Connection choose **Tunnel** and select the tunnel, or paste its `tunnel_id`;
   - set Authentication to **No Auth**. The tunnel is already scoped to your
     organization, and the local server holds no credentials.
6. **Test** from a ChatGPT web chat with the app enabled; see the release gate below.
   After changing tool names or schemas, refresh the app's connection in ChatGPT
   (Settings → Plugins → the app → refresh) so it picks up the new tool list.

   Once the app works on the web, Android chats in the same account can discuss what
   it retrieves. Setting up and testing custom MCP apps is web-only.

## Release gate: the live end-to-end test

The bridge isn't done until this passes. Steps 4–6 and 9 run on your side (OpenAI and ChatGPT web).

1. Start the bot: `cdcx-telegram bot`. Its banner should read `Telegram inbox: ENABLED (... inbound + outbound)`.
2. Generate a fresh report: send `/status XRP/USD` to @patches5020bot.
3. Confirm the outbound row exists. This reads the newest tagged report through the same code ChatGPT uses:
   ```
   python -c "from cdcx.telegram_inbox import InboxReader as R; m=R().latest_report('XRP/USD')[0]; print(m['time_utc'], m['source'], m['symbol'], m['text'][:80])"
   ```
4. Start the tunnel: `tunnel-client run --profile cdcx-inbox`.
5. Connect the tunnel in ChatGPT web (step 5 above).
6. Ask: *"Retrieve the latest CDCX-AI XRP/USD report from patches5020bot."*
7. Check that ChatGPT called `telegram_latest_report`, and that its `time_utc` and text match step 3.
8. Send `/status XRP/USD` again, then re-run step 3. The `time_utc` should be newer.
9. Ask ChatGPT again.
10. It must return the **second** report's `time_utc`. If it returns the first, or the old
    Sep 29 file, it isn't reading the live inbox.

## Checks

- **Tests:** `tests/test_telegram_inbox_bridge.py` also covers the report tags, `telegram_latest_report`,
  the bot tagging its reports by engine and its chatter as `cdcx-bot`, the CLI `--source`/`--symbol`
  flags, full text for `.txt` documents, and a local version of the release gate (report 2 replaces
  report 1). It also covers:
  - outbound copies for text, photo, document and multi-chunk messages, plus the bot's replies;
  - a failed copy never blocks a send;
  - the direction filter;
  - XRP/USD search and the CDCX-AI report prompt, newest first;
  - migrating an old inbox;
  - HTTP health check, a missing or wrong token, non-bearer auth, unknown paths → 404,
    the same five read-only tools, and the database left unchanged;
  - the token-length and loopback-only rules;
  - the import allowlist and banned names (no sending, no Telegram client);
  - still exactly one `getUpdates` reader.
- **Live:** `curl http://127.0.0.1:8765/healthz` while the HTTP server runs, or
  `tunnel-client doctor --profile cdcx-inbox --explain`.
- **If ChatGPT returns nothing:**
  - Run `telegram_latest(direction="outbound")`. If it's empty, nothing has been sent
    since this change. Send a report with `cdcx-telegram send` and try again.
  - Make sure the cdcx bot is running (`cdcx-telegram bot`), or your typed messages
    won't be stored.
