"""
Read-only RANGE MODE PREVIEW (cli._print_range_setup_preview) and the VP-BOS
PENDING explanation line. Both are display-only: the preview writes no journal
entry and opens no trade, and the note only appears when a row is PENDING.
"""
from types import SimpleNamespace

from cdcx import cli, journal, vp_bos


def _sig(regime, entry=1.4890):
    return SimpleNamespace(regime=SimpleNamespace(regime=regime), entry=entry)


def test_range_entry_timeframe_is_the_fastest_and_only_if_ranging():
    assert cli._range_entry_timeframe({"1h": _sig("ranging"), "4h": _sig("trending")}) == "1h"
    assert cli._range_entry_timeframe({"1h": _sig("transitional"), "4h": _sig("ranging")}) is None
    assert cli._range_entry_timeframe({"1h": None, "4h": _sig("ranging")}) == "4h"
    assert cli._range_entry_timeframe({}) is None


def test_preview_prints_the_setup_and_writes_nothing(monkeypatch, capsys):
    vp = SimpleNamespace(poc=1.4887, vah=1.5114, val=1.4796)
    monkeypatch.setattr(cli, "_range_setup_inputs", lambda s, tf, n: (None, [], [], [40.0, 41.0], vp, []))
    def boom(*a, **k):
        raise AssertionError("preview must not write the journal or open a trade")
    for name in ("write_signal", "write_rejected", "write_simulated_order"):
        monkeypatch.setattr(journal, name, boom)
    cli._print_range_setup_preview("XRP/USD", {"1h": _sig("ranging"), "4h": _sig("ranging")}, 200)
    out = capsys.readouterr().out
    assert "RANGE MODE PREVIEW (1H, read-only)" in out and "RANGING STRATEGY SETUP" in out
    assert "No journal entry, no paper trade." in out


def test_preview_is_silent_when_not_ranging(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_range_setup_inputs", lambda *a: (_ for _ in ()).throw(AssertionError("no fetch")))
    cli._print_range_setup_preview("XRP/USD", {"1h": _sig("transitional")}, 200)
    assert capsys.readouterr().out == ""


def _row(signal):
    return SimpleNamespace(structure="HH/HL/LH/LL", bos_label="BULL PENDING" if signal == "BOS-PENDING" else "NONE",
                           level_price=1.5097 if signal == "BOS-PENDING" else None,
                           acceptance="NOT CONFIRMED" if signal == "BOS-PENDING" else "--",
                           poc_direction="flat", result="PENDING" if signal == "BOS-PENDING" else "NONE",
                           signal=signal, raw_note=None)


def test_pending_note_only_when_a_row_is_pending():
    with_pending = vp_bos.format_vp_bos_section("XRP/USD", {"4h": _row("BOS-PENDING"), "1h": _row("NONE")})
    without = vp_bos.format_vp_bos_section("XRP/USD", {"4h": _row("NONE"), "1h": _row("NONE")})
    assert "PENDING = the swing broke" in with_pending
    assert "PENDING = the swing broke" not in without
