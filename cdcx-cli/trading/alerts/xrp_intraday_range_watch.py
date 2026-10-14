"""
XRP/USD intraday RANGE plan (5m-1H, 2026-10-14) -> Telegram alerts (send-only, alert-only).

Watches the 30m range from the intraday paper plan and tells the user when price reaches an
edge zone, whether cdcx's ranging setup (all 4 conditions on a CLOSED 30m candle) qualifies,
and when a 30m close breaks the range. It NEVER trades, sizes or journals anything: a
qualifying range setup on 30m is a lower-timeframe, paper/advisory call that cdcx --execute
never uses, so every decision stays with the user.

Edge zones come from cdcx's own LIVE 30m range (the outer 15% of VAL..VAH, ranging_strategy's
NEAR_BOUNDARY_FRACTION), the same range the 4-condition check uses
(ranging_strategy.evaluate_ranging_setup on cli._range_inputs_from_data, exactly as
`cdcx-ai --timeframes 30m` would) -- so an edge alert and a 4/4 alert can never disagree about
where the range is. The range-BREAK levels are the plan's fixed boundaries from
xrp_intraday_range_config.json, plus the 4H/1H references.

Alerts (each once per visit; a side re-arms when a 5m close crosses back past the midpoint of the
range as it was when that side's alert fired -- the live range moving can't re-arm it):
  EDGE REACHED   a closed 5m bar traded into the long or short zone
  SETUP 4/4      a closed 30m candle passes all 4 ranging conditions on that side
  RANGE BREAK    a 30m close beyond the plan range high/low -> stand aside, re-run 1H/4H/1D/1W
  FAILED BREAK   after a break, a 30m close back inside the plan range
  DATA UNAVAILABLE after 3 failed checks in a row

    python trading/alerts/xrp_intraday_range_watch.py --once   print the current read, send nothing
    python trading/alerts/xrp_intraday_range_watch.py          watch loop until expires_utc
"""
from __future__ import annotations

import argparse
import json
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from cdcx import ranging_strategy
from cdcx.cli import _range_inputs_from_data
from cdcx.exchange.cryptocom import CryptoComExchange, OHLCV

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "xrp_intraday_range_config.json"
STATE = HERE / "xrp_intraday_range_state.json"
LOG = HERE / "xrp_intraday_range_watch.log"
SYMBOL = "XRP/USD"
POLL_S = 60
TF_SECS = {"5m": 300, "30m": 1800}
LIMIT = 200
DATA_FAIL_ALERT_AFTER = 3
LOCAL_TZ = ZoneInfo("America/Chicago")


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z {msg}"
    with LOG.open("a") as f:
        f.write(line + "\n")
    print(line, flush=True)


def iso(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def utc(ts: float) -> str:
    local = datetime.fromtimestamp(ts, timezone.utc).astimezone(LOCAL_TZ)
    hour = local.hour % 12 or 12
    return f"{datetime.fromtimestamp(ts, timezone.utc):%Y-%m-%d %H:%MZ} = {local:%b} {local.day} {hour}:{local:%M %p %Z}"


def closed(d: OHLCV, tf: str) -> OHLCV:
    """Drop the still-open last bar."""
    ts = [t / 1000 if t > 1e11 else t for t in d.timestamps]
    n = len(ts) - (1 if time.time() < ts[-1] + TF_SECS[tf] else 0)
    return OHLCV(d.timestamps[:n], d.opens[:n], d.highs[:n], d.lows[:n], d.closes[:n], d.volumes[:n], d.market)


def load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {"data_failures": 0, "fired": {}}


def save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=2))


def send(text: str) -> None:
    from cdcx.telegram_send import send_message
    send_message(text, pre=True, source="cdcx-ai", symbol=SYMBOL)


def fetch(ex=None) -> dict:
    """Closed 5m and 30m bars plus cdcx's 30m ranging setup. Raises on missing/stale data."""
    ex = ex or CryptoComExchange()
    d5 = closed(ex.fetch_ohlcv(SYMBOL, "5m", 60), "5m")
    d30 = closed(ex.fetch_ohlcv(SYMBOL, "30m", LIMIT), "30m")
    if len(d5.closes) < 3 or len(d30.closes) < 50:
        raise RuntimeError(f"too few closed bars (5m {len(d5.closes)}, 30m {len(d30.closes)})")
    if time.time() - d30.timestamps[-1] / 1000 > 3 * TF_SECS["30m"]:
        raise RuntimeError("stale 30m data")
    _, _, _, rsi_series, vp, patterns = _range_inputs_from_data(d30)
    setup = ranging_strategy.evaluate_ranging_setup(
        price=d30.closes[-1], rsi_series=rsi_series, poc=vp.poc, vah=vp.vah, val=vp.val,
        pattern_matches=patterns,
    )
    return {"d5": d5, "d30": d30, "setup": setup, "rsi": rsi_series[-1], "vp": vp}


def zones(vp) -> dict:
    """Edge zones from the live cdcx 30m range: the outer NEAR_BOUNDARY_FRACTION on each side."""
    edge = (vp.vah - vp.val) * ranging_strategy.NEAR_BOUNDARY_FRACTION
    return {"long": (vp.val, vp.val + edge), "short": (vp.vah - edge, vp.vah), "mid": (vp.val + vp.vah) / 2}


def zone_of(z: dict, high: float, low: float) -> str | None:
    """Which edge zone a bar traded into (a bar entirely beyond the range is a break, not an edge)."""
    if low <= z["long"][1] and high >= z["long"][0]:
        return "long"
    if high >= z["short"][0] and low <= z["short"][1]:
        return "short"
    return None


def summary(cfg: dict, fx: dict) -> str:
    d5, d30, s, vp = fx["d5"], fx["d30"], fx["setup"], fx["vp"]
    z = zones(vp)
    lines = [
        f"XRP/USD intraday range plan (paper, alert-only) -- expires {utc(iso(cfg['expires_utc']))}",
        f"Last 5m close {d5.closes[-1]:.4f} | last 30m close {d30.closes[-1]:.4f} "
        f"({utc(d30.timestamps[-1] / 1000 + TF_SECS['30m'])}) | 30m RSI {fx['rsi']:.1f}",
        f"cdcx live 30m range: VAL {vp.val:.4f}  POC {vp.poc:.4f}  VAH {vp.vah:.4f}",
        f"Live edge zones: LONG {z['long'][0]:.4f}-{z['long'][1]:.4f}  SHORT {z['short'][0]:.4f}-{z['short'][1]:.4f}",
        f"Plan range (break = 30m close beyond): {cfg['range_low']}-{cfg['range_high']} | "
        f"4H FVG top {cfg['accept_above']} | support {cfg['accept_below']} | bear trigger {cfg['bear_trigger']}",
        "",
        ranging_strategy.format_ranging_setup(s),
    ]
    return "\n".join(lines)


def check(cfg: dict, state: dict, fx: dict) -> list[str]:
    """Return the alerts to send for this poll and update `state` in place."""
    out, fired = [], state.setdefault("fired", {})
    d5, d30, s = fx["d5"], fx["d30"], fx["setup"]
    bar5, bar30 = d5.timestamps[-1], d30.timestamps[-1]
    c30 = d30.closes[-1]
    z = zones(fx["vp"])

    # A side re-arms only once a 5m close crosses back past the midpoint of the range AS IT WAS when that
    # side's alert fired. (Re-arming on the live range's middle let a shifting range re-fire the same visit:
    # LONG edge twice, 12:35Z and 13:00Z on 2026-10-14.)
    rearm = state.setdefault("rearm_at", {})
    if state.get("last_5m") != bar5:
        c5 = d5.closes[-1]
        for side, back in (("long", lambda m: c5 >= m), ("short", lambda m: c5 <= m)):
            if any(f"{k}_{side}" in fired for k in ("edge", "setup")) and back(rearm.get(side, z["mid"])):
                fired.pop(f"edge_{side}", None)
                fired.pop(f"setup_{side}", None)
                rearm.pop(side, None)

    if state.get("last_5m") != bar5:
        side = zone_of(z, d5.highs[-1], d5.lows[-1])
        if side and f"edge_{side}" not in fired:
            zone = z[side]
            out.append(
                f"{'🟢' if side == 'long' else '🔴'} XRP/USD reached the {side.upper()} edge zone "
                f"{zone[0]:.4f}-{zone[1]:.4f} of the live cdcx 30m range "
                f"(5m bar high {d5.highs[-1]:.4f} / low {d5.lows[-1]:.4f}, close {d5.closes[-1]:.4f}).\n"
                "NOT a trade yet: wait for a CLOSED 30m candle that passes all 4 range conditions, "
                "then time the entry on 5m. No trade has been placed.\n\n" + summary(cfg, fx))
            fired[f"edge_{side}"] = time.time()
            rearm.setdefault(side, z["mid"])
        state["last_5m"] = bar5

    if state.get("last_30m") != bar30:
        log(f"30m close {c30:.4f} rsi {fx['rsi']:.1f} setup={s.direction or 'none'} valid={s.valid}")
        if s.valid and f"setup_{s.direction}" not in fired:
            out.append(
                f"⚡ XRP/USD 30m RANGE SETUP 4/4 -- {s.direction.upper()} (paper, advisory).\n"
                "All 4 cdcx ranging conditions passed on the closed 30m candle. NOTHING HAS BEEN SUBMITTED.\n"
                "Before any paper entry: re-run `cdcx-ai --symbol XRP/USD --timeframes 30m,15m`, recompute "
                "entry/stop (1.5x ATR 30m)/TP1 POC/TP2 opposite edge, require R:R >= 1:2 to TP2, cap notional "
                "at paper equity, confirm on 5m.\n\n" + summary(cfg, fx))
            fired[f"setup_{s.direction}"] = time.time()
            rearm.setdefault(s.direction, z["mid"])
        if c30 > cfg["range_high"] and "break_up" not in fired:
            out.append(
                f"⬆️ XRP/USD RANGE BREAK UP: 30m close {c30:.4f} above {cfg['range_high']}.\n"
                f"Range plan off -> stand aside. Overhead: 4H bearish FVG to {cfg['accept_above']}. "
                "No long on a 30m break: re-run cdcx-ai --timeframes 1h,4h,1d,1w; act only if 1H trends "
                "and another higher timeframe agrees.")
            fired["break_up"] = time.time()
        if c30 < cfg["range_low"] and "break_down" not in fired:
            out.append(
                f"⬇️ XRP/USD RANGE BREAK DOWN: 30m close {c30:.4f} below {cfg['range_low']}.\n"
                f"Range plan off -> stand aside. Next support {cfg['accept_below']}. No short on a 30m break: "
                f"the bear plan still needs a 4H close below {cfg['bear_trigger']} plus its 1H retest.")
            fired["break_down"] = time.time()
        for key, back_inside, edge in (("break_up", c30 <= cfg["range_high"], cfg["range_high"]),
                                       ("break_down", c30 >= cfg["range_low"], cfg["range_low"])):
            if key in fired and back_inside:
                out.append(
                    f"↩️ XRP/USD FAILED BREAKOUT: 30m close {c30:.4f} back inside the plan range "
                    f"(broke {'above' if key == 'break_up' else 'below'} {edge}).\n"
                    "Possible edge rejection -- still needs all 4 closed-30m range conditions. "
                    "Re-run cdcx-ai --symbol XRP/USD --timeframes 30m,15m before anything.")
                fired.pop(key)
        state["last_30m"] = bar30
    return out


def watch(cfg: dict) -> None:
    log("watcher up")
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
                    send(f"⚠️ XRP/USD intraday range watcher: DATA UNAVAILABLE "
                         f"({state['data_failures']} checks in a row): {exc}\nStatus UNKNOWN -> no trade.")
                    state["data_alerted"] = time.time()
                except Exception:
                    log("telegram send failed:\n" + traceback.format_exc())
            save_state(state)
            time.sleep(POLL_S)
            continue
        try:
            for msg in check(cfg, state, fx):
                log("ALERT " + msg.splitlines()[0])
                send(msg)
        except Exception:
            log("check failed:\n" + traceback.format_exc())
        save_state(state)
        time.sleep(POLL_S)
    log("watcher finished (plan expired)")
    try:
        send("⏹ XRP/USD intraday range watcher finished (plan expired). Re-run the analysis for a new plan.")
    except Exception:
        log("telegram send failed:\n" + traceback.format_exc())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="print the current read, send nothing")
    args = ap.parse_args()
    cfg = json.loads(CONFIG.read_text())
    if args.once:
        print(summary(cfg, fetch()))
        return 0
    watch(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
