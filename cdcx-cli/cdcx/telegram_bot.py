"""
telegram_bot.py
---------------
Read-only Telegram front end for cdcx: ask for an analysis from your phone,
get the report (and the TradingView chart) back.

    /status SYMBOL    multi-timeframe summary only (fast)
    /analyze SYMBOL   full --structure analysis + full report file + 1H chart
    /chart SYMBOL     TradingView 1H chart screenshot
    /report           the ChatGPT handoff packet (.ai/HANDOFF/packet_for_chatgpt.md)
    /help

SYMBOL: a crypto pair with a slash (XRP/USD -> cdcx-ai, Crypto.com) or a
stock/ETF ticker (SPY -> cdcx-equity --source robinhood).

Deliberately NOT here: /paper, /execute, or anything that runs arbitrary
commands. This bot only runs the same read-only analysis commands you run
by hand -- never --execute -- so a leaked bot token can't trade or run code.
Messages from any chat not in CDCX_TELEGRAM_ALLOWED_CHAT_IDS are ignored.

Setup (cdcx-cli/.env):
    CDCX_TELEGRAM_BOT_TOKEN=...          a NEW bot from @BotFather -- not the
                                         Claude Code Telegram plugin's bot (two
                                         programs polling one token fight over
                                         every message)
    CDCX_TELEGRAM_ALLOWED_CHAT_IDS=...   your chat id(s), comma-separated
Run (from cdcx-cli):  python -m cdcx.telegram_bot

Standard library only (urllib) -- no extra package to install.
"""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

CDCX_CLI_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = CDCX_CLI_DIR.parent
TV_CLI_JS = CDCX_CLI_DIR / "tradingview-mcp" / "src" / "cli" / "index.js"

TIMEFRAMES = "1w,1d,4h,1h"
ANALYSIS_TIMEOUT_S = 300
TELEGRAM_TEXT_LIMIT = 4000  # Telegram's hard cap is 4096; leave room for <pre> tags

# Crypto pair (XRP/USD) or plain ticker (SPY, BRK.B). Anything else is refused
# before it gets near a subprocess -- args are also passed as a list, never a shell.
_SYMBOL_RE = re.compile(r"^(?:[A-Z0-9]{1,10}/[A-Z0-9]{2,6}|[A-Z]{1,5}(?:\.[A-Z])?)$")

HELP = (
    "cdcx bot (read-only, never trades)\n\n"
    "/status SYMBOL  - multi-timeframe summary\n"
    "/analyze SYMBOL - full analysis + report file + 1H chart\n"
    "/chart SYMBOL   - TradingView 1H chart\n"
    "/report         - ChatGPT handoff packet\n\n"
    "SYMBOL: XRP/USD (crypto) or SPY (stock/ETF)"
)


@dataclass
class Command:
    name: str
    symbol: Optional[str] = None
    error: Optional[str] = None


def parse_command(text: str) -> Command:
    parts = (text or "").strip().split()
    if not parts or not parts[0].startswith("/"):
        return Command(name="", error="Send a command. /help lists them.")
    name = parts[0][1:].split("@", 1)[0].lower()  # "/status@MyBot" in group chats
    if name in ("help", "start"):
        return Command(name="help")
    if name == "report":
        return Command(name="report")
    if name not in ("status", "analyze", "chart"):
        return Command(name=name, error=f"Unknown command /{name}. /help lists them.")
    if len(parts) != 2:
        return Command(name=name, error=f"Usage: /{name} SYMBOL  (e.g. /{name} XRP/USD or /{name} SPY)")
    symbol = parts[1].upper()
    if not _SYMBOL_RE.match(symbol):
        return Command(name=name, error=f"'{parts[1]}' isn't a symbol I accept (e.g. XRP/USD or SPY).")
    return Command(name=name, symbol=symbol)


def is_crypto(symbol: str) -> bool:
    return "/" in symbol


def analysis_argv(symbol: str, structure: bool) -> list[str]:
    """The exact read-only command a user would type. Never --execute."""
    if is_crypto(symbol):
        argv = ["cdcx-ai", "--symbol", symbol, "--timeframes", TIMEFRAMES]
        return argv + (["--structure"] if structure else [])
    argv = ["cdcx-equity", "--source", "robinhood", "--symbol", symbol, "--timeframes", TIMEFRAMES]
    return argv + (["--structure-report"] if structure else [])


def tradingview_symbol(symbol: str) -> str:
    """XRP/USD -> CRYPTOCOM:XRPUSD (the exchange cdcx-ai reads); SPY -> SPY."""
    return f"CRYPTOCOM:{symbol.replace('/', '')}" if is_crypto(symbol) else symbol


def extract_summary(report: str) -> str:
    """MULTI-TIMEFRAME SUMMARY table + ATR alignment + VP hierarchy."""
    start = report.find("MULTI-TIMEFRAME SUMMARY")
    if start == -1:
        return ""
    start = report.rfind("\n", 0, report.rfind("=" * 20, 0, start)) + 1
    ends = [i for i in (report.find(m, start) for m in ("\n--------------------------------------------------\n",
                                                          "\n-------------------------------------------------\n"))
            if i != -1]
    return report[start:min(ends) if ends else len(report)].strip()


def extract_block(report: str, title: str) -> str:
    """A dashed-rule block (STRUCTURE SETUP, STRUCTURE / VP SUMMARY) by its title."""
    at = report.find(title)
    if at == -1:
        return ""
    start = report.rfind("\n", 0, report.rfind("\n", 0, at)) + 1
    end = report.find("\n\n", at)
    return report[start:end if end != -1 else len(report)].strip()


def extract_decisions(report: str) -> str:
    """One line per timeframe: regime + direction + decision."""
    lines, tf, regime, bias = [], None, "?", "?"
    for line in report.splitlines():
        if m := re.match(r"Symbol: \S+\s+Timeframe: (\S+)", line):
            tf, regime, bias = m.group(1), "?", "?"
        elif tf and line.startswith("MARKET REGIME:"):
            regime = line.split(":", 1)[1].strip()
        elif tf and line.startswith("DIRECTION BIAS:"):
            bias = line.split(":", 1)[1].strip()
        elif tf and line.startswith("DECISION:"):
            lines.append(f"{tf.upper():<3} {line.split(':', 1)[1].strip():<11} {regime} | {bias}")
            tf = None
    return "\n".join(lines)


def run_analysis(symbol: str, structure: bool, runner=subprocess.run) -> tuple[int, str]:
    proc = runner(analysis_argv(symbol, structure), cwd=CDCX_CLI_DIR, capture_output=True, text=True,
                  timeout=ANALYSIS_TIMEOUT_S)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def take_chart(symbol: str, runner=subprocess.run) -> Optional[Path]:
    """Set TradingView to SYMBOL on 1H and screenshot it via the tv CLI.
    Uses Windows node.exe: from WSL, Windows' localhost CDP port is only
    reliably reachable by a Windows process."""
    node = "node.exe" if os.path.exists("/proc/version") and "microsoft" in Path("/proc/version").read_text().lower() else "node"
    js = _to_windows_path(TV_CLI_JS) if node == "node.exe" else str(TV_CLI_JS)

    def tv(*args: str) -> dict:
        proc = runner([node, js, *args], capture_output=True, text=True, timeout=60)
        return json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {"success": False}

    if not tv("symbol", tradingview_symbol(symbol)).get("success"):
        return None
    tv("timeframe", "60")
    time.sleep(2)
    tv("ui", "keyboard", "r", "--alt")  # Alt+R: reset the view so the latest bars fill the chart
    time.sleep(2)  # let it render
    # "full", not "chart": the chart region crops off the right-hand price scale and its level labels.
    shot = tv("screenshot", "--region", "full", "--output", f"telegram_{symbol.replace('/', '')}_1h")
    path = shot.get("file_path")
    return Path(_to_wsl_path(path)) if path else None


def _to_windows_path(p: Path) -> str:
    return subprocess.run(["wslpath", "-w", str(p)], capture_output=True, text=True).stdout.strip() or str(p)


def _to_wsl_path(p: str) -> str:
    if re.match(r"^[A-Za-z]:\\", p):
        return subprocess.run(["wslpath", "-u", p], capture_output=True, text=True).stdout.strip() or p
    return p


# --- Telegram Bot API (stdlib only) -------------------------------------------

class TelegramApi:
    def __init__(self, token: str, opener: Callable = urllib.request.urlopen):
        self._base = f"https://api.telegram.org/bot{token}/"
        self._open = opener

    def call(self, method: str, params: Optional[dict] = None, timeout: float = 60) -> dict:
        data = json.dumps(params or {}).encode()
        req = urllib.request.Request(self._base + method, data=data, headers={"Content-Type": "application/json"})
        with self._open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())

    def upload(self, method: str, chat_id: int, field: str, path: Path, caption: str = "") -> dict:
        boundary = uuid.uuid4().hex
        body = b""
        for name, value in (("chat_id", str(chat_id)), ("caption", caption[:1000])):
            body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{path.name}\"\r\n"
                 "Content-Type: application/octet-stream\r\n\r\n").encode() + path.read_bytes() + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(self._base + method, data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with self._open(req, timeout=120) as resp:
            return json.loads(resp.read().decode())

    def send_text(self, chat_id: int, text: str, pre: bool = False) -> None:
        for chunk in _chunks(text, TELEGRAM_TEXT_LIMIT):
            params = {"chat_id": chat_id, "text": f"<pre>{html.escape(chunk)}</pre>" if pre else chunk}
            if pre:
                params["parse_mode"] = "HTML"
            self.call("sendMessage", params)


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


# --- command handling ----------------------------------------------------------

class Bot:
    def __init__(self, api: TelegramApi, allowed_chat_ids: set[int], workdir: Path,
                 runner=subprocess.run, chart=take_chart):
        self.api, self.allowed, self.workdir = api, allowed_chat_ids, workdir
        self.runner, self.chart = runner, chart

    def handle_update(self, update: dict) -> None:
        message = update.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        if chat_id is None or not message.get("text"):
            return
        if chat_id not in self.allowed:
            print(f"ignored message from unlisted chat {chat_id}", file=sys.stderr)
            return
        cmd = parse_command(message["text"])
        if cmd.error:
            self.api.send_text(chat_id, cmd.error)
            return
        try:
            getattr(self, f"_cmd_{cmd.name}")(chat_id, cmd)
        except subprocess.TimeoutExpired:
            self.api.send_text(chat_id, f"/{cmd.name} timed out after {ANALYSIS_TIMEOUT_S}s.")
        except Exception as exc:  # report, keep the bot alive
            self.api.send_text(chat_id, f"/{cmd.name} failed: {type(exc).__name__}: {exc}")

    def _cmd_help(self, chat_id: int, cmd: Command) -> None:
        self.api.send_text(chat_id, HELP)

    def _cmd_status(self, chat_id: int, cmd: Command) -> None:
        self.api.send_text(chat_id, f"Running {cmd.symbol} summary...")
        code, report = run_analysis(cmd.symbol, structure=False, runner=self.runner)
        summary = extract_summary(report)
        if not summary:
            self.api.send_text(chat_id, f"No summary produced (exit {code}):\n{report[-1500:]}", pre=True)
            return
        self.api.send_text(chat_id, f"{summary}\n\n{extract_decisions(report)}", pre=True)

    def _cmd_analyze(self, chat_id: int, cmd: Command) -> None:
        self.api.send_text(chat_id, f"Running full {cmd.symbol} analysis (about a minute)...")
        code, report = run_analysis(cmd.symbol, structure=True, runner=self.runner)
        summary = extract_summary(report)
        if not summary:
            self.api.send_text(chat_id, f"No summary produced (exit {code}):\n{report[-1500:]}", pre=True)
            return
        parts = [summary, extract_decisions(report),
                 extract_block(report, "STRUCTURE SETUP"),
                 extract_block(report, "MULTI-TIMEFRAME STRUCTURE / VP SUMMARY")]
        self.api.send_text(chat_id, "\n\n".join(p for p in parts if p), pre=True)
        self.api.send_text(chat_id, "NO TRADE = insufficient confirmation, not a sell signal. Not financial advice.")
        report_file = self.workdir / f"{cmd.symbol.replace('/', '')}_{time.strftime('%Y%m%d_%H%M')}.txt"
        report_file.write_text(report)
        self.api.upload("sendDocument", chat_id, "document", report_file, caption="Full cdcx report")
        self._send_chart(chat_id, cmd.symbol)

    def _cmd_chart(self, chat_id: int, cmd: Command) -> None:
        self._send_chart(chat_id, cmd.symbol, announce=True)

    def _send_chart(self, chat_id: int, symbol: str, announce: bool = False) -> None:
        if announce:
            self.api.send_text(chat_id, f"Taking {symbol} 1H chart...")
        path = self.chart(symbol)
        if path and path.exists():
            self.api.upload("sendPhoto", chat_id, "photo", path, caption=f"{tradingview_symbol(symbol)} 1H")
        else:
            self.api.send_text(chat_id, "Chart unavailable -- is TradingView running with CDP (port 9222)?")

    def _cmd_report(self, chat_id: int, cmd: Command) -> None:
        proc = self.runner([sys.executable, str(REPO_DIR / ".ai" / "prepare_handoff.py")], cwd=REPO_DIR,
                           capture_output=True, text=True, timeout=120)
        packet = REPO_DIR / ".ai" / "HANDOFF" / "packet_for_chatgpt.md"
        status = (proc.stdout or "").strip().splitlines()[-1:] or ["(no output)"]
        if not packet.exists():
            self.api.send_text(chat_id, f"Packet not built: {status[0]}")
            return
        self.api.upload("sendDocument", chat_id, "document", packet, caption=f"ChatGPT handoff packet -- {status[0]}")


def _allowed_ids(raw: str) -> set[int]:
    return {int(x) for x in raw.replace(" ", "").split(",") if x.lstrip("-").isdigit()}


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(CDCX_CLI_DIR / ".env")
    token = os.getenv("CDCX_TELEGRAM_BOT_TOKEN", "").strip()
    allowed = _allowed_ids(os.getenv("CDCX_TELEGRAM_ALLOWED_CHAT_IDS", ""))
    if not token or not allowed:
        print("Set CDCX_TELEGRAM_BOT_TOKEN and CDCX_TELEGRAM_ALLOWED_CHAT_IDS in cdcx-cli/.env "
              "(a NEW bot from @BotFather -- see this module's docstring).", file=sys.stderr)
        return 1
    workdir = CDCX_CLI_DIR / "trading" / "telegram_reports"
    workdir.mkdir(parents=True, exist_ok=True)
    api = TelegramApi(token)
    me = api.call("getMe").get("result", {})
    print(f"cdcx bot @{me.get('username')} running; answering chats {sorted(allowed)}. Ctrl+C to stop.")
    bot, offset = Bot(api, allowed, workdir), None
    while True:
        try:
            updates = api.call("getUpdates", {"timeout": 50, "offset": offset}, timeout=70).get("result", [])
        except Exception as exc:  # network blip -- back off and retry
            print(f"getUpdates failed: {exc}", file=sys.stderr)
            time.sleep(5)
            continue
        for update in updates:
            offset = update["update_id"] + 1
            bot.handle_update(update)


if __name__ == "__main__":
    raise SystemExit(main())
