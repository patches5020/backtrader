"""
journal.py
----------
On-disk audit trail for the pipeline described in the project's flowchart:

    SIGNAL -> SIMULATED ORDER -> PAPER RESULT -> REJECT | APPROVE
                                                              |
                                                     HUMAN PERMISSION
                                                              |
                                              LIVE ORDER -> LIVE EXECUTION -> LIVE RESULT

trading/
├── paper/
│   ├── signals/            every TradeSignal considered by --execute, pass or fail
│   ├── simulated_orders/   the sized plan (entry/stop/TP/size) once an entry timeframe qualifies
│   ├── simulated_results/  paper trades that cleared every gate and were opened (PAPER RESULT: PASS)
│   └── rejected/           anything blocked at any gate, with the reason and stage recorded
│
└── live/
    ├── approved/           the human's typed YES, captured right before a real order is sent
    ├── orders/              the built order_list + dry-run preview, before the human is asked
    ├── executions/          the real (non-dry-run) send result once the order actually goes out
    └── results/             realized P&L of a *closed* live position

`results/` is never written automatically -- this project has no live
fill/position polling (see live_execution.py's own docstring), so a closed
live trade has to be recorded manually via `write_live_result()` or
`python -m cdcx --record-live-close`. `tax_export.py` reads this folder to
build the Form 8949 / Schedule D / CPA / SSA exports.

Every record is one JSON file: envelope fields (`schema_version`,
`written_at`, `stage`, `symbol`) plus whatever the specific `write_*` call
was given. This is an append-only audit trail -- nothing here is read back
into the trading pipeline itself, except by `tax_export.py` reading
`live/results/`.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, is_dataclass
from typing import Any

from .config import settings

SCHEMA_VERSION = 1

# stage name -> (top-level dir, subdirectory)
_STAGE_DIRS = {
    "signal": ("paper", "signals"),
    "simulated_order": ("paper", "simulated_orders"),
    "simulated_result": ("paper", "simulated_results"),
    "rejected": ("paper", "rejected"),
    "approved": ("live", "approved"),
    "live_order": ("live", "orders"),
    "live_execution": ("live", "executions"),
    "live_result": ("live", "results"),
}


def _root() -> str:
    return settings.trading_journal_dir


def stage_dir(stage: str) -> str:
    top, sub = _STAGE_DIRS[stage]
    return os.path.join(_root(), top, sub)


def ensure_directories() -> None:
    """Creates the full trading/paper/... and trading/live/... tree up
    front, even for stages that haven't written anything yet."""
    for stage in _STAGE_DIRS:
        os.makedirs(stage_dir(stage), exist_ok=True)


def _jsonable(value: Any) -> Any:
    """Recursively converts dataclasses (TradeSignal, Trade, RegimeResult,
    BracketResult, ...) into plain dicts so json.dump doesn't choke on them."""
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _write(stage: str, symbol: str, payload: dict) -> str:
    directory = stage_dir(stage)
    os.makedirs(directory, exist_ok=True)

    record = {
        "schema_version": SCHEMA_VERSION,
        "written_at": time.time(),
        "stage": stage,
        "symbol": symbol,
    }
    record.update({k: _jsonable(v) for k, v in payload.items()})

    safe_symbol = symbol.replace("/", "-") if symbol else "unknown"
    filename = f"{int(record['written_at'] * 1000)}_{safe_symbol}_{uuid.uuid4().hex[:8]}.json"
    path = os.path.join(directory, filename)
    with open(path, "w") as f:
        json.dump(record, f, indent=2, default=str)
    return path


# --- paper side -------------------------------------------------------

def write_signal(symbol: str, timeframe: str, signal: Any) -> str:
    return _write("signal", symbol, {"timeframe": timeframe, "signal": signal})


def write_simulated_order(symbol: str, direction: str, plan: Any, tp_levels: list[float]) -> str:
    return _write("simulated_order", symbol, {"direction": direction, "plan": plan, "tp_levels": tp_levels})


def write_simulated_result(symbol: str, trade: Any, result: str = "PASS") -> str:
    return _write("simulated_result", symbol, {"result": result, "trade": trade})


def write_rejected(symbol: str, stage: str, reason: str, details: Any = None) -> str:
    return _write("rejected", symbol, {"rejected_at_stage": stage, "reason": reason, "details": details})


# --- live side ----------------------------------------------------------

def write_live_order(symbol: str, instrument_name: str, order_list: list[dict]) -> str:
    return _write("live_order", symbol, {"instrument_name": instrument_name, "order_list": order_list})


def write_approved(symbol: str, order_list: list[dict], confirmed_by: str = "human") -> str:
    return _write("approved", symbol, {"order_list": order_list, "confirmed_by": confirmed_by})


def write_live_execution(symbol: str, result: Any) -> str:
    return _write("live_execution", symbol, {"result": result})


def write_live_result(
    symbol: str, direction: str, quantity: float, entry_price: float, exit_price: float,
    opened_at: float, closed_at: float, fees: float = 0.0, notes: str = "",
) -> str:
    """
    Records the realized outcome of a *closed* live position, e.g. from
    `python -m cdcx --record-live-close`. `opened_at`/`closed_at` are unix
    timestamps (seconds) -- used by tax_export.py to compute the holding
    period (short-term vs long-term). Nothing in this project polls the
    exchange for fills or closes automatically, so this always has to be
    supplied by you, not derived.
    """
    direction_sign = 1 if direction == "long" else -1
    gross_pnl = (exit_price - entry_price) * quantity * direction_sign
    realized_pnl = gross_pnl - fees
    return _write("live_result", symbol, {
        "direction": direction,
        "quantity": quantity,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "opened_at": opened_at,
        "closed_at": closed_at,
        "fees": fees,
        "gross_pnl": round(gross_pnl, 8),
        "realized_pnl": round(realized_pnl, 8),
        "notes": notes,
    })


def load_stage(stage: str) -> list[dict]:
    """Reads back every JSON record written to one stage's directory,
    oldest first (filenames are millisecond-timestamp-prefixed)."""
    directory = stage_dir(stage)
    if not os.path.isdir(directory):
        return []
    records = []
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".json"):
            continue
        with open(os.path.join(directory, filename)) as f:
            records.append(json.load(f))
    return records
