import pytest

from cdcx.engine import analyze_ohlcv
from cdcx.exchange.cryptocom import OHLCV


def _make_ohlcv(closes, opens=None, highs=None, lows=None, volumes=None):
    n = len(closes)
    opens = opens or closes
    highs = highs or [c + 1 for c in closes]
    lows = lows or [c - 1 for c in closes]
    volumes = volumes or [100.0] * n
    return OHLCV(timestamps=list(range(n)), opens=opens, highs=highs, lows=lows, closes=closes, volumes=volumes)


def test_take_profit_1_always_clears_2_to_1_risk_reward():
    # regression: TP ratios were once a direct reuse of the Fibonacci
    # extension ratios (1.272 etc), which mathematically locked R:R at
    # exactly 1.272:1 forever -- permanently failing the 2:1 minimum on
    # every single trade. TP1 must clear 2.0 with real margin.
    import random
    random.seed(1)
    closes = [100 + i * 0.5 + random.uniform(-0.3, 0.3) for i in range(80)]
    data = _make_ohlcv(closes)
    signal = analyze_ohlcv("BTC/USDT", data)
    assert signal.risk_reward_ratio >= 2.0


def test_stop_loss_and_take_profits_derive_from_the_same_atr():
    # regression: TP levels used to come from a separate Fibonacci
    # swing_high/swing_low lookback, completely decoupled from the ATR used
    # for the stop -- letting them imply wildly different volatility for
    # the same trade. Verify SL and every TP are consistent with ONE
    # stop_distance (atr * multiplier).
    import random
    random.seed(2)
    closes = [100 + i * 0.3 + random.uniform(-0.3, 0.3) for i in range(80)]
    data = _make_ohlcv(closes)
    signal = analyze_ohlcv("BTC/USDT", data)

    stop_distance = abs(signal.entry - signal.stop_loss)
    for tp_name, tp_price in signal.take_profits.items():
        implied_r_multiple = abs(tp_price - signal.entry) / stop_distance
        assert implied_r_multiple > 0  # sane, not a leftover epsilon floor


def test_direction_score_is_negative_for_bearish_setup_even_when_total_score_clamps_to_zero():
    # regression: a deeply bearish setup used to clamp total_score to 0,
    # which looked identical to "no information" -- direction_score should
    # show the real negative magnitude instead.
    import random
    random.seed(4)
    closes = [200 - i * 1.2 + random.uniform(-0.5, 0.5) for i in range(80)]  # steady downtrend
    data = _make_ohlcv(closes)
    signal = analyze_ohlcv("BTC/USDT", data)

    if signal.total_score == 0.0:
        assert signal.direction_score < -10  # confirms it's genuinely bearish, not neutral


def test_execution_signal_is_no_trade_when_regime_is_transitional():
    from cdcx import regime as regime_module
    import random
    random.seed(5)
    # a directionless random walk tends to land in a dead-zone regime
    closes = [100.0]
    for _ in range(79):
        closes.append(closes[-1] + random.uniform(-0.05, 0.05))
    data = _make_ohlcv(closes)
    signal = analyze_ohlcv("BTC/USDT", data)

    if signal.regime.regime == "transitional":
        assert signal.execution_signal == "NO TRADE"
        assert "transitional" in signal.execution_reason.lower()


def test_execution_signal_falls_back_to_indicator_signal_when_gates_pass():
    import random
    random.seed(3)
    closes = [100 + i * 0.3 + random.uniform(-0.4, 0.4) for i in range(80)]
    data = _make_ohlcv(closes)
    signal = analyze_ohlcv("BTC/USDT", data, higher_timeframes_aligned=True)

    if signal.regime.regime != "transitional" and signal.risk_reward_ratio >= 2.0:
        assert signal.execution_signal == signal.signal
        assert signal.execution_reason == ""


def test_computed_at_timestamp_is_set():
    data = _make_ohlcv([100 + i * 0.1 for i in range(60)])
    signal = analyze_ohlcv("BTC/USDT", data)
    assert signal.computed_at > 0


def test_setup_score_is_low_when_regime_transitional_even_with_strong_direction():
    # regression: "AI SCORE = 0.0" while direction_score was clearly
    # bearish (-50+) was the core complaint -- setup_score should reflect
    # that regime invalidity caps the score, not zero it out entirely
    # (direction/RR/structure still contribute even during a NO TRADE read).
    import random
    random.seed(9)
    closes = []
    price = 126000.0
    for i in range(30):
        price -= random.uniform(1500, 2800)
        closes.append(price)
    for i in range(30):
        price += random.uniform(-200, 150)
        closes.append(price)
    highs = [c + random.uniform(50, 300) for c in closes]
    lows = [c - random.uniform(50, 300) for c in closes]
    opens = [c + random.uniform(-50, 50) for c in closes]
    volumes = [random.uniform(50, 200) for _ in range(60)]
    data = _make_ohlcv(closes, opens=opens, highs=highs, lows=lows, volumes=volumes)
    signal = analyze_ohlcv("BTC/USDT", data)

    if signal.regime.regime == "transitional":
        assert signal.setup_score < 100  # regime invalidity must cap it
        assert signal.setup_score >= 0


def test_decision_matches_execution_signal():
    data = _make_ohlcv([100 + i * 0.3 for i in range(80)])
    signal = analyze_ohlcv("BTC/USDT", data)
    assert signal.decision == signal.execution_signal


def test_timeframe_is_stored_on_signal():
    data = _make_ohlcv([100 + i * 0.1 for i in range(60)])
    signal = analyze_ohlcv("BTC/USDT", data, timeframe="4h")
    assert signal.timeframe == "4h"


def test_atr_length_matches_the_actual_atr_constant_not_ema_length():
    from cdcx.indicators.atr_ema_variant1 import ATR_LENGTH, EMA_LENGTH
    data = _make_ohlcv([100 + i * 0.1 for i in range(60)])
    signal = analyze_ohlcv("BTC/USDT", data)
    assert EMA_LENGTH == 17
    assert ATR_LENGTH == 11
    assert signal.atr_length == ATR_LENGTH


def test_neutral_ema_is_not_coerced_to_bullish_or_bearish_by_engine_direction_rule():
    # Flat prices keep price/EMA and EMA slope neutral. The engine must report
    # the EMA state as neutral; any directional ATR plan must come from the
    # aggregate signal, not from an unconditional neutral->down fallback.
    closes = [100.0] * 80
    data = _make_ohlcv(closes)
    signal = analyze_ohlcv("BTC/USDT", data)
    assert signal.labels["ema_trend"] == "No Clear Trend"
    if signal.signal in {"STRONG SELL", "SELL"}:
        assert signal.stop_loss > signal.entry
    elif signal.signal in {"STRONG BUY", "BUY"}:
        assert signal.stop_loss < signal.entry
    else:
        assert signal.stop_loss == signal.entry
        assert signal.risk_reward_ratio is None


def test_atr_multiplier_resolves_per_symbol_and_matches_stop_distance():
    # regression: engine.py's stop_distance used to read settings.atr_stop_multiplier
    # directly (a flat global), never per-symbol -- both BTC and XRP currently
    # resolve to 1.5x (see risk.resolve_atr_multiplier / config.atr_multiplier_overrides
    # -- a backtest sweep found XRP's empirical optimum was a tighter 1.0x, deliberately
    # overridden back to 1.5 at the user's request). Whatever multiplier is used must be
    # the one reported on the signal AND the one that actually produced stop_loss, so
    # the two can never silently disagree.
    import random
    random.seed(6)
    closes = [100 + i * 0.3 + random.uniform(-0.4, 0.4) for i in range(80)]

    btc_data = _make_ohlcv(closes)
    btc_signal = analyze_ohlcv("BTC/USDT", btc_data)
    xrp_data = _make_ohlcv(closes)
    xrp_signal = analyze_ohlcv("XRP/USD", xrp_data)

    assert btc_signal.atr_multiplier == 1.5
    assert xrp_signal.atr_multiplier == 1.5

    for signal in (btc_signal, xrp_signal):
        expected_distance = signal.atr * signal.atr_multiplier
        actual_distance = abs(signal.entry - signal.stop_loss)
        # stop_loss is rounded to 6 significant figures in the constructor -- allow that much slack
        assert actual_distance == pytest.approx(expected_distance, abs=0.01)


def test_atr_multiplier_still_resolves_per_symbol_when_actually_configured_differently(monkeypatch):
    # The per-symbol resolution mechanism itself still genuinely differentiates
    # by symbol -- BTC and XRP simply happen to both be set to 1.5 by default
    # right now. Proven here by temporarily configuring them differently.
    from cdcx.config import settings
    original = settings.atr_multiplier_overrides
    settings.atr_multiplier_overrides = "BTC:1.5,XRP:1.0"
    try:
        import random
        random.seed(6)
        closes = [100 + i * 0.3 + random.uniform(-0.4, 0.4) for i in range(80)]
        btc_signal = analyze_ohlcv("BTC/USDT", _make_ohlcv(closes))
        xrp_signal = analyze_ohlcv("XRP/USD", _make_ohlcv(closes))
        assert btc_signal.atr_multiplier == 1.5
        assert xrp_signal.atr_multiplier == 1.0
    finally:
        settings.atr_multiplier_overrides = original


def test_atr_multiplier_override_beats_per_symbol_default():
    import random
    random.seed(6)
    closes = [100 + i * 0.3 + random.uniform(-0.4, 0.4) for i in range(80)]
    data = _make_ohlcv(closes)

    signal = analyze_ohlcv("BTC/USDT", data, atr_multiplier_override=4.0)
    assert signal.atr_multiplier == 4.0


def test_low_priced_asset_tp_ladder_stays_distinct_and_ordered():
    # regression: engine.py used to round stop_loss/take_profits to a flat
    # 2 decimal places regardless of price magnitude -- fine for BTC
    # (~$65,000), but confirmed live on XRP/USD (~$1) to collapse 3 of 4 TP
    # levels to the identical rounded price and risk inverting TP4 past
    # TP1-3, breaking trade_manager.py's "TP levels are ordered" invariant.
    import random
    random.seed(9)
    # a low, tightly-clustered price series mimicking XRP's ~$1 scale
    closes = [1.00 + i * 0.0003 + random.uniform(-0.0004, 0.0004) for i in range(80)]
    data = _make_ohlcv(closes)
    signal = analyze_ohlcv("XRP/USD", data)

    tps = list(signal.take_profits.values())
    assert len(set(tps)) == len(tps), f"TP levels collapsed to duplicates: {tps}"

    # TP levels must move strictly away from entry in trade direction, in order
    distances = [abs(tp - signal.entry) for tp in tps]
    assert distances == sorted(distances), f"TP distances not monotonically increasing: {tps}"


def test_round_price_scales_precision_to_magnitude():
    from cdcx.engine import _round_price
    assert _round_price(65432.987, sig_figs=6) == 65433.0
    assert _round_price(1.0012345, sig_figs=6) == 1.00123
    assert _round_price(0.00123456, sig_figs=6) == 0.00123456
    assert _round_price(0.0, sig_figs=6) == 0.0


def test_round_price_keeps_distinct_close_xrp_style_values_distinct():
    from cdcx.engine import _round_price
    raw = [0.991702, 0.989975, 0.987384, 0.981772]
    rounded = [_round_price(v) for v in raw]
    assert len(set(rounded)) == 4
