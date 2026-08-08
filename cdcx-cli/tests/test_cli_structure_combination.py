"""
--structure used to be either a fully separate top-level command, or (in a
first pass at this) a whole extra section merely appended after the normal
report. Neither actually combined the two systems: the user wanted each
timeframe's indicator report and that same timeframe's structure levels
merged into ONE block per timeframe, with the final 1W/1D/4H/1H LONG/SHORT
trigger evaluation printed once at the end.

These tests stub out the network-bound pieces (_run_single, _handle_execute,
_fetch_structure_map) and verify main()'s wiring: a requested timeframe that
matches one of the four structural roles (1w/1d/4h/1h) gets its structure
block printed immediately after that timeframe's own report (not in a
separate section), a requested timeframe that ISN'T one of those roles gets
no structure block at all, the final combined setup section only prints once
per run (after everything else), and repeated timeframes across the report
loop and the final section reuse the same fetch instead of hitting the
exchange twice for the same timeframe -- same monkeypatch-the-internals
style as test_execute_integration.py.
"""

from types import SimpleNamespace

from cdcx import cli, engine as engine_module


def _fake_signal(total_score=80, signal="BUY"):
    return SimpleNamespace(total_score=total_score, signal=signal)


def _fake_ohlcv_data(tf):
    return SimpleNamespace(
        highs=[1.0], lows=[1.0], closes=[1.0], opens=[1.0], volumes=[1.0], timeframe=tf,
    )


def _make_fetch_structure_map(fetch_calls):
    """A fake _fetch_structure_map that records each (timeframe) it's asked to
    fetch and returns a distinct, cheaply-identifiable StructureMap stand-in."""
    def fake(symbol, timeframe, limit):
        fetch_calls.append(timeframe)
        smap = SimpleNamespace(poc=1.0, resistance=1.0, support=1.0, fvgs=[], condition="ranging")
        return smap, _fake_ohlcv_data(timeframe)
    return fake


def test_timeframe_matching_a_structural_role_gets_a_merged_block(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_run_single", lambda symbol, timeframe, limit: _fake_signal())
    monkeypatch.setattr(engine_module, "format_report", lambda signal: f"REPORT")
    fetch_calls = []
    monkeypatch.setattr(cli, "_fetch_structure_map", _make_fetch_structure_map(fetch_calls))
    monkeypatch.setattr(
        cli.structure_levels, "format_structure_map",
        lambda name, smap: f"STRUCTURE BLOCK ({name})",
    )
    monkeypatch.setattr(
        cli.structure_strategy, "evaluate_structure_setup",
        lambda *a, **kw: SimpleNamespace(),
    )
    monkeypatch.setattr(cli.structure_strategy, "format_structure_setup", lambda setup: "FINAL SETUP SECTION")

    result = cli.main(["--symbol", "BTC/USDT", "--timeframe", "1h", "--structure"])
    out = capsys.readouterr().out

    assert result == 0
    # 1h is a structural role -> its block is merged in right after the report,
    # then reused (not re-fetched) for the final combined setup section, which
    # still needs 1w/1d/4h too.
    assert fetch_calls == ["1h", "1w", "1d", "4h"]
    assert "STRUCTURE BLOCK (1H (entry confirmation))" in out
    assert out.index("REPORT") < out.index("STRUCTURE BLOCK (1H (entry confirmation))")
    assert "FINAL SETUP SECTION" in out
    # the merged per-timeframe block prints before the final combined section
    assert out.index("STRUCTURE BLOCK (1H (entry confirmation))") < out.index("FINAL SETUP SECTION")


def test_timeframe_not_a_structural_role_gets_no_merged_block(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_run_single", lambda symbol, timeframe, limit: _fake_signal())
    monkeypatch.setattr(engine_module, "format_report", lambda signal: "REPORT")
    fetch_calls = []
    monkeypatch.setattr(cli, "_fetch_structure_map", _make_fetch_structure_map(fetch_calls))
    monkeypatch.setattr(
        cli.structure_levels, "format_structure_map",
        lambda name, smap: f"STRUCTURE BLOCK ({name})",
    )
    monkeypatch.setattr(
        cli.structure_strategy, "evaluate_structure_setup",
        lambda *a, **kw: SimpleNamespace(),
    )
    monkeypatch.setattr(cli.structure_strategy, "format_structure_setup", lambda setup: "FINAL SETUP SECTION")

    result = cli.main(["--symbol", "BTC/USDT", "--timeframe", "15m", "--structure"])
    out = capsys.readouterr().out

    assert result == 0
    # 15m isn't one of the four roles -- no merged block for it, but the final
    # combined section still needs to fetch all four roles fresh.
    assert "STRUCTURE BLOCK" not in out
    assert fetch_calls == ["1w", "1d", "4h", "1h"]
    assert "FINAL SETUP SECTION" in out


def test_without_structure_flag_nothing_structural_is_fetched(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_run_single", lambda symbol, timeframe, limit: _fake_signal())
    monkeypatch.setattr(engine_module, "format_report", lambda signal: "REPORT")
    fetch_calls = []
    monkeypatch.setattr(cli, "_fetch_structure_map", _make_fetch_structure_map(fetch_calls))

    result = cli.main(["--symbol", "BTC/USDT", "--timeframe", "1h"])

    assert result == 0
    assert fetch_calls == []


def test_timeframes_run_merges_all_four_roles_and_reuses_fetches_for_final_section(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_run_single", lambda symbol, timeframe, limit: _fake_signal())
    monkeypatch.setattr(engine_module, "format_report", lambda signal: "REPORT")
    fetch_calls = []
    monkeypatch.setattr(cli, "_fetch_structure_map", _make_fetch_structure_map(fetch_calls))
    monkeypatch.setattr(
        cli.structure_levels, "format_structure_map",
        lambda name, smap: f"STRUCTURE BLOCK ({name})",
    )
    monkeypatch.setattr(
        cli.structure_strategy, "evaluate_structure_setup",
        lambda *a, **kw: SimpleNamespace(),
    )
    monkeypatch.setattr(cli.structure_strategy, "format_structure_setup", lambda setup: "FINAL SETUP SECTION")

    result = cli.main(["--symbol", "BTC/USDT", "--timeframes", "1h,4h,1d,1w", "--structure"])
    out = capsys.readouterr().out

    assert result == 0
    # all four roles already covered by the requested timeframes -> the final
    # section reuses every one of them, no extra fetches at all.
    assert fetch_calls == ["1h", "4h", "1d", "1w"]
    for role_label in ("1H (entry confirmation)", "4H (primary setup)", "1D (major volume structure)", "1W (major structure)"):
        assert f"STRUCTURE BLOCK ({role_label})" in out
    assert "FINAL SETUP SECTION" in out
    # the final combined section prints once, after the summary table / last block
    assert out.count("FINAL SETUP SECTION") == 1
    assert out.rindex("STRUCTURE BLOCK") < out.index("FINAL SETUP SECTION")


def test_timeframes_execute_run_structure_section_prints_after_execute_plan(monkeypatch, capsys):
    order = []

    monkeypatch.setattr(cli, "_run_single", lambda symbol, timeframe, limit: _fake_signal())
    monkeypatch.setattr(engine_module, "format_report", lambda signal: "REPORT")

    def fake_execute(symbol, balance, risk_pct, results, limit, live, instrument_name_override, news_imminent):
        order.append("execute")
        print("EXECUTE PLAN HERE")
        return 0

    def fake_setup_section(symbol, limit, cache):
        order.append("structure_setup")
        print("FINAL SETUP SECTION")
        return True

    monkeypatch.setattr(cli, "_handle_execute", fake_execute)
    monkeypatch.setattr(cli, "_print_merged_structure_block", lambda *a, **kw: None)
    monkeypatch.setattr(cli, "_print_structure_setup_section", fake_setup_section)

    result = cli.main([
        "--symbol", "BTC/USDT", "--timeframes", "1h,4h",
        "--execute", "--balance", "10000", "--structure",
    ])

    out = capsys.readouterr().out
    assert result == 0
    assert order == ["execute", "structure_setup"]
    assert out.index("EXECUTE PLAN HERE") < out.index("FINAL SETUP SECTION")
