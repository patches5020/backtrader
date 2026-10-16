#!/usr/bin/env bash
# One-shot (user request 2026-10-16): re-arm the XLM/USD VP plans after the current arming
# expires (2026-10-17 15:22:50Z). Waits for the running watcher to log "watcher finished"
# so the new "armed" line is the log's last line and cdcx_autostart.sh restarts the watcher.
set -u
cd /mnt/c/Users/patch/my-trade/backtrader-repo/cdcx-cli/trading/alerts
LOGF=xlm_vp_plan_watch.log
EXPIRES=$(date -d "2026-10-17T15:22:50Z" +%s)
while [ "$(date +%s)" -lt "$EXPIRES" ]; do sleep 60; done
for _ in $(seq 1 30); do   # the watcher polls every 5 min; give it up to 30 min to exit
  tail -1 "$LOGF" | grep -q "watcher finished" && break
  sleep 60
done
echo "$(date -u '+%Y-%m-%d %H:%M:%SZ') rearm_xlm_vp_once: re-arming" >> rearm_xlm_vp_once.log
/mnt/c/Users/patch/my-trade/bin/python xrp_vp_plan_watch.py --symbol XLM/USD --arm >> rearm_xlm_vp_once.log 2>&1
echo "$(date -u '+%Y-%m-%d %H:%M:%SZ') rearm_xlm_vp_once: done (exit $?)" >> rearm_xlm_vp_once.log
