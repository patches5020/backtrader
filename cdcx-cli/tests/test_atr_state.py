from cdcx.indicators import atr_state


# ---------------------------------------------------------------------------
# classify_atr_series
# ---------------------------------------------------------------------------

def test_classify_atr_series_insufficient_history_is_none():
    states = atr_state.classify_atr_series([1.0] * 5, lookback=10)
    assert states == [None] * 5


def test_classify_atr_series_flat_when_unchanged():
    series = [1.0] * 15
    states = atr_state.classify_atr_series(series, lookback=10)
    assert states[10:] == ["flat"] * 5


def test_classify_atr_series_expansion_when_above_threshold():
    series = [1.0] * 10 + [1.5]  # +50% vs trailing average -> expansion
    states = atr_state.classify_atr_series(series, lookback=10)
    assert states[-1] == "expansion"


def test_classify_atr_series_contraction_when_below_threshold():
    series = [1.0] * 10 + [0.5]  # -50% vs trailing average -> contraction
    states = atr_state.classify_atr_series(series, lookback=10)
    assert states[-1] == "contraction"


# ---------------------------------------------------------------------------
# detect_transition
# ---------------------------------------------------------------------------

def test_detect_transition_insufficient_data():
    result = atr_state.detect_transition([None, None])
    assert result.kind == "none"
    assert result.is_trigger is False


def test_detect_transition_contraction_to_expansion_is_a_trigger():
    result = atr_state.detect_transition(["contraction", "contraction", "expansion"])
    assert result.kind == "contraction_to_expansion"
    assert result.is_trigger is True


def test_detect_transition_second_expansion_after_cooldown_is_a_trigger():
    states = ["expansion", "expansion", "flat", "flat", "expansion"]
    result = atr_state.detect_transition(states)
    assert result.kind == "second_expansion"
    assert result.is_trigger is True
    assert result.bars_since_prior_expansion == 2


def test_detect_transition_first_expansion_with_no_cooldown_is_not_a_trigger():
    states = ["flat", "flat", "flat", "expansion"]
    result = atr_state.detect_transition(states)
    assert result.kind == "expansion_continuation"
    assert result.is_trigger is False


def test_detect_transition_plain_contraction_is_not_a_trigger():
    result = atr_state.detect_transition(["flat", "contraction"])
    assert result.kind == "contraction"
    assert result.is_trigger is False


def test_detect_transition_plain_flat_is_not_a_trigger():
    result = atr_state.detect_transition(["contraction", "flat"])
    assert result.kind == "flat"
    assert result.is_trigger is False


def test_detect_transition_ignores_leading_none_padding():
    states = [None, None, "contraction", "expansion"]
    result = atr_state.detect_transition(states)
    assert result.kind == "contraction_to_expansion"


def test_detect_transition_compression_release_is_a_trigger():
    # contraction -> flat bridge -> expansion, no earlier expansion behind it
    states = ["contraction", "flat", "flat", "expansion"]
    result = atr_state.detect_transition(states)
    assert result.kind == "compression_release"
    assert result.is_trigger is True
    assert result.bars_since_prior_expansion == 3


def test_detect_transition_expansion_to_contraction_is_not_a_trigger():
    result = atr_state.detect_transition(["expansion", "expansion", "contraction"])
    assert result.kind == "expansion_to_contraction"
    assert result.is_trigger is False


def test_detect_transition_expansion_to_flat_is_not_a_trigger():
    result = atr_state.detect_transition(["expansion", "expansion", "flat"])
    assert result.kind == "expansion_to_flat"
    assert result.is_trigger is False


# ---------------------------------------------------------------------------
# analyze (OHLC convenience wrapper)
# ---------------------------------------------------------------------------

def test_analyze_computes_from_raw_ohlc():
    closes = [100.0] * 25
    highs = [c + 0.1 for c in closes]
    lows = [c - 0.1 for c in closes]
    result = atr_state.analyze(highs, lows, closes)
    assert result.kind in {"flat", "none"}


# ---------------------------------------------------------------------------
# format_atr_transition
# ---------------------------------------------------------------------------

def test_format_atr_transition_marks_triggers_distinctly():
    trigger = atr_state.detect_transition(["contraction", "expansion"])
    non_trigger = atr_state.detect_transition(["flat", "flat"])
    assert "[TRIGGER]" in atr_state.format_atr_transition(trigger)
    assert "[TRIGGER]" not in atr_state.format_atr_transition(non_trigger)
