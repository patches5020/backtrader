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

## Fixes from live XRP/USD testing

**Low-priced assets could get a broken TP ladder.** `stop_loss`/
`take_profits` used to round to a flat 2 decimal places regardless of the
asset's price -- harmless for BTC (~$65,000), but confirmed live on
XRP/USD (~$1): raw TP1-4 R-multiple targets `0.991702 / 0.989975 /
0.987384 / 0.981772` all rounded to `0.99 / 0.99 / 0.99 / 0.98` -- three of
four TP levels became the identical price, and the rounding was coarse
enough it could even land TP4 on the wrong side of TP1-3, breaking
`trade_manager.py`'s "TP levels are ordered" invariant it relies on to
process consecutive TP hits correctly. Fixed with `engine._round_price()`:
rounds to 6 *significant figures* instead of a flat decimal count, scaling
precision to the asset's own price magnitude -- XRP's ladder now stays
fully distinct and correctly ordered (`0.991702 / 0.989975 / 0.987384 /
0.981772`, no collapsing), while BTC still prints cleanly
(`stop_loss=63416.8`, one decimal). `tests/test_engine_regression.py` locks
this in with both a synthetic low-priced-asset regression test and direct
`_round_price()` unit tests.

**A short backtest window crashed outright, and the P&L for any multi-leg
trade was silently wrong.** Found running a "just the past week" (168 1h
bars) backtest -- rare for a 1000-bar run to end with a trade still open,
routine for a 7-day one. Two distinct bugs, both in `cdcx/backtest/engine.py`:

1. The force-close-at-end-of-window code still imported
   `trade_manager._close_trade`, a name that no longer existed --
   renamed to `_close_size` when `trade_manager.py` was reworked for
   partial closes (see "Trade management / trailing rules" above). Any
   window ending with a trade still open raised `ImportError` and crashed
   the whole backtest.
2. Even after fixing the import, every fully-closed trade's cost/P&L was
   computed via `apply_trade_costs()` **once**, against the trade's full
   original `position_size` and only the *final* exit price -- silently
   wrong for any trade that partially closed at TP1-3 (each at its own,
   different price) before finally closing. A trade that took 25% off at
   TP1, TP2, TP3 and the rest at TP4 was being priced as if the *entire*
   position rode straight from entry to the TP4 price alone.

Fixed with `apply_trade_costs_over_partial_closes()`: sums cost/P&L per
actual exit slice (`trade_manager.Trade.partial_closes` -- one entry per
TP-triggered partial close plus the final close, each with its own price
and size). Fee/slippage are linear in size so summing per-slice costs
equals one full-size cost (no double-charging); market impact (sqrt-law) is
if anything *more* realistic computed per-slice, since executing in
tranches really does cost less cumulative impact than dumping the full
size at once. `tests/test_backtest_partial_close_costs.py` locks in both
fixes -- including a case proving the old single-leg calculation and the
new multi-leg one give genuinely different numbers, not just a formatting
change.

**`--tp-mode structural` could offer a floored Fibonacci-extension artifact
as a real TP.** Found testing XRP/USD's 1w timeframe right after
structural TP mode shipped: `fibonacci.calculate_extension()`'s own
"never return <= 0" safety clamp (see its docstring -- it floors a "down"
direction level at `swing_low * 0.01` whenever the raw projection goes
negative, which is routine once the swing range exceeds ~38% of
swing_high) was being fed straight through as a structural TP candidate.
On a real, wide `swing_high=3.19 / swing_low=0.99` weekly range, the
1.618/2.618 extension rungs floored to `$0.0079`/`$0.0069` -- essentially
zero, more than 99% below entry -- and got selected as TP3/TP4 simply
because they were technically "ahead of price." Fixed two ways: (1) at the
source, `engine.py`'s `_real_down_extension_levels()` recomputes each
rung's raw (unfloored) value and excludes any that hit the clamp, so a
floored artifact is never offered as a candidate at all; (2) as a
source-agnostic backstop, `risk.build_structural_tp_levels()` gained a
`max_r_multiple` cap (default 50R) alongside its existing `min_r_multiple`
floor, so a future degenerate value from *any* indicator can't sneak
through either. `tests/test_structural_tp.py` locks in both.

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

- Stop loss = entry price -/+ **ATR x multiplier** (long: below; short:
  above) -- the multiplier defaults to 1.5x ("the ATR magic number"), but is
  now resolved per-symbol; see "Per-symbol ATR multiplier" below.
- Position size = risk_amount / stop_distance, where risk_amount = account
  balance x risk% (default 2%, override with `--risk-pct`, capped at 2% by
  the entry checklist). This sizes the trade so that hitting the stop loses
  exactly the planned risk amount, never more by design.
- Never more than one open trade per currency pair at a time (see rule C
  below) -- which is also how "never risk more than 2% on the same pair
  at once" is enforced, since each open trade already carries exactly the
  per-trade risk cap.

### Per-symbol ATR multiplier (cdcx/risk.py's resolve_atr_multiplier)

The "1.5x ATR" stop distance isn't actually one flat number for every
symbol anymore -- `resolve_atr_multiplier(symbol, override)` resolves it in
priority order:

1. An explicit override (`--atr-multiplier` on the CLI, or
   `atr_multiplier_override=` on `engine.analyze`/`analyze_ohlcv`,
   `risk.build_position_plan`, or either offline backtest function) --
   always wins.
2. A per-symbol default from `ATR_MULTIPLIER_OVERRIDES` in `.env`, keyed by
   BASE currency (`"BTC"` matches `BTC/USDT`, `BTC/USD`, etc.) -- ships
   pre-configured with `BTC:1.5,XRP:1.5`.
3. `ATR_STOP_MULTIPLIER` -- the flat global fallback (1.5x) for any base
   currency not listed in (2).

A real 1000-bar 1h backtest sweep (regime-gated + circuit-breaker-on,
1.0x-3.0x) found a genuine, per-instrument optimum -- not guessed:

| Multiplier | BTC/USD | XRP/USD | XRP/USDT | ETH/USD |
|---|---|---|---|---|
| 1.0x | -11.19% / 11.19% DD | **+15.11%** / 10.35% DD | **+17.09%** / 9.03% DD | **+27.38%** / 9.18% DD |
| **1.5x** | **+19.71%** / 9.27% DD | +2.91% / 11.00% DD | +4.75% / 9.86% DD | +0.69% / 13.69% DD |
| 2.0x | +9.20% / 8.46% DD | -8.64% / 9.57% DD | -1.70% / 10.06% DD | +13.75% / 6.71% DD |
| 2.5x | -3.73% / 8.70% DD | -5.69% / 7.90% DD | +6.05% / 6.45% DD | +0.34% / 8.18% DD |
| 3.0x | -5.48% / 6.88% DD | -0.50% / 5.19% DD | +9.18% / 3.40% DD | +1.66% / 7.23% DD |

**BTC prefers the 1.5x default; every altcoin tested (XRP on both quote
pairs, ETH) had a *backtested* edge at a tighter 1.0x instead** -- not a
smooth curve anywhere (XRP/USDT dips at 2.0x then recovers by 3.0x), so
this isn't "tighter is always better," it's genuinely per-instrument.

**XRP's default was deliberately set to 1.5x anyway, at the user's
request** -- trading the backtested edge above for one consistent
multiplier across both actively-traded symbols (BTC and XRP). The evidence
table stays here so that tradeoff is visible, not silently lost; revert to
`XRP:1.0` in `.env` (or pass `--atr-multiplier 1.0` per-run) if you want
the backtested-optimal setting back.

```bash
# XRP now resolves to 1.5x by default too (same as BTC) -- no flag needed
python -m cdcx --symbol XRP/USDT --timeframes 1h,4h,1d,1w --execute --balance 10000

# force a specific multiplier for one run, any symbol (always wins over the table)
python -m cdcx --symbol XRP/USDT --timeframes 1h,4h,1d,1w --execute --balance 10000 --atr-multiplier 1.0

# revert XRP to its backtested optimum permanently, or add ETH, in .env
# ATR_MULTIPLIER_OVERRIDES=BTC:1.5,XRP:1.0,ETH:1.0
```

`engine.TradeSignal.atr_multiplier` and `risk.PositionPlan.atr_multiplier`
both carry the actual resolved value used for that specific signal/plan --
the report and the real trade plan can never disagree, by construction
(same invariant as the original SL/TP-must-share-one-ATR-reading fix).

### TP ratios & partial-close percentages -- selectable at input

Neither the TP1-4 R-multiples nor how much of the position closes at each
one are hardcoded:

```bash
# custom TP ladder (R-multiples of stop_distance) for one run
python -m cdcx --symbol BTC/USDT --timeframes 1h,4h,1d,1w --execute --balance 10000 --tp-ratios "2,3,4,5"

# custom scale-out -- 50% at TP1, 25% at TP2, 25% at TP3, TP4 always closes the rest
python -m cdcx --symbol BTC/USDT --timeframes 1h,4h,1d,1w --execute --balance 10000 --tp-close-pcts "50,25,25,0"

# make either permanent in .env
# TP_RATIOS=2.2,2.6,3.2,4.5
# TP_CLOSE_PCTS=25,25,25,25
```

Resolution order for both matches `resolve_atr_multiplier`'s pattern
(explicit CLI override > `.env` default) -- see `risk.resolve_tp_ratios()` /
`risk.resolve_tp_close_pcts()`. Malformed input (wrong count, non-numeric)
falls back to the known-good default rather than crashing the report.

### TP mode: ATR ladder (default) or structural levels -- opt-in

By default every TP is a fixed R-multiple of `stop_distance` (the table
above). `--tp-mode structural` computes TP1-4 from real price levels
instead -- nearest first, ahead of price in the trade's direction:

- volume-profile VAH/HVN (resistance side) or VAL/LVN (support side)
- the swing high/low this timeframe already tracks
- an active FVG edge, if one is open and trend-aligned
- a Fibonacci extension rung (1.272/1.414/1.618/2.618), when its own
  direction matches the trade

Any rung without a real structural candidate close enough (and at least
0.5R away, so a level that's basically noise/spread never becomes TP1)
falls back to its ATR R-multiple level -- structural mode never returns
fewer than 4 targets or a rung that sits behind price.

```bash
# one run
python -m cdcx --symbol BTC/USDT --timeframes 1h,4h,1d,1w --execute --balance 10000 --tp-mode structural

# permanent in .env
# TP_MODE=structural
```

This is opt-in and defaults to `atr` -- switching it on doesn't touch the
per-symbol ATR-multiplier table or `TP_RATIOS` tuning above; it only
changes where the TP *prices* come from, not the stop or position size.
See `risk.resolve_tp_mode()` / `risk.build_structural_tp_levels()` and
`TradeSignal.tp_mode` / `TradeSignal.fib_extension_levels`.

### Trade management / trailing rules (cdcx/trade_manager.py)

- **C.** Only the first entry per symbol is taken -- opening a second trade
  on a symbol that already has one open is refused outright (no
  pyramiding).
- **G.** When TP1 is reached, the stop moves to breakeven (entry price) AND
  `tp_close_pcts[0]`% of the **original** position size is closed (default
  25% -- four equal slices; **selectable at input**, not hardcoded --
  `--tp-close-pcts` on the CLI or `TP_CLOSE_PCTS` in `.env`, see
  `risk.resolve_tp_close_pcts()`).
- **H.** Each subsequent TP reached moves the stop to the *previous* TP
  level AND closes that TP's configured % of the original size. **TP4
  always closes 100% of whatever remains outright**, regardless of its own
  configured share -- "TP4 -> close remaining position," not "TP4 closes
  its slice and leaves a runner." (The ranging path's 2-target ladder
  follows the same rule: TP1 partial-closes, TP2 -- the final rung there --
  always closes 100% of the remainder.)
- **I.** If price gives back from TP1 toward breakeven, the *remaining*
  position (whatever's left after TP1's partial close) closes early at a
  level 20% of the way from breakeven towards TP1 (rather than riding all
  the way back down to the breakeven stop) -- a tighter protective exit.
  This interpretation of "20% above breakeven" is anchored to the
  breakeven-to-TP1 distance; flag it if a different anchor was intended.
- **J.** Planned max loss per trade is capped by position sizing above. If a
  close realizes a larger loss than planned on that slice -- e.g. price
  gaps past the stop in fast-moving conditions rather than filling exactly
  there -- the realized P&L is recorded honestly (not assumed-to-match-plan),
  and a warning is raised if that specific close's loss exceeds a 5%
  ceiling (checked per-slice, not just on the trade's cumulative total --
  a big TP1 win shouldn't mask a genuinely bad final stop-out). This is an
  honest-accounting safeguard, not a guarantee -- nothing here can force a
  real fill at the stop price without a live broker connection.

`realized_pnl`/`realized_pnl_pct` on a `Trade` are **cumulative** across
every partial close so far, not just the final one -- `partial_closes` is
the itemized log of each individual TP-triggered close (which TP, price,
size closed, P&L on that slice). `format_trade()` prints both the running
total and the itemized log.

### Circuit breaker (cdcx/circuit_breaker.py)

A portfolio-level throttle, distinct from `trade_manager.py`'s per-trade
rules above -- it doesn't manage an open position, it only gates whether a
*new* trade is allowed to open, like `entry_checklist.py` and
`no_trade_filter.py` already do. Checked immediately before every trade
opens, live/paper and in both offline backtest functions
(`cdcx/backtest/engine.py`). Two independent triggers, either one blocks:

- **Consecutive losses** (default: 3): pauses new entries for that symbol
  after N closed losing trades in a row (a breakeven close counts as a
  loss for streak purposes), until a winning trade resets the streak.
- **Drawdown from peak** (default: 10%): pauses new entries once realized
  equity has drawn down more than this % from its running peak.

Motivated by a real, empirically observed pattern, not a generic
risk-management checkbox: backtesting XRP/USD after the regime-gate fix
above still showed a run of 4 consecutive losing trades driving most of
that run's 20.89% max drawdown. Re-running BTC/ETH/XRP with the breaker on
vs. off (real 1000-bar 1h history, same regime gate, same costs):

| Symbol | Circuit breaker | Trades | Return | Max drawdown | Win rate |
|---|---|---|---|---|---|
| BTC/USD | off | 15 | +13.70% | 15.26% | 53.3% |
| BTC/USD | **on** | 10 | **+19.71%** | **9.27%** | 60.0% |
| ETH/USD | off | 14 | -8.48% | 21.55% | 42.9% |
| ETH/USD | **on** | 8 | **+0.69%** | **13.69%** | 50.0% |
| XRP/USD | off | 18 | -8.21% | 20.89% | 33.3% |
| XRP/USD | **on** | 11 | **+2.91%** | **11.00%** | 45.5% |

Consistent, large improvement on all three -- ETH and XRP flip from net
losses to net positive, BTC's drawdown roughly halves. Override via
`--max-consecutive-losses` / `--max-drawdown-pct` on the CLI (pass `0` to
disable a specific trigger), or the same-named keyword args on
`run_single_tf_backtest`/`run_confluence_backtest` (pass `None` to disable).

```bash
# tighten the circuit breaker to 2 consecutive losses / 5% drawdown
python -m cdcx --symbol BTC/USDT --timeframes 1h,4h,1d,1w --execute --balance 10000 \
  --max-consecutive-losses 2 --max-drawdown-pct 5

# disable both triggers
python -m cdcx --symbol BTC/USDT --timeframes 1h,4h,1d,1w --execute --balance 10000 \
  --max-consecutive-losses 0 --max-drawdown-pct 0
```

### One-way execution path: TRADING_MODE + the final NO-TRADE gate

Two independent, software-level safeguards sit between "a paper trade
qualified" and "a real order was sent" -- neither is bypassable by anything
upstream in the pipeline (Claude's analysis, the entry checklist, the
regime gate, the circuit breaker all only ever produce a recommendation;
none of them can themselves authorize a live send):

```
PAPER TRADE PASSES EVERY GATE
        |
        v
   --live passed?  --NO-->  stays paper, nothing else happens
        |
       YES
        v
TRADING_MODE=LIVE in the environment?  --NO-->  REFUSED before anything
        |                                        else runs (see below)
       YES
        v
   dry-run preview shown, human asked to type YES
        |
        v
  FINAL NO-TRADE GATE (no_trade_gate.py) -- re-validates EVERYTHING,
  from scratch, right here:
        paper_trade_result == PASS?
        human typed YES?
        risk% <= ceiling?
        stop loss present & valid?
        every planned TP present & valid?
        timeframe confirmation held?
        withdrawal permission confirmed disabled? (human attestation --
            see below, this project cannot check it automatically)
        market data still fresh (not stale)?
        no duplicate order already sent for this symbol recently?
        |
        +-- ANY single check fails --> BLOCKED, every failing reason shown,
        |                                logged to trading/paper/rejected/
        v
    ALL PASS
        v
  live bracket order sent to Crypto.com
```

**`TRADING_MODE` (config.py, `.env`)** -- `--live` refuses outright unless
`TRADING_MODE=LIVE` is *also* set in the environment, independent of the
`--live` flag and the typed-`YES` prompt. Default is `PAPER`. This exists
specifically so a stray `--live` on a machine still configured for paper
testing can't accidentally place a real order -- two independent switches
have to agree, not one.

```bash
# --live refused outright -- TRADING_MODE is still PAPER
python -m cdcx --symbol BTC/USDT --timeframes 1h,4h,1d,1w --execute --balance 10000 --live

# TRADING_MODE=LIVE in .env (or the environment) is required before --live does anything
TRADING_MODE=LIVE python -m cdcx --symbol BTC/USDT --timeframes 1h,4h,1d,1w --execute --balance 10000 --live
```

**The final gate (`cdcx/no_trade_gate.py`)** runs immediately after the
typed-`YES` prompt resolves, re-checking the whole trade from scratch
rather than trusting every earlier gate still holds by the time a human has
approved it. Every condition is independent -- any single failure blocks
the order outright, and every failing reason is always printed, never
silently dropped.

One condition needs a human, not a program: **withdrawal permission**.
Crypto.com's API (via `ccxt`) has no endpoint this project can use to check
whether an API key has withdrawal permission enabled (`ccxt.cryptocom().has`
doesn't advertise `fetchPermissions`) -- there's no way to verify this
automatically. Rather than skip the check, the gate **fails closed**: it
requires `--confirmed-no-withdraw-permission` on the CLI, an explicit
attestation that you checked manually in your Crypto.com account's API-key
settings. No attestation, no live order, every time -- unknown is treated
as unsafe, not as a pass, exactly like every other condition here.

```bash
TRADING_MODE=LIVE python -m cdcx --symbol BTC/USDT --timeframes 1h,4h,1d,1w \
  --execute --balance 10000 --live --confirmed-no-withdraw-permission
```

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

### The sequential MTF framework, restated

Everything above was already built around one sequential read down the
timeframes -- this just names it explicitly, and maps each role to the
module that actually implements it:

```
1W  DIRECTION   weekly_bias() in structure_strategy.py -- which side of the
                weekly POC is price on. Advisory, not a hard gate.
1D  LOCATION    structure_levels.py's POC / support / resistance / FVGs for
                the day -- the zone the 4H setup has to trade against.
4H  STATE       regime.py (TRENDING / RANGING / TRANSITIONAL) decides which
                strategy runs at all; atr_state.py reads the ATR sequence
                (contraction / flat / expansion, and the transition between
                them) as *timing* context on top of that regime read.
1H  TRIGGER     candlestick_patterns.py's pattern match against the
                direction implied by the 4H setup -- the actual entry bar.
```

ATR is deliberately never the directional signal on its own (`regime.py`
and `structure_strategy.py` both only ever treat it as timing/context, per
their own docstrings) -- it answers **WHEN**, not **WHICH DIRECTION**.
Fibonacci (`indicators/fibonacci.py`), Volume Profile
(`indicators/volume_profile_fixed.py` / `volume_profile_anchor.py`), and FVG
(`indicators/fair_value_gap.py`) answer **WHERE**; market structure
(`indicators/market_structure.py`) answers **WHICH DIRECTION**; candlestick
patterns answer the **TRIGGER**; Fibonacci Trend Extension
(`fibonacci.calculate_extension`) answers **WHERE PRICE MAY GO** (also used
as the `--tp-mode structural` TP ladder, section 6 above).

**ATR's three states map to three separate strategies, all already
implemented:**

| ATR condition | Strategy | Implemented by |
|---|---|---|
| Contraction -> Expansion | **A -- Contraction breakout** | `structure_strategy.py`'s `breakout_retest` / `fvg_confluence` triggers, timed by `atr_state.py`'s `contraction_to_expansion` / `compression_release` reads |
| Flat | **B -- Flat rotation** | `ranging_strategy.py` (only runs once `regime.py` classifies RANGING) -- trades `HVA <-> POC <-> LVA`, TP1 = POC, TP2 = opposite range edge |
| Expansion -> pullback -> Expansion | **C -- Expansion continuation** | same `structure_strategy.py` triggers, timed by `atr_state.py`'s `second_expansion` read (the "don't chase the first move" entry) |

**ATR transition vocabulary** (`indicators/atr_state.py`'s `AtrTransition.kind`,
all advisory -- read by `entry_checklist.py` as a non-blocking `advisory=True`
item, never a hard gate):

| Transition | `kind` | Trigger? | Reading |
|---|---|---|---|
| Contraction -> Expansion | `contraction_to_expansion` | Yes | Breakout trigger (single-bar flip) |
| Contraction -> Flat -> Expansion | `compression_release` | Yes | Breakout trigger, bridged through a flat cooldown -- Strategy A's other shape |
| Expansion -> cooldown -> Expansion | `second_expansion` | Yes | The higher-quality "don't chase the first move" entry -- Strategy C |
| Expansion, no prior cooldown | `expansion_continuation` | No | First/ongoing expansion -- be wary of chasing |
| Expansion -> Contraction | `expansion_to_contraction` | No | Momentum cooling / likely pullback |
| Expansion -> Flat | `expansion_to_flat` | No | Possible exhaustion / consolidation |
| Plain contraction | `contraction` | No | Compression, direction not yet known |
| Plain flat | `flat` | No | Rotation environment (Strategy B territory) |

### A+ setup grading (cdcx/setup_grade.py)

`setup_grade.grade_setup()` composes a `structure_strategy.StructureSetup`
with an `atr_state.AtrTransition` (and, optionally, a
`confluence.ConfluenceResult` / `confidence_scoring.WeightedConfidenceResult`)
into one advisory label:

```
GRADE A+   Structural setup valid (1W bias + 1D location + 4H setup + 1H
           confirmation) AND the 4H ATR transition confirms
           (contraction_to_expansion / compression_release / second_expansion)
           AND, if supplied, confluence/confidence are both at their
           strongest tiers.
GRADE A    Structural setup valid, but the ATR timing hasn't confirmed yet
           (or confluence/confidence came in weaker) -- still tradeable,
           just not the highest-quality timed entry.
No Trade   No qualifying structural setup.
```

Printed automatically as part of `--structure`'s final section (right after
`STRUCTURE SETUP (1W/1D/4H/1H)`), reusing the same 4H OHLCV the structure
setup itself already fetched -- no extra exchange calls. Same convention as
every other advisory read in this project (`atr_state.py`,
`entry_checklist.py`'s `advisory=True` items): it labels quality for the
report, it is never consulted by `no_trade_gate.py`, and it never blocks or
authorizes a live order on its own.

```python
from cdcx import setup_grade
from cdcx.indicators import atr_state

atr_transition = atr_state.analyze(h4_data.highs, h4_data.lows, h4_data.closes)
grade = setup_grade.grade_setup(setup, atr_transition)  # setup = evaluate_structure_setup(...)
print(setup_grade.format_setup_grade(grade))
```

## Paper Trade Approval report (cdcx/paper_approval.py)

Every time `--execute` clears every gate (confluence, entry checklist,
no-trade filter, or the ranging-strategy setup) and `trade_manager` opens
the paper trade, one consolidated report prints before the raw trade-state
dump -- the same shape as this project's PAPER TRADE APPROVAL template:

```
============================================================
                    PAPER TRADE APPROVAL
============================================================
Symbol:    BTC/USDT
Direction: LONG

1H   BULLISH
4H   BULLISH
1D   BULLISH
1W   NEUTRAL

Market State: TRENDING (bullish)

POC:  $79,374.41
FVG:  $78,274.31 - $78,396.03
HVN:  $78,668.89
LVN:  $83,607.49

FIBONACCI:
  0.382 = $79,961.37
  0.500 = $79,494.27
  0.618 = $79,027.17
  0.786 = $78,362.14

ATR:        $898.07
Entry:      $80,666.63
Stop Loss:  $79,319.53  (1.5x ATR)
TP1:        $83,630.25
TP2:        $84,169.09
TP3:        $84,977.36
TP4:        $86,728.59

Portfolio Risk: 2.0% maximum
Position Size:  0.148467 units (~$11,976.32 notional)

PAPER RESULT: PASS

LIVE EXECUTION:
[ APPROVE ]   [ REJECT ]
(pass --live to be prompted for this before anything real is sent)
============================================================
```

This is a formatter, not a new computation -- every number comes from
values the pipeline already produces:

| Field | Source |
|---|---|
| 1H/4H/1D/1W | `signals_by_tf` (trending path) mapped from Strong Buy/Buy/Watch/Neutral/Sell/Strong Sell to BULLISH/BEARISH/NEUTRAL. The ranging path doesn't require multi-timeframe confluence, so only the entry timeframe's own read is filled in there; the rest show `N/A` rather than a fabricated read. |
| Market State | `signal.regime.label` (Step 1 -- TRENDING/RANGING/NO TRADE (TRANSITION)) |
| POC / VAH / VAL | `indicators/volume_profile_fixed.py` |
| FVG | the active, unfilled, trend-aligned gap from `indicators/fair_value_gap.py`, if any |
| HVN | the tallest volume-profile bucket **other than** the POC itself -- a genuine second field, not POC relabeled |
| LVN | the thinnest-traded bucket in the same profile |
| Fibonacci ladder | `indicators/fibonacci.py`'s retracement levels (0.382/0.5/0.618/0.786 shown; 0.236/0.786 exist too, in `signal.fib_levels`) |
| Entry / Stop / TP1-4 | `risk.PositionPlan` + the same TP ladder `trade_manager.open_trade` was given (ATR-extension R-multiples on the trending path; POC/opposite-edge on the ranging path -- unchanged from the rest of this README) |
| Portfolio Risk / Position Size | the risk % and sized units from `risk.PositionPlan` |
| PAPER RESULT | always `PASS` here -- this report only ever prints once every gate already passed and the paper trade was opened; a blocked setup prints its own gate-specific message instead (see `trading/paper/rejected/`) |
| LIVE EXECUTION [APPROVE]/[REJECT] | a static reminder of the actual gate -- `--live`'s existing typed-`YES` confirmation in `_handle_live_order` (unchanged; this report doesn't add a second prompt) |

`engine.TradeSignal` carries the raw POC/VAH/VAL/HVN/LVN/FVG/Fibonacci
values needed for this (`swing_high`, `swing_low`, `poc`, `vah`, `val`,
`hvn`, `lvn`, `fvg_top`, `fvg_bottom`, `fib_levels`) alongside the existing
scored fields -- additive fields only, nothing else about `TradeSignal`
changed.

## Trade journal & audit trail (cdcx/journal.py)

Every stage of the pipeline below writes one JSON file to disk as it
happens, building an append-only audit trail of every decision -- not just
the trades that were opened. This is the on-disk form of the project's
end-to-end flowchart:

```
CLAUDE-ASSISTED MARKET ANALYSIS (engine.py, confluence.py, structure_strategy.py, ...)
        |
        v
   TRADE SIGNAL  ------------------------------------------->  trading/paper/signals/
        |
        v
  PAPER SIMULATION -- checklist / regime / no-trade filter gates
        |
        +-- any gate fails ------------------------------->  trading/paper/rejected/
        |
        v (sized plan built)  -------------------------->  trading/paper/simulated_orders/
        |
        v (all gates pass, trade_manager opens it)  ----->  trading/paper/simulated_results/  (PAPER RESULT: PASS)
        |
        v  (only if --live)
   LIVE ORDER PREVIEW (dry-run)  ----------------------->  trading/live/orders/
        |
        v
  HUMAN APPROVAL ("type YES")
        |
        +-- declined ------------------------------------->  trading/paper/rejected/
        |
        v (typed YES)  ----------------------------------->  trading/live/approved/
        |
        v
  LIVE CDCX-CLI EXECUTION (real bracket order sent)  ----->  trading/live/executions/
        |
        v
  CRYPTO.COM  ->  position closes eventually, recorded manually
        |          (`--record-live-close`, see below -- nothing here
        v           polls the exchange for fills automatically)
  trading/live/results/
        |
        v
  --export-tax  ->  trading/tax_records/ (Form 8949, Schedule D, CPA summary)
                     trading/ssa_records/ (documentary activity record)
```

```
trading/
├── paper/
│   ├── signals/              every TradeSignal considered by --execute
│   ├── simulated_orders/     sized plan (entry/stop/TP/size) once an entry timeframe qualifies
│   ├── simulated_results/    paper trades that cleared every gate and were opened
│   └── rejected/             anything blocked at any gate, with the reason
│
├── live/
│   ├── approved/              the human's typed YES, right before a real order is sent
│   ├── orders/                 the built order + dry-run preview, before confirmation is asked
│   ├── executions/             the real send result once the order actually goes out
│   └── results/                 realized P&L of closed live positions (manual, see below)
│
├── tax_records/                Form 8949 CSV, Schedule D summary, CPA summary (--export-tax)
└── ssa_records/                 documentary trading-activity record (--export-tax)
```

This tree is created under the current working directory by default
(override with `TRADING_JOURNAL_DIR` in `.env`), gitignored, and populated
automatically by `--execute`/`--live` -- there's nothing to opt into. Every
record is a single JSON file with envelope fields (`schema_version`,
`written_at`, `stage`, `symbol`) plus the stage-specific payload
(dataclasses like `TradeSignal`/`Trade`/`BracketResult` are serialized to
plain dicts). Read them back programmatically with
`journal.load_stage("rejected")`, etc.

**`trading/live/results/` is never written automatically.** This project
has no live position/fill polling (see `live_execution.py`) -- once a real
position actually closes on the exchange, record it yourself:

```bash
python -m cdcx --record-live-close --symbol BTC/USDT --direction long \
  --quantity 0.1 --entry-price 60000 --exit-price 65000 \
  --opened-at 2026-01-01 --closed-at 2026-01-15 --fees 5 --notes "TP1 hit"
```

### Tax / CPA / SSA export (cdcx/tax_export.py)

```bash
python -m cdcx --export-tax
```

Reads every record in `trading/live/results/` and writes into
`trading/tax_records/` and `trading/ssa_records/`:

- **`form_8949_<timestamp>.csv`** -- one row per closed position (crypto is
  IRS property, Notice 2014-21, so each round trip is a disposition:
  Description / Date Acquired / Date Sold / Proceeds / Cost Basis /
  Gain-Loss / Term), ready to hand to a CPA for Form 8949 / Schedule D.
- **`schedule_d_summary_<timestamp>.txt`** -- short-term vs. long-term
  totals (held > 365 days = long-term, the same "> 1 year" line the IRS
  uses for property).
- **`cpa_summary_<timestamp>.txt`** -- trade count, win rate, total realized
  P&L and fees, broken down by symbol and by tax year.
- **`ssa_trading_record_<timestamp>.txt`** -- a documentary record of
  trading activity, *not* an SSA filing.

**This is not tax or legal advice.** It mechanically formats numbers you
already recorded via `--record-live-close` -- it assumes one lot per
recorded round trip (no FIFO/LIFO/specific-ID lot matching across partial
fills), doesn't know your jurisdiction, and doesn't know whether you hold
any elected tax status. Ordinary trading gains are capital gains, not
self-employment income, and by default are **not** reported to the Social
Security Administration -- that only changes with an elected IRS Trader Tax
Status (Section 475(f) mark-to-market election), which is a CPA
determination, not something this tool can decide. Have a CPA review every
export before filing or relying on it.

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

# real-time pricing for one contract -- TICKER must be a real `symbol`
# copied from --predictions/--predictions-search output (see below),
# e.g. NFL-00002-260813-M-Packers-011_270301-2300_1_PM.NPO
python -m cdcx --predictions-contract NFL-00002-260813-M-Packers-011_270301-2300_1_PM.NPO
```

```python
from cdcx.predictions import PredictionsClient, format_events, format_contract_price

client = PredictionsClient()  # api_key="" works fine for anonymous access
events = client.list_events(kind="NFL", limit=5)
print(format_events("PREDICTION MARKET EVENTS", events))

# grab a real ticker from one of those events' contracts, then:
price = client.get_contract_price(events[0].contracts[0].symbol)
print(format_contract_price(price))
```

> **Confirmed against real traffic, schema locked in from a live capture.**
> `--predictions`/`--predictions CRYPT`/`--predictions-search` have been
> run against the live API and correctly parse real events -- this
> project's own sandbox can't reach `crypto.com` at all, so all of this
> was confirmed on a real machine, not in CI here. A real `/events`
> response looks like this (trimmed):
> ```json
> {"data": [{"id": "...", "title": "Green Bay @ Pittsburgh", "kind": "NFL",
>   "contracts": [
>     {"id": "...", "symbol": "NFL-00002-260813-M-Packers-011_270301-2300_1_PM.NPO",
>      "title": "Green Bay", "status": "active",
>      "yes": "0.42", "no": "0.58", "chance": "42.00", "payout_per_100": "232.56"}
>   ]}]}
> ```
> **The important, non-obvious thing this confirmed:** a contract's real
> identifier is its `symbol` -- a long structured string, not a short
> asset-style code. `BTC-YES` (the quickstart docs' own illustrative
> example) and a guessed `BTC` both 404 against the live API -- that's
> Crypto.com correctly reporting neither is a real, currently-listed
> contract, not a bug in this client (confirmed via `PredictionsNotFound`
> printing a clear message instead of a crash or a misparse). Get a real
> ticker from `--predictions`/`--predictions-search` output first, then
> pass its `symbol` to `--predictions-contract`.
>
> **`GET /contracts/{ticker}/price` itself turned out to use a genuinely
> different shape** from the nested event contracts above -- also
> confirmed live, via a pretty-printed response (`curl ... | python3 -m
> json.tool`, specifically to rule out a terminal wrapping/hiding a
> field):
> ```json
> {"data": {"symbol": "BTCUSD_260808-2100_6538400_B.NXO",
>           "title": "Above $65,384.00", "status": "active",
>           "bid": "0", "ask": "0.10", "mid": "0.05",
>           "probability": "10.00", "spread": "0.10", "updated_at": "..."}}
> ```
> Order-book style (`bid`/`ask`/`mid`/`spread`) plus a `probability`
> percentage -- not `yes`/`no`/`chance` like the nested event contracts.
> Both shapes are real; they just don't match each other, which is a
> genuine quirk of this API. `predictions.py` parses each endpoint against
> its own confirmed shape rather than assuming they're the same.

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
│   ├── paper_approval.py      # PAPER TRADE APPROVAL report formatter
│   ├── journal.py             # on-disk audit trail: trading/paper/... and trading/live/...
│   ├── tax_export.py          # Form 8949 / Schedule D / CPA summary / SSA record export
│   ├── regime.py               # Step 1: TRENDING / RANGING / TRANSITIONAL classification
│   ├── ranging_strategy.py     # Step 3: range-boundary entries, POC + opposite-edge targets
│   ├── no_trade_filter.py      # Step 4: final safety gate (RR<2, ATR low, ADX dead zone, news)
│   ├── circuit_breaker.py      # portfolio throttle: consecutive-loss pause + drawdown-from-peak pause
│   ├── no_trade_gate.py        # FINAL gate right before a live order sends -- re-validates everything
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
│   ├── backtrader_strategy.py # bridges the signal engine into a native backtrader.Strategy
│   ├── backtrader_runner.py   # Cerebro runner for backtrader_strategy.CDCXSignalStrategy
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
    ├── test_paper_approval.py
    ├── test_volume_profile_fixed.py
    ├── test_journal.py
    ├── test_tax_export.py
    ├── test_circuit_breaker.py
    ├── test_backtest_regime_gate.py
    ├── test_backtest_circuit_breaker.py
    ├── test_cryptocom_exchange.py
    ├── test_backtest_atr_multiplier.py
    ├── test_backtest_partial_close_costs.py
    ├── test_no_trade_gate_integration.py
    ├── test_regime.py
    ├── test_regime_color.py
    ├── test_ranging_strategy.py
    ├── test_no_trade_filter.py
    ├── test_confidence_scoring.py
    ├── test_execute_integration.py
    ├── test_engine_regression.py
    ├── test_backtrader_bridge.py
    ├── test_structure_levels.py
    ├── test_structure_strategy.py
    ├── test_predictions.py
    ├── test_cli_predictions.py
    └── test_cli_structure_combination.py
```

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

### `--limit` above 300 (cdcx/exchange/cryptocom.py)

Crypto.com's REST API caps a single OHLCV request at 300 candles --
confirmed live (a `limit=1000` call returned exactly 300 rows). `--limit`
values above that are paginated transparently: `CryptoComExchange` walks
backward from "now" in 300-candle pages, so `--limit 1000` genuinely
returns 1000 candles instead of silently capping at 300.

**The wrinkle this fix is actually built around, confirmed live against
real XRP/USD data:** a `since` that's *decades* before a pair's real
history returns an **empty list** -- `since=0` (epoch) on XRP/USD 1w (real
history: ~264 weekly candles back to mid-2021) came back with 0 rows.
`--limit 1000` on `1w` originally computed `since = now - 1000 weeks`
(~19 years back) via a naive upfront guess, landing in that same "decades
early, comes back empty" territory and crashing downstream on an empty
result. But a `since` only *modestly* before the true start -- confirmed
with both 1 and 5 weeks early -- correctly **clamps forward** to the
earliest available candle instead of returning nothing. So the fix isn't
"handle empty responses everywhere" -- it's walking backward from "now" one
300-candle page at a time (each `since` anchored on data already confirmed
to exist, never guessed from the full `limit` up front), which keeps every
request well inside the "clamps forward fine" range. A halving retry on an
empty response remains as defensive insurance for the residual edge case
where total history isn't an exact multiple of page size -- see
`tests/test_cryptocom_exchange.py` for the regression coverage (a fake
non-page-aligned history exercising exactly this boundary).

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
  Check what the exchange actually allows first with `--leverage`:
  ```bash
  python -m cdcx --symbol XRP/USD --leverage
  # XRPUSD-PERP: 1x - 50x leverage
  ```
  Worth checking before `--live` on a small account -- `risk.py`'s 2%-risk
  position sizing can imply notional exposure well over 100% of account
  equity on a tight ATR stop (confirmed live on XRP/USD: ~289% notional on
  a $1,000 account), which needs leverage room on the exchange side that
  this tool never confirms or configures.
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

## Backtrader integration (cdcx/backtrader_strategy.py, cdcx/backtrader_runner.py)

Since this tool lives inside the `backtrader` repository, `CDCXSignalStrategy`
bridges the same signal engine, entry checklist, and risk sizing into a
native `backtrader.Strategy`, so it can be driven through backtrader's own
`Cerebro` engine, data feeds, brokers, and analyzers instead of (or
alongside) the standalone offline backtester above.

This is a *bridge*, not a second copy of `cdcx.backtest.engine`'s paper
trade-manager:

| | `cdcx.backtest.engine` | `cdcx.backtrader_strategy` |
|---|---|---|
| Signal generation | `engine.analyze_ohlcv` | same |
| Entry gating | `entry_checklist.evaluate_entry_checklist` | same |
| Position sizing | `risk.build_position_plan` | same |
| Exits | its own trailing / break-even / give-back rules (`trade_manager.py`), replayed against a persisted JSON trade-state file | a backtrader-native bracket order (market entry + ATR stop-loss + TP1 limit) -- no TP2-TP4 laddering or trailing here |
| Costs / fills | custom fee + fixed-slippage + square-root market-impact model | whatever `Cerebro`'s broker/commission scheme provides |

Use `cdcx.backtest.engine` for the full paper trade-manager simulation this
project was originally built around; use the backtrader bridge when you
want CDCX signals inside a normal `Cerebro` run (alongside other
strategies, analyzers, or broker integrations).

```bash
# no network/API keys needed -- synthetic multi-regime OHLCV
python -m cdcx --backtrader --synthetic --symbol BTC/USDT --timeframe 1h --limit 1500

# real candles via ccxt (needs CDCX_API_KEY / CDCX_API_SECRET-less public data)
python -m cdcx --backtrader --symbol BTC/USDT --timeframe 1h --limit 500 --balance 10000
```

```python
import backtrader as bt
from cdcx.backtrader_strategy import CDCXSignalStrategy
from cdcx.backtrader_runner import run_backtrader_backtest, format_summary
from cdcx.backtest.synthetic import generate_ohlcv

data = generate_ohlcv(n_bars=1500, start_price=62000.0, seed=42, timeframe="1h")
summary = run_backtrader_backtest(data, symbol="BTC/USDT", timeframe="1h", cash=10_000.0)
print(format_summary(summary))

# or wire CDCXSignalStrategy into your own Cerebro setup directly:
cerebro = bt.Cerebro()
cerebro.adddata(bt.feeds.PandasData(dataname=my_dataframe))  # any backtrader-compatible feed
cerebro.addstrategy(CDCXSignalStrategy, symbol="BTC/USDT")
cerebro.run()
```

Install the optional `backtrader` extra (`pip install -e ".[backtrader]"`)
if using `cdcx-cli` outside this repository.

## TradingView / Pine Script port (pine/cdcx_trend_core.pine)

A hand-ported `//@version=6` Pine strategy for backtesting the trending-path
core directly in TradingView's own Strategy Tester -- useful for validating
against TradingView's independent bar/fill simulation, or if you want a
chart-native version to eyeball entries visually.

**Ported 1:1:** EMA(17)/ATR(11) trend (`atr_ema_variant1.py`), ADX(17)+DI
(`adx.py`), RSI(17) (`rsi.py`), the Bollinger overextension guard
(`bollinger_bands.py`), a 3-candle Fair Value Gap check
(`fair_value_gap.py`), the 1.5x ATR stop + 2%-account-risk position sizing
formula (`risk.py`, computed inline and passed via `qty=` on each
`strategy.entry`), and the TP1-4 R-multiple ladder (2.2R/2.6R/3.2R/4.5R,
same ratios as `engine.py`'s `TP_RATIOS`).

**Not ported, and why:**
- **1H/4H/1D/1W confluence** (`confluence.py`) -- possible via
  `request.security()`, but deliberately left out here to avoid the
  repainting pitfalls of naive multi-timeframe Pine without a lot of extra
  care (`lookahead=barmerge.lookahead_off` + confirmed-bar handling).
- **Volume Profile POC/VAH/VAL + HVN/LVN**
  (`volume_profile_fixed.py`/`volume_profile_anchor.py`) -- TradingView's
  Volume Profile is a chart drawing tool, not a value a Pine strategy script
  can read back into trading logic.
- **The TRENDING/RANGING/TRANSITIONAL regime gate** (`regime.py`) and the
  separate **ranging-strategy path** (`ranging_strategy.py`) -- this script
  only covers the trending path.
- **`trade_manager.py`'s break-even/give-back trailing rules** -- this uses
  one static ATR stop per entry (shared across all four TP exits) instead
  of ratcheting the stop as each TP is hit.

### Usage

1. Paste `pine/cdcx_trend_core.pine` into TradingView's Pine Editor, **Add
   to Chart**, open the **Strategy Tester** tab.
2. In Strategy Tester **Properties**: commission ~0.05-0.1% (Crypto.com
   taker fee), a couple ticks of slippage, **Recalculate on bar close** on.
   Order size doesn't need setting -- the script computes quantity itself
   from `riskPct` and passes it via `qty=`.
3. Match `--symbol`/`--timeframe` to whatever you're comparing against in
   `python -m cdcx`, and use **Deep Backtesting** (top-right menu) instead
   of the default ~5k-bar window for full history.

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
