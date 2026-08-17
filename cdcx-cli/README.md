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
│   ├── regime.py         Wilder ADX trend/range classifier
│   ├── fibonacci.py
│   ├── fixed_volume_profile.py
│   ├── anchored_volume_profile.py
│   ├── fair_value_gap.py
│   ├── order_blocks.py
│   └── liquidity.py
├── strategy/             backtrader Strategies
│   ├── atr_ema_variant1_strategy.py
│   └── trend_range_strategy.py   regime-adaptive entries + ATR SL/TP/R:R
├── backtest/             backtrader Cerebro runners
│   └── run_backtest.py
├── scanner/              Multi-symbol support/resistance scanner
│   └── sr_scanner.py
├── charts/               Matplotlib chart matching the Pine Script plots
│   └── atr_ema_variant1_chart.py
├── integrations/         Third-party integrations
│   └── tvremix_mcp.py    tvremix.ai MCP (Model Context Protocol) client
├── tests/                Unit tests (pandas indicator math + API parsing)
├── cli.py                Entry point (run / scan / backtest / chart / mcp)
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

`regime.py` is a Wilder ADX port (`plus_di`/`minus_di`/`adx`) used to label
each bar as **trending** (`adx >= trend_threshold`, default `25`) or
**ranging** (`adx < trend_threshold`), same pandas-fn + `backtrader.Indicator`
split as the other indicators.

## Strategies

- **`atr_ema_variant1_strategy.ATREMAVariant1Strategy`** — the original
  strategy: buy on a support-band touch, close on a resistance-band touch.

- **`trend_range_strategy.TrendRangeStrategy`** — a regime-adaptive strategy
  that reuses the same EMA/ATR support-resistance bands and adds an ADX
  regime filter, an ATR-based stop-loss, and a fixed risk-to-reward
  take-profit:

  | Market regime (ADX)          | Entry                                              |
  |-------------------------------|-----------------------------------------------------|
  | Trending (`adx >= threshold`) | Breakout above the resistance band while `close > ema` (trend continuation) |
  | Ranging (`adx < threshold`)   | Touch of the support band (mean reversion), same trigger as the base strategy |

  Every entry is submitted as a single OCO bracket order
  (`Strategy.buy_bracket`) so risk is fixed at order time:

  - `stop_loss   = entry - atr * atr_sl_mult`
  - `take_profit = entry + (entry - stop_loss) * risk_reward`
  - position size is chosen so a stop-out risks exactly `risk_pct`% of
    account equity (risk-based position sizing), never more than cash on
    hand allows.

## tvremix.ai integration

`integrations/tvremix_mcp.py` is a client for tvremix.ai's ("TradingView
Remix: AI Chart Copilot") MCP server at `https://tvremix.xyz/api/mcp/v1`.
MCP (Model Context Protocol) is a JSON-RPC 2.0 protocol, not a plain REST
API, so `MCPClient` handles the `initialize` handshake, session-id header,
and `tools/list`/`tools/call` calls per the spec's Streamable HTTP
transport — the CLI then exposes whatever tools the server reports rather
than hard-coding a specific tool contract:

```bash
# discover what tvremix.ai exposes
python cli.py mcp list-tools

# call a specific tool with JSON arguments
python cli.py mcp call --tool chart_analyze --args '{"symbol": "BTCUSD"}'

# point at a different endpoint / pass an API key, if the server requires one
python cli.py mcp list-tools --url https://tvremix.xyz/api/mcp/v1 --api-key "$TVREMIX_API_KEY"
# ...or via env vars: TVREMIX_MCP_URL, TVREMIX_API_KEY
```

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

# backtest the regime-adaptive strategy: trend breakouts + range mean-reversion,
# ATR stop-loss/take-profit sized to a 1:2 risk-to-reward ratio, 1% equity risk/trade
python cli.py trend-range --instrument BTC_USDT --timeframe 1h --count 500 \
    --risk-reward 2.0 --atr-sl-mult 1.5 --risk-pct 1.0
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
- Same caveat for `integrations/tvremix_mcp.py`: outbound access to
  `tvremix.xyz` was blocked from the environment this was written in, so
  the client is built strictly against the public MCP spec and unit-tested
  against a fake transport, not the live server. It has not been confirmed
  to work against the real endpoint, and whether it requires an API key at
  all is unknown. Run `python cli.py mcp list-tools` once in your own
  environment first — to confirm connectivity/auth and see the real tool
  names/schemas — before calling `mcp call` against it.
