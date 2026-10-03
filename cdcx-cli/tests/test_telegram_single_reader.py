"""
Single-reader Telegram architecture: exactly one getUpdates reader (the cdcx
bot's TelegramReader), any number of send-only senders, and a guard against
the Claude Code Telegram plugin polling the same bot.
"""
import io
import json
import pathlib
import urllib.error

import pytest

from cdcx import telegram_bot as tb
from cdcx import telegram_send as ts

TOKEN = "123456789:TEST_TOKEN_not_real_xxxxxxxxxxxxxxxxxxxx"
CONFIG = ts.TelegramConfig(token=TOKEN, chat_ids=(8814026148,))


class RecordingOpener:
    """Stands in for urllib.request.urlopen; records every Bot API method called."""

    def __init__(self, fail_with=None):
        self.methods, self.fail_with = [], fail_with

    def __call__(self, req, timeout=None):
        self.methods.append(req.full_url.rsplit("/", 1)[-1])
        if self.fail_with:
            raise self.fail_with
        return io.BytesIO(json.dumps({"ok": True, "result": []}).encode())


# Test 1 / 2 -- outbound never reads -------------------------------------------------

def test_send_message_never_calls_get_updates():
    opener = RecordingOpener()
    ts.TelegramSender(CONFIG, opener=opener).send_message("hello\n" * 2000)  # multi-chunk
    assert opener.methods and set(opener.methods) == {"sendMessage"}


def test_send_photo_and_document_never_call_get_updates(tmp_path):
    img, doc = tmp_path / "chart.png", tmp_path / "report.txt"
    img.write_bytes(b"\x89PNG")
    doc.write_text("report")
    opener = RecordingOpener()
    sender = ts.TelegramSender(CONFIG, opener=opener)
    sender.send_photo(img, caption="XRPUSD 1H")
    sender.send_document(doc)
    assert opener.methods == ["sendPhoto", "sendDocument"]


def test_sender_refuses_to_read():
    opener = RecordingOpener()
    with pytest.raises(RuntimeError, match="send-only"):
        ts.TelegramSender(CONFIG, opener=opener).call("getUpdates")
    assert opener.methods == []


# Test 3 -- the reader is the only getUpdates caller ------------------------------------

def test_reader_is_the_get_updates_component():
    opener = RecordingOpener()
    assert tb.TelegramReader(CONFIG, opener=opener).get_updates(offset=None) == []
    assert opener.methods == ["getUpdates"]


def test_get_updates_appears_only_in_the_reader_source():
    cdcx_dir = pathlib.Path(tb.__file__).parent
    callers = [p.name for p in cdcx_dir.rglob("*.py") if "getUpdates" in p.read_text()]
    assert sorted(callers) == ["telegram_bot.py", "telegram_send.py"]  # reader + the sender's refusal list
    send_src = (cdcx_dir / "telegram_send.py").read_text()
    assert 'READ_METHODS = frozenset({"getUpdates"})' in send_src


# Test 3b -- the inbox MCP server can never become a reader or hold the token --------------

INBOX_MODULES = ("telegram_inbox.py", "telegram_inbox_mcp.py")
ALLOWED_INBOX_IMPORTS = {
    "telegram_inbox.py": {"__future__", "os", "sqlite3", "time", "pathlib", "typing"},
    "telegram_inbox_mcp.py": {"__future__", "typing", "mcp.server.mcpserver", "mcp.types", ".telegram_inbox"},
}
# Checked against the code (names, attributes, string literals) -- docstrings may explain what it lacks.
# Running cdcx analysis/trading is blocked by the import allowlist below (no cdcx module but telegram_inbox).
FORBIDDEN_IN_INBOX = ("getupdates", "setwebhook", "webhook", "api.telegram.org", "token",
                      "telegram_send", "telegramreader", "telegramsender", "urllib", "requests",
                      "http", "socket", "subprocess", "load_config", "dotenv", ".env", "getenv(\"telegram")


def _inbox_src(name):
    return (pathlib.Path(tb.__file__).parent / name).read_text()


def _code_words(src):
    import ast
    tree = ast.parse(src)
    docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
                  and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    words = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            words.append(node.id)
        elif isinstance(node, ast.Attribute):
            words.append(node.attr)
        elif isinstance(node, ast.alias):
            words.append(node.name)
        elif isinstance(node, ast.ImportFrom):
            words.append(node.module or "")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            words.append(node.value)
    return [w.lower() for w in words]


@pytest.mark.parametrize("name", INBOX_MODULES)
def test_inbox_modules_have_no_telegram_access_or_credentials(name):
    words = _code_words(_inbox_src(name))
    assert sorted({f for f in FORBIDDEN_IN_INBOX for w in words if f in w}) == []


def test_inbox_guard_catches_a_reader():
    bad = 'import urllib.request\nURL = "https://api.telegram.org/bot%s/getUpdates" % TOKEN\n'
    words = _code_words(bad)
    assert {f for f in FORBIDDEN_IN_INBOX for w in words if f in w} >= {"urllib", "getupdates", "token"}


@pytest.mark.parametrize("name", INBOX_MODULES)
def test_inbox_modules_import_only_the_allowlist(name):
    import ast
    imported = set()
    for node in ast.walk(ast.parse(_inbox_src(name))):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add("." * node.level + (node.module or ""))
    assert imported <= ALLOWED_INBOX_IMPORTS[name], imported - ALLOWED_INBOX_IMPORTS[name]


def test_inbox_mcp_import_loads_no_telegram_client_and_needs_no_token(tmp_path):
    pytest.importorskip("mcp.server.mcpserver")
    import os
    import subprocess
    import sys
    env = {k: v for k, v in os.environ.items() if "TELEGRAM" not in k}
    env["CDCX_TELEGRAM_INBOX_DB"] = str(tmp_path / "inbox.db")
    code = ("import json, sys, cdcx.telegram_inbox_mcp\n"
            "print(json.dumps(sorted(m for m in sys.modules if m in ('cdcx.telegram_send', 'cdcx.telegram_bot', 'dotenv')"
            " or m.startswith(('urllib.request', 'http.client', 'requests')))))")
    out = subprocess.run([sys.executable, "-c", code], env=env, cwd=pathlib.Path(tb.__file__).parent.parent,
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    loaded = json.loads(out.stdout.strip().splitlines()[-1])
    assert [m for m in loaded if m.startswith("cdcx.") or m == "dotenv"] == []


def test_inbox_mcp_exposes_exactly_five_read_only_tools():
    pytest.importorskip("mcp.server.mcpserver")
    import asyncio
    from cdcx import telegram_inbox_mcp as mcp_mod
    tools = asyncio.run(mcp_mod.server.list_tools())
    assert sorted(t.name for t in tools) == ["telegram_history", "telegram_latest", "telegram_latest_report",
                                                 "telegram_search", "telegram_unread"]
    assert all(t.annotations.read_only_hint and not t.annotations.destructive_hint for t in tools)


def test_inbox_mcp_tools_make_no_network_calls_and_leave_db_unchanged(tmp_path, monkeypatch):
    pytest.importorskip("mcp.server.mcpserver")
    import hashlib
    import socket
    import urllib.request
    from cdcx import telegram_inbox as ti
    from cdcx import telegram_inbox_mcp as mcp_mod
    db = tmp_path / "inbox.db"
    ti.TelegramInbox(db).store_message(
        {"update_id": 1, "message": {"message_id": 1, "date": 1, "text": "hi", "chat": {"id": 8814026148}}})
    before = hashlib.sha256(db.read_bytes()).hexdigest()

    def no_network(*a, **k):
        raise AssertionError("inbox MCP tried to use the network")
    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(mcp_mod, "reader", ti.InboxReader(db))
    assert mcp_mod.telegram_latest()["messages"][0]["text"] == "hi"
    assert mcp_mod.telegram_unread(since=0)["count"] == 1
    assert mcp_mod.telegram_search("HI")["count"] == 1
    assert mcp_mod.telegram_history()["count"] == 1
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before


# Test 4 -- Claude Code plugin must not poll the same bot ---------------------------------

def _claude_home(tmp_path, enabled, token=TOKEN):
    home = tmp_path / ".claude"
    (home / "channels" / "telegram").mkdir(parents=True)
    (home / "settings.json").write_text(json.dumps({"enabledPlugins": {tb.CLAUDE_TELEGRAM_PLUGIN: enabled}}))
    (home / "channels" / "telegram" / ".env").write_text(f"TELEGRAM_BOT_TOKEN={token}\n")
    return home


def test_guard_detects_enabled_plugin_on_same_bot(tmp_path):
    assert tb.claude_plugin_reads_same_bot(TOKEN, claude_dir=_claude_home(tmp_path, True)) is True


def test_guard_passes_when_plugin_disabled(tmp_path):
    assert tb.claude_plugin_reads_same_bot(TOKEN, claude_dir=_claude_home(tmp_path, False)) is False


def test_guard_passes_when_plugin_uses_a_different_bot(tmp_path):
    home = _claude_home(tmp_path, True, token="999:other_bot_token")
    assert tb.claude_plugin_reads_same_bot(TOKEN, claude_dir=home) is False


def test_guard_honours_project_local_override(tmp_path):
    # user settings disable it, but a project's settings.local.json re-enables it -> still a second reader
    home = _claude_home(tmp_path, False)
    project = tmp_path / "proj"
    (project / ".claude").mkdir(parents=True)
    (project / ".claude" / "settings.local.json").write_text(
        json.dumps({"enabledPlugins": {tb.CLAUDE_TELEGRAM_PLUGIN: True}}))
    assert tb.claude_plugin_reads_same_bot(TOKEN, claude_dir=home, project_dirs=(project,)) is True


def test_main_refuses_to_start_when_plugin_would_be_a_second_reader(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(tb, "load_config", lambda: CONFIG)
    monkeypatch.setattr(tb, "claude_plugin_reads_same_bot", lambda token, **kw: True)
    monkeypatch.setattr(tb, "poll_forever", lambda *a, **k: pytest.fail("must not poll"))
    assert tb.main() == 1
    assert "REFUSING TO START" in capsys.readouterr().err


# Test 5 -- credentials come from configuration --------------------------------------------

def test_credentials_come_from_environment():
    cfg = ts.load_config({"CDCX_TELEGRAM_BOT_TOKEN": TOKEN, "CDCX_TELEGRAM_ALLOWED_CHAT_IDS": "8814026148, 42"})
    assert cfg.token == TOKEN and cfg.chat_ids == (8814026148, 42) and cfg.default_chat_id == 8814026148
    with pytest.raises(ts.TelegramConfigError, match="CDCX_TELEGRAM_BOT_TOKEN"):
        ts.load_config({"CDCX_TELEGRAM_ALLOWED_CHAT_IDS": "1"})
    with pytest.raises(ts.TelegramConfigError, match="CDCX_TELEGRAM_ALLOWED_CHAT_IDS"):
        ts.load_config({"CDCX_TELEGRAM_BOT_TOKEN": TOKEN})


def test_token_never_in_repr():
    assert TOKEN not in repr(CONFIG)


def test_no_bot_token_committed_in_source_or_tests():
    import re
    root = pathlib.Path(tb.__file__).parent.parent
    real_token = re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_-]{30,}\b")  # Telegram token shape
    offenders = [str(p.relative_to(root)) for p in list(root.glob("cdcx/**/*.py")) + list(root.glob("tests/**/*"))
                 if p.is_file() and p.suffix in {".py", ".txt", ".json", ".md"} and real_token.search(p.read_text(errors="ignore"))]
    assert offenders == []


# Test 6 -- 409 cannot become a tight loop -----------------------------------------------

class FakeSender:
    def __init__(self):
        self.messages = []

    def send_message(self, text, **kw):
        self.messages.append(text)


def test_409_backs_off_exponentially_and_alerts_once():
    conflict = urllib.error.HTTPError("u", 409, "Conflict", {}, None)
    reader = tb.TelegramReader(CONFIG, opener=RecordingOpener(fail_with=conflict))
    sleeps, sender = [], FakeSender()
    tb.poll_forever(reader, bot=None, sender=sender, sleep=sleeps.append, max_iterations=10)
    assert sleeps == [5, 10, 20, 40, 80, 160, 300, 300, 300, 300]  # capped, never 0
    assert len(sender.messages) == 1 and "409" in sender.messages[0]


def test_other_errors_also_back_off():
    reader = tb.TelegramReader(CONFIG, opener=RecordingOpener(fail_with=OSError("net down")))
    sleeps = []
    tb.poll_forever(reader, bot=None, sender=FakeSender(), sleep=sleeps.append, max_iterations=15)
    assert min(sleeps) >= 5 and max(sleeps) == tb.ERROR_BACKOFF_MAX_S


# Commands -------------------------------------------------------------------------------

@pytest.mark.parametrize("text,name,symbol,tf", [
    ("/status", "status", "XRP/USD", None),
    ("/analyze", "analyze", "XRP/USD", None),
    ("/chart", "chart", "XRP/USD", "1H"),
    ("/chart XRP/USD 4H", "chart", "XRP/USD", "4H"),
    ("/chart spy 1d", "chart", "SPY", "1D"),
    ("/chart 1W", "chart", "XRP/USD", "1W"),
    ("/report XRP/USD", "report", "XRP/USD", None),
    ("/report", "report", None, None),
])
def test_command_forms(text, name, symbol, tf):
    cmd = tb.parse_command(text, default="XRP/USD")
    assert (cmd.name, cmd.symbol, cmd.timeframe, cmd.error) == (name, symbol, tf, None)


@pytest.mark.parametrize("text,symbol,tf", [
    ("/analyze XRP / USD", "XRP/USD", None),   # phone keyboard spacing
    ("/analyze XRP/ USD", "XRP/USD", None),
    ("/analyze XRP /USD.", "XRP/USD", None),   # trailing autocorrect punctuation
    ("/chart xrp / usd 4h", "XRP/USD", "4H"),
    ("/status SPY,", "SPY", None),
])
def test_forgiving_symbol_typing(text, symbol, tf):
    cmd = tb.parse_command(text, default="XRP/USD")
    assert (cmd.symbol, cmd.timeframe, cmd.error) == (symbol, tf, None)


def test_forgiving_parse_still_refuses_junk():
    assert tb.parse_command("/status XRP/USD;rm -rf ~").error
    assert tb.parse_command("/status $(whoami)").error
