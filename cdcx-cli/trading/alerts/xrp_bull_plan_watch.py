"""
XRP/USD bullish paper-trade plan watcher -> Telegram alerts (send-only).

Checks the plan's requirements (xrp_bull_plan_config.json) on CLOSED bars
every time a new 1H bar closes, and alerts on Telegram when:
  * the set of met requirements changes (progress line),
  * ALL requirements are met -> asks for permission; nothing is executed,
  * the plan is invalidated (4H close below the higher low).

It never trades by itself. A paper trade is opened ONLY by an explicit
approval from the user:
    python trading/alerts/xrp_bull_plan_watch.py --approve
which refuses if the plan expired or was already approved, re-checks all 12
requirements on fresh closed bars, preflights the LIVE data --execute will use
(must be the trend path going LONG -- never the range path), then runs cdcx's
own --execute handler in-process on that same data (PAPER, never --live). Its
remaining gates (checklist, extended-move/no-trade filters, circuit breaker)
still decide. One execution per plan_id.

Restart safety: requirements, invalidation and the R11 retest are recomputed
from bar history every check (200 closed 1H bars > the 7-day plan), so a
restart can't skip a failed retest or a 4H close below the higher low.

Other modes:
    --once     evaluate and print the requirement table, send nothing
    (default)  watch loop, resumes from xrp_bull_plan_state.json
Never reads Telegram (cdcx.telegram_send is send-only).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from cdcx import engine, trade_manager, circuit_breaker
from cdcx.confluence import evaluate_confluence
from cdcx.entry_checklist import evaluate_entry_checklist
from cdcx.exchange.cryptocom import CryptoComExchange, OHLCV
from cdcx.indicators import market_structure, atr_ema_variant1
from cdcx import regime as regime_module, bos_state as bos_state_module, avp_rejection

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "xrp_bull_plan_config.json"
STATE = HERE / "xrp_bull_plan_state.json"
LOG = HERE / "xrp_bull_plan_watch.log"
POLL_S = 300
TF_SECS = {"1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800}
GATE_TFS = ["1h", "4h", "1d", "1w"]
LIMIT = 200


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z {msg}"
    with LOG.open("a") as f:
        f.write(line + "\n")
    print(line, flush=True)


def iso(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def closed(d: OHLCV, tf: str) -> OHLCV:
    """Drop the still-open last bar."""
    ts = [t / 1000 if t > 1e11 else t for t in d.timestamps]
    n = len(ts) - (1 if time.time() < ts[-1] + TF_SECS[tf] else 0)
    return OHLCV(d.timestamps[:n], d.opens[:n], d.highs[:n], d.lows[:n], d.closes[:n], d.volumes[:n], d.market)


def anchored_vwap(d1h: OHLCV, anchor: float) -> float:
    pv = vol = 0.0
    for t, o, h, l, c, v in zip(d1h.timestamps, d1h.opens, d1h.highs, d1h.lows, d1h.closes, d1h.volumes):
        if t / 1000 >= anchor:
            pv += (o + h + l + c) / 4 * v
            vol += v
    return pv / vol if vol else float("nan")


def retest_state(d4: OHLCV, d1: OHLCV, lvl: float, margin: float, armed: float) -> tuple[bool, str]:
    """(held?, detail) for a retest of `lvl` after the most recent 4H close back above it."""
    reclaim_close = None
    prev = None
    for t, c in zip(d4.timestamps, d4.closes):
        if t / 1000 + TF_SECS["4h"] > armed and c > lvl and prev is not None and prev <= lvl:
            reclaim_close = t / 1000 + TF_SECS["4h"]
        prev = c
    if reclaim_close is None:
        return False, f"waiting for a 4H close above {lvl} (reclaim)"
    after = [(l, c) for t, l, c in zip(d1.timestamps, d1.lows, d1.closes) if t / 1000 >= reclaim_close]
    if any(c < lvl - margin for _, c in after):
        return False, f"FAILED: a 1H close below {lvl - margin:.4f} after the reclaim"
    if any(l <= lvl + margin and c > lvl for l, c in after):
        return True, "HELD: a 1H bar tested the level and closed above it"
    return False, f"reclaimed; waiting for a 1H dip to <= {lvl + margin:.4f} that closes above {lvl}"


def evaluate(cfg: dict) -> dict:
    """Returns {"reqs": [(key, name, met, detail)], "all_met", "invalidated", "price", ...} on closed bars."""
    ex = CryptoComExchange()
    sym = cfg["symbol"]
    lv = cfg["levels"]
    data = {tf: closed(ex.fetch_ohlcv(sym, tf, LIMIT), tf) for tf in GATE_TFS}
    d1h_long = closed(ex.fetch_ohlcv(sym, "1h", 400), "1h")
    sig = {tf: engine.analyze_ohlcv(sym, data[tf], timeframe=tf) for tf in GATE_TFS}
    c4 = data["4h"].closes[-1]
    c1 = data["1h"].closes[-1]
    reqs = []

    # R1 cdcx confluence (same filter as --execute: transitional TFs don't count)
    tradeable = {tf: s.signal for tf, s in sig.items() if s.regime.regime != "transitional"}
    conf = evaluate_confluence(tradeable) if len(tradeable) >= 2 else None
    r1 = bool(conf and conf.should_execute and conf.direction == "long")
    regimes = ", ".join(f"{tf.upper()} {sig[tf].regime.regime}" for tf in GATE_TFS)
    reqs.append(("R1", "cdcx confluence LONG (2+ of 1H/4H/1D/1W, non-transitional)", r1,
                 (conf.label if conf else f"only {len(tradeable)} tradeable TF(s)") + f" | {regimes}"))

    # R2 entry-timeframe regime with HTF alignment, R3 entry checklist
    entry_tf = conf.entry_timeframe if r1 else "1h"
    d = data[entry_tf]
    reg = regime_module.analyze(d.highs, d.lows, d.closes, d.volumes, higher_timeframes_aligned=r1)
    r2 = reg.regime in ("trending", "ranging")
    reqs.append(("R2", f"Entry TF ({entry_tf.upper()}) regime trending/ranging", r2, reg.regime))
    if r2 and reg.regime == "trending":
        atr_series = atr_ema_variant1.calculate_atr(d.highs, d.lows, d.closes)
        chk = evaluate_entry_checklist(sig[entry_tf], "long", symbol=sym, atr_series=atr_series)
        r3, r3d = chk.all_passed, "all passed" if chk.all_passed else "not all passed"
    else:
        r3, r3d = (reg.regime == "ranging"), "ranging -> cdcx range path decides" if reg.regime == "ranging" else "needs a valid regime"
    reqs.append(("R3", "cdcx entry checklist", r3, r3d))

    # R4 ATR confirms (never triggers alone)
    atr_lbl = {tf: sig[tf].labels.get("atr_expansion", "n/a") for tf in GATE_TFS}
    r4 = atr_lbl[entry_tf] == "Expansion" or atr_lbl["4h"] == "Expansion"
    reqs.append(("R4", "ATR expansion on the entry TF or 4H", r4,
                 ", ".join(f"{tf.upper()} {v}" for tf, v in atr_lbl.items())))

    # R5 BOS: 1H and 4H bullish break that has not failed
    bos = {}
    for tf in ("1h", "4h"):
        dd = data[tf]
        st = market_structure.analyze(dd.highs, dd.lows, price=dd.closes[-1])
        bos[tf] = bos_state_module.classify_bos_state(st, dd.highs, dd.lows, dd.closes, dd.volumes)
    ok = lambda b: b.direction == "up" and b.state in ("continuation", "retest_held")
    r5 = ok(bos["1h"]) and ok(bos["4h"])
    reqs.append(("R5", "Bullish BOS on 1H AND 4H (continuation or retest held)", r5,
                 ", ".join(f"{tf.upper()} {b.direction or '-'} {b.state} {b.level_price or ''}".strip()
                           for tf, b in bos.items())))

    # R6 reversal: 4H close above the reclaim level, higher low intact
    armed = iso(cfg["armed_utc"])
    closes_since = [c for t, c in zip(data["4h"].timestamps, data["4h"].closes)
                    if t / 1000 + TF_SECS["4h"] > armed]  # every 4H bar that CLOSED after arming
    invalidated = any(c < lv["higher_low"] for c in closes_since)
    r6 = c4 > lv["reversal_reclaim"] and not invalidated
    reqs.append(("R6", f"REVERSAL: 4H close > {lv['reversal_reclaim']} and no 4H close < {lv['higher_low']}", r6,
                 f"last 4H close {c4:.4f}" + (" | INVALIDATED" if invalidated else "")))

    # R7 VWAP
    vwap = anchored_vwap(d1h_long, iso(lv["vwap_anchor_utc"]))
    r7 = c4 > vwap
    reqs.append(("R7", "VWAP: 4H close above anchored VWAP (Oct 8)", r7, f"VWAP {vwap:.4f}"))

    # R8 Volume profile: 1H bullish VP setup AND 4H close back above the 1D value-area high
    vp1 = (sig["1h"].vp_setup_type, sig["1h"].vp_setup_direction)
    r8 = vp1[1] == "up" and c4 >= sig["1d"].vah
    reqs.append(("R8", "VP: 1H bullish VP setup AND 4H close >= 1D VAH", r8,
                 f"1H {vp1[0]} {vp1[1] or '-'} | 1D VAH {sig['1d'].vah:.4f}"))

    # R9 FVG: 4H not trapped under an active bearish FVG, 1H FVG bullish
    s4 = sig["4h"]
    bear4 = s4.labels.get("fair_value_gap", "").startswith("Bearish") and s4.fvg_top is not None and c4 <= s4.fvg_top
    fvg1 = sig["1h"].labels.get("fair_value_gap", "")
    r9 = not bear4 and fvg1.startswith("Bullish")
    reqs.append(("R9", "FVG: 1H bullish FVG and 4H not below an active bearish FVG", r9,
                 f"1H {fvg1 or '-'} | 4H {s4.labels.get('fair_value_gap', '-')}"
                 + (f" top {s4.fvg_top:.4f}" if s4.fvg_top else "")))

    # R10 POC bounce: price rejected the 1H or 4H anchored-VP POC/VAL and held it
    avp = avp_rejection.build_avp_by_tf(sym, {"1h": data["1h"], "4h": data["4h"]}, timeframes=["1h", "4h"])
    avp_ok = [tf for tf, a in avp.items() if a is not None and a.state == "CONFIRMED"]
    reqs.append(("R10", "POC BOUNCE: 1H or 4H AVP POC/VAL rejection CONFIRMED", bool(avp_ok),
                 "AVP " + ", ".join(f"{tf.upper()} {a.state if a else 'n/a'}"
                                    + (f" @ {a.level:.4f}" if a and a.level else "") for tf, a in avp.items())))

    # R11 RETEST: after the R6 reclaim, a closed 1H bar dips back to the reclaim level
    # (within 0.25x 1H ATR) and closes above it; a 1H close below level - margin = failed.
    lvl = lv["reversal_reclaim"]
    margin = 0.25 * sig["1h"].atr
    rt_ok, rt_detail = retest_state(data["4h"], data["1h"], lvl, margin, armed)
    reqs.append(("R11", f"RETEST: after the reclaim, 1H dips to {lvl} (+-{margin:.4f}) and closes back above", rt_ok, rt_detail))

    # R12 risk: breaker clear, no open XRP paper trade
    cb = circuit_breaker.check_circuit_breaker_for_symbol(sym)
    open_xrp = [t for t in trade_manager.load_trades() if t.symbol == sym and t.status == "open"]
    risk_ok = not cb.tripped and not open_xrp
    reqs.append(("R12", "Circuit breaker clear, no open XRP paper trade", risk_ok,
                 f"losses {cb.consecutive_losses}/3" + (" TRIPPED" if cb.tripped else "")
                 + (f", open trade {open_xrp[0].id[:8]}" if open_xrp else "")))

    return {"reqs": reqs, "all_met": all(r[2] for r in reqs), "invalidated": invalidated,
            "price_1h": c1, "price_4h": c4, "bar_1h": data["1h"].timestamps[-1]}


def table(res: dict) -> str:
    met = sum(r[2] for r in res["reqs"])
    lines = [f"XRP/USD BULL PLAN -- {met}/{len(res['reqs'])} requirements met "
             f"(closed 1H {res['price_1h']:.4f}, 4H {res['price_4h']:.4f})"]
    for key, name, ok, detail in res["reqs"]:
        lines.append(f"{'✅' if ok else '❌'} {key} {name}\n     {detail}")
    return "\n".join(lines)


def send(text: str, pre: bool = False) -> None:
    from cdcx.telegram_send import send_message
    send_message(text, pre=pre, source="cdcx-ai", symbol="XRP/USD")


def load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {"last_bar": None, "met": [], "fired": {}}


def save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=2))


def watch(cfg: dict) -> None:
    state = load_state()
    log(f"watcher up, plan {cfg['plan_id']}")
    while time.time() < iso(cfg["expires_utc"]):
        try:
            res = evaluate(cfg)
            if res["bar_1h"] != state["last_bar"]:
                met = [r[0] for r in res["reqs"] if r[2]]
                log(f"1H close {res['price_1h']:.4f}: met {met}")
                if res["invalidated"] and "invalidated" not in state["fired"]:
                    send("🔴 XRP/USD bull plan INVALIDATED: a 4H bar closed below the "
                         f"{cfg['levels']['higher_low']} higher low.\nNo trade. Plan stays visible; "
                         "re-arm with new levels to resume.\n\n" + table(res))
                    state["fired"]["invalidated"] = time.time()
                elif res["all_met"] and "all_met" not in state["fired"]:
                    log("ALL REQUIREMENTS MET -- permission requested on Telegram")
                    send("🟢 XRP/USD BULL PLAN: ALL 12 REQUIREMENTS MET -- PERMISSION NEEDED\n"
                         "Nothing has been executed. To open the PAPER trade, approve it:\n"
                         "  • tell Claude Code \"approve the XRP bull plan\", or\n"
                         "  • run: python trading/alerts/xrp_bull_plan_watch.py --approve\n"
                         "Approval re-checks every requirement, then runs cdcx-ai --execute "
                         "(paper, never --live).\n\n" + table(res))
                    state["fired"]["all_met"] = time.time()
                elif met != state["met"]:
                    send("🟡 XRP/USD bull plan progress (no action needed)\n\n" + table(res))
                if not res["all_met"]:
                    state["fired"].pop("all_met", None)  # re-alert if it becomes all-met again later
                state["met"], state["last_bar"] = met, res["bar_1h"]
                save_state(state)
        except Exception:
            log("check failed:\n" + traceback.format_exc())
        time.sleep(POLL_S)
    log("watcher finished (plan expired)")


def approve(cfg: dict) -> int:
    """Explicit user approval. Refuses unless: the plan is unexpired and not already
    approved/executed, all 12 requirements pass on fresh closed bars, AND a live
    preflight on the very same `results` --execute will use shows the trend path
    going LONG (never the range path, whose direction isn't tied to this plan).
    Executes in-process with those results, so nothing can change in between."""
    from cdcx import cli
    from cdcx.config import settings

    state = load_state()
    def refuse(why: str) -> int:
        print(f"\nREFUSED: {why} -- nothing executed.")
        log(f"approve refused: {why}")
        return 1

    if time.time() >= iso(cfg["expires_utc"]):
        return refuse(f"plan {cfg['plan_id']} expired at {cfg['expires_utc']}")
    if state["fired"].get("approved"):
        return refuse(f"plan {cfg['plan_id']} was already approved at "
                      f"{datetime.fromtimestamp(state['fired']['approved'], timezone.utc):%Y-%m-%d %H:%MZ} "
                      "(one execution per plan; re-arm with a new plan_id)")

    res = evaluate(cfg)
    print(table(res))
    if not res["all_met"]:
        return refuse("not all 12 requirements are met on fresh closed bars")

    # Preflight on LIVE data, exactly what --execute will see.
    sym = cfg["symbol"]
    results = {tf: cli._run_single(sym, tf, settings.default_limit) for tf in GATE_TFS}
    if any(r is None for r in results.values()):
        return refuse("live analysis failed for a timeframe")
    if cli._range_entry_timeframe(results) is not None:
        return refuse("1H is RANGING on live data -> --execute would take the range path, "
                      "whose direction is not tied to this bullish plan")
    tradeable = {tf: r.signal for tf, r in results.items() if r.regime.regime != "transitional"}
    conf = evaluate_confluence(tradeable) if len(tradeable) >= 2 else None
    if not (conf and conf.should_execute and conf.direction == "long"):
        return refuse("live confluence is not LONG/executable: " + (conf.label if conf else "fewer than 2 tradeable TFs"))

    # Mark approved BEFORE executing: a crash mid-way can never lead to a second execution.
    state["fired"]["approved"] = time.time()
    save_state(state)
    log(f"approved by user -> cdcx --execute (paper) balance {cfg['balance']}")
    before = {t.id for t in trade_manager.load_trades()}
    import os
    os.chdir(HERE.parent.parent)  # cdcx-cli/, where cdcx-ai normally runs (journal etc. paths)
    cli._handle_execute(sym, cfg["balance"], None, results, settings.default_limit, live=False)

    new = [t for t in trade_manager.load_trades() if t.id not in before]
    if new and new[0].direction != "long":  # should be impossible after the preflight
        msg = f"⚠️ XRP/USD bull plan: cdcx opened a {new[0].direction.upper()} paper trade {new[0].id[:8]} -- check it."
    elif new:
        t = new[0]
        state["fired"]["executed"] = time.time()
        save_state(state)
        msg = (f"✅ XRP/USD bull plan approved -> LONG paper trade {t.id[:8]} opened @ {t.entry_price}, "
               f"stop {t.current_stop}, TP1 {t.tp_levels[0]}, size {t.position_size}, risk ${t.risk_amount}")
    else:
        msg = ("⚪ XRP/USD bull plan approved, but cdcx --execute's own gates refused -- no trade opened. "
               "The plan is spent; re-arm to try again.")
    send(msg)
    log(msg)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--approve", action="store_true")
    a = ap.parse_args()
    cfg = json.loads(CONFIG.read_text())
    if a.approve:
        return approve(cfg)
    if a.once:
        print(table(evaluate(cfg)))
        return 0
    watch(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
