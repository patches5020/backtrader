"""
data_loader.py
--------------
Load OHLCV from CSV files into the engine's OHLCV dataclass.

Supported layouts
-----------------
1. TradingView export (typical columns):
     time, open, high, low, close, Volume
   - `time` may be Unix seconds, Unix ms, or ISO-8601 / "yyyy-MM-dd HH:mm"
   - Volume column is often capital-V "Volume"

2. Generic / CCXT-style:
     timestamp, open, high, low, close, volume
   - timestamp in ms or seconds

3. Flexible header matching (case-insensitive, common aliases).

Usage
-----
    from cdcx.backtest.data_loader import load_csv, load_tradingview_csv
    data = load_tradingview_csv("BTCUSDT_1h.csv")
    # then pass `data` to run_single_tf_backtest(...)
"""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from typing import Optional

from cdcx.exchange.cryptocom import OHLCV


# Common header aliases → canonical name
_ALIASES = {
    "time": "timestamp",
    "date": "timestamp",
    "datetime": "timestamp",
    "timestamp": "timestamp",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "vol": "volume",
}


def _canonical_header(name: str) -> Optional[str]:
    key = name.strip().lower().replace(" ", "")
    # TradingView sometimes exports "Volume" with capital V — already lowercased
    return _ALIASES.get(key)


def _parse_time(value: str) -> int:
    """
    Return Unix timestamp in **milliseconds**.
    Accepts: integer seconds, integer ms, ISO-8601, 'yyyy-MM-dd HH:mm[:ss]'.
    """
    value = value.strip().strip('"')
    # pure integer?
    if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
        n = int(value)
        # heuristic: 10-digit ≈ seconds, 13-digit ≈ ms
        if n < 10_000_000_000:  # before ~2286 in seconds
            return n * 1000
        return n

    # try common datetime formats
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
    ):
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue

    # last resort: fromisoformat (handles many ISO variants)
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except ValueError as exc:
        raise ValueError(f"Cannot parse timestamp: {value!r}") from exc


def load_csv(
    path: str,
    *,
    delimiter: Optional[str] = None,
) -> OHLCV:
    """
    Load a CSV file into OHLCV. Headers are matched case-insensitively.
    Requires at least open/high/low/close; volume defaults to 0 if missing;
    timestamp defaults to sequential indices if missing.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"CSV not found: {path}")

    with open(path, newline="", encoding="utf-8-sig") as f:
        sample = f.read(4096)
        f.seek(0)
        if delimiter is None:
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
                delimiter = dialect.delimiter
            except csv.Error:
                delimiter = ","
        reader = csv.DictReader(f, delimiter=delimiter)
        if not reader.fieldnames:
            raise ValueError(f"No header row in {path}")

        # map file columns → canonical
        colmap: dict[str, str] = {}
        for raw in reader.fieldnames:
            canon = _canonical_header(raw)
            if canon and canon not in colmap:
                colmap[canon] = raw

        required = {"open", "high", "low", "close"}
        missing = required - set(colmap)
        if missing:
            raise ValueError(
                f"CSV {path} missing columns {missing}. "
                f"Found headers: {list(reader.fieldnames)}"
            )

        timestamps: list[int] = []
        opens: list[float] = []
        highs: list[float] = []
        lows: list[float] = []
        closes: list[float] = []
        volumes: list[float] = []

        for i, row in enumerate(reader):
            try:
                o = float(row[colmap["open"]])
                h = float(row[colmap["high"]])
                l = float(row[colmap["low"]])
                c = float(row[colmap["close"]])
            except (KeyError, ValueError) as exc:
                raise ValueError(f"Bad OHLC at row {i + 2}: {exc}") from exc

            if "volume" in colmap:
                try:
                    v = float(row[colmap["volume"]] or 0)
                except ValueError:
                    v = 0.0
            else:
                v = 0.0

            if "timestamp" in colmap:
                ts = _parse_time(row[colmap["timestamp"]])
            else:
                ts = i * 3_600_000  # synthetic 1h spacing

            timestamps.append(ts)
            opens.append(o)
            highs.append(h)
            lows.append(l)
            closes.append(c)
            volumes.append(v)

    if not closes:
        raise ValueError(f"No data rows in {path}")

    # ensure chronological order
    order = sorted(range(len(timestamps)), key=lambda i: timestamps[i])
    return OHLCV(
        timestamps=[timestamps[i] for i in order],
        opens=[opens[i] for i in order],
        highs=[highs[i] for i in order],
        lows=[lows[i] for i in order],
        closes=[closes[i] for i in order],
        volumes=[volumes[i] for i in order],
    )


def load_tradingview_csv(path: str) -> OHLCV:
    """
    Convenience alias for TradingView chart exports.

    In TradingView:
      1. Open the chart (correct symbol + timeframe)
      2. Menu → Export chart data…  (or the download icon on some layouts)
      3. Save the CSV
      4. Pass that path here

    Typical headers: time, open, high, low, close, Volume
    """
    return load_csv(path)


def ohlcv_summary(data: OHLCV) -> str:
    n = len(data.closes)
    if n == 0:
        return "Empty OHLCV"
    t0 = datetime.fromtimestamp(data.timestamps[0] / 1000, tz=timezone.utc)
    t1 = datetime.fromtimestamp(data.timestamps[-1] / 1000, tz=timezone.utc)
    return (
        f"{n} bars | {t0.isoformat()} → {t1.isoformat()} | "
        f"close {data.closes[0]:.4g} → {data.closes[-1]:.4g} | "
        f"range [{min(data.lows):.4g}, {max(data.highs):.4g}]"
    )


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m cdcx.backtest.data_loader <file.csv>")
        raise SystemExit(1)
    data = load_csv(sys.argv[1])
    print(ohlcv_summary(data))
    print(f"First close={data.closes[0]}  Last close={data.closes[-1]}")
