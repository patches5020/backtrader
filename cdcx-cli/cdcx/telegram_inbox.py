"""
telegram_inbox.py
-----------------
A local SQLite copy of the Telegram messages the cdcx bot has ALREADY received.

    Telegram -> cdcx bot (TelegramReader, the single reader) -> Bot.handle_update
             -> TelegramInbox.store_message -> data/telegram_inbox.db
             -> InboxReader (read-only) -> cdcx.telegram_inbox_mcp -> Claude Code / ChatGPT

This module never talks to Telegram and never sees the bot token: the writer
side only receives update dicts the bot hands it, and the reader side opens
the database read-only (`mode=ro` + `PRAGMA query_only`). Standard library only.

Only messages from allowlisted chats are stored -- Bot.handle_update drops
everything else before calling store_message.

WAL mode lets the MCP reader query while the bot is writing; the busy timeout
keeps a brief lock from turning into an error. All SQL is parameterized.
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

INBOX_DB = Path(os.getenv("CDCX_TELEGRAM_INBOX_DB")
                or Path(__file__).resolve().parent.parent / "data" / "telegram_inbox.db")

BUSY_TIMEOUT_MS = 5000
MAX_LIMIT = 200
DEFAULT_UNREAD_HOURS = 24

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS messages (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_update_id  INTEGER NOT NULL,
        telegram_message_id INTEGER NOT NULL,
        chat_id             INTEGER NOT NULL,
        user_id             INTEGER,
        username            TEXT,
        timestamp           INTEGER NOT NULL,  -- Telegram's message date (unix seconds, UTC)
        received_at         REAL    NOT NULL,  -- when the bot stored it (unix seconds, UTC)
        text                TEXT    NOT NULL,
        UNIQUE (chat_id, telegram_message_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages (timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_messages_chat_timestamp ON messages (chat_id, timestamp)",
)

_COLUMNS = ("id, telegram_update_id, telegram_message_id, chat_id, user_id, username, "
            "timestamp, received_at, text")


class TelegramInbox:
    """Writer, used only inside the cdcx bot process."""

    def __init__(self, path: Path = INBOX_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            with conn:
                for stmt in SCHEMA:
                    conn.execute(stmt)
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_MS / 1000)
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        return conn

    def store_message(self, update: dict, now: Optional[float] = None) -> bool:
        """Store the update's text message. True if newly stored, False if it
        has no text or (chat_id, telegram_message_id) is already stored."""
        message = update.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        text = message.get("text")
        if chat_id is None or not text or message.get("message_id") is None:
            return False
        sender = message.get("from") or {}
        received = time.time() if now is None else now
        conn = self._connect()
        try:
            with conn:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO messages (telegram_update_id, telegram_message_id, chat_id, user_id, "
                    "username, timestamp, received_at, text) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (update.get("update_id"), message["message_id"], chat_id, sender.get("id"),
                     sender.get("username"), int(message.get("date") or received), received, text))
            return cur.rowcount == 1
        finally:
            conn.close()


class InboxError(Exception):
    pass


class InboxReader:
    """Strictly read-only view of the inbox. Never creates, alters or writes it."""

    def __init__(self, path: Path = INBOX_DB):
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        if not self.path.exists():
            raise InboxError(f"no inbox yet at {self.path} -- it is created when the cdcx bot stores "
                             "its first message (run `python -m cdcx.telegram_bot`)")
        conn = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True,
                               timeout=BUSY_TIMEOUT_MS / 1000)
        conn.execute("PRAGMA query_only=ON")
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        conn.row_factory = sqlite3.Row
        return conn

    def _query(self, where: str, params: tuple, limit: int, newest_first: bool = True) -> list[dict]:
        limit = max(1, min(int(limit), MAX_LIMIT))
        order = "DESC" if newest_first else "ASC"
        conn = self._connect()
        try:
            rows = conn.execute(f"SELECT {_COLUMNS} FROM messages {where} ORDER BY timestamp {order}, id {order} "
                                "LIMIT ?", (*params, limit)).fetchall()
        finally:
            conn.close()
        return [_row(r) for r in rows]

    def latest(self, limit: int = 1) -> list[dict]:
        return self._query("", (), limit)

    def unread(self, since: Optional[float] = None, limit: int = 50, now: Optional[float] = None) -> list[dict]:
        """Messages received after `since` (unix seconds), oldest first. Without
        `since`, the last DEFAULT_UNREAD_HOURS. Nothing is marked read -- the
        caller keeps its own cutoff (pass back the newest `received_at`)."""
        if since is None:
            since = (time.time() if now is None else now) - DEFAULT_UNREAD_HOURS * 3600
        return self._query("WHERE received_at > ?", (float(since),), limit, newest_first=False)

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Case-insensitive substring match on message text, newest first."""
        if not query or not query.strip():
            raise InboxError("search query is empty")
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return self._query("WHERE text LIKE ? ESCAPE '\\'", (f"%{escaped}%",), limit)

    def history(self, limit: int = 50, before: Optional[float] = None, chat_id: Optional[int] = None) -> list[dict]:
        """Newest-first page of messages; pass the oldest `timestamp` seen as `before` for the next page."""
        clauses, params = [], []
        if before is not None:
            clauses.append("timestamp < ?")
            params.append(int(before))
        if chat_id is not None:
            clauses.append("chat_id = ?")
            params.append(int(chat_id))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return self._query(where, tuple(params), limit)


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["time_utc"] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(d["timestamp"]))
    return d
