"""Multi-symbol support/resistance scanner.

Uses the pandas-vectorized ATR_EMA_VARIANT1 computation (not backtrader
Cerebro) so many instruments can be scanned quickly.
"""
from api.cryptocom import CryptocomClient, CryptocomAPIError
from indicators.atr_ema_variant1 import compute_atr_ema_variant1, DEFAULT_EMA_LENGTH, DEFAULT_ATR_LENGTH, DEFAULT_SR_LENGTH


def scan_instruments(instruments, timeframe="1h", count=200, ema_length=DEFAULT_EMA_LENGTH,
                      atr_length=DEFAULT_ATR_LENGTH, sr_length=DEFAULT_SR_LENGTH, client=None):
    """Return a list of {"instrument", "close", "ema", "support", "resistance", "hit"} for
    instruments whose latest bar touched support or resistance. Instruments with fetch
    errors are reported with an "error" key instead.
    """
    client = client or CryptocomClient()
    results = []

    for instrument in instruments:
        try:
            df = client.get_candles_dataframe(instrument, timeframe=timeframe, count=count)
        except CryptocomAPIError as exc:
            results.append({"instrument": instrument, "error": str(exc)})
            continue

        if df.empty or len(df) < max(ema_length, atr_length) + 1:
            results.append({"instrument": instrument, "error": "insufficient candle history"})
            continue

        signal = compute_atr_ema_variant1(
            df, ema_length=ema_length, atr_length=atr_length, sr_length=sr_length,
        )
        latest = signal.iloc[-1]

        hit = None
        if bool(latest["support_hit"]):
            hit = "support"
        elif bool(latest["resistance_hit"]):
            hit = "resistance"

        if hit:
            results.append({
                "instrument": instrument,
                "close": float(df["close"].iloc[-1]),
                "ema": float(latest["ema"]),
                "support": float(latest["support"]),
                "resistance": float(latest["resistance"]),
                "hit": hit,
            })

    return results


def format_scan_results(results):
    if not results:
        return "No support/resistance hits found."

    lines = []
    for row in results:
        if "error" in row:
            lines.append(f"{row['instrument']}: ERROR - {row['error']}")
            continue
        lines.append(
            f"{row['instrument']}: {row['hit'].upper()} hit @ {row['close']:.6f} "
            f"(ema={row['ema']:.6f}, support={row['support']:.6f}, resistance={row['resistance']:.6f})"
        )
    return "\n".join(lines)
