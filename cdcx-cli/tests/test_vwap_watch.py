"""vwap_watch: closed-bar shadow watcher -- state transitions, replay, dedup, stale data,
anchor boundary, no look-ahead, monitor-only isolation."""

import ast
import json
import pathlib
import random
import subprocess
import sys
from types import SimpleNamespace

from cdcx.exchange.cryptocom import OHLCV
from cdcx.volume_profile import vwap_confluence as vc
from cdcx.volume_profile import vwap_watch as vw
from cdcx.volume_profile.prev_day import PrevDayLevels

H = 3600
DAY = 86400
A0 = 1_799_971_200            # a UTC midnight (anchor = previous day's 00:00Z)
A1 = A0 + DAY
BAR0 = A1 + 10 * H            # a bar "today" (10:00Z)


# ------------------------------------------------------------------ fabricated snapshots
def _levels(anchor=A0, vwap=1.30):
    lv = PrevDayLevels(status="OK", session_start=anchor, session_end=anchor + DAY, poc=1.3, vah=1.32, val=1.28)
    lv.avwap = SimpleNamespace(vwap=vwap, sigma=0.01, bands={1: (vwap - 0.01, vwap + 0.01)},
                               anchor_ts=anchor, last_bar_ts=None)
    return lv


def _res(fam=None, htf=None, setups=(), swing_high=1.35, swing_low=1.25, bos=(None, None, None)):
    fam = {"vwap": None, "volume": None, "structure": None, "price_action": None, **(fam or {})}
    q, qd, why = vc.qualify(fam, htf)
    return vc.VwapVpResult(status="OK", families=fam, qualification=q, qualification_direction=qd,
                           qualification_reason=why, htf=htf, setups=list(setups), swing_high=swing_high,
                           swing_low=swing_low, z=0.0, bos_state=bos[0], bos_direction=bos[1], bos_level=bos[2])


def _snap(res, k=0, close=1.31, anchor=A0, dq="valid", reason=""):
    t = BAR0 + k * H
    return vw.Snapshot("X/USD", "1h", "24x7", evaluated_at=t + H + 1, data_quality=dq, dq_reason=reason,
                       bar_ts=t, bar_close_ts=t + H, close=close, levels=_levels(anchor), res=res)


BASE = vw.DirState(baselined=True)          # a direction whose first valid bar was already recorded


def _state():
    from dataclasses import asdict
    return {"directions": {f"X/USD|1h|{d}": asdict(BASE) for d in vw.DIRECTIONS}, "notify": {}}


def _run(seq, d="bullish", start=BASE):
    st, out = start, []
    for snap in seq:
        st, evs = vw.step(st, snap, d)
        out.append((st.state, [e.event for e in evs]))
    return st, out


BULL2 = {"vwap": "bullish", "price_action": "bullish"}
BULL3S = {"vwap": "bullish", "price_action": "bullish", "structure": "bullish"}


def test_promotion_path_and_invalidation_level():
    st, out = _run([_snap(_res({"vwap": "bullish"}), 0), _snap(_res(BULL2), 1),
                    _snap(_res(BULL3S, htf="bullish"), 2)])
    assert out == [("WATCH", ["ENTRY_WATCH"]), ("SETUP", ["ENTRY_SETUP"]),
                   ("CONFIRMATION_CANDIDATE", ["ENTRY_CONFIRMATION_CANDIDATE"])]
    assert st.invalidation_level == 1.25            # bullish: the swing low when the SETUP formed


def test_jump_from_idle_is_one_event_and_htf_is_required_for_confirmation():
    _, out = _run([_snap(_res(BULL3S, htf="none"), 0)])
    assert out == [("SETUP", ["ENTRY_SETUP"])]       # 3 families incl. structure but no HTF -> not CC
    _, out = _run([_snap(_res(BULL3S, htf=None), 0)])
    assert out[0][0] == "SETUP"


def test_demotion_is_deterioration_not_invalidation():
    _, out = _run([_snap(_res(BULL2), 0), _snap(_res({"vwap": "bullish"}), 1), _snap(_res(), 2)])
    assert out == [("SETUP", ["ENTRY_SETUP"]), ("WATCH", ["SETUP_DETERIORATION"]), ("IDLE", ["WATCH_CLEARED"])]


def test_close_beyond_recorded_swing_invalidates_then_resets():
    _, out = _run([_snap(_res(BULL2), 0), _snap(_res(BULL2, swing_low=1.20), 1, close=1.24), _snap(_res(), 2)])
    assert out == [("SETUP", ["ENTRY_SETUP"]), ("INVALIDATED", ["STRUCTURAL_INVALIDATION"]), ("IDLE", [])]


def test_structure_flip_invalidates_a_setup():
    _, out = _run([_snap(_res(BULL2), 0), _snap(_res({**BULL2, "structure": "bearish"}), 1)])
    assert out[1] == ("INVALIDATED", ["STRUCTURAL_INVALIDATION"])


def test_avwap_lost_keeps_the_state():
    _, out = _run([_snap(_res(BULL2), 0, close=1.31), _snap(_res(BULL2), 1, close=1.29)])
    assert out[1] == ("SETUP", ["AVWAP_LOST"])


def test_anchor_rollover_expires_active_state_only():
    _, out = _run([_snap(_res({"vwap": "bullish"}), 0), _snap(_res(), 1, anchor=A1), _snap(_res(), 2, anchor=A1)])
    assert out == [("WATCH", ["ENTRY_WATCH"]), ("EXPIRED", ["EXPIRED"]), ("IDLE", [])]
    _, out = _run([_snap(_res(), 0), _snap(_res(), 1, anchor=A1)])
    assert out == [("IDLE", []), ("IDLE", [])]       # nothing active -> silent reset


def test_new_anchor_can_promote_on_the_rollover_bar():
    _, out = _run([_snap(_res(BULL2), 0), _snap(_res({"vwap": "bullish"}), 1, anchor=A1)])
    assert out[1] == ("WATCH", ["EXPIRED", "ENTRY_WATCH"])


def test_unknown_data_freezes_state_and_cannot_confirm():
    seq = [_snap(_res(BULL2), 0),
           _snap(_res(BULL3S, htf="bullish"), 1, dq="unknown", reason="data is stale"),
           _snap(_res(BULL3S, htf="bullish"), 2, dq="unknown", reason="data is stale"),
           _snap(_res(BULL2), 3)]
    _, out = _run(seq)
    assert out == [("SETUP", ["ENTRY_SETUP"]), ("SETUP", ["DATA_UNKNOWN"]), ("SETUP", []),
                   ("SETUP", ["DATA_RESTORED"])]


def test_same_bar_twice_is_a_no_op():
    snap = _snap(_res(BULL2), 0)
    st, _ = vw.step(None, snap, "bullish")
    again, evs = vw.step(st, snap, "bullish")
    assert evs == [] and again == st


def test_directions_are_independent():
    snap = _snap(_res({"vwap": "bearish", "structure": "bearish"}), 0, close=1.29)
    bull, bevs = vw.step(BASE, snap, "bullish")
    bear, sevs = vw.step(BASE, snap, "bearish")
    assert (bull.state, bevs) == ("IDLE", []) and bear.state == "SETUP"
    assert bear.invalidation_level == 1.35           # bearish: the swing high


def test_retest_reported_once_per_anchor_and_level():
    r = _res(BULL2, bos=("retest_held", "bullish", 1.3013))
    _, out = _run([_snap(r, 0), _snap(r, 1), _snap(r, 2, anchor=A1)])
    assert [e for _, e in out] == [["ENTRY_SETUP", "RETEST_HOLD"], [], ["EXPIRED", "ENTRY_SETUP", "RETEST_HOLD"]]
    sweep = vc.Setup("VP-04", "Value-area breakout", "FAILED", "bearish", "broke 1.29264, closed back inside (sweep)")
    _, out = _run([_snap(_res(setups=[sweep]), 0)], d="bearish")
    assert out == [("IDLE", ["RETEST_FAILURE"])]
    pull = [vc.Setup("VP-03", "Trend continuation", st, "bearish", f"pullback, close below {x}")
            for st, x in (("PENDING", 1.2689), ("PENDING", 1.2909), ("CONFIRMED", 1.2909))]
    _, out = _run([_snap(_res(setups=[p]), k) for k, p in enumerate(pull)], d="bearish")
    assert [e for _, e in out] == [["ENTRY_WATCH", "RETEST_HOLD"], [], ["RETEST_HOLD"]]   # new pullback bar != news


def test_early_setup_state_counts_as_watch_unless_opposed():
    pend = vc.Setup("VP-04", "Value-area breakout", "PENDING", "bearish", "broke 1.29, 1/3 closes so far")
    assert vw.target_state(_res(setups=[pend]), "bearish")[0] == "WATCH"
    assert vw.target_state(_res({"price_action": "bullish"}, setups=[pend]), "bearish")[0] == "IDLE"


# ------------------------------------------------------------------ journal / notify / record
def test_journal_dedup_append_only_and_record_fields(tmp_path):
    j = vw.Journal(str(tmp_path / "journal.jsonl"))
    state = _state()
    recs = vw.run_once(_snap(_res(BULL2), 0), state, j)
    first = (tmp_path / "journal.jsonl").read_text()
    assert [r["event"] for r in recs] == ["ENTRY_SETUP"]
    # the same bar again, even from a fresh (baselined) state, writes nothing new
    assert vw.run_once(_snap(_res(BULL2), 0), _state(), vw.Journal(j.path)) == []
    vw.run_once(_snap(_res(), 1), state, j)
    text = (tmp_path / "journal.jsonl").read_text()
    assert text.startswith(first) and len(text.splitlines()) == 2
    r = json.loads(first)
    assert r["execution_authorized"] is False and r["mode"] == "monitor_only" and r["position"] is None
    assert "Paper Trading" in r["position_note"] and r["bar_status"] == "closed"
    assert r["version"] == vw.WATCH_VERSION and r["ruleset"] == vc.RULESET_VERSION
    assert r["anchor"] == "2027-01-15T00:00:00Z" and r["bar_open"] == "2027-01-16T10:00:00Z"
    assert r["inputs"]["avwap"] == 1.30 and r["inputs"]["families"]["vwap"] == "bullish"
    assert r["key"] == vw.dedup_key(_snap(_res(BULL2), 0), vw.Event("ENTRY_SETUP", "entry", "bullish", "", "", "",
                                                                   key_part=f"bar{BAR0}"))


def test_notify_rate_limited_but_always_journaled(tmp_path):
    sent = []
    j = vw.Journal(str(tmp_path / "j.jsonl"))
    state = _state()
    seq = [_snap(_res({"vwap": "bullish"}), 0), _snap(_res(BULL2), 1), _snap(_res(), 2)]
    outcomes = [vw.run_once(s, state, j, notify_fn=sent.append, min_interval_s=2 * H)[0]["notify"] for s in seq]
    assert outcomes[0] == "sent" and outcomes[1].startswith("suppressed") and outcomes[2] == "sent"
    assert len(sent) == 2 and len(j.path and open(j.path).read().splitlines()) == 3
    assert "NOT AUTHORIZED" in sent[0]

    def boom(_):
        raise RuntimeError("no network")
    rec = vw.run_once(_snap(_res(BULL2), 5), _state(), vw.Journal(str(tmp_path / "k.jsonl")),
                      notify_fn=boom)
    assert rec[0]["notify"].startswith("failed")


# ------------------------------------------------------------------ real classifier on synthetic bars
NOW = A1 + 14 * H + 1800      # 14:30Z: the 14:00 bar is forming


def _hourly(end=NOW, n=120, seed=3, drop=None):
    rng = random.Random(seed)
    last_open = (end // H) * H
    ts = [last_open - H * (n - 1 - i) for i in range(n)]
    c, closes = 1.30, []
    for _ in range(n):
        c *= 1 + rng.uniform(-0.006, 0.006)
        closes.append(c)
    opens = [closes[0]] + closes[:-1]
    d = OHLCV([t * 1000 for t in ts], opens, [max(o, x) * 1.002 for o, x in zip(opens, closes)],
              [min(o, x) * 0.998 for o, x in zip(opens, closes)], closes, [100.0 + (i * 37) % 23 for i in range(n)])
    if drop is not None:
        for k in ("timestamps", "opens", "highs", "lows", "closes", "volumes"):
            getattr(d, k).pop(drop)
    return d


def test_evaluate_reads_closed_bars_only():
    d = _hourly()
    a = vw.evaluate("X/USD", d, "1h", now=NOW)
    assert a.data_quality == "valid" and a.bar_ts == d.timestamps[-2] / 1000 and a.anchor == A0
    d.closes[-1] *= 1.3
    d.highs[-1] *= 1.3
    d.volumes[-1] *= 40                               # the forming bar can't change anything
    b = vw.evaluate("X/USD", d, "1h", now=NOW)
    assert (b.window_hash, b.res.families, b.res.qualification, b.close) == \
        (a.window_hash, a.res.families, a.res.qualification, a.close)


def test_stale_and_gapped_data_are_unknown():
    stale = vw.evaluate("X/USD", _hourly(end=NOW - 10 * H), "1h", now=NOW)
    assert stale.data_quality == "unknown" and "stale" in stale.dq_reason
    gap = vw.evaluate("X/USD", _hourly(drop=-4), "1h", now=NOW)        # a bar missing from today
    assert gap.data_quality == "unknown" and "gap" in gap.dq_reason
    prior = vw.evaluate("X/USD", _hourly(drop=-25), "1h", now=NOW)     # a bar missing from the prior day
    assert prior.data_quality == "unknown" and "missing" in prior.dq_reason
    st, evs = vw.step(None, gap, "bearish")
    assert [e.event for e in evs] == ["DATA_UNKNOWN"] and st.state == "IDLE"


def test_anchor_boundary_at_utc_midnight():
    before = vw.evaluate("X/USD", _hourly(end=A1 + 2 * H), "1h", now=A1 - 1)       # 23:59:59: 22:00 bar closed
    after = vw.evaluate("X/USD", _hourly(end=A1 + 2 * H), "1h", now=A1 + 1)        # 00:00:01: 23:00 bar closed
    assert before.anchor == A0 - DAY and before.bar_ts == A1 - 2 * H
    assert after.anchor == A0 and after.bar_ts == A1 - H


def test_replay_is_deterministic_and_never_looks_ahead():
    d = _hourly(n=150, seed=11)
    full = vw.replay("X/USD", d, "1h", bars=60, now=NOW)
    assert full == vw.replay("X/USD", d, "1h", bars=60, now=NOW)
    assert all(r["bar_status"] == "closed" and r["execution_authorized"] is False for r in full)
    # Cut the data 20 bars earlier: every event up to the cut must be identical.
    k = len(d.timestamps) - 20
    cut = OHLCV(*(list(getattr(d, f))[:k] for f in ("timestamps", "opens", "highs", "lows", "closes", "volumes")))
    cut_now = d.timestamps[k - 1] / 1000 + H + 1
    part = vw.replay("X/USD", cut, "1h", bars=60 - 20, now=cut_now)
    last = cut.timestamps[-1] / 1000
    assert part == [r for r in full if r["bar_open"] <= vw._iso(last)]


def _equity(end, missing_prev=False):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    day = datetime.fromtimestamp(end, et).date()
    ts = []
    for back in range(6, -1, -1):
        dd = day - timedelta(days=back)
        if dd.weekday() >= 5:
            continue
        o = datetime(dd.year, dd.month, dd.day, 9, 30, tzinfo=et).timestamp()
        ts += [o + i * 900 for i in range(26) if o + i * 900 < end]
    if missing_prev:
        prev_day = max(t for t in ts if datetime.fromtimestamp(t, et).date() < day)
        ts.remove(prev_day - 900 * 5)
    n = len(ts)
    closes = [100 + (i % 9) * 0.1 for i in range(n)]
    return OHLCV([int(t) for t in ts], closes, [x + 0.2 for x in closes], [x - 0.2 for x in closes], closes,
                 [1000.0] * n, market="us_equity")


EQ_NOW = 1_800_027_000        # Friday 2027-01-15 10:30 ET (checked below)


def test_equity_incomplete_or_stale_session_is_unknown():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    local = datetime.fromtimestamp(EQ_NOW, ZoneInfo("America/New_York"))
    assert local.weekday() < 5 and 10 <= local.hour < 16
    ok = vw.evaluate("SPY", _equity(EQ_NOW), "15m", now=EQ_NOW)
    assert ok.data_quality == "valid", ok.dq_reason
    bad = vw.evaluate("SPY", _equity(EQ_NOW, missing_prev=True), "15m", now=EQ_NOW)
    assert bad.data_quality == "unknown" and "missing" in bad.dq_reason
    later = EQ_NOW + 3 * 3600                                                  # 13:30 ET
    stale = vw.evaluate("SPY", _equity(later - 3600), "15m", now=later)     # last bar ended 12:30
    assert stale.data_quality == "unknown" and "stale" in stale.dq_reason
    none_today = vw.evaluate("SPY", _equity(EQ_NOW - 3600), "15m", now=EQ_NOW)
    assert none_today.data_quality == "unknown" and "no closed bar" in none_today.dq_reason


# ------------------------------------------------------------------ isolation
FORBIDDEN = ("live_execution", "paper_approval", "trade_manager", "circuit_breaker", "risk", "telegram_bot",
             "cli", "cli_equity", "journal", "entry_checklist", "no_trade_filter", "confidence_scoring")


def test_no_execution_or_risk_imports():
    src = pathlib.Path(vw.__file__).read_text()
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
    leaf = {n.rsplit(".", 1)[-1] for n in names}
    assert not leaf & set(FORBIDDEN), leaf & set(FORBIDDEN)
    probe = ("import sys, cdcx.volume_profile.vwap_watch as w; "
             "bad=[m for m in sys.modules if m.split('.')[-1] in %r and m.startswith('cdcx')]; print(bad)"
             % (("live_execution", "paper_approval", "trade_manager", "telegram_bot", "cli", "cli_equity"),))
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=300)   # generous: slow under load
    assert out.stdout.strip() == "[]", out.stdout + out.stderr


def test_watcher_does_not_touch_existing_watcher_files(tmp_path, monkeypatch):
    import os
    seen = []
    real_open = open

    def spy(path, *a, **k):
        seen.append(str(path))
        return real_open(path, *a, **k)
    monkeypatch.setattr("builtins.open", spy)
    j = vw.Journal(str(tmp_path / "journal.jsonl"))
    state = _state()
    vw.run_once(_snap(_res(BULL2), 0), state, j)
    vw.save_state(str(tmp_path / "state.json"), state)
    assert seen and all(os.path.dirname(p).startswith(str(tmp_path)) for p in seen)
    assert not any("xrp_vp_plan" in p or "xlm_vp_plan" in p or "cdcx_trades" in p for p in seen)


# ------------------------------------------------------------------ first run / baseline / catch-up
def test_first_valid_bar_is_a_baseline_and_later_transitions_still_fire():
    retest = _res(BULL2, bos=("retest_held", "bullish", 1.3013))
    st, out = _run([_snap(retest, 0), _snap(retest, 1), _snap(_res(BULL3S, htf="bullish"), 2)], start=None)
    assert out == [("SETUP", ["BASELINE"]), ("SETUP", []), ("CONFIRMATION_CANDIDATE", ["ENTRY_CONFIRMATION_CANDIDATE"])]
    first, evs = vw.step(None, _snap(retest, 0), "bullish")
    assert "ENTRY_SETUP" in evs[0].reason and "RETEST_HOLD" in evs[0].reason      # what was already there
    assert first.invalidation_level == 1.25                                      # the setup is fully tracked


def test_baseline_waits_for_the_first_valid_bar():
    _, out = _run([_snap(_res(BULL2), 0, dq="unknown", reason="stale"), _snap(_res(BULL2), 1)], start=None)
    assert out == [("IDLE", ["DATA_UNKNOWN"]), ("SETUP", ["BASELINE"])]          # not DATA_RESTORED + ENTRY


def test_baseline_is_never_notified(tmp_path):
    sent = []
    recs = vw.run_once(_snap(_res(BULL2), 0), {"directions": {}, "notify": {}},
                       vw.Journal(str(tmp_path / "j.jsonl")), notify_fn=sent.append)
    assert [r["event"] for r in recs] == ["BASELINE", "BASELINE"] and sent == []
    assert all(r["notify"] == "off" for r in recs)


def test_unreadable_state_file_is_moved_aside_and_noted(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json")
    state, problem = vw.load_state(str(p))
    assert state == {"directions": {}, "notify": {}} and "unreadable" in problem and not p.exists()
    assert list(tmp_path.glob("state.json.unreadable-*"))
    recs = vw.run_once(_snap(_res(), 0), state, vw.Journal(str(tmp_path / "j.jsonl")), note=problem)
    assert all(r["event"] == "BASELINE" and "unreadable" in r["reason"] for r in recs)
    assert vw.load_state(str(tmp_path / "missing.json")) == ({"directions": {}, "notify": {}}, None)


def test_unreadable_journal_lines_are_counted_not_rewritten(tmp_path):
    p = tmp_path / "j.jsonl"
    p.write_text('garbage\n{"key": "abc"}\n')
    j = vw.Journal(str(p))
    assert j.keys() == {"abc"} and j.bad_lines == 1
    vw.run_once(_snap(_res(BULL2), 0), _state(), j)
    assert p.read_text().startswith('garbage\n{"key": "abc"}\n')


def test_live_catch_up_then_rebaseline_on_a_long_gap(tmp_path):
    d = _hourly(n=200, seed=5)
    tss = [t / 1000 for t in d.timestamps]
    j = vw.Journal(str(tmp_path / "j.jsonl"))
    state = {"directions": {}, "notify": {}}
    early = vw._slice(d, None, len(tss) - 6)                       # the watcher last ran 5 bars ago
    vw.advance_live("X/USD", early, "1h", state, j, now=tss[-7] + H + 1)
    snap, caught, recs = vw.advance_live("X/USD", d, "1h", state, j, now=NOW)
    assert snap.bar_ts == tss[-2]
    assert all(r["catch_up"] and r["notify"].startswith("off") for r in caught)
    bars = {r["bar_open"] for r in caught}
    assert bars <= {vw._iso(t) for t in tss[-6:-2]}                 # only the 4 missed closed bars
    assert not any(r["event"] == "BASELINE" for r in recs)
    # a replay over the same bars produces the same events AND the same saved state
    ref_state = {"directions": {}, "notify": {}}
    ref = vw.replay("X/USD", d, "1h", bars=7, now=NOW, state=ref_state)
    strip = lambda rs: [(r["bar_open"], r["direction"], r["event"], r["reason"]) for r in rs]
    first_run = [r for r in ref if r["bar_open"] == vw._iso(tss[-7])]
    assert strip(caught + recs) == strip(ref[len(first_run):])
    assert state == ref_state
    # 59 missed bars > MAX_CATCH_UP_BARS -> re-baseline with the reason, nothing caught up
    state2 = {"directions": {}, "notify": {}}
    j2 = vw.Journal(str(tmp_path / "j2.jsonl"))
    vw.advance_live("X/USD", vw._slice(d, None, len(tss) - 61), "1h", state2, j2, now=tss[-62] + H + 1)
    _, caught2, recs2 = vw.advance_live("X/USD", d, "1h", state2, j2, now=NOW)
    assert caught2 == [] and [r["event"] for r in recs2] == ["BASELINE", "BASELINE"]
    assert "re-baselined" in recs2[0]["reason"] and "59 closed bars missed" in recs2[0]["reason"]


def test_equity_overnight_is_not_a_gap(tmp_path):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    thu_close = datetime(2027, 1, 14, 16, 0, 1, tzinfo=et).timestamp()
    data = _equity(EQ_NOW)
    j = vw.Journal(str(tmp_path / "j.jsonl"))
    state = {"directions": {}, "notify": {}}
    thu = vw._slice(data, None, sum(1 for t in data.timestamps if t + 900 <= thu_close))
    vw.advance_live("SPY", thu, "15m", state, j, now=thu_close)
    snap, caught, recs = vw.advance_live("SPY", data, "15m", state, j, now=EQ_NOW)
    assert snap.data_quality == "valid"
    assert not any(r["event"] == "BASELINE" for r in recs + caught)  # Thursday -> Friday: caught up, no reset
    assert all(r["catch_up"] for r in caught)


def _gap_run(tmp_path, missed):
    d = _hourly(n=200, seed=5)
    tss = [t / 1000 for t in d.timestamps]
    state = {"directions": {}, "notify": {}}
    j = vw.Journal(str(tmp_path / f"g{missed}.jsonl"))
    k = len(tss) - 3 - missed                           # last evaluated index; newest closed is -2, so
                                                        # exactly `missed` closed bars lie strictly between
    vw.advance_live("X/USD", vw._slice(d, None, k + 1), "1h", state, j, now=tss[k] + H + 1)
    return vw.advance_live("X/USD", d, "1h", state, j, now=NOW)


def test_catch_up_boundary_48_ok_49_rebaselines(tmp_path):
    _, caught, recs = _gap_run(tmp_path, 48)
    assert not any(r["event"] == "BASELINE" for r in recs)
    assert all(r["catch_up"] for r in caught)
    _, caught, recs = _gap_run(tmp_path, 49)
    assert caught == [] and "49 closed bars missed" in recs[0]["reason"] and recs[0]["event"] == "BASELINE"


def test_history_not_reaching_last_bar_rebaselines(tmp_path):
    d = _hourly(n=200, seed=5)
    tss = [t / 1000 for t in d.timestamps]
    state = {"directions": {}, "notify": {}}
    j = vw.Journal(str(tmp_path / "j.jsonl"))
    vw.advance_live("X/USD", vw._slice(d, None, 91), "1h", state, j, now=tss[90] + H + 1)
    _, caught, recs = vw.advance_live("X/USD", vw._slice(d, 100, None), "1h", state, j, now=NOW)
    assert caught == [] and "starts after the last evaluated bar" in recs[0]["reason"]


def test_rebaseline_reason_survives_until_a_valid_bar(tmp_path):
    d = _hourly(n=200, seed=5)
    tss = [t / 1000 for t in d.timestamps]
    state = {"directions": {}, "notify": {}}
    j = vw.Journal(str(tmp_path / "j.jsonl"))
    vw.advance_live("X/USD", vw._slice(d, None, 91), "1h", state, j, now=tss[90] + H + 1)
    _, _, recs = vw.advance_live("X/USD", vw._slice(d, 195, None), "1h", state, j, now=NOW)   # too short: UNKNOWN
    assert [r["event"] for r in recs] == ["DATA_UNKNOWN", "DATA_UNKNOWN"] and state["notes"]
    _, _, recs = vw.advance_live("X/USD", vw._slice(d, 100, None), "1h", state, j, now=NOW)   # valid again
    assert all(r["event"] == "BASELINE" and "starts after the last evaluated bar" in r["reason"] for r in recs)
    assert state["notes"] == {}


def test_lost_journal_cannot_resend_alerts(tmp_path):
    sent = []
    state = _state()
    j = vw.Journal(str(tmp_path / "j.jsonl"))
    vw.run_once(_snap(_res(BULL2), 0), state, j, notify_fn=sent.append)
    assert len(sent) == 1
    (tmp_path / "j.jsonl").write_text("corrupted\n")              # journal damaged; state intact
    again = vw.run_once(_snap(_res(BULL2), 0), state, vw.Journal(str(tmp_path / "j.jsonl")), notify_fn=sent.append)
    assert again == [] and len(sent) == 1                          # same bar: the state says already processed
    nxt = vw.run_once(_snap(_res({"vwap": "bullish"}), 1), state, vw.Journal(str(tmp_path / "j.jsonl")),
                      notify_fn=sent.append, min_interval_s=0)
    assert [r["event"] for r in nxt] == ["SETUP_DETERIORATION"] and len(sent) == 2


def test_unreadable_copies_are_never_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(vw.time, "time", lambda: 1_800_000_000)
    p = tmp_path / "state.json"
    for text in ("bad one", "bad two"):
        p.write_text(text)
        vw.load_state(str(p))
    copies = sorted(x.read_text() for x in tmp_path.glob("state.json.unreadable-*"))
    assert copies == ["bad one", "bad two"]
