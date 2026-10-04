"""
Telegram bot: /status and /analyze take optional timeframes (1m..1w, comma- or
space-separated), /chart takes 1M..1W. Only whitelisted tokens reach argv, the
default stays 1w,1d,4h,1h, and the bot still never runs --execute.
"""
from types import SimpleNamespace

import pytest

from cdcx import telegram_bot as tb


@pytest.mark.parametrize("text,symbol,tfs", [
    ("/status XRP/USD 15m", "XRP/USD", ("15m",)),
    ("/status 15m", "XRP/USD", ("15m",)),
    ("/status XRP/USD 5m 15m 1h", "XRP/USD", ("5m", "15m", "1h")),
    ("/analyze 5m,15m,45m", "XRP/USD", ("5m", "15m", "45m")),
    ("/analyze XRP/USD 1m,5m,10m,15m,30m,45m,1h,4h,1d,1w", "XRP/USD",
     ("1m", "5m", "10m", "15m", "30m", "45m", "1h", "4h", "1d", "1w")),
    ("/status xrp / usd 45M", "XRP/USD", ("45m",)),            # phone spacing + capital M = minutes
    ("/status XRP/USD 15m,15m 15m", "XRP/USD", ("15m",)),        # de-duplicated
    ("/status XRP/USD", "XRP/USD", None),                         # default unchanged
    ("/status SPY 30m", "SPY", ("30m",)),
])
def test_status_and_analyze_timeframes(text, symbol, tfs):
    cmd = tb.parse_command(text, default="XRP/USD")
    assert (cmd.symbol, cmd.timeframes, cmd.error) == (symbol, tfs, None)


@pytest.mark.parametrize("text", ["/status XRP/USD 2m", "/status XRP/USD 15m;rm -rf ~", "/analyze 15m,$(id)",
                                  "/status XRP/USD 15m SPY", "/status 3w"])
def test_unknown_timeframes_and_junk_are_refused(text):
    assert tb.parse_command(text, default="XRP/USD").error


@pytest.mark.parametrize("text,tf", [("/chart XRP/USD 45M", "45M"), ("/chart 10m", "10M"), ("/chart 1m", "1M"),
                                     ("/chart XRP/USD 30M", "30M"), ("/chart", "1H")])
def test_chart_accepts_minute_timeframes(text, tf):
    cmd = tb.parse_command(text, default="XRP/USD")
    assert cmd.timeframe == tf and cmd.error is None
    assert tf in tb.CHART_TIMEFRAMES


def test_argv_uses_requested_or_default_timeframes_and_never_executes():
    assert tb.analysis_argv("XRP/USD", False) == ["cdcx-ai", "--symbol", "XRP/USD", "--timeframes", "1w,1d,4h,1h"]
    argv = tb.analysis_argv("XRP/USD", True, ("5m", "15m", "45m"))
    assert argv == ["cdcx-ai", "--symbol", "XRP/USD", "--timeframes", "5m,15m,45m", "--structure"]
    assert tb.analysis_argv("SPY", False, ("30m",))[-2:] == ["--timeframes", "30m"]
    assert "--execute" not in argv and "--live" not in argv
    with pytest.raises(ValueError):
        tb.analysis_argv("XRP/USD", False, ("15m;rm",))


def test_analyze_chart_uses_the_fastest_requested_timeframe():
    assert tb._chart_tf(None) == "1H"
    assert tb._chart_tf(("1h", "45m", "5m")) == "5M"


class FakeApi:
    def __init__(self):
        self.texts = []

    def send_text(self, chat_id, text, pre=False, source=None, symbol=None):
        self.texts.append(text)

    def upload(self, *a, **k):
        pass


def test_status_runs_cdcx_with_the_requested_timeframes(tmp_path):
    seen = []

    def runner(argv, **kw):
        seen.append(argv)
        return SimpleNamespace(returncode=0, stdout="MULTI-TIMEFRAME SUMMARY -- XRP/USD\n", stderr="")
    bot = tb.Bot(FakeApi(), {1}, tmp_path, runner=runner, chart=lambda s, tf: None)
    bot.handle_update({"update_id": 1, "message": {"message_id": 1, "chat": {"id": 1}, "text": "/status XRP/USD 15m,45m"}})
    assert seen == [["cdcx-ai", "--symbol", "XRP/USD", "--timeframes", "15m,45m"]]
    assert "15m,45m" in bot.api.texts[0]
