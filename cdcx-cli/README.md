# cdcx-cli

Command-line toolkit that connects to the Crypto.com Exchange public REST API
and runs the **ATR_EMA_VARIANT1** indicator (a Python port of the
`EMA+ ATR Support Resistance Take Profit signal` Pine Script) over live or
historical candles, with backtesting, scanning, and charting on top.

```
cdcx-cli/
├── api/                  Crypto.com Exchange REST client
│   └── cryptocom.py
├── indicators/           Technical indicators
│   ├── ema.py
│   ├── atr.py
│   ├── support_resistance.py
│   ├── atr_ema_variant1.py
│   ├── fibonacci.py
│   ├── fixed_volume_profile.py
│   ├── anchored_volume_profile.py
│   ├── fair_value_gap.py
│   ├── order_blocks.py
│   └── liquidity.py
├── strategy/             backtrader Strategy built on ATR_EMA_VARIANT1
│   └── atr_ema_variant1_strategy.py
├── backtest/             backtrader Cerebro runner
│   └── run_backtest.py
├── scanner/              Multi-symbol support/resistance scanner
│   └── sr_scanner.py
├── charts/               Matplotlib chart matching the Pine Script plots
│   └── atr_ema_variant1_chart.py
├── tests/                Unit tests (pandas indicator math + API parsing)
├── cli.py                Entry point (run / scan / backtest / chart)
└── requirements.txt
```

## Indicator coverage

`ema.py`, `atr.py`, `support_resistance.py`, and `atr_ema_variant1.py` are
full ports of the Pine Script logic (EMA, Wilder ATR/RMA, EMA±ATR bands, and
support/resistance "hit" detection), each shipped as both a plain
pandas/numpy function (for the scanner and CLI, no backtrader needed) and a
`backtrader.Indicator` (for `strategy/` and `backtest/`).

`fibonacci.py`, `fixed_volume_profile.py`, `anchored_volume_profile.py`,
`fair_value_gap.py`, `order_blocks.py`, and `liquidity.py` are first-pass
(v1) pandas implementations of the related concepts referenced in the
flowchart. They're functional but intentionally simpler than the core
ATR/EMA indicator — good building blocks, not final production logic.

## Usage

```bash
pip install -r requirements.txt

# fetch candles + run ATR_EMA_VARIANT1, print the latest support/resistance hit
python cli.py run --instrument BTC_USDT --timeframe 1h --count 200

# render a chart mirroring the Pine Script plots (EMA, support, resistance, hits)
python cli.py chart --instrument BTC_USDT --timeframe 1h --count 200 --output chart.png

# scan multiple instruments for a fresh support/resistance touch
python cli.py scan --instruments BTC_USDT,ETH_USDT,SOL_USDT --timeframe 1h

# backtest the ATR_EMA_VARIANT1 strategy with backtrader's Cerebro engine
python cli.py backtest --instrument BTC_USDT --timeframe 1h --count 500 --cash 10000
```

## Notes

- The Crypto.com Exchange public REST API (`https://api.crypto.com/exchange/v1/public/...`)
  requires no API key for market data. `api/cryptocom.py` only calls public
  endpoints (candlesticks, tickers, order book, instruments) — no order
  placement/trading.
- This client was built against the documented v1 REST response shape and
  parses both the abbreviated (`o/h/l/c/v/t`) and verbose
  (`open/high/low/close/volume/timestamp`) field-name variants defensively,
  since it could not be smoke-tested against the live API from the
  environment this was written in (outbound access to `api.crypto.com` was
  blocked). Run `python cli.py run ...` once against the real API in your own
  environment to confirm connectivity before relying on it.
