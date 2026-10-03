import pathlib
import subprocess
from types import SimpleNamespace

import pytest

from cdcx import telegram_bot as tb

REPORT = (pathlib.Path(__file__).parent / "fixtures" / "xrp_cdcx_ai_report.txt").read_text()
ME = 8814026148


# --- parsing / safety ----------------------------------------------------------

@pytest.mark.parametrize("text,name,symbol", [
    ("/status XRP/USD", "status", "XRP/USD"),
    ("/analyze xrp/usd", "analyze", "XRP/USD"),
    ("/chart SPY", "chart", "SPY"),
    ("/status@CdcxBot BRK.B", "status", "BRK.B"),
    ("/help", "help", None),
    ("/start", "help", None),
    ("/report", "report", None),
])
def test_parse_valid_commands(text, name, symbol):
    cmd = tb.parse_command(text)
    assert (cmd.name, cmd.symbol, cmd.error) == (name, symbol, None)


@pytest.mark.parametrize("text", [
    "/status XRP/USD;rm -rf ~", "/status $(whoami)", "/analyze ../../etc", "/status XRP/USD --execute",
    "/status XRP/USD SPY", "/execute XRP/USD", "/paper XRP/USD", "/claude do something", "hello",
])
def test_parse_refuses_anything_else(text):
    assert tb.parse_command(text).error


def test_analysis_never_executes():
    for symbol in ("XRP/USD", "SPY"):
        for structure in (True, False):
            argv = tb.analysis_argv(symbol, structure)
            assert "--execute" not in argv and "--live" not in argv


def test_crypto_and_equity_routing():
    assert tb.analysis_argv("XRP/USD", True) == [
        "cdcx-ai", "--symbol", "XRP/USD", "--timeframes", "1w,1d,4h,1h", "--structure"]
    assert tb.analysis_argv("SPY", True) == [
        "cdcx-equity", "--source", "robinhood", "--symbol", "SPY", "--timeframes", "1w,1d,4h,1h",
        "--structure-report"]
    assert tb.tradingview_symbol("XRP/USD") == "CRYPTOCOM:XRPUSD"
    assert tb.tradingview_symbol("SPY") == "SPY"


# --- report extraction (real cdcx-ai output) -------------------------------------

def test_extract_summary_from_real_report():
    s = tb.extract_summary(REPORT)
    assert s.splitlines()[1].strip() == "MULTI-TIMEFRAME SUMMARY -- XRP/USD"
    assert "1h          76.0    WATCH" in s
    assert "VOLUME PROFILE HIERARCHY" in s
    assert "STRUCTURE SETUP" not in s


def test_extract_decisions_one_line_per_timeframe():
    lines = tb.extract_decisions(REPORT).splitlines()
    assert [l.split()[0] for l in lines] == ["1W", "1D", "4H", "1H"]
    assert "RANGING" in lines[3] and "WATCH" in lines[3]


def test_extract_blocks():
    assert "SETUP: NO TRADE" in tb.extract_block(REPORT, "STRUCTURE SETUP")
    vp = tb.extract_block(REPORT, "MULTI-TIMEFRAME STRUCTURE / VP SUMMARY")
    assert "VP-BOS CONFIRMED: 0/4" in vp and "BOS-FAILED:       0/4" in vp


def test_chunks_respect_limit_and_keep_everything():
    text = "\n".join(f"line {i} " + "x" * 50 for i in range(300)) + "\n" + "y" * 9000
    chunks = tb._chunks(text, 4000)
    assert all(len(c) <= 4000 for c in chunks)
    assert "".join(chunks) == text


# --- bot behaviour (fake Telegram API, fake subprocess) ---------------------------

class FakeApi:
    def __init__(self):
        self.texts, self.uploads, self.tags = [], [], []  # tags: (kind, source, symbol) per send

    def send_text(self, chat_id, text, pre=False, source=None, symbol=None):
        self.texts.append((chat_id, text, pre))
        self.tags.append(("text", source, symbol))

    def upload(self, method, chat_id, field, path, caption="", source=None, symbol=None):
        self.uploads.append((method, chat_id, path.name, caption))
        self.tags.append((method, source, symbol))


def _update(text, chat_id=ME):
    return {"update_id": 1, "message": {"chat": {"id": chat_id}, "text": text}}


def _bot(tmp_path, runner=None, chart=lambda s, tf: None):
    def default_runner(argv, **kw):
        return SimpleNamespace(returncode=0, stdout=REPORT, stderr="")
    return tb.Bot(FakeApi(), {ME}, tmp_path, runner=runner or default_runner, chart=chart)


def test_unlisted_chat_is_ignored_silently(tmp_path):
    calls = []
    bot = _bot(tmp_path, runner=lambda argv, **kw: calls.append(argv))
    bot.handle_update(_update("/analyze XRP/USD", chat_id=12345))
    assert bot.api.texts == [] and bot.api.uploads == [] and calls == []


def test_status_sends_summary_only(tmp_path):
    seen = []
    bot = _bot(tmp_path, runner=lambda argv, **kw: seen.append(argv) or SimpleNamespace(
        returncode=0, stdout=REPORT, stderr=""))
    bot.handle_update(_update("/status XRP/USD"))
    assert "--structure" not in seen[0]
    body = bot.api.texts[-1][1]
    assert "MULTI-TIMEFRAME SUMMARY" in body and "1H  WATCH" in body
    assert bot.api.uploads == []


def test_analyze_sends_summary_report_file_and_chart(tmp_path):
    shot = tmp_path / "chart.png"
    shot.write_bytes(b"png")
    bot = _bot(tmp_path, chart=lambda s, tf: shot)
    bot.handle_update(_update("/analyze XRP/USD"))
    body = "\n".join(t[1] for t in bot.api.texts)
    assert "MULTI-TIMEFRAME SUMMARY" in body and "SETUP: NO TRADE" in body and "VP-BOS CONFIRMED" in body
    assert "not a sell signal" in body
    assert [u[0] for u in bot.api.uploads] == ["sendDocument", "sendPhoto"]
    assert bot.api.uploads[1][3] == "CRYPTOCOM:XRPUSD 1H"


def test_chart_unavailable_is_reported_not_raised(tmp_path):
    bot = _bot(tmp_path, chart=lambda s, tf: None)
    bot.handle_update(_update("/chart XRP/USD"))
    assert "Chart unavailable" in bot.api.texts[-1][1]


def test_failures_and_timeouts_are_reported(tmp_path):
    def boom(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 300)
    bot = _bot(tmp_path, runner=boom)
    bot.handle_update(_update("/status XRP/USD"))
    assert "timed out" in bot.api.texts[-1][1]

    bot = _bot(tmp_path, runner=lambda argv, **kw: SimpleNamespace(returncode=1, stdout="", stderr="boom"))
    bot.handle_update(_update("/status XRP/USD"))
    assert "No summary produced" in bot.api.texts[-1][1] and "boom" in bot.api.texts[-1][1]


def test_bad_command_gets_a_helpful_reply(tmp_path):
    bot = _bot(tmp_path)
    bot.handle_update(_update("/execute XRP/USD"))
    assert "Unknown command /execute" in bot.api.texts[-1][1]


def test_allowed_ids_parsing():
    from cdcx.telegram_send import parse_chat_ids
    assert parse_chat_ids("8814026148, -100123,abc,") == (8814026148, -100123)
