# Watcher re-armed + test isolation (2026-10-05) -- commits 6685587, 7781c03

## 1. XRP watcher: config-driven, re-armed with cdcx-style retests (6685587)
- **Config file.** Levels moved to `cdcx-cli/trading/alerts/xrp_bos_watch_config.json` (force-added; `trading/` is
  gitignored). The watcher re-reads it every poll.
- **Retest rule, matching cdcx:**
  - HELD = a later bar dips into the zone and closes back above the level;
  - FAILED = only a close beyond the level by the 0.25×ATR margin.

  The old rule fired FAILED on Oct 4 09:00 for a 0.0004 dip that the next bar reversed.
- **Re-armed map (Oct 5 ~00:50 UTC):**
  - bullish: break-even 1.532 (1H, inclusive), weekly VAL 1.5379 (1H, then 4H acceptance), new high 1.5285,
    4H 1.5599 / 1D 1.5735;
  - retest: 1H 1.5096 (zone up to 1.5132, fails below 1.5078);
  - bearish: 4H VP-BOS failure below 1.4913, 1H 1.4969 / 4H 1.4410 / 1D 1.4265;
  - paper stop and TP1 touches.
- **Verified:**
  - dry run: a shallow dip sent no alert, a zone dip with a close above sent HELD, and a close at 1.5320 fired BREAK-EVEN;
  - live: the old watcher was stopped and its state archived (`xrp_bos_watch_state.20261004.json`); the supervisor
    started the new one; RE-ARMED was delivered (Telegram msg 201).

## 2. Tests no longer write into the real journal (7781c03)
- **The bug.** `settings.trading_journal_dir` defaults to `"trading"`, so tests reaching `cdcx.journal` wrote fixture
  trades into the real `cdcx-cli/trading/paper/`. These included a $65,000 BTC/USDT order on a $10k account, which
  looked like a real BTC paper trade. There were 486 such files by Oct 4, plus 11 per run.
- **The fix.** New `tests/conftest.py` (autouse) points the journal and the trade log at each test's `tmp_path`.
- **Verified:** 650 passed, journal file count unchanged across a full run, real `cdcx_trades.json` unchanged.
- **Not done:** the junk files already in `trading/paper/` were left in place (nothing deleted).

Protected params: unchanged.
