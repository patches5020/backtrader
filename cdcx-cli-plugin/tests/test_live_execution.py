from cdcx.live_execution import derive_instrument_name, build_otoco_order_list


def test_derive_instrument_name_strips_quote_and_appends_usd_perp():
    assert derive_instrument_name("BTC/USDT") == "BTCUSD-PERP"
    assert derive_instrument_name("ETH/USDT") == "ETHUSD-PERP"


def test_long_bracket_matches_verified_schema():
    order_list = build_otoco_order_list(
        instrument_name="BTCUSD-PERP", direction="long", quantity=0.001,
        stop_price=63725.0, take_profit_price=66000.0,
    )
    assert len(order_list) == 3
    assert order_list[0] == {
        "instrument_name": "BTCUSD-PERP", "side": "BUY", "type": "MARKET", "quantity": "0.001",
    }
    assert order_list[1]["type"] == "STOP_LOSS" and order_list[1]["side"] == "SELL"
    assert order_list[1]["trigger_price"] == "63725.0"
    assert order_list[2]["type"] == "TAKE_PROFIT" and order_list[2]["side"] == "SELL"
    assert order_list[2]["trigger_price"] == "66000.0"


def test_short_bracket_flips_sides():
    order_list = build_otoco_order_list(
        instrument_name="BTCUSD-PERP", direction="short", quantity=0.001,
        stop_price=66275.0, take_profit_price=64000.0,
    )
    assert order_list[0]["side"] == "SELL"
    assert order_list[1]["side"] == "BUY" and order_list[2]["side"] == "BUY"
