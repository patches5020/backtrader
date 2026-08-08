"""
Covers cdcx/utils/color.py and its wiring into engine.format_report():
the plain-text [GREEN]/[YELLOW]/[RED] tag is always present next to the
emoji regime icon, and ANSI color only appears when explicitly forced
(mirroring the FORCE_COLOR / NO_COLOR / non-TTY conventions) -- see
color.py's module docstring for why the tag exists (some WSL/mintty
terminals don't render the emoji glyph at all).
"""

import os

from cdcx.engine import analyze_ohlcv, format_report
from cdcx.exchange.cryptocom import OHLCV
from cdcx.utils.color import REGIME_TAGS, colorize, colorize_regime


def _make_ohlcv(closes):
    n = len(closes)
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    volumes = [100.0] * n
    return OHLCV(timestamps=list(range(n)), opens=closes, highs=highs, lows=lows, closes=closes, volumes=volumes)


def test_regime_tags_cover_every_regime_value():
    assert set(REGIME_TAGS) == {"trending", "ranging", "transitional"}
    assert REGIME_TAGS["trending"] == "GREEN"
    assert REGIME_TAGS["ranging"] == "YELLOW"
    assert REGIME_TAGS["transitional"] == "RED"


def test_colorize_is_a_noop_without_force_color(monkeypatch):
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")
    assert colorize("text", "\033[31m") == "text"
    assert colorize_regime("text", "transitional") == "text"


def test_colorize_wraps_text_when_force_color_set(monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.delenv("NO_COLOR", raising=False)
    out = colorize_regime("NO TRADE", "transitional")
    assert out != "NO TRADE"
    assert "NO TRADE" in out
    assert "\033[" in out


def test_unknown_regime_passes_through_uncolored(monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert colorize_regime("text", "not-a-real-regime") == "text"


def test_format_report_always_includes_the_plain_text_regime_tag(monkeypatch):
    # Regardless of color/TTY state, the bracketed tag must be present so the
    # regime reads correctly even when neither emoji nor ANSI color renders.
    monkeypatch.setenv("NO_COLOR", "1")
    data = _make_ohlcv([100 + i * 0.1 for i in range(60)])
    signal = analyze_ohlcv("BTC/USDT", data)
    report = format_report(signal)
    expected_tag = f"[{REGIME_TAGS[signal.regime.regime]}]"
    assert expected_tag in report
    assert signal.regime.icon in report
