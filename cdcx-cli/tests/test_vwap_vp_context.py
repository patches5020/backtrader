"""--vwap-vp Context / STATUS / Next / Invalidates (display only, 2026-10-17)."""

import random
from types import SimpleNamespace

import pytest

from cdcx import cli
from cdcx.exchange.cryptocom import OHLCV
from cdcx.volume_profile import vwap_confluence as vc

LEVELS = SimpleNamespace(avwap=SimpleNamespace(vwap=1.3166))


def _res(q, d=None, families=None, htf="none", z=-0.8, hi=1.3519, lo=1.2877, reason="r"):
    return vc.VwapVpResult(status="OK" if q != "UNKNOWN" else "UNKNOWN", qualification=q,
                           qualification_direction=d, qualification_reason=reason,
                           families=families or {}, htf=htf, z=z, swing_high=hi, swing_low=lo)


@pytest.mark.parametrize("q,label", [
    ("UNKNOWN", "DATA UNKNOWN"), ("CONFLICT", "CONFLICT -- monitor only"), ("NONE", "MONITOR"),
    ("CANDIDATE", "SETUP DEVELOPING"), ("QUALIFIED", "CONFIRMED -- evaluate the existing gates"),
])
def test_status_relabels_the_decision(q, label):
    d = "bearish" if q in ("CANDIDATE", "QUALIFIED") else None
    assert vc.disposition(_res(q, d, {"volume": d, "price_action": d}), LEVELS, "1h")[0] == label


def test_bearish_candidate_next_and_invalidates_use_existing_levels():
    fam = {"vwap": None, "volume": "bearish", "structure": None, "price_action": "bearish"}
    status, nxt, inval = vc.disposition(_res("CANDIDATE", "bearish", fam), LEVELS, "1h")
    assert status == "SETUP DEVELOPING"
    assert nxt == "1H close below 1.2877 (bearish BOS) AND cdcx 2-of-4 confluence turns bearish"
    assert inval == "1H close back above AVWAP 1.3166 or bullish BOS: 1H close above 1.3519"


def test_bullish_candidate_mirrors():
    fam = {"vwap": "bullish", "volume": None, "structure": "bullish", "price_action": None}
    _, nxt, inval = vc.disposition(_res("CANDIDATE", "bullish", fam, htf="bullish", z=0.6), LEVELS, "15m")
    assert nxt == "a third evidence family agrees"           # structure + HTF already agree
    assert inval == "15M close back below AVWAP 1.3166 or bearish BOS: 15M close below 1.2877"


def test_unknown_is_data_unknown_with_no_thesis():
    status, nxt, inval = vc.disposition(_res("UNKNOWN"), LEVELS, "1h")
    assert status == "DATA UNKNOWN" and "restore" in nxt and inval.startswith("--")
    no_vwap = SimpleNamespace(avwap=None)
    assert vc.disposition(_res("CANDIDATE", "bearish", {"volume": "bearish"}), no_vwap, "1h")[0] == "DATA UNKNOWN"


def test_missing_swing_levels_are_reported_unknown_not_invented():
    fam = {"volume": "bearish", "price_action": "bearish"}
    _, nxt, inval = vc.disposition(_res("CANDIDATE", "bearish", fam, hi=None, lo=None), LEVELS, "1h")
    assert "level unknown" in nxt
    assert inval == "1H close back above AVWAP 1.3166"                      # no opposite swing -> no BOS clause
    # price already on the wrong side of the AVWAP and no swing -> nothing to reference
    _, _, inval2 = vc.disposition(_res("CANDIDATE", "bearish", fam, hi=None, lo=None, z=0.4), LEVELS, "1h")
    assert inval2 == "UNKNOWN (no reference level available)"


def test_avwap_clause_only_while_price_is_on_the_thesis_side():
    fam = {"volume": "bearish", "price_action": "bearish"}
    _, _, inval = vc.disposition(_res("CANDIDATE", "bearish", fam, z=0.3), LEVELS, "1h")
    assert "AVWAP" not in inval and "1.3519" in inval


def test_qualified_and_conflict_and_none():
    fam = {"vwap": "bearish", "volume": "bearish", "structure": "bearish"}
    _, nxt, _ = vc.disposition(_res("QUALIFIED", "bearish", fam, htf="bearish"), LEVELS, "1h")
    assert "existing gates" in nxt
    _, nxt, inval = vc.disposition(_res("CONFLICT", reason="bullish: vwap vs bearish: structure"), LEVELS, "1h")
    assert "stop disagreeing" in nxt and inval.startswith("--")
    assert vc.disposition(_res("NONE"), LEVELS, "1h")[1] == "2+ evidence families agree in one direction"


# ---------------------------------------------------------------- context
H = 3600
NOW = 1_800_000_000 - (1_800_000_000 % H) + 1800      # half way through a 1h bar


def _hourly(n, forming=True, seed=2, end=NOW):
    rng = random.Random(seed)
    last_open = (end // H) * H if forming else (end // H) * H - H
    ts = [last_open - H * (n - 1 - i) for i in range(n)]
    c, closes = 1.3, []
    for _ in range(n):
        c *= 1 + rng.uniform(-0.006, 0.006)
        closes.append(c)
    opens = [closes[0]] + closes[:-1]
    return OHLCV([t * 1000 for t in ts], opens, [max(o, x) * 1.002 for o, x in zip(opens, closes)],
                 [min(o, x) * 0.998 for o, x in zip(opens, closes)], closes, [100.0 + i % 7 for i in range(n)])


def test_context_uses_closed_bars_only():
    d = _hourly(200)
    ctx = vc.context_from_closed("X/USD", d, "1h", now=NOW)
    assert ctx.status == "OK" and ctx.last_bar_ts == d.timestamps[-2] / 1000      # forming bar dropped
    # whatever the forming bar does, the context can't change (no look-ahead)
    d.closes[-1] *= 1.5
    d.highs[-1] *= 1.5
    d.volumes[-1] *= 50
    again = vc.context_from_closed("X/USD", d, "1h", now=NOW)
    assert (again.adx, again.rsi, again.volume_ratio, again.regime) == (ctx.adx, ctx.rsi, ctx.volume_ratio, ctx.regime)


def test_context_fails_closed():
    assert vc.context_from_closed("X/USD", _hourly(40), "1h", now=NOW).status == "UNKNOWN"          # too short
    stale = vc.context_from_closed("X/USD", _hourly(200, end=NOW - 10 * H), "1h", now=NOW)
    assert stale.status == "UNKNOWN" and "stale" in stale.reason
    broken = vc.context_from_closed("X/USD", object(), "1h", now=NOW)
    assert broken.status == "UNKNOWN"


def test_context_line_formats():
    assert "not evaluated" in vc.format_context(None, "1h")
    assert "UNKNOWN -- too short" in vc.format_context(vc.Context("UNKNOWN", "too short"), "1h")
    ok = vc.Context("OK", regime="transitional", adx=24.1, plus_di=12.0, minus_di=20.0, rsi=41.3, volume_ratio=0.8)
    line = vc.format_context(ok, "1h")
    assert "regime TRANSITIONAL" in line and "-DI leads" in line and "RSI(17) 41.3" in line
    assert "not scored" in line


# ---------------------------------------------------------------- CLI wiring
def test_crypto_section_keeps_its_window_and_gets_longer_context(monkeypatch, capsys):
    seen = {}

    class Fake:
        def __init__(self, *a, **k):
            pass

        def fetch_ohlcv(self, symbol, timeframe="1h", limit=0):
            seen.setdefault("fetched", []).append(timeframe)
            return _hourly(limit, end=__import__("time").time())

    def fake_build(symbol, data, timeframe, results, context_data=None, fine_data=None):
        seen["fine"] = fine_data is not None
        seen["section"], seen["context"] = len(data.timestamps), len(context_data.timestamps)
        seen["same_tail"] = data.timestamps == context_data.timestamps[-len(data.timestamps):]
        return "ok"

    monkeypatch.setattr("cdcx.exchange.cryptocom.CryptoComExchange", Fake)
    monkeypatch.setattr("cdcx.volume_profile.vwap_confluence.build_section", fake_build)
    cli._print_vwap_vp("XRP/USD", "1h", results={})
    assert seen["section"] == 58 and seen["context"] == max(58, cli.settings.default_limit) and seen["same_tail"]
    assert seen["fetched"] == ["1h", "5m"] and seen["fine"]          # 5m bars only feed the vwap-vp-2 line
    assert "ok" in capsys.readouterr().out


def test_section_shows_new_lines_and_keeps_decision_and_execution():
    d = _hourly(260, forming=True, end=NOW)
    text = vc.build_section("X/USD", d, "1h", results={}, now=NOW)
    for needle in ("Context (1h, closed bars)", "DECISION:", "STATUS:", "  Next:", "  Invalidates:",
                   "Execution: NOT AUTHORIZED (analysis only)"):
        assert needle in text, needle
