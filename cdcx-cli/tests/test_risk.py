import pytest

from cdcx.config import settings
from cdcx.risk import calculate_stop_loss, calculate_position_size, build_position_plan, resolve_atr_multiplier


def test_long_stop_is_below_entry_by_1_5x_atr():
    stop = calculate_stop_loss(entry_price=65000, atr=850, direction="long")
    assert stop == 65000 - 1.5 * 850


def test_short_stop_is_above_entry_by_1_5x_atr():
    stop = calculate_stop_loss(entry_price=65000, atr=850, direction="short")
    assert stop == 65000 + 1.5 * 850


def test_position_size_risks_exactly_the_target_percent():
    entry, atr = 65000, 850
    stop = calculate_stop_loss(entry, atr, "long")
    risk_amount, stop_distance, size = calculate_position_size(
        account_balance=10000, entry_price=entry, stop_price=stop, risk_pct=2.0
    )
    assert abs(risk_amount - 200.0) < 1e-9
    # if the stop is hit, size * stop_distance must equal the risk amount exactly
    assert abs(size * stop_distance - risk_amount) < 1e-6


def test_build_position_plan_end_to_end():
    plan = build_position_plan(
        symbol="BTC/USDT", direction="long", entry_price=65000, atr=850,
        account_balance=10000, risk_pct=2.0,
    )
    assert plan.stop_price < plan.entry_price
    assert abs(plan.risk_amount - 200.0) < 1e-9
    assert plan.position_size > 0


def test_zero_distance_raises():
    with pytest.raises(ValueError):
        calculate_position_size(account_balance=10000, entry_price=100, stop_price=100)


# --- resolve_atr_multiplier() -----------------------------------------------

@pytest.fixture(autouse=True)
def isolated_atr_overrides():
    """Isolate settings.atr_multiplier_overrides / atr_stop_multiplier per
    test so a mutation in one test can't leak into another."""
    original_overrides = settings.atr_multiplier_overrides
    original_default = settings.atr_stop_multiplier
    yield
    settings.atr_multiplier_overrides = original_overrides
    settings.atr_stop_multiplier = original_default


def test_no_symbol_no_override_falls_back_to_global_default():
    assert resolve_atr_multiplier() == settings.atr_stop_multiplier


def test_btc_resolves_to_its_configured_override():
    assert resolve_atr_multiplier("BTC/USDT") == 1.5
    assert resolve_atr_multiplier("BTC/USD") == 1.5  # base currency match, quote ignored


def test_xrp_resolves_to_its_configured_override():
    # A real backtest sweep found XRP's empirical optimum was a tighter
    # 1.0x -- deliberately set back to 1.5 (matching the global default)
    # at the user's request. Still an explicit per-symbol override entry
    # (not a fallthrough), just one that currently equals the default.
    assert resolve_atr_multiplier("XRP/USD") == 1.5
    assert resolve_atr_multiplier("XRP/USDT") == 1.5


def test_symbol_not_in_overrides_falls_back_to_global_default():
    assert resolve_atr_multiplier("ETH/USD") == settings.atr_stop_multiplier


def test_explicit_override_always_wins():
    assert resolve_atr_multiplier("BTC/USDT", override=2.5) == 2.5
    assert resolve_atr_multiplier("XRP/USD", override=0.75) == 0.75
    assert resolve_atr_multiplier(None, override=3.0) == 3.0


def test_malformed_override_entries_are_skipped_not_raised():
    settings.atr_multiplier_overrides = "BTC:1.5,garbage,XRP:notanumber,ETH:2.0"
    assert resolve_atr_multiplier("BTC/USDT") == 1.5
    assert resolve_atr_multiplier("ETH/USDT") == 2.0
    # XRP's malformed entry falls back to the global default instead of crashing
    assert resolve_atr_multiplier("XRP/USDT") == settings.atr_stop_multiplier


def test_calculate_stop_loss_uses_per_symbol_default_when_symbol_given():
    xrp_stop = calculate_stop_loss(entry_price=1.0, atr=0.01, direction="long", symbol="XRP/USD")
    btc_stop = calculate_stop_loss(entry_price=65000, atr=850, direction="long", symbol="BTC/USDT")
    assert xrp_stop == 1.0 - 1.5 * 0.01     # XRP override: 1.5x
    assert btc_stop == 65000 - 1.5 * 850    # BTC override: 1.5x (same as global default)


def test_calculate_stop_loss_without_symbol_keeps_legacy_flat_default():
    """No symbol passed -- must NOT silently pick up any per-symbol
    override; preserves the original flat-multiplier behavior exactly."""
    stop = calculate_stop_loss(entry_price=65000, atr=850, direction="long")
    assert stop == 65000 - settings.atr_stop_multiplier * 850


def test_build_position_plan_records_the_resolved_multiplier():
    xrp_plan = build_position_plan(
        symbol="XRP/USD", direction="long", entry_price=1.0, atr=0.01,
        account_balance=10000, risk_pct=2.0,
    )
    assert xrp_plan.atr_multiplier == 1.5
    assert xrp_plan.stop_distance == pytest.approx(0.015)  # 1.5x ATR

    override_plan = build_position_plan(
        symbol="XRP/USD", direction="long", entry_price=1.0, atr=0.01,
        account_balance=10000, risk_pct=2.0, atr_multiplier_override=3.0,
    )
    assert override_plan.atr_multiplier == 3.0
    assert override_plan.stop_distance == pytest.approx(0.03)
