# cdcx-cli

AI-assisted trade analysis engine for Crypto.com markets. Combines trend,
momentum, volatility, liquidity, and market-structure signals into a single
weighted score, then generates an entry, ATR-based stop loss, and a
Fibonacci-extension take-profit ladder (TP1-TP4).

## Fixes from the follow-up review

A second review confirmed the regime gate and R:R filter both work
correctly, and found four more real issues. All fixed:

**"AI SCORE = 0.0" was still shown, still misleading.** Removed it as the
headline number. Replaced with **Setup Score** (0-100), a genuinely
meaningful composite: regime validity (30) + direction strength (30) +
R:R quality (20) + market structure agreement (10) + indicator
confirmation breadth (10). `total_score` is kept internally (confluence.py
and entry_checklist.py still use it), just no longer the number the report
leads with.

**"Confidence: 100%" next to "NO TRADE" read as "100% confident this trade
will work."** Relabeled to **Decision Confidence**, shown paired directly
with **Decision** (`STRONG BUY`, `NO TRADE`, etc.) and **Reason** -- same
underlying number, honestly reframed as confidence *in the decision shown*
(including a NO TRADE decision), not confidence a trade will win.

**Range Score alone doesn't mean a range trade should fire.** A ranging
regime with price sitting in the middle of the range looks identical, at
the regime-score level, to one with price at a clean boundary rejection --
but only one of those should ever trade. Every ranging report now shows
an explicit `RangeProfile`: `RANGE HIGH/LOW/MID`, `POC`, `PRICE LOCATION`
(`LOWER EDGE` / `MIDDLE` / `UPPER EDGE`), `EDGE DISTANCE %`, and
`REJECTION` (yes/no + direction) -- visibly distinguishing "Range = 8/10,
price in the middle -> NO TRADE" from "Range = 8/10, price at the upper
edge with a bearish rejection -> SHORT."

**ATR provenance wasn't visible enough to catch a calculation error by
eye.** Every report now shows `Timeframe`, `ATR Timeframe`, `ATR Length`
(17, the shared EMA_LENGTH constant), and an explicit
`Entry / ATR / ATR x mult / Stop Loss` breakdown -- the multiplier x ATR
distance is shown as its own line, not buried inside a single stop-loss
number.

## Fixes from the video review (six real bugs, all now fixed)

A detailed review of a demo caught six genuine problems. Fixed all six:

1. **Regime wasn't an execution gate.** `format_report()` always printed the
   raw indicator `SIGNAL` (e.g. `STRONG SELL`) even when `Market Regime`
   said `NO TRADE (TRANSITION)` -- a real, actively misleading
   contradiction. Fixed: every report now shows a separate
   `EXECUTION SIGNAL` field that force-overrides to `NO TRADE` whenever the
   regime is transitional or R:R doesn't clear 2:1, with a `REASON` line
   explaining why. `SIGNAL`/`total_score` are kept unchanged for backward
   compatibility (confluence.py, entry_checklist.py, and tests all still
   use the 0-100 scale) -- `EXECUTION SIGNAL` is the field that should
   actually drive any real decision, not `SIGNAL`.

2. **"AI SCORE" was actively misleading at the extremes.** A deeply
   bearish setup (every indicator firing negative) clamped `total_score`
   to `0.0` -- visually identical to "no information at all," even though
   nine indicators had just fired. Fixed by decomposing into three
   separate, honest numbers instead of one conflated score:
   `DIRECTION BIAS` (`direction_score`, -100..+100, clamped only in
   magnitude, never floored to 0 -- a strongly bearish setup now correctly
   shows e.g. `-58.0`, not `0.0`), `TRADE QUALITY` (`trade_quality`,
   0-100, breadth of indicator confirmation), and `MARKET REGIME`
   (trend/range, 0-10 each, already existed). `total_score`/`AI SCORE`
   stays as additional context, not the only number shown.

3 & 4. **A trade with bad R:R, or during a transitional regime, still
   looked executable.** Same root cause and fix as #1 -- `EXECUTION SIGNAL`
   now blocks both cases explicitly, with the actual reason stated.

5 & 6. **SL and TP could imply completely different volatility for the
   same trade** (the "72,101 stop" bug) -- traced to the real root cause:
   TP1-4 were computed from `fibonacci.calculate_extension()` using a
   separate historical swing_high/swing_low lookback, totally decoupled
   from the ATR used for the stop-loss. A wide historical swing (e.g. BTC
   having spiked far above current price earlier in the lookback window)
   could produce a TP ladder implying an ATR many times larger than the
   one actually driving the stop -- collapsing TP4 toward the safety floor
   once extension math went negative. **Fixed at the root**: TP1-4 are now
   R-multiples (2.2R / 2.6R / 3.2R / 4.5R) of the *exact same*
   `stop_distance` (`atr * ATR_STOP_MULTIPLIER`) used for the stop loss --
   SL and every TP are now atomic by construction, computed from one ATR
   reading at one instant. There is no longer a code path where they can
   disagree. A `computed_at` timestamp was also added to `TradeSignal` so
   the whole entry/atr/stop/TP block is auditable as one snapshot.

   **One important follow-on catch made during this fix, before shipping
   it**: the first version of this fix reused the original Fibonacci
   extension ratios (1.272/1.414/1.618/2.618) directly as R-multiples.
   Since TP1 = stop_distance * 1.272 and the stop itself = stop_distance *
   1.0, that made R:R *mathematically fixed at exactly 1.272:1 for every
   single trade* -- permanently failing the 2:1 minimum and blocking
   execution forever, on every setup, trending or ranging. Caught via a
   regression test before release; the ratios were rescaled so TP1 clears
   2:1 with real margin (`tests/test_engine_regression.py` locks this in).

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
| Candlestick Patterns         | 10     |
| RSI Momentum               | 12     |
| Fibonacci Retracement      | 12     |
| Fibonacci Extension         | 8      |
| Fair Value Gap              | 15     |
| Fixed Volume Profile        | 10     |
| Anchored Volume Profile     | 10     |
| Market Structure            | 10     |
| Risk/Reward Quality          | 10     |

> **Note:** the original weight table already summed to 120, not 100, before
> ADX, Bollinger Bands, and Candlestick Patterns were added (now 150). The
> engine keeps every weight exactly as specified rather than rescaling, and
> clamps the final total to 100 -- a fully-confirmed setup naturally
> saturates the cap, which is what the original spec's example report
> shows.

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

**Candlestick Patterns** detects single-, two-, and three-candle price-action
patterns on the most recent bar(s): Doji / Dragonfly / Gravestone Doji,
Hammer, Shooting Star, Bullish/Bearish Engulfing, Bullish/Bearish Harami,
Tweezer Top/Bottom, and Morning/Evening Star. Only scores when a detected
pattern aligns with the prevailing trend direction (same convention as
every other indicator here) -- the strongest aligned pattern's score scales
with its signal strength (1-3). Head & Shoulders and Double/Triple
Top/Bottom are not yet covered -- they need multi-swing sequence detection
beyond single-candle shapes, and are a scoped follow-up rather than rushed
into this pass.

## Signal bands

| Score   | Signal      |
|---------|-------------|
| 96-100  | Strong Buy  |
| 80-95   | Buy         |
| 60-79   | Watch       |
| 40-59   | Neutral     |
| 20-39   | Sell        |
| 0-19    | Strong Sell |

Each report also prints a **Confidence** percentage. This is *not* the raw
score -- it's how far the score sits from the neutral midpoint (50), in
either direction: `confidence = |score - 50| * 2`. A Strong Sell (score
near 0) and a Strong Buy (score near 100) both show high confidence
(approaching 100%); a Neutral read (score near 50) shows low confidence
(near 0%). Using the raw score directly used to display "0% confidence"
right next to "SIGNAL: STRONG SELL" for a maximally bearish read -- reading
as "no conviction" when it meant the opposite. Fixed.

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

## Market regime detection (Step 1 of every trade)

**Every `--execute` run now starts here.** Before anything else, the
market is classified as one of three regimes:

| | Trending | Ranging |
|---|---|---|
| ADX > 25 | +2 | |
| ADX < 20 | | +2 |
| EMA(17) slope strong | +2 | |
| EMA(17) slope flat | | +2 |
| Price outside Value Area | +2 | |
| Price oscillating around POC | | +2 |
| ATR expanding | +2 | |
| ATR contracting | | +2 |
| 2+ higher timeframes aligned | +3 | |
| Multiple reversals between S/R | | +3 |

Trend score >= 8 -> 🟢 **TRENDING**. Range score >= 8 -> 🟡 **RANGING**.
Neither reaches 8 -> 🔴 **NO TRADE (TRANSITION)**, regardless of what
confluence or the entry checklist would otherwise say. The regime line
shows on *every* report now, not just `--execute` runs -- that's the
"indicator on your chart" this was meant to provide.

ADX 20-25, an EMA slope that's neither clearly strong nor flat, price
inside the value area but not close to POC, and flat ATR are all
deliberate dead zones (favor neither side) -- otherwise TRANSITIONAL would
be almost unreachable.

### Trending path

Unchanged from before, plus one new guard: if Bollinger Bands reads
"...(Extended)" (price stretched beyond the band), the trade is skipped
with a message to wait for a pullback -- "avoid entering after an extended
move." Still requires the full entry checklist (EMA/ATR, Fibonacci, FVG,
Volume Profile, risk <= 2%, no existing position) and still targets the
1.5x-ATR-stop / Fibonacci-extension TP ladder (TP1-TP4).

### Ranging path (`cdcx/ranging_strategy.py`)

Does **not** require multi-timeframe agreement (per spec: "do not require
all higher timeframes to point in the same direction"). Instead trades the
range boundaries:

- **Long:** price near lower support, RSI < 35 and turning up, a bullish
  rejection candle (reuses `candlestick_patterns.py`), near the lower
  value area.
- **Short:** mirrored at the upper boundary, RSI > 65 turning down,
  bearish rejection.
- **Targets:** TP1 = POC, TP2 = the opposite side of the range -- replaces
  the Fibonacci extension ladder, which assumes directional continuation
  that a ranging market isn't giving you.

### No-trade filter (`cdcx/no_trade_filter.py`, Step 4)

A final gate, checked on both paths: ADX 20-25 dead zone, higher
timeframes disagreeing, risk/reward below 2:1 (a hard cutoff, stricter
than the partial-credit R:R scoring elsewhere), and ATR unusually low
(30%+ below its own recent average). **"Major scheduled news is imminent"
cannot be automated** -- this project has no news/economic-calendar feed.
It's a manual `--news-imminent` flag, not a silent no-op; pass it yourself
when you know the calendar.

### Weighted confidence score (`cdcx/confidence_scoring.py`, Step 5)

Replaces (for the execute flow specifically) a plain % with a score that
requires both timeframe agreement *and* individual indicator confirmation:

| Component | Weight |
|---|---|
| Weekly | 25 |
| Daily | 20 |
| 4H | 15 |
| 1H | 10 |
| EMA/ATR | 10 |
| RSI | 5 |
| ADX | 5 |
| FVG | 5 |
| Volume Profiles | 5 |

90-100 Very Strong · 75-89 Strong · 60-74 Moderate · 40-59 Weak · <40 No
Trade. This is distinct from `engine.py`'s per-signal `confidence` field
(single-timeframe, distance-from-neutral) and from `confluence.py`'s
simpler timeframe-only `confidence_pct` -- both of those are unchanged and
still used where they were before.

```bash
# manually flag imminent news to force a No Trade regardless of everything else
python -m cdcx --symbol BTC/USDT --timeframes 1h,4h,1d,1w --execute --balance 10000 --news-imminent
```

## Structural setup system (cdcx/structure_levels.py, cdcx/structure_strategy.py)

A separate, named-component view of the chart, orthogonal to the
trending/ranging path above -- built around eight chart-analysis
components with fixed display conventions:

| Letter | Component | Display | Backed by |
|---|---|---|---|
| A | POC (Point of Control) | WHITE level | `indicators/volume_profile_fixed.py` (`poc`) |
| B | FVG (Fair Value Gap) | zone | `indicators/fair_value_gap.py` |
| C | Volume High / Resistance | GREEN level | `indicators/volume_profile_fixed.py` (`vah`) |
| D | Volume Low / Support | RED level | `indicators/volume_profile_fixed.py` (`val`) |
| E | Consolidation | market condition | ranging regime + contracting ATR |
| F | Ranging | market condition | `regime.py`'s "ranging" state |
| G | Breakout | price event | `structure_levels.detect_breakout()` |
| H | Retest | price event | `structure_levels.detect_retest()` |

A, C, D, E, and F are names for calculations this project already had
(volume profile, regime detection); G and H are genuinely new -- a
decisive close through a named level, and a controlled return to that
level afterward without re-crossing it.

**Timeframe roles** (1W/1D/4H/1H, distinct from the trending path's
1h/4h/1d/1w confluence check):

| Timeframe | Role |
|---|---|
| 1W | Major structure -- advisory bias: which side of the weekly POC is price on? |
| 1D | Major volume structure -- the POC/resistance/support levels the setup trades against |
| 4H | Primary setup -- where the breakout+retest or FVG+volume confluence is detected |
| 1H | Entry confirmation -- does the fastest timeframe agree, right now? |

1W is advisory, not a hard gate: LONG triggers only fire with price above
the weekly POC, SHORT only below -- lower timeframes aren't blocked by a
neutral weekly read, only by an opposing one.

**Three entry triggers**, evaluated in this order, first match wins:

```
LONG  breakout_retest:  4H closes through the 1D support/low-volume area
                        -> retest holds -> 1H confirms bullish.
LONG  fvg_confluence:   an unfilled bullish 4H FVG sits near the 1D POC
                        or support -> price reacts bullishly -> 1H
                        confirms bullish.
SHORT breakdown_retest: 4H closes through the 1D resistance/high-volume
                        area -> retest holds -> 1H confirms bearish.
```

There's no symmetric bearish FVG-confluence trigger -- that's not an
oversight, it just wasn't part of the spec this was built against, even
though `structure_levels.find_fvg_near_level()` would support one
trivially if it's ever wanted.

`--structure` doesn't run as a separate command, and it doesn't just append a
second report after the first one either -- it **merges into the same
per-timeframe blocks**. If a timeframe you requested (via `--timeframe` or
`--timeframes`) happens to be one of the four structural roles (1w/1d/4h/1h),
that timeframe's STRUCTURE block (POC/resistance/support/condition) prints
immediately after that same timeframe's indicator report -- one block per
timeframe, not two separate systems. Whichever of the four roles wasn't
already covered by what you requested still gets fetched, so the final
LONG/SHORT trigger evaluation (which needs all four) can always run; it's
printed once, at the very end, after the summary table and `--execute` plan:

```bash
# --timeframe 1h is itself one of the four roles ("entry confirmation") --
# its STRUCTURE block merges right into this one report, then 1w/1d/4h are
# fetched just for the final trigger evaluation
python -m cdcx --symbol BTC/USDT --timeframe 1h --structure

# --timeframe 15m isn't one of the four roles -- no merged block for it, but
# the final trigger evaluation still runs (fetching all four itself)
python -m cdcx --symbol BTC/USDT --timeframe 15m --structure

# all four roles requested up front -- every block gets its structure section
# merged in, and the final trigger evaluation reuses those same fetches
# (no redundant re-fetching) instead of hitting the exchange again
python -m cdcx --symbol BTC/USDT --timeframes 1h,4h,1d,1w --execute --balance 10000 --structure
```

```python
from cdcx.structure_levels import compute_structure_map, format_structure_map
from cdcx.structure_strategy import evaluate_structure_setup, format_structure_setup

w1 = compute_structure_map(w1_data.highs, w1_data.lows, w1_data.closes, w1_data.volumes)
d1 = compute_structure_map(d1_data.highs, d1_data.lows, d1_data.closes, d1_data.volumes)
h4 = compute_structure_map(h4_data.highs, h4_data.lows, h4_data.closes, h4_data.volumes)

setup = evaluate_structure_setup(
    w1, d1, h4,
    h4_data.highs, h4_data.lows, h4_data.closes, h4_data.volumes,
    h1_data.highs, h1_data.lows, h1_data.opens, h1_data.closes,
)
print(format_structure_setup(setup))
```

This system still doesn't feed *into* `--execute`'s trading/ranging decision
or `trade_manager.py` -- it's a second, independent read, printed alongside
the main report so you see both together, and left for you to act on
manually (or wire into `--execute`/`--live` yourself, following the same
pattern `_handle_trending_path`/`_handle_ranging_path` use in `cli.py`).

## Predictions market data (cdcx/predictions.py)

A thin client for the public **Crypto.com Predictions Market Data API**
(`data-api.crypto.com` -- a separate product from both the App API and the
Exchange API used elsewhere in this project). Prediction markets are
binary-outcome contracts -- sports, crypto price thresholds, elections,
and similar events -- priced by a live order book: a YES share trading at
`0.63` means the market is pricing that outcome at roughly a 63% chance.

Read-only market data needs **no API key** -- anonymous access is open for
personal, non-commercial use, rate-limited by Crypto.com (not by this
project) to 100 requests/minute and 50,000/day per IP. Set
`PREDICTIONS_API_KEY` in `.env` if you have a licensed Market Data License
(MDLA) key for higher limits; every command below works fine without one.

These are independent, standalone commands -- like `--list-trades` /
`--update-trades` -- not tied to `--symbol`/`--timeframe` and not wired
into `--execute`'s trade decision:

```bash
# list events, optionally filtered by category
python -m cdcx --predictions            # all kinds
python -m cdcx --predictions NFL        # just NFL
python -m cdcx --predictions --predictions-limit 5

# full-text search across events
python -m cdcx --predictions-search "super bowl"

# real-time pricing for one contract -- the implied probability of a
# specific binary outcome
python -m cdcx --predictions-contract BTC-YES
```

```python
from cdcx.predictions import PredictionsClient, format_events, format_contract_price

client = PredictionsClient()  # api_key="" works fine for anonymous access
events = client.list_events(kind="NFL", limit=5)
print(format_events("PREDICTION MARKET EVENTS", events))

price = client.get_contract_price("BTC-YES")
print(format_contract_price(price))
```

> **Schema caveat, flagged rather than silently assumed:** this project's
> sandbox cannot reach `crypto.com` at all (outbound requests to the whole
> domain are blocked in the environment this was built in), so
> `_parse_contract_price` was written defensively against the quickstart
> docs alone rather than a captured real response -- it tries
> `yes_price`/`no_price` first, falls back to treating a lone `last_price`
> as the YES side, and always keeps the full response on
> `ContractPrice.raw` so nothing is lost if the real field names differ.
> `_parse_event`'s `title`/`kind` fields **are** confirmed directly from
> the quickstart's own sample code. Verify `_parse_contract_price` against
> a real response once you can reach the API, and adjust if needed.

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
│   ├── live_execution.py      # real bracket order via the separate cdcx exchange CLI (confirm-gated)
│   ├── regime.py               # Step 1: TRENDING / RANGING / TRANSITIONAL classification
│   ├── ranging_strategy.py     # Step 3: range-boundary entries, POC + opposite-edge targets
│   ├── no_trade_filter.py      # Step 4: final safety gate (RR<2, ATR low, ADX dead zone, news)
│   ├── confidence_scoring.py   # Step 5: weighted timeframe + indicator confidence score
│   │
│   ├── exchange/
│   │   └── cryptocom.py       # CCXT wrapper
│   │
│   ├── indicators/
│   │   ├── atr_ema_variant1.py
│   │   ├── adx.py
│   │   ├── bollinger_bands.py
│   │   ├── candlestick_patterns.py
│   │   ├── rsi.py
│   │   ├── fibonacci.py
│   │   ├── fair_value_gap.py
│   │   ├── volume_profile_fixed.py
│   │   ├── volume_profile_anchor.py
│   │   └── market_structure.py
│   │
│   ├── charts/                # reserved for chart rendering
│   ├── backtest/              # offline backtester (reuses real engine/risk/checklist)
│   │   ├── engine.py          # bar-by-bar single-TF and multi-TF confluence backtests
│   │   ├── execution.py       # market vs TWAP fill/cost modeling
│   │   ├── data_loader.py     # load OHLCV from CSV
│   │   └── synthetic.py       # synthetic multi-regime OHLCV generator
│   ├── structure_levels.py    # POC/FVG/volume levels + breakout & retest detection (A-H)
│   ├── structure_strategy.py  # 1W/1D/4H/1H structural entry combos
│   ├── predictions.py         # Crypto.com Predictions Market Data API client
│   ├── scanner/                 # reserved for multi-symbol scanning
│   └── utils/
│
└── tests/
    ├── test_rsi.py
    ├── test_fibonacci.py
    ├── test_adx.py
    ├── test_bollinger_bands.py
    ├── test_candlestick_patterns.py
    ├── test_confluence.py
    ├── test_entry_checklist.py
    ├── test_risk.py
    ├── test_trade_manager.py
    ├── test_live_execution.py
    ├── test_regime.py
    ├── test_ranging_strategy.py
    ├── test_no_trade_filter.py
    ├── test_confidence_scoring.py
    ├── test_execute_integration.py
    ├── test_engine_regression.py
    ├── test_structure_levels.py
    ├── test_structure_strategy.py
    ├── test_predictions.py
    ├── test_cli_predictions.py
    └── test_cli_structure_combination.py
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
cdcx-ai --symbol ETH/USDT --timeframe 4h
```

> **Important -- do not use the bare `cdcx` command for this project.**
> `cdcx` is the name of the real, official Crypto.com Exchange CLI (the one
> with `cdcx tui`, `cdcx setup`, `cdcx market ticker`, `cdcx mcp`, live
> trading, etc.) -- a completely separate tool from this repo. If both are
> ever installed, whichever one lands later/earlier on your `PATH` wins,
> causing exactly the "unrecognized arguments" confusion this project hit
> before this was renamed. Always use `python -m cdcx` (module invocation)
> or the `cdcx-ai` console script -- never bare `cdcx` -- to guarantee
> you're running this analysis engine and not accidentally colliding with
> the real exchange CLI (or vice versa).

### Multiple timeframes in one command

```bash
python -m cdcx --symbol BTC/USDT --timeframes 1h,4h,1d,1w --limit 200
```

Prints a full report for each timeframe, followed by a combined summary
table (timeframe / score / signal). If one timeframe errors (e.g. not
enough candles at `--limit`), the rest still run and the table shows
`ERROR` for that row.

## Live execution (real money -- read this fully before using)

**`--live` sends a real bracket order to your actual exchange account** via
the separately-installed, official Crypto.com Exchange CLI (`cdcx` on your
PATH -- a different program from this repo's `python -m cdcx`; see the
naming-collision note above). Everything else in this project stays
paper-only unless you explicitly add `--live`.

### What it does

1. Runs the exact same confluence check + entry checklist as the paper
   flow. `--live` has zero effect unless a paper trade would have opened
   anyway -- it never bypasses those gates.
2. Builds the real order as a `create-otoco` bracket (verified against the
   live `private/advanced/create-otoco` schema): one MARKET entry, one
   STOP_LOSS trigger at the 1.5x-ATR stop, one TAKE_PROFIT trigger at TP1.
3. Runs `cdcx advanced create-otoco --dry-run '<order_list>'` first,
   unconditionally, and shows you the full order JSON and the dry-run
   response before anything else happens.
4. Asks you to type exactly `YES` (all caps) to proceed. Anything else
   cancels. This is a second, independent gate from the real CLI's own
   confirmation prompt (`--yes` is never passed to it).
5. Only after your `YES` does it run the same command again without
   `--dry-run`.

### What it does NOT do

- **Does not set leverage.** `create-otoco`'s schema has no leverage field
  -- set it on your account first with `cdcx trade leverage` if you're
  trading margin/perpetuals with leverage other than the account default.
- **Does not confirm the instrument name is real.** `--symbol BTC/USDT`
  gets turned into `BTCUSD-PERP` by a simple rule (strip the quote
  currency, append `USD-PERP`) -- verified correct for BTC/USDT via a live
  `--dry-run`, not confirmed for every pair. It's always printed before you
  confirm; use `--instrument-name` to override it if the real listing for
  your pair differs.
- **Does not trail the stop through TP2-TP4.** A bracket order is exactly
  3 orders (entry + 1 stop + 1 target) -- once TP1 fills, you'll need to
  place a new bracket manually for the remainder of the position with the
  stop moved to TP1, and so on. This is a known gap, not an oversight;
  automating it safely needs more testing against a real account before
  it's wired in.
- **Does not run unattended.** There is no scheduler, no loop, no
  auto-retry. You run the command, you review the dry-run, you type `YES`,
  once.

### Usage

```bash
python -m cdcx --symbol BTC/USDT --timeframes 1h,4h,1d,1w --execute --balance 10000 --live
python -m cdcx --symbol ETH/USDT --timeframes 1h,4h,1d,1w --execute --balance 10000 --live --instrument-name ETHUSD-PERP
```

## Backtesting (cdcx/backtest/)

An offline backtester that reuses the *exact same* indicator scoring, entry
checklist, risk sizing, and trade-manager trailing rules as live analysis --
walked bar-by-bar over historical or synthetic OHLCV, with fees, fixed
slippage, and size-dependent market impact (square-root law vs average
volume) modeled per fill.

```bash
python -m cdcx.backtest
```

Runs a synthetic-data demo (single-timeframe with/without the entry
checklist, plus a multi-timeframe confluence backtest) and prints a full
report: return, drawdown, win rate, profit factor, expectancy, and a
market-vs-TWAP execution cost comparison.

```python
from cdcx.backtest.synthetic import generate_ohlcv
from cdcx.backtest.data_loader import load_csv
from cdcx.backtest.engine import run_single_tf_backtest, run_confluence_backtest, format_backtest_report

# synthetic data, or load your own CSV:
data = generate_ohlcv(n_bars=1500, start_price=62000.0, seed=42, timeframe="1h")
# data = load_csv("BTCUSDT_1h.csv")

result = run_single_tf_backtest(data, symbol="BTC/USDT", timeframe="1h", initial_balance=10_000.0)
print(format_backtest_report(result))
```

**No network, no live orders** -- this only ever consumes OHLCV you already
have (synthetic or CSV). It never calls the exchange. Treat results as
"does the backtesting machinery work," not "does this strategy have a live
edge" -- synthetic regimes are simplified, and even real historical data
doesn't guarantee future performance.

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
