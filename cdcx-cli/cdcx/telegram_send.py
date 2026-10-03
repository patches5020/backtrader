"""
telegram_send.py
----------------
The one place cdcx talks to the Telegram Bot API for SENDING, and the one
place the bot token and chat ids are read.

    from cdcx.telegram_send import send_message, send_photo, send_document
    send_message("XRP report ...")
    send_photo("chart.png", caption="XRPUSD 1H")
    send_document("report.txt")

CLI (see main()):  cdcx-telegram send "text" | photo PATH | document PATH | bot

Single-reader rule: Telegram lets exactly ONE program call getUpdates per bot.
For @patches5020bot that program is the cdcx bot (cdcx/telegram_bot.py, the
`TelegramReader` class). This sender NEVER calls getUpdates -- it refuses to --
so any number of senders can run alongside the one reader.

Outbound copy: every message Telegram confirms as sent (text, photo caption,
document caption) is also stored in data/telegram_inbox.db with
direction='outbound', so the read-only inbox MCP can find the reports cdcx
sent -- getUpdates never returns the bot's own messages. The copy is tagged
with its source (cdcx-ai / cdcx-equity reports, cdcx-bot chatter, or
cdcx-telegram for an untagged manual send) and symbol -- pass source=/symbol=,
or --source/--symbol on the CLI. A .txt/.md report sent as a document is
copied in full. The copy is local SQLite only; a failed copy is printed and
never blocks or fails the send.

Config (cdcx-cli/.env, loaded without overriding real environment variables):
    CDCX_TELEGRAM_BOT_TOKEN          bot token -- never printed or logged
    CDCX_TELEGRAM_ALLOWED_CHAT_IDS   comma-separated; the first is the default
                                     destination for send_* and the only chats
                                     the reader answers
"""
from __future__ import annotations

import html
import json
import os
import sys
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Union

from .telegram_inbox import SOURCES, TelegramInbox

CDCX_CLI_DIR = Path(__file__).resolve().parent.parent
TELEGRAM_TEXT_LIMIT = 4000  # Telegram's hard cap is 4096; leave room for <pre> tags


class TelegramConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class TelegramConfig:
    token: str
    chat_ids: tuple[int, ...]

    @property
    def default_chat_id(self) -> int:
        return self.chat_ids[0]

    def __repr__(self) -> str:  # never leak the token through a repr/log line
        return f"TelegramConfig(token=<hidden>, chat_ids={self.chat_ids})"


def parse_chat_ids(raw: str) -> tuple[int, ...]:
    return tuple(int(x) for x in (raw or "").replace(" ", "").split(",") if x.lstrip("-").isdigit())


def load_config(env: Optional[dict] = None) -> TelegramConfig:
    """From `env` if given (tests), else the process environment after
    loading cdcx-cli/.env. Raises TelegramConfigError naming the missing key."""
    if env is None:
        from dotenv import load_dotenv

        load_dotenv(CDCX_CLI_DIR / ".env", override=False)
        env = os.environ
    token = (env.get("CDCX_TELEGRAM_BOT_TOKEN") or "").strip()
    chat_ids = parse_chat_ids(env.get("CDCX_TELEGRAM_ALLOWED_CHAT_IDS") or "")
    if not token:
        raise TelegramConfigError("CDCX_TELEGRAM_BOT_TOKEN is not set (cdcx-cli/.env).")
    if not chat_ids:
        raise TelegramConfigError("CDCX_TELEGRAM_ALLOWED_CHAT_IDS is not set (cdcx-cli/.env).")
    return TelegramConfig(token=token, chat_ids=chat_ids)


def _chunks(text: str, size: int) -> list[str]:
    out, current = [], ""
    for line in text.splitlines(keepends=True):
        if len(line) > size and current:  # flush first so an oversized line stays in order
            out.append(current)
            current = ""
        while len(line) > size:
            out.append(line[:size])
            line = line[size:]
        if len(current) + len(line) > size:
            out.append(current)
            current = ""
        current += line
    return out + [current] if current else out


class TelegramSender:
    """Send-only Bot API client. Calling getUpdates through it is an error."""

    READ_METHODS = frozenset({"getUpdates"})

    SEND_METHODS = frozenset({"sendMessage", "sendPhoto", "sendDocument"})
    # Text documents up to this size are copied into the inbox in full, so the report inside is readable.
    DOCUMENT_TEXT_SUFFIXES = frozenset({".txt", ".md", ".csv", ".json", ".log"})
    DOCUMENT_TEXT_MAX_BYTES = 256 * 1024

    def __init__(self, config: TelegramConfig, opener: Callable = urllib.request.urlopen,
                 inbox: Optional[TelegramInbox] = None, default_source: str = "cdcx-telegram"):
        self.config = config
        self._base = f"https://api.telegram.org/bot{config.token}/"
        self._open = opener
        self.inbox = inbox  # where sent messages are copied (direction='outbound'); None = no copy
        self.default_source = default_source  # the inbox `source` tag when a send does not name one

    def _request(self, method: str, data: bytes, content_type: str, timeout: float,
                 tags: Optional[dict] = None) -> dict:
        req = urllib.request.Request(self._base + method, data=data, headers={"Content-Type": content_type})
        with self._open(req, timeout=timeout) as resp:
            response = json.loads(resp.read().decode())
        if method in self.SEND_METHODS:
            self._record_outbound(response, tags or {})
        return response

    def _record_outbound(self, response: dict, tags: dict) -> None:
        message = response.get("result") if isinstance(response, dict) and response.get("ok") else None
        if self.inbox is None or not isinstance(message, dict):
            return
        try:
            self.inbox.store_outbound(message, source=tags.get("source") or self.default_source,
                                      symbol=tags.get("symbol"), document_text=tags.get("document_text"))
        except Exception as exc:  # the copy is a convenience; the send already succeeded
            print(f"outbound inbox copy failed ({type(exc).__name__}: {exc}); message was sent",
                  file=sys.stderr, flush=True)

    def call(self, method: str, params: Optional[dict] = None, timeout: float = 60,
             source: Optional[str] = None, symbol: Optional[str] = None) -> dict:
        if method in self.READ_METHODS:
            raise RuntimeError(f"TelegramSender is send-only; {method} belongs to the single reader (telegram_bot).")
        return self._request(method, json.dumps(params or {}).encode(), "application/json", timeout,
                             {"source": source, "symbol": symbol})

    def upload(self, method: str, chat_id: int, field: str, path: Path, caption: str = "",
               source: Optional[str] = None, symbol: Optional[str] = None) -> dict:
        boundary = uuid.uuid4().hex
        content = path.read_bytes()
        body = b""
        for name, value in (("chat_id", str(chat_id)), ("caption", caption[:1000])):
            body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{path.name}\"\r\n"
                 "Content-Type: application/octet-stream\r\n\r\n").encode() + content + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        document_text = None
        if (field == "document" and path.suffix.lower() in self.DOCUMENT_TEXT_SUFFIXES
                and len(content) <= self.DOCUMENT_TEXT_MAX_BYTES):
            document_text = content.decode("utf-8", errors="replace")
        return self._request(method, body, f"multipart/form-data; boundary={boundary}", 120,
                             {"source": source, "symbol": symbol, "document_text": document_text})

    # --- the public sending interface -----------------------------------------
    # source: who produced it -- "cdcx-ai" / "cdcx-equity" for an analysis report, "cdcx-bot",
    # or omitted for this sender's default_source. symbol: what it is about ("XRP/USD", "SPY").
    def send_message(self, text: str, chat_id: Optional[int] = None, pre: bool = False,
                     source: Optional[str] = None, symbol: Optional[str] = None) -> None:
        chat_id = chat_id or self.config.default_chat_id
        for chunk in _chunks(text, TELEGRAM_TEXT_LIMIT):
            params = {"chat_id": chat_id, "text": f"<pre>{html.escape(chunk)}</pre>" if pre else chunk}
            if pre:
                params["parse_mode"] = "HTML"
            self.call("sendMessage", params, source=source, symbol=symbol)

    def send_photo(self, path: Union[str, Path], caption: str = "", chat_id: Optional[int] = None,
                   source: Optional[str] = None, symbol: Optional[str] = None) -> None:
        self.upload("sendPhoto", chat_id or self.config.default_chat_id, "photo", Path(path), caption,
                    source=source, symbol=symbol)

    def send_document(self, path: Union[str, Path], caption: str = "", chat_id: Optional[int] = None,
                      source: Optional[str] = None, symbol: Optional[str] = None) -> None:
        self.upload("sendDocument", chat_id or self.config.default_chat_id, "document", Path(path), caption,
                    source=source, symbol=symbol)

    # Names telegram_bot.Bot uses (kept so the bot and the CLI share one client).
    def send_text(self, chat_id: int, text: str, pre: bool = False,
                  source: Optional[str] = None, symbol: Optional[str] = None) -> None:
        self.send_message(text, chat_id=chat_id, pre=pre, source=source, symbol=symbol)


_default: Optional[TelegramSender] = None


def _outbound_inbox() -> Optional[TelegramInbox]:
    try:
        return TelegramInbox()
    except Exception as exc:  # sending must keep working without the local copy
        print(f"outbound inbox copy disabled ({type(exc).__name__}: {exc})", file=sys.stderr, flush=True)
        return None


def default_sender() -> TelegramSender:
    global _default
    if _default is None:
        _default = TelegramSender(load_config(), inbox=_outbound_inbox())
    return _default


def send_message(text: str, pre: bool = False, source: Optional[str] = None, symbol: Optional[str] = None) -> None:
    default_sender().send_message(text, pre=pre, source=source, symbol=symbol)


def send_photo(path: Union[str, Path], caption: str = "", source: Optional[str] = None,
               symbol: Optional[str] = None) -> None:
    default_sender().send_photo(path, caption=caption, source=source, symbol=symbol)


def send_document(path: Union[str, Path], caption: str = "", source: Optional[str] = None,
                  symbol: Optional[str] = None) -> None:
    default_sender().send_document(path, caption=caption, source=source, symbol=symbol)


def main(argv: Optional[list[str]] = None) -> int:
    """cdcx-telegram: send | photo | document | bot."""
    import argparse

    parser = argparse.ArgumentParser(prog="cdcx-telegram", description=(
        "Send to Telegram through the cdcx bot (send-only), or run the bot itself (the single reader)."))
    sub = parser.add_subparsers(dest="command", required=True)
    tags = argparse.ArgumentParser(add_help=False)
    tags.add_argument("--source", choices=[s for s in SOURCES if s != "telegram-user"],
                      help="who produced it, for the inbox copy: cdcx-ai / cdcx-equity for an analysis "
                           "report (default: cdcx-telegram, an untagged manual send)")
    tags.add_argument("--symbol", help="what it is about, e.g. XRP/USD or SPY (inbox tag)")
    p = sub.add_parser("send", help="send a text message", parents=[tags])
    p.add_argument("text", help="message text; '-' reads it from stdin")
    p.add_argument("--pre", action="store_true", help="monospace (for tables)")
    for name in ("photo", "document"):
        p = sub.add_parser(name, help=f"send a {name}", parents=[tags])
        p.add_argument("path")
        p.add_argument("--caption", default="")
    sub.add_parser("bot", help="run the cdcx Telegram bot (the ONLY getUpdates reader)")
    args = parser.parse_args(argv)

    if args.command == "bot":
        from .telegram_bot import main as bot_main
        return bot_main()
    try:
        sender = default_sender()
    except TelegramConfigError as exc:
        print(exc, file=sys.stderr)
        return 1
    print("Telegram outbound sender initialized\nTelegram receive: DISABLED", file=sys.stderr)
    tag = {"source": args.source, "symbol": args.symbol}
    if args.command == "send":
        sender.send_message(sys.stdin.read() if args.text == "-" else args.text, pre=args.pre, **tag)
    elif args.command == "photo":
        sender.send_photo(args.path, caption=args.caption, **tag)
    else:
        sender.send_document(args.path, caption=args.caption, **tag)
    print(f"sent {args.command}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
