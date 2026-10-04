"""
Advisory sections extended to requested lower timeframes (45m/30m/15m/10m/5m/1m):
ATR alignment, VP hierarchy, per-TF STRUCTURE block, structure-setup context,
VP-BOS rows, AVP, range preview. Each lower timeframe is shown on its own
"context only" lines; the protected 1W/1D/4H/1H counts, roles and gate never
change because of them.
"""
from types import SimpleNamespace

from cdcx import avp_rejection, cli, mtf_context, vp_bos


def _sig(atr="Flat", vp="none", vp_dir=None, regime="trending", entry=1.49):
    return SimpleNamespace(labels={"atr_expansion": atr}, vp_setup_type=vp, vp_setup_direction=vp_dir,
                           regime=SimpleNamespace(regime=regime), entry=entry)


CORE = {"1w": _sig("Flat", "value_area_breakout", "down"), "1d": _sig("Contraction", "value_area_breakout", "up"),
        "4h": _sig("Contraction"), "1h": _sig("Flat")}


def test_lower_timeframes_helper_orders_slowest_first_and_ignores_core_and_higher():
    assert mtf_context.lower_timeframes(["1h", "5m", "45m", "1w", "15m", "1m", "10m", "30m", "2h", "5m"]) == [
        "45m", "30m", "15m", "10m", "5m", "1m"]


def test_atr_alignment_keeps_the_protected_count_and_lists_lower_tfs_separately():
    results = {**CORE, "15m": _sig("Expansion"), "5m": _sig("Expansion"), "45m": _sig("Flat")}
    a = mtf_context.build_atr_alignment(results)
    assert (a.expansion_count, a.total_count) == (0, 4)                   # lower expansions never counted
    text = mtf_context.format_atr_alignment(a)
    assert text.startswith("ATR ALIGNMENT: 0/4 timeframes expanding")
    assert "LOWER TIMEFRAMES (context only, not in the 4): 2/3 expanding" in text
    assert text.index("    45M:") < text.index("    15M:") < text.index("    5M:")


def test_core_only_output_is_unchanged():
    assert "LOWER" not in mtf_context.format_atr_alignment(mtf_context.build_atr_alignment(CORE))
    h = mtf_context.build_vp_hierarchy(CORE)
    assert h.lower_entries == [] and "context only" not in mtf_context.format_vp_hierarchy(h)


def test_vp_hierarchy_lists_lower_tfs_without_touching_the_macro_note():
    results = {**CORE, "15m": _sig(vp="value_area_breakout", vp_dir="up")}
    h = mtf_context.build_vp_hierarchy(results)
    core_note = mtf_context.build_vp_hierarchy(CORE).macro_conflict
    assert h.macro_conflict == core_note                                   # still 1W vs fastest CORE tf
    assert "15M [lower timeframe, context only]: Value Area Breakout (bullish)" in mtf_context.format_vp_hierarchy(h)


def _row(signal, direction="up"):
    return vp_bos.VpBos(signal=signal, acceptance="CONFIRMED" if signal.startswith("VP-BOS") else "--",
                        status="TRANSITIONAL", structure="HH/HL/LH/HL", poc_direction="flat",
                        direction=direction if signal != "NONE" else None, level_price=1.5 if signal != "NONE" else None)


def test_vp_bos_lower_rows_are_shown_but_never_counted():
    by_tf = {"1w": _row("NONE"), "1d": _row("NONE"), "4h": _row("NONE"), "1h": _row("NONE"),
             "15m": _row("VP-BOS-BULL"), "5m": _row("VP-BOS-BULL")}
    text = vp_bos.format_vp_bos_section("XRP/USD", by_tf)
    assert "VP-BOS CONFIRMED: 0/4  (bull 0, bear 0)  ->  DIRECTION: NONE" in text  # 2 lower bulls don't make 2-of-4
    assert "lower timeframes (advisory, not counted below)" in text
    assert "LOWER TF VP-BOS:  2/2 confirmed (bull 2, bear 0), 0 pending  (15M, 5M; context only)" in text
    assert text.index("1h ") < text.index("15m ")


def test_vp_bos_and_avp_builders_default_to_their_protected_timeframes():
    assert vp_bos.TIMEFRAMES == ("1w", "1d", "4h", "1h") and avp_rejection.TIMEFRAMES == ("4h", "1h")
    assert vp_bos.build_vp_bos_by_tf({}) == {} and avp_rejection.build_avp_by_tf("XRP/USD", {}) == {}
    calls = []
    orig = vp_bos.classify_vp_bos
    try:
        vp_bos.classify_vp_bos = lambda *a, **k: calls.append(a[5]) or _row("NONE")
        data = SimpleNamespace(timestamps=[], highs=[], lows=[], closes=[], volumes=[])
        vp_bos.build_vp_bos_by_tf({"1h": data, "15m": data})
        assert calls == ["1h"]                                             # default ignores extras
        vp_bos.build_vp_bos_by_tf({"1h": data, "15m": data}, timeframes=["1h", "15m"])
        assert calls == ["1h", "1h", "15m"]
    finally:
        vp_bos.classify_vp_bos = orig


def test_merged_structure_block_prints_for_lower_tfs_and_still_skips_others(monkeypatch, capsys):
    smap = SimpleNamespace(poc=1.4888, resistance=1.4922, support=1.4845, fvgs=[], condition="ranging")
    monkeypatch.setattr(cli, "_fetch_structure_map", lambda s, tf, n: (smap, SimpleNamespace(closes=[1.49])))
    monkeypatch.setattr(cli.structure_levels, "format_structure_map", lambda name, s: f"STRUCTURE — {name}")
    cache = {}
    cli._print_merged_structure_block("XRP/USD", "15m", 200, cache)
    cli._print_merged_structure_block("XRP/USD", "2h", 200, cache)          # neither a role nor lower -> nothing
    out = capsys.readouterr().out
    assert "STRUCTURE — 15M (lower timeframe, advisory)" in out and "2H" not in out
    assert list(cache) == ["15m"]


def test_range_preview_adds_ranging_lower_tfs_after_the_execute_equivalent(monkeypatch, capsys):
    vp = SimpleNamespace(poc=1.4887, vah=1.5114, val=1.4796)
    fetched = []
    monkeypatch.setattr(cli, "_range_setup_inputs", lambda s, tf, n: fetched.append(tf) or (None, [], [], [50, 51], vp, []))
    results = {"1h": _sig(regime="ranging"), "4h": _sig(regime="ranging"),
               "45m": _sig(regime="ranging"), "15m": _sig(regime="trending")}
    cli._print_range_setup_preview("XRP/USD", results, 200)
    out = capsys.readouterr().out
    assert fetched == ["1h", "45m"]                                        # 15m trending -> no preview
    assert "RANGE MODE PREVIEW (1H, read-only): the range-boundary check --execute would run." in out
    assert "RANGE MODE PREVIEW (45M, read-only): lower timeframe, advisory -- --execute never uses it." in out
