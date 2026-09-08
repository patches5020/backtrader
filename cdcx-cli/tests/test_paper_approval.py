from types import SimpleNamespace

from cdcx import paper_approval


def test_direction_label_maps_signals():
    assert paper_approval.direction_label("STRONG BUY") == "BULLISH"
    assert paper_approval.direction_label("BUY") == "BULLISH"
    assert paper_approval.direction_label("STRONG SELL") == "BEARISH"
    assert paper_approval.direction_label("SELL") == "BEARISH"
    assert paper_approval.direction_label("WATCH") == "NEUTRAL"
    assert paper_approval.direction_label("NEUTRAL") == "NEUTRAL"
    assert paper_approval.direction_label(None) == "N/A"
    assert paper_approval.direction_label("garbage") == "N/A"


def _full_signal():
    return SimpleNamespace(
        signal="STRONG BUY",
        timeframe="1h",
        regime=SimpleNamespace(regime="trending", label="TRENDING (bullish)"),
        poc=61000.0,
        vah=62500.0,
        val=59400.0,
        hvn=60800.0,
        lvn=58800.0,
        fvg_top=61200.0,
        fvg_bottom=61000.0,
        fib_levels={"0.382": 60500.0, "0.5": 60250.0, "0.618": 60000.0, "0.786": 59650.0},
        atr=400.0,
    )


def _plan():
    return SimpleNamespace(entry_price=61500.0, stop_price=60900.0, position_size=0.5, notional_value=30750.0)


def test_build_uses_signal_and_plan_fields():
    approval = paper_approval.build_paper_trade_approval(
        "BTC/USDT", "long", _full_signal(), _plan(), [62000.0, 62500.0, 63000.0, 64000.0],
        timeframe_directions={"4h": "BULLISH", "1d": "BULLISH", "1w": "NEUTRAL"},
        risk_pct=2.0,
    )

    assert approval.symbol == "BTC/USDT"
    assert approval.direction == "long"
    # entry timeframe's own read is folded in alongside the caller-supplied map
    assert approval.timeframe_directions == {
        "1h": "BULLISH", "4h": "BULLISH", "1d": "BULLISH", "1w": "NEUTRAL",
    }
    assert approval.market_state == "TRENDING (bullish)"
    assert approval.poc == 61000.0
    assert approval.hvn == 60800.0
    assert approval.lvn == 58800.0
    assert approval.fvg_top == 61200.0
    assert approval.fvg_bottom == 61000.0
    assert approval.entry == 61500.0
    assert approval.stop == 60900.0
    assert approval.tp_levels == [62000.0, 62500.0, 63000.0, 64000.0]
    assert approval.risk_pct == 2.0
    assert approval.position_size == 0.5
    assert approval.result == "PASS"


def test_build_degrades_gracefully_for_partial_mock_signal():
    """entry/atr/take_profits-only mocks (as used by test_execute_integration.py)
    must not raise -- every extra field falls back to a safe default."""
    minimal_signal = SimpleNamespace(entry=65000.0, atr=850.0)
    approval = paper_approval.build_paper_trade_approval(
        "BTC/USDT", "long", minimal_signal, _plan(), [67600.0], result="PASS",
    )
    assert approval.poc == 0.0
    assert approval.fvg_top is None
    assert approval.fib_levels == {}
    assert approval.market_state == ""


def test_format_includes_every_required_section():
    approval = paper_approval.build_paper_trade_approval(
        "BTC/USDT", "long", _full_signal(), _plan(), [62000.0, 62500.0, 63000.0, 64000.0],
        timeframe_directions={"4h": "BULLISH", "1d": "BULLISH", "1w": "NEUTRAL"},
        risk_pct=2.0,
    )
    text = paper_approval.format_paper_trade_approval(approval)

    assert "PAPER TRADE APPROVAL" in text
    assert "Symbol:    BTC/USDT" in text
    assert "Direction: LONG" in text
    for tf in ("1H", "4H", "1D", "1W"):
        assert tf in text
    assert "Market State: TRENDING (bullish)" in text
    assert "POC:" in text
    assert "FVG:" in text
    assert "HVN:" in text
    assert "LVN:" in text
    assert "FIBONACCI:" in text
    assert "0.618" in text
    assert "ATR:" in text
    assert "Entry:" in text
    assert "Stop Loss:" in text
    for i in range(1, 5):
        assert f"TP{i}:" in text
    assert "Portfolio Risk: 2.0% maximum" in text
    assert "PAPER RESULT: PASS" in text
    assert "LIVE EXECUTION:" in text
    assert "[ APPROVE ]" in text
    assert "[ REJECT ]" in text


def test_format_handles_missing_fvg_and_fib():
    signal = _full_signal()
    signal.fvg_top = None
    signal.fvg_bottom = None
    signal.fib_levels = {}
    approval = paper_approval.build_paper_trade_approval("BTC/USDT", "long", signal, _plan(), [62000.0])
    text = paper_approval.format_paper_trade_approval(approval)
    assert "FVG:  no active aligned gap" in text
    assert "n/a" in text
