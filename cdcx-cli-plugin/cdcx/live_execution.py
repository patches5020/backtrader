"""
live_execution.py
--------------------
Wires the confluence + entry-checklist + risk-sizing pipeline to the real
`cdcx` (Crypto.com Exchange CLI) binary's `advanced create-otoco` endpoint,
verified against the live schema (private/advanced/create-otoco):

    order_list: exactly 3 orders --
        [0] entry:       {instrument_name, side, type: MARKET|LIMIT, quantity}
        [1] stop leg:     {instrument_name, side, type: STOP_LOSS, trigger_price, quantity}
        [2] target leg:   {instrument_name, side, type: TAKE_PROFIT, trigger_price, quantity}

Safety model (do not weaken any of this without the person explicitly
asking):
    - --dry-run is ALWAYS sent first, unconditionally, and its output is
      shown before anything else happens.
    - The live (non-dry-run) command is only ever sent after an explicit
      interactive "yes" from the person running this -- never automatic.
    - --yes (the CLI's own "skip confirmation prompts" flag) is NEVER
      passed. The real CLI's own confirmation prompt stays active as a
      second, independent safety layer beyond ours.
    - Account leverage is NOT set here -- create-otoco's schema doesn't
      expose a leverage field, so leverage must already be configured on
      the account via `cdcx trade leverage` beforehand. This module warns
      about that rather than silently assuming a value.
    - The instrument_name mapping (e.g. "BTC/USDT" -> "BTCUSD-PERP") is a
      DERIVED GUESS from one verified example, not a confirmed mapping for
      every pair. It's always shown for review before sending, and can be
      overridden explicitly.
    - This only covers the FIRST bracket (entry + stop + TP1). Trailing the
      stop through TP2/TP3/TP4 requires placing a new bracket after TP1
      fills -- not automated here yet; see README.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Literal, Optional

Direction = Literal["long", "short"]

CDCX_BINARY = "cdcx"  # the real, separately-installed Crypto.com Exchange CLI


@dataclass
class BracketResult:
    order_list: list[dict]
    dry_run_command: list[str]
    dry_run_returncode: Optional[int] = None
    dry_run_stdout: str = ""
    dry_run_stderr: str = ""
    sent_live: bool = False
    live_command: Optional[list[str]] = None
    live_returncode: Optional[int] = None
    live_stdout: str = ""
    live_stderr: str = ""


def derive_instrument_name(symbol: str) -> str:
    """
    Best-effort derivation of a Crypto.com perpetual instrument name from
    our internal "BASE/QUOTE" symbol format, e.g. "BTC/USDT" -> "BTCUSD-PERP".
    Verified correct for BTC/USDT via a live --dry-run; NOT verified for
    every pair. Always pass an explicit override if you know the real
    listing differs (e.g. via `cdcx market list` / `cdcx schema show
    private/market/...`).
    """
    base = symbol.split("/")[0].upper()
    return f"{base}USD-PERP"


def build_otoco_order_list(
    instrument_name: str,
    direction: Direction,
    quantity: float,
    stop_price: float,
    take_profit_price: float,
    entry_type: str = "MARKET",
) -> list[dict]:
    entry_side = "BUY" if direction == "long" else "SELL"
    exit_side = "SELL" if direction == "long" else "BUY"
    qty_str = str(quantity)

    return [
        {"instrument_name": instrument_name, "side": entry_side, "type": entry_type, "quantity": qty_str},
        {
            "instrument_name": instrument_name, "side": exit_side, "type": "STOP_LOSS",
            "trigger_price": str(stop_price), "quantity": qty_str,
        },
        {
            "instrument_name": instrument_name, "side": exit_side, "type": "TAKE_PROFIT",
            "trigger_price": str(take_profit_price), "quantity": qty_str,
        },
    ]


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


def preview_bracket(order_list: list[dict]) -> BracketResult:
    """Always-safe step: runs ONLY --dry-run, never sends anything real."""
    dry_run_cmd = [CDCX_BINARY, "advanced", "create-otoco", "--dry-run", json.dumps(order_list)]
    proc = _run(dry_run_cmd)
    return BracketResult(
        order_list=order_list,
        dry_run_command=dry_run_cmd,
        dry_run_returncode=proc.returncode,
        dry_run_stdout=proc.stdout,
        dry_run_stderr=proc.stderr,
    )


def send_bracket_live(result: BracketResult) -> BracketResult:
    """
    Sends the REAL order. Caller is responsible for having already shown the
    dry-run output and obtained explicit, informed confirmation -- this
    function does not prompt itself, so it can't be called from anywhere
    that skips that step by accident.
    """
    live_cmd = [CDCX_BINARY, "advanced", "create-otoco", json.dumps(result.order_list)]  # no --yes, ever
    proc = _run(live_cmd)
    result.sent_live = True
    result.live_command = live_cmd
    result.live_returncode = proc.returncode
    result.live_stdout = proc.stdout
    result.live_stderr = proc.stderr
    return result


def format_bracket_preview(instrument_name: str, order_list: list[dict], result: BracketResult) -> str:
    lines = [
        "=" * 60,
        "LIVE BRACKET ORDER -- REVIEW CAREFULLY".center(60),
        "=" * 60,
        f"Instrument: {instrument_name}  (derived from symbol -- verify this is the real listing)",
        "",
        "Order list (entry / stop-loss / take-profit):",
        json.dumps(order_list, indent=2),
        "",
        f"Command: {' '.join(result.dry_run_command)}",
        "-" * 60,
        "DRY RUN OUTPUT (nothing sent yet):",
        result.dry_run_stdout or "(empty stdout)",
    ]
    if result.dry_run_stderr:
        lines.append("stderr: " + result.dry_run_stderr)
    lines.append(f"dry-run exit code: {result.dry_run_returncode}")
    lines.append("=" * 60)
    lines.append(
        "Reminders: account leverage is NOT set by this order -- confirm it "
        "separately via `cdcx trade leverage` beforehand. This bracket only "
        "covers entry + stop + TP1; TP2-TP4 trailing needs a new bracket "
        "placed manually after TP1 fills (not automated yet)."
    )
    return "\n".join(lines)
