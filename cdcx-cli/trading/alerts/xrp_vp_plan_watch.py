"""
Volume-Profile paper-trade plans per symbol -- BULLISH and BEARISH -> Telegram alerts
(send-only). XRP/USD (default): xrp-bull-vp / xrp-bear-vp. XLM/USD (--symbol XLM/USD):
xlm-bull-vp / xlm-bear-vp. Each symbol runs its own watcher process with its own
config/state/log/plan files ({prefix}_vp_plan_*). Shared across symbols: one paper
account (equity = starting balance + all realized P&L), one approval at a time, and
at most one open paper trade PER symbol, each sized at its config risk_pct (1% for XRP and
XLM since 2026-10-10; capped at 2%). Supersedes xrp_bull_plan_watch.py.

Each plan has 12 requirements, evaluated on CLOSED candles after every 1H close
(R1 confluence, R2 regime, R3 checklist, R4 ATR, R5 BOS, R6 reversal/breakdown,
R7 VWAP, R8 VP, R9 FVG, R10 POC rejection, R11 retest, R12 risk). Levels are
derived from fresh cdcx data when a plan is ARMED and stay fixed for its life,
so a retest or invalidation can't move mid-plan; re-arming recomputes them.

Alerts: progress (met set changed), PERMISSION NEEDED (12/12), INVALIDATED,
DATA UNAVAILABLE (3 failed checks in a row). The watcher NEVER trades.

    python trading/alerts/xrp_vp_plan_watch.py --arm        derive levels from fresh data, (re)arm both plans
    python trading/alerts/xrp_vp_plan_watch.py --once       print both plans + live preflight, send nothing
    python trading/alerts/xrp_vp_plan_watch.py              watch loop
    python trading/alerts/xrp_vp_plan_watch.py --approve xrp-bull-vp | xrp-bear-vp | xlm-bull-vp | xlm-bear-vp
    add --symbol XLM/USD to --arm / --once / the watch loop for XLM

--approve takes an exclusive lock (one approval at a time) and refuses unless:
the plan is armed, unexpired, not already approved;
no paper trade is open on any watched symbol; all 12 pass on fresh closed bars; a live preflight
on the exact data --execute will use is the TREND path in the plan's direction
(never the range path). It then runs cdcx's own _handle_execute in-process on
that data, PAPER only (never --live), sized on validated paper equity. One
execution per arming. Missing/failed data = UNKNOWN = no trade. Right before
executing it re-checks expiry, approval state and open trades from disk, and
refuses if a new 1H bar closed meanwhile or the approval took > 10 min.

Restart safety: every requirement (incl. the R11 retest and invalidation) is
recomputed from closed-bar history each check (>= 200 1H bars > a 7-day plan);
the derived retest state is also written to the state file for the record.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cdcx import engine, trade_manager, circuit_breaker
from cdcx.confluence import evaluate_confluence
from cdcx.entry_checklist import evaluate_entry_checklist
from cdcx.exchange.cryptocom import CryptoComExchange, OHLCV
from cdcx.indicators import market_structure, atr_ema_variant1
from cdcx import regime as regime_module, bos_state as bos_state_module, avp_rejection

HERE = Path(__file__).resolve().parent
# Watched symbols -> file/plan-id prefix and price decimals. Each symbol has its own config, state, log
# and plan text; XRP keeps its original file names and plan ids.
SYMBOLS = {"XRP/USD": {"prefix": "xrp", "dec": 4}, "XLM/USD": {"prefix": "xlm", "dec": 5}}
APPROVE_LOCK = HERE / "vp_plan_approve.lock"  # shared: one approval at a time across all symbols
MAX_APPROVAL_S = 600  # requirements older than this at execution time are stale
POLL_S = 300
TF_SECS = {"1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800}
GATE_TFS = ["1h", "4h", "1d", "1w"]
LIMIT = 200
DATA_FAIL_ALERT_AFTER = 3


def configure(symbol: str) -> None:
    """Point every per-symbol global at `symbol` (XRP/USD by default)."""
    global SYMBOL, BASE, DEC, PLANS, CONFIG, STATE, LOG, PLAN_TXT
    if symbol not in SYMBOLS:
        raise SystemExit(f"unsupported symbol {symbol} (use one of {', '.join(SYMBOLS)})")
    pre = SYMBOLS[symbol]["prefix"]
    SYMBOL, BASE, DEC = symbol, symbol.split("/")[0], SYMBOLS[symbol]["dec"]
    PLANS = {f"{pre}-bull-vp": "long", f"{pre}-bear-vp": "short"}
    CONFIG = HERE / f"{pre}_vp_plan_config.json"
    STATE = HERE / f"{pre}_vp_plan_state.json"
    LOG = HERE / f"{pre}_vp_plan_watch.log"
    PLAN_TXT = HERE / f"{pre}_vp_plan.txt"


def symbol_for_plan(pid: str) -> str | None:
    return next((s for s, v in SYMBOLS.items() if pid.startswith(v["prefix"] + "-")), None)


def open_symbol_trades() -> list:
    """Open paper trades on THIS symbol: one open position per symbol (XRP and XLM may each hold one)."""
    return [t for t in trade_manager.load_trades() if t.symbol == SYMBOL and t.status == "open"]


def risk_pct(cfg: dict) -> float:
    """Per-plan risk % of paper equity (config `risk_pct`; 2.0 = cdcx default if absent). Never above 2.0."""
    return min(float(cfg.get("risk_pct", 2.0)), 2.0)


configure("XRP/USD")


# --------------------------------------------------------------------------- helpers
def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z {msg}"
    with LOG.open("a") as f:
        f.write(line + "\n")
    print(line, flush=True)


def iso(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%MZ")


def closed(d: OHLCV, tf: str) -> OHLCV:
    """Drop the still-open last bar."""
    ts = [t / 1000 if t > 1e11 else t for t in d.timestamps]
    n = len(ts) - (1 if time.time() < ts[-1] + TF_SECS[tf] else 0)
    return OHLCV(d.timestamps[:n], d.opens[:n], d.highs[:n], d.lows[:n], d.closes[:n], d.volumes[:n], d.market)


def bar_close_time(d: OHLCV, i: int, tf: str) -> float:
    return d.timestamps[i] / 1000 + TF_SECS[tf]


def anchored_vwap(d1h: OHLCV, anchor: float) -> float:
    pv = vol = 0.0
    for t, o, h, l, c, v in zip(d1h.timestamps, d1h.opens, d1h.highs, d1h.lows, d1h.closes, d1h.volumes):
        if t / 1000 >= anchor:
            pv += (o + h + l + c) / 4 * v
            vol += v
    return pv / vol if vol else float("nan")


def load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {"plans": {}, "data_failures": 0}


def save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=2))


def plan_state(state: dict, pid: str) -> dict:
    return state["plans"].setdefault(pid, {"last_bar": None, "met": [], "fired": {}, "retest": ""})


def send(text: str) -> None:
    from cdcx.telegram_send import send_message
    send_message(text, pre=True, source="cdcx-ai", symbol=SYMBOL)


def paper_equity(cfg: dict) -> float:
    """Starting balance + every realized P&L on closed paper trades (all symbols: one shared paper account)."""
    realized = sum(t.realized_pnl for t in trade_manager.load_trades() if t.status == "closed")
    return round(cfg["starting_balance"] + realized, 2)


# --------------------------------------------------------------------------- data
def fetch(ex=None) -> dict:
    """Closed bars for every gate TF (+ a longer 1H history for VWAP/retest) and a cdcx signal per TF.
    Raises on any missing data -> the caller reports UNKNOWN, never a pass."""
    ex = ex or CryptoComExchange()
    data = {tf: closed(ex.fetch_ohlcv(SYMBOL, tf, LIMIT), tf) for tf in GATE_TFS}
    data["1h_long"] = closed(ex.fetch_ohlcv(SYMBOL, "1h", 400), "1h")
    for tf, d in data.items():
        if len(d.closes) < 50:
            raise RuntimeError(f"only {len(d.closes)} closed {tf} bars")
    newest_1h = data["1h"].timestamps[-1] / 1000
    if time.time() - newest_1h > 3 * 3600:
        raise RuntimeError(f"stale 1H data (newest closed bar opened {utc(newest_1h)})")
    sig = {tf: engine.analyze_ohlcv(SYMBOL, data[tf], timeframe=tf) for tf in GATE_TFS}
    return {"data": data, "sig": sig}


# --------------------------------------------------------------------------- arming
def derive_levels(fx: dict) -> dict:
    """From closed 4H bars: nearest confirmed swing high above / swing low below the last close.
    Bull reclaims the high, is invalidated below the low; bear is the mirror image."""
    d = fx["data"]["4h"]
    price = d.closes[-1]
    swings = market_structure.find_swings(d.highs, d.lows)
    highs = [s for s in swings if s.kind == "high" and s.price > price]
    lows = [s for s in swings if s.kind == "low" and s.price < price]
    if not highs or not lows:
        raise RuntimeError("no confirmed 4H swing high above / low below price to arm from")
    hi, lo = highs[-1], lows[-1]  # most recent
    anchor_idx = max(hi.index, lo.index)
    return {
        "swing_high": round(hi.price, DEC), "swing_high_utc": utc(d.timestamps[hi.index] / 1000),
        "swing_low": round(lo.price, DEC), "swing_low_utc": utc(d.timestamps[lo.index] / 1000),
        "vwap_anchor_utc": datetime.fromtimestamp(d.timestamps[anchor_idx] / 1000, timezone.utc)
                                   .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "price_at_arming": price,
    }


def arm(days: int = 7) -> dict:
    fx = fetch()
    lv = derive_levels(fx)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {"starting_balance": 1000.0}
    cfg.update({
        "symbol": SYMBOL,
        "armed_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_utc": (now + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "arming_id": now.strftime("%Y%m%d%H%M"),
        "levels": lv,
    })
    CONFIG.write_text(json.dumps(cfg, indent=2) + "\n")
    save_state({"plans": {}, "data_failures": 0})  # fresh arming: no approvals carried over
    log(f"armed {cfg['arming_id']}: swing high {lv['swing_high']} / low {lv['swing_low']}, "
        f"VWAP anchor {lv['vwap_anchor_utc']}, expires {cfg['expires_utc']}")
    return cfg


# --------------------------------------------------------------------------- requirements
def retest_state(d4: OHLCV, d1: OHLCV, lvl: float, margin: float, armed: float, side: str) -> tuple[bool, str]:
    """After the most recent 4H close through `lvl` (above for long, below for short) that closed after
    arming: HELD when a later closed 1H bar comes back to within `margin` of the level and closes on the
    breakout side; FAILED on a 1H close back through it by more than `margin` (needs a fresh break)."""
    up = side == "long"
    beyond = (lambda c: c > lvl) if up else (lambda c: c < lvl)
    brk = None
    for i in range(1, len(d4.closes)):
        if bar_close_time(d4, i, "4h") > armed and beyond(d4.closes[i]) and not beyond(d4.closes[i - 1]):
            brk = bar_close_time(d4, i, "4h")
    word = "reclaim" if up else "breakdown"
    if brk is None:
        return False, f"waiting for a 4H close {'above' if up else 'below'} {lvl} ({word})"
    after = [(l, h, c) for t, l, h, c in zip(d1.timestamps, d1.lows, d1.highs, d1.closes) if t / 1000 >= brk]
    if any((c < lvl - margin) if up else (c > lvl + margin) for _, _, c in after):
        return False, f"FAILED: 1H closed back {'below' if up else 'above'} {lvl - margin if up else lvl + margin:.{DEC}f} after the {word} at {utc(brk)}"
    if any((l <= lvl + margin and c > lvl) if up else (h >= lvl - margin and c < lvl) for l, h, c in after):
        return True, f"HELD: 1H tested {lvl} after the {word} at {utc(brk)} and closed {'above' if up else 'below'}"
    return False, (f"{word} at {utc(brk)}; waiting for a 1H {'dip to <=' if up else 'rally to >='} "
                   f"{lvl + margin if up else lvl - margin:.{DEC}f} that closes {'above' if up else 'below'} {lvl}")


def bear_poc_rejection(d: OHLCV, poc: float, lookback: int = 12) -> tuple[str, str]:
    """Mirror of cdcx's bullish AVP rejection for the short side, on the fixed-VP POC:
    CONFIRMED = a closed bar traded up to the POC but closed below it, and the next closed bar also
    closed below the POC (rejection held). PENDING = the rejection bar is the newest closed bar."""
    n = len(d.closes)
    for i in range(n - 1, max(0, n - lookback) - 1, -1):
        if d.highs[i] >= poc and d.closes[i] < poc:
            if i == n - 1:
                return "PENDING", f"rejected POC {poc:.{DEC}f} on the newest closed bar; waiting for the next to hold"
            if d.closes[i + 1] < poc:
                return "CONFIRMED", f"rejected POC {poc:.{DEC}f} at {utc(d.timestamps[i] / 1000)}, next bar held below"
    return "NONE", f"no closed bar rejected POC {poc:.{DEC}f} in the last {lookback}"


def evaluate(cfg: dict, side: str, fx: dict) -> dict:
    up = side == "long"
    data, sig = fx["data"], fx["sig"]
    lv = cfg["levels"]
    armed = iso(cfg["armed_utc"])
    d4, d1h = data["4h"], data["1h"]
    c4 = d4.closes[-1]
    want_sig = "up" if up else "down"
    reqs = []

    # R1 cdcx confluence (transitional TFs don't count -- same filter as --execute)
    tradeable = {tf: s.signal for tf, s in sig.items() if s.regime.regime != "transitional"}
    conf = evaluate_confluence(tradeable) if len(tradeable) >= 2 else None
    r1 = bool(conf and conf.should_execute and conf.direction == side)
    regimes = ", ".join(f"{tf.upper()} {sig[tf].regime.regime}" for tf in GATE_TFS)
    reqs.append(("R1", f"CONFLUENCE: cdcx {side.upper()} on 2+ of 1H/4H/1D/1W (non-transitional)", r1,
                 (conf.label if conf else f"only {len(tradeable)} tradeable TF(s)") + f" | {regimes}"))

    # R2 regime: entry TF trending (HTF-aligned) and 1H not ranging (range path excluded)
    entry_tf = conf.entry_timeframe if r1 else "1h"
    d = data[entry_tf]
    reg = regime_module.analyze(d.highs, d.lows, d.closes, d.volumes, higher_timeframes_aligned=r1)
    r2 = reg.regime == "trending" and sig["1h"].regime.regime != "ranging"
    reqs.append(("R2", f"REGIME: entry TF ({entry_tf.upper()}) trending, 1H not ranging", r2,
                 f"{entry_tf.upper()} {reg.regime}" + (f", 1H {sig['1h'].regime.regime}" if entry_tf != "1h" else "")))

    # R3 cdcx entry checklist for this direction
    atr_series = atr_ema_variant1.calculate_atr(d.highs, d.lows, d.closes)
    chk = evaluate_entry_checklist(sig[entry_tf], side, risk_pct=risk_pct(cfg), symbol=SYMBOL, atr_series=atr_series)
    failed = [it.name for it in getattr(chk, "items", []) if not getattr(it, "passed", True)
              and not getattr(it, "advisory", False)]
    reqs.append(("R3", "CHECKLIST: cdcx entry checklist passes", r2 and chk.all_passed,
                 "all passed" if chk.all_passed else "failing: " + (", ".join(failed[:4]) or "see cdcx")))

    # R4 ATR confirms
    atr_lbl = {tf: sig[tf].labels.get("atr_expansion", "n/a") for tf in GATE_TFS}
    r4 = atr_lbl[entry_tf] == "Expansion" or atr_lbl["4h"] == "Expansion"
    reqs.append(("R4", "ATR: expansion on the entry TF or 4H (confirms, never triggers)", r4,
                 ", ".join(f"{tf.upper()} {v}" for tf, v in atr_lbl.items())))

    # R5 BOS on 1H and 4H in the plan direction, not failed (swings precede the break -- cdcx rule)
    bos = {}
    for tf in ("1h", "4h"):
        dd = data[tf]
        st = market_structure.analyze(dd.highs, dd.lows, price=dd.closes[-1])
        bos[tf] = bos_state_module.classify_bos_state(st, dd.highs, dd.lows, dd.closes, dd.volumes)
    ok = lambda b: b.direction == want_sig and b.state in ("continuation", "retest_held")
    def bos_txt(tf, b):
        when = f" @ {utc(bar_close_time(data[tf], b.break_index, tf))}" if b.break_index is not None else ""
        return f"{tf.upper()} {b.direction or '-'} {b.state} {b.level_price or ''}{when}".strip()
    reqs.append(("R5", f"BOS: {'bullish' if up else 'bearish'} BOS on 1H AND 4H, continuation or retest held",
                 ok(bos["1h"]) and ok(bos["4h"]), " | ".join(bos_txt(tf, b) for tf, b in bos.items())))

    # R6 reversal (bull) / breakdown (bear) + invalidation, close-based, bars closed after arming
    trig, inval = (lv["swing_high"], lv["swing_low"]) if up else (lv["swing_low"], lv["swing_high"])
    since = [d4.closes[i] for i in range(len(d4.closes)) if bar_close_time(d4, i, "4h") > armed]
    invalidated = any((c < inval) if up else (c > inval) for c in since)
    through = (c4 > trig) if up else (c4 < trig)
    reqs.append(("R6", f"{'REVERSAL' if up else 'BREAKDOWN'}: 4H close {'>' if up else '<'} {trig}, "
                       f"no 4H close {'<' if up else '>'} {inval} since arming", through and not invalidated,
                 f"last closed 4H {c4:.{DEC}f} ({utc(bar_close_time(d4, len(d4.closes) - 1, '4h'))})"
                 + (" | INVALIDATED" if invalidated else "")))

    # R7 anchored VWAP
    vwap = anchored_vwap(data["1h_long"], iso(lv["vwap_anchor_utc"]))
    reqs.append(("R7", f"VWAP: 4H close {'above' if up else 'below'} anchored VWAP", (c4 > vwap) if up else (c4 < vwap),
                 f"VWAP {vwap:.{DEC}f} anchored {lv['vwap_anchor_utc']}"))

    # R8 Volume profile acceptance
    vp1 = (sig["1h"].vp_setup_type, sig["1h"].vp_setup_direction)
    if up:
        edge, r8_rule = sig["1d"].vah, "4H close >= 1D VAH (back above daily value)"
        r8 = vp1[1] == "up" and c4 >= edge
    else:
        edge, r8_rule = sig["4h"].val, "4H close < 4H VAL (rejected from value)"
        r8 = vp1[1] == "down" and c4 < edge
    s1d, s4 = sig["1d"], sig["4h"]
    reqs.append(("R8", f"VP: 1H {'bullish' if up else 'bearish'} VP setup AND {r8_rule}", r8,
                 f"1H {vp1[0]} {vp1[1] or '-'} | edge {edge:.{DEC}f} | "
                 f"4H POC {s4.poc:.{DEC}f} VAH {s4.vah:.{DEC}f} VAL {s4.val:.{DEC}f} HVN {s4.hvn:.{DEC}f} LVN {s4.lvn:.{DEC}f} | "
                 f"1D POC {s1d.poc:.{DEC}f} VAH {s1d.vah:.{DEC}f} VAL {s1d.val:.{DEC}f} (fixed VP, last {LIMIT} closed bars)"))

    # R9 FVG: 1H gap in direction; 4H not trapped against an active opposing gap
    f4 = s4.labels.get("fair_value_gap", "")
    if up:
        trapped = f4.startswith("Bearish") and s4.fvg_top is not None and c4 <= s4.fvg_top
    else:
        trapped = f4.startswith("Bullish") and s4.fvg_bottom is not None and c4 >= s4.fvg_bottom
    f1 = sig["1h"].labels.get("fair_value_gap", "")
    r9 = not trapped and f1.startswith("Bullish" if up else "Bearish")
    gap = lambda s: f"[{s.fvg_bottom:.{DEC}f}-{s.fvg_top:.{DEC}f}]" if s.fvg_top is not None else ""
    reqs.append(("R9", f"FVG: 1H {'bullish' if up else 'bearish'} FVG, 4H not {'below a bearish' if up else 'above a bullish'} FVG",
                 r9, f"1H {f1 or '-'} {gap(sig['1h'])} | 4H {f4 or '-'} {gap(s4)}"))

    # R10 POC bounce/rejection -- rejection evidence, not a touch
    if up:
        avp = avp_rejection.build_avp_by_tf(SYMBOL, {"1h": d1h, "4h": d4}, timeframes=["1h", "4h"])
        st10 = {tf: (a.state if a else "n/a", f"@ {a.level:.{DEC}f}" if a and a.level else "") for tf, a in avp.items()}
        rule10 = "1H or 4H anchored-VP POC/VAL bullish rejection CONFIRMED (cdcx AVP)"
    else:
        st10 = {tf: bear_poc_rejection(data[tf], sig[tf].poc) for tf in ("1h", "4h")}
        rule10 = "1H or 4H POC bearish rejection CONFIRMED (traded up to POC, closed below, next bar held)"
    r10 = any(s == "CONFIRMED" for s, _ in st10.values())
    reqs.append(("R10", f"POC {'BOUNCE' if up else 'REJECTION'}: {rule10}", r10,
                 " | ".join(f"{tf.upper()} {s} {x}".strip() for tf, (s, x) in st10.items())))

    # R11 retest of the R6 level
    margin = 0.25 * sig["1h"].atr
    r11, r11d = retest_state(d4, data["1h_long"], trig, margin, armed, side)
    reqs.append(("R11", f"RETEST: after the {'reclaim' if up else 'breakdown'} of {trig}, 1H retests within "
                        f"{margin:.{DEC}f} and closes {'above' if up else 'below'}; fail beyond the margin", r11, r11d))

    # R12 risk / position conflict
    cb = circuit_breaker.check_circuit_breaker_for_symbol(SYMBOL)
    open_any = open_symbol_trades()
    eq = paper_equity(cfg)
    r12 = not cb.tripped and not open_any and eq > 0
    reqs.append(("R12", f"RISK: circuit breaker clear, no open {BASE} paper trade, "
                        "paper equity valid", r12,
                 f"losses {cb.consecutive_losses}/3{' TRIPPED' if cb.tripped else ''} | equity ${eq:,.2f}"
                 + (f" | OPEN trade {open_any[0].id[:8]} {open_any[0].symbol} {open_any[0].direction}" if open_any else "")))

    # reference plan from cdcx's own levels on the entry TF
    lvls = sig[entry_tf].directional_levels.get(side, {})
    risk_usd = round(eq * risk_pct(cfg) / 100, 2)
    dist = abs(lvls.get("entry", 0) - lvls.get("stop", 0))
    plan = {"entry_tf": entry_tf, "atr": sig[entry_tf].atr, **lvls, "risk_usd": risk_usd,
            "size": round(risk_usd / dist, 2) if dist else None}
    # Illustration only: the same stop distance and TP R-multiples placed at the R6 trigger, where
    # this plan can actually fire. cdcx computes the real levels from the live price at approval.
    if dist:
        sgn = 1 if up else -1
        ratios = list(getattr(sig[entry_tf], "tp_ratios", None) or [2.2, 2.6, 3.2, 4.5])
        plan["at_trigger"] = {"entry": trig, "stop": trig - sgn * dist,
                              "take_profits": [trig + sgn * r * dist for r in ratios]}

    return {"side": side, "reqs": reqs, "all_met": all(r[2] for r in reqs), "invalidated": invalidated,
            "retest": r11d, "plan": plan, "bar_1h": d1h.timestamps[-1], "trigger": trig, "invalidation": inval}


# --------------------------------------------------------------------------- reporting
def header(fx: dict) -> str:
    data = fx["data"]
    stamps = " | ".join(f"{tf.upper()} {data[tf].closes[-1]:.{DEC}f} closed {utc(bar_close_time(data[tf], len(data[tf].closes) - 1, tf))}"
                        for tf in GATE_TFS)
    return f"Last completed candles: {stamps}"


def table(pid: str, cfg: dict, res: dict, state: dict) -> str:
    met = sum(r[2] for r in res["reqs"])
    ps = plan_state(state, pid)
    approved = ps["fired"].get("approved")
    p = res["plan"]
    tps = p.get("take_profits", {})
    lines = [f"{'🟢 BULLISH' if res['side'] == 'long' else '🔴 BEARISH'} {pid} (arming {cfg['arming_id']}) -- "
             f"{met}/12 met",
             f"Expires {cfg['expires_utc']} | approval: {'USED ' + utc(approved) if approved else 'not given'}"
             + (" | INVALIDATED" if res["invalidated"] else "")]
    for key, name, ok, detail in res["reqs"]:
        lines.append(f"{'PASS' if ok else 'FAIL'} {key} {name}\n       {detail}")
    if p.get("entry"):
        lines.append(f"Sizing preview at last {p['entry_tf'].upper()} close (NOT an order or entry level): "
                     f"price {p['entry']:.{DEC}f} ATR {p['atr']:.{DEC}f} stop {p['stop']:.{DEC}f} | TP1-4 "
                     + " / ".join(f"{v:.{DEC}f}" for v in tps.values())
                     + f" | risk ${p['risk_usd']} ({risk_pct(cfg):g}% equity) -> {p['size']} {BASE}")
        t = p.get("at_trigger")
        if t:
            lines.append(f"Same distances at the R6 trigger {t['entry']} (illustration): stop {t['stop']:.{DEC}f} | TP1-4 "
                         + " / ".join(f"{v:.{DEC}f}" for v in t["take_profits"]))
        lines.append("The plan can only fire after R6 + R11; the actual entry, stop and TPs are computed by cdcx "
                     "from the live price at approval.")
    return "\n".join(lines)


def unknown_table(pid: str, why: str) -> str:
    return f"{pid}: all 12 requirements UNKNOWN -- data unavailable ({why}). NO TRADE."


def next_to_watch(res: dict) -> str:
    first = next((r for r in res["reqs"] if not r[2]), None)
    return f"Next: {first[0]} {first[1]} -- {first[3]}" if first else "Next: all met"


# --------------------------------------------------------------------------- live preflight
def preflight(side: str):
    """Exactly what --execute will see: returns (ok, why, results)."""
    from cdcx import cli
    from cdcx.config import settings
    results = {tf: cli._run_single(SYMBOL, tf, settings.default_limit) for tf in GATE_TFS}
    if any(r is None for r in results.values()):
        return False, "live analysis failed for a timeframe (data unavailable)", results
    if cli._range_entry_timeframe(results) is not None:
        return False, "1H is RANGING on live data -> --execute would take the range path (direction not tied to this plan)", results
    tradeable = {tf: r.signal for tf, r in results.items() if r.regime.regime != "transitional"}
    conf = evaluate_confluence(tradeable) if len(tradeable) >= 2 else None
    if not (conf and conf.should_execute and conf.direction == side):
        return False, "live confluence is not executable " + side.upper() + ": " + (conf.label if conf else "fewer than 2 tradeable TFs"), results
    return True, f"live trend path {side.upper()} via {conf.entry_timeframe.upper()}", results


# --------------------------------------------------------------------------- modes
def once(cfg: dict) -> str:
    state = load_state()
    try:
        fx = fetch()
    except Exception as exc:
        return "\n\n".join(unknown_table(pid, str(exc)) for pid in PLANS)
    out = [f"{SYMBOL} VP PAPER-TRADE PLANS -- {utc(time.time())}", header(fx),
           f"Levels (armed {cfg['armed_utc']} from closed 4H swings): swing high {cfg['levels']['swing_high']} "
           f"({cfg['levels']['swing_high_utc']}), swing low {cfg['levels']['swing_low']} ({cfg['levels']['swing_low_utc']})"]
    for pid, side in PLANS.items():
        res = evaluate(cfg, side, fx)
        ok, why, _ = preflight(side)
        out.append(table(pid, cfg, res, state) + f"\nLive execution gate preflight: {'PASS' if ok else 'FAIL'} -- {why}")
    return "\n\n".join(out)


def watch(cfg: dict) -> None:
    log(f"watcher up, arming {cfg['arming_id']}")
    while time.time() < iso(cfg["expires_utc"]):
        state = load_state()
        try:
            fx = fetch()
            state["data_failures"] = 0
            state.pop("data_alerted", None)
        except Exception as exc:
            state["data_failures"] = state.get("data_failures", 0) + 1
            log(f"data failure {state['data_failures']}: {exc}")
            if state["data_failures"] >= DATA_FAIL_ALERT_AFTER and not state.get("data_alerted"):
                try:
                    send(f"⚠️ {SYMBOL} VP plans: DATA UNAVAILABLE ({state['data_failures']} checks in a row): {exc}\n"
                         "All requirements UNKNOWN -> NO TRADE, approvals refused until data returns.")
                    state["data_alerted"] = time.time()
                except Exception:
                    log("telegram send failed:\n" + traceback.format_exc())
            save_state(state)
            time.sleep(POLL_S)
            continue
        for pid, side in PLANS.items():
            try:
                res = evaluate(cfg, side, fx)
                ps = plan_state(state, pid)
                if res["bar_1h"] == ps["last_bar"]:
                    continue
                met = [r[0] for r in res["reqs"] if r[2]]
                log(f"{pid} 1H close: {len(met)}/12 met {met}")
                if res["invalidated"] and "invalidated" not in ps["fired"]:
                    send(f"⛔ {SYMBOL} {pid} INVALIDATED: a 4H bar closed "
                         f"{'below' if side == 'long' else 'above'} {res['invalidation']} after arming.\n"
                         "No trade. Re-arm (--arm) to get fresh levels.\n\n" + table(pid, cfg, res, state))
                    ps["fired"]["invalidated"] = time.time()
                elif res["all_met"] and "all_met" not in ps["fired"] and not ps["fired"].get("approved"):
                    p = res["plan"]
                    log(f"{pid} ALL 12 MET -- permission requested")
                    send(f"{'🟢 ' + SYMBOL + ' BULLISH' if side == 'long' else '🔴 ' + SYMBOL + ' BEARISH'} -- PERMISSION NEEDED\n"
                         f"Plan {pid} ({side.upper()}), 12/12 on closed candles. NO TRADE HAS BEEN SUBMITTED.\n"
                         f"Risk ${p['risk_usd']} ({risk_pct(cfg):g}% of validated paper equity). Entry, stop and TPs are computed by cdcx "
                         f"from the LIVE price at approval -- the levels below are previews, not orders.\n"
                         f"Invalidation: 4H close {'below' if side == 'long' else 'above'} {res['invalidation']} | "
                         f"expires {cfg['expires_utc']}\n"
                         f"Approve: tell Claude Code \"approve {pid}\", or run\n"
                         f"  python trading/alerts/xrp_vp_plan_watch.py --approve {pid}\n"
                         "Approval re-validates everything; paper only, never --live.\n\n"
                         + table(pid, cfg, res, state))
                    ps["fired"]["all_met"] = time.time()
                elif met != ps["met"]:
                    send(f"🟡 {SYMBOL} {pid} progress {len(ps['met'])}/12 -> {len(met)}/12 (no action needed)\n"
                         f"{next_to_watch(res)}\n\n" + table(pid, cfg, res, state))
                if not res["all_met"]:
                    ps["fired"].pop("all_met", None)
                ps["met"], ps["last_bar"], ps["retest"] = met, res["bar_1h"], res["retest"]
            except Exception:
                log(f"{pid} check failed:\n" + traceback.format_exc())
        save_state(state)
        time.sleep(POLL_S)
    log("watcher finished (plans expired)")


def approve(cfg: dict, pid: str) -> int:
    """One approval at a time (exclusive lock); see _approve_locked."""
    with APPROVE_LOCK.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"\nREFUSED {pid}: another approval is in progress -- nothing executed.")
            log(f"approve {pid} refused: another approval is in progress")
            return 1
        return _approve_locked(cfg, pid)


def _approve_locked(cfg: dict, pid: str) -> int:
    from cdcx import cli
    from cdcx.config import settings

    def refuse(why: str) -> int:
        print(f"\nREFUSED {pid}: {why} -- nothing executed.")
        log(f"approve {pid} refused: {why}")
        return 1

    started = time.time()

    if pid not in PLANS:
        return refuse(f"unknown plan id (use one of {', '.join(PLANS)})")
    side = PLANS[pid]
    state = load_state()
    ps = plan_state(state, pid)
    if "armed_utc" not in cfg:
        return refuse("plans are not armed (run --arm)")
    if time.time() >= iso(cfg["expires_utc"]):
        return refuse(f"plan expired at {cfg['expires_utc']} (re-arm with --arm)")
    if ps["fired"].get("approved"):
        return refuse(f"already approved at {utc(ps['fired']['approved'])} for arming {cfg['arming_id']} "
                      "(one execution per arming; re-arm with --arm)")
    other = [p for p in PLANS if p != pid and plan_state(state, p)["fired"].get("approved")]
    open_any = open_symbol_trades()
    if open_any:
        return refuse(f"{open_any[0].symbol} paper trade {open_any[0].id[:8]} ({open_any[0].direction}) is still open")
    try:
        fx = fetch()
    except Exception as exc:
        return refuse(f"data unavailable: {exc}")
    res = evaluate(cfg, side, fx)
    print(table(pid, cfg, res, state))
    if not res["all_met"]:
        return refuse("not all 12 requirements pass on fresh closed bars")
    ok, why, results = preflight(side)
    print(f"Live preflight: {why}")
    if not ok:
        return refuse(why)
    equity = paper_equity(cfg)
    if equity <= 0:
        return refuse(f"paper equity ${equity} is not valid")

    # Final re-checks immediately before execution (state re-read from disk, not the copy loaded above).
    now = time.time()
    if now >= iso(cfg["expires_utc"]):
        return refuse(f"plan expired at {cfg['expires_utc']} during approval")
    if now - started > MAX_APPROVAL_S:
        return refuse(f"approval took {now - started:.0f}s (> {MAX_APPROVAL_S}s) -- requirements are stale, re-run")
    if now >= res["bar_1h"] / 1000 + 2 * TF_SECS["1h"]:
        return refuse("a new 1H bar closed during approval -- requirements were checked on an old bar, re-run")
    state = load_state()
    ps = plan_state(state, pid)
    if ps["fired"].get("approved"):
        return refuse(f"already approved at {utc(ps['fired']['approved'])} (recorded during this approval)")
    open_any = open_symbol_trades()
    if open_any:
        return refuse(f"{open_any[0].symbol} paper trade {open_any[0].id[:8]} ({open_any[0].direction}) opened during approval")

    ps["fired"]["approved"] = now  # before executing: a crash can never cause a second execution
    save_state(state)
    log(f"approve {pid}: user approved -> cdcx _handle_execute (paper) on equity ${equity}, risk {risk_pct(cfg):g}%"
        + (f" (other plan {other[0]} was approved earlier, its trade is closed)" if other else ""))
    before = {t.id for t in trade_manager.load_trades()}
    os.chdir(HERE.parent.parent)  # cdcx-cli/, where cdcx-ai normally runs
    cli._handle_execute(SYMBOL, equity, risk_pct(cfg), results, settings.default_limit, live=False)

    new = [t for t in trade_manager.load_trades() if t.id not in before]
    if new and new[0].direction != side:
        msg = f"⚠️ {SYMBOL} {pid}: cdcx opened a {new[0].direction.upper()} paper trade {new[0].id[:8]} -- check it."
    elif new:
        t = new[0]
        ps["fired"]["executed"] = time.time()
        msg = (f"✅ {SYMBOL} {pid} approved -> {side.upper()} paper trade {t.id[:8]} opened @ {t.entry_price}, "
               f"stop {t.current_stop}, TP1 {t.tp_levels[0]}, size {t.position_size}, risk ${t.risk_amount}")
    else:
        msg = (f"⚪ {SYMBOL} {pid} approved, but cdcx --execute's own gates refused -- no trade opened. "
               "Plan spent for this arming; re-arm (--arm) to try again.")
    ps["fired"]["execution_result"] = msg
    save_state(state)
    send(msg)
    log(msg)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", action="store_true", help="derive fresh levels and (re)arm both plans")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--approve", metavar="PLAN_ID")
    ap.add_argument("--symbol", default=None, help=f"one of {', '.join(SYMBOLS)} (default XRP/USD; "
                                                   "--approve infers it from the plan id)")
    a = ap.parse_args()
    symbol = a.symbol or (symbol_for_plan(a.approve) if a.approve else None) or "XRP/USD"
    configure(symbol)
    if a.arm:
        cfg = arm(a.days)
        report = once(cfg)
        PLAN_TXT.write_text(report + "\n")
        print(report)
        return 0
    cfg = json.loads(CONFIG.read_text())
    if a.approve:
        return approve(cfg, a.approve)
    if a.once:
        print(once(cfg))
        return 0
    watch(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
