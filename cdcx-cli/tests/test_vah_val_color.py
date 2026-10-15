"""VAH is red and VAL is green (user's choice, 2026-10-15) in the MARKET STRUCTURE report and the
STRUCTURE map -- ANSI only when forced, the plain-text (red)/(green) label always."""

from cdcx.structure_levels import StructureMap, format_structure_map
from cdcx.structure_report import build_structure_report, format_structure_report
from cdcx.utils.color import GREEN, RED, colorize_val, colorize_vah

from test_structure_report import _flat_range_series


def _line(out, prefix):
    return next(l for l in out.splitlines() if prefix in l)


def test_vah_red_val_green_when_color_forced(monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert RED in colorize_vah("VAH") and GREEN in colorize_val("VAL")
    out = format_structure_report(build_structure_report("XRP/USD", "1h", *_flat_range_series()))
    assert RED in _line(out, "VAH:") and GREEN not in _line(out, "VAH:")
    assert GREEN in _line(out, "VAL:") and RED not in _line(out, "VAL:")


def test_plain_labels_without_color(monkeypatch):
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")
    out = format_structure_report(build_structure_report("XRP/USD", "1h", *_flat_range_series()))
    assert "\033[" not in out
    assert "(value area high, red)" in _line(out, "VAH:")
    assert "(value area low, green)" in _line(out, "VAL:")


def test_structure_map_labels(monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    smap = StructureMap(poc=1.36, resistance=1.39, support=1.32, fvgs=[], condition="inside", regime=None)
    out = format_structure_map("1H", smap)
    assert "Resistance / VAH (red)" in out and RED in _line(out, "VAH (red)")
    assert "Support / VAL (green)" in out and GREEN in _line(out, "VAL (green)")
