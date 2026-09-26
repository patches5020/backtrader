# ATR-Transition Entry Timing — Flowchart

New pieces from this update are marked `NEW`. Everything else is the
existing pipeline, unchanged.

```mermaid
flowchart TD
    A["1W/1D/4H/1H OHLCV fetched"] --> B["regime.analyze()\nADX + EMA(17) slope + Value Area position\n+ ATR state + higher-TF alignment + reversals"]

    B -->|trend_score >= 8| C["TRENDING"]
    B -->|range_score >= 8| D["RANGING"]
    B -->|neither| E["TRANSITIONAL\nHARD NO-TRADE"]

    C --> F["confluence.evaluate_confluence()\n1W/1D/4H/1H directional agreement"]
    F -->|should_execute| G["entry_checklist.evaluate_entry_checklist()"]
    F -->|not enough agreement| E

    subgraph G["entry_checklist.evaluate_entry_checklist()"]
        direction G_TB
        G1["EMA/ATR trend confirms"]
        G2["Fibonacci retracement confirms"]
        G3["FVG confirms"]
        G4["Volume Profile confirms (fixed or anchored)"]
        G5["Risk <= 2%"]
        G6["No existing open position"]
        G7["NEW: ATR transition timing (advisory)\ncontraction-to-expansion OR second-expansion\n= [INFO] trigger present\notherwise = [NOTE], does NOT block"]
        G1 & G2 & G3 & G4 & G5 & G6 -->|all required items pass| GPASS["all_passed = True"]
        G7 -.->|informational only, excluded from all_passed| GPASS
    end

    GPASS --> H{"Bollinger overextension guard"}
    H -->|extended| E
    H -->|ok| I["risk.build_position_plan()"]
    I --> J["no_trade_filter.check_no_trade_filter()"]
    J -->|blocked| E
    J -->|clear| K["confidence_scoring.calculate_weighted_confidence()"]
    K --> L["OPEN TRADE"]

    D --> M["ranging_strategy.evaluate_ranging_setup()\nRSI + rejection candle + edge-of-range location"]
    M -->|valid| N["NEW: print ATR transition read (advisory)\nMode 2 expects FLAT -- an expansion read here\nis an early heads-up the range may be breaking"]
    N --> J
    M -->|not valid| E

    O["structure_strategy.evaluate_structure_setup()\n(1W/1D/4H/1H combined report, separate command)"] --> P["Header:\n1W bias vs weekly POC\nNEW: 4H ATR transition line"]
    P --> Q{"breakout_retest LONG\nfvg_confluence LONG\nbreakdown_retest SHORT"}
    Q -->|1H candlestick confirms| R["SETUP: LONG/SHORT"]
    Q -->|no trigger fires| S["NO TRADE"]

    classDef new fill:#2f6f4f,stroke:#1c4530,color:#fff;
    class G7,N,P new;
```

## Reading this

- **Nothing new blocks a trade.** Both `NEW` additions (`G7` in the
  checklist, and the header line in `structure_strategy`) are advisory:
  they report what the ATR sequence (`atr_state.py`) is doing —
  `contraction -> expansion` (Mode 1 breakout trigger) or a confirmed
  `expansion -> cooldown -> expansion` ("second expansion", the
  higher-quality entry that isn't chasing the first move) — without
  gating `all_passed` / `valid`.
- **Existing gates are untouched**: EMA/ATR trend, Fibonacci, FVG, Volume
  Profile, risk %, existing-position check, the Bollinger overextension
  guard, the no-trade filter, and weighted confidence scoring all work
  exactly as before this change.
- The **ranging path** (Mode 2) gets the ATR read printed as a standalone
  heads-up rather than folded into `ranging_strategy`'s own pass/fail
  checks, since a flat ATR is already implicit in "ranging" — the useful
  signal here is an *early* departure from flat.
