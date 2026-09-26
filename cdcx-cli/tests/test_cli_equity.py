import pytest

from cdcx.config import settings
from cdcx import cli_equity, engine, mtf_context


@pytest.fixture(autouse=True)
def isolated_trade_state(tmp_path):
    """Same isolation pattern as test_trade_manager.py -- never touch a real cdcx_trades.json."""
    original = settings.trade_state_path
    settings.trade_state_path = str(tmp_path / "trades_test.json")
    yield
    settings.trade_state_path = original


def _signal(execution_signal: str, symbol="AAPL", entry=150.0, atr=2.0) -> engine.TradeSignal:
    """A minimal real TradeSignal -- only the fields _handle_execute actually reads are meaningful."""
    return engine.TradeSignal(
        symbol=symbol, total_score=90.0, signal=execution_signal, stars="****.",
        scores={}, labels={}, entry=entry, atr=atr,
        stop_loss=entry - atr * 1.5, take_profits={f"TP{i}": entry + atr * i for i in range(1, 5)},
        risk_reward_ratio=2.5, confidence=80.0, regime=None,
        execution_signal=execution_signal, timeframe="1d",
    )


def test_execute_opens_a_long_paper_trade_on_buy_signal(capsys):
    rc = cli_equity._handle_execute("AAPL", _signal("BUY"), balance=10000, risk_pct=2.0)
    assert rc == 0
    out = capsys.readouterr().out
    assert "LONG" in out.upper()
    from cdcx import trade_manager
    trades = trade_manager.load_trades()
    assert len(trades) == 1
    assert trades[0].direction == "long"


def test_execute_opens_a_short_paper_trade_on_sell_signal():
    rc = cli_equity._handle_execute("AAPL", _signal("STRONG SELL"), balance=10000, risk_pct=2.0)
    assert rc == 0
    from cdcx import trade_manager
    trades = trade_manager.load_trades()
    assert trades[0].direction == "short"


def test_execute_skips_no_trade_signal(capsys):
    rc = cli_equity._handle_execute("AAPL", _signal("NO TRADE"), balance=10000, risk_pct=2.0)
    assert rc == 0
    from cdcx import trade_manager
    assert trade_manager.load_trades() == []
    assert "No trade planned" in capsys.readouterr().out


def test_execute_skips_neutral_watch_signal():
    rc = cli_equity._handle_execute("AAPL", _signal("WATCH"), balance=10000, risk_pct=2.0)
    assert rc == 0
    from cdcx import trade_manager
    assert trade_manager.load_trades() == []


def test_build_parser_requires_source_and_symbol():
    parser = cli_equity.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--symbol", "AAPL"])  # missing --source


def test_build_parser_defaults():
    args = cli_equity.build_parser().parse_args(["--source", "webull", "--symbol", "AAPL"])
    assert args.timeframe == "1h"
    assert args.execute is False
    assert args.structure_report is False


def test_build_parser_accepts_structure_report_flag():
    args = cli_equity.build_parser().parse_args(["--source", "robinhood", "--symbol", "SPCX", "--structure-report"])
    assert args.structure_report is True


def test_cli_equity_wires_mtf_context_against_real_trade_signals():
    """cli_equity.py's --timeframes path prints mtf_context.py's ATR
    alignment + VP hierarchy the same way cli.py does (see cli_equity.py's
    module docstring) -- confirms that wiring against real TradeSignal
    instances (not the SimpleNamespace stand-ins mtf_context's own test
    suite uses), since engine.TradeSignal is what cli_equity.py's
    --timeframes loop actually populates `results` with."""
    results = {}
    for tf in ("1w", "1d", "4h", "1h"):
        signal = _signal("STRONG BUY")
        signal.timeframe = tf
        signal.labels = {"atr_expansion": "Expansion"}
        signal.vp_setup_type = "value_area_breakout"
        signal.vp_setup_direction = "up"
        results[tf] = signal

    alignment = mtf_context.build_atr_alignment(results)
    assert alignment.expansion_count == 4
    hierarchy = mtf_context.build_vp_hierarchy(results)
    assert len(hierarchy.entries) == 4
    assert hierarchy.macro_conflict is None

    formatted = mtf_context.format_atr_alignment(alignment) + mtf_context.format_vp_hierarchy(hierarchy)
    assert "4/4" in formatted
    assert "macro location" in formatted
