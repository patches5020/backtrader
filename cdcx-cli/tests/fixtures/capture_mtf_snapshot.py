"""
Freeze a live multi-timeframe OHLCV pull into a JSON fixture so a cdcx-ai
report can be replayed offline, byte-for-byte the same market data, in a
regression test (see tests/test_baseline_xrp_mtf.py).

Usage (from the cdcx-cli directory):
    python tests/fixtures/capture_mtf_snapshot.py XRP/USD tests/fixtures/xrp_usd_mtf_baseline.json

`captured_at` is recorded so the test can pin engine.py's "is the last
candle still forming?" check (which reads time.time()) to the moment of
capture -- without it, replaying the same candles later would treat the
in-progress last bar as closed and shift VOL(17).
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict

from cdcx.config import settings
from cdcx.exchange.cryptocom import CryptoComExchange

TIMEFRAMES = ("1w", "1d", "4h", "1h")


def main(symbol: str, out_path: str, limit: int = settings.default_limit) -> None:
    exchange = CryptoComExchange(settings.cryptocom_api_key, settings.cryptocom_api_secret)
    captured_at = time.time()
    snapshot = {
        "symbol": symbol,
        "source": "crypto.com",
        "captured_at": captured_at,
        "limit": limit,
        "timeframes": {tf: asdict(exchange.fetch_ohlcv(symbol, timeframe=tf, limit=limit)) for tf in TIMEFRAMES},
    }
    with open(out_path, "w") as fh:
        json.dump(snapshot, fh)
    print(f"Wrote {out_path} ({', '.join(f'{tf}={len(snapshot['timeframes'][tf]['closes'])}' for tf in TIMEFRAMES)} candles)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
