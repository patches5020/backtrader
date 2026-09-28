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
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Union

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

    def __init__(self, config: TelegramConfig, opener: Callable = urllib.request.urlopen):
        self.config = config
        self._base = f"https://api.telegram.org/bot{config.token}/"
        self._open = opener

    def _request(self, method: str, data: bytes, content_type: str, timeout: float) -> dict:
        req = urllib.request.Request(self._base + method, data=data, headers={"Content-Type": content_type})
        with self._open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())

    def call(self, method: str, params: Optional[dict] = None, timeout: float = 60) -> dict:
        if method in self.READ_METHODS:
            raise RuntimeError(f"TelegramSender is send-only; {method} belongs to the single reader (telegram_bot).")
        return self._request(method, json.dumps(params or {}).encode(), "application/json", timeout)

    def upload(self, method: str, chat_id: int, field: str, path: Path, caption: str = "") -> dict:
        boundary = uuid.uuid4().hex
        body = b""
        for name, value in (("chat_id", str(chat_id)), ("caption", caption[:1000])):
            body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{path.name}\"\r\n"
                 "Content-Type: application/octet-stream\r\n\r\n").encode() + path.read_bytes() + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        return self._request(method, body, f"multipart/form-data; boundary={boundary}", 120)

    # --- the public sending interface -----------------------------------------
    def send_message(self, text: str, chat_id: Optional[int] = None, pre: bool = False) -> None:
        chat_id = chat_id or self.config.default_chat_id
        for chunk in _chunks(text, TELEGRAM_TEXT_LIMIT):
            params = {"chat_id": chat_id, "text": f"<pre>{html.escape(chunk)}</pre>" if pre else chunk}
            if pre:
                params["parse_mode"] = "HTML"
            self.call("sendMessage", params)

    def send_photo(self, path: Union[str, Path], caption: str = "", chat_id: Optional[int] = None) -> None:
        self.upload("sendPhoto", chat_id or self.config.default_chat_id, "photo", Path(path), caption)

    def send_document(self, path: Union[str, Path], caption: str = "", chat_id: Optional[int] = None) -> None:
        self.upload("sendDocument", chat_id or self.config.default_chat_id, "document", Path(path), caption)

    # Names telegram_bot.Bot uses (kept so the bot and the CLI share one client).
    def send_text(self, chat_id: int, text: str, pre: bool = False) -> None:
        self.send_message(text, chat_id=chat_id, pre=pre)


_default: Optional[TelegramSender] = None


def default_sender() -> TelegramSender:
    global _default
    if _default is None:
        _default = TelegramSender(load_config())
    return _default


def send_message(text: str, pre: bool = False) -> None:
    default_sender().send_message(text, pre=pre)


def send_photo(path: Union[str, Path], caption: str = "") -> None:
    default_sender().send_photo(path, caption=caption)


def send_document(path: Union[str, Path], caption: str = "") -> None:
    default_sender().send_document(path, caption=caption)


def main(argv: Optional[list[str]] = None) -> int:
    """cdcx-telegram: send | photo | document | bot."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="cdcx-telegram", description=(
        "Send to Telegram through the cdcx bot (send-only), or run the bot itself (the single reader)."))
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("send", help="send a text message")
    p.add_argument("text", help="message text; '-' reads it from stdin")
    p.add_argument("--pre", action="store_true", help="monospace (for tables)")
    for name in ("photo", "document"):
        p = sub.add_parser(name, help=f"send a {name}")
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
    if args.command == "send":
        sender.send_message(sys.stdin.read() if args.text == "-" else args.text, pre=args.pre)
    elif args.command == "photo":
        sender.send_photo(args.path, caption=args.caption)
    else:
        sender.send_document(args.path, caption=args.caption)
    print(f"sent {args.command}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
