from types import SimpleNamespace

from cdcx.mtf_context import (
    build_atr_alignment,
    build_vp_hierarchy,
    format_atr_alignment,
    format_vp_hierarchy,
)


def _signal(atr_label="Expansion", vp_setup_type="value_area_breakout", vp_setup_direction="up"):
    return SimpleNamespace(
        labels={"atr_expansion": atr_label},
        vp_setup_type=vp_setup_type,
        vp_setup_direction=vp_setup_direction,
    )


def test_atr_alignment_all_expanding():
    results = {tf: _signal("Expansion") for tf in ("1w", "1d", "4h", "1h")}
    alignment = build_atr_alignment(results)
    assert alignment.expansion_count == 4
    assert alignment.total_count == 4
    assert "4/4" in format_atr_alignment(alignment)


def test_atr_alignment_mixed():
    results = {
        "1w": _signal("Expansion"), "1d": _signal("Flat"),
        "4h": _signal("Expansion"), "1h": _signal("Contraction"),
    }
    alignment = build_atr_alignment(results)
    assert alignment.expansion_count == 2
    assert alignment.total_count == 4


def test_atr_alignment_skips_missing_timeframes():
    results = {"1w": _signal("Expansion"), "4h": _signal("Expansion")}  # 1d/1h absent
    alignment = build_atr_alignment(results)
    assert alignment.expansion_count == 2
    assert alignment.total_count == 2
    assert alignment.by_timeframe["1d"] == "n/a"


def test_vp_hierarchy_assigns_correct_roles():
    results = {tf: _signal() for tf in ("1w", "1d", "4h", "1h")}
    hierarchy = build_vp_hierarchy(results)
    roles = {e.timeframe: e.role for e in hierarchy.entries}
    assert roles["1w"] == "macro location"
    assert roles["1d"] == "major trend/value location"
    assert roles["4h"] == "setup location"
    assert roles["1h"] == "entry-area location"


def test_vp_hierarchy_flags_run_21_style_macro_conflict():
    # 1W bearish breakout (still below weekly VAL) while 1D/4H/1H are all
    # bullish breakouts -- the exact live Run 21 shape.
    results = {
        "1w": _signal(vp_setup_direction="down"),
        "1d": _signal(vp_setup_direction="up"),
        "4h": _signal(vp_setup_direction="up"),
        "1h": _signal(vp_setup_direction="up"),
    }
    hierarchy = build_vp_hierarchy(results)
    assert hierarchy.macro_conflict is not None
    assert "1W" in hierarchy.macro_conflict and "1H" in hierarchy.macro_conflict
    assert "NOTE" in format_vp_hierarchy(hierarchy)


def test_vp_hierarchy_no_conflict_when_aligned():
    results = {tf: _signal(vp_setup_direction="up") for tf in ("1w", "1d", "4h", "1h")}
    hierarchy = build_vp_hierarchy(results)
    assert hierarchy.macro_conflict is None


def test_vp_hierarchy_no_conflict_with_fewer_than_two_directional_readings():
    results = {
        "1w": _signal(vp_setup_type="none", vp_setup_direction=None),
        "1h": _signal(vp_setup_direction="up"),
    }
    hierarchy = build_vp_hierarchy(results)
    assert hierarchy.macro_conflict is None


def test_vp_hierarchy_skips_missing_timeframes():
    results = {"4h": _signal()}
    hierarchy = build_vp_hierarchy(results)
    assert len(hierarchy.entries) == 1
    assert hierarchy.entries[0].timeframe == "4h"
