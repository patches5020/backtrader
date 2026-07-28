# cdcx-cli

AI-assisted trade analysis engine for Crypto.com markets. Combines trend,
momentum, volatility, liquidity, and market-structure signals into a single
weighted score, then generates an entry, ATR-based stop loss, and a
Fibonacci-extension take-profit ladder (TP1-TP4).

## Flow

```
Download OHLCV (Crypto.com CCXT)
        |
Calculate EMA(17) + ATR(11)
        |
Calculate Dynamic Support/Resistance
        |
Calculate ADX(17) + DI+/DI- (aligned to EMA(17))
        |
Calculate Bollinger Bands (SMA 17, +/-2 stddev, aligned to EMA(17))
        |
Calculate RSI(17) (aligned to EMA(17))
        |
Detect Market Trend (EMA + HH/LL)
        |
Build Trend Fibonacci Retracement
        |
Calculate Fibonacci Extension Levels (1.272 / 1.414 / 1.618 / 2.618)
        |
Detect Fair Value Gaps (FVG)
        |
Calculate Fixed Volume Profile
        |
Calculate Anchored Volume Profile -> POC / VAH / VAL
        |
Market Structure Detection (HH HL LH LL, Break of Structure)
        |
Generate Individual Scores
        |
AI Weighted Score Engine
        |
Generate Trade Signal (Strong Buy / Buy / Watch / Neutral / Sell / Strong Sell)
        |
Calculate Stop Loss (ATR based)
        |
Calculate Take Profit Targets (TP1-TP4)
        |
Print Final Report
```

## Indicator weights

| Indicator                | Weight |
|---------------------------|--------|
| EMA Trend                 | 15     |
| ATR Expansion              | 8      |
| ADX Trend Strength           | 10     |
| Bollinger Bands              | 10     |
| RSI Momentum               | 12     |
| Fibonacci Retracement      | 12     |
| Fibonacci Extension         | 8      |
| Fair Value Gap              | 15     |
| Fixed Volume Profile        | 10     |
| Anchored Volume Profile     | 10     |
| Market Structure            | 10     |
| Risk/Reward Quality          | 10     |

> **Note:** the original weight table already summed to 120, not 100, before
> ADX and Bollinger Bands were added (now 140). The engine keeps every
> weight exactly as specified rather than rescaling, and clamps the final
> total to 100 -- a fully-confirmed setup naturally saturates the cap, which
> is what the original spec's example report shows.

> **Period alignment:** RSI, ADX, and Bollinger Bands all default to a
> 17-period lookback -- imported directly from `atr_ema_variant1.EMA_LENGTH`
> rather than each hardcoding its own conventional period (RSI 14, ADX 14,
> Bollinger SMA 20). This keeps every smoothed/lookback indicator running on
> the same period as the primary EMA trend read; change `EMA_LENGTH` in
> `atr_ema_variant1.py` and all three follow automatically. `ATR_LENGTH`
> (11) is left as its own distinct setting, unchanged from the original
> Pine Script.

**ADX** (Average Directional Index, period 17) measures trend *strength*,
independent of direction. It's paired with +DI/-DI to confirm which side is
driving that strength, and cross-checked against the EMA-detected trend:

- ADX ≥ 25 with the dominant DI line agreeing with the trend → full weight
- ADX 20-24 (developing trend) → half weight
- ADX < 20, or a strong ADX with DI/trend disagreement → 0 (chop or warning sign)

**Bollinger Bands** (SMA 17, ±2 standard deviations) checks where price
sits relative to its recent volatility envelope (%B), and rewards price
riding the band in the direction of the trend -- a classic continuation
signal -- while reducing credit once price is stretched beyond the band
(mean-reversion risk rising) or sitting on the wrong side of the mean for
the stated trend:

- Bullish trend, %B between 0.5-1.0 (upper half to upper band) → full weight
- Bullish trend, %B > 1.0 (beyond the upper band) → half weight (extended)
- Bullish trend, %B < 0.2 (well below the mean) → 0 (thesis weak)
- Mirrored for bearish trend on the lower band

## Signal bands

| Score   | Signal      |
|---------|-------------|
| 96-100  | Strong Buy  |
| 80-95   | Buy         |
| 60-79   | Watch       |
| 40-59   | Neutral     |
| 20-39   | Sell        |
| 0-19    | Strong Sell |

## Multi-timeframe confluence execution & money management

**This is a paper-planning and paper-tracking system only.** There is no
live broker/order-routing connection in this project -- `--execute` never
places a real order. It computes a fully sized trade plan and writes it to
a local JSON file (`cdcx_trades.json`), which `--update-trades` then
re-checks against fresh prices to apply trailing-stop rules. Review every
plan yourself before acting on it with real capital.

### Confluence (cdcx/confluence.py)

Restricted to exactly four timeframes: **1H, 4H, 1D, 1W**. A trade is only
considered when 2 or more of these four agree on direction (bullish or
bearish) -- any other timeframe passed via `--timeframes` is ignored for
this specific decision (it still shows in the plain multi-timeframe
report). Higher timeframes count for more via a percentage confidence
score:

| Timeframe | Confidence weight |
|-----------|--------------------|
| 1H        | 10%                |
| 4H        | 20%                |
| 1D        | 30%                |
| 1W        | 40%                |

Confidence tiers (symmetric both directions):

| Confidence  | Tier                            |
|-------------|----------------------------------|
| >= 70%      | Strong Buy / Strong Sell          |
| 50% - 69%   | Buy / Sell                        |
| 30% - 49%   | Buy (Lower Confidence) / Sell (Lower Confidence) |

A 2-vs-2 tie is reported as **WATCH** (flagged, no trade). Fewer than 2 of
the four agreeing is **NO TRADE**.

> **Known spec inconsistency, flagged rather than silently resolved:** an
> illustrative example (1H bullish, 4H/1D/1W bearish) computes to 90%
> bearish confidence under this formula -- which lands in the Strong Sell
> tier, not "Sell" as a separate hand-labeled example table suggested for
> that exact row. This implementation treats the percentage formula as the
> single source of truth. Say so if you want asymmetric, table-matched
> tiers instead.

### Entry checklist (cdcx/entry_checklist.py)

Confluence alone only says the *blended* score qualifies. Before actually
opening a paper trade, every one of these must **individually** confirm
the same direction on the entry timeframe (a neutral/zero reading does
NOT count as confirming):

- ATR/EMA trend (`atr_ema_variant1`)
- Fibonacci retracement (an actual bounce/rejection, not just "no
  contradiction")
- Fair Value Gap
- Volume Profile -- fixed OR anchored, either counts
- Risk per trade <= 2% of account equity
- No existing open position on the same symbol

All must pass, or no trade is planned -- printed as a PASS/FAIL checklist
either way.

### Money management (cdcx/risk.py)

- Stop loss = entry price -/+ **1.5x ATR** (long: below; short: above) --
  the "ATR magic number."
- Position size = risk_amount / stop_distance, where risk_amount = account
  balance x risk% (default 2%, override with `--risk-pct`, capped at 2% by
  the entry checklist). This sizes the trade so that hitting the stop loses
  exactly the planned risk amount, never more by design.
- Never more than one open trade per currency pair at a time (see rule C
  below) -- which is also how "never risk more than 2% on the same pair
  at once" is enforced, since each open trade already carries exactly the
  per-trade risk cap.

### Trade management / trailing rules (cdcx/trade_manager.py)

- **C.** Only the first entry per symbol is taken -- opening a second trade
  on a symbol that already has one open is refused outright (no
  pyramiding).
- **G.** When TP1 is reached, the stop moves to breakeven (entry price).
- **H.** Each subsequent TP reached moves the stop to the *previous* TP
  level, ratcheting all the way through TP4, which closes the trade
  outright.
- **I.** If price gives back from TP1 toward breakeven, the trade closes
  early at a level 20% of the way from breakeven towards TP1 (rather than
  riding all the way back down to the breakeven stop) -- a tighter
  protective exit. This interpretation of "20% above breakeven" is
  anchored to the breakeven-to-TP1 distance; flag it if a different
  anchor was intended.
- **J.** Planned max loss per trade is 2% (enforced by sizing above). If an
  actual close realizes a larger loss than planned -- e.g. price gaps past
  the stop in fast-moving conditions rather than filling exactly there --
  the realized P&L is recorded honestly (not assumed-to-match-plan), and a
  warning is raised if the realized loss exceeds a 5% ceiling. This is an
  honest-accounting safeguard, not a guarantee -- nothing here can force a
  real fill at the stop price without a live broker connection.

### Commands

```bash
# Check confluence + entry checklist and open a paper trade if everything qualifies
python -m cdcx --symbol BTC/USDT --timeframes 1h,4h,1d,1w --limit 200 --execute --balance 10000

# override risk % per trade (must stay <= 2.0 to pass the checklist)
python -m cdcx --symbol BTC/USDT --timeframes 1h,4h,1d,1w --execute --balance 10000 --risk-pct 1.5

# re-check open paper trades against fresh prices, apply trailing-stop rules
python -m cdcx --update-trades

# view current paper trade state without fetching new prices
python -m cdcx --list-trades
```

## Project layout

```
cdcx-cli/
├── pyproject.toml
├── requirements.txt
├── README.md
├── .env.example
│
├── cdcx/
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── engine.py              # central AI weighted scoring engine
│   ├── confluence.py          # multi-timeframe (1h/4h/1d/1w) confluence check
│   ├── entry_checklist.py     # per-component confirmation gate before opening a trade
│   ├── risk.py                # 1.5x ATR stop + 2% account-risk position sizing
│   ├── trade_manager.py       # local paper-trade lifecycle: TP ladder trailing, give-back exit
│   │
│   ├── exchange/
│   │   └── cryptocom.py       # CCXT wrapper
│   │
│   ├── indicators/
│   │   ├── atr_ema_variant1.py
│   │   ├── adx.py
│   │   ├── bollinger_bands.py
│   │   ├── rsi.py
│   │   ├── fibonacci.py
│   │   ├── fair_value_gap.py
│   │   ├── volume_profile_fixed.py
│   │   ├── volume_profile_anchor.py
│   │   └── market_structure.py
│   │
│   ├── charts/                # reserved for chart rendering
│   ├── backtest/               # reserved for backtesting
│   ├── scanner/                 # reserved for multi-symbol scanning
│   └── utils/
│
└── tests/
    ├── test_rsi.py
    ├── test_fibonacci.py
    ├── test_adx.py
    ├── test_bollinger_bands.py
    ├── test_confluence.py
    ├── test_entry_checklist.py
    ├── test_risk.py
    └── test_trade_manager.py
```

## Using as a Claude Code plugin

This repo doubles as a Claude Code plugin marketplace and plugin (see
`.claude-plugin/marketplace.json` and `.claude-plugin/plugin.json`). Once
this repo is pushed to `crypto-com/cdcx-cli` on GitHub:

```
claude plugin marketplace add crypto-com/cdcx-cli
claude plugin install cdcx-cli@cdcx-cli
```

This installs a `/cdcx-analyze [symbol] [timeframe] [limit]` slash command
inside Claude Code that runs the engine and summarizes the result, e.g.:

```
/cdcx-analyze BTC/USDT 1h 200
```

### Bundled MCP server registration

`.mcp.json` at the plugin root registers a separate, more full-featured
`cdcx mcp` server (exposing `market`, `account`, `trade`, `margin`,
`staking`, `funding`, `fiat`, `otc`, `bot`, and `stream` tools) so it's
picked up automatically alongside the plugin, instead of needing to be run
manually in a terminal.

```json
{
  "mcpServers": {
    "cdcx": {
      "command": "cdcx",
      "args": ["mcp"],
      "env": {
        "CRYPTOCOM_API_KEY": "${CRYPTOCOM_API_KEY}",
        "CRYPTOCOM_API_SECRET": "${CRYPTOCOM_API_SECRET}"
      }
    }
  }
}
```

This assumes the `cdcx` binary is already installed and on `PATH` wherever
Claude Code runs (`which cdcx` to confirm) -- this is a separate,
pre-existing authenticated trading tool, distinct from this repo's own
`python -m cdcx` analysis engine. If `cdcx` isn't on `PATH`, replace
`"command": "cdcx"` with the full binary path. Set
`CRYPTOCOM_API_KEY`/`CRYPTOCOM_API_SECRET` as real environment variables
before launching Claude Code (or hardcode them here, though env vars are
safer) -- check that tool's own docs for any additional required variables.

To test locally before pushing to GitHub, point at the local folder instead:

```
claude plugin marketplace add /path/to/cdcx-cli
claude plugin install cdcx-cli@cdcx-cli
```

> **Note:** the Claude Code plugin/marketplace manifest format is a newer,
> evolving part of Claude Code. The `plugin.json` / `marketplace.json` files
> here are built from best available knowledge but weren't validated against
> live documentation. If `claude plugin install` reports a schema error,
> check https://docs.claude.com/en/docs/claude-code/plugins for the current
> manifest spec and adjust these two files accordingly.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
```

## Usage

```bash
python -m cdcx --symbol BTC/USDT --timeframe 1h --limit 200
```

or, after installing the package (`pip install -e .`):

```bash
cdcx --symbol ETH/USDT --timeframe 4h
```

### Multiple timeframes in one command

```bash
python -m cdcx --symbol BTC/USDT --timeframes 1h,4h,1d,1w --limit 200
```

Prints a full report for each timeframe, followed by a combined summary
table (timeframe / score / signal). If one timeframe errors (e.g. not
enough candles at `--limit`), the rest still run and the table shows
`ERROR` for that row.

## Tests

```bash
pytest
```

`rsi.py`, `fibonacci.py`, `adx.py`, and `bollinger_bands.py` are fully
covered since they're pure functions of price data, as are `confluence.py`,
`entry_checklist.py`, `risk.py`, and `trade_manager.py` (the latter two use
a `tmp_path`-isolated trade-state file per test, so they never touch a real
`cdcx_trades.json`). The remaining indicator modules (`atr_ema_variant1.py`,
`fair_value_gap.py`, `volume_profile_fixed.py`, `volume_profile_anchor.py`,
`market_structure.py`) and `engine.py` include runnable smoke tests under
their `if __name__ == "__main__":` blocks -- run them directly, e.g.
`python -m cdcx.indicators.fair_value_gap`, to sanity-check on synthetic
data. Add dedicated pytest coverage for these as you tune their thresholds
against real market data.
