"""
color.py
--------
Minimal ANSI color helper for terminal output. No dependency, no
terminfo lookup -- just the 3 codes this project actually needs (the
market-regime traffic light) plus the standard opt-out conventions:

- Colors are suppressed automatically when stdout is not a TTY (piped to
  a file/log, captured by a test, etc.).
- Respects the NO_COLOR convention (https://no-color.org/): any non-empty
  NO_COLOR env var disables color regardless of TTY status.
- FORCE_COLOR=1 overrides both checks, for CI logs or terminals that
  misreport isatty() (some WSL/mintty setups do).

The emoji regime icons (see regime.py) are the primary indicator and are
kept as-is; this is a fallback channel for terminals/fonts that don't
render the emoji glyphs (a real symptom seen in some WSL/mintty setups),
since ANSI SGR color codes are far more universally supported than color
emoji fonts.
"""

from __future__ import annotations

import os
import sys

RESET = "\033[0m"
RED = "\033[31m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
BOLD = "\033[1m"


def _color_enabled() -> bool:
    if os.environ.get("FORCE_COLOR"):
        return True
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def colorize(text: str, code: str) -> str:
    """Wrap `text` in the given ANSI SGR code, bolded, if color is enabled;
    otherwise return `text` unchanged."""
    if not _color_enabled():
        return text
    return f"{BOLD}{code}{text}{RESET}"


# regime.Regime ("trending" | "ranging" | "transitional") -> ANSI code.
# Mirrors the emoji traffic light in regime.py: green trending, yellow
# ranging, red transitional/no-trade.
REGIME_COLORS = {
    "trending": GREEN,
    "ranging": YELLOW,
    "transitional": RED,
}

# Plain-text tag shown alongside the emoji so the regime is still legible
# even when neither the emoji glyph nor ANSI color renders.
REGIME_TAGS = {
    "trending": "GREEN",
    "ranging": "YELLOW",
    "transitional": "RED",
}


def colorize_regime(text: str, regime: str) -> str:
    """Colorize `text` using the traffic-light color for `regime`
    ("trending"/"ranging"/"transitional"). Unknown regimes pass through
    uncolored."""
    code = REGIME_COLORS.get(regime)
    if code is None:
        return text
    return colorize(text, code)
