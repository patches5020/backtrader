from cdcx.confluence import ConfluenceResult
from cdcx.entry_checklist import ChecklistItem, ChecklistResult
from cdcx.entry_location import (
    CONFIRMED,
    DEVELOPING,
    INVALID,
    WAIT_FIB,
    WAIT_FIB_AND_VP,
    WAIT_VOLUME_PROFILE,
    classify_entry_location,
    format_entry_location,
)

PASSING_CONFLUENCE = ConfluenceResult(
    direction="long", should_execute=True, tier="strong",
    agreeing_timeframes=["1h", "4h", "1d", "1w"], entry_timeframe="1h",
    confluence_score=10, confidence_pct=100, label="Strong Buy -- 100% confidence (1H, 4H, 1D, 1W bullish)",
)

FAILING_CONFLUENCE = ConfluenceResult(
    direction=None, should_execute=False, tier="none", label="NO TRADE -- fewer than 2 of {1H, 4H, 1D, 1W} in agreement",
)


def _checklist(*failed_names: str) -> ChecklistResult:
    """A ChecklistResult where every standard item passes except the named ones."""
    all_names = [
        "ATR/EMA trend confirms",
        "Fibonacci level confirms",
        "Fair Value Gap confirms",
        "Volume Profile confirms (fixed or anchored)",
        "Account risk <= 2%",
        "No existing position in this symbol",
    ]
    result = ChecklistResult()
    for name in all_names:
        result.items.append(ChecklistItem(name, passed=name not in failed_names, detail="test"))
    result.all_passed = all(item.passed for item in result.items)
    return result


def test_invalid_when_confluence_does_not_execute():
    state = classify_entry_location(FAILING_CONFLUENCE, regime="trending", checklist_result=None)
    assert state.state == INVALID
    assert "NO TRADE" in format_entry_location(state)


def test_invalid_when_regime_is_not_trending():
    state = classify_entry_location(PASSING_CONFLUENCE, regime="transitional", checklist_result=None)
    assert state.state == INVALID


def test_invalid_when_checklist_not_yet_evaluated():
    state = classify_entry_location(PASSING_CONFLUENCE, regime="trending", checklist_result=None)
    assert state.state == INVALID


def test_confirmed_when_checklist_fully_passes():
    state = classify_entry_location(PASSING_CONFLUENCE, regime="trending", checklist_result=_checklist())
    assert state.state == CONFIRMED


def test_developing_when_only_fibonacci_fails():
    checklist = _checklist("Fibonacci level confirms")
    state = classify_entry_location(PASSING_CONFLUENCE, regime="trending", checklist_result=checklist)
    assert state.state == DEVELOPING
    assert state.substate == WAIT_FIB
    formatted = format_entry_location(state)
    assert "WAIT" in formatted
    assert "WAIT_FIB" in formatted
    assert "NEXT TRIGGER" in formatted


def test_developing_when_only_volume_profile_fails():
    checklist = _checklist("Volume Profile confirms (fixed or anchored)")
    state = classify_entry_location(PASSING_CONFLUENCE, regime="trending", checklist_result=checklist)
    assert state.state == DEVELOPING
    assert state.substate == WAIT_VOLUME_PROFILE


def test_developing_when_both_location_items_fail():
    checklist = _checklist("Fibonacci level confirms", "Volume Profile confirms (fixed or anchored)")
    state = classify_entry_location(PASSING_CONFLUENCE, regime="trending", checklist_result=checklist)
    assert state.state == DEVELOPING
    assert state.substate == WAIT_FIB_AND_VP
    assert "Fibonacci" in state.reasons[0] and "Volume Profile" in state.reasons[0]


def test_invalid_and_confirmed_states_have_no_substate():
    invalid_state = classify_entry_location(FAILING_CONFLUENCE, regime="trending", checklist_result=None)
    assert invalid_state.substate is None
    confirmed_state = classify_entry_location(PASSING_CONFLUENCE, regime="trending", checklist_result=_checklist())
    assert confirmed_state.substate is None


def test_invalid_when_a_non_location_item_fails_alongside_fibonacci():
    checklist = _checklist("Fibonacci level confirms", "ATR/EMA trend confirms")
    state = classify_entry_location(PASSING_CONFLUENCE, regime="trending", checklist_result=checklist)
    assert state.state == INVALID


def test_invalid_when_only_a_non_location_item_fails():
    checklist = _checklist("Account risk <= 2%")
    state = classify_entry_location(PASSING_CONFLUENCE, regime="trending", checklist_result=checklist)
    assert state.state == INVALID


def test_run_21_scenario_is_developing():
    """The exact motivating case: 4/4 trending confluence, every checklist
    item confirms except Fibonacci -- 'good market, entry location not
    confirmed', not a bad market."""
    checklist = _checklist("Fibonacci level confirms")
    state = classify_entry_location(PASSING_CONFLUENCE, regime="trending", checklist_result=checklist)
    assert state.state == DEVELOPING
    assert state.substate == WAIT_FIB
