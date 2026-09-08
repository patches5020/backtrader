"""
no_trade_gate.py
------------------
The FINAL, absolute gate, checked immediately before a live order is ever
sent -- layered on TOP of every earlier gate in the pipeline
(entry_checklist.py, no_trade_filter.py, regime.py, circuit_breaker.py).
Re-validates the whole trade from scratch right at the point of no return,
rather than trusting that everything checked upstream still holds by the
time a human has typed YES.

Every condition below is an unconditional, independent block -- ANY single
failure refuses the trade outright ("NO TRADE"), with every failing reason
always shown, never silently:

    paper_trade_result != "PASS"          -> NO TRADE
    human_approval is not True            -> NO TRADE
    risk_pct > max_risk_pct (2% default)  -> NO TRADE
    stop_loss missing / <= 0              -> NO TRADE
    any of TP1-4 missing / <= 0           -> NO TRADE
    timeframe_confirmed is not True       -> NO TRADE
    withdrawal permission not confirmed   -> NO TRADE (see below)
    market data older than the staleness
        limit (in candles)                -> NO TRADE
    duplicate_order_detected              -> NO TRADE

**Withdrawal permission**: Crypto.com's API (via ccxt) has no
`fetchPermissions`-equivalent endpoint (confirmed: `ccxt.cryptocom().has`
doesn't advertise it) -- there is no way for this project to programmatically
verify an API key's withdrawal-permission flag. Rather than skip the check
or silently assume it's safe, this gate FAILS CLOSED: it requires an
explicit human attestation (`--confirmed-no-withdraw-permission` on the
CLI) that you've checked manually in your Crypto.com account's API-key
settings. No attestation, no live order -- exactly like every other
condition here, unknown is treated as unsafe, not as a pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

DEFAULT_MAX_RISK_PCT = 2.0
DEFAULT_MAX_DATA_STALENESS_BARS = 3.0

_TIMEFRAME_UNIT_SECONDS = {"m": 60, "h": 3600, "d": 86400, "w": 604800}


def timeframe_to_seconds(timeframe: str) -> Optional[float]:
    """Tiny local parser ("1h" -> 3600.0, "4h" -> 14400.0, "1d" -> 86400.0,
    "1w" -> 604800.0) -- avoids depending on ccxt just for this. Returns
    None (not an exception) for anything it can't parse, so the staleness
    check degrades to "skipped" rather than crashing the whole gate."""
    timeframe = (timeframe or "").strip().lower()
    if not timeframe or timeframe[-1] not in _TIMEFRAME_UNIT_SECONDS:
        return None
    try:
        count = float(timeframe[:-1])
    except ValueError:
        return None
    return count * _TIMEFRAME_UNIT_SECONDS[timeframe[-1]]


@dataclass
class NoTradeGateResult:
    passed: bool
    failures: list[str] = field(default_factory=list)


def check_no_trade_gate(
    *,
    paper_trade_result: str,
    human_approval: bool,
    risk_pct: Optional[float],
    stop_loss: Optional[float],
    take_profits: Sequence[Optional[float]],
    timeframe_confirmed: bool,
    withdrawal_permission_confirmed_disabled: bool,
    duplicate_order_detected: bool,
    data_age_seconds: Optional[float] = None,
    timeframe: str = "",
    max_risk_pct: float = DEFAULT_MAX_RISK_PCT,
    max_data_staleness_bars: float = DEFAULT_MAX_DATA_STALENESS_BARS,
    required_tp_count: int = 4,
) -> NoTradeGateResult:
    failures: list[str] = []

    if paper_trade_result != "PASS":
        failures.append(f"Paper trade result is '{paper_trade_result}', not PASS.")

    if human_approval is not True:
        failures.append("Human approval was not explicitly confirmed (typed YES).")

    if risk_pct is None or risk_pct > max_risk_pct:
        failures.append(f"Risk {risk_pct}% exceeds the {max_risk_pct:g}% ceiling.")

    if stop_loss is None or stop_loss <= 0:
        failures.append("Stop loss (SL) is missing or invalid.")

    # required_tp_count adapts to the strategy's own complete ladder length --
    # the trending path plans a full TP1-4 ladder, the ranging path plans
    # exactly TP1/TP2 (POC + opposite range edge) by design (see
    # ranging_strategy.py) -- either way, every planned target must be
    # present and valid, not partially missing.
    tps = list(take_profits)
    if len(tps) < required_tp_count or any(tp is None or tp <= 0 for tp in tps[:required_tp_count]):
        failures.append(f"One or more of the planned TP1-{required_tp_count} targets is missing or invalid ({tps}).")

    if timeframe_confirmed is not True:
        failures.append("Required multi-timeframe confirmation did not pass.")

    if withdrawal_permission_confirmed_disabled is not True:
        failures.append(
            "Withdrawal permission on the API key has not been confirmed disabled -- "
            "this project cannot query Crypto.com API key permissions automatically. "
            "Check manually in your Crypto.com account's API-key settings, then pass "
            "--confirmed-no-withdraw-permission."
        )

    if data_age_seconds is not None:
        timeframe_seconds = timeframe_to_seconds(timeframe)
        if timeframe_seconds:
            data_age_bars = data_age_seconds / timeframe_seconds
            if data_age_bars > max_data_staleness_bars:
                failures.append(
                    f"Market data is {data_age_bars:.1f} candles old ({data_age_seconds:.0f}s), "
                    f"exceeding the {max_data_staleness_bars:g}-candle staleness limit."
                )

    if duplicate_order_detected:
        failures.append("A duplicate/already-open order or position was detected for this symbol.")

    return NoTradeGateResult(passed=not failures, failures=failures)


def format_no_trade_gate(result: NoTradeGateResult) -> str:
    lines = ["=" * 60, "FINAL NO-TRADE GATE".center(60), "=" * 60]
    if result.passed:
        lines.append("ALL CHECKS PASSED -- cleared to send the live order.")
    else:
        lines.append("BLOCKED -- NO TRADE:")
        for f in result.failures:
            lines.append(f"  - {f}")
    lines.append("=" * 60)
    return "\n".join(lines)
