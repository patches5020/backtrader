"""
Unit tests for the Phase 1 FVP shadow layer (cdcx/volume_profile/). These
never touch entry_checklist.py, confluence.py, or regime.py -- that's the
point being tested: the layer is purely descriptive and self-contained.
"""

from cdcx.volume_profile.zone_state import VolumeZone, contains, compute_tested_state
from cdcx.volume_profile.zone_detector import detect_fixed_zone, detect_anchored_zone
from cdcx.volume_profile.zone_lifecycle import classify_lifecycle, ZoneLifecycleState
from cdcx.volume_profile.fvp_analysis import build_fvp_shadow_report, format_fvp_shadow, EXECUTION_IMPACT


def _flat_profile_bars(n=120, base=100.0, spread=1.0):
    """Bars that trade in a tight, stable range around `base` for the whole
    window -- gives a well-defined, non-degenerate value area to detect a
    zone from."""
    highs = [base + spread for _ in range(n)]
    lows = [base - spread for _ in range(n)]
    closes = [base for _ in range(n)]
    volumes = [100.0] * n
    return highs, lows, closes, volumes


def test_contains_is_inclusive_of_both_boundaries():
    zone = VolumeZone(timeframe="1h", zone_type="fixed_value_area", lower_price=10.0, upper_price=20.0, poc_price=15.0)
    assert contains(zone, 10.0)
    assert contains(zone, 20.0)
    assert contains(zone, 15.0)
    assert not contains(zone, 9.99)
    assert not contains(zone, 20.01)


def test_untested_zone_when_price_never_returns():
    # Zone formed over bars 0-9; price then runs away and never comes back.
    zone = VolumeZone(timeframe="1h", zone_type="fixed_value_area", lower_price=10.0, upper_price=12.0, poc_price=11.0)
    highs = [11.0] * 10 + [50.0] * 10
    lows = [10.5] * 10 + [49.0] * 10
    result = compute_tested_state(zone, highs, lows, formed_at_index=9)
    assert result.tested is False
    assert result.test_count == 0
    assert result.first_test is False


def test_first_test_when_current_bar_is_the_only_touch():
    zone = VolumeZone(timeframe="1h", zone_type="fixed_value_area", lower_price=10.0, upper_price=12.0, poc_price=11.0)
    highs = [11.0] * 10 + [50.0] * 5 + [11.5]   # last bar dips back into the zone
    lows = [10.5] * 10 + [49.0] * 5 + [10.8]
    result = compute_tested_state(zone, highs, lows, formed_at_index=9)
    assert result.tested is True
    assert result.test_count == 1
    assert result.first_test is True


def test_not_first_test_once_the_touch_is_in_the_past():
    zone = VolumeZone(timeframe="1h", zone_type="fixed_value_area", lower_price=10.0, upper_price=12.0, poc_price=11.0)
    # One touch, then price moves away again before the window ends.
    highs = [11.0] * 10 + [11.5] + [50.0] * 5
    lows = [10.5] * 10 + [10.8] + [49.0] * 5
    result = compute_tested_state(zone, highs, lows, formed_at_index=9)
    assert result.tested is True
    assert result.test_count == 1
    assert result.first_test is False  # touched once, but not on the current (last) bar


def test_degraded_after_multiple_touches_and_price_moves_away():
    zone = VolumeZone(timeframe="1h", zone_type="fixed_value_area", lower_price=10.0, upper_price=12.0, poc_price=11.0)
    zone.tested, zone.test_count, zone.first_test = True, 3, False
    state = classify_lifecycle(zone, current_price=50.0)
    assert state == ZoneLifecycleState.TESTED_DEGRADED


def test_untested_zone_far_from_price_reads_untested():
    zone = VolumeZone(timeframe="1h", zone_type="fixed_value_area", lower_price=10.0, upper_price=12.0, poc_price=11.0)
    state = classify_lifecycle(zone, current_price=50.0)
    assert state == ZoneLifecycleState.UNTESTED


def test_untested_zone_with_price_inside_reads_first_test():
    zone = VolumeZone(timeframe="1h", zone_type="fixed_value_area", lower_price=10.0, upper_price=12.0, poc_price=11.0)
    state = classify_lifecycle(zone, current_price=11.0)
    assert state == ZoneLifecycleState.FIRST_TEST


def test_detect_fixed_zone_reuses_existing_poc_vah_val():
    highs, lows, closes, volumes = _flat_profile_bars()
    zone = detect_fixed_zone(highs, lows, volumes, price=closes[-1], timeframe="1h", lookback=100)
    assert zone.zone_type == "fixed_value_area"
    assert zone.lower_price <= zone.poc_price <= zone.upper_price


def test_detect_anchored_zone_reuses_existing_poc_vah_val():
    highs, lows, closes, volumes = _flat_profile_bars()
    zone = detect_anchored_zone(highs, lows, closes, volumes, price=closes[-1], timeframe="1h")
    assert zone.zone_type == "anchored_value_area"
    assert zone.lower_price <= zone.poc_price <= zone.upper_price


def test_shadow_report_is_hardcoded_information_only():
    highs, lows, closes, volumes = _flat_profile_bars()
    report = build_fvp_shadow_report(highs, lows, closes, volumes, price=closes[-1], timeframe="1h")
    assert report.execution_impact == "INFORMATION_ONLY"
    assert EXECUTION_IMPACT == "INFORMATION_ONLY"


def test_shadow_report_never_raises_on_degenerate_input():
    # A single flat bar isn't enough for either VP calculation to succeed --
    # this must degrade to an empty zone list, not propagate an exception.
    report = build_fvp_shadow_report([1.0], [1.0], [1.0], [1.0], price=1.0, timeframe="1h")
    assert report.zones == []
    # format_fvp_shadow must also handle the empty case cleanly.
    text = format_fvp_shadow(report)
    assert "INFORMATION_ONLY" in text
