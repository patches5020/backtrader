from cdcx.risk import calculate_stop_loss, calculate_position_size, build_position_plan


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
    import pytest
    with pytest.raises(ValueError):
        calculate_position_size(account_balance=10000, entry_price=100, stop_price=100)
