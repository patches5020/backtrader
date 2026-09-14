from cdcx.no_trade_filter import check_no_trade_filter, is_atr_unusually_low


def test_clean_setup_passes():
    result = check_no_trade_filter(
        adx_value=30, higher_timeframes_agree=True, price_in_middle_of_range=False,
        risk_reward_ratio=2.5, atr_unusually_low=False,
    )
    assert result.blocked is False
    assert result.reasons == []


def test_adx_dead_zone_blocks():
    result = check_no_trade_filter(
        adx_value=22, higher_timeframes_agree=True, price_in_middle_of_range=False,
        risk_reward_ratio=2.5, atr_unusually_low=False,
    )
    assert result.blocked is True
    assert any("dead zone" in r for r in result.reasons)


def test_risk_reward_below_2_blocks():
    result = check_no_trade_filter(
        adx_value=30, higher_timeframes_agree=True, price_in_middle_of_range=False,
        risk_reward_ratio=1.8, atr_unusually_low=False,
    )
    assert result.blocked is True


def test_risk_reward_exactly_2_does_not_block():
    result = check_no_trade_filter(
        adx_value=30, higher_timeframes_agree=True, price_in_middle_of_range=False,
        risk_reward_ratio=2.0, atr_unusually_low=False,
    )
    assert result.blocked is False


def test_news_imminent_blocks_when_flagged():
    result = check_no_trade_filter(
        adx_value=30, higher_timeframes_agree=True, price_in_middle_of_range=False,
        risk_reward_ratio=2.5, atr_unusually_low=False, news_imminent=True,
    )
    assert result.blocked is True


def test_multiple_conditions_all_reported():
    result = check_no_trade_filter(
        adx_value=22, higher_timeframes_agree=False, price_in_middle_of_range=True,
        risk_reward_ratio=1.5, atr_unusually_low=True, news_imminent=True,
    )
    assert result.blocked is True
    assert len(result.reasons) == 6


def test_atr_unusually_low_detection():
    dropped = [10.0] * 10 + [7.0]  # current bar 30% below its own recent average
    assert is_atr_unusually_low(dropped) is True

    flat = [10.0] * 11
    assert is_atr_unusually_low(flat) is False
