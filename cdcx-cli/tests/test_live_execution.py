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


def test_isolated_margin_attaches_exec_inst_to_every_leg():
    """Stock/RWA perpetuals (e.g. AAPLUSD-PERP) reject a plain cross-margin
    order with error 623 INSTRUMENT_MUST_USE_ISOLATED_MARGIN -- every leg
    must carry exec_inst: ["ISOLATED_MARGIN"], not just the entry."""
    order_list = build_otoco_order_list(
        instrument_name="AAPLUSD-PERP", direction="long", quantity=1.0,
        stop_price=100.0, take_profit_price=120.0, isolated_margin=True,
    )
    assert all(leg["exec_inst"] == ["ISOLATED_MARGIN"] for leg in order_list)
    assert all("isolation_id" not in leg for leg in order_list)  # omitted when not given


def test_isolation_id_attaches_to_every_leg_when_isolated():
    """Topping up/trimming an already-open isolated position requires
    isolation_id on the order, per the cdcx-isolated-margin skill -- else
    error 617 DUPLICATED_INSTRUMENT_ORDER_FOR_ISOLATED_MARGIN."""
    order_list = build_otoco_order_list(
        instrument_name="AAPLUSD-PERP", direction="long", quantity=1.0,
        stop_price=100.0, take_profit_price=120.0,
        isolated_margin=True, isolation_id="abc123",
    )
    assert all(leg["isolation_id"] == "abc123" for leg in order_list)


def test_isolation_id_ignored_when_not_isolated():
    """isolation_id is meaningless for a cross-margin instrument -- must not
    leak onto the order if isolated_margin wasn't also set."""
    order_list = build_otoco_order_list(
        instrument_name="BTCUSD-PERP", direction="long", quantity=0.001,
        stop_price=63725.0, take_profit_price=66000.0,
        isolation_id="abc123",
    )
    assert all("isolation_id" not in leg and "exec_inst" not in leg for leg in order_list)
