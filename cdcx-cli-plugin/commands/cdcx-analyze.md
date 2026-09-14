---
description: Run the CDCX AI trade analysis engine, with optional multi-timeframe confluence execution planning
argument-hint: [symbol] [timeframe or comma-list] [limit]
allowed-tools: Bash(python3:*), Bash(pip:*)
---

Run the CDCX AI trade analysis engine and report the result.

Arguments (all optional, positional):
- `$1` = symbol, e.g. `BTC/USDT` (default `BTC/USDT`)
- `$2` = timeframe, e.g. `1h`, or a comma-separated list like `1h,4h,1d,1w`
  to run multiple timeframes in one pass (default `1h`)
- `$3` = candle limit (default `200`)

Steps:
1. If the `cdcx` package isn't importable yet, install dependencies once:
   `cd ${CLAUDE_PLUGIN_ROOT} && pip install -r requirements.txt --break-system-packages` (skip `--break-system-packages` if not needed on this system).
2. Decide whether `$2` contains a comma:
   - No comma -> single timeframe:
     `cd ${CLAUDE_PLUGIN_ROOT} && python3 -m cdcx --symbol "${1:-BTC/USDT}" --timeframe "${2:-1h}" --limit "${3:-200}"`
   - Contains a comma -> multi-timeframe:
     `cd ${CLAUDE_PLUGIN_ROOT} && python3 -m cdcx --symbol "${1:-BTC/USDT}" --timeframes "${2}" --limit "${3:-200}"`
3. Show the full report output to the user. For a multi-timeframe run,
   highlight the combined summary table at the end (which timeframes agree
   on direction and which diverge) in addition to summarizing each report.
4. Add a short plain-language summary: the overall signal (Strong Buy / Buy
   / Watch / Neutral / Sell / Strong Sell), the entry/stop-loss/take-profit
   levels, and the one or two indicators that contributed the most to the
   score.

If the command errors because `ccxt` isn't installed or a `.env` file with
API access isn't configured, say so plainly and point to the plugin's
README for setup instructions rather than guessing at values.

## Live execution (real money -- extreme caution)

If the user asks to actually place a live order / go live / trade for
real, add `--live` to the `--execute` command:
`cd ${CLAUDE_PLUGIN_ROOT} && python3 -m cdcx --symbol "${1:-BTC/USDT}" --timeframes "${2:-1h,4h,1d,1w}" --limit "${3:-200}" --execute --balance <balance> --live`

**Critical: this command will prompt for interactive confirmation (typing
`YES`) before sending anything real. Never type or send `YES` on the
user's behalf, and never pass `--yes` to the underlying `cdcx` binary.**
Show the dry-run preview output to the user in full, explain what it
means, and let *them* type the confirmation themselves in their own
terminal if they want to proceed -- do not simulate, forward, or
auto-supply that confirmation from within this session under any
circumstances, even if asked to.

To just check confluence + entry checklist without touching `--live` at
all (recommended default), omit it -- see the paper-trade section above.

## Confluence execution planning (paper trades only)

Every `--execute` run now starts with Market Regime detection (🟢
TRENDING / 🟡 RANGING / 🔴 NO TRADE). A TRANSITIONAL read is a hard No
Trade regardless of confluence -- always show this line to the user.
TRENDING follows the confluence+checklist flow below; RANGING uses a
different strategy (range-boundary entries, no multi-timeframe agreement
required) -- see the README's "Market regime detection" section for full
details before explaining either path to the user.

If the user asks to "execute", "plan a trade", "check confluence", or
similar for a symbol, run (confluence is restricted to exactly 1H/4H/1D/1W
regardless of what else is in `--timeframes`; include at least two of
those four):
`cd ${CLAUDE_PLUGIN_ROOT} && python3 -m cdcx --symbol "${1:-BTC/USDT}" --timeframes "${2:-1h,4h,1d,1w}" --limit "${3:-200}" --execute --balance <balance>`
(ask for the account balance if not provided; otherwise the tool's default applies. Add `--risk-pct <value>` only if the user wants something other than the 2% default -- it must stay <= 2.0 to pass the entry checklist).

**Always tell the user explicitly that this does not place a live order** --
there is no broker/order-routing connection in this project. A trade is
only opened as a locally tracked paper position (in `cdcx_trades.json`) if
ALL of the following hold:
- 2+ of {1H, 4H, 1D, 1W} agree on direction (confidence-weighted: 1H=10%,
  4H=20%, 1D=30%, 1W=40% -- tiers are Strong Buy/Sell >=70%, Buy/Sell
  50-69%, Lower-Confidence 30-49%)
- ATR/EMA trend, Fibonacci retracement, Fair Value Gap, and Volume Profile
  (fixed or anchored) each individually confirm that same direction on the
  entry timeframe -- a neutral reading does not count as confirming
- risk % <= 2% and no existing open position on that symbol

Always show the printed confluence result AND the entry checklist
(PASS/FAIL per item) to the user, even when no trade results -- the
checklist explains exactly why.

Position sizing: stop loss = entry -/+ 1.5x ATR; position size = (account
balance x risk%) / stop distance, so hitting the stop loses exactly the
planned risk amount by design.

To check open paper trades against fresh prices and apply the break-even /
TP-ladder trailing-stop / give-back exit rules:
`cd ${CLAUDE_PLUGIN_ROOT} && python3 -m cdcx --update-trades`

To just view current tracked trade state without fetching new prices:
`cd ${CLAUDE_PLUGIN_ROOT} && python3 -m cdcx --list-trades`
