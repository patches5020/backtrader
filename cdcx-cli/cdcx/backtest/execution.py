"""
execution.py
------------
Order-execution models for the offline backtester.

Supported styles:
  - MARKET   : single aggressive fill at the signal bar close
               (fee + fixed slip + size-dependent impact on full size)
  - TWAP     : Time-Weighted Average Price — split the order into N equal
               slices executed over a horizon of bars; each slice pays its
               own fee/slip/impact (smaller Q → lower impact per slice)

TWAP motivation
---------------
Large orders relative to ADV move the market. Spreading the same notional
over time reduces instantaneous participation and therefore square-root
impact, at the cost of:
  - more fee events (if fee is charged per fill)
  - price drift risk (market can move against you while you are slicing)
  - opportunity cost if the edge is short-lived

This module only computes *fill prices and cost breakdowns*. It does not
place live orders.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Sequence

from cdcx.backtest.engine import apply_trade_costs, _sqrt_market_impact_pct


ExecutionStyle = Literal["market", "twap"]


@dataclass
class FillSlice:
    bar_offset: int          # 0 = signal bar, 1 = next bar, ...
    price: float             # mid/reference price used for this slice
    size: float              # base units filled on this slice
    fill_price: float        # adverse-adjusted fill
    fee: float
    slip: float
    impact: float


@dataclass
class ExecutionResult:
    style: ExecutionStyle
    direction: str
    total_size: float
    avg_fill_price: float    # size-weighted average fill
    total_fee: float
    total_slip: float
    total_impact: float
    total_cost: float
    slices: list[FillSlice]
    notes: str = ""


def _adverse_fill(direction: str, mid: float, adverse_pct: float) -> float:
    """adverse_pct in percent (e.g. 0.10 = 10 bps)."""
    a = adverse_pct / 100.0
    if direction == "long":
        return mid * (1 + a)
    return mid * (1 - a)


def execute_market(
    direction: str,
    price: float,
    position_size: float,
    fee_pct: float = 0.075,
    slippage_pct: float = 0.05,
    avg_volume: float = 0.0,
    volatility_pct: float = 0.0,
    impact_coeff: float = 0.10,
) -> ExecutionResult:
    """Single-shot market fill of the full size at `price`."""
    impact_pct = _sqrt_market_impact_pct(
        position_size, avg_volume, volatility_pct, impact_coeff
    )
    adverse = slippage_pct + impact_pct
    fill = _adverse_fill(direction, price, adverse)

    notional = fill * position_size
    fee = fee_pct / 100.0 * notional
    slip = slippage_pct / 100.0 * price * position_size
    impact = impact_pct / 100.0 * price * position_size

    slice_ = FillSlice(
        bar_offset=0, price=price, size=position_size, fill_price=fill,
        fee=fee, slip=slip, impact=impact,
    )
    return ExecutionResult(
        style="market",
        direction=direction,
        total_size=position_size,
        avg_fill_price=fill,
        total_fee=fee,
        total_slip=slip,
        total_impact=impact,
        total_cost=fee + slip + impact,
        slices=[slice_],
        notes="Single market fill of full size",
    )


def execute_twap(
    direction: str,
    prices: Sequence[float],
    position_size: float,
    fee_pct: float = 0.075,
    slippage_pct: float = 0.05,
    avg_volumes: Sequence[float] | None = None,
    volatility_pcts: Sequence[float] | None = None,
    impact_coeff: float = 0.10,
    n_slices: int | None = None,
) -> ExecutionResult:
    """
    TWAP execution over the provided price path.

    `prices[0]` is the signal-bar reference; subsequent elements are later
    bars over which the remainder of the order is worked.

    Each slice is size = total / n_slices. Impact is computed on the *slice*
    size (not the full order), which is the whole point of TWAP.

    If avg_volumes / volatility_pcts are shorter than prices, the last value
    is reused.
    """
    if position_size <= 0:
        raise ValueError("position_size must be > 0")
    if not prices:
        raise ValueError("need at least one price")

    horizon = len(prices)
    n = n_slices or horizon
    n = max(1, min(n, horizon))

    slice_size = position_size / n
    slices: list[FillSlice] = []
    total_fee = total_slip = total_impact = 0.0
    weighted_fill = 0.0

    for i in range(n):
        mid = prices[i]
        adv = 0.0
        if avg_volumes:
            adv = avg_volumes[min(i, len(avg_volumes) - 1)]
        vol_pct = 0.0
        if volatility_pcts:
            vol_pct = volatility_pcts[min(i, len(volatility_pcts) - 1)]

        impact_pct = _sqrt_market_impact_pct(
            slice_size, adv, vol_pct, impact_coeff
        )
        adverse = slippage_pct + impact_pct
        fill = _adverse_fill(direction, mid, adverse)

        notional = fill * slice_size
        fee = fee_pct / 100.0 * notional
        slip = slippage_pct / 100.0 * mid * slice_size
        impact = impact_pct / 100.0 * mid * slice_size

        slices.append(FillSlice(
            bar_offset=i, price=mid, size=slice_size, fill_price=fill,
            fee=fee, slip=slip, impact=impact,
        ))
        total_fee += fee
        total_slip += slip
        total_impact += impact
        weighted_fill += fill * slice_size

    avg_fill = weighted_fill / position_size if position_size else prices[0]

    # Theoretical impact if the full size had been dumped at once (for notes)
    full_impact = _sqrt_market_impact_pct(
        position_size,
        avg_volumes[0] if avg_volumes else 0.0,
        volatility_pcts[0] if volatility_pcts else 0.0,
        impact_coeff,
    )
    slice_impact = _sqrt_market_impact_pct(
        slice_size,
        avg_volumes[0] if avg_volumes else 0.0,
        volatility_pcts[0] if volatility_pcts else 0.0,
        impact_coeff,
    )

    return ExecutionResult(
        style="twap",
        direction=direction,
        total_size=position_size,
        avg_fill_price=avg_fill,
        total_fee=total_fee,
        total_slip=total_slip,
        total_impact=total_impact,
        total_cost=total_fee + total_slip + total_impact,
        slices=slices,
        notes=(
            f"TWAP {n} slices over {horizon} bars | "
            f"per-slice impact {slice_impact:.4f}% vs full-size {full_impact:.4f}%"
        ),
    )


def compare_market_vs_twap(
    direction: str,
    prices: Sequence[float],
    position_size: float,
    fee_pct: float = 0.075,
    slippage_pct: float = 0.05,
    avg_volume: float = 0.0,
    volatility_pct: float = 0.0,
    impact_coeff: float = 0.10,
    n_slices: int | None = None,
) -> dict:
    """
    Side-by-side comparison helper for research / demos.

    Market uses prices[0] only. TWAP works the order across the whole path.
    """
    market = execute_market(
        direction, prices[0], position_size,
        fee_pct, slippage_pct, avg_volume, volatility_pct, impact_coeff,
    )
    vols = [avg_volume] * len(prices)
    vols_pct = [volatility_pct] * len(prices)
    twap = execute_twap(
        direction, prices, position_size,
        fee_pct, slippage_pct, vols, vols_pct, impact_coeff, n_slices,
    )

    # Gross advantage of TWAP avg fill vs market fill (before costs already in fills)
    if direction == "long":
        fill_advantage = market.avg_fill_price - twap.avg_fill_price  # lower is better for long
    else:
        fill_advantage = twap.avg_fill_price - market.avg_fill_price  # higher is better for short

    return {
        "market": market,
        "twap": twap,
        "impact_saved": market.total_impact - twap.total_impact,
        "fee_extra": twap.total_fee - market.total_fee,
        "cost_delta": twap.total_cost - market.total_cost,  # negative = TWAP cheaper
        "fill_advantage_per_unit": fill_advantage,
        "fill_advantage_dollars": fill_advantage * position_size,
    }


def format_execution_comparison(cmp: dict) -> str:
    m: ExecutionResult = cmp["market"]
    t: ExecutionResult = cmp["twap"]
    lines = [
        "=" * 56,
        "MARKET vs TWAP EXECUTION".center(56),
        "=" * 56,
        f"Direction:     {m.direction.upper()}  size={m.total_size:.6f}",
        "",
        f"{'':12} {'Market':>12} {'TWAP':>12} {'Delta':>12}",
        f"{'Avg fill':12} {m.avg_fill_price:12.4f} {t.avg_fill_price:12.4f} "
        f"{t.avg_fill_price - m.avg_fill_price:+12.4f}",
        f"{'Fee $':12} {m.total_fee:12.4f} {t.total_fee:12.4f} "
        f"{t.total_fee - m.total_fee:+12.4f}",
        f"{'Slip $':12} {m.total_slip:12.4f} {t.total_slip:12.4f} "
        f"{t.total_slip - m.total_slip:+12.4f}",
        f"{'Impact $':12} {m.total_impact:12.4f} {t.total_impact:12.4f} "
        f"{t.total_impact - m.total_impact:+12.4f}",
        f"{'Total cost $':12} {m.total_cost:12.4f} {t.total_cost:12.4f} "
        f"{cmp['cost_delta']:+12.4f}",
        "",
        f"Impact saved by TWAP:     ${cmp['impact_saved']:+.4f}",
        f"Extra fees from slicing:  ${cmp['fee_extra']:+.4f}",
        f"Fill advantage (TWAP):    ${cmp['fill_advantage_dollars']:+.4f}",
        "",
        f"Market note: {m.notes}",
        f"TWAP note:   {t.notes}",
        "=" * 56,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# When is TWAP worth it?  (analytic sketch)
# ---------------------------------------------------------------------------

def twap_breakeven_participation(
    impact_coeff: float = 0.10,
    volatility_pct: float = 1.0,
    fee_pct: float = 0.075,
    n_slices: int = 4,
) -> dict:
    """
    Rough breakeven: TWAP saves impact but pays n_slices fee events vs 1.

    For a single side:
      impact_full  = c * σ * sqrt(Q/V)
      impact_slice = c * σ * sqrt((Q/n)/V) = impact_full / sqrt(n)
      impact_saved (one side) ≈ impact_full * (1 - 1/sqrt(n)) * notional
      extra fees   ≈ (n - 1) * fee * (notional / n)  = fee * notional * (1 - 1/n)

    Breakeven participation roughly when impact savings = extra fees.
    Returns a dict of illustrative numbers at several participation rates.
    """
    rows = []
    for part in (0.01, 0.05, 0.10, 0.25, 0.50, 1.0):
        impact_full = impact_coeff * volatility_pct * math.sqrt(part)  # percent
        impact_slice = impact_coeff * volatility_pct * math.sqrt(part / n_slices)
        # one-side savings in percent of notional
        saved_pct = impact_full - impact_slice
        # extra fee percent of notional for one side with n fills vs 1
        extra_fee_pct = fee_pct * (1 - 1 / n_slices)
        net_pct = saved_pct - extra_fee_pct
        rows.append({
            "participation": part,
            "impact_full_pct": impact_full,
            "impact_slice_pct": impact_slice,
            "impact_saved_pct": saved_pct,
            "extra_fee_pct": extra_fee_pct,
            "net_advantage_pct": net_pct,
            "twap_better": net_pct > 0,
        })
    return {
        "n_slices": n_slices,
        "impact_coeff": impact_coeff,
        "volatility_pct": volatility_pct,
        "fee_pct": fee_pct,
        "rows": rows,
    }


if __name__ == "__main__":
    # Demo: large order relative to volume → TWAP wins on impact
    prices = [100.0, 100.2, 99.9, 100.1, 100.3, 99.8]
    size = 50.0
    adv = 200.0          # participation = 25% if dumped at once
    vol = 1.5            # 1.5% bar vol

    cmp = compare_market_vs_twap(
        "long", prices, size,
        avg_volume=adv, volatility_pct=vol, n_slices=6,
    )
    print(format_execution_comparison(cmp))
    print()

    be = twap_breakeven_participation(volatility_pct=1.5, n_slices=6)
    print("Breakeven sketch (one side, σ=1.5%, n=6):")
    print(f"{'Part':>8} {'Imp full':>10} {'Imp slice':>10} {'Saved':>8} {'+Fee':>8} {'Net':>8} TWAP?")
    for r in be["rows"]:
        print(
            f"{r['participation']:8.0%} {r['impact_full_pct']:10.4f} "
            f"{r['impact_slice_pct']:10.4f} {r['impact_saved_pct']:8.4f} "
            f"{r['extra_fee_pct']:8.4f} {r['net_advantage_pct']:+8.4f} "
            f"{'YES' if r['twap_better'] else 'no'}"
        )
