import pytest

from cdcx.exchange.cryptocom import OHLCV
from cdcx.volume_profile import vwap_confluence as vc
from cdcx.volume_profile.prev_day import prev_day_levels

H = 3600
D0 = 1_792_022_400                       # prior UTC day starts here; "today" starts at D0 + 86400


def _data(today_closes, today_vol=100.0, spread=0.1, today_opens=None):
    """24 prior-day 1h bars rotating 99.5-100.5 (POC ~100), then today's bars from `today_closes`
    (each opening at the previous close unless `today_opens` is given). Keep today under 24 bars, or
    today becomes a whole completed UTC day."""
    prior = [100 + (0.5 if i % 4 == 1 else -0.5 if i % 4 == 3 else 0.0) for i in range(24)]
    closes = prior + list(today_closes)
    opens = [closes[0]] + closes[:-1]
    if today_opens is not None:
        opens[24:] = today_opens
    highs = [max(o, c) + spread for o, c in zip(opens, closes)]
    lows = [min(o, c) - spread for o, c in zip(opens, closes)]
    vols = [100.0] * 24 + [today_vol] * len(today_closes)
    ts = [(D0 + i * H) * 1000 for i in range(len(closes))]
    return OHLCV(ts, opens, highs, lows, closes, vols)


def _zigzag(n=20, up=0.25, down=0.15):
    p, out = 100.0, []
    for k in range(n):
        p += up if k % 2 == 0 else -down
        out.append(round(p, 3))
    return out


def _run(today, **kw):
    d = _data(today, **kw)
    now = D0 + (len(d.closes)) * H + 60          # every bar closed
    lv = prev_day_levels(d, "1h", now=now)
    assert lv.status == "OK", lv.reasons
    return lv, vc.classify(lv, d), d


def _setup(res, code):
    return next(s for s in res.setups if s.code == code)


def test_unknown_levels_pass_through():
    d = _data([100.0] * 3)
    lv = prev_day_levels(d, "1h", now=D0 + 40 * H)            # stale feed -> UNKNOWN
    res = vc.classify(lv, d)
    assert res.status == "UNKNOWN" and res.qualification == "UNKNOWN"
    assert res.execution.startswith("NOT AUTHORIZED")


def test_balance_when_price_rotates_around_vwap():
    _, res, _ = _run([100.4, 99.6, 100.4, 99.6, 100.4, 99.6, 100.4, 99.6])
    assert res.condition == "BALANCE"
    assert res.families["vwap"] is None


def test_trend_up_with_accepted_breakout():
    lv, res, _ = _run(_zigzag(), today_vol=300.0)
    assert res.condition == "TREND" and res.condition_direction == "bullish"
    assert res.families["vwap"] == "bullish"
    b = _setup(res, "VP-04")
    assert b.state == "ACCEPTED" and b.direction == "bullish"
    assert res.families["volume"] == "bullish"


def test_straight_line_rally_is_expansion_not_trend():
    _, res, _ = _run([100 + 0.4 * k for k in range(1, 13)])
    assert res.condition == "EXPANSION" and res.families["vwap"] is None


def test_expansion_votes_nothing():
    _, res, _ = _run([100.0] * 6 + [104.0], today_vol=100.0)
    assert res.condition == "EXPANSION"
    assert res.families["vwap"] is None


def test_breakout_that_falls_back_inside_is_a_failed_sweep():
    lv, res, _ = _run([100.0, 100.2, lv_top := 101.5, 100.0])
    b = _setup(res, "VP-04")
    assert b.state == "FAILED" and b.direction == "bullish"
    assert res.families["volume"] is None


def test_breakout_pending_until_enough_closes():
    _, res, _ = _run([100.0, 100.0, 101.5])
    assert _setup(res, "VP-04").state == "PENDING"


def test_poc_reclaim_confirmed_when_next_close_holds():
    lv, _, _ = _run([100.0])
    poc = lv.poc
    # a bar dips below POC and closes above it, then the next bar holds
    lv2, res, _ = _run([poc + 0.3, poc + 0.05, poc + 0.2], spread=0.08,
                       today_opens=[poc + 0.3, poc + 0.3, poc + 0.2])
    s = _setup(res, "VP-01")
    assert s.direction == "bullish" and s.state == "CONFIRMED"


def test_zone_untested_while_price_stays_away():
    _, res, _ = _run([102.0, 102.1, 102.0, 102.2], today_opens=[102.0, 102.0, 102.1, 102.0])
    assert _setup(res, "VP-02").state in ("UNTESTED", "APPROACHING")


@pytest.mark.parametrize("fam,htf,expected", [
    ({"vwap": "bullish", "volume": "bullish", "structure": "bullish", "price_action": None}, True, "QUALIFIED"),
    ({"vwap": "bullish", "volume": "bullish", "structure": "bullish", "price_action": None}, None, "CANDIDATE"),
    ({"vwap": "bullish", "volume": "bullish", "structure": None, "price_action": "bullish"}, True, "CANDIDATE"),
    ({"vwap": "bullish", "volume": None, "structure": "bearish", "price_action": None}, True, "CONFLICT"),
    ({"vwap": None, "volume": None, "structure": "bearish", "price_action": None}, True, "NONE"),
    ({"vwap": None, "volume": None, "structure": None, "price_action": None}, True, "NONE"),
])
def test_qualify(fam, htf, expected):
    assert vc.qualify(fam, htf)[0] == expected


def test_format_never_authorizes_execution():
    lv, res, d = _run(_zigzag(), today_vol=300.0)
    text = vc.format_vwap_vp("TEST/USD", "1h", lv, res, d.closes[-1])
    assert "Execution: NOT AUTHORIZED (analysis only)" in text
    assert "POC" in text and "+/-3" in text
