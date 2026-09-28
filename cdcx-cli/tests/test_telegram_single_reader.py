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
