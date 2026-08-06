"""
--structure used to be a separate, mutually-exclusive top-level command
(cli.main() returned immediately from a dedicated _handle_structure branch,
never reaching the normal engine report). It now composes with whichever
path the run already takes -- single-timeframe, --timeframes, and
--timeframes --execute -- so a single invocation's final printed output
carries both the classic weighted-indicator report AND the structure
section together, instead of requiring two separate commands.

These tests stub out the network-bound pieces (_run_single, _handle_execute,
_print_structure_section, engine.format_report) and just verify main()'s
wiring calls both and orders them correctly, using the same
monkeypatch-the-internals style as test_execute_integration.py.

Note: cli.py does `from . import engine` locally inside main(), which binds
to the `engine` attribute already cached on the `cdcx` package by whichever
test imported it first -- monkeypatching sys.modules["cdcx.engine"] doesn't
reach that cached attribute. Patching attributes directly on the real
`cdcx.engine` module object (imported here) works regardless of import
order or caching.
"""

from types import SimpleNamespace

from cdcx import cli, engine as engine_module


def _fake_signal(total_score=80, signal="BUY"):
    return SimpleNamespace(total_score=total_score, signal=signal)


def test_single_timeframe_run_appends_structure_section(monkeypatch, capsys):
    calls = []

    def fake_run_single(symbol, timeframe, limit):
        calls.append("run_single")
        return _fake_signal()

    def fake_print_structure_section(symbol):
        calls.append("structure")
        print("STRUCTURE SECTION HERE")
        return True

    monkeypatch.setattr(cli, "_run_single", fake_run_single)
    monkeypatch.setattr(cli, "_print_structure_section", fake_print_structure_section)
    monkeypatch.setattr(engine_module, "format_report", lambda signal: "MAIN REPORT HERE")

    result = cli.main(["--symbol", "BTC/USDT", "--timeframe", "1h", "--structure"])

    out = capsys.readouterr().out
    assert result == 0
    assert calls == ["run_single", "structure"]
    assert "MAIN REPORT HERE" in out
    assert "STRUCTURE SECTION HERE" in out
    # main report must come before the appended structure section
    assert out.index("MAIN REPORT HERE") < out.index("STRUCTURE SECTION HERE")


def test_single_timeframe_run_without_structure_flag_skips_it(monkeypatch, capsys):
    calls = []

    monkeypatch.setattr(cli, "_run_single", lambda symbol, timeframe, limit: _fake_signal())
    monkeypatch.setattr(
        cli, "_print_structure_section",
        lambda symbol: calls.append("structure") or True,
    )
    monkeypatch.setattr(engine_module, "format_report", lambda signal: "MAIN REPORT HERE")

    result = cli.main(["--symbol", "BTC/USDT", "--timeframe", "1h"])

    assert result == 0
    assert calls == []


def test_timeframes_execute_run_appends_structure_after_execute_plan(monkeypatch, capsys):
    order = []

    monkeypatch.setattr(cli, "_run_single", lambda symbol, timeframe, limit: _fake_signal())

    def fake_execute(symbol, balance, risk_pct, results, limit, live, instrument_name_override, news_imminent):
        order.append("execute")
        print("EXECUTE PLAN HERE")
        return 0

    def fake_structure(symbol):
        order.append("structure")
        print("STRUCTURE SECTION HERE")
        return True

    monkeypatch.setattr(cli, "_handle_execute", fake_execute)
    monkeypatch.setattr(cli, "_print_structure_section", fake_structure)
    monkeypatch.setattr(engine_module, "format_report", lambda signal: "MAIN REPORT HERE")

    result = cli.main([
        "--symbol", "BTC/USDT", "--timeframes", "1h,4h",
        "--execute", "--balance", "10000", "--structure",
    ])

    out = capsys.readouterr().out
    assert result == 0
    assert order == ["execute", "structure"]
    assert out.index("EXECUTE PLAN HERE") < out.index("STRUCTURE SECTION HERE")
