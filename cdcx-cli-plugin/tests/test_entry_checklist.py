import os
import pytest
from types import SimpleNamespace

from cdcx.config import settings
from cdcx.entry_checklist import evaluate_entry_checklist


@pytest.fixture(autouse=True)
def isolated_trade_state(tmp_path):
    original = settings.trade_state_path
    settings.trade_state_path = str(tmp_path / "trades_test.json")
    yield
    settings.trade_state_path = original


def _all_confirming_long_signal():
    return SimpleNamespace(
        scores={
            "ema_trend": 15, "fib_retracement": 9, "fair_value_gap": 15,
            "fixed_volume_profile": 10, "anchored_volume_profile": 10,
        },
        labels={},
    )


def test_all_confirming_passes():
    signal = _all_confirming_long_signal()
    result = evaluate_entry_checklist(signal, "long", risk_pct=2.0, symbol="BTC/USDT")
    assert result.all_passed is True


def test_neutral_component_does_not_count_as_confirming():
    signal = _all_confirming_long_signal()
    signal.scores["fib_retracement"] = 0  # neutral, not an active bounce
    result = evaluate_entry_checklist(signal, "long", risk_pct=2.0, symbol="BTC/USDT")
    assert result.all_passed is False


def test_contradicting_component_fails_even_if_others_confirm():
    signal = _all_confirming_long_signal()
    signal.scores["fib_retracement"] = -9  # actively bearish while others are bullish
    result = evaluate_entry_checklist(signal, "long", risk_pct=2.0, symbol="BTC/USDT")
    assert result.all_passed is False


def test_volume_profile_passes_if_either_fixed_or_anchored_confirms():
    signal = _all_confirming_long_signal()
    signal.scores["fixed_volume_profile"] = -5
    signal.scores["anchored_volume_profile"] = 10  # this one still confirms
    result = evaluate_entry_checklist(signal, "long", risk_pct=2.0, symbol="BTC/USDT")
    assert result.all_passed is True


def test_risk_pct_over_2_percent_fails():
    signal = _all_confirming_long_signal()
    result = evaluate_entry_checklist(signal, "long", risk_pct=3.0, symbol="BTC/USDT")
    assert result.all_passed is False


def test_existing_open_position_fails_checklist():
    from cdcx import trade_manager

    trade_manager.open_trade(
        symbol="BTC/USDT", direction="long", entry_price=65000.0, atr=850.0,
        stop_price=63725.0, tp_levels=[66000, 67000, 68500, 71000],
        position_size=0.157, risk_amount=200.0, account_balance=10000.0,
    )
    signal = _all_confirming_long_signal()
    result = evaluate_entry_checklist(signal, "long", risk_pct=2.0, symbol="BTC/USDT")
    assert result.all_passed is False


# ---------------------------------------------------------------------------
# atr_series: optional, advisory ATR-transition item (see atr_state.py)
# ---------------------------------------------------------------------------

def test_atr_series_omitted_keeps_checklist_unchanged():
    signal = _all_confirming_long_signal()
    result = evaluate_entry_checklist(signal, "long", risk_pct=2.0, symbol="BTC/USDT")
    assert all(not item.advisory for item in result.items)


def test_atr_series_contraction_to_expansion_is_advisory_pass_but_not_required():
    signal = _all_confirming_long_signal()
    atr_series = [1.0] * 10 + [0.5] * 10 + [1.0]  # contraction settles, then a fresh expansion bar
    result = evaluate_entry_checklist(signal, "long", risk_pct=2.0, symbol="BTC/USDT", atr_series=atr_series)
    advisory_items = [item for item in result.items if item.advisory]
    assert len(advisory_items) == 1
    assert result.all_passed is True  # advisory item doesn't gate an otherwise-passing checklist


def test_atr_series_no_trigger_does_not_fail_checklist():
    signal = _all_confirming_long_signal()
    atr_series = [1.0] * 15  # flat throughout -- no contraction->expansion or second-expansion trigger
    result = evaluate_entry_checklist(signal, "long", risk_pct=2.0, symbol="BTC/USDT", atr_series=atr_series)
    advisory_items = [item for item in result.items if item.advisory]
    assert advisory_items[0].passed is False
    assert result.all_passed is True  # still passes -- advisory item is informational only
