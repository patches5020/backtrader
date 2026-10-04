# XRP/USD BOS trigger-map watcher → Telegram alerts (2026-10-04) -- commit b26455d

## Request
"Send me an alert to my phone when those conditions of the trigger map hit." The map is Telegram msg 177,
2026-10-04 02:33 UTC.

## What
New `cdcx-cli/trading/alerts/xrp_bos_trigger_watch.py`. `trading/` is gitignored, so only this script is force-added;
its state, log and stdout files stay untracked.
- Polls Crypto.com every 60 s and evaluates **closed bars only**, and only bars that close after it arms.
- Uses cdcx's BOS rule: a close beyond the swing level by 0.25× ATR.
- Each alert fires once:

  | Alert | Bullish | Bearish |
  |---|---|---|
  | 15m early warning | > 1.4916 | < 1.4862 |
  | 1H | > 1.4973 | < 1.4827 |
  | 4H | > 1.5599 | < 1.4401 |
  | 1D | > 1.5805 | < 1.4456 |
  | 1H retest | held / failed on a later bar | held / failed on a later bar |
  | Paper trade 5a75fd5f | TP1 1.8569 touched | stop 1.3843 touched |

- Each alert includes the bar's OHLC, volume vs its 20-bar average (volume-confirmed yes/no), cdcx candlestick
  patterns on that bar, the trade's P&L at that close, and the next step on the map.
- Sends through `cdcx.telegram_send.send_message` (send-only, tagged `cdcx-telegram` / `XRP/USD`, so it never becomes
  `latest_report`). It never reads Telegram, never trades, never touches the paper trade or the gate.
- Runs up to 7 days, or until all the 4H/1D triggers fire. State persists in `xrp_bos_watch_state.json`, so a restart
  doesn't repeat alerts.

## Verification
- Dry run with fake bars and Telegram stubbed out. It caught a bug: the retest alert fired on the break bar itself,
  because it compared wall time with bar time. Fixed by storing the break bar's timestamp; re-run confirmed the order
  break → retest on a later bar → opposite break, each once.
- Armed live at 2026-10-04 02:50:49 UTC; the ARMED message was delivered (Telegram msg 179). Process running in WSL.

No cdcx package code changed. Protected params: unchanged.
