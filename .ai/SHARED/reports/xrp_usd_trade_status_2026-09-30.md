# XRP/USD — paper trade status + MTF summary — 2026-09-30 20:25 UTC

Source: `cdcx-ai --update-trades` and `cdcx-ai --symbol XRP/USD --timeframes 1h,4h,1d,1w --structure`
(raw output: `xrp_usd_mtf_2026-09-30.txt`), plus TradingView chart CRYPTOCOM:XRPUSD (same Crypto.com feed).
Price at snapshot: **1.4945**. PAPER mode only; analysis, not a trade signal.

## Open paper trade `5a75fd5f` (log: `cdcx-cli/cdcx_trades.json`)
| Field | Value |
|---|---|
| Direction | LONG, opened 2026-09-24 17:40 UTC |
| Entry / stop | 1.5320 / 1.38430654 (1.5 × 1D ATR 0.0985) |
| TP1–TP4 | 1.85693 / 1.916 / 2.00462 / 2.19662 (25% each) |
| Size / risk | 135.4156 XRP / $20 (2% of $1,000) |
| Confluence at open | 1D + 1W (score 7) |
| cdcx update | "no rule triggers (no TP/stop/give-back events)", log unchanged |
| Unrealized | **−$5.08 = −0.25R** (−2.45% price, −0.51% account); realized $0.00 |
| Best / worst since open | 1.6297 (Sep 25) +0.66R / 1.4654 (Sep 29) −0.45R |
| Largest open-profit drop | −$17.60 (0.88R), Sep 25 12:00 → Sep 28 07:00 (1H closes) |
| Distance to stop / TP1 | −7.37% / +24.25% |

## Timeframes
| TF | Regime | Direction | ADX | Value area (POC / VAH / VAL) | Price location | BOS |
|---|---|---|---|---|---|---|
| 1H | TRANSITION | −27 | 10.7 | 1.4952 / 1.5230 / 1.4833 | inside, below POC | none; raw bear flag 1.4887 (missed 0.25×ATR margin) |
| 4H | TRANSITION | −24 | 16.9 | 1.4952 / 1.6149 / 1.3925 | inside, below POC | none |
| 1D | TRANSITION (6/10) | +100 | 40.6 | 1.0900 / 1.4173 / 1.0008 | above VAH (bull breakout) | none |
| 1W | TRANSITION | +79 | 25.5 | 2.2785 / 3.2031 / 1.6181 | below VAL | none |

ATR expanding 0/4. VP-BOS confirmed 0/4. Setup check: NO TRADE. Advisory AVP bullish rejection: FAILED on both 4H and 1H.
1D unfilled bullish FVG now 1.3191–1.3928; price traded into the old 1.4176–1.4920 gap (low 1.4654), so cdcx no longer lists it.

## Key levels
1.5320 entry · 1.5129 Fib 78.6% · **1.4945 price** · 1.4887 1H swing low · 1.4841 day low ·
1.4705 1D EMA · 1.4654 low since entry · 1.4173 1D VAH (breakout retest) · 1.3925 4H VAL · 1.3843 stop

## Conditional paths (not predictions)
- **Pressure:** 1H bearish BOS (close < ~1.4845), then a daily close below EMA 1.4705 → 1.417 retest in play.
- **Relief:** daily close back above 1.5129–1.532 (ends six lower-high rejections since Sep 25), then ATR expansion + daily bullish BOS toward TP1.

## Corrections to the Sep 29 ChatGPT assessment
- It used Sep 29 data (price 1.5026) and didn't cover the open trade.
- Its 4H value area (1.28987 / 1.51228 / 1.27276) matches no cdcx run here. 1.51228 was the 4H **POC** on Sep 29.
- "Range 11/10" is off-scale (0–10). The 1D candles were Doji + Bullish Harami, not Hammer.
- The "~$1.54" Crypto.com page price matches the 13:00 UTC high (1.5438), not the 20:25 feed price (1.4945).
- The VP-BOS timing bug is unverified. Treat it as an open item.
