"""
Telegram inbox -> ChatGPT bridge: outbound copies of the reports cdcx sends,
direction-filtered retrieval, and the opt-in localhost HTTP transport
(cdcx.telegram_inbox_http) with bearer-token auth and a health check -- while
the inbox stays read-only, never sends, and never becomes a second reader.
"""
import ast
import hashlib
import io
import json
import os
import pathlib
import sqlite3
import subprocess
import sys

import pytest

from cdcx import telegram_inbox as ti
from cdcx import telegram_send as ts

ME = 8814026148
NOW = 1_790_900_000
TOKEN = "123456789:TEST_TOKEN_not_real_xxxxxxxxxxxxxxxxxxxx"
CONFIG = ts.TelegramConfig(token=TOKEN, chat_ids=(ME,))
AUTH = "t" * 40
CDCX_DIR = pathlib.Path(ti.__file__).parent

XRP_OLD = "CDCX AI TRADE ANALYSIS\nSymbol: XRP/USD   Timeframe: 1h\nDECISION: NO TRADE  (Sep 29)"
XRP_NEW = "XRP/USD PAPER LONG -- status (Oct 2)\nCDCX-AI (1h/4h/1d/1w)\nUnrealized -$0.89"


def _inbound(text, message_id, date):
    return {"update_id": message_id, "message": {"message_id": message_id, "date": date, "text": text,
                                                 "chat": {"id": ME}, "from": {"id": ME, "username": "patches5020"}}}


def _sent(message_id, date, **fields):
    return {"message_id": message_id, "date": date, "chat": {"id": ME},
            "from": {"id": 1, "username": "patches5020bot", "is_bot": True}, **fields}


@pytest.fixture
def db(tmp_path):
    return tmp_path / "data" / "telegram_inbox.db"


@pytest.fixture
def chat(db):
    """A chat where the user asked twice and cdcx sent two XRP reports and a chart."""
    inbox = ti.TelegramInbox(db)
    inbox.store_message(_inbound("/status XRP/USD", 1, NOW))
    inbox.store_outbound(_sent(2, NOW + 60, text=XRP_OLD))
    inbox.store_message(_inbound("send the XRP/USD update", 3, NOW + 100))
    inbox.store_outbound(_sent(4, NOW + 200, text=XRP_NEW))
    inbox.store_outbound(_sent(5, NOW + 210, photo=[{"file_id": "x"}], caption="XRP/USD 1H -- TradingView"))
    return ti.InboxReader(db)


# --- outbound copies --------------------------------------------------------------------

class EchoOpener:
    """Stands in for urlopen; answers each send the way Telegram does (the sent message)."""

    def __init__(self):
        self.methods, self.next_id = [], 100

    def __call__(self, req, timeout=None):
        method = req.full_url.rsplit("/", 1)[-1]
        self.methods.append(method)
        self.next_id += 1
        if method == "sendMessage":
            text = json.loads(req.data)["text"]
            for tag in ("<pre>", "</pre>"):  # Telegram returns the text without its HTML markup
                text = text.replace(tag, "")
            result = _sent(self.next_id, NOW, text=text)
        elif method == "sendPhoto":
            result = _sent(self.next_id, NOW, photo=[{"file_id": "p"}], caption="XRPUSD 1H")
        else:
            result = _sent(self.next_id, NOW, document={"file_name": "report.txt"})
        return io.BytesIO(json.dumps({"ok": True, "result": result}).encode())


def test_sent_text_photo_and_document_are_copied_as_outbound(tmp_path, db):
    img, doc = tmp_path / "chart.png", tmp_path / "report.txt"
    img.write_bytes(b"\x89PNG")
    doc.write_text("report")
    opener = EchoOpener()
    sender = ts.TelegramSender(CONFIG, opener=opener, inbox=ti.TelegramInbox(db))
    sender.send_message("XRP/USD report")
    sender.send_message("| TF | Score |", pre=True)
    sender.send_photo(img, caption="XRPUSD 1H")
    sender.send_document(doc)
    assert opener.methods == ["sendMessage", "sendMessage", "sendPhoto", "sendDocument"]
    got = [(m["direction"], m["text"]) for m in reversed(ti.InboxReader(db).history())]
    assert got == [("outbound", "XRP/USD report"), ("outbound", "| TF | Score |"),
                   ("outbound", "[photo]\nXRPUSD 1H"), ("outbound", "[document: report.txt]\n\nreport")]


def test_multi_chunk_message_stores_every_chunk(db):
    sender = ts.TelegramSender(CONFIG, opener=EchoOpener(), inbox=ti.TelegramInbox(db))
    sender.send_message("line\n" * 2000)
    assert len(ti.InboxReader(db).latest(limit=50, direction="outbound")) == len(ts._chunks("line\n" * 2000, 4000))


def test_bot_replies_are_copied_too(db):
    # the bot's sender is a TelegramSender with the inbox attached (telegram_bot.main)
    sender = ts.TelegramSender(CONFIG, opener=EchoOpener(), inbox=ti.TelegramInbox(db))
    sender.send_text(ME, "MULTI-TIMEFRAME SUMMARY -- XRP/USD", pre=True)
    assert ti.InboxReader(db).latest(direction="outbound")[0]["text"] == "MULTI-TIMEFRAME SUMMARY -- XRP/USD"


class BrokenInbox:
    def store_outbound(self, message):
        raise sqlite3.OperationalError("database is locked")


def test_failed_outbound_copy_never_blocks_the_send(capsys):
    opener = EchoOpener()
    ts.TelegramSender(CONFIG, opener=opener, inbox=BrokenInbox()).send_message("still sent")
    assert opener.methods == ["sendMessage"]
    assert "outbound inbox copy failed" in capsys.readouterr().err


def test_no_inbox_means_no_copy_and_get_me_is_never_copied(db):
    ts.TelegramSender(CONFIG, opener=EchoOpener()).send_message("not copied")
    assert not db.exists()
    sender = ts.TelegramSender(CONFIG, opener=EchoOpener(), inbox=ti.TelegramInbox(db))
    sender.call("getMe")
    assert ti.InboxReader(db).latest(limit=10) == []


def test_store_outbound_ignores_messages_without_chat_or_content(db):
    inbox = ti.TelegramInbox(db)
    assert inbox.store_outbound({"message_id": 1, "date": NOW}) is False
    assert inbox.store_outbound(_sent(2, NOW, sticker={"file_id": "s"})) is False
    assert inbox.store_outbound(_sent(3, NOW, text="ok")) is True
    assert inbox.store_outbound(_sent(3, NOW, text="ok")) is False  # same chat + message id


# --- direction + search -----------------------------------------------------------------

def test_direction_filters(chat):
    assert [m["text"] for m in chat.latest(limit=10, direction="inbound")] == [
        "send the XRP/USD update", "/status XRP/USD"]
    assert [m["telegram_message_id"] for m in chat.history(direction="outbound")] == [5, 4, 2]
    assert [m["telegram_message_id"] for m in chat.unread(since=NOW - 1, direction="outbound", now=NOW)] == [2, 4, 5]
    assert len(chat.latest(limit=10)) == 5  # omitted = both
    with pytest.raises(ti.InboxError, match="direction"):
        chat.latest(direction="sideways")


def test_xrp_search_returns_newest_report_first(chat):
    found = chat.search("XRP/USD", direction="outbound")
    assert [m["telegram_message_id"] for m in found] == [5, 4, 2]
    assert chat.search("XRP/USD", direction="outbound", limit=5)[0]["time_utc"] == "2026-10-02 00:16:50"


def test_cdcx_ai_report_retrieval_matches_hyphen_or_space(chat):
    # "CDCX-AI" in the request; the engine prints "CDCX AI TRADE ANALYSIS", the status report "CDCX-AI"
    assert [m["text"] for m in chat.search("CDCX-AI XRP/USD", direction="outbound")] == [XRP_NEW, XRP_OLD]
    assert [m["text"] for m in chat.search("cdcx ai trade analysis")] == [XRP_OLD]


def test_search_needs_every_word(chat):
    assert chat.search("XRP/USD PAPER LONG")[0]["text"] == XRP_NEW
    assert chat.search("XRP/USD bananas") == []


def test_old_inbox_without_direction_column_still_reads_and_is_migrated(db):
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(db)  # the schema as first released
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_update_id INTEGER NOT NULL, "
                 "telegram_message_id INTEGER NOT NULL, chat_id INTEGER NOT NULL, user_id INTEGER, username TEXT, "
                 "timestamp INTEGER NOT NULL, received_at REAL NOT NULL, text TEXT NOT NULL, "
                 "UNIQUE (chat_id, telegram_message_id))")
    conn.execute("INSERT INTO messages (telegram_update_id, telegram_message_id, chat_id, timestamp, received_at, text) "
                 "VALUES (1, 1, ?, ?, ?, 'TEST FROM TELEGRAM')", (ME, NOW, NOW))
    conn.commit()
    conn.close()
    reader = ti.InboxReader(db)
    assert reader.latest()[0]["direction"] == "inbound"      # read-only reader copes before migration
    assert reader.latest(direction="outbound") == []
    ti.TelegramInbox(db).store_outbound(_sent(2, NOW + 1, text="report"))  # writer migrates on start
    assert [(m["direction"], m["text"]) for m in reader.latest(limit=5)] == [
        ("outbound", "report"), ("inbound", "TEST FROM TELEGRAM")]


# --- MCP tools --------------------------------------------------------------------------

@pytest.fixture
def mcp_mod(chat, monkeypatch):
    mod = pytest.importorskip("cdcx.telegram_inbox_mcp")
    monkeypatch.setattr(mod, "reader", chat)
    return mod


def test_mcp_latest_report_prompt_gets_the_newest_message(mcp_mod):
    # "Retrieve the latest CDCX-AI XRP/USD report from patches5020bot"
    res = mcp_mod.telegram_search("CDCX-AI XRP/USD", direction="outbound", limit=5)
    assert res["success"] and res["messages"][0]["text"] == XRP_NEW
    assert mcp_mod.telegram_latest(direction="outbound")["messages"][0]["telegram_message_id"] == 5
    assert mcp_mod.telegram_history(direction="inbound")["count"] == 2
    assert mcp_mod.telegram_unread(since=0, direction="outbound")["count"] == 3


def test_mcp_bad_direction_is_an_error_result_not_a_crash(mcp_mod):
    res = mcp_mod.telegram_latest(direction="both")
    assert res["success"] is False and "direction" in res["error"]


def test_mcp_instructions_point_at_outbound_search(mcp_mod):
    assert "direction='outbound'" in mcp_mod.server.instructions


# --- HTTP transport -----------------------------------------------------------------------

@pytest.fixture
def http(mcp_mod):
    pytest.importorskip("starlette.testclient")
    from starlette.testclient import TestClient
    from cdcx import telegram_inbox_http as h
    with TestClient(h.build_app(AUTH), base_url="http://127.0.0.1:8765") as client:
        yield client


MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
               "MCP-Protocol-Version": "2025-06-18"}


def _rpc(client, method, params=None, token=AUTH):
    headers = dict(MCP_HEADERS)
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": method,
                                                       "params": params or {}})


def test_health_check_is_open_and_reports_inbox(http):
    r = http.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "server": "cdcx-telegram-inbox", "transport": "streamable-http",
                        "read_only": True, "inbox": "present"}


@pytest.mark.parametrize("token", [None, "wrong" * 10, ""])
def test_mcp_endpoint_rejects_missing_or_wrong_token(http, token):
    r = _rpc(http, "tools/list", token=token)
    assert r.status_code == 401 and "bearer" in r.headers["www-authenticate"].lower()


def test_mcp_endpoint_rejects_non_bearer_scheme(http):
    r = http.post("/mcp", headers={**MCP_HEADERS, "Authorization": f"Basic {AUTH}"}, json={})
    assert r.status_code == 401


def test_only_mcp_and_health_paths_exist(http):
    for path in ("/", "/data/telegram_inbox.db", "/../.env", "/mcp/../healthz/x", "/docs"):
        assert http.get(path, headers={"Authorization": f"Bearer {AUTH}"}).status_code == 404


def test_http_lists_the_same_five_read_only_tools_and_nothing_that_sends(http):
    r = _rpc(http, "tools/list")
    assert r.status_code == 200
    tools = r.json()["result"]["tools"]
    assert sorted(t["name"] for t in tools) == ["telegram_history", "telegram_latest", "telegram_latest_report",
                                                "telegram_search", "telegram_unread"]
    assert all(t["annotations"]["readOnlyHint"] and not t["annotations"]["destructiveHint"] for t in tools)
    assert not any("send" in t["name"] or "write" in t["name"] for t in tools)


def test_http_tool_call_returns_newest_xrp_report_and_leaves_db_unchanged(http, chat):
    before = hashlib.sha256(chat.path.read_bytes()).hexdigest()
    r = _rpc(http, "tools/call", {"name": "telegram_search",
                                  "arguments": {"query": "CDCX-AI XRP/USD", "direction": "outbound"}})
    assert r.status_code == 200
    result = r.json()["result"]
    payload = result.get("structuredContent") or json.loads(result["content"][0]["text"])
    assert payload["messages"][0]["text"] == XRP_NEW
    assert hashlib.sha256(chat.path.read_bytes()).hexdigest() == before


def test_http_refuses_short_or_missing_token_and_non_loopback_host(tmp_path):
    pytest.importorskip("mcp.server.mcpserver")
    from cdcx import telegram_inbox_http as h
    for bad in (None, "", "short"):
        with pytest.raises(h.ConfigError, match="at least"):
            h.load_token(env={h.TOKEN_ENV: bad} if bad is not None else {})
    with pytest.raises(h.ConfigError, match="loopback"):
        h.check_host("0.0.0.0")
    assert h.check_host("127.0.0.1") == "127.0.0.1"
    f = tmp_path / "token"
    f.write_text(AUTH + "\n")
    assert h.load_token(token_file=str(f)) == AUTH


def test_http_main_does_not_start_without_token(monkeypatch, capsys):
    pytest.importorskip("mcp.server.mcpserver")
    from cdcx import telegram_inbox_http as h
    monkeypatch.delenv(h.TOKEN_ENV, raising=False)
    assert h.main([]) == 1
    assert h.main(["--host", "0.0.0.0"]) == 1
    assert "not started" in capsys.readouterr().err
    assert h.main(["--new-token"]) == 0
    assert len(capsys.readouterr().out.strip()) >= h.MIN_TOKEN_LENGTH


# --- the HTTP module stays a read-only, non-sending, non-reading wrapper ---------------------

HTTP_ALLOWED_IMPORTS = {"__future__", "argparse", "hmac", "json", "os", "secrets", "sys", "pathlib", "typing",
                        ".", "uvicorn"}
HTTP_FORBIDDEN = ("getupdates", "setwebhook", "api.telegram.org", "telegram_send", "telegram_bot",
                  "telegramreader", "telegramsender", "sendmessage", "sendphoto", "senddocument",
                  "urllib", "requests", "subprocess", "load_config", "dotenv", "telegram_bot_token",
                  "telegraminbox", "store_message", "store_outbound", "sqlite3")


def _http_src():
    return (CDCX_DIR / "telegram_inbox_http.py").read_text()


def test_http_module_imports_only_the_allowlist():
    imported = set()
    for node in ast.walk(ast.parse(_http_src())):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add("." * node.level + (node.module or ""))
    assert imported <= HTTP_ALLOWED_IMPORTS, imported - HTTP_ALLOWED_IMPORTS
    froms = [(n.module, [a.name for a in n.names]) for n in ast.walk(ast.parse(_http_src()))
             if isinstance(n, ast.ImportFrom) and n.level == 1]
    assert froms == [(None, ["telegram_inbox_mcp"])]  # its only cdcx dependency is the read-only MCP server


def test_http_module_code_has_no_telegram_access_sending_or_writing():
    from test_telegram_single_reader import _code_words  # tests/ is on sys.path (rootdir prepend)
    words = _code_words(_http_src())
    assert sorted({f for f in HTTP_FORBIDDEN for w in words if f in w}) == []


def test_http_import_loads_no_telegram_client_and_needs_no_telegram_token(tmp_path):
    pytest.importorskip("mcp.server.mcpserver")
    env = {k: v for k, v in os.environ.items() if "TELEGRAM" not in k}
    env["CDCX_TELEGRAM_INBOX_DB"] = str(tmp_path / "inbox.db")
    code = ("import json, sys, cdcx.telegram_inbox_http\n"
            "print(json.dumps(sorted(m for m in sys.modules if m in ('cdcx.telegram_send', 'cdcx.telegram_bot', "
            "'dotenv') or m.startswith(('urllib.request', 'requests')))))")
    out = subprocess.run([sys.executable, "-c", code], env=env, cwd=CDCX_DIR.parent,
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    loaded = json.loads(out.stdout.strip().splitlines()[-1])
    assert [m for m in loaded if m.startswith("cdcx.") or m == "dotenv"] == []


def test_still_exactly_one_get_updates_reader():
    callers = sorted(p.name for p in CDCX_DIR.rglob("*.py") if "getUpdates" in p.read_text())
    assert callers == ["telegram_bot.py", "telegram_send.py"]  # reader + the sender's refusal list
    assert "getUpdates" not in _http_src() and "getUpdates" not in (CDCX_DIR / "telegram_inbox.py").read_text()


# --- report tags: source / symbol / message_type / caption ------------------------------------

def _stored(db):
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT direction, message_type, caption, source, symbol FROM messages ORDER BY id").fetchall()
    finally:
        conn.close()


def test_outbound_rows_carry_type_caption_source_and_symbol(tmp_path, db):
    img = tmp_path / "chart.png"
    img.write_bytes(b"\x89PNG")
    inbox = ti.TelegramInbox(db)
    sender = ts.TelegramSender(CONFIG, opener=EchoOpener(), inbox=inbox)
    sender.send_message("CDCX AI TRADE ANALYSIS XRP/USD", source="cdcx-ai", symbol="xrp / usd")
    sender.send_photo(img, caption="XRPUSD 1H", source="cdcx-ai", symbol="XRP/USD")
    sender.send_message("hello")                                       # untagged manual send
    inbox.store_message(_inbound("/status XRP/USD", 999, NOW))
    assert _stored(db) == [("outbound", "text", None, "cdcx-ai", "XRP/USD"),
                           ("outbound", "photo", "XRPUSD 1H", "cdcx-ai", "XRP/USD"),
                           ("outbound", "text", None, "cdcx-telegram", None),
                           ("inbound", "text", None, "telegram-user", None)]
    row = ti.InboxReader(db).latest_report("XRP/USD")[0]
    assert {k: row[k] for k in ("direction", "message_type", "source", "symbol", "telegram_message_id")} == {
        "direction": "outbound", "message_type": "text", "source": "cdcx-ai", "symbol": "XRP/USD",
        "telegram_message_id": 101}
    assert row["timestamp"] == NOW and row["time_utc"]  # Telegram's creation time


def test_unknown_source_is_refused_by_the_writer_and_never_blocks_a_send(db, capsys):
    with pytest.raises(ValueError, match="unknown source"):
        ti.TelegramInbox(db).store_outbound(_sent(1, NOW, text="x"), source="chatgpt")
    opener = EchoOpener()
    ts.TelegramSender(CONFIG, opener=opener, inbox=ti.TelegramInbox(db)).send_message("x", source="chatgpt")
    assert opener.methods == ["sendMessage"] and "outbound inbox copy failed" in capsys.readouterr().err


def test_text_report_documents_are_copied_in_full(tmp_path, db):
    report = tmp_path / "XRPUSD_20261002_0510.txt"
    report.write_text("MULTI-TIMEFRAME SUMMARY -- XRP/USD\n1d  99.0  STRONG BUY")
    blob = tmp_path / "chart.bin"
    blob.write_bytes(b"\x00" * 10)
    big = tmp_path / "huge.txt"
    big.write_text("x" * (ts.TelegramSender.DOCUMENT_TEXT_MAX_BYTES + 1))
    sender = ts.TelegramSender(CONFIG, opener=EchoOpener(), inbox=ti.TelegramInbox(db))
    for path in (report, blob, big):
        sender.send_document(path, caption="Full cdcx report -- XRP/USD", source="cdcx-ai", symbol="XRP/USD")
    texts = [m["text"] for m in reversed(ti.InboxReader(db).history())]
    assert "1d  99.0  STRONG BUY" in texts[0]
    assert texts[1] == texts[2] == "[document: report.txt]"  # EchoOpener's file name; no body copied
    assert ti.InboxReader(db).search("STRONG BUY", symbol="XRP/USD")[0]["message_type"] == "document"


@pytest.fixture
def tagged(db):
    inbox = ti.TelegramInbox(db)
    inbox.store_outbound(_sent(1, NOW, text=XRP_OLD), source="cdcx-ai", symbol="XRP/USD")
    inbox.store_outbound(_sent(2, NOW + 10, text="SPY summary"), source="cdcx-equity", symbol="SPY")
    inbox.store_outbound(_sent(3, NOW + 20, photo=[{}], caption="CRYPTOCOM:XRPUSD 1H"), source="cdcx-ai",
                         symbol="XRP/USD")
    inbox.store_outbound(_sent(4, NOW + 30, text="Running XRP/USD summary..."), source="cdcx-bot", symbol="XRP/USD")
    inbox.store_outbound(_sent(5, NOW + 40, text="CDCX-AI XRP/USD looks bullish"))  # untagged manual send
    inbox.store_message(_inbound("/status XRP/USD", 6, NOW + 50))
    return ti.InboxReader(db)


def test_latest_report_matches_tags_not_text(tagged):
    # newer rows mention XRP/USD -- bot chatter, a chart photo, an untagged send, the user's command --
    # but the newest cdcx-ai XRP/USD *report* is message 1
    assert [m["telegram_message_id"] for m in tagged.latest_report("XRP/USD", limit=10)] == [1]
    assert tagged.latest_report("xrp/usd")[0]["text"] == XRP_OLD
    assert tagged.latest_report("SPY")[0]["source"] == "cdcx-equity"
    assert tagged.latest_report("XRP/USD", source="cdcx-equity") == []
    assert [m["telegram_message_id"] for m in tagged.latest_report("XRP/USD", message_type="photo")] == [3]
    assert tagged.latest_report("BTC/USD") == []
    with pytest.raises(ti.InboxError, match="symbol is required"):
        tagged.latest_report("  ")
    with pytest.raises(ti.InboxError, match="source"):
        tagged.latest_report("XRP/USD", source="chatgpt")


def test_history_and_search_filter_by_source_and_symbol(tagged):
    assert [m["telegram_message_id"] for m in tagged.history(source="cdcx-bot")] == [4]
    assert [m["telegram_message_id"] for m in tagged.history(symbol="spy")] == [2]
    assert [m["telegram_message_id"] for m in tagged.search("XRP/USD", source="cdcx-ai")] == [1]  # photo caption says XRPUSD


def test_second_report_replaces_the_first_as_latest(db):
    """The live release gate, locally: report 1 -> ask -> report 2 -> ask -> must be report 2."""
    sender = ts.TelegramSender(CONFIG, opener=EchoOpener(), inbox=ti.TelegramInbox(db))
    reader = ti.InboxReader(db)
    sender.send_message("XRP/USD report #1", pre=True, source="cdcx-ai", symbol="XRP/USD")
    assert reader.latest_report("XRP/USD")[0]["text"] == "XRP/USD report #1"
    sender.send_message("XRP/USD report #2", pre=True, source="cdcx-ai", symbol="XRP/USD")
    assert [m["text"] for m in reader.latest_report("XRP/USD", limit=5)] == ["XRP/USD report #2", "XRP/USD report #1"]


def test_bot_tags_its_reports_with_the_engine_and_its_chatter_as_cdcx_bot(tmp_path, db):
    from types import SimpleNamespace
    from cdcx import telegram_bot as tb
    inbox = ti.TelegramInbox(db)
    sender = ts.TelegramSender(CONFIG, opener=EchoOpener(), inbox=inbox, default_source="cdcx-bot")
    summary = "MULTI-TIMEFRAME SUMMARY -- XRP/USD\n1h 100.0 STRONG BUY\n"
    bot = tb.Bot(sender, {ME}, tmp_path, inbox=inbox, chart=lambda s, tf: None,
                 runner=lambda argv, **kw: SimpleNamespace(returncode=0, stdout=summary, stderr=""))
    bot.handle_update(_inbound("/status XRP/USD", 1, NOW))
    rows = [(r[3], r[4]) for r in _stored(db)]
    assert rows[0] == ("telegram-user", None)              # the command
    assert ("cdcx-bot", None) in rows                      # "Running XRP/USD summary..."
    report = ti.InboxReader(db).latest_report("XRP/USD")[0]
    assert report["source"] == "cdcx-ai" and "1h 100.0 STRONG BUY" in report["text"]
    assert tb.report_source("SPY") == "cdcx-equity"


def test_cli_send_flags_tag_the_copy(monkeypatch, db, capsys):
    sender = ts.TelegramSender(CONFIG, opener=EchoOpener(), inbox=ti.TelegramInbox(db))
    monkeypatch.setattr(ts, "default_sender", lambda: sender)
    assert ts.main(["send", "XRP/USD PAPER LONG status", "--source", "cdcx-ai", "--symbol", "XRP/USD"]) == 0
    assert ts.main(["send", "plain note"]) == 0
    assert [(r[3], r[4]) for r in _stored(db)] == [("cdcx-ai", "XRP/USD"), ("cdcx-telegram", None)]
    with pytest.raises(SystemExit):
        ts.main(["send", "x", "--source", "telegram-user"])  # only cdcx sources can be claimed


def test_mcp_latest_report_tool(tagged, monkeypatch):
    mcp_mod = pytest.importorskip("cdcx.telegram_inbox_mcp")
    monkeypatch.setattr(mcp_mod, "reader", tagged)
    res = mcp_mod.telegram_latest_report("XRP/USD")
    assert res["success"] and res["count"] == 1 and res["messages"][0]["telegram_message_id"] == 1
    assert mcp_mod.telegram_latest_report("XRP/USD", source="nope")["success"] is False
    assert "telegram_latest_report" in mcp_mod.server.instructions


def test_unmigrated_inbox_has_no_tagged_reports(db):
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_update_id INTEGER NOT NULL, "
                 "telegram_message_id INTEGER NOT NULL, chat_id INTEGER NOT NULL, user_id INTEGER, username TEXT, "
                 "timestamp INTEGER NOT NULL, received_at REAL NOT NULL, text TEXT NOT NULL, "
                 "UNIQUE (chat_id, telegram_message_id))")
    conn.execute("INSERT INTO messages (telegram_update_id, telegram_message_id, chat_id, timestamp, received_at, text) "
                 "VALUES (1, 1, ?, ?, ?, 'XRP/USD')", (ME, NOW, NOW))
    conn.commit()
    conn.close()
    reader = ti.InboxReader(db)
    assert reader.latest_report("XRP/USD") == []
    assert reader.latest()[0]["message_type"] == "text" and reader.latest()[0]["source"] is None
    ti.TelegramInbox(db)  # migrate
    conn = sqlite3.connect(db)
    assert {"direction", "message_type", "caption", "source", "symbol"} <= {r[1] for r in conn.execute(
        "PRAGMA table_info(messages)")}
    conn.close()
