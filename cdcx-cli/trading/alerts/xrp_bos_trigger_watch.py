"""
XRP/USD BOS trigger-map watcher -> Telegram alerts (send-only).

Levels are the trigger map sent to Telegram on 2026-10-04 02:33 UTC (msg 177):
cdcx's own BOS rule on CLOSED bars -- close beyond the latest labeled swing
by 0.25x ATR. Each condition alerts ONCE. Also alerts on:
  * the 1H retest after a 1H break (held / failed), with any cdcx candlestick
    pattern on that bar;
  * the open paper trade 5a75fd5f touching its stop (1.3843) or TP1 (1.8569).

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
STATE = HERE / "xrp_bos_watch_state.json"
LOG = HERE / "xrp_bos_watch.log"
POLL_S = 60
RUN_FOR_S = 7 * 24 * 3600
TF_SECS = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}

ENTRY, STOP, TP1, QTY, ONE_R = 1.532, 1.38430654, 1.85693, 135.41560556, 1.532 - 1.38430654

# key: (timeframe, side, close level, swing level, description)
TRIGGERS = {
    "15m_bull": ("15m", "bull", 1.4916, 1.4910, "15m early warning: close above the 1.4910 swing high"),
    "15m_bear": ("15m", "bear", 1.4862, 1.4868, "15m early warning: close below the 1.4868 swing low"),
    "1h_bull": ("1h", "bull", 1.4973, 1.4958, "1H BULLISH BOS: close above the 1.4958 swing high (+ reclaims the 1.495-1.496 POC)"),
    "1h_bear": ("1h", "bear", 1.4827, 1.4842, "1H BEARISH BOS: close below the 1.4842 swing low"),
    "4h_bull": ("4h", "bull", 1.5599, 1.5545, "4H BULLISH BOS (trend confirm): close above the 1.5545 Oct 2 high"),
    "4h_bear": ("4h", "bear", 1.4401, 1.4455, "4H BEARISH BOS (trend confirm): close below the 1.4455 Oct 2 low"),
    "1d_bull": ("1d", "bull", 1.5805, 1.5607, "1D BULLISH BOS: daily close above the 1.5607 swing high"),
    "1d_bear": ("1d", "bear", 1.4456, 1.4654, "1D BEARISH BOS: daily close below the 1.4654 swing low (loses 1D VAH 1.447)"),
}
NEXT = {
    "1h_bull": "Next: retest of 1.4958-1.496 should HOLD (hammer / bullish engulfing / tweezer bottom), ATR expansion, then 1.5112-1.53 -> break-even 1.532.",
    "1h_bear": "Next: a retest of 1.4842 from below should FAIL (shooting star / bearish engulfing / tweezer top), then 1.4796-1.4765 -> 1.4455.",
    "4h_bull": "Trend-level bullish confirmation. Next 1D > 1.5805; 4H VAH 1.604 / weekly VAL 1.618.",
    "4h_bear": "Trend-level bearish confirmation. Next 1.4267 -> 1D FVG 1.3191-1.3928, which overlaps the 1.3843 stop.",
    "1d_bull": "Daily structure turned bullish.",
    "1d_bear": "Daily lost its value-area high. Stop 1.3843 sits inside the 1D FVG 1.3191-1.3928.",
    "15m_bull": "Early warning only -- cdcx counts the 1H trigger (close > 1.4973).",
    "15m_bear": "Early warning only -- cdcx counts the 1H trigger (close < 1.4827).",
}


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z {msg}"
    with LOG.open("a") as f:
        f.write(line + "\n")
    print(line, flush=True)


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {"fired": {}, "last_bar": {}, "break_bar": {}, "started": time.time()}


def save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=1))


def pnl(price: float) -> str:
    usd = (price - ENTRY) * QTY
    return f"trade 5a75fd5f at {price:.4f}: {'+' if usd >= 0 else '-'}${abs(usd):.2f} ({(price - ENTRY) / ONE_R:+.2f}R)"


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


def check(ex: CryptoComExchange, state: dict) -> None:
    for tf in TF_SECS:
        ts, o, h, l, c, v, _ = closed_bars(ex, tf)
        last = ts[-1]
        if state["last_bar"].get(tf) is None:  # first run: only bars that close after arming count
            state["last_bar"][tf] = last
            save_state(state)
            continue
        new = [i for i, t in enumerate(ts) if t > state["last_bar"][tf]]
        for i in new:
            avg = sum(v[max(0, i - 20):i]) / max(1, len(v[max(0, i - 20):i]))
            vol_ok = v[i] >= avg
            pats = ", ".join(f"{p.name} ({p.direction})" for p in detect_patterns(h[:i + 1], l[:i + 1], o[:i + 1], c[:i + 1])) or "none"
            bar = (f"{tf.upper()} bar {utc(ts[i])}Z  O {o[i]:.4f} H {h[i]:.4f} L {l[i]:.4f} C {c[i]:.4f}\n"
                   f"Volume {v[i]:,.0f} vs 20-bar avg {avg:,.0f} -> {'VOLUME-CONFIRMED' if vol_ok else 'NOT volume-confirmed'}\n"
                   f"cdcx candle patterns on this bar: {pats}")
            for key, (ktf, side, level, swing, desc) in TRIGGERS.items():
                if ktf != tf or key in state["fired"]:
                    continue
                if (side == "bull" and c[i] > level) or (side == "bear" and c[i] < level):
                    state.setdefault("break_bar", {})[key] = ts[i]  # the retest must come on a LATER bar
                    alert(state, key, f"🚨 XRP/USD {desc}\nTrigger: close {'>' if side == 'bull' else '<'} {level} "
                                      f"(swing {swing} {'+' if side == 'bull' else '-'} 0.25x ATR)\n{bar}\n{pnl(c[i])}\n"
                                      f"{NEXT[key]}\nAlert only -- cdcx NO TRADE / execution gate unchanged.")
            if tf == "1h":  # retest follow-up, on bars AFTER the break bar
                for brk, side, swing in (("1h_bull", "bull", 1.4958), ("1h_bear", "bear", 1.4842)):
                    break_ts = state.get("break_bar", {}).get(brk)
                    if break_ts is None or ts[i] <= break_ts or f"{brk}_retest" in state["fired"]:
                        continue
                    if side == "bull" and l[i] <= 1.4973:
                        held = c[i] > swing
                    elif side == "bear" and h[i] >= 1.4827:
                        held = c[i] < swing
                    else:
                        continue
                    verdict = "HELD" if held else "FAILED (back through the level -- break not accepted)"
                    alert(state, f"{brk}_retest", f"{'✅' if held else '⚠️'} XRP/USD 1H {side.upper()} BOS retest {verdict}\n"
                                                  f"Retest of {swing}\n{bar}\n{pnl(c[i])}\nAlert only -- cdcx gate unchanged.")
        if new:
            state["last_bar"][tf] = last
            save_state(state)

    # Paper trade: stop / TP1 touched (wick, including the forming 15m bar)
    *_, raw = closed_bars(ex, "15m")
    lo, hi = min(raw.lows[-4:]), max(raw.highs[-4:])
    if lo <= STOP and "trade_stop" not in state["fired"]:
        alert(state, "trade_stop", f"🛑 XRP/USD touched the paper stop {STOP:.4f} (low {lo:.4f}).\n{pnl(STOP)}\n"
                                   "Run `cdcx-ai --update-trades` to record it.")
    if hi >= TP1 and "trade_tp1" not in state["fired"]:
        alert(state, "trade_tp1", f"🎯 XRP/USD touched TP1 {TP1:.4f} (high {hi:.4f}).\n{pnl(TP1)}\n"
                                  "Run `cdcx-ai --update-trades` -- stop to break-even, 25% closes.")


def main() -> int:
    state = load_state()
    ex = CryptoComExchange()
    if "armed" not in state["fired"]:
        check(ex, state)  # records the current bars so only new closes count
        send_message("🔔 XRP/USD BOS trigger watcher ARMED (closed bars, checked every 60s)\n"
                     "1H: BULL close > 1.4973 | BEAR close < 1.4827\n4H: BULL > 1.5599 | BEAR < 1.4401\n"
                     "1D: BULL > 1.5805 | BEAR < 1.4456\n15m early warning: > 1.4916 | < 1.4862\n"
                     "Also: 1H retest held/failed, paper stop 1.3843 / TP1 1.8569 touches.\n"
                     "Each alert fires once. Runs up to 7 days.", source="cdcx-telegram", symbol=SYMBOL)
        state["fired"]["armed"] = time.time()
        save_state(state)
        log("armed")
    errors = 0
    while time.time() - state["started"] < RUN_FOR_S:
        try:
            check(ex, state)
            errors = 0
        except Exception as exc:  # network / Telegram hiccup: back off and keep watching
            errors += 1
            log(f"error {errors}: {type(exc).__name__}: {exc}")
            if errors == 1:
                log(traceback.format_exc().splitlines()[-1])
            time.sleep(min(600, POLL_S * 2 ** min(errors, 4)))
            continue
        if all(k in state["fired"] for k in ("1d_bull", "1d_bear", "4h_bull", "4h_bear")):
            break
        time.sleep(POLL_S)
    log("watcher finished")
    return 0


if __name__ == "__main__":
    sys.exit(main())
