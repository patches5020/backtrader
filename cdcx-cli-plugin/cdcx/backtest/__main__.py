"""
Run a synthetic-data demo backtest:

    python -m cdcx.backtest
"""

from __future__ import annotations

from cdcx.backtest.synthetic import generate_ohlcv
from cdcx.backtest.engine import (
    run_single_tf_backtest,
    run_confluence_backtest,
    format_backtest_report,
)


def main() -> int:
    print("Generating synthetic multi-regime OHLCV (1500 × 1h bars)...")
    data = generate_ohlcv(n_bars=1500, start_price=62000.0, seed=42, timeframe="1h")
    print(f"  Start={data.closes[0]:.1f}  End={data.closes[-1]:.1f}  "
          f"Min={min(data.lows):.1f}  Max={max(data.highs):.1f}")
    print()

    print("=== SINGLE-TIMEFRAME BACKTEST (1h, checklist ON) ===")
    r1 = run_single_tf_backtest(
        data,
        symbol="BTC/USDT",
        timeframe="1h",
        warmup=150,
        initial_balance=10_000.0,
        risk_pct=2.0,
        min_score_long=60.0,
        min_score_short=40.0,
        require_checklist=True,
    )
    print(format_backtest_report(r1))
    print()

    print("=== SINGLE-TIMEFRAME BACKTEST (1h, checklist OFF — more trades) ===")
    r2 = run_single_tf_backtest(
        data,
        symbol="BTC/USDT",
        timeframe="1h",
        warmup=150,
        initial_balance=10_000.0,
        risk_pct=2.0,
        min_score_long=55.0,
        min_score_short=45.0,
        require_checklist=False,
    )
    print(format_backtest_report(r2))
    print()

    print("=== MULTI-TF CONFLUENCE BACKTEST (resampled 4h/1d/1w) ===")
    r3 = run_confluence_backtest(
        data,
        symbol="BTC/USDT",
        warmup_1h=250,
        initial_balance=10_000.0,
        risk_pct=2.0,
    )
    print(format_backtest_report(r3))
    print()

    print("IMPORTANT CAVEATS")
    print("-" * 60)
    print("• This used SYNTHETIC price data, not real Crypto.com history.")
    print("• Synthetic regimes are simplified; real markets have more structure,")
    print("  liquidity holes, and regime shifts.")
    print("• Fees + fixed slippage + size-dependent market impact (sqrt law vs ADV) ARE modelled.")
    print("• Results are for demonstrating the backtester machinery only.")
    print("• Do NOT treat these numbers as evidence of a live edge.")
    print("-" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
