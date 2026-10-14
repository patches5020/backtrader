"""
XRP/USD bearish anchored-VWAP retest (5m/15m, 2026-10-14) -> Telegram alerts (send-only, alert-only).

The user's discretionary 5m checklist from the 2026-10-14 analysis -- NOT a cdcx gate. cdcx itself
does not qualify this short (1H is RANGING with price near the range low), so every alert is
paper/advisory and NOTHING is ever submitted.

Re-evaluated from closed candles on every poll (restart-safe):
  C1 rejection   a closed 5m candle traded up to the anchored VWAP (high >= VWAP) and closed back
                 below min(VWAP, bos_5m)
  C2 lower high  that candle's high < the bounce high before it, and < fvg_bottom
  C3 15m break   a 15m candle that closed after the rejection closed below bos_15m
  C4 volume      rejection candle volume > SMA(17) of the 17 prior 5m volumes
  C5 no reclaim  no 5m close above fvg_bottom from the rejection candle on
Invalidated: any 15m close above invalidate_above, or two 15m closes in a row above fvg_bottom.

Levels when all 5 pass: entry = the confirming 15m close; stop = entry + atr_mult x ATR(5m, Wilder 11,
cdcx's own calculate_atr); TP1-4 = entry - 2.2/2.6/3.2/4.5 R (25% each); breakeven = entry after TP1.

    python trading/alerts/xrp_vwap_retest_watch.py --once   print the checklist now, send nothing
    python trading/alerts/xrp_vwap_retest_watch.py          watch loop until expires_utc
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
import xrp_intraday_range_watch as _irw
from xrp_intraday_range_watch import closed, iso, utc

_irw.TF_SECS.setdefault("15m", 900)

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "xrp_vwap_retest_config.json"
STATE = HERE / "xrp_vwap_retest_state.json"
LOG = HERE / "xrp_vwap_retest_watch.log"
SYMBOL = "XRP/USD"
POLL_S = 30
TP_R = (2.2, 2.6, 3.2, 4.5)
LOOKBACK_5M = 24          # how far back (2h) a rejection candle may be
DATA_FAIL_ALERT_AFTER = 3


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z {msg}"
    with LOG.open("a") as f:
        f.write(line + "\n")
    print(line, flush=True)


def send(text: str) -> None:
    from cdcx.telegram_send import send_message
    send_message(text, pre=True, source="cdcx-ai", symbol=SYMBOL)


def fetch(cfg: dict, ex=None) -> dict:
    ex = ex or CryptoComExchange()
    d5 = closed(ex.fetch_ohlcv(SYMBOL, "5m", 1000), "5m")
    d15 = closed(ex.fetch_ohlcv(SYMBOL, "15m", 60), "15m")
    if len(d5.closes) < 60 or len(d15.closes) < 10:
        raise RuntimeError(f"too few closed bars (5m {len(d5.closes)}, 15m {len(d15.closes)})")
    if time.time() - d5.timestamps[-1] / 1000 > 3 * 300:
        raise RuntimeError("stale 5m data")
    anchor = iso(cfg["vwap_anchor_utc"])
    pv = vol = 0.0
    first = d5.timestamps[0] / 1000
    if first > anchor:
        raise RuntimeError("5m history does not reach the VWAP anchor")
    for t, o, h, l, c, v in zip(d5.timestamps, d5.opens, d5.highs, d5.lows, d5.closes, d5.volumes):
        if t / 1000 >= anchor:
            pv += (o + h + l + c) / 4 * v
            vol += v
    atr = atr_ema_variant1.calculate_atr(d5.highs, d5.lows, d5.closes)[-1]
    return {"d5": d5, "d15": d15, "vwap": pv / vol, "atr5": atr}


def evaluate(cfg: dict, fx: dict) -> dict:
    d5, d15, vwap = fx["d5"], fx["d15"], fx["vwap"]
    n5 = len(d5.closes)
    since = iso(cfg["armed_utc"])
    fvg_bottom = cfg["fvg_bottom"]

    # invalidation: 15m closes after arming
    closes15 = [(d15.timestamps[i] / 1000 + 900, d15.closes[i]) for i in range(len(d15.closes))
                if d15.timestamps[i] / 1000 + 900 > since]
    invalid = None
    for k, (t, c) in enumerate(closes15):
        if c > cfg["invalidate_above"]:
            invalid = f"15m close {c:.4f} above {cfg['invalidate_above']} ({utc(t)})"
            break
        if k and c > fvg_bottom and closes15[k - 1][1] > fvg_bottom:
            invalid = f"two 15m closes in a row above {fvg_bottom} ({utc(t)})"
            break

    # C1: most recent rejection candle in the lookback, after arming
    rej = None
    for i in range(n5 - 1, max(n5 - 1 - LOOKBACK_5M, 17), -1):
        if d5.timestamps[i] / 1000 < since:
            break
        if d5.highs[i] >= vwap and d5.closes[i] < min(vwap, cfg["bos_5m"]):
            rej = i
            break
    c = {"C1 rejection at VWAP": rej is not None}
    if rej is not None:
        bounce_high = max(d5.highs[max(rej - 6, 0):rej]) if rej else 0.0
        sma = sum(d5.volumes[rej - 17:rej]) / 17
        rej_close_t = d5.timestamps[rej] / 1000 + 300
        c["C2 lower high"] = d5.highs[rej] < bounce_high and d5.highs[rej] < fvg_bottom
        brk = [(t, cl) for t, cl in closes15 if t > rej_close_t and cl < cfg["bos_15m"]]
        c["C3 15m close below " + str(cfg["bos_15m"])] = bool(brk)
        c["C4 rejection volume > SMA17"] = d5.volumes[rej] > sma
        c["C5 no 5m close above " + str(fvg_bottom)] = all(x <= fvg_bottom for x in d5.closes[rej:])
        detail = (f"rejection 5m {utc(d5.timestamps[rej] / 1000)}: high {d5.highs[rej]:.4f} close {d5.closes[rej]:.4f} "
                  f"vol {d5.volumes[rej]:,.0f} vs SMA17 {sma:,.0f}; bounce high {bounce_high:.4f}")
        entry = brk[0][1] if brk else None
        entry_t = brk[0][0] if brk else None
    else:
        for k in ("C2 lower high", "C3 15m close below " + str(cfg["bos_15m"]), "C4 rejection volume > SMA17",
                  "C5 no 5m close above " + str(fvg_bottom)):
            c[k] = False
        detail, entry, entry_t = "no 5m rejection candle at VWAP yet", None, None
    return {"checks": c, "all": all(c.values()) and not invalid, "invalid": invalid, "detail": detail,
            "entry": entry, "entry_t": entry_t, "rej_t": d5.timestamps[rej] if rej is not None else None}


def levels(cfg: dict, entry: float, atr: float) -> str:
    r = cfg["atr_mult"] * atr
    rows = [f"Entry (15m close)  {entry:.4f}",
            f"ATR(5m, 11)        {atr:.6f}   x {cfg['atr_mult']} = R {r:.4f}",
            f"Stop loss          {entry + r:.4f}   (+1R)"]
    for k, m in enumerate(TP_R, 1):
        rows.append(f"TP{k} ({m}R, 25%)    {entry - m * r:.4f}")
    rows.append(f"Breakeven          {entry:.4f}   (stop moves here once TP1 fills)")
    eq = cfg["paper_equity"]
    qty_cap = eq / entry
    rows.append(f"Size @ equity cap  {qty_cap:,.0f} XRP (~${eq:,.0f} notional) -> risk ${qty_cap * r:.2f} "
                f"({qty_cap * r / eq * 100:.2f}%)")
    return "\n".join(rows)


def report(cfg: dict, fx: dict, ev: dict) -> str:
    lines = [f"XRP/USD bearish VWAP retest (paper, alert-only) -- expires {utc(iso(cfg['expires_utc']))}",
             f"Anchored VWAP {fx['vwap']:.4f} | last 5m close {fx['d5'].closes[-1]:.4f} | "
             f"last 15m close {fx['d15'].closes[-1]:.4f}",
             ev["detail"]]
    lines += [f"[{'PASS' if ok else 'FAIL'}] {name}" for name, ok in ev["checks"].items()]
    lines.append(f"Invalidated: {ev['invalid']}" if ev["invalid"] else
                 f"Invalidation: 15m close > {cfg['invalidate_above']} or two 15m closes > {cfg['fvg_bottom']}")
    return "\n".join(lines)


def watch(cfg: dict) -> None:
    log("watcher up")
    while time.time() < iso(cfg["expires_utc"]):
        state = json.loads(STATE.read_text()) if STATE.exists() else {"fired": {}, "data_failures": 0}
        try:
            fx = fetch(cfg)
            state["data_failures"] = 0
        except Exception as exc:
            state["data_failures"] = state.get("data_failures", 0) + 1
            log(f"data failure {state['data_failures']}: {exc}")
            if state["data_failures"] == DATA_FAIL_ALERT_AFTER:
                try:
                    send(f"⚠️ XRP/USD VWAP retest watcher: DATA UNAVAILABLE ({exc}). Status UNKNOWN -> no signal.")
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
                log(f"vwap {fx['vwap']:.4f} close {fx['d5'].closes[-1]:.4f} "
                    + " ".join(f"{n.split()[0]}={'Y' if ok else 'n'}" for n, ok in ev["checks"].items())
                    + (f" INVALID: {ev['invalid']}" if ev["invalid"] else ""))
                state["last_5m"] = key5
            if ev["invalid"] and "invalid" not in fired:
                send("⛔ XRP/USD bearish VWAP retest INVALIDATED -- " + ev["invalid"] + ".\n"
                     "VWAP reclaimed: no bearish retest (not a bullish call). Watcher stops.\n\n" + report(cfg, fx, ev))
                fired["invalid"] = time.time()
                STATE.write_text(json.dumps(state, indent=2))
                log("watcher finished (invalidated)")
                return
            if ev["checks"]["C1 rejection at VWAP"] and fired.get("rejection") != ev["rej_t"]:
                send("👀 XRP/USD 5m REJECTION at anchored VWAP (C1) -- heads-up only, not the trigger.\n\n"
                     + report(cfg, fx, ev))
                fired["rejection"] = ev["rej_t"]
            if ev["all"] and "met" not in fired:
                send("🔴 XRP/USD BEARISH VWAP RETEST -- ALL 5 CONDITIONS MET (paper, advisory).\n"
                     "NOTHING HAS BEEN SUBMITTED. Not a cdcx-qualified trade: 1H is ranging near its low and TP1 "
                     "sits below the 1H range low (1.3508) -- it needs a range breakdown.\n"
                     f"Stop uses {cfg['atr_mult']}x ATR (user-chosen; cdcx's protected default is 1.5x).\n\n"
                     + levels(cfg, ev["entry"], fx["atr5"]) + "\n\n" + report(cfg, fx, ev))
                fired["met"] = time.time()
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
        fx = fetch(cfg)
        ev = evaluate(cfg, fx)
        print(report(cfg, fx, ev))
        print()
        print(levels(cfg, ev["entry"] or fx["d5"].closes[-1], fx["atr5"]))
        return 0
    watch(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
