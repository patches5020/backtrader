"""
vwap_watch.py
---------------
Closed-bar SHADOW watcher on top of vwap_confluence (approved 2026-10-18).
MONITOR ONLY: it reads market data, keeps its own state file and appends to
its own JSONL journal. It never imports or calls approval, order, plan or
risk-setting code, never touches the existing watchers or their state, and
every record says execution_authorized = false.

Everything is computed by code that already exists -- no second VWAP, BOS,
FVG or indicator implementation:
    levels   prev_day.prev_day_levels   (Variant A anchor, frozen previous-day
                                         profile, ohlc4 AVWAP +/- 1/2/3 sigma)
    evidence vwap_confluence.classify   (VP-01..05, four evidence families,
                                         QUALIFIED / CANDIDATE / CONFLICT / NONE)
    HTF      vwap_confluence.htf_direction (the 2-of-4 1H/4H/1D/1W filter
                                         --execute uses, transitional excluded),
             fed with CLOSED bars of each timeframe so a replay and a live run
             of the same bar agree
    context  vwap_confluence.context_from_closed (regime/ADX/DI/RSI/volume --
             recorded, never a condition; RQ5 found no evidence they add to VP-04)

No composite score. Each direction (bullish, bearish) of each symbol/timeframe
has its own state, evaluated once per CLOSED bar:

    IDLE                     nothing directional
    WATCH                    >= 1 family votes this way, or a setup is PENDING /
                             CONFIRMED / ACCEPTED / RETURNED this way -- and no
                             family votes the other way
    SETUP                    classifier CANDIDATE in this direction (>= 2
                             families agree, none oppose)
    CONFIRMATION_CANDIDATE   classifier QUALIFIED in this direction (>= 3 incl.
                             structure, none oppose, cdcx 2-of-4 HTF agrees).
                             Analysis state only -- never an authorization.
    INVALIDATED              from SETUP / CONFIRMATION_CANDIDATE: a close beyond
                             the opposite swing recorded when the setup formed,
                             or the structure family flips against it
    EXPIRED                  the anchor rolled over (new previous-day session)
                             while the state was WATCH or higher

First run (no saved state for a symbol/timeframe/direction): the first VALID bar
writes one BASELINE record with the state found and the conditions that already
existed (not alerted, never notified); later bars report transitions normally.
Missed bars (watcher not run) are caught up bar by bar, up to MAX_CATCH_UP_BARS,
journaled with catch_up = true and not notified; a longer gap re-baselines (the
BASELINE record says why). An unreadable state file is moved aside and
re-baselined, also with the reason; unreadable journal lines are counted.

INVALIDATED and EXPIRED last one bar; the next bar starts from IDLE. A state
moves up or down with the evidence (a weaker reading is a SETUP_DETERIORATION
or WATCH_CLEARED event, not an invalidation). Missing, stale or gapped data
freezes the state (no promotion, no demotion) and logs DATA_UNKNOWN once.

Events carry a kind so the three alert families stay apart:
    entry          ENTRY_WATCH, ENTRY_SETUP, ENTRY_CONFIRMATION_CANDIDATE
    retest         RETEST_HOLD / RETEST_FAILURE (BOS retest, VP-03 VWAP
                   pullback, VP-04 sweep) -- once per anchor and level
    deterioration  SETUP_DETERIORATION, WATCH_CLEARED, AVWAP_LOST,
                   STRUCTURAL_INVALIDATION -- about the SETUP, never a
                   position: no trade source is read (cdcx ledger not
                   consulted; TradingView Paper Trading positions never read)
    lifecycle      EXPIRED;  data  DATA_UNKNOWN / DATA_RESTORED

Every record is reproducible: the bar it came from, the anchor, versions, a
hash of the closed OHLCV window, and the levels/evidence it saw. A dedup key
(sha256 of symbol|tf|direction|event|anchor|bar-or-level|version) keeps a
re-run of the same bar from writing twice. Telegram is off unless --notify,
and then rate-limited per symbol/timeframe; a suppressed notification is
still journaled (with notify = "suppressed").

Delivery is at-least-once, never lost: order per run = notify -> journal ->
state (atomic replace). A crash after notifying but before the journal write
re-sends that bar's alert on the next run; a crash after the journal write is
absorbed by the journal's dedup keys. Not exactly-once.

Intrabar (forming-bar) warnings are NOT implemented here -- a separate,
provisional second step.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from .. import no_trade_gate
from ..config import settings
from . import vwap_confluence as vc
from .prev_day import PrevDayLevels, prev_day_levels

WATCH_VERSION = "vwap-watch-1"
ANCHOR_METHOD = ("prev-day Variant A: crypto = previous UTC day 00:00-24:00, equity = previous regular "
                 "session 09:30-16:00 ET; frozen profile; AVWAP from the session open")
CALC_METHOD = "anchored_vwap ohlc4, volume-weighted sigma, bands +/-1/2/3"
NOTIFY_MIN_INTERVAL_S = 3600
MAX_CATCH_UP_BARS = 48
HTF_TIMEFRAMES = ("1h", "4h", "1d", "1w")
NO_POSITION_NOTE = ("no position is read: cdcx ledger not consulted; TradingView Paper Trading positions "
                    "are never read -- deterioration events describe the setup, not a trade")

IDLE, WATCH, SETUP, CC = "IDLE", "WATCH", "SETUP", "CONFIRMATION_CANDIDATE"
INVALIDATED, EXPIRED = "INVALIDATED", "EXPIRED"
RANK = {IDLE: 0, INVALIDATED: 0, EXPIRED: 0, WATCH: 1, SETUP: 2, CC: 3}
DIRECTIONS = ("bullish", "bearish")
EARLY_SETUP_STATES = ("PENDING", "CONFIRMED", "ACCEPTED", "RETURNED")
ET = ZoneInfo("America/New_York")

HtfFn = Callable[[float], tuple[Optional[str], str]]


def _opp(d: str) -> str:
    return "bearish" if d == "bullish" else "bullish"


def _fmt(t: Optional[float]) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%m-%d %H:%MZ") if t is not None else "--"


def _iso(t: Optional[float]) -> Optional[str]:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if t is not None else None


def _slice(data, n_from: Optional[int], n_to: int):
    return replace(data, **{k: list(getattr(data, k))[n_from:n_to]
                            for k in ("timestamps", "opens", "highs", "lows", "closes", "volumes")})


# ---------------------------------------------------------------------------
# One closed bar -> a snapshot (read-only analysis)
# ---------------------------------------------------------------------------
@dataclass
class Snapshot:
    symbol: str
    timeframe: str
    market: str
    evaluated_at: float
    data_quality: str = "unknown"            # "valid" | "unknown"
    dq_reason: str = ""
    bar_ts: Optional[float] = None           # open time of the last CLOSED bar (unix s)
    bar_close_ts: Optional[float] = None
    close: Optional[float] = None
    window_hash: Optional[str] = None
    levels: Optional[PrevDayLevels] = None
    res: Optional[vc.VwapVpResult] = None
    ctx: Optional[vc.Context] = None
    htf: Optional[str] = None
    htf_label: str = "not evaluated"

    @property
    def anchor(self) -> Optional[float]:
        return self.levels.session_start if self.levels is not None and self.levels.status == "OK" else None


def _gap_reason(ts: list[float], tf_s: float, market: str, start: float) -> Optional[str]:
    """A missing bar inside the AVWAP window makes the window unreliable. Equity only checks within
    one ET trading day (overnight and weekends have no bars by design)."""
    window = [t for t in ts if t >= start]
    for a, b in zip(window, window[1:]):
        if market == no_trade_gate.MARKET_US_EQUITY:
            if datetime.fromtimestamp(a, ET).date() != datetime.fromtimestamp(b, ET).date():
                continue
        if b - a != tf_s:
            return f"gap in the bars since the anchor: {_fmt(a)} -> {_fmt(b)} (expected {tf_s / 60:g}m steps)"
    return None


def _equity_stale(ts_closed: list[float], tf_s: float, now: float) -> Optional[str]:
    """During regular hours an equity feed must be current; outside them it is legitimately quiet."""
    local = datetime.fromtimestamp(now, ET)
    if local.weekday() >= 5:
        return None
    open_t = local.replace(hour=9, minute=30, second=0, microsecond=0).timestamp()
    close_t = local.replace(hour=16, minute=0, second=0, microsecond=0).timestamp()
    if not (open_t + 2 * tf_s <= now < close_t):
        return None
    if not ts_closed or ts_closed[-1] < open_t:
        return "no closed bar from today's regular session yet"
    age = (now - (ts_closed[-1] + tf_s)) / tf_s
    if age > no_trade_gate.DEFAULT_MAX_DATA_STALENESS_BARS:
        return f"data is stale: last closed bar ended {age:.1f} bars ago during regular hours"
    return None


def evaluate(symbol: str, data, timeframe: str, now: Optional[float] = None,
             htf_fn: Optional[HtfFn] = None) -> Snapshot:
    """Analyse the latest CLOSED bar of `data` (any forming bar is dropped first). Never raises."""
    now = time.time() if now is None else now
    market = getattr(data, "market", no_trade_gate.MARKET_24X7)
    snap = Snapshot(symbol, timeframe, market, evaluated_at=now)
    try:
        tf_s = no_trade_gate.timeframe_to_seconds(timeframe)
        if not tf_s or tf_s >= 86400:
            snap.dq_reason = f"timeframe {timeframe!r} must be intraday"
            return snap
        ts = [no_trade_gate.timestamp_to_seconds(t) for t in data.timestamps]
        n = len(ts)
        while n and no_trade_gate.last_bar_is_forming(ts[:n], timeframe, now, market=market):
            n -= 1                                      # forming bar, and anything after `now` (replay)
        if n <= 0:
            snap.dq_reason = "no closed bars"
            return snap
        closed = _slice(data, None, n)
        snap.bar_ts, snap.bar_close_ts, snap.close = ts[n - 1], ts[n - 1] + tf_s, closed.closes[-1]

        section_n = int(2 * 86400 / tf_s) + 10          # same window the --vwap-vp section reads
        section = _slice(closed, -section_n, None)
        levels = prev_day_levels(section, timeframe, now=now)
        snap.levels = levels
        if htf_fn is not None:
            snap.htf, snap.htf_label = htf_fn(now)
        snap.res = vc.classify(levels, section, htf=snap.htf, htf_detail=snap.htf_label)
        snap.ctx = vc.context_from_closed(symbol, closed, timeframe, now=now)
        a = levels.avwap
        win = [i for i, t in enumerate(ts[:n]) if a is not None and t >= a.anchor_ts]
        snap.window_hash = hashlib.sha256(json.dumps(
            [[ts[i], closed.opens[i], closed.highs[i], closed.lows[i], closed.closes[i], closed.volumes[i]]
             for i in win]).encode()).hexdigest()[:16]

        if levels.status != "OK" or snap.res.status != "OK":
            snap.dq_reason = "; ".join(levels.reasons or snap.res.reasons or ["levels unavailable"])
            return snap
        reason = _gap_reason(ts[:n], tf_s, market, levels.session_start)
        if reason is None and market == no_trade_gate.MARKET_US_EQUITY:
            reason = _equity_stale(ts[:n], tf_s, now)
        if reason:
            snap.dq_reason = reason
            return snap
        snap.data_quality = "valid"
    except Exception as exc:     # monitor only: a failure is an UNKNOWN reading, never a pass
        snap.data_quality, snap.dq_reason = "unknown", f"evaluation failed ({exc})"
    return snap


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------
@dataclass
class DirState:
    state: str = IDLE
    anchor_ts: Optional[float] = None
    since_bar_ts: Optional[float] = None
    last_bar_ts: Optional[float] = None
    invalidation_level: Optional[float] = None    # opposite swing when the SETUP formed (None = unknown)
    on_thesis_side: Optional[bool] = None         # close vs AVWAP at the last evaluated bar
    data_quality: str = "valid"
    retests_seen: list = field(default_factory=list)   # retest key_parts already reported this anchor
    baselined: bool = False                             # False until the first VALID bar was recorded


@dataclass
class Event:
    event: str
    kind: str                     # entry / retest / deterioration / lifecycle / data
    direction: str
    state_from: str
    state_to: str
    reason: str
    key_part: str = ""            # what makes this event unique within its anchor (bar or level)
    evidence: list[str] = field(default_factory=list)
    opposing: list[str] = field(default_factory=list)


def evidence_for(res: vc.VwapVpResult, d: str) -> tuple[list[str], list[str], list[str]]:
    """(agreeing families, early setups this way, opposing families)."""
    agree = [k for k, v in res.families.items() if v == d]
    oppose = [k for k, v in res.families.items() if v == _opp(d)]
    early = [f"{s.code} {s.state}" for s in res.setups if s.direction == d and s.state in EARLY_SETUP_STATES]
    return agree, early, oppose


def target_state(res: vc.VwapVpResult, d: str) -> tuple[str, str]:
    agree, early, oppose = evidence_for(res, d)
    if res.qualification == "QUALIFIED" and res.qualification_direction == d:
        return CC, res.qualification_reason
    if res.qualification == "CANDIDATE" and res.qualification_direction == d:
        return SETUP, res.qualification_reason
    if not oppose and (agree or early):
        return WATCH, "early evidence: " + ", ".join(agree + early)
    if oppose:
        return IDLE, "opposing evidence: " + ", ".join(oppose)
    return IDLE, "no directional evidence"


def _retest_events(res: vc.VwapVpResult, d: str, st: str) -> list[Event]:
    out = []
    if res.bos_direction == d and res.bos_state in ("retest_held", "retest_failed"):
        held = res.bos_state == "retest_held"
        out.append(Event("RETEST_HOLD" if held else "RETEST_FAILURE", "retest", d, st, st,
                         f"BOS {res.bos_state} at {res.bos_level:.6g}", key_part=f"bos@{res.bos_level:.8g}"))
    by = {s.code: s for s in res.setups}
    vp3 = by.get("VP-03")
    if vp3 and vp3.direction == d and vp3.state in ("PENDING", "CONFIRMED"):
        out.append(Event("RETEST_HOLD", "retest", d, st, st, f"VP-03 {vp3.state}: {vp3.detail}",
                         key_part=f"vp03:{vp3.state}"))     # once per anchor per state (each new pullback bar is not news)
    vp4 = by.get("VP-04")
    if vp4 and vp4.direction == d and vp4.state == "FAILED":
        out.append(Event("RETEST_FAILURE", "retest", d, st, st, f"VP-04 {vp4.detail}", key_part=f"vp04:{vp4.detail}"))
    return out


def _bar_key(snap: Snapshot) -> str:
    return f"bar{int(snap.bar_ts)}" if snap.bar_ts is not None else "bar-none"


def step(prev: Optional[DirState], snap: Snapshot, d: str, note: str = "") -> tuple[DirState, list[Event]]:
    """Advance one direction's state by one evaluated bar. Pure: same inputs -> same outputs.
    Until a first VALID bar has been seen, that bar's events collapse into one BASELINE event."""
    was = prev is not None and prev.baselined
    st, events = _advance(prev, snap, d)
    if was or snap.data_quality != "valid":
        return st, events                               # (DATA_UNKNOWN still logged; baseline waits)
    st.baselined = True
    found = [e.event + (f" ({e.reason})" if e.kind == "retest" else "") for e in events if e.kind != "data"]
    reason = ((note + " -- ") if note else "") + f"initialized at {st.state}; already present (not alerted): " \
        + (", ".join(found) or "none")
    agree, early, oppose = evidence_for(snap.res, d)
    return st, [Event("BASELINE", "baseline", d, "-", st.state, reason, key_part=_bar_key(snap),
                      evidence=agree + early, opposing=oppose)]


def _advance(prev: Optional[DirState], snap: Snapshot, d: str) -> tuple[DirState, list[Event]]:
    st = replace(prev) if prev is not None else DirState()
    events: list[Event] = []

    if snap.data_quality != "valid":
        if st.data_quality == "valid":
            events.append(Event("DATA_UNKNOWN", "data", d, st.state, st.state,
                                f"{snap.dq_reason} -- state frozen, no confirmation possible",
                                key_part=_bar_key(snap)))
        st.data_quality = "unknown"
        return st, events
    if st.last_bar_ts is not None and snap.bar_ts <= st.last_bar_ts:
        return st, []                                   # bar already processed (re-run): nothing new
    if st.data_quality != "valid":
        events.append(Event("DATA_RESTORED", "data", d, st.state, st.state, "complete, fresh data again",
                            key_part=_bar_key(snap)))
        st.data_quality = "valid"

    res, lv = snap.res, snap.levels
    expired_now = False
    if st.anchor_ts is not None and st.anchor_ts != snap.anchor:
        expired_now = RANK[st.state] >= 1
        if expired_now:
            events.append(Event("EXPIRED", "lifecycle", d, st.state, EXPIRED,
                                f"anchor rolled over {_fmt(st.anchor_ts)} -> {_fmt(snap.anchor)}",
                                key_part=f"anchor{int(st.anchor_ts)}"))
        st = DirState(state=EXPIRED if RANK[st.state] >= 1 else IDLE, anchor_ts=snap.anchor,
                      since_bar_ts=snap.bar_ts, baselined=st.baselined)
    st.anchor_ts = snap.anchor
    base = st.state if RANK[st.state] >= 1 else IDLE
    bull = d == "bullish"
    on_side = (snap.close > lv.avwap.vwap) if bull else (snap.close < lv.avwap.vwap)
    agree, early, oppose = evidence_for(res, d)

    # Invalidation of a formed setup
    if RANK[base] >= 2:
        lvl = st.invalidation_level
        broke = lvl is not None and ((snap.close < lvl) if bull else (snap.close > lvl))
        flipped = res.families.get("structure") == _opp(d)
        if broke or flipped:
            why = (f"{snap.timeframe.upper()} close {snap.close:.6g} {'below' if bull else 'above'} {lvl:.6g} "
                   f"(opposite swing when the setup formed)") if broke else "structure family turned " + _opp(d)
            events.append(Event("STRUCTURAL_INVALIDATION", "deterioration", d, base, INVALIDATED, why,
                                key_part=_bar_key(snap), evidence=agree, opposing=oppose))
            return replace(st, state=INVALIDATED, since_bar_ts=snap.bar_ts, last_bar_ts=snap.bar_ts,
                           invalidation_level=None, on_thesis_side=on_side), events
        if st.on_thesis_side and not on_side:
            events.append(Event("AVWAP_LOST", "deterioration", d, base, base,
                                f"closed back {'below' if bull else 'above'} AVWAP {lv.avwap.vwap:.6g}",
                                key_part=_bar_key(snap), evidence=agree, opposing=oppose))

    target, why = target_state(res, d)
    if RANK[target] > RANK[base]:
        events.append(Event("ENTRY_" + target, "entry", d, base, target, why, key_part=_bar_key(snap),
                            evidence=agree + early, opposing=oppose))
        if RANK[base] < 2 <= RANK[target]:
            st.invalidation_level = res.swing_low if bull else res.swing_high
        st.state, st.since_bar_ts = target, snap.bar_ts
    elif RANK[target] < RANK[base]:
        name = "WATCH_CLEARED" if base == WATCH else "SETUP_DETERIORATION"
        events.append(Event(name, "deterioration", d, base, target, why, key_part=_bar_key(snap),
                            evidence=agree + early, opposing=oppose))
        st.state, st.since_bar_ts = target, snap.bar_ts
        if RANK[target] < 2:
            st.invalidation_level = None
    elif not expired_now:                               # EXPIRED stays visible for this one bar
        st.state = base
        if st.since_bar_ts is None:
            st.since_bar_ts = snap.bar_ts

    for ev in _retest_events(res, d, st.state):
        if ev.key_part not in st.retests_seen:          # once per anchor and level
            st.retests_seen = st.retests_seen + [ev.key_part]
            events.append(ev)
    st.last_bar_ts, st.on_thesis_side = snap.bar_ts, on_side
    return st, events


# ---------------------------------------------------------------------------
# Journal records
# ---------------------------------------------------------------------------
def dedup_key(snap: Snapshot, ev: Event) -> str:
    raw = "|".join(str(x) for x in (snap.symbol, snap.timeframe, ev.direction, ev.event,
                                    snap.anchor, ev.key_part, WATCH_VERSION))
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def inputs_of(snap: Snapshot) -> dict:
    lv, res, ctx = snap.levels, snap.res, snap.ctx
    a = lv.avwap if lv is not None else None
    return {
        "close": snap.close,
        "window_hash": snap.window_hash,
        "avwap": a.vwap if a else None,
        "sigma": a.sigma if a else None,
        "bands": {f"{k}": [lo, hi] for k, (lo, hi) in a.bands.items()} if a else None,
        "z": res.z if res else None,
        "prior_profile": ({"poc": lv.poc, "vah": lv.vah, "val": lv.val, "hvn": lv.hvn, "lvn": lv.lvn,
                           "session_start": _iso(lv.session_start), "session_end": _iso(lv.session_end)}
                          if lv is not None and lv.status == "OK" else None),
        "condition": res.condition if res else None,
        "setups": {s.code: [s.state, s.direction] for s in res.setups} if res else None,
        "families": res.families if res else None,
        "qualification": [res.qualification, res.qualification_direction] if res else None,
        "swing_high": res.swing_high if res else None,
        "swing_low": res.swing_low if res else None,
        "bos": [res.bos_state, res.bos_direction, res.bos_level] if res else None,
        "htf": [snap.htf, snap.htf_label],
        "context": asdict(ctx) if ctx is not None else None,
    }


def record(snap: Snapshot, ev: Event, notify: str, catch_up: bool = False) -> dict:
    return {
        "engine": "vwap_watch", "mode": "monitor_only", "version": WATCH_VERSION,
        "ruleset": vc.RULESET_VERSION, "anchor_method": ANCHOR_METHOD, "calc_method": CALC_METHOD,
        "key": dedup_key(snap, ev),
        "symbol": snap.symbol, "timeframe": snap.timeframe, "market": snap.market,
        "direction": ev.direction, "event": ev.event, "kind": ev.kind,
        "state_from": ev.state_from, "state_to": ev.state_to, "reason": ev.reason,
        "evidence": ev.evidence, "opposing": ev.opposing,
        "bar_status": "closed", "bar_open": _iso(snap.bar_ts), "bar_close": _iso(snap.bar_close_ts),
        "anchor": _iso(snap.anchor), "evaluated_at": _iso(snap.evaluated_at),
        "data_quality": snap.data_quality, "data_quality_reason": snap.dq_reason or None,
        "position": None, "position_note": NO_POSITION_NOTE,
        "inputs": inputs_of(snap),
        "notify": notify,
        "catch_up": catch_up,
        "execution_authorized": False,
    }


class Journal:
    """Append-only JSONL. Never rewrites a line; skips a record whose key is already present."""

    def __init__(self, path: str):
        self.path = path
        self._keys: Optional[set] = None
        self.bad_lines = 0

    def keys(self) -> set:
        if self._keys is None:
            self._keys = set()
            if os.path.exists(self.path):
                with open(self.path, encoding="utf-8") as fh:
                    for line in fh:
                        try:
                            self._keys.add(json.loads(line)["key"])
                        except (ValueError, KeyError, TypeError):
                            self.bad_lines += 1     # reported, never rewritten
        return self._keys

    def append(self, rec: dict) -> bool:
        if rec["key"] in self.keys():
            return False
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, sort_keys=True, default=str) + "\n")
        self._keys.add(rec["key"])
        return True


def load_state(path: str) -> tuple[dict, Optional[str]]:
    """(state, problem). Missing file -> empty state (first run). Unreadable file -> moved aside, empty
    state, and a problem string that goes into the BASELINE records -- never a silent reset."""
    empty = {"directions": {}, "notify": {}}
    if not os.path.exists(path):
        return empty, None
    try:
        with open(path, encoding="utf-8") as fh:
            st = json.load(fh)
        if not isinstance(st.get("directions"), dict) or not isinstance(st.get("notify"), dict):
            raise ValueError("unexpected layout")
        for raw in st["directions"].values():
            DirState(**raw)
        return st, None
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        stem, k = f"{path}.unreadable-{int(time.time())}", 0
        moved = stem
        while os.path.exists(moved):                    # never overwrite an earlier unreadable copy
            k += 1
            moved = f"{stem}-{k}"
        os.rename(path, moved)
        return empty, f"state file unreadable ({exc}), moved to {os.path.basename(moved)} -- re-baselined"



def save_state(path: str, state: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1, sort_keys=True)
    os.replace(tmp, path)


def run_once(snap: Snapshot, state: dict, journal: Optional[Journal], notify_fn=None,
             min_interval_s: float = NOTIFY_MIN_INTERVAL_S, note: str = "", catch_up: bool = False) -> list[dict]:
    """Advance both directions for one snapshot, journal new events, optionally notify. Returns the
    records written (or, with journal=None, the records that would be written)."""
    events: list[Event] = []
    pending = state.get("notes", {}).get(f"{snap.symbol}|{snap.timeframe}")
    note = note or pending or ""
    for d in DIRECTIONS:
        key = f"{snap.symbol}|{snap.timeframe}|{d}"
        raw = state["directions"].get(key)
        new, evs = step(DirState(**raw) if raw else None, snap, d, note=note)
        state["directions"][key] = asdict(new)
        events += evs
    if pending and all(state["directions"].get(f"{snap.symbol}|{snap.timeframe}|{d}", {}).get("baselined")
                       for d in DIRECTIONS):
        state["notes"].pop(f"{snap.symbol}|{snap.timeframe}")
    fresh = [e for e in events if journal is None or dedup_key(snap, e) not in journal.keys()]
    outcome = "off"
    alertable = [e for e in fresh if e.kind != "baseline"]
    if catch_up:
        outcome = "off (catch-up)"
    elif alertable and notify_fn is not None:
        nkey = f"{snap.symbol}|{snap.timeframe}"
        last = state["notify"].get(nkey)
        if last is not None and snap.evaluated_at - last < min_interval_s:
            outcome = f"suppressed (rate limit {min_interval_s / 60:g} min)"
        else:
            try:
                notify_fn(format_message(snap, alertable))
                outcome = "sent"
                state["notify"][nkey] = snap.evaluated_at
            except Exception as exc:
                outcome = f"failed ({exc})"
    recs = [record(snap, e, "off (baseline)" if e.kind == "baseline" and outcome != "off" else outcome, catch_up)
            for e in fresh]
    if journal is not None:
        recs = [r for r in recs if journal.append(r)]
    return recs


def advance_live(symbol: str, data, timeframe: str, state: dict, journal: Journal,
                 htf_fn: Optional[HtfFn] = None, now: Optional[float] = None, notify_fn=None,
                 note: str = "") -> tuple[Snapshot, list[dict], list[dict]]:
    """One live run: catch up any closed bars missed since the last evaluation (journaled, not notified),
    then evaluate the newest closed bar. Returns (snapshot, catch-up records, records)."""
    now = time.time() if now is None else now
    tf_s = no_trade_gate.timeframe_to_seconds(timeframe)
    snap = evaluate(symbol, data, timeframe, now=now, htf_fn=htf_fn)
    keys = [f"{symbol}|{timeframe}|{d}" for d in DIRECTIONS]
    last = [state["directions"][k].get("last_bar_ts") for k in keys if k in state["directions"]]
    last = max((x for x in last if x is not None), default=None)
    caught: list[dict] = []
    if last is not None and snap.bar_ts is not None and snap.bar_ts > last + tf_s:
        ts = [no_trade_gate.timestamp_to_seconds(t) for t in data.timestamps]
        # Count the data's own bars (an equity feed has no overnight bars -- that is not a gap). Holes
        # inside the missed span are caught by evaluate()'s gap check on each bar. Up to
        # MAX_CATCH_UP_BARS (48) missed bars are caught up in time order; 49+ re-baseline. "Reaches" =
        # the fetched series' first bar opens at or before the last evaluated bar.
        missed = [i for i, t in enumerate(ts) if last < t < snap.bar_ts]
        reaches = bool(ts) and ts[0] <= last
        if len(missed) > MAX_CATCH_UP_BARS or not reaches:
            for k in keys:
                state["directions"].pop(k, None)
            why = (f"{len(missed)} closed bars missed since {_fmt(last)} (> {MAX_CATCH_UP_BARS})" if reaches else
                   f"fetched history starts after the last evaluated bar {_fmt(last)}")
            why += " -- re-baselined, transitions in the gap not observed"
            note = f"{note}; {why}" if note else why
        else:
            for i in missed:
                s_i = evaluate(symbol, _slice(data, None, i + 1), timeframe, now=ts[i] + tf_s + 1, htf_fn=htf_fn)
                caught += run_once(s_i, state, journal, catch_up=True)
    if note:   # kept until the BASELINE is actually written (it waits for a VALID bar)
        state.setdefault("notes", {})[f"{symbol}|{timeframe}"] = note
    recs = run_once(snap, state, journal, notify_fn=notify_fn, note=note)
    return snap, caught, recs


# ---------------------------------------------------------------------------
# Replay (same code path, one closed bar at a time, nothing after `now` visible)
# ---------------------------------------------------------------------------
def replay(symbol: str, data, timeframe: str, bars: int, htf_fn: Optional[HtfFn] = None,
           journal: Optional[Journal] = None, now: Optional[float] = None,
           state: Optional[dict] = None, on_snapshot=None) -> list[dict]:
    """Evaluate the last `bars` CLOSED bars (as of `now`) one at a time from a fresh state.
    `on_snapshot(snap)`, if given, sees every evaluated snapshot (read-only; used by RQ6 eligibility)."""
    real_now = time.time() if now is None else now
    tf_s = no_trade_gate.timeframe_to_seconds(timeframe)
    ts = [no_trade_gate.timestamp_to_seconds(t) for t in data.timestamps]
    state = {"directions": {}, "notify": {}} if state is None else state
    out = []
    for i in range(max(0, len(ts) - bars), len(ts)):
        at = ts[i] + tf_s + 1                       # bar i has just closed; bar i+1 doesn't exist yet
        if at > real_now:
            break                                    # a forming bar is never replayed
        snap = evaluate(symbol, _slice(data, None, i + 1), timeframe, now=at, htf_fn=htf_fn)
        if on_snapshot is not None:
            on_snapshot(snap)
        out += run_once(snap, state, journal)
    return out


def htf_from_history(histories: dict, symbol: str) -> HtfFn:
    """cdcx's 2-of-4 HTF direction at time `now`, from already-fetched histories truncated to the bars
    CLOSED by then (engine.analyze_ohlcv per timeframe, then vwap_confluence.htf_direction)."""
    from .. import engine

    def at(now: float) -> tuple[Optional[str], str]:
        results = {}
        for tf, data in histories.items():
            tf_s = no_trade_gate.timeframe_to_seconds(tf)
            if data is None or not tf_s:
                continue
            ts = [no_trade_gate.timestamp_to_seconds(t) for t in data.timestamps]
            n = sum(1 for t in ts if t + tf_s <= now)
            if n < 30:
                continue
            try:
                results[tf] = engine.analyze_ohlcv(symbol, _slice(data, None, n), timeframe=tf)
            except Exception:
                continue
        htf, label = vc.htf_direction(results)
        return htf, f"{label} (closed bars)"
    return at


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def format_message(snap: Snapshot, events: list[Event]) -> str:
    head = f"VWAP WATCH (shadow) {snap.symbol} {snap.timeframe} -- bar {_fmt(snap.bar_ts)} closed"
    lines = [head] + [f"{e.direction} {e.event}: {e.state_from} -> {e.state_to} -- {e.reason}" for e in events]
    lines.append("Monitor only -- not a trade signal. Execution: NOT AUTHORIZED")
    return "\n".join(lines)


def format_section(snap: Snapshot, state: dict, recs: list[dict], caught: Optional[list] = None,
                   bad_lines: int = 0) -> str:
    bar = "-" * 81
    lines = [bar, f"VWAP WATCH -- {snap.symbol} {snap.timeframe} (shadow, monitor only, {WATCH_VERSION})".center(81),
             bar]
    lines.append(f"Last closed bar {_fmt(snap.bar_ts)} | anchor {_fmt(snap.anchor)} | data "
                 + (snap.data_quality.upper() if snap.data_quality == "valid" else f"UNKNOWN -- {snap.dq_reason}"))
    lines.append(f"cdcx HTF 2-of-4: {snap.htf or 'not evaluated'} -- {snap.htf_label}")
    for d in DIRECTIONS:
        raw = state["directions"].get(f"{snap.symbol}|{snap.timeframe}|{d}") or {}
        st = raw.get("state", IDLE)
        txt = f"  {d:<8} {st:<23}"
        if snap.res is not None and snap.res.status == "OK":
            agree, early, oppose = evidence_for(snap.res, d)
            txt += f" evidence: {', '.join(agree + early) or 'none'}"
            if oppose:
                txt += f" | opposing: {', '.join(oppose)}"
        if raw.get("since_bar_ts") and RANK.get(st, 0) >= 1:
            txt += f" | since {_fmt(raw['since_bar_ts'])}"
        if RANK.get(st, 0) >= 2:
            lvl = raw.get("invalidation_level")
            txt += f" | invalidates: close {'below' if d == 'bullish' else 'above'} " + (
                f"{lvl:.6g}" if lvl is not None else "level unknown") + " or structure flips"
        lines.append(txt)
    if caught:
        lines.append(f"Caught up {len(caught)} event(s) from missed bars (journaled, not notified)")
    if bad_lines:
        lines.append(f"Journal: {bad_lines} unreadable line(s) skipped for dedup (left in place)")
    lines.append("New events: " + ("none" if not recs else ""))
    for r in recs:
        lines.append(f"  [{r['kind']}] {r['direction']} {r['event']}: {r['state_from']} -> {r['state_to']} -- "
                     f"{r['reason']} (notify: {r['notify']})")
    lines += [f"Positions: {NO_POSITION_NOTE}", "Execution: NOT AUTHORIZED (monitor only)", bar]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI:  python -m cdcx.volume_profile.vwap_watch --symbol XRP/USD [--timeframe 1h]
# ---------------------------------------------------------------------------
def _default_dir() -> str:
    return os.path.join(settings.trading_journal_dir, "vwap_watch")


def _fetch(args, timeframe: str, limit: int):
    if args.equity:
        if args.source == "robinhood":
            from ..exchange.robinhood_equity import RobinhoodEquityExchange as Exchange
        else:
            from ..exchange.webull_equity import WebullEquityExchange as Exchange
        return Exchange().fetch_ohlcv(args.symbol, timeframe=timeframe, limit=limit)
    from ..exchange.cryptocom import CryptoComExchange
    ex = CryptoComExchange(settings.cryptocom_api_key, settings.cryptocom_api_secret)
    return ex.fetch_ohlcv(args.symbol, timeframe=timeframe, limit=limit)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m cdcx.volume_profile.vwap_watch",
                                description="Closed-bar AVWAP shadow watcher (monitor only, no execution).")
    p.add_argument("--symbol", required=True)
    p.add_argument("--timeframe", default="1h")
    p.add_argument("--equity", action="store_true", help="equity symbol (regular-hours bars)")
    p.add_argument("--source", default="robinhood", choices=("robinhood", "webull"))
    p.add_argument("--dir", default=None, help="journal/state directory (default <trading>/vwap_watch)")
    p.add_argument("--no-htf", action="store_true", help="skip the 2-of-4 HTF read (CONFIRMATION_CANDIDATE "
                                                         "then can't be reached)")
    p.add_argument("--notify", action="store_true", help="send new events via the send-only Telegram CLI, "
                                                         "rate-limited")
    p.add_argument("--replay", type=int, metavar="BARS", default=0,
                   help="replay the last BARS closed bars from a fresh state into <dir>/replay_*.jsonl")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    base = args.dir or _default_dir()
    tf_s = no_trade_gate.timeframe_to_seconds(args.timeframe)
    if not tf_s or tf_s >= 86400:
        print(f"VWAP WATCH: UNKNOWN (--timeframe must be intraday, got {args.timeframe!r})")
        return 2
    limit = max(int(2 * 86400 / tf_s) + 10, settings.default_limit) + max(args.replay, 0)
    try:
        data = _fetch(args, args.timeframe, limit)
    except Exception as exc:
        print(f"VWAP WATCH -- {args.symbol} {args.timeframe}: UNKNOWN (data unavailable: {exc})")
        return 1
    htf_fn = None
    if not args.no_htf:
        hist = {}
        for tf in HTF_TIMEFRAMES:
            try:
                hist[tf] = data if tf == args.timeframe else _fetch(args, tf, settings.default_limit + args.replay)
            except Exception:
                hist[tf] = None
        htf_fn = htf_from_history(hist, args.symbol)
    safe = args.symbol.replace("/", "-")

    if args.replay:
        path = os.path.join(base, f"replay_{safe}_{args.timeframe}.jsonl")
        if os.path.exists(path):
            os.remove(path)                            # a replay file is a fresh research artifact
        recs = replay(args.symbol, data, args.timeframe, args.replay, htf_fn=htf_fn, journal=Journal(path))
        print(f"VWAP WATCH replay -- {args.symbol} {args.timeframe}: {len(recs)} events over the last "
              f"{args.replay} closed bars -> {path}")
        for r in recs:
            print(f"  {r['bar_open']} {r['direction']:<8} [{r['kind']}] {r['event']}: {r['state_from']} -> "
                  f"{r['state_to']} -- {r['reason']}")
        print("Execution: NOT AUTHORIZED (monitor only)")
        return 0

    state_path = os.path.join(base, "state.json")
    state, problem = load_state(state_path)
    notify_fn = None
    if args.notify:
        from ..telegram_send import send_message
        notify_fn = lambda text: send_message(text, source="vwap_watch", symbol=args.symbol)  # noqa: E731
    journal = Journal(os.path.join(base, "journal.jsonl"))
    snap, caught, recs = advance_live(args.symbol, data, args.timeframe, state, journal, htf_fn=htf_fn,
                                      notify_fn=notify_fn, note=problem or "")
    save_state(state_path, state)
    print(format_section(snap, state, recs, caught=caught, bad_lines=journal.bad_lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
