"""
XRP/USD BOS trigger-map watcher -> Telegram alerts (send-only).

The trigger map lives in xrp_bos_watch_config.json next to this file, so it can
be re-armed by editing levels, not code. cdcx's BOS rule on CLOSED bars: a close
beyond the swing by 0.25x ATR (the config levels already include the margin).
Each alert fires once. Also alerts on:
  * retests (cdcx-style): HELD when a later bar dips into the retest zone and
    closes back on the right side of the level; FAILED only on a close beyond
    the level by the 0.25x ATR margin (`fail_level`), not on a marginal dip;
  * the open paper trade touching its stop or TP1.

Informational only: it never trades, never opens/closes/edits a paper trade,
and never reads Telegram (sends through cdcx.telegram_send, which refuses
getUpdates). Run:  python trading/alerts/xrp_bos_trigger_watch.py
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from cdcx.exchange.cryptocom import CryptoComExchange
from cdcx.indicators.candlestick_patterns import detect_patterns
from cdcx.telegram_send import send_message

SYMBOL = "XRP/USD"
HERE = Path(__file__).resolve().parent
CONFIG = HERE / "xrp_bos_watch_config.json"
STATE = HERE / "xrp_bos_watch_state.json"
LOG = HERE / "xrp_bos_watch.log"
POLL_S = 60
RUN_FOR_S = 7 * 24 * 3600
TF_SECS = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}


def load_config() -> dict:
    return json.loads(CONFIG.read_text())


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z {msg}"
    with LOG.open("a") as f:
        f.write(line + "\n")
    print(line, flush=True)


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {"fired": {}, "last_bar": {}, "started": time.time()}


def save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=1))


def pnl(trade: dict, price: float) -> str:
    one_r = trade["entry"] - trade["stop"]
    usd = (price - trade["entry"]) * trade["qty"]
    return (f"trade 5a75fd5f at {price:.4f}: {'+' if usd >= 0 else '-'}${abs(usd):.2f} "
            f"({(price - trade['entry']) / one_r:+.2f}R)")


def utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%m-%d %H:%M")


def closed_bars(ex: CryptoComExchange, tf: str):
    d = ex.fetch_ohlcv(SYMBOL, tf, 60)
    ts = [t / 1000 if t > 1e11 else t for t in d.timestamps]
    n = len(ts) - (1 if time.time() < ts[-1] + TF_SECS[tf] else 0)
    return ts[:n], d.opens[:n], d.highs[:n], d.lows[:n], d.closes[:n], d.volumes[:n], d


def alert(state: dict, key: str, text: str) -> None:
    send_message(text, source="cdcx-telegram", symbol=SYMBOL)  # raises on failure -> retried next poll
    state["fired"][key] = time.time()
    save_state(state)
    log(f"ALERT {key}: {text.splitlines()[0]}")


def check(ex: CryptoComExchange, state: dict, cfg: dict) -> None:
    trade = cfg["trade"]
    for tf in TF_SECS:
        ts, o, h, l, c, v, _ = closed_bars(ex, tf)
        last = ts[-1]
        if state["last_bar"].get(tf) is None:  # first run: only bars that close after arming count
            state["last_bar"][tf] = last
            save_state(state)
            continue
        new = [i for i, t in enumerate(ts) if t > state["last_bar"][tf]]
        for i in new:
            window = v[max(0, i - 20):i]
            avg = sum(window) / max(1, len(window))
            vol_ok = v[i] >= avg
            pats = ", ".join(f"{p.name} ({p.direction})"
                             for p in detect_patterns(h[:i + 1], l[:i + 1], o[:i + 1], c[:i + 1])) or "none"
            bar = (f"{tf.upper()} bar {utc(ts[i])}Z  O {o[i]:.4f} H {h[i]:.4f} L {l[i]:.4f} C {c[i]:.4f}\n"
                   f"Volume {v[i]:,.0f} vs 20-bar avg {avg:,.0f} -> {'VOLUME-CONFIRMED' if vol_ok else 'NOT volume-confirmed'}\n"
                   f"cdcx candle patterns on this bar: {pats}")
            for t in cfg["triggers"]:
                if t["tf"] != tf or t["key"] in state["fired"]:
                    continue
                lvl = t["level"]
                hit = (c[i] >= lvl if t.get("inclusive") else c[i] > lvl) if t["side"] == "bull" else c[i] < lvl
                if hit:
                    icon = "🟢" if t["side"] == "bull" else "🔴"
                    alert(state, t["key"], f"{icon} XRP/USD {t['desc']}\nTrigger: close {'>' if t['side'] == 'bull' else '<'}"
                                           f"{'=' if t.get('inclusive') else ''} {lvl}\n{bar}\n{pnl(trade, c[i])}\n"
                                           f"{t['next']}\nAlert only -- cdcx NO TRADE / execution gate unchanged.")
            for r in cfg.get("retests", []):
                if r["tf"] != tf or r["key"] in state["fired"]:
                    continue
                if c[i] < r["fail_level"]:
                    verdict, icon = f"FAILED (closed below {r['fail_level']}, beyond the 0.25x ATR margin)", "⚠️"
                elif l[i] <= r["zone_top"] and c[i] >= r["level"]:
                    verdict, icon = "HELD (dipped into the retest zone and closed back above)", "✅"
                else:
                    continue
                alert(state, r["key"], f"{icon} XRP/USD {r['desc']}: {verdict}\nLevel {r['level']} | zone to "
                                       f"{r['zone_top']} | fails below {r['fail_level']}\n{bar}\n{pnl(trade, c[i])}\n"
                                       "Alert only -- cdcx gate unchanged.")
        if new:
            state["last_bar"][tf] = last
            save_state(state)

    # Paper trade: stop / TP1 touched (wick, including the forming 15m bar)
    *_, raw = closed_bars(ex, "15m")
    lo, hi = min(raw.lows[-4:]), max(raw.highs[-4:])
    if lo <= trade["stop"] and "trade_stop" not in state["fired"]:
        alert(state, "trade_stop", f"🛑 XRP/USD touched the paper stop {trade['stop']:.4f} (low {lo:.4f}).\n"
                                   f"{pnl(trade, trade['stop'])}\nRun `cdcx-ai --update-trades` to record it.")
    if hi >= trade["tp1"] and "trade_tp1" not in state["fired"]:
        alert(state, "trade_tp1", f"🎯 XRP/USD touched TP1 {trade['tp1']:.4f} (high {hi:.4f}).\n"
                                  f"{pnl(trade, trade['tp1'])}\nRun `cdcx-ai --update-trades` -- stop to break-even, 25% closes.")


def armed_message(cfg: dict) -> str:
    bulls = [t for t in cfg["triggers"] if t["side"] == "bull"]
    bears = [t for t in cfg["triggers"] if t["side"] == "bear"]
    lines = ["🔔 XRP/USD BOS trigger watcher RE-ARMED (closed bars, checked every 60s)", cfg.get("armed_note", ""), "BULLISH:"]
    lines += [f"  {t['tf'].upper()} close {'>=' if t.get('inclusive') else '>'} {t['level']}  {t['desc'].split(':')[0]}" for t in bulls]
    lines.append("BEARISH:")
    lines += [f"  {t['tf'].upper()} close < {t['level']}  {t['desc'].split(':')[0]}" for t in bears]
    for r in cfg.get("retests", []):
        lines.append(f"RETEST: {r['desc']} -- HELD if a bar dips to <= {r['zone_top']} and closes >= {r['level']}; "
                     f"FAILED on a close < {r['fail_level']}")
    tr = cfg["trade"]
    lines.append(f"Paper trade: stop {tr['stop']:.4f} / TP1 {tr['tp1']:.4f} touches. Each alert fires once. Runs up to 7 days.")
    return "\n".join(x for x in lines if x)


def main() -> int:
    cfg = load_config()
    state = load_state()
    ex = CryptoComExchange()
    if "armed" not in state["fired"]:
        check(ex, state, cfg)  # records the current bars so only new closes count
        send_message(armed_message(cfg), source="cdcx-telegram", symbol=SYMBOL)
        state["fired"]["armed"] = time.time()
        save_state(state)
        log("armed")
    errors = 0
    while time.time() - state["started"] < RUN_FOR_S:
        try:
            check(ex, state, load_config())  # re-read each poll: edits to the config apply live
            errors = 0
        except Exception as exc:  # network / Telegram hiccup: back off and keep watching
            errors += 1
            log(f"error {errors}: {type(exc).__name__}: {exc}")
            if errors == 1:
                log(traceback.format_exc().splitlines()[-1])
            time.sleep(min(600, POLL_S * 2 ** min(errors, 4)))
            continue
        trend_keys = [t["key"] for t in cfg["triggers"] if t["tf"] in ("4h", "1d") and "weekly" not in t["key"]]
        if trend_keys and all(k in state["fired"] for k in trend_keys):
            break
        time.sleep(POLL_S)
    log("watcher finished")
    return 0


if __name__ == "__main__":
    sys.exit(main())
