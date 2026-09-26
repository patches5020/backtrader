# cdcx-cli -- End-to-End Flowchart

This is the full life-cycle flowchart this project is built against, split
into two parts: the **capital/account life cycle** (mostly outside this
codebase -- your bank, your exchange account, your CPA) and the **trading
pipeline** this repository actually implements and journals to disk.

Generated as a standalone backup artifact alongside the project zip -- see
`README.md` for the authoritative, always-current version of each section
this summarizes.

---

## 1. Capital & account life cycle

```
                         YOU
                          |
              PERSONAL / INHERITED
                     CAPITAL
                          |
                          v
                 PERSONAL BANK
                          |
                          v
              CRYPTO.COM EXCHANGE
                 PERSONAL ACCOUNT
                          |
                          v
                     CDCX-CLI
                          |
             +------------+------------+
             |                         |
             v                         v
       MARKET ANALYSIS             EXECUTION
             |                         ^
             v                         |
        CLAUDE-ASSISTED                |
        MARKET ANALYSIS                |
             |                         |
             v                         |
       TRADE SIGNAL                    |
             |                         |
             v                         |
      +-----------------+              |
      | PAPER TRADING   |              |
      | / SIMULATION    |              |
      +--------+--------+              |
               |                       |
               v                       |
       PAPER TRADE VALIDATION          |
               |                       |
        +------+------+                |
        |             |                |
        v             v                |
     REJECT         APPROVE            |
        |             |                |
        v             v                |
      LOG ONLY    HUMAN PERMISSION ----+
                       |
                       v
                LIVE CDCX-CLI
                       |
                       v
                 CRYPTO.COM
                       |
                       v
                 TRADE JOURNAL
                       |
          +------------+------------+
          v            v            v
     TAX RECORDS    STRATEGY     SSA RECORDS
          |            |            |
          v            v            v
         CPA        BACKTEST       SSA
          |
          v
      IRS RETURN
```

Everything from **CDCX-CLI** down through **TRADE JOURNAL** is implemented
in this repository. **TAX RECORDS -> CPA -> IRS RETURN** and **SSA
RECORDS -> SSA** are exported as documentary paperwork
(`cdcx/tax_export.py`, `--export-tax`) -- not tax/legal advice, and not a
filing integration; a human (you, your CPA) still carries those the rest of
the way. **STRATEGY -> BACKTEST** is `cdcx/backtest/` and
`cdcx/backtrader_strategy.py`.

---

## 2. Trading pipeline (implemented, journaled to disk)

```
CLAUDE-ASSISTED MARKET ANALYSIS (engine.py, confluence.py, structure_strategy.py, ...)
        |
        v
   TRADE SIGNAL  ------------------------------------------->  trading/paper/signals/
        |
        v
CHECK: 1H/4H/1D/1W direction * FVG * POC * HVN/LVN * Fixed & Anchored
       Volume Profile * Fibonacci * Trend Fibonacci * Consolidation /
       Range / Breakout / Retest * ADX(17) * RSI(17) * VOL(17) * ATR *
       Risk = 2% * SL = 1.5 x ATR
        |
        v
  PAPER SIMULATION -- checklist / regime / no-trade filter / circuit-breaker gates
        |
        +-- any gate fails ------------------------------->  trading/paper/rejected/
        |
        v (sized plan built)  -------------------------->  trading/paper/simulated_orders/
        |
        v (circuit breaker checked -- see below, blocks even a fully-
        |  qualified setup if this symbol is on a losing streak / drawdown)
        v (all gates pass, trade_manager opens it)
   PAPER TRADE APPROVAL report printed (see below)  ----->  trading/paper/simulated_results/
                                                              (PAPER RESULT: PASS)
        |
        v  (only if --live AND TRADING_MODE=LIVE -- two independent
        |   software-level switches, both required; see section 7)
   LIVE ORDER PREVIEW (dry-run)  ----------------------->  trading/live/orders/
        |
        v
  HUMAN APPROVAL ("type YES")
        |
        v
  FINAL NO-TRADE GATE (no_trade_gate.py) -- re-validates EVERYTHING from
  scratch: paper PASS? human YES? risk<=ceiling? SL present? every TP
  present? timeframe confirmed? withdrawal permission confirmed OFF?
  data fresh? no duplicate order? ANY single failure blocks, always
  shown -- see section 7.
        |
        +-- any check fails (incl. declined) ------------->  trading/paper/rejected/
        |
        v (ALL PASS)  -------------------------------------->  trading/live/approved/
        |
        v
  LIVE CDCX-CLI EXECUTION (real bracket order sent)  ----->  trading/live/executions/
        |
        v
  CRYPTO.COM  ->  position closes eventually, recorded manually
        |          (`--record-live-close` -- nothing here polls the
        v           exchange for fills automatically)
  trading/live/results/
        |
        v
  --export-tax  ->  trading/tax_records/ (Form 8949, Schedule D, CPA summary)
                     trading/ssa_records/ (documentary activity record)
```

### On-disk audit trail

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
│   └── results/                 realized P&L of closed live positions (manual, see README)
│
├── tax_records/                Form 8949 CSV, Schedule D summary, CPA summary (--export-tax)
└── ssa_records/                 documentary trading-activity record (--export-tax)
```

---

## 3. PAPER TRADE APPROVAL report

Printed automatically once a paper trade clears every gate
(`cdcx/paper_approval.py`, wired into `cli.py`'s `_open_trade_and_maybe_go_live`):

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
TP1:        $83,630.25   (close 25% -> stop to breakeven)
TP2:        $84,169.09   (close 25% -> stop to TP1)
TP3:        $84,977.36   (close 25% -> stop to TP2)
TP4:        $86,728.59   (close 100% of remainder -- position fully closed)

Portfolio Risk: 2.0% maximum
Position Size:  0.148467 units (~$11,976.32 notional)

PAPER RESULT: PASS

LIVE EXECUTION:
[ APPROVE ]   [ REJECT ]
(pass --live to be prompted for this before anything real is sent)
============================================================
```

Both the ATR stop multiplier and the TP1-4 R-multiples/close-percentages
shown above are **selectable at input** (`--atr-multiplier`, `--tp-ratios`,
`--tp-close-pcts`, or the matching `.env` defaults), not hardcoded -- see
section 5 (and TP *targets* can additionally come from real structural
levels instead of R-multiples -- section 6). `PAPER RESULT: PASS` and the
`[ APPROVE ] [ REJECT ]` footer are the report's terminal state --
`APPROVE`/`REJECT` is a reminder of `--live`'s typed-`YES` confirmation gate
in `_handle_live_order`, further backed by the FINAL NO-TRADE GATE described
in section 7.

---

## 4. Circuit breaker (cdcx/circuit_breaker.py)

A portfolio-level throttle, separate from `trade_manager.py`'s per-trade
rules -- it gates whether a *new* trade is allowed to open, live/paper and
in both offline backtest functions, checked right before every entry:

```
                new signal, every other gate already passed
                              |
                              v
              +----------------------------------+
              | CIRCUIT BREAKER (checked per symbol) |
              +----------------------------------+
                 |                              |
        3+ losses in a row              drawdown >= 10% from peak
        for this symbol?                equity for this symbol?
                 |                              |
                YES  ---------- OR --------  YES
                 |                              |
                 v                              v
           BLOCKED -- no trade opens, logged to trading/paper/rejected/
                 |
                clears once a win resets the streak / equity recovers
```

Both thresholds default on (3 consecutive losses / 10% drawdown) and are
independently overridable: `--max-consecutive-losses` / `--max-drawdown-pct`
on the CLI (`0` disables a trigger), or the same-named backtest keyword
args (`None` disables). Empirically, enabling it improved every one of
BTC/ETH/XRP's 1000-bar backtests -- ETH and XRP flipped from net losses to
net positive, BTC's max drawdown roughly halved. See `README.md`'s
"Circuit breaker" section for the full before/after table.

---

## 5. Per-symbol ATR multiplier (cdcx/risk.py's resolve_atr_multiplier)

The "1.5x ATR" stop distance is no longer one flat number for every symbol.
Resolution order:

```
              --atr-multiplier flag (or atr_multiplier_override=)
                              |
                          given? --YES--> use it, done
                              |
                             NO
                              v
        ATR_MULTIPLIER_OVERRIDES in .env, keyed by BASE currency
        (ships with "BTC:1.5,XRP:1.5")
                              |
                    symbol's base found? --YES--> use that per-symbol value
                              |
                             NO
                              v
                  ATR_STOP_MULTIPLIER (global fallback, 1.5x)
```

Backtested empirically, not guessed -- real 1000-bar 1h history,
regime-gated + circuit-breaker-on, sweeping 1.0x-3.0x across BTC/USD,
XRP/USD, XRP/USDT, ETH/USD:

```
              1.0x        1.5x (old default)   2.0x        2.5x        3.0x
BTC/USD    -11.19%             +19.71% (best)  +9.20%      -3.73%      -5.48%
XRP/USD    +15.11% (best)      +2.91%          -8.64%      -5.69%      -0.50%
XRP/USDT   +17.09% (best)      +4.75%          -1.70%      +6.05%      +9.18%
ETH/USD    +27.38% (best)      +0.69%          +13.75%     +0.34%      +1.66%
```

**BTC prefers the 1.5x default; every altcoin tested had a *backtested*
edge at a tighter 1.0x instead** -- not a smooth curve anywhere, genuinely
per-instrument, not "tighter is always better." **XRP's default was
deliberately set back to 1.5x anyway, at the user's request** -- trading
that backtested edge for one consistent multiplier across both
actively-traded symbols; the table stays here so the tradeoff is visible,
not silently lost. `engine.TradeSignal.atr_multiplier` and
`risk.PositionPlan.atr_multiplier` both carry the actual resolved value
used, so the printed report and the real trade plan can never silently
disagree (same invariant as the earlier SL/TP-must-share-one-ATR-reading
fix). See `README.md`'s "Per-symbol ATR multiplier" section for full detail.

---

## 6. TP mode: ATR ladder (default) or structural levels (cdcx/risk.py's resolve_tp_mode)

TP1-4 *prices* have a second, opt-in resolution path -- independent of the
ATR multiplier/R-multiple tuning in section 5, which still controls the
stop and (in the default mode) the TP ladder:

```
                --tp-mode flag (or tp_mode_override=)
                              |
                          given? --YES--> use it, done
                              |
                             NO
                              v
                    TP_MODE in .env (default "atr")
```

**`atr` (default, unchanged):** TP1-4 = fixed R-multiples of `stop_distance`
(section 5's `TP_RATIOS` table).

**`structural`:** each rung is instead the *nearest real price level* ahead
of entry in the trade's direction, checked in this order per rung
(nearest-first): volume-profile VAH/HVN (resistance side) or VAL/LVN
(support side), the swing high/low this timeframe already tracks, an active
FVG edge, a Fibonacci extension rung (1.272/1.414/1.618/2.618) sharing the
trade's own direction. A candidate closer than 0.5R is discarded as noise;
any rung that still has no real candidate falls back to its `atr`-mode
level, so `structural` mode never returns fewer than 4 targets or one
sitting behind price (`risk.build_structural_tp_levels`).

This was the one genuinely new, unimplemented item from the architecture
review that requested it -- everything else the same review asked for
(timeframe-hierarchy weighting, POC/HVN/LVN/FVG/Fib level extraction, the
2-of-4 weighted confluence grading, breakeven-on-TP1 + partial-close
simulation, the human-approval gate) was already built in earlier rounds
(sections 2-4, 7). Deliberately opt-in and defaulted to `atr` so it doesn't
disturb the per-symbol ATR-multiplier table (section 5) or its backtested
tuning. `TradeSignal.tp_mode` and `TradeSignal.fib_extension_levels` carry
the actual mode used and the raw extension ladder, for display/debugging.
See `README.md`'s "TP mode: ATR ladder (default) or structural levels" section.

---

## 7. One-way execution path: TRADING_MODE + the final NO-TRADE gate

Two independent, software-level safeguards sit between "a paper trade
qualified" and "a real order was sent" -- neither bypassable by anything
upstream (Claude's analysis, the entry checklist, the regime gate, the
circuit breaker all only ever produce a recommendation; none of them can
themselves authorize a live send):

```
TRADING_MODE=LIVE required (config.py / .env, default PAPER)
        |    independent of --live and the typed-YES prompt -- a stray
        |    --live on a machine still set to PAPER is refused outright
        v
--live passed AND TRADING_MODE=LIVE?  --NO--> refused before anything else runs
        |
       YES
        v
dry-run preview shown, human asked to type YES
        |
        v
FINAL NO-TRADE GATE (cdcx/no_trade_gate.py) -- re-validates EVERYTHING
from scratch, right here, not trusting any earlier gate still holds:

    paper_trade_result == PASS?
    human typed YES?
    risk% <= ceiling (2% default)?
    stop loss present & valid?
    every planned TP present & valid (adapts to the strategy's own ladder
        length -- 4 for trending, 2 for ranging)?
    timeframe confirmation held?
    withdrawal permission confirmed disabled?  <- HUMAN ATTESTATION, see below
    market data still fresh (not stale, default max 3 candles old)?
    no duplicate order already sent for this symbol recently?
        |
        +-- ANY single check fails --> BLOCKED, every failing reason shown,
        |                                logged to trading/paper/rejected/
        v
    ALL PASS
        v
  live bracket order sent to Crypto.com
```

**Withdrawal permission** is the one condition that needs a human, not a
program: Crypto.com's API (via `ccxt`) has no endpoint this project can use
to check whether an API key has withdrawal permission enabled --
`ccxt.cryptocom().has` doesn't advertise `fetchPermissions`. Rather than
skip the check, the gate **fails closed**: `--confirmed-no-withdraw-permission`
is required on the CLI, an explicit attestation that you checked manually
in your Crypto.com account's API-key settings. No attestation, no live
order, every time.

```bash
TRADING_MODE=LIVE python -m cdcx --symbol BTC/USDT --timeframes 1h,4h,1d,1w \
  --execute --balance 10000 --live --confirmed-no-withdraw-permission
```

See `README.md`'s "One-way execution path" section for the full detail and
more examples.

---

## 8. Other testing & validation surfaces

- **Offline backtester** (`cdcx/backtest/engine.py`) -- reuses the real
  signal engine, entry checklist, and risk sizing bar-by-bar. Regime-gated
  by default (Step 1 of live `--execute`: a TRANSITIONAL read blocks a
  trade there too, not just live) and circuit-breaker-gated by default --
  both were gaps in earlier versions of this backtester, fixed and
  regression-tested (`tests/test_backtest_regime_gate.py`,
  `tests/test_backtest_circuit_breaker.py`).
- **TradingView / Pine Script port** (`pine/cdcx_trend_core.pine`) -- a
  hand-ported `//@version=6` strategy for validating the trending-path core
  (EMA/ATR/RSI/ADX, 1.5x ATR stop, R-multiple TP ladder, risk-based sizing)
  directly in TradingView's own Strategy Tester. Multi-timeframe confluence
  and true Volume Profile POC/VAH/VAL aren't ported (documented
  limitations in the script header and README).
- **`--leverage`** -- looks up the exchange's real min/max leverage for a
  symbol's USD-margined perpetual before ever using `--live` (this project
  never sets leverage itself).
- **Live no-trade-gate testing** -- `TRADING_MODE` and `no_trade_gate.py`
  were both exercised directly against real live-fetched BTC/USD and
  XRP/USD data (real ATR, entry price, timestamps), confirming every
  failure mode (declined approval, missing withdrawal attestation, stale
  data, risk over ceiling, duplicate order) blocks independently with the
  correct reason. That same live XRP test surfaced a real bug: `stop_loss`/
  `take_profits` rounded to a flat 2 decimal places regardless of price,
  which collapsed 3 of 4 TP levels to the same price on a ~$1 asset. Fixed
  with significant-figure-based rounding (`engine._round_price`) -- see
  `README.md`'s "Fixes from live XRP/USD testing" section.
- **Past-week (168-bar) backtest testing** surfaced two more real bugs in
  `cdcx/backtest/engine.py`, both only triggered by a window short enough to
  end with a trade still open (rare at 1000 bars, routine at 168): a stale
  `_close_trade` import (renamed to `_close_size` when partial closes were
  added) crashed the backtest outright, and even after fixing that, a
  trade's cost/P&L was being priced once against its full original size at
  only the final exit price -- silently wrong for any trade that partially
  closed at TP1-3 first. Fixed with `apply_trade_costs_over_partial_closes`,
  which sums cost/P&L per actual exit slice. See `README.md`'s "Fixes from
  live XRP/USD testing" section for the full detail.
- **`--tp-mode structural` testing on XRP/USD** surfaced a real bug the same
  day the feature shipped (section 6): on the 1w timeframe, a genuinely
  wide `swing_high=3.19 / swing_low=0.99` range made `fibonacci.
  calculate_extension()`'s own floor clamp (its documented "never return
  <= 0" safety net) kick in for the far extension rungs, and those floored
  values -- `$0.0079` / `$0.0069`, essentially zero -- got offered as real
  TP candidates simply because they were technically "ahead of price."
  Fixed at the source (excluding any extension level that hit the floor)
  and with a source-agnostic `max_r_multiple` backstop in
  `risk.build_structural_tp_levels`. See `README.md`'s "Fixes from live
  XRP/USD testing" section.

---

## 9. Predictions market data (cdcx/predictions.py) -- not part of the trading pipeline

A thin, read-only client for the public **Crypto.com Predictions Market
Data API** (`data-api.crypto.com` -- a separate product from both the App
API and the Exchange API used everywhere above). Prediction markets are
binary-outcome contracts (sports, crypto price thresholds, elections)
priced by a live order book -- a YES share at `0.63` prices that outcome
at roughly 63%.

```
python -m cdcx --predictions [KIND]              # list events, e.g. NFL
python -m cdcx --predictions-search "super bowl"  # full-text search
python -m cdcx --predictions-contract <TICKER>    # live contract pricing
```

No API key required (anonymous, rate-limited by Crypto.com); an optional
`PREDICTIONS_API_KEY` (MDLA) raises the limit. These commands are
independent of `--symbol`/`--timeframe` and **not wired into `--execute`'s
trade decision** -- they don't feed section 2's pipeline, the paper
simulation, or any gate. See `README.md`'s "Predictions market data"
section for full detail.

---

## 10. Sequential MTF framework, ATR states, and the A+ setup

The trading pipeline in sections 1-9 is built around one sequential read
down the timeframes. This section names that sequence explicitly and shows
how ATR's three states (contraction / flat / expansion) route to three
separate strategies, all already implemented -- see `README.md`'s "The
sequential MTF framework, restated" and "A+ setup grading" sections for the
full module-by-module mapping.

```
                              1W  DIRECTION
                    weekly_bias() -- which side of the
                    weekly POC is price on (advisory bias,
                    not a hard gate)
                              |
                              v
                              1D  LOCATION
                    structure_levels.py -- POC / support /
                    resistance / FVGs: the zone the 4H
                    setup has to trade against
                              |
                              v
                              4H  STATE / SETUP
                    regime.py: TRENDING / RANGING / TRANSITIONAL
                    atr_state.py: contraction / flat / expansion,
                    and the transition between them (timing, not
                    direction)
                              |
              +---------------+---------------+
              |               |               |
       CONTRACTION          FLAT          EXPANSION
       -> Expansion                       -> pullback -> Expansion
              |               |               |
       Strategy A:       Strategy B:      Strategy C:
       breakout_retest /  ranging_strategy  breakout_retest /
       fvg_confluence     .py (HVA<->POC    fvg_confluence,
       (structure_        <->LVA rotation,  timed by the
       strategy.py)       TP1=POC,          "second_expansion"
                          TP2=range edge)    ATR read (don't
                                             chase the first move)
              |               |               |
              +---------------+---------------+
                              |
                              v
                              1H  TRIGGER
                    candlestick_patterns.py -- reversal/
                    continuation candle confirming the
                    direction the 4H setup implies
                              |
                              v
                    ATR TRANSITION CONFIRMS?
              (contraction_to_expansion / compression_release
                        / second_expansion)
                              |
                    +---------+---------+
                    |                   |
                   YES                  NO
                    |                   |
              setup_grade.py:     setup_grade.py:
               GRADE A+            GRADE A
                    |                   |
                    +---------+---------+
                              |
                              v
                          ENTRY
                              |
                              v
              Fib Trend Extension + POC/HVA/LVA targets
                    (risk.py's `--tp-mode structural`,
                     or the default ATR R-multiple ladder)
```

**ATR transition vocabulary** (`indicators/atr_state.py`'s
`AtrTransition.kind` -- every one of these is advisory context, read by
`entry_checklist.py` as a non-blocking `advisory=True` item, never a hard
gate):

```
Contraction -> Expansion              contraction_to_expansion   [TRIGGER]
Contraction -> Flat -> Expansion      compression_release        [TRIGGER]
Expansion -> cooldown -> Expansion    second_expansion           [TRIGGER]
Expansion, no prior cooldown          expansion_continuation
Expansion -> Contraction              expansion_to_contraction   (cooling)
Expansion -> Flat                     expansion_to_flat          (exhaustion?)
Plain contraction                     contraction                (prepare/wait)
Plain flat                            flat                       (rotation)
```

**A+ setup** (`cdcx/setup_grade.py`, printed automatically at the end of
`--structure`'s output): a structurally valid 1W/1D/4H/1H setup (`GRADE A`)
whose 4H ATR transition also confirms as one of the three `[TRIGGER]` kinds
above becomes `GRADE A+` -- optionally tightened further by
`confluence.py` / `confidence_scoring.py` results when supplied. Advisory
only, same as every other read in this section: never consulted by
`no_trade_gate.py` (section 7), never blocks or authorizes a live order.

---

## 11. Multi-timeframe summary table (cli.py / cli_equity.py's `_print_summary_table`)

Printed once per `--timeframes` run, one row per requested timeframe, using
raw indicator readings already computed in `engine.analyze_ohlcv()` --
`TradeSignal.adx_value` / `.rsi_value` / `.volume_ratio` -- not a second,
separately-configured calculation. ADX(17) and RSI(17) run on the same
period every other smoothed indicator in the engine uses
(`atr_ema_variant1.EMA_LENGTH`, not the textbook 14). VOL(17) is the last
CLOSED bar's volume divided by its own trailing 17-bar average -- same
window `structure_levels.py`'s breakout `volume_confirmed` check already
uses, so this doesn't introduce a fourth, inconsistent lookback. "Last
CLOSED bar," not simply the latest bar, is deliberate: confirmed live
(XRP/USD, 2026-09) that the exchange's most recent candle is frequently
still forming, so its volume-so-far understated the ratio (read near 0x
seconds after a new candle opened) versus TradingView's own last-closed-bar
volume for the same window. RSI/EMA/ADX are unaffected -- those are proper
running indicators, correctly live-updating every tick; only a ratio
against a fixed-length average breaks when its numerator is a partial bar.

```
=======================================================================================================
                                   MULTI-TIMEFRAME SUMMARY -- XRP/USD
=======================================================================================================
Timeframe   Score   Signal        Market    ADX(17)   RSI(17)   VOL(17)   ATR         Range
-------------------------------------------------------------------------------------------------------
1h          72      BUY           bullish   23.4      61.2      1.8x      expansion   no
4h          65      BUY           bullish   28.1      58.7      1.3x      flat        no
1d          50      NEUTRAL       neutral   19.6      49.3      0.9x      contraction yes
1w          40      NEUTRAL       neutral   15.2      46.8      0.7x      flat        yes
=======================================================================================================
```

`cli.py` (crypto path) and `cli_equity.py` (Robinhood/Webull path) each keep
their own `_print_summary_table`, deliberately kept in sync rather than
sharing one implementation -- see `_market_bias`'s docstring in both files.

---

## 12. BOS state (bos_state.py) -- distinguishing a break from what happened after it

`market_structure.py`'s `BREAK OF STRUCTURE` flag (`Bullish BOS` / `Bearish
BOS` / `None`) is a **stateless** check re-derived fresh on every call: "is
the latest close currently beyond the most recent labeled swing point?"
Confirmed live (XRP/USD, 2026-09): the exact same uptrend, no reversal in
between, printed `Bullish BOS` on one scan, `None` two scans later, then
`Bullish BOS` again -- not a bug, just what happens as the swing-pivot
window slides forward and relabels which point is "most recent." A `None`
reading right after a real break does NOT mean the break stopped
mattering.

`bos_state.py` answers the different question this flag can't: given the
specific swing point BOS most recently referenced, what has price actually
done *since* that break? It reuses `structure_levels.detect_breakout()` /
`detect_retest()` as-is -- both already level-agnostic (any price +
direction) -- pointed at the swing high/low instead of POC/VAH/VAL. No new
breakout/retest algorithm:

```
market_structure.analyze()
        |
        v
BREAK OF STRUCTURE flag (Bullish / Bearish / None)
        |
        v
bos_state.classify_bos_state()
  -- same direction as the flag when it's Bullish/Bearish;
     falls back to whichever side has a breakout at all,
     most recent by bar index, only when the flag reads None
        |
        v
  structure_levels.detect_breakout() against that swing level
        |
   +----+----+
   |         |
 none      found
   |         |
NO_BREAK   detect_retest()
                |
      +---------+---------+
      |         |         |
  no retest   held      failed
      |         |         |
CONTINUATION  RETEST   RETEST FAILED
              HELD     -- direction-dependent:
                          up-break failed   -> bearish reversal
                          down-break failed -> bullish reclaim
                          (a failed break is bearish news only
                          when the break itself was bullish)
```

Printed as one extra line in `structure_report.py`'s `MARKET STRUCTURE`
box (the `--structure` / `--structure-report` read), directly under
`BREAK OF STRUCTURE:` -- informational only, same as everything else in
that report: never consulted by `structure_strategy.py`'s LONG/SHORT
triggers or the confluence/execution gate (section 7). Example:

```
SWING STRUCTURE: LL / HH / HH / HL
BREAK OF STRUCTURE: Bullish BOS
BOS STATE: Continuation (bullish break of 1.319100, unchallenged)
```

---

## 13. Volume Profile setup classification (vp_setup.py) -- context only, Mode A

Labels the current situation relative to the Fixed Volume Profile's
POC/VAH/VAL as one of three named setups, or `none`:

- **POC Bounce** -- price recently traded outside the value area (above VAH
  or below VAL) and has now returned to sit at POC, a possible rejection
  point.
- **Value Area Reversal** -- price broke outside the value area (through
  VAH or VAL) and that break failed: price closed back through the level,
  reclaiming the value area.
- **Value Area Breakout** -- price broke outside the value area and is
  holding the break (retest held, or no retest yet).

This is **Mode A**: pure classification, added purely as context. It does
**not** feed `TradeSignal`'s score, direction bias, or the `--execute`
confluence gate -- same non-scoring status as `bos_state.py`'s BOS state
(section 12). Two later modes were scoped but deliberately not built yet:
Mode B (record whether the VP setup agrees with the existing signal,
still without changing entry/SL/TP) and Mode C (separate backtest
performance by setup type) -- both are natural follow-ons once Mode A has
been observed live for a while.

Reuses `structure_levels.detect_breakout()` / `detect_retest()` exactly as
`bos_state.py` does, pointed at VAH/VAL instead of a swing high/low. No new
breakout/retest algorithm:

```
volume_profile_fixed.analyze() -> POC / VAH / VAL
        |
        v
vp_setup.classify_vp_setup()
        |
        v
  detect_breakout() against VAH (up) and VAL (down)
   -- most recent by bar index, if either fired
        |
   +----+----+
   |         |
 none      found
   |         |
 (fall     detect_retest()
 through          |
  to POC    +------+------+
 check)     |      |      |
        no retest  held  failed
            |       |      |
      VALUE_AREA  VALUE_AREA  VALUE_AREA_REVERSAL
      BREAKOUT    BREAKOUT    (failed break -> price
      (unretested)(confirmed)  reclaimed the value area)
   |
   v (only reached when no VAH/VAL breakout fired)
 price within 0.5*ATR of POC, after an
 excursion outside the value area in the
 last 40 bars (older than the 20-bar
 breakout window above, so the two checks
 don't double-fire on the same move)
   |
   v
 POC_BOUNCE (direction = back toward the
 side price came from)
```

Printed as one extra line in `structure_report.py`'s `MARKET STRUCTURE` box,
directly under the `-> price is ...` value-area location line. Also carried
on `TradeSignal.vp_setup_type` / `.vp_setup_direction` purely so it lands in
`journal.py`'s `write_signal()` records for later review, per the flowchart
proposal's "don't gate on it yet, just log it" recommendation. Example:

```
PRICE:  1.5167
POC:    1.41508
VAH:    1.49779   (value area high)
VAL:    1.36781   (value area low)
  -> price is ABOVE the value area (beyond VAH) -- outside the accepted range
VP SETUP: Value Area Breakout (bullish)
```

---

## 14. Entry location state (entry_location.py) -- "good market, wrong spot" vs "bad market"

A bare `NO TRADE` reads the same whether nothing about the market lines up,
or every single gate confirms except one. Confirmed live (XRP/USD,
2026-09-22): all 4 timeframes TRENDING and bullish, confluence at 100%
(`Strong Buy -- 100% confidence (1H, 4H, 1D, 1W bullish)`), ATR expanding on
every timeframe, BOS/FVG/Volume Profile all confirming -- and still
correctly `NO TRADE`, because `entry_checklist.py`'s Fibonacci item never
confirmed. That's a fundamentally different situation from "the trend
disagrees across timeframes" or "the regime is transitional," but both
printed the identical `NO TRADE`.

`entry_location.py` narrates which case it is, purely for display/journal --
it never feeds back into `confluence.should_execute` or
`entry_checklist.ChecklistResult.all_passed`, and never touches entry price,
stop-loss, TP1-4, R:R, or position sizing:

```
confluence.should_execute?
        |
   +----+----+
   |         |
  no        yes
   |         |
INVALID   regime == "trending"?
(no MTF        |
 direction  +----+----+
 at all)    |         |
           no        yes
            |         |
         INVALID   checklist.all_passed?
        (no edge         |
         to trade)  +----+----+
                    |         |
                   yes       no
                    |         |
               CONFIRMED   which items failed?
                                |
                    +-----------+-----------+
                    |                       |
             only Fibonacci /        any OTHER item
             Volume Profile          (trend, risk,
             ("WHERE" items)          existing position)
                    |                       |
               DEVELOPING               INVALID
          ("good market, wait      (a non-location
           for entry location")     problem, not just
                                     the entry spot)
```

Fibonacci and Volume Profile are classified as the checklist's two location
("WHERE") items, vs. ATR/EMA trend, risk, and position state as
context/administrative ("WHETHER") items -- if one of those latter items is
what's failing, calling it "just waiting for a pullback" would be wrong;
the direction or the account state itself isn't clean.

Printed as one line (plus reasons) right after the `ENTRY CHECKLIST` box in
`cli.py`'s `--execute` output, and also at the two earlier NO-TRADE exit
points (confluence not reaching 2-timeframe majority; entry-timeframe
regime not trending) so every NO-TRADE report in the CLI carries this
context, not just the one after the checklist. Example (the motivating
Run 21 case):

```
ENTRY LOCATION: NO TRADE -- ENTRY LOCATION NOT CONFIRMED (WAIT)
  Direction confirmed (confluence + trending regime), entry location not yet confirmed: Fibonacci level confirms pending.
```

---

## 15. ATR alignment and the Volume Profile hierarchy (mtf_context.py) -- context only, Mode A

A direct follow-on to entry_location.py, adding the two remaining pieces
from the same review: ATR alignment across all 4 timeframes, and labeling
each timeframe's vp_setup (section 13) with its structural role in the
1W -> 1D -> 4H -> 1H hierarchy this codebase already uses everywhere else
(structure_report.py's "STRUCTURE -- 1W (major structure)" /
"STRUCTURE -- 4H (primary setup)" headers). Both are pure display -- neither
feeds score, confluence, the entry checklist, or entry_location.py's
classification.

**ATR alignment** counts how many of the 4 timeframes are currently in ATR
Expansion (`TradeSignal.labels["atr_expansion"]`, the same label already
shown in each timeframe's own indicator breakdown and the MTF summary
table's `ATR` column -- one source of truth, reused rather than
re-derived). Confirmed live (XRP/USD, 2026-09-22): `4/4 timeframes
expanding` is a genuinely rare, notable state, not something to treat as
routine. ATR answers WHEN a market is actually moving; alignment describes
breadth of that movement, never WHERE to enter or WHETHER a trade is valid.

**Volume Profile hierarchy** re-labels vp_setup.py's per-timeframe output
with its role:

```
1W -> macro location             (where price sits vs. the long-run range)
1D -> major trend/value location
4H -> setup location
1H -> entry-area location
```

and flags when the slowest timeframe carrying a VP direction disagrees with
the fastest one -- confirmed live in the same run: 1H/4H/1D all read "Value
Area Breakout (bullish)" while 1W still read "Value Area Breakout
(bearish)" (price still below the weekly VAL):

```
VOLUME PROFILE HIERARCHY:
  1W [macro location]: Value Area Breakout (bearish)
  1D [major trend/value location]: Value Area Breakout (bullish)
  4H [setup location]: Value Area Breakout (bullish)
  1H [entry-area location]: Value Area Breakout (bullish)
  NOTE: 1H Volume Profile is bullish while 1W (macro location) is still bearish -- the higher-timeframe location has not confirmed the move.
```

This is short-term strength with an unconfirmed higher-timeframe location,
not a contradiction to alarm over -- the same "good market, entry location
not confirmed" framing entry_location.py already applies at the checklist
level, here applied specifically to the VP hierarchy.

Printed once, right after the `MULTI-TIMEFRAME SUMMARY` table in `cli.py`'s
`--timeframes` output (unconditional, same as the summary table itself --
not gated behind `--execute`).

**Also wired into `cli_equity.py`'s `--timeframes` path**, right after that
module's own `_print_summary_table` -- these two functions only need a
`dict[timeframe, TradeSignal]`, no `ConfluenceResult` or `ChecklistResult`,
so they carry over to the equity CLI with zero equity-specific code.
`vp_setup.py`'s and `bos_state.py`'s own lines (`VP SETUP:` / `BOS STATE:`)
already printed there automatically before this, since both live inside
`engine.py`/`structure_report.py` themselves, which `cli_equity.py` already
reuses unchanged (see that module's own docstring). Section 14's
`entry_location.py` classification and section 16's `ENTRY LOCATION
ASSESSMENT` report were deliberately NOT ported to `cli_equity.py` --
both need a `ConfluenceResult`/`ChecklistResult`, i.e. exactly the
crypto-tuned confluence/entry-checklist state machine `cli_equity.py`'s
docstring already explains it intentionally doesn't have yet ("that
machinery was built and tuned against crypto ATR/regime behavior and
hasn't been validated for equities"). Building that for equities is a real
architectural addition, not a mechanical port.

---

## 16. Entry location Phase 2: DEVELOPING substates + the ENTRY LOCATION ASSESSMENT report

A direct Phase 2 follow-on to section 14, requested after reviewing section
14/15 live: DEVELOPING alone answers "is the market good" but not "waiting
on exactly what, and what changes that." Two additions, both still pure
narration -- neither touches `confluence.should_execute`,
`entry_checklist.ChecklistResult.all_passed`, or any entry/SL/TP/R:R/risk
value.

**DEVELOPING substates** -- subdivides DEVELOPING by exactly which
location item(s) (section 14's `LOCATION_ITEM_NAMES`) are still pending:

```
WAIT_FIB              -- only Fibonacci pending
WAIT_VOLUME_PROFILE   -- only Volume Profile pending
WAIT_FIB_AND_VP       -- both pending
```

Each substate carries a `NEXT_TRIGGER_BY_SUBSTATE` hint -- the specific
market event that would flip it to CONFIRMED (e.g. WAIT_FIB: "Price pulls
back into a Fibonacci retracement level that confirms this direction.").

`WAIT_RETEST` / `WAIT_BOS` / `WAIT_CANDLE_CONFIRMATION` were proposed
alongside these three but deliberately not built: entry_checklist.py has no
BOS-retest or candlestick-pattern item that blocks `all_passed` today
(bos_state.py and candlestick_patterns.py are informational, not gates), so
a substate for either would describe a condition the code doesn't actually
enforce. If either becomes a real checklist gate, add its substate the same
way.

**ENTRY LOCATION ASSESSMENT** -- a `cli.py`-level report (`_format_entry_assessment`)
that composes confluence.py / mtf_context.py (ATR alignment + VP hierarchy,
section 15) / entry_checklist.py / bos_state.py / entry_location.py's
already-computed results into one "why not enter, and what would change
that" block, printed in `_handle_trending_path` right after the entry
checklist and entry-location line. `bos_state` is (re)computed here from
the entry timeframe's raw OHLCV the same way `structure_report.py` already
does it -- consistent with that module's own "computes nothing new, reuses
the same indicator modules" precedent rather than plumbing a duplicate
computation through TradeSignal. Example (the same Run 21 shape, live):

```
================================================
       ENTRY LOCATION ASSESSMENT
================================================

Market Direction:        BULLISH
MTF Confluence:          90% (3/4)
Trend Regime:            TRENDING
ATR Alignment:           3/4 EXPANSION

Volume Profile:
  1W: macro location               BEARISH (Value Area Breakout)
  1D: major trend/value location   BULLISH (Value Area Breakout)
  4H: setup location               BULLISH (Value Area Breakout)
  1H: entry-area location          BULLISH (Value Area Breakout)
  NOTE: 1H Volume Profile is bullish while 1W (macro location) is still bearish -- the higher-timeframe location has not confirmed the move.

FVG:                     CONFIRMED (Bullish FVG)
BOS:                     Retest Failed -- bullish reclaim (bearish break of 1.492000 invalidated)
Fibonacci:               ❌ NOT CONFIRMED
Volume Profile (entry):  ✅ CONFIRMED

ENTRY LOCATION:          DEVELOPING

WAIT CONDITION:
  -> WAIT_FIB
  -> Price pulls back into a Fibonacci retracement level that confirms this direction.

TRADE STATUS:
  -> NO TRADE -- WAIT

IMPORTANT:
  Entry / SL / TP / R:R / position sizing unchanged
================================================
```

`_handle_trending_path` gained two new parameters to support this,
`raw_data` (the entry timeframe's OHLCV, already fetched one call up in
`_handle_execute`) and `results` (the full per-timeframe `TradeSignal`
dict, needed by `mtf_context.build_atr_alignment`/`build_vp_hierarchy` --
`signals_by_tf`, already a parameter here, only carries the signal *label*
strings, not the TradeSignal objects those two functions need).

---

## 17. Equity gets the same confluence + checklist + entry_location pipeline

Sections 14/15/16 were built crypto-only; `cli_equity.py`'s own docstring
explicitly said the confluence/checklist state machine "hasn't been
validated for equities" and was left out on purpose. Requested as a direct
follow-on to actually do that validation now -- built by REUSING cli.py's
`confluence.py` / `entry_checklist.py` / `entry_location.py` unchanged
(none of the three had any crypto-specific assumption baked in; they
operate on `TradeSignal`/strings/regime labels, not an exchange), not by
reimplementing equity-specific versions.

`cli_equity.py` now has two distinct `--execute` paths, chosen by which
flag was given:

```
--timeframe (single) --execute
        |
        v
  engine.py's own execution_signal (regime + R:R gate)
        |
        v
  PAPER trade  (unchanged since before this update)

--timeframes (2+) --execute
        |
        v
  confluence.evaluate_confluence()        <- same function cli.py calls
        |
        v
  regime recompute (higher_timeframes_aligned=True) on the
  confluence-selected entry timeframe
        |
        v
  entry_checklist.evaluate_entry_checklist()   <- same function cli.py calls
        |
        v
  entry_location.classify_entry_location() + format_entry_assessment()
        |
        v
  CONFIRMED -> PAPER trade   |   DEVELOPING/INVALID -> no trade
```

To support the entry-timeframe regime recompute and BOS state without an
extra live refetch, `main()`'s `--timeframes` loop now also retains
`raw_data_by_tf: dict[tf, OHLCV]` (previously the fetched OHLCV was
discarded after building each timeframe's `TradeSignal`, except under
`--structure-report`) -- passed into the new `_handle_execute_confluence()`.

`format_entry_assessment()` moved from a `cli.py`-private function into
`entry_location.py` itself (still called the same way from `cli.py`) so
both CLIs share one implementation instead of two copies that could drift.

Still crypto-only, on purpose, even after this: `circuit_breaker.py`,
`no_trade_filter.py`, `no_trade_gate.py`, `journal.py`'s live-trading audit
trail, `confidence_scoring.py` -- none of cli.py's live-ORDER safety layers
apply here, because there is no live equity order path to protect;
`--execute` on either equity path only ever opens a locally tracked PAPER
trade via `trade_manager.open_trade()`, exactly as it always has.

---

## 18. Source of truth

This file is a point-in-time backup snapshot. `README.md` in the project
root is authoritative and updated alongside the code -- if the two ever
disagree, trust `README.md`.
