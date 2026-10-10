"""Offline checks for xrp_vp_plan_watch (no network, no real ledger/state, execution stubbed):
approvals both sides, conflicts, data failure, retest, bearish POC rejection; XLM plans and
cross-symbol rules (one open trade PER symbol, 1% risk each, shared approval lock).
Run from anywhere:  python -I cdcx-cli/trading/alerts/check_vp_plan_offline.py"""
import sys, json, time, types, pathlib, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import xrp_vp_plan_watch as w
from cdcx.exchange.cryptocom import OHLCV
import cdcx.cli as cli

tmp = pathlib.Path(tempfile.mkdtemp())
w.STATE = tmp / "vp_state.json"; w.LOG = tmp / "vp.log"; w.APPROVE_LOCK = tmp / "approve.lock"
sent = []; w.send = lambda m: sent.append(m)
executed = []; cli._handle_execute = lambda *a, **k: executed.append(a)
open_trades = []
w.trade_manager = types.SimpleNamespace(load_trades=lambda: open_trades)
w.paper_equity = lambda cfg: 980.0
w.fetch = lambda ex=None: {"data": {}, "sig": {}}
cfg = json.loads(w.CONFIG.read_text())
met = lambda side: {"side": side, "reqs": [("R1", "x", True, "")], "all_met": True, "invalidated": False,
                    "plan": {}, "retest": "", "bar_1h": (int(time.time() // 3600) * 3600 - 3600) * 1000,
                    "trigger": 1, "invalidation": 1}
notmet = lambda side: dict(met(side), all_met=False, reqs=[("R1", "x", False, "")])
sig = lambda regime, signal: types.SimpleNamespace(regime=types.SimpleNamespace(regime=regime), signal=signal)
def reset(): w.STATE.write_text(json.dumps({"plans": {}, "data_failures": 0}))
def live(regime1h, signal): cli._run_single = lambda s, tf, l: sig(regime1h if tf == "1h" else "trending", signal)
n = 0
def check(cond, label):
    global n; assert cond, label; n += 1

reset(); w.evaluate = lambda c, s, fx: met(s)
check(w.approve(cfg, "xrp-nope") == 1 and not executed, "unknown plan id")
check(w.approve(dict(cfg, expires_utc="2020-01-01T00:00:00Z"), "xrp-bull-vp") == 1 and not executed, "expired")
w.evaluate = lambda c, s, fx: notmet(s)
check(w.approve(cfg, "xrp-bull-vp") == 1 and not executed, "not met")
w.evaluate = lambda c, s, fx: met(s)
live("ranging", "STRONG BUY"); check(w.approve(cfg, "xrp-bull-vp") == 1 and not executed, "range path refused (bull)")
live("ranging", "STRONG SELL"); check(w.approve(cfg, "xrp-bear-vp") == 1 and not executed, "range path refused (bear)")
live("trending", "STRONG SELL"); check(w.approve(cfg, "xrp-bull-vp") == 1 and not executed, "bull refused on SHORT confluence")
live("trending", "STRONG BUY"); check(w.approve(cfg, "xrp-bear-vp") == 1 and not executed, "bear refused on LONG confluence")
def boom(ex=None): raise RuntimeError("exchange down")
w.fetch = boom; check(w.approve(cfg, "xrp-bull-vp") == 1 and not executed, "data failure -> refused")
w.fetch = lambda ex=None: {"data": {}, "sig": {}}
open_trades[:] = [types.SimpleNamespace(symbol="XRP/USD", status="open", id="abcdef12", direction="long")]
check(w.approve(cfg, "xrp-bear-vp") == 1 and not executed, "open XRP trade -> conflict refused")
open_trades[:] = []
live("trending", "STRONG BUY"); check(w.approve(cfg, "xrp-bull-vp") == 0 and len(executed) == 1, "bull executes")
check(executed[0][1] == 980.0 and executed[0][2] == 1.0, "sized on equity at the plan's 1% risk")
check(w.approve(cfg, "xrp-bull-vp") == 1 and len(executed) == 1, "bull duplicate refused")
live("trending", "STRONG SELL"); check(w.approve(cfg, "xrp-bear-vp") == 0 and len(executed) == 2, "bear executes (bull trade closed)")
check(w.approve(cfg, "xrp-bear-vp") == 1 and len(executed) == 2, "bear duplicate refused")
print(f"approval safeguards: {n}/{n} OK")

# --- XLM plans + cross-symbol rules (one open trade, one approval, shared account) ---
w.configure("XLM/USD")
w.STATE = tmp / "xlm_state.json"; w.LOG = tmp / "xlm.log"   # configure() re-points these; keep them in tmp
reset(); executed.clear(); w.evaluate = lambda c, s, fx: met(s)
check(w.SYMBOL == "XLM/USD" and set(w.PLANS) == {"xlm-bull-vp", "xlm-bear-vp"}, "XLM plan ids")
check(w.symbol_for_plan("xlm-bear-vp") == "XLM/USD" and w.symbol_for_plan("xrp-bull-vp") == "XRP/USD"
      and w.symbol_for_plan("doge-bull-vp") is None, "plan id -> symbol")
check(w.approve(cfg, "xrp-bull-vp") == 1 and not executed, "XRP plan id refused by the XLM watcher")
open_trades[:] = [types.SimpleNamespace(symbol="XLM/USD", status="open", id="abcdef12", direction="long")]
live("trending", "STRONG BUY"); check(w.approve(cfg, "xlm-bull-vp") == 1 and not executed, "open XLM trade blocks XLM")
open_trades[:] = [types.SimpleNamespace(symbol="XRP/USD", status="open", id="0badc0de", direction="long")]
check(w.approve(cfg, "xlm-bull-vp") == 0 and len(executed) == 1 and executed[0][0] == "XLM/USD",
      "open XRP trade does NOT block XLM (one per symbol); XLM executes on XLM/USD")
check(executed[0][2] == 1.0, "XLM sized at its 1% risk")
open_trades[:] = []
check(w.approve(cfg, "xlm-bull-vp") == 1 and len(executed) == 1, "XLM duplicate refused")
import fcntl
with w.APPROVE_LOCK.open("w") as held:
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)        # e.g. an XRP approval in progress
    live("trending", "STRONG SELL"); check(w.approve(cfg, "xlm-bear-vp") == 1 and len(executed) == 1,
                                           "shared lock: XLM refused while another approval runs")
check(f"{1.23456789:.{w.DEC}f}" == "1.23457", "XLM prices shown with 5 decimals")
check(w.risk_pct({"risk_pct": 1.0}) == 1.0 and w.risk_pct({}) == 2.0 and w.risk_pct({"risk_pct": 5}) == 2.0,
      "risk_pct from config, default 2, capped at 2")
w.configure("XRP/USD")
check(w.DEC == 4 and w.CONFIG.name == "xrp_vp_plan_config.json", "XRP defaults restored")
print(f"XLM + cross-symbol: {n}/{n} OK")

# retest both sides
H = 3600 * 1000
armed = 0
d4 = OHLCV([0, 4 * H, 8 * H], [0] * 3, [0] * 3, [0] * 3, [1.41, 1.43, 1.44], [1] * 3)
mk = lambda lows, highs, closes: OHLCV([(8 + i) * H for i in range(len(lows))], [0] * len(lows), highs, lows, closes, [1] * len(lows))
r = lambda d1, side, d=d4, lvl=1.4225: w.retest_state(d, d1, lvl, 0.003, armed, side)[0]
check(r(mk([1.424], [1.44], [1.43]), "long") is True, "bull retest held")
check(r(mk([1.41], [1.43], [1.418]), "long") is False, "bull retest failed")
d4s = OHLCV([0, 4 * H, 8 * H], [0] * 3, [0] * 3, [0] * 3, [1.33, 1.31, 1.30], [1] * 3)
check(r(mk([1.30], [1.3170], [1.31]), "short", d4s, 1.3176) is True, "bear retest held")
check(r(mk([1.30], [1.33], [1.322]), "short", d4s, 1.3176) is False, "bear retest failed")
check(r(mk([1.29], [1.30], [1.295]), "short", d4s, 1.3176) is False, "bear retest waiting")
# bear POC rejection
d = OHLCV(list(range(5)), [0] * 5, [1.40, 1.41, 1.42, 1.38, 1.37], [0] * 5, [1.39, 1.40, 1.405, 1.37, 1.36], [1] * 5)
check(w.bear_poc_rejection(d, 1.41)[0] == "CONFIRMED", "bear rejection confirmed")
d2 = OHLCV(list(range(3)), [0] * 3, [1.39, 1.39, 1.42], [0] * 3, [1.38, 1.38, 1.405], [1] * 3)
check(w.bear_poc_rejection(d2, 1.41)[0] == "PENDING", "bear rejection pending")
d3 = OHLCV(list(range(3)), [0] * 3, [1.39, 1.39, 1.40], [0] * 3, [1.38, 1.38, 1.39], [1] * 3)
check(w.bear_poc_rejection(d3, 1.41)[0] == "NONE", "touch-free -> none")
print(f"all {n} checks OK")
