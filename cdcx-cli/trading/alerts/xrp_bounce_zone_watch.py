"""
XRP/USD bearish bounce-zone rejection (5m/15m, 2026-10-14) -> Telegram alerts (send-only, alert-only).

The 1.3316-1.3385 resistance (broken 1H VAL .. bottom of the 1H bearish FVG) sits below the anchored
VWAP, so xrp_vwap_retest_watch.py can't see a rejection there. This is the user's discretionary
checklist -- NOT a cdcx gate (the bear VP plan is 5/12, every timeframe TRANSITIONAL / NO TRADE), so
every alert is paper/advisory and NOTHING is ever submitted.

Re-evaluated from closed candles on every poll (restart-safe):
  Z1 zone touch   a closed 5m candle after arming traded into the zone (high >= zone_low)
  Z2 rejection    the most recent such candle closed back below zone_low, bearish (close < open)
  Z3 15m break    a 15m candle that closed after the rejection closed below the rejection candle's low
  Z4 no reclaim   no 5m close above zone_high from the rejection candle on
Invalidated: a 15m close above invalidate_above (top of the 1H FVG) -> the zone failed; watcher stops.

Alerts: a heads-up on the first touch of each episode (a new episode starts after the zone has gone
untouched for REARM_S), a heads-up on each rejection candle, and CONDITIONS MET once per rejection when
Z1-Z4 pass and the confirming 15m candle closed at most FRESH_S ago (older setups are logged only).
Levels = the VWAP retest watcher's: entry = confirming 15m close, stop = entry + atr_mult x ATR(5m, 11),
TP1-4 at 2.2/2.6/3.2/4.5 R (25% each), breakeven = entry after TP1.

    python trading/alerts/xrp_bounce_zone_watch.py --once   print the checklist now, send nothing
    python trading/alerts/xrp_bounce_zone_watch.py          watch loop until expires_utc
"""
from __future__ import annotations

import argparse
import json
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from cdcx.exchange.cryptocom import CryptoComExchange
from cdcx.indicators import atr_ema_variant1
from xrp_intraday_range_watch import closed, iso, utc
from xrp_vwap_retest_watch import levels   # also registers 15m in TF_SECS

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "xrp_bounce_zone_config.json"
STATE = HERE / "xrp_bounce_zone_state.json"
LOG = HERE / "xrp_bounce_zone_watch.log"
SYMBOL = "XRP/USD"
POLL_S = 30
LOOKBACK_5M = 24          # how far back (2h) a rejection candle may be
FRESH_S = 900             # alert only if the confirming 15m close is at most one 15m bar old
REARM_S = 3600            # zone untouched this long -> the next touch is a new episode
DATA_FAIL_ALERT_AFTER = 3


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z {msg}"
    with LOG.open("a") as f:
        f.write(line + "\n")
    print(line, flush=True)


def send(text: str) -> None:
    from cdcx.telegram_send import send_message
    send_message(text, pre=True, source="cdcx-ai", symbol=SYMBOL)


def fetch(ex=None) -> dict:
    ex = ex or CryptoComExchange()
    d5 = closed(ex.fetch_ohlcv(SYMBOL, "5m", 300), "5m")
    d15 = closed(ex.fetch_ohlcv(SYMBOL, "15m", 60), "15m")
    if len(d5.closes) < 30 or len(d15.closes) < 10:
        raise RuntimeError(f"too few closed bars (5m {len(d5.closes)}, 15m {len(d15.closes)})")
    if time.time() - d5.timestamps[-1] / 1000 > 3 * 300:
        raise RuntimeError("stale 5m data")
    atr = atr_ema_variant1.calculate_atr(d5.highs, d5.lows, d5.closes)[-1]
    return {"d5": d5, "d15": d15, "atr5": atr}


def evaluate(cfg: dict, fx: dict) -> dict:
    d5, d15 = fx["d5"], fx["d15"]
    n5 = len(d5.closes)
    since = iso(cfg["armed_utc"])
    lo, hi = cfg["zone_low"], cfg["zone_high"]

    closes15 = [(d15.timestamps[i] / 1000 + 900, d15.closes[i]) for i in range(len(d15.closes))
                if d15.timestamps[i] / 1000 + 900 > since]
    invalid = next((f"15m close {c:.4f} above {cfg['invalidate_above']} ({utc(t)})"
                    for t, c in closes15 if c > cfg["invalidate_above"]), None)

    after = [i for i in range(n5) if d5.timestamps[i] / 1000 >= since]
    touches = [i for i in after if d5.highs[i] >= lo]
    rej = None
    for i in range(n5 - 1, max(n5 - 1 - LOOKBACK_5M, -1), -1):
        if d5.timestamps[i] / 1000 < since:
            break
        if d5.highs[i] >= lo and d5.closes[i] < lo and d5.closes[i] < d5.opens[i]:
            rej = i
            break
    c = {"Z1 zone touch": bool(touches), "Z2 rejection close below " + str(lo): rej is not None}
    entry = entry_t = None
    if rej is not None:
        rej_close_t = d5.timestamps[rej] / 1000 + 300
        brk = [(t, cl) for t, cl in closes15 if t > rej_close_t and cl < d5.lows[rej]]
        c["Z3 15m close below rejection low"] = bool(brk)
        c["Z4 no 5m close above " + str(hi)] = all(x <= hi for x in d5.closes[rej:])
        detail = (f"rejection 5m {utc(d5.timestamps[rej] / 1000)}: O {d5.opens[rej]:.4f} H {d5.highs[rej]:.4f} "
                  f"L {d5.lows[rej]:.4f} C {d5.closes[rej]:.4f}\n"
                  f"Structure: the rejection high {d5.highs[rej]:.4f} -- an ATR stop below it sits inside the "
                  f"tested zone")
        if brk:
            entry_t, entry = brk[0]
    else:
        c["Z3 15m close below rejection low"] = False
        c["Z4 no 5m close above " + str(hi)] = False
        detail = (f"last touch 5m {utc(d5.timestamps[touches[-1]] / 1000)} high {d5.highs[touches[-1]]:.4f}"
                  if touches else "no 5m candle has reached the zone yet")
    return {"checks": c, "all": all(c.values()) and not invalid, "invalid": invalid, "detail": detail,
            "entry": entry, "entry_t": entry_t,
            "fresh": entry_t is not None and time.time() - entry_t <= FRESH_S,
            "rej_t": d5.timestamps[rej] if rej is not None else None,
            "rej_high": d5.highs[rej] if rej is not None else None,
            "last_touch_t": d5.timestamps[touches[-1]] if touches else None}


def report(cfg: dict, fx: dict, ev: dict) -> str:
    lines = [f"XRP/USD bounce-zone rejection {cfg['zone_low']}-{cfg['zone_high']} (paper, alert-only) "
             f"-- expires {utc(iso(cfg['expires_utc']))}",
             f"last 5m close {fx['d5'].closes[-1]:.4f} | last 15m close {fx['d15'].closes[-1]:.4f}",
             ev["detail"]]
    lines += [f"[{'PASS' if ok else 'FAIL'}] {name}" for name, ok in ev["checks"].items()]
    lines.append(f"Invalidated: {ev['invalid']}" if ev["invalid"] else
                 f"Invalidation: 15m close > {cfg['invalidate_above']}")
    return "\n".join(lines)


def watch(cfg: dict) -> None:
    log("watcher up")
    while time.time() < iso(cfg["expires_utc"]):
        state = json.loads(STATE.read_text()) if STATE.exists() else {"fired": {}, "data_failures": 0}
        try:
            fx = fetch()
            state["data_failures"] = 0
        except Exception as exc:
            state["data_failures"] = state.get("data_failures", 0) + 1
            log(f"data failure {state['data_failures']}: {exc}")
            if state["data_failures"] == DATA_FAIL_ALERT_AFTER:
                try:
                    send(f"⚠️ XRP/USD bounce-zone watcher: DATA UNAVAILABLE ({exc}). Status UNKNOWN -> no signal.")
                except Exception:
                    log("telegram send failed:\n" + traceback.format_exc())
            STATE.write_text(json.dumps(state, indent=2))
            time.sleep(POLL_S)
            continue
        try:
            ev = evaluate(cfg, fx)
            fired = state.setdefault("fired", {})
            key5 = fx["d5"].timestamps[-1]
            if state.get("last_5m") != key5:
                log(f"close {fx['d5'].closes[-1]:.4f} high {fx['d5'].highs[-1]:.4f} "
                    + " ".join(f"{n.split()[0]}={'Y' if ok else 'n'}" for n, ok in ev["checks"].items())
                    + (f" INVALID: {ev['invalid']}" if ev["invalid"] else ""))
                state["last_5m"] = key5
            if ev["invalid"] and "invalid" not in fired:
                send("⛔ XRP/USD bounce-zone rejection INVALIDATED -- " + ev["invalid"] + ".\n"
                     "Buyers reclaimed the zone and the FVG: no bearish rejection (not a bullish call). "
                     "Watcher stops.\n\n" + report(cfg, fx, ev))
                fired["invalid"] = time.time()
                STATE.write_text(json.dumps(state, indent=2))
                log("watcher finished (invalidated)")
                return
            t = ev["last_touch_t"]
            if t is not None and t != fired.get("touch_t"):
                if fired.get("touch_t") is None or (t - fired["touch_t"]) / 1000 >= REARM_S:
                    send("👀 XRP/USD bounced INTO the 1.3316-1.3385 resistance zone -- heads-up only, "
                         "a touch is not a rejection.\n\n" + report(cfg, fx, ev))
                    fired["touch_alert_t"] = t
                fired["touch_t"] = t
            if ev["rej_t"] is not None and fired.get("rejection") != ev["rej_t"]:
                send("🟠 XRP/USD 5m REJECTION candle at the bounce zone (Z2) -- heads-up, waiting for a "
                     "15m close below its low.\n\n" + report(cfg, fx, ev))
                fired["rejection"] = ev["rej_t"]
            if ev["all"] and not ev["fresh"] and fired.get("stale") != ev["rej_t"]:
                log(f"conditions met but confirmed {utc(ev['entry_t'])} -- older than {FRESH_S}s, not alerted")
                fired["stale"] = ev["rej_t"]
            if ev["all"] and ev["fresh"] and fired.get("met") != ev["rej_t"]:
                send("🔴 XRP/USD BOUNCE-ZONE REJECTION -- CONDITIONS MET (paper, advisory).\n"
                     "NOTHING HAS BEEN SUBMITTED. Not a cdcx-qualified trade: the bear VP plan still needs a "
                     "4H close < 1.3176 and its regime/confluence gates.\n"
                     f"Stop uses {cfg['atr_mult']}x ATR (user-chosen; cdcx's protected default is 1.5x).\n\n"
                     + levels(cfg, ev["entry"], fx["atr5"], ev["rej_high"]) + "\n\n" + report(cfg, fx, ev))
                fired["met"] = ev["rej_t"]
                log(f"ALL MET entry {ev['entry']:.4f}")
            STATE.write_text(json.dumps(state, indent=2))
        except Exception:
            log("check failed:\n" + traceback.format_exc())
        time.sleep(POLL_S)
    log("watcher finished (expired)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    cfg = json.loads(CONFIG.read_text())
    if args.once:
        fx = fetch()
        ev = evaluate(cfg, fx)
        print(report(cfg, fx, ev))
        print()
        print(levels(cfg, ev["entry"] or fx["d5"].closes[-1], fx["atr5"], ev["rej_high"]))
        return 0
    watch(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
