"""
telegram_bot.py
---------------
Read-only Telegram front end for cdcx: ask for an analysis from your phone,
get the report (and the TradingView chart) back.

    /status [SYMBOL]          multi-timeframe summary only (fast)
    /analyze [SYMBOL]         full --structure analysis + full report file + 1H chart
    /chart [SYMBOL] [TF]      TradingView chart screenshot (TF: 5M 15M 1H 4H 1D 1W; default 1H)
    /report                   the ChatGPT handoff packet (.ai/HANDOFF/packet_for_chatgpt.md)
    /report SYMBOL            the full cdcx report as a file
    /help

SYMBOL defaults to CDCX_TELEGRAM_DEFAULT_SYMBOL (XRP/USD). A crypto pair with a
slash (XRP/USD) runs cdcx-ai (Crypto.com); a ticker (SPY) runs cdcx-equity
--source robinhood.

SINGLE READER: this bot is the ONE program that calls getUpdates for its bot
token (`TelegramReader` below). Everything else -- including Claude Code --
sends through cdcx.telegram_send, which never reads. The bot refuses to start
while the Claude Code Telegram plugin is enabled for the same bot, because
that plugin also polls getUpdates and Telegram only allows one reader.

Deliberately NOT here: /paper, /execute, or anything that runs arbitrary
commands. This bot only runs the same read-only analysis commands you run by
hand -- never --execute -- so a leaked bot token can't trade or run code.
Messages from any chat not in CDCX_TELEGRAM_ALLOWED_CHAT_IDS are ignored.
Allowlisted text messages are also copied to data/telegram_inbox.db
(cdcx.telegram_inbox) for the read-only inbox MCP server; a failed copy never
stops the command.

Run:  cdcx-telegram bot   (or: python -m cdcx.telegram_bot, from cdcx-cli)
Standard library only (urllib) -- no extra package to install.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .telegram_inbox import INBOX_DB, TelegramInbox
from .telegram_send import (
    CDCX_CLI_DIR, TelegramConfig, TelegramConfigError, TelegramSender, _chunks, load_config,
)

REPO_DIR = CDCX_CLI_DIR.parent
TV_CLI_JS = CDCX_CLI_DIR / "tradingview-mcp" / "src" / "cli" / "index.js"

TIMEFRAMES = "1w,1d,4h,1h"
ANALYSIS_TIMEOUT_S = 300
DEFAULT_SYMBOL = "XRP/USD"

# Crypto pair (XRP/USD) or plain ticker (SPY, BRK.B). Anything else is refused
# before it gets near a subprocess -- args are also passed as a list, never a shell.
_SYMBOL_RE = re.compile(r"^(?:[A-Z0-9]{1,10}/[A-Z0-9]{2,6}|[A-Z]{1,5}(?:\.[A-Z])?)$")
# /chart timeframe -> TradingView resolution
CHART_TIMEFRAMES = {"5M": "5", "15M": "15", "1H": "60", "4H": "240", "1D": "D", "1W": "W"}

# 409 handling for the reader: exponential backoff, capped -- never a tight loop.
CONFLICT_BACKOFF_START_S = 5
CONFLICT_BACKOFF_MAX_S = 300
CONFLICT_ALERT_AFTER = 3  # consecutive 409s before telling the user on Telegram
ERROR_BACKOFF_MAX_S = 60

HELP = (
    "cdcx bot (read-only, never trades)\n\n"
    "/status [SYMBOL]      - multi-timeframe summary\n"
    "/analyze [SYMBOL]     - full analysis + report file + 1H chart\n"
    "/chart [SYMBOL] [TF]  - TradingView chart (TF: 5M 15M 1H 4H 1D 1W)\n"
    "/report               - ChatGPT handoff packet\n"
    "/report SYMBOL        - full cdcx report file\n\n"
    "SYMBOL: XRP/USD (crypto) or SPY (stock/ETF). Default: {default}"
)


def default_symbol() -> str:
    sym = (os.getenv("CDCX_TELEGRAM_DEFAULT_SYMBOL") or DEFAULT_SYMBOL).strip().upper()
    return sym if _SYMBOL_RE.match(sym) else DEFAULT_SYMBOL


@dataclass
class Command:
    name: str
    symbol: Optional[str] = None
    timeframe: Optional[str] = None
    error: Optional[str] = None


def parse_command(text: str, default: Optional[str] = None) -> Command:
    default = default or default_symbol()
    # Phone keyboards turn "XRP/USD" into "XRP / USD" or "XRP/ USD"; also drop
    # trailing punctuation autocorrect adds ("XRP/USD." / "SPY,").
    text = (text or "").strip()
    head, _, rest = text.partition(" ")
    rest = re.sub(r"\s*/\s*", "/", rest)
    parts = [p.rstrip(".,;:!?") for p in f"{head} {rest}".split()]
    if not parts or not parts[0].startswith("/"):
        return Command(name="", error="Send a command. /help lists them.")
    name = parts[0][1:].split("@", 1)[0].lower()  # "/status@MyBot" in group chats
    args = parts[1:]
    if name in ("help", "start"):
        return Command(name="help")
    if name not in ("status", "analyze", "chart", "report"):
        return Command(name=name, error=f"Unknown command /{name}. /help lists them.")
    if name == "report" and not args:
        return Command(name="report")  # the ChatGPT handoff packet

    timeframe = None
    if name == "chart":
        if len(args) > 2:
            return Command(name=name, error="Usage: /chart [SYMBOL] [TF]  e.g. /chart XRP/USD 4H")
        if args and args[-1].upper() in CHART_TIMEFRAMES:
            timeframe = args.pop().upper()
        timeframe = timeframe or "1H"
    if len(args) > 1:
        return Command(name=name, error=f"Usage: /{name} [SYMBOL]  (e.g. /{name} XRP/USD or /{name} SPY)")
    symbol = args[0].upper() if args else default
    if not _SYMBOL_RE.match(symbol):
        return Command(name=name, error=f"'{args[0]}' isn't a symbol I accept (e.g. XRP/USD or SPY).")
    return Command(name=name, symbol=symbol, timeframe=timeframe)


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


def take_chart(symbol: str, timeframe: str = "1H", runner=subprocess.run) -> Optional[Path]:
    """Set TradingView to SYMBOL/TIMEFRAME and screenshot it via the tv CLI.
    Uses Windows node.exe: from WSL, Windows' localhost CDP port is only
    reliably reachable by a Windows process."""
    node = "node.exe" if os.path.exists("/proc/version") and "microsoft" in Path("/proc/version").read_text().lower() else "node"
    js = _to_windows_path(TV_CLI_JS) if node == "node.exe" else str(TV_CLI_JS)

    def tv(*args: str) -> dict:
        proc = runner([node, js, *args], capture_output=True, text=True, timeout=60)
        return json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {"success": False}

    if not tv("symbol", tradingview_symbol(symbol)).get("success"):
        return None
    tv("timeframe", CHART_TIMEFRAMES.get(timeframe, "60"))
    time.sleep(2)
    tv("ui", "keyboard", "r", "--alt")  # Alt+R: reset the view so the latest bars fill the chart
    time.sleep(2)  # let it render
    # "full", not "chart": the chart region crops off the right-hand price scale and its level labels.
    shot = tv("screenshot", "--region", "full", "--output", f"telegram_{symbol.replace('/', '')}_{timeframe.lower()}")
    path = shot.get("file_path")
    return Path(_to_wsl_path(path)) if path else None


def _to_windows_path(p: Path) -> str:
    return subprocess.run(["wslpath", "-w", str(p)], capture_output=True, text=True).stdout.strip() or str(p)


def _to_wsl_path(p: str) -> str:
    if re.match(r"^[A-Za-z]:\\", p):
        return subprocess.run(["wslpath", "-u", p], capture_output=True, text=True).stdout.strip() or p
    return p


# --- the single reader ------------------------------------------------------------

class TelegramReader:
    """The ONLY class in cdcx that calls getUpdates. Exactly one running
    instance per bot token -- see the module docstring."""

    def __init__(self, config: TelegramConfig, opener: Callable = urllib.request.urlopen):
        self._url = f"https://api.telegram.org/bot{config.token}/getUpdates"
        self._open = opener

    def get_updates(self, offset: Optional[int], timeout: int = 50) -> list[dict]:
        data = json.dumps({"timeout": timeout, "offset": offset}).encode()
        req = urllib.request.Request(self._url, data=data, headers={"Content-Type": "application/json"})
        with self._open(req, timeout=timeout + 20) as resp:
            return json.loads(resp.read().decode()).get("result", [])


def _is_conflict(exc: Exception) -> bool:
    return isinstance(exc, urllib.error.HTTPError) and exc.code == 409


def poll_forever(reader: TelegramReader, bot: "Bot", sender: TelegramSender,
                 sleep: Callable[[float], None] = time.sleep, max_iterations: Optional[int] = None) -> None:
    """Long-poll loop. A 409 means ANOTHER program is reading this bot's
    updates -- this bot is then NOT receiving. It is logged loudly every time,
    retried with exponential backoff (5s doubling to 5 min, never a tight
    loop), and after CONFLICT_ALERT_AFTER in a row the user is told on Telegram."""
    offset, conflicts, errors, alerted, n = None, 0, 0, False, 0
    while max_iterations is None or n < max_iterations:
        n += 1
        try:
            updates = reader.get_updates(offset)
        except Exception as exc:  # network blip or 409 -- back off, never spin
            if _is_conflict(exc):
                conflicts += 1
                delay = min(CONFLICT_BACKOFF_START_S * 2 ** (conflicts - 1), CONFLICT_BACKOFF_MAX_S)
                print(f"{time.strftime('%H:%M:%S')} 409 CONFLICT: another program is reading this bot's updates "
                      f"-- this bot is NOT receiving (#{conflicts}, retry in {delay}s). Only one reader is allowed.",
                      file=sys.stderr, flush=True)
                if conflicts >= CONFLICT_ALERT_AFTER and not alerted:
                    alerted = True
                    try:
                        sender.send_message("cdcx bot: another program is reading this bot's messages (409 Conflict), "
                                            "so your commands aren't reaching me. Stop the other reader.")
                    except Exception:
                        pass
            else:
                errors += 1
                delay = min(CONFLICT_BACKOFF_START_S * errors, ERROR_BACKOFF_MAX_S)
                print(f"{time.strftime('%H:%M:%S')} getUpdates failed ({type(exc).__name__}); retry in {delay}s",
                      file=sys.stderr, flush=True)
            sleep(delay)
            continue
        if conflicts or errors:
            print(f"{time.strftime('%H:%M:%S')} Telegram receive: recovered", flush=True)
        conflicts, errors, alerted = 0, 0, False
        for update in updates:
            offset = update["update_id"] + 1
            kinds = [k for k in update if k != "update_id"]
            chat = ((update.get("message") or update.get("edited_message") or {}).get("chat") or {}).get("id")
            print(f"{time.strftime('%H:%M:%S')} update {update['update_id']}: {','.join(kinds)} chat={chat}", flush=True)
            bot.handle_update(update)


# --- command handling ----------------------------------------------------------

class Bot:
    def __init__(self, api: TelegramSender, allowed_chat_ids: set[int], workdir: Path,
                 runner=subprocess.run, chart=take_chart, inbox: Optional[TelegramInbox] = None):
        self.api, self.allowed, self.workdir = api, allowed_chat_ids, workdir
        self.runner, self.chart, self.inbox = runner, chart, inbox

    def handle_update(self, update: dict) -> None:
        message = update.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        if chat_id is None or not message.get("text"):
            return
        if chat_id not in self.allowed:
            print(f"ignored message from unlisted chat {chat_id}", file=sys.stderr)
            return
        if self.inbox is not None:  # a local copy for the read-only inbox MCP; must never block the command
            try:
                self.inbox.store_message(update)
            except Exception as exc:
                print(f"inbox store failed ({type(exc).__name__}: {exc}); command still handled",
                      file=sys.stderr, flush=True)
        cmd = parse_command(message["text"])
        print(f"{time.strftime('%H:%M:%S')} /{cmd.name or '?'} {cmd.symbol or ''} {cmd.timeframe or ''}"
              f"{'  -> ' + cmd.error if cmd.error else ''}", flush=True)
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
        self.api.send_text(chat_id, HELP.format(default=default_symbol()))

    def _cmd_status(self, chat_id: int, cmd: Command) -> None:
        self.api.send_text(chat_id, f"Running {cmd.symbol} summary...")
        code, report = run_analysis(cmd.symbol, structure=False, runner=self.runner)
        summary = extract_summary(report)
        if not summary:
            self.api.send_text(chat_id, f"No summary produced (exit {code}):\n{report[-1500:]}", pre=True)
            return
        self.api.send_text(chat_id, f"{summary}\n\n{extract_decisions(report)}", pre=True)

    def _full_report(self, chat_id: int, symbol: str) -> Optional[tuple[str, Path]]:
        code, report = run_analysis(symbol, structure=True, runner=self.runner)
        if not extract_summary(report):
            self.api.send_text(chat_id, f"No summary produced (exit {code}):\n{report[-1500:]}", pre=True)
            return None
        report_file = self.workdir / f"{symbol.replace('/', '')}_{time.strftime('%Y%m%d_%H%M')}.txt"
        report_file.write_text(report)
        return report, report_file

    def _cmd_analyze(self, chat_id: int, cmd: Command) -> None:
        self.api.send_text(chat_id, f"Running full {cmd.symbol} analysis (about a minute)...")
        result = self._full_report(chat_id, cmd.symbol)
        if result is None:
            return
        report, report_file = result
        parts = [extract_summary(report), extract_decisions(report),
                 extract_block(report, "STRUCTURE SETUP"),
                 extract_block(report, "MULTI-TIMEFRAME STRUCTURE / VP SUMMARY"),
                 extract_block(report, "AVP BULLISH REJECTION")]
        self.api.send_text(chat_id, "\n\n".join(p for p in parts if p), pre=True)
        self.api.send_text(chat_id, "NO TRADE = insufficient confirmation, not a sell signal. Not financial advice.")
        self.api.upload("sendDocument", chat_id, "document", report_file, caption="Full cdcx report")
        self._send_chart(chat_id, cmd.symbol, "1H")

    def _cmd_chart(self, chat_id: int, cmd: Command) -> None:
        self._send_chart(chat_id, cmd.symbol, cmd.timeframe or "1H", announce=True)

    def _send_chart(self, chat_id: int, symbol: str, timeframe: str, announce: bool = False) -> None:
        if announce:
            self.api.send_text(chat_id, f"Taking {symbol} {timeframe} chart...")
        path = self.chart(symbol, timeframe)
        if path and path.exists():
            self.api.upload("sendPhoto", chat_id, "photo", path, caption=f"{tradingview_symbol(symbol)} {timeframe}")
        else:
            self.api.send_text(chat_id, "Chart unavailable -- is TradingView running with CDP (port 9222)?")

    def _cmd_report(self, chat_id: int, cmd: Command) -> None:
        if cmd.symbol:  # /report SYMBOL -> the full cdcx report as a file
            self.api.send_text(chat_id, f"Building full {cmd.symbol} report (about a minute)...")
            result = self._full_report(chat_id, cmd.symbol)
            if result:
                self.api.upload("sendDocument", chat_id, "document", result[1], caption=f"Full cdcx report -- {cmd.symbol}")
            return
        proc = self.runner([sys.executable, str(REPO_DIR / ".ai" / "prepare_handoff.py")], cwd=REPO_DIR,
                           capture_output=True, text=True, timeout=120)
        packet = REPO_DIR / ".ai" / "HANDOFF" / "packet_for_chatgpt.md"
        status = (proc.stdout or "").strip().splitlines()[-1:] or ["(no output)"]
        if not packet.exists():
            self.api.send_text(chat_id, f"Packet not built: {status[0]}")
            return
        self.api.upload("sendDocument", chat_id, "document", packet, caption=f"ChatGPT handoff packet -- {status[0]}")


# --- single-reader guard -----------------------------------------------------------

CLAUDE_TELEGRAM_PLUGIN = "telegram@claude-plugins-official"


def claude_plugin_reads_same_bot(token: str, claude_dir: Optional[Path] = None,
                                 project_dirs: tuple[Path, ...] = ()) -> bool:
    """True when the Claude Code Telegram plugin is enabled (user, or any
    project/local settings in `project_dirs`) AND configured with this same bot
    token. That plugin polls getUpdates with no receive-off switch, so it
    would be a second reader."""
    claude_dir = claude_dir or Path(os.getenv("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    enabled = False
    settings_files = [claude_dir / "settings.json"]
    for d in project_dirs:
        settings_files += [d / ".claude" / "settings.json", d / ".claude" / "settings.local.json"]
    for f in settings_files:  # later files override earlier ones, like Claude Code's own precedence
        try:
            value = json.loads(f.read_text()).get("enabledPlugins", {}).get(CLAUDE_TELEGRAM_PLUGIN)
        except (OSError, ValueError):
            continue
        if value is not None:
            enabled = bool(value)
    if not enabled:
        return False
    plugin_env = claude_dir / "channels" / "telegram" / ".env"
    try:
        lines = plugin_env.read_text().splitlines()
    except OSError:
        return False
    return any(l.split("=", 1)[1].strip().strip("'\"") == token
               for l in lines if l.strip().startswith("TELEGRAM_BOT_TOKEN="))


def main() -> int:
    try:
        config = load_config()
    except TelegramConfigError as exc:
        print(f"{exc} See cdcx/telegram_bot.py's docstring.", file=sys.stderr)
        return 1
    here = Path.cwd()
    if claude_plugin_reads_same_bot(config.token, project_dirs=tuple([*reversed(here.parents), here])):
        print("REFUSING TO START: the Claude Code Telegram plugin is enabled for this same bot and also reads\n"
              "getUpdates -- Telegram allows exactly one reader. Disable it first:\n"
              f"  ~/.claude/settings.json -> \"enabledPlugins\": {{\"{CLAUDE_TELEGRAM_PLUGIN}\": false}}\n"
              "then restart Claude Code (or stop its running 'bun server.ts' process).", file=sys.stderr)
        return 1
    workdir = CDCX_CLI_DIR / "trading" / "telegram_reports"
    workdir.mkdir(parents=True, exist_ok=True)
    sender = TelegramSender(config)
    me = sender.call("getMe").get("result", {})
    try:
        inbox, inbox_status = TelegramInbox(), f"ENABLED ({INBOX_DB})"
    except Exception as exc:  # the inbox is optional; the bot runs without it
        inbox, inbox_status = None, f"DISABLED ({type(exc).__name__}: {exc})"
    print(f"Telegram CDCX bot started: @{me.get('username')}\n"
          "Telegram receive: ENABLED (sole getUpdates reader)\n"
          "Telegram outbound sending: ENABLED\n"
          f"Telegram inbox: {inbox_status}\n"
          f"Answering chats {list(config.chat_ids)}; default symbol {default_symbol()}. Ctrl+C to stop.", flush=True)
    poll_forever(TelegramReader(config), Bot(sender, set(config.chat_ids), workdir, inbox=inbox), sender)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
