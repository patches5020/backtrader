"""End-to-end paper approval scenarios for xrp_vp_plan_watch, one scenario per PROCESS.
Usage: PID=xrp-bull-vp|xrp-bear-vp python -I check_vp_plan_e2e.py <ABSOLUTE workdir> <scenario>
(scenarios: any name; special: stale_bar, expires_mid, seed_loss; HOLD_S=n holds the approval lock n seconds;
REAL_SIZING=1 sizes with cdcx's real risk.build_position_plan; live_execution is a tripwire in every run)
Real: approve() flow, lock, state file, cdcx _open_trade_and_maybe_go_live (circuit breaker +
trade_manager ledger write), audit log. Stubbed: market data / requirement evaluation, the
analysis results fed to execution, and Telegram (written to <workdir>/telegram.txt)."""
import os, sys, json, time, types, pathlib

work = pathlib.Path(sys.argv[1]).resolve(); work.mkdir(parents=True, exist_ok=True); scenario = sys.argv[2]
os.environ["TRADE_STATE_PATH"] = str(work / "ledger.json")      # before cdcx.config is imported
os.environ["TRADING_JOURNAL_DIR"] = str(work / "journal")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import xrp_vp_plan_watch as w
from cdcx import cli, trade_manager
from cdcx.config import settings
assert settings.trade_state_path == str(work / "ledger.json"), "refusing to run against the real ledger"

pid = os.environ.get("PID", "xrp-bull-vp")
w.configure(w.symbol_for_plan(pid) or "XRP/USD")
pre = w.SYMBOLS[w.SYMBOL]["prefix"]
w.STATE, w.LOG, w.APPROVE_LOCK = work / f"{pre}_state.json", work / "audit.log", work / "approve.lock"
w.send = lambda m: (work / "telegram.txt").open("a").write(m + "\n---\n")
cfg = json.loads(w.CONFIG.read_text())
bar_1h = (int(time.time() // 3600) * 3600 - 3600) * 1000           # last closed 1H bar (open time, ms)
if scenario == "stale_bar":
    bar_1h -= 3 * 3600 * 1000
if scenario == "expires_mid":
    cfg = dict(cfg, expires_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 2)))

w.fetch = lambda ex=None: {"data": {}, "sig": {}}
w.evaluate = lambda c, side, fx: {"side": side, "reqs": [("R1", "stub", True, "")], "all_met": True,
                                  "invalidated": False, "plan": {}, "retest": "", "bar_1h": bar_1h,
                                  "trigger": 0, "invalidation": 0}
side_of = lambda pid: w.PLANS[pid]
signal = "STRONG BUY" if side_of(pid) == "long" else "STRONG SELL"
cli._run_single = lambda s, tf, l: types.SimpleNamespace(regime=types.SimpleNamespace(regime="trending"), signal=signal)
if scenario == "expires_mid":
    real_pre = w.preflight
    w.preflight = lambda side: (time.sleep(3), real_pre(side))[1]


# Tripwire: nothing in a check may reach the exchange order path.
import cdcx.live_execution as _live
for _name in dir(_live):
    if callable(getattr(_live, _name)) and not _name.startswith("_") and getattr(getattr(_live, _name), "__module__", "") == _live.__name__:
        setattr(_live, _name, lambda *a, _n=_name, **k: (_ for _ in ()).throw(AssertionError(f"live_execution.{_n} called")))


def real_sizing_execute(symbol, balance, risk_pct, results, limit, live=False, **k):
    """REAL_SIZING=1: cdcx's actual risk.build_position_plan sizes the trade from the equity and risk_pct that
    approve() passed, then cdcx's real _open_trade_and_maybe_go_live records it (breaker + ledger)."""
    from cdcx import risk
    assert live is False, "approve must never pass live=True"
    if os.environ.get("HOLD_S"):
        time.sleep(float(os.environ["HOLD_S"]))
    long = side_of(pid) == "long"
    entry, atr = (1.4056, 0.0122) if symbol == "XRP/USD" else (0.19783, 0.00112)
    plan = risk.build_position_plan(symbol=symbol, direction="long" if long else "short", entry_price=entry,
                                    atr=atr, account_balance=balance, risk_pct=risk_pct)
    sgn = 1 if long else -1
    tps = [entry + sgn * m * plan.stop_distance for m in (2.2, 2.6, 3.2, 4.5)]
    print(f"REAL PLAN risk_pct={plan.risk_pct} risk=${plan.risk_amount} stop={plan.stop_price} size={plan.position_size} "
          f"stop_distance={plan.stop_distance}")
    return cli._open_trade_and_maybe_go_live(symbol, "long" if long else "short", plan, tps, ["1h", "4h"], 7,
                                            live=False, instrument_name_override=None)


def fake_handle_execute(symbol, balance, risk_pct, results, limit, live=False, **k):
    """Stands in for the analysis part of cdcx's handler; the trade itself goes through cdcx's REAL
    _open_trade_and_maybe_go_live (circuit breaker gate + trade_manager.open_trade ledger write)."""
    assert live is False, "approve must never pass live=True"
    if os.environ.get("HOLD_S"):
        time.sleep(float(os.environ["HOLD_S"]))
    long = side_of(pid) == "long"
    entry, dist = (1.40, 0.03) if symbol == "XRP/USD" else (0.198, 0.004)
    risk = round(balance * (risk_pct if risk_pct is not None else 2.0) / 100, 2)
    plan = types.SimpleNamespace(entry_price=entry, atr=0.02, stop_price=entry - dist if long else entry + dist,
                                 position_size=round(risk / dist, 4), risk_amount=risk, account_balance=balance)
    tps = [entry + m * dist if long else entry - m * dist for m in (2.2, 2.6, 3.2, 4.5)]
    return cli._open_trade_and_maybe_go_live(symbol, "long" if long else "short", plan, tps, ["1h", "4h"], 7,
                                            live=False, instrument_name_override=None)


cli._handle_execute = real_sizing_execute if os.environ.get("REAL_SIZING") else fake_handle_execute
if scenario == "seed_loss":   # closed -$20 trade so the temp account's equity is $980, like the real ledger
    from cdcx import trade_manager as _tm
    _t, _ = _tm.open_trade(symbol="XRP/USD", direction="long", entry_price=1.532, atr=0.0985, stop_price=1.38430654,
                           tp_levels=[1.857, 1.916, 2.005, 2.197], position_size=135.41560556, risk_amount=20.0,
                           account_balance=1000.0)
    _tm.update_trade_bar(_t, 1.40, 1.40, 1.38, 1.39, at=time.time() - 3600)
    _tm.save_trades([_t])
    print(f"SCENARIO seed_loss closed {_t.id[:8]} pnl {_t.realized_pnl}")
    sys.exit(0)
rc = w.approve(cfg, pid)
print(f"SCENARIO {scenario} pid={pid} rc={rc}")
