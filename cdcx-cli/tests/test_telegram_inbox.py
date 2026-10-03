"""
Telegram inbox: the cdcx bot copies allowlisted messages into SQLite, and the
read-only reader (behind cdcx.telegram_inbox_mcp) queries them.
"""
import sqlite3
from types import SimpleNamespace

import pytest

from cdcx import telegram_bot as tb
from cdcx import telegram_inbox as ti

ME = 8814026148
NOW = 1_790_000_000.0


def _update(text, message_id=1, chat_id=ME, update_id=100, date=NOW, username="patches5020"):
    return {"update_id": update_id, "message": {
        "message_id": message_id, "date": int(date), "text": text,
        "chat": {"id": chat_id}, "from": {"id": chat_id, "username": username}}}


@pytest.fixture
def db(tmp_path):
    return tmp_path / "data" / "telegram_inbox.db"


@pytest.fixture
def inbox(db):
    return ti.TelegramInbox(db)


def _rows(db):
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT telegram_update_id, telegram_message_id, chat_id, user_id, username, "
                            "timestamp, text FROM messages ORDER BY id").fetchall()
    finally:
        conn.close()


# --- storage ------------------------------------------------------------------------

def test_store_creates_db_in_wal_mode_and_saves_fields(inbox, db):
    assert inbox.store_message(_update("TEST FROM TELEGRAM", message_id=7, update_id=55), now=NOW) is True
    assert _rows(db) == [(55, 7, ME, ME, "patches5020", int(NOW), "TEST FROM TELEGRAM")]
    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()


def test_duplicate_chat_and_message_id_is_stored_once(inbox, db):
    assert inbox.store_message(_update("hi", message_id=1, update_id=1)) is True
    assert inbox.store_message(_update("hi again", message_id=1, update_id=2)) is False
    assert inbox.store_message(_update("other chat", message_id=1, chat_id=42, update_id=3)) is True
    assert [(r[1], r[2], r[6]) for r in _rows(db)] == [(1, ME, "hi"), (1, 42, "other chat")]


def test_unique_constraint_is_in_the_schema(inbox, db):
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO messages (telegram_update_id, telegram_message_id, chat_id, timestamp, received_at, text) "
                 "VALUES (1, 9, 5, 0, 0, 'a')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO messages (telegram_update_id, telegram_message_id, chat_id, timestamp, received_at, "
                     "text) VALUES (2, 9, 5, 0, 0, 'b')")
    conn.close()


def test_non_text_updates_are_not_stored(inbox, db):
    assert inbox.store_message({"update_id": 1, "message": {"message_id": 1, "chat": {"id": ME}}}) is False
    assert inbox.store_message({"update_id": 2, "edited_message": {"message_id": 2, "chat": {"id": ME}, "text": "x"}}) is False
    assert _rows(db) == []


def test_sql_is_parameterized(inbox, db):
    evil = "x'); DROP TABLE messages; --"
    inbox.store_message(_update(evil))
    assert _rows(db)[0][6] == evil


# --- bot integration ------------------------------------------------------------------

class FakeApi:
    def __init__(self):
        self.texts, self.uploads, self.tags = [], [], []  # tags: (kind, source, symbol) per send

    def send_text(self, chat_id, text, pre=False, source=None, symbol=None):
        self.texts.append((chat_id, text, pre))
        self.tags.append(("text", source, symbol))

    def upload(self, method, chat_id, field, path, caption="", source=None, symbol=None):
        self.uploads.append((method, chat_id, path.name, caption))
        self.tags.append((method, source, symbol))


def _bot(tmp_path, inbox, runs=None):
    def runner(argv, **kw):
        if runs is not None:
            runs.append(argv)
        return SimpleNamespace(returncode=0, stdout="MULTI-TIMEFRAME SUMMARY -- XRP/USD\n", stderr="")
    return tb.Bot(FakeApi(), {ME}, tmp_path, runner=runner, chart=lambda s, tf: None, inbox=inbox)


def test_bot_stores_commands_and_plain_text(tmp_path, inbox, db):
    bot = _bot(tmp_path, inbox)
    bot.handle_update(_update("/help", message_id=1))
    bot.handle_update(_update("TEST FROM TELEGRAM", message_id=2))
    assert [r[6] for r in _rows(db)] == ["/help", "TEST FROM TELEGRAM"]
    assert bot.api.texts  # existing replies still sent


def test_bot_does_not_store_unlisted_chats(tmp_path, inbox, db):
    bot = _bot(tmp_path, inbox)
    bot.handle_update(_update("/status XRP/USD", chat_id=12345))
    assert _rows(db) == [] and bot.api.texts == []


class BrokenInbox:
    def store_message(self, update):
        raise sqlite3.OperationalError("database is locked")


def test_inbox_failure_never_stops_the_command(tmp_path, capsys):
    runs = []
    bot = _bot(tmp_path, BrokenInbox(), runs=runs)
    bot.handle_update(_update("/status XRP/USD"))
    assert runs and "MULTI-TIMEFRAME SUMMARY" in bot.api.texts[-1][1]
    assert "inbox store failed" in capsys.readouterr().err


def test_bot_without_inbox_behaves_as_before(tmp_path):
    runs = []
    bot = _bot(tmp_path, None, runs=runs)
    bot.handle_update(_update("/status XRP/USD"))
    assert runs and bot.api.texts


# --- read-only reader -------------------------------------------------------------------

@pytest.fixture
def filled(inbox, db):
    for i, text in enumerate(["/status XRP/USD", "hello world", "TEST FROM TELEGRAM", "100% done_now"], start=1):
        inbox.store_message(_update(text, message_id=i, update_id=i, date=NOW + i), now=NOW + i)
    inbox.store_message(_update("from other", message_id=1, chat_id=42, date=NOW + 10), now=NOW + 10)
    return ti.InboxReader(db)


def test_latest(filled):
    assert [m["text"] for m in filled.latest()] == ["from other"]
    assert [m["text"] for m in filled.latest(limit=2)] == ["from other", "100% done_now"]


def test_unread_is_time_based_and_oldest_first(filled):
    assert [m["text"] for m in filled.unread(since=NOW + 2)] == ["TEST FROM TELEGRAM", "100% done_now", "from other"]
    assert filled.unread(since=NOW + 10) == []
    assert len(filled.unread(now=NOW + 3600)) == 5          # default window: last 24h
    assert filled.unread(now=NOW + 25 * 3600) == []


def test_search_is_case_insensitive_and_escapes_wildcards(filled):
    assert [m["text"] for m in filled.search("test from")] == ["TEST FROM TELEGRAM"]
    assert [m["text"] for m in filled.search("100%")] == ["100% done_now"]
    assert [m["text"] for m in filled.search("_")] == ["100% done_now"]
    with pytest.raises(ti.InboxError):
        filled.search("  ")


def test_history_pages_and_filters(filled):
    page = filled.history(limit=2)
    assert [m["text"] for m in page] == ["from other", "100% done_now"]
    nxt = filled.history(limit=2, before=page[-1]["timestamp"])
    assert [m["text"] for m in nxt] == ["TEST FROM TELEGRAM", "hello world"]
    assert [m["text"] for m in filled.history(chat_id=42)] == ["from other"]


def test_limit_is_clamped(filled):
    assert len(filled.history(limit=0)) == 1
    assert len(filled.history(limit=10_000)) == 5


def test_reader_cannot_write(filled):
    conn = filled._connect()
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM messages")
    conn.close()
    assert len(filled.history()) == 5


def test_reader_does_not_create_a_missing_db(tmp_path):
    missing = tmp_path / "nope" / "telegram_inbox.db"
    with pytest.raises(ti.InboxError, match="no inbox yet"):
        ti.InboxReader(missing).latest()
    assert not missing.parent.exists()


def test_reader_sees_writes_while_writer_is_active(inbox, db):
    reader = ti.InboxReader(db)
    inbox.store_message(_update("one", message_id=1))
    assert len(reader.latest(limit=10)) == 1
    inbox.store_message(_update("two", message_id=2))
    assert len(reader.latest(limit=10)) == 2
