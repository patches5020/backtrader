"""
telegram_inbox.py
-----------------
A local SQLite copy of the Telegram messages the cdcx bot has ALREADY received,
plus the messages cdcx has sent (reports, charts, bot replies).

    inbound:  Telegram -> cdcx bot (TelegramReader, the single reader) -> Bot.handle_update
                       -> TelegramInbox.store_message ------------------.
    outbound: cdcx.telegram_send (send-only) -> Telegram returns the     |
              sent message -> TelegramInbox.store_outbound -------------+-> data/telegram_inbox.db
              -> InboxReader (read-only) -> cdcx.telegram_inbox_mcp -> Claude Code / ChatGPT

Telegram never delivers the bot's own messages to its reader, so without the
outbound copy the reports the bot sends would be invisible to the inbox.
Each outbound row is tagged with its `source` (cdcx-ai / cdcx-equity for an
analysis report, cdcx-bot for the bot's own chatter, cdcx-telegram for an
untagged manual send), `symbol` and `message_type`, so InboxReader.latest_report
finds "the newest cdcx-ai XRP/USD report" by those tags rather than by text.

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
        telegram_update_id  INTEGER NOT NULL,           -- 0 for outbound (sent messages have no update)
        telegram_message_id INTEGER NOT NULL,
        chat_id             INTEGER NOT NULL,
        user_id             INTEGER,
        username            TEXT,
        timestamp           INTEGER NOT NULL,  -- Telegram's message date = when it was created (unix seconds, UTC)
        received_at         REAL    NOT NULL,  -- when it was stored here (unix seconds, UTC)
        text                TEXT    NOT NULL,  -- searchable body; photos/documents: a marker line + caption
        direction           TEXT    NOT NULL DEFAULT 'inbound',  -- 'inbound' (to the bot) | 'outbound' (sent by cdcx)
        message_type        TEXT    NOT NULL DEFAULT 'text',     -- 'text' | 'photo' | 'document'
        caption             TEXT,                                -- photo/document caption, as sent
        source              TEXT,              -- who produced it: SOURCES below
        symbol              TEXT,              -- e.g. 'XRP/USD' or 'SPY' when the message is about one symbol
        UNIQUE (chat_id, telegram_message_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages (timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_messages_chat_timestamp ON messages (chat_id, timestamp)",
)
# Columns added after the first release, with the value an older row gets. The writer adds any that
# are missing on start; until then the read-only reader reports these defaults for every row.
MIGRATED_COLUMNS = {
    "direction": ("TEXT NOT NULL DEFAULT 'inbound'", "inbound"),
    "message_type": ("TEXT NOT NULL DEFAULT 'text'", "text"),
    "caption": ("TEXT", None),
    "source": ("TEXT", None),
    "symbol": ("TEXT", None),
}
POST_MIGRATION_INDEX = "CREATE INDEX IF NOT EXISTS idx_messages_report ON messages (direction, source, symbol, timestamp)"

DIRECTIONS = ("inbound", "outbound")
MESSAGE_TYPES = ("text", "photo", "document")
# 'telegram-user': what the user typed. Outbound: the analysis engine that produced a report
# ('cdcx-ai', 'cdcx-equity'), the bot's own chatter ('cdcx-bot'), or an untagged manual send ('cdcx-telegram').
REPORT_SOURCES = ("cdcx-ai", "cdcx-equity")
SOURCES = ("telegram-user", *REPORT_SOURCES, "cdcx-bot", "cdcx-telegram")
REPORT_MESSAGE_TYPES = ("text", "document")  # a chart photo is not the report itself

_BASE_COLUMNS = ("id", "telegram_update_id", "telegram_message_id", "chat_id", "user_id", "username",
                 "timestamp", "received_at", "text")


def normalize_symbol(symbol: Optional[str]) -> Optional[str]:
    """'xrp / usd ' -> 'XRP/USD'; '' or None -> None."""
    cleaned = "".join((symbol or "").split()).upper()
    return cleaned or None


class TelegramInbox:
    """Writer, used inside the cdcx bot (inbound + its replies) and the send-only sender (outbound)."""

    def __init__(self, path: Path = INBOX_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            with conn:
                for stmt in SCHEMA:
                    conn.execute(stmt)
                existing = _columns(conn)
                for name, (ddl, _) in MIGRATED_COLUMNS.items():
                    if name not in existing:
                        conn.execute(f"ALTER TABLE messages ADD COLUMN {name} {ddl}")
                conn.execute(POST_MIGRATION_INDEX)
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
                    "username, timestamp, received_at, text, direction, message_type, source) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'inbound', 'text', 'telegram-user')",
                    (update.get("update_id"), message["message_id"], chat_id, sender.get("id"),
                     sender.get("username"), int(message.get("date") or received), received, text))
            return cur.rowcount == 1
        finally:
            conn.close()

    def store_outbound(self, message: dict, source: Optional[str] = None, symbol: Optional[str] = None,
                       document_text: Optional[str] = None, now: Optional[float] = None) -> bool:
        """Store a message cdcx SENT, as Telegram returned it (the `result` of
        sendMessage / sendPhoto / sendDocument), tagged with who produced it
        (`source`, one of SOURCES; default 'cdcx-telegram') and the `symbol` it is
        about. A photo/document is stored as a marker line plus its caption; a
        text document's contents can be passed as `document_text` so the report
        inside it is searchable. True if newly stored."""
        chat_id = (message.get("chat") or {}).get("id")
        if chat_id is None or message.get("message_id") is None:
            return False
        source = source or "cdcx-telegram"
        if source not in SOURCES:
            raise ValueError(f"unknown source {source!r}; expected one of {', '.join(SOURCES)}")
        caption = message.get("caption") or None
        if message.get("text"):
            message_type, text = "text", message["text"]
        elif message.get("photo"):
            message_type = "photo"
            text = "\n".join(p for p in ("[photo]", caption) if p)
        elif message.get("document"):
            message_type = "document"
            name = (message.get("document") or {}).get("file_name") or "file"
            text = "\n".join(p for p in (f"[document: {name}]", caption) if p)
            if document_text:
                text += "\n\n" + document_text
        else:
            return False  # stickers, polls, ... -- nothing cdcx sends
        sender = message.get("from") or {}
        received = time.time() if now is None else now
        conn = self._connect()
        try:
            with conn:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO messages (telegram_update_id, telegram_message_id, chat_id, user_id, "
                    "username, timestamp, received_at, text, direction, message_type, caption, source, symbol) "
                    "VALUES (0, ?, ?, ?, ?, ?, ?, ?, 'outbound', ?, ?, ?, ?)",
                    (message["message_id"], chat_id, sender.get("id"), sender.get("username"),
                     int(message.get("date") or received), received, text, message_type, caption, source,
                     normalize_symbol(symbol)))
            return cur.rowcount == 1
        finally:
            conn.close()


def _columns(conn: sqlite3.Connection) -> set[str]:
    return {row[1] for row in conn.execute("PRAGMA table_info(messages)")}


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

    def _query(self, clauses: list[str], params: list, limit: int, newest_first: bool = True,
               **filters) -> list[dict]:
        """`clauses` are ANDed; every value in them is a `?` parameter. `filters`
        are exact matches on MIGRATED_COLUMNS: None = any, a str, or a tuple of allowed values."""
        limit = max(1, min(int(limit), MAX_LIMIT))
        filters = {k: v for k, v in filters.items() if v is not None}
        _validate(filters)
        order = "DESC" if newest_first else "ASC"
        conn = self._connect()
        try:
            present = _columns(conn)
            columns = list(_BASE_COLUMNS)
            for name, (_, default) in MIGRATED_COLUMNS.items():
                columns.append(name if name in present else f"{_sql_literal(default)} AS {name}")
            clauses, params = list(clauses), list(params)
            for name, wanted in filters.items():
                allowed = (wanted,) if isinstance(wanted, str) else tuple(wanted)
                if name in present:
                    clauses.append(f"{name} IN ({', '.join('?' * len(allowed))})")
                    params += allowed
                elif MIGRATED_COLUMNS[name][1] not in allowed:
                    return []  # an unmigrated inbox has only the default value for this column
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = conn.execute(f"SELECT {', '.join(columns)} FROM messages {where} "
                                f"ORDER BY timestamp {order}, id {order} LIMIT ?", (*params, limit)).fetchall()
        finally:
            conn.close()
        return [_row(r) for r in rows]

    def latest(self, limit: int = 1, direction: Optional[str] = None) -> list[dict]:
        return self._query([], [], limit, direction=direction)

    def latest_report(self, symbol: str, source: Optional[str] = None, limit: int = 1,
                      message_type: Optional[str] = None) -> list[dict]:
        """The newest report(s) cdcx SENT about `symbol`, newest first -- matched on
        the stored tags (direction='outbound', source, symbol), not on text.
        `source` defaults to any analysis engine (cdcx-ai or cdcx-equity);
        `message_type` defaults to text and documents (a chart photo is not a report)."""
        wanted = normalize_symbol(symbol)
        if not wanted:
            raise InboxError("symbol is required, e.g. 'XRP/USD' or 'SPY'")
        return self._query([], [], limit, direction="outbound", source=source or REPORT_SOURCES,
                           symbol=wanted, message_type=message_type or REPORT_MESSAGE_TYPES)

    def unread(self, since: Optional[float] = None, limit: int = 50, now: Optional[float] = None,
               direction: Optional[str] = None) -> list[dict]:
        """Messages received after `since` (unix seconds), oldest first. Without
        `since`, the last DEFAULT_UNREAD_HOURS. Nothing is marked read -- the
        caller keeps its own cutoff (pass back the newest `received_at`)."""
        if since is None:
            since = (time.time() if now is None else now) - DEFAULT_UNREAD_HOURS * 3600
        return self._query(["received_at > ?"], [float(since)], limit, newest_first=False, direction=direction)

    def search(self, query: str, limit: int = 20, direction: Optional[str] = None,
               source: Optional[str] = None, symbol: Optional[str] = None) -> list[dict]:
        """Case-insensitive search, newest first. Every whitespace-separated word
        must appear (in any order); a hyphenated word also matches with a space,
        so "CDCX-AI" finds "CDCX AI"."""
        words = (query or "").split()
        if not words:
            raise InboxError("search query is empty")
        clauses, params = [], []
        for word in words:
            variants = list(dict.fromkeys([word, word.replace("-", " ")]))
            clauses.append("(" + " OR ".join(["text LIKE ? ESCAPE '\\'"] * len(variants)) + ")")
            params += [f"%{_escape_like(v)}%" for v in variants]
        return self._query(clauses, params, limit, direction=direction, source=source,
                           symbol=normalize_symbol(symbol))

    def history(self, limit: int = 50, before: Optional[float] = None, chat_id: Optional[int] = None,
                direction: Optional[str] = None, source: Optional[str] = None,
                symbol: Optional[str] = None) -> list[dict]:
        """Newest-first page of messages; pass the oldest `timestamp` seen as `before` for the next page."""
        clauses, params = [], []
        if before is not None:
            clauses.append("timestamp < ?")
            params.append(int(before))
        if chat_id is not None:
            clauses.append("chat_id = ?")
            params.append(int(chat_id))
        return self._query(clauses, params, limit, direction=direction, source=source,
                           symbol=normalize_symbol(symbol))


_ALLOWED = {"direction": DIRECTIONS, "message_type": MESSAGE_TYPES, "source": SOURCES}


def _validate(filters: dict) -> None:
    for name, wanted in filters.items():
        allowed = _ALLOWED.get(name)
        values = (wanted,) if isinstance(wanted, str) else tuple(wanted)
        if allowed is not None and any(v not in allowed for v in values):
            raise InboxError(f"{name} must be one of {', '.join(allowed)} (or omitted for any)")


def _sql_literal(value) -> str:
    return "NULL" if value is None else "'" + str(value).replace("'", "''") + "'"


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["time_utc"] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(d["timestamp"]))
    return d
