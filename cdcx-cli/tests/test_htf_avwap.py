"""
HTF AVWAP context (htf_avwap.py) -- analysis only.

Covers: the AVWAP anchors at exactly the matching AVP's anchor bar (engine
cdcx AVP on 4H/1D/1W, avp_rejection decline-start on 4H), the existing
anchored_vwap math is reused unchanged on CLOSED bars, the forming bar is
only ever "provisional", bad/stale data fails closed to unknown, the
existing --structure report is unchanged above the new section, and nothing
on the trade path imports the module.
"""
import ast
import contextlib
import io
import math
import pathlib
import random
import re

import pytest

from cdcx import avp_rejection, cli, engine, htf_avwap, structure_levels
from cdcx.exchange.cryptocom import OHLCV
from cdcx.indicators import anchored_vwap as avwap_module

TF_S = {"1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800}
NOW = 1_800_000_000.0   # fixed "now" -- every test passes it explicitly


def _series(tf, n=160, seed=1, forming=True, ms=True, volumes=None, closes=None):
    """n bars ending at NOW: with forming=True the last bar is still open at NOW."""
    rng = random.Random(seed)
    step = TF_S[tf]
    last_open = (NOW // step) * step if forming else (NOW // step) * step - step
    ts = [last_open - (n - 1 - i) * step for i in range(n)]
    if closes is None:
        closes, p = [], 1.30
        for _ in range(n):
            p *= 1 + rng.uniform(-0.02, 0.02)
            closes.append(p)
    opens = [closes[0]] + closes[:-1]
    highs = [max(o, c) * 1.004 for o, c in zip(opens, closes)]
    lows = [min(o, c) * 0.996 for o, c in zip(opens, closes)]
    vols = volumes if volumes is not None else [rng.uniform(100, 1000) for _ in range(n)]
    return OHLCV(timestamps=[t * 1000 if ms else t for t in ts], opens=opens, highs=highs, lows=lows,
                 closes=closes, volumes=vols)


def _sig(tf, data):
    return engine.analyze_ohlcv("XRP/USD", data, timeframe=tf)


# --- anchor parity -----------------------------------------------------------

@pytest.mark.parametrize("tf", ["4h", "1d", "1w"])
def test_engine_signal_carries_the_avp_anchor_bar(tf):
    data = _series(tf, seed=3)
    sig = _sig(tf, data)
    from cdcx.indicators import volume_profile_anchor
    lookback = min(engine.settings.swing_lookback, len(data.closes) - 1)
    avp = volume_profile_anchor.analyze(data.highs, data.lows, data.closes, data.volumes,
                                        price=data.closes[-1], anchor_lookback=lookback)
    assert sig.anchored_vp_anchor_ts == data.timestamps[avp.anchor_index] / 1000
    assert (sig.anchored_vp_poc, sig.anchored_vp_vah, sig.anchored_vp_val) == (avp.poc, avp.vah, avp.val)


@pytest.mark.parametrize("tf", ["4h", "1d", "1w"])
def test_derived_anchor_matches_engine_anchor_on_the_same_series(tf):
    data = _series(tf, seed=4)
    sig = _sig(tf, data)
    with_sig = htf_avwap.build_context(tf, data, signal=sig, now=NOW)
    derived = htf_avwap.build_context(tf, data, signal=None, now=NOW)
    assert with_sig.anchor_source == "engine signal" and derived.anchor_source == "derived (same rule)"
    assert with_sig.anchor_ts == derived.anchor_ts == sig.anchored_vp_anchor_ts
    assert with_sig.avp_levels == derived.avp_levels
    assert with_sig.avwap.vwap == derived.avwap.vwap


def test_decline_start_anchor_is_avp_rejections_own_anchor():
    closes = [1.2 + i * 0.01 for i in range(40)] + [1.6 - i * 0.003 for i in range(120)]   # top ~bar 40
    data = _series("4h", n=len(closes), closes=closes)
    ctx = htf_avwap.build_context("4h", data, htf_avwap.ANCHOR_DECLINE_START, now=NOW)
    h, l = data.highs[:-1], data.lows[:-1]   # avp_rejection drops the forming bar too
    idx = avp_rejection.anchor_at_decline_start(h, l)
    assert ctx.anchor_ts == data.timestamps[idx] / 1000
    prof = avp_rejection.anchored_profile(h, l, data.volumes[:-1], idx)
    assert ctx.avp_levels == (prof.poc, prof.vah, prof.val)


@pytest.mark.parametrize("tf", ["4h", "1d", "1w"])
def test_avwap_is_the_existing_calculation_from_the_anchor_bar_on_closed_bars(tf):
    data = _series(tf, seed=6)
    ctx = htf_avwap.build_context(tf, data, signal=_sig(tf, data), now=NOW)
    n = len(data.closes) - 1   # closed bars
    ref = avwap_module.anchored_vwap(data.timestamps[:n], data.opens[:n], data.highs[:n], data.lows[:n],
                                     data.closes[:n], data.volumes[:n], anchor_ts=ctx.anchor_ts)
    assert ctx.data_status == "valid"
    assert ctx.avwap.vwap == ref.vwap and ctx.avwap.sigma == ref.sigma and ctx.avwap.bands == ref.bands
    anchor_idx = [t / 1000 for t in data.timestamps].index(ctx.anchor_ts)
    assert ctx.avwap.bars_used == n - anchor_idx          # period starts exactly at the anchor bar
    assert ctx.avwap.source == "ohlc4" and sorted(ctx.avwap.bands) == [1, 2, 3]


def test_timeframe_mapping_4h_gets_both_anchor_types_1d_1w_one_1h_none():
    data = {tf: _series(tf, seed=7) for tf in ("1h", "4h", "1d", "1w")}
    ctxs = htf_avwap.build_htf_avwap(data, now=NOW)
    got = [(c.timeframe, c.anchor_type) for c in ctxs]
    assert got == [("4h", htf_avwap.ANCHOR_CDCX_AVP), ("4h", htf_avwap.ANCHOR_DECLINE_START),
                   ("1d", htf_avwap.ANCHOR_CDCX_AVP), ("1w", htf_avwap.ANCHOR_CDCX_AVP)]


# --- temporal integrity ------------------------------------------------------

def test_forming_bar_never_enters_the_avwap():
    closed = _series("4h", seed=8, forming=False)
    sig = _sig("4h", closed)
    a = htf_avwap.build_context("4h", closed, signal=sig, now=NOW)
    # same closed history plus one forming bar with a wild price and volume
    step = TF_S["4h"] * 1000
    forming = OHLCV(timestamps=closed.timestamps + [closed.timestamps[-1] + step],
                    opens=closed.opens + [closed.closes[-1]], highs=closed.highs + [9.0],
                    lows=closed.lows + [0.1], closes=closed.closes + [5.0], volumes=closed.volumes + [1e9])
    b = htf_avwap.build_context("4h", forming, signal=sig, now=NOW)
    assert a.avwap.vwap == b.avwap.vwap and a.last_closed_ts == b.last_closed_ts
    assert a.provisional_price is None and b.provisional_price == 5.0
    assert b.provisional == ("provisional cross above" if a.relation != "above" else "none")


def test_provisional_cross_is_labelled_not_confirmed():
    data = _series("4h", seed=9)
    ctx = htf_avwap.build_context("4h", data, now=NOW)
    target = ctx.avwap.vwap * (0.9 if ctx.relation == "above" else 1.1)
    data.closes[-1] = target
    ctx2 = htf_avwap.build_context("4h", data, now=NOW)
    assert ctx2.relation == ctx.relation and ctx2.event == ctx.event   # closed-bar facts unchanged
    assert ctx2.provisional.startswith("provisional cross")
    assert "[provisional]" in htf_avwap.format_htf_avwap_section("XRP/USD", [ctx2])


def test_reclaim_on_the_last_closed_bar():
    # long decline then a closed bar jumping above the AVWAP (but below the decline's top); forming bar after
    closes = [1.5 - i * 0.002 for i in range(150)] + [1.36, 1.36]
    data = _series("4h", n=len(closes), closes=closes, volumes=[500.0] * len(closes))
    ctx = htf_avwap.build_context("4h", data, htf_avwap.ANCHOR_DECLINE_START, now=NOW)
    assert ctx.data_status == "valid"
    assert ctx.relation == "above" and ctx.event == "reclaimed"


def test_period_transition_moves_the_anchor_with_the_avp():
    data = _series("1d", seed=10, n=120)
    a = htf_avwap.build_context("1d", data, now=NOW)
    # a new lowest close on the newest closed bar becomes the AVP anchor -> AVWAP follows
    data.closes[-2] = min(data.closes) * 0.9
    data.lows[-2] = data.closes[-2] * 0.99
    b = htf_avwap.build_context("1d", data, now=NOW)
    assert b.anchor_ts == data.timestamps[-2] / 1000 != a.anchor_ts
    assert b.avwap.bars_used == 1


def test_anchor_on_the_forming_bar_is_insufficient_not_a_signal():
    data = _series("1w", seed=11, n=80)
    data.closes[-1] = min(data.closes) * 0.5      # forming bar is the lowest close -> AVP anchors there
    ctx = htf_avwap.build_context("1w", data, now=NOW)
    assert ctx.data_status == "insufficient" and ctx.confluence == "unknown" and ctx.avwap is None


def test_stale_data_is_unknown():
    data = _series("4h", seed=12)
    ctx = htf_avwap.build_context("4h", data, now=NOW + 10 * TF_S["4h"])
    assert ctx.data_status == "stale" and ctx.relation == "unknown" and ctx.confluence == "unknown"


def test_zero_volume_and_missing_timestamps_fail_closed():
    z = _series("4h", seed=13, volumes=[0.0] * 160)
    ctx = htf_avwap.build_context("4h", z, now=NOW)
    assert ctx.data_status == "invalid" and ctx.confluence == "unknown"
    no_ts = _series("4h", seed=13)
    no_ts.timestamps = []
    ctx2 = htf_avwap.build_context("4h", no_ts, now=NOW)
    assert ctx2.data_status == "invalid" and ctx2.relation == "unknown"


def test_calculation_failure_is_an_explicit_unknown(monkeypatch):
    monkeypatch.setattr(htf_avwap.avwap_module, "anchored_vwap", lambda *a, **k: 1 / 0)
    ctxs = htf_avwap.build_htf_avwap({"4h": _series("4h", seed=14)}, now=NOW)
    assert ctxs and all(c.data_status == "invalid" and c.confluence == "unknown" for c in ctxs)


def test_seconds_and_millisecond_timestamps_agree_and_runs_are_deterministic():
    ms = htf_avwap.build_context("1d", _series("1d", seed=15, ms=True), now=NOW)
    s = htf_avwap.build_context("1d", _series("1d", seed=15, ms=False), now=NOW)
    again = htf_avwap.build_context("1d", _series("1d", seed=15, ms=True), now=NOW)
    assert ms.anchor_ts == s.anchor_ts and ms.avwap.vwap == s.avwap.vwap
    assert htf_avwap.format_htf_avwap_section("X", [ms]) == htf_avwap.format_htf_avwap_section("X", [again])


# --- confluence wording --------------------------------------------------------

def _ctx(relation, avp="none", structure="none", rejection=None):
    c = htf_avwap.HtfAvwapContext(timeframe="4h", anchor_type="t", anchor_source="s")
    c.relation, c.avp_side, c.structure_side, c.rejection_state = relation, avp, structure, rejection
    return c


def test_confluence_aligned_mixed_only_unknown():
    assert htf_avwap._confluence(_ctx("above", "bullish", "bullish")).startswith("aligned bullish")
    assert htf_avwap._confluence(_ctx("below", "bearish")).startswith("aligned bearish")
    # bullish AVP rejection while price stays below the AVWAP -> reported as mixed, not resolved
    mixed = htf_avwap._confluence(_ctx("below", rejection="CONFIRMED"))
    assert mixed.startswith("mixed") and "AVP rejection bullish" in mixed
    assert htf_avwap._confluence(_ctx("above")).startswith("AVWAP only")
    assert htf_avwap._confluence(_ctx("unknown")) == "unknown"


# --- existing report preserved -------------------------------------------------

def _run_report(monkeypatch, tfs="1h,4h,1d,1w"):
    data = {tf: _series(tf, seed=s, n=300) for tf, s in (("1h", 21), ("4h", 22), ("1d", 23), ("1w", 24))}
    monkeypatch.setattr(cli, "_run_single",
                        lambda symbol, timeframe, limit, **kw: engine.analyze_ohlcv(symbol, data[timeframe],
                                                                                    timeframe=timeframe))
    monkeypatch.setattr(cli, "_fetch_structure_map", lambda symbol, timeframe, limit: (
        structure_levels.compute_structure_map(data[timeframe].highs, data[timeframe].lows,
                                               data[timeframe].closes, data[timeframe].volumes), data[timeframe]))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(["--symbol", "XRP/USD", "--timeframes", tfs, "--structure", "--no-vwap-vp"])
    return rc, re.sub(r"Snapshot: \d+", "Snapshot: <ts>", buf.getvalue())


def test_existing_sections_unchanged_and_htf_avwap_is_appended_last(monkeypatch):
    rc, with_section = _run_report(monkeypatch)
    monkeypatch.setattr(htf_avwap, "build_htf_avwap", lambda *a, **k: 1 / 0)   # section disabled
    rc2, without = _run_report(monkeypatch)
    assert rc == rc2 == 0
    # everything before the new section's opening rule must equal the report with the section disabled
    head = with_section[:with_section.rfind("=" * 73, 0, with_section.index("HTF AVWAP CONTEXT"))]
    assert without.rstrip("\n") == head.rstrip("\n")
    for title in ("MARKET REGIME", "MARKET STRUCTURE --", "MULTI-TIMEFRAME SUMMARY", "STRUCTURE SETUP",
                  "SETUP GRADE", "MULTI-TIMEFRAME STRUCTURE / VP SUMMARY", "AVP BULLISH REJECTION"):
        assert title in head
        assert head.index(title) < with_section.index("HTF AVWAP CONTEXT")
    assert "Trade action: NONE" in with_section


def test_engine_report_text_has_no_new_fields(monkeypatch):
    data = _series("4h", seed=30)
    report = engine.format_report(engine.analyze_ohlcv("XRP/USD", data, timeframe="4h"))
    assert "anchored_vp" not in report and "AVWAP" not in report


# --- isolation -----------------------------------------------------------------

TRADE_PATH = ("confluence", "entry_checklist", "no_trade_gate", "no_trade_filter", "risk", "live_execution",
              "trade_manager", "paper_approval", "journal", "setup_grade", "circuit_breaker", "structure_strategy",
              "vp_bos", "avp_rejection", "engine")


def _imports(path):
    tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
    return names


def test_no_trade_path_module_imports_htf_avwap():
    pkg = pathlib.Path(htf_avwap.__file__).parent
    for mod in TRADE_PATH:
        assert not any("htf_avwap" in n for n in _imports(pkg / f"{mod}.py")), mod


def test_htf_avwap_imports_nothing_that_trades_or_writes():
    names = _imports(htf_avwap.__file__)
    for forbidden in ("risk", "live_execution", "trade_manager", "paper_approval", "journal", "exchange",
                      "confluence", "entry_checklist", "telegram_send", "subprocess"):
        assert not any(n == forbidden or n.endswith("." + forbidden) for n in names), forbidden


def test_confluence_flags_mixed_basis_when_engine_avp_includes_the_forming_bar():
    forming = htf_avwap.build_context("4h", _series("4h", seed=40), now=NOW)
    assert forming.avp_includes_forming and forming.avp_side in ("bullish", "bearish")
    assert forming.confluence.endswith("[mixed basis: AVP levels include the forming bar]")
    closed = htf_avwap.build_context("4h", _series("4h", seed=40, forming=False), now=NOW)
    assert not closed.avp_includes_forming and "mixed basis" not in closed.confluence
    decline = htf_avwap.build_context("4h", _series("4h", seed=40), htf_avwap.ANCHOR_DECLINE_START, now=NOW)
    assert not decline.avp_includes_forming and "mixed basis" not in decline.confluence   # closed-bar AVP


# --- cdcx-equity -----------------------------------------------------------------

def _run_equity_report(monkeypatch):
    from cdcx import cli_equity
    data = {tf: _series(tf, seed=s, n=300, ms=False) for tf, s in (("1h", 41), ("4h", 42), ("1d", 43), ("1w", 44))}
    for d in data.values():
        d.market = "us_equity"

    class FakeExchange:
        def fetch_ohlcv(self, symbol, timeframe, limit):
            return data[timeframe]

    monkeypatch.setattr(cli_equity, "_make_exchange", lambda source: FakeExchange())
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli_equity.main(["--source", "webull", "--symbol", "AAPL", "--timeframes", "1h,4h,1d,1w",
                              "--structure-report", "--no-vwap-vp"])
    return rc, re.sub(r"Snapshot: \d+", "Snapshot: <ts>", buf.getvalue())


def test_equity_existing_sections_unchanged_and_htf_avwap_is_appended_last(monkeypatch):
    rc, with_section = _run_equity_report(monkeypatch)
    monkeypatch.setattr(htf_avwap, "build_htf_avwap", lambda *a, **k: 1 / 0)   # section disabled
    rc2, without = _run_equity_report(monkeypatch)
    assert rc == rc2 == 0                     # a failing section never changes the exit status
    head = with_section[:with_section.rfind("=" * 73, 0, with_section.index("HTF AVWAP CONTEXT"))]
    assert without.rstrip("\n") == head.rstrip("\n")
    for title in ("MARKET REGIME", "MULTI-TIMEFRAME SUMMARY", "MULTI-TIMEFRAME STRUCTURE / VP SUMMARY",
                  "AVP BULLISH REJECTION"):
        assert title in head
    assert "Trade action: NONE" in with_section


def test_equity_daily_bar_from_friday_is_not_stale_over_the_weekend():
    from datetime import datetime, timezone
    friday = datetime(2026, 10, 16, tzinfo=timezone.utc).timestamp()          # a Friday, bar opens 00:00Z
    monday = datetime(2026, 10, 19, 12, tzinfo=timezone.utc).timestamp()
    assert not htf_avwap._is_stale(friday, "1d", monday, "us_equity")
    assert htf_avwap._is_stale(friday, "1d", monday, "24x7")                   # crypto has no weekend gap


# --- level colours (user's choice, 2026-10-20) --------------------------------

def _colour_section(monkeypatch, env):
    for k in ("FORCE_COLOR", "NO_COLOR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv(env, "1")
    data = _series("4h", seed=3)
    ctxs = htf_avwap.build_htf_avwap({"4h": data}, signals={"4h": _sig("4h", data)}, now=NOW,
                                     timeframes=["4h"])
    return htf_avwap.format_htf_avwap_section("XRP/USD", ctxs)


def test_poc_yellow_vah_red_val_green_vwap_blue_when_color_forced(monkeypatch):
    from cdcx.utils.color import GREEN, RED, RESET, VWAP_COLOR as BLUE, YELLOW
    out = _colour_section(monkeypatch, "FORCE_COLOR")
    avp = next(l for l in out.splitlines() if "Same-anchor AVP" in l)
    assert re.search(re.escape(YELLOW) + r"POC [\d.]+" + re.escape(RESET), avp)
    assert re.search(re.escape(RED) + r"VAH [\d.]+" + re.escape(RESET), avp)
    assert re.search(re.escape(GREEN) + r"VAL [\d.]+" + re.escape(RESET), avp)
    vwap = next(l for l in out.splitlines() if "sigma" in l and "closed bars" in l)
    assert re.search(re.escape(BLUE) + r"AVWAP [\d.]+" + re.escape(RESET), vwap)


def test_htf_avwap_section_is_plain_text_without_color(monkeypatch):
    out = _colour_section(monkeypatch, "NO_COLOR")
    assert "\033[" not in out and "Same-anchor AVP" in out and "  AVWAP " in out


def test_equity_htf_avwap_section_uses_the_same_level_colours(monkeypatch):
    from cdcx.utils.color import GREEN, RED, VWAP_COLOR as BLUE, YELLOW
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    _, out = _run_equity_report(monkeypatch)
    section = out[out.index("HTF AVWAP CONTEXT"):]
    avp = next(l for l in section.splitlines() if "Same-anchor AVP" in l)
    assert all(c in avp for c in (YELLOW + "POC", RED + "VAH", GREEN + "VAL"))
    assert any(BLUE + "AVWAP" in l for l in section.splitlines())


# --- LTF-style setup block (VP-01..VP-05 + DECISION) inside each HTF context (2026-10-21) ---------

SETUP_BLOCK = ("VP-01 POC reaction", "VP-02 Heavy-volume zone", "VP-03 Trend continuation",
               "VP-04 Value-area breakout", "VP-05 Band exhaustion", "  vwap ", "  volume ", "  structure ",
               "  price_action ", "Context (", "DECISION: ", "STATUS: ", "Next:", "Invalidates:",
               "Execution: NOT AUTHORIZED (analysis only)")


def test_htf_context_carries_the_ltf_setup_block():
    ctx = htf_avwap.build_context("4h", _series("4h", seed=50), now=NOW)
    assert ctx.data_status == "valid" and ctx.vp is not None
    assert [s.code for s in ctx.vp.setups] == ["VP-01", "VP-02", "VP-03", "VP-04", "VP-05"]
    assert (ctx.vp_levels.poc, ctx.vp_levels.vah, ctx.vp_levels.val) == ctx.avp_levels   # same-anchor AVP
    assert ctx.vp_levels.avwap is ctx.avwap                                             # same AVWAP
    text = " ".join(s.detail for s in ctx.vp.setups) + " ".join(ctx.vp.family_detail.values())
    assert "today" not in text and "prior value area" not in text


def test_htf_section_prints_setup_block_for_every_valid_context():
    data = {tf: _series(tf, seed=s, n=300) for tf, s in (("4h", 51), ("1d", 52), ("1w", 53))}
    ctxs = htf_avwap.build_htf_avwap(data, now=NOW, symbol="XRP/USD")
    out = htf_avwap.format_htf_avwap_section("XRP/USD", ctxs)
    valid = [c for c in ctxs if c.vp is not None]
    assert valid
    for label in SETUP_BLOCK:
        assert out.count(label) >= len(valid), label
    assert out.rstrip().splitlines()[-2].startswith("Existing setup grade changed: NO")


def test_htf_setup_block_without_avp_levels_is_explicit_unknown():
    ctx = htf_avwap.HtfAvwapContext(timeframe="1d", anchor_type=htf_avwap.ANCHOR_CDCX_AVP, anchor_source="x",
                                    data_status="valid", avwap=None)
    out = htf_avwap.format_htf_avwap_section("XRP/USD", [ctx])
    assert "AVWAP: unknown" in out


def test_equity_htf_section_has_the_setup_block(monkeypatch):
    rc, out = _run_equity_report(monkeypatch)
    section = out[out.index("HTF AVWAP CONTEXT"):]
    assert rc == 0
    assert "VP-01 POC reaction" in section and "DECISION: " in section and "Execution: NOT AUTHORIZED" in section
