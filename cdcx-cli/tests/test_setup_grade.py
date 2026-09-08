from cdcx import setup_grade, structure_strategy, confluence, confidence_scoring
from cdcx.indicators import atr_state


def _valid_setup(direction="long"):
    return structure_strategy.StructureSetup(
        direction=direction, valid=True, trigger="breakout_retest",
        reasons=["demo"], entry=100.0, stop_level=95.0,
    )


def _invalid_setup():
    return structure_strategy.StructureSetup(direction=None, valid=False, trigger="", reasons=["demo"])


def _trigger_transition():
    return atr_state.detect_transition(["contraction", "contraction", "expansion"])


def _non_trigger_transition():
    return atr_state.detect_transition(["flat", "flat", "flat"])


def test_no_structure_setup_is_no_trade():
    result = setup_grade.grade_setup(_invalid_setup(), _non_trigger_transition())
    assert result.grade == "No Trade"
    assert result.direction is None


def test_valid_setup_with_atr_trigger_is_a_plus():
    result = setup_grade.grade_setup(_valid_setup(), _trigger_transition())
    assert result.grade == "A+"
    assert result.direction == "long"


def test_valid_setup_without_atr_trigger_is_a_not_a_plus():
    result = setup_grade.grade_setup(_valid_setup(), _non_trigger_transition())
    assert result.grade == "A"
    assert result.direction == "long"


def test_a_plus_downgraded_by_weak_confluence():
    weak_confluence = confluence.evaluate_confluence({"1h": "BUY", "4h": "BUY"})  # 30% -> lower_confidence
    result = setup_grade.grade_setup(_valid_setup(), _trigger_transition(), confluence_result=weak_confluence)
    assert result.grade == "A"


def test_a_plus_holds_with_strong_confluence():
    strong_confluence = confluence.evaluate_confluence({"1w": "STRONG BUY", "1d": "BUY"})  # 70% -> strong
    result = setup_grade.grade_setup(_valid_setup(), _trigger_transition(), confluence_result=strong_confluence)
    assert result.grade == "A+"


def test_format_setup_grade_includes_grade_and_direction():
    result = setup_grade.grade_setup(_valid_setup(), _trigger_transition())
    text = setup_grade.format_setup_grade(result)
    assert "A+ LONG" in text
