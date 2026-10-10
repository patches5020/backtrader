#!/usr/bin/env bash
# Supervisor for the cdcx background services in WSL: starts each one if it is
# not running, re-checks every 60 s, and by staying alive keeps WSL from
# shutting the distro down (an idle distro would kill the services).
#
# Run by the Windows scheduled task "cdcx-autostart" at logon (registered by
# scripts/register_cdcx_autostart.ps1), hidden, via:
#   conhost.exe --headless wsl.exe -d Ubuntu-26.04 -- bash /mnt/c/Users/patch/my-trade/backtrader-repo/scripts/cdcx_autostart.sh
#
# - Telegram bot (cdcx-telegram bot): the ONLY getUpdates reader for
#   @patches5020bot -- never started while one is running (the bot also backs
#   off on a 409 if another reader somehow exists).
# - XRP/USD BOS trigger watcher: alert-only, send-only; resumes from its state
#   file (fired alerts are not repeated) and is left stopped once it finished.
# - VP plan watchers, one process per symbol (XRP/USD; XLM/USD via --symbol), each with
#   bullish + bearish plans: alert-only, send-only;
#   asks permission on Telegram when all 12 requirements of a plan are met,
#   never executes by itself.
# - Each service is (re)started at most once per 5 minutes, so a crash loop
#   can't hammer Telegram or the exchange.
set -u
CDCX=${CDCX:-/mnt/c/Users/patch/my-trade/backtrader-repo/cdcx-cli}   # overridable for tests only
BIN=${BIN:-/mnt/c/Users/patch/my-trade/bin}
LOG=$CDCX/trading/autostart.log
MIN_RESTART_S=${MIN_RESTART_S:-300}
declare -A LAST_START=()
declare -A REPORTED=()
ts() { date -u '+%Y-%m-%d %H:%M:%SZ'; }

running() {  # the real python process -- not a shell whose command line merely mentions it
  ps -eo args | grep -E "^$BIN/python3? " | grep -qE "$1"
}

start_once() {  # name, pattern, workdir, logfile, command...
  local name=$1 pattern=$2 dir=$3 out=$4; shift 4
  local now; now=$(date +%s)
  if running "$pattern"; then
    [ -z "${REPORTED[$name]:-}" ] && echo "$(ts) $name running" >>"$LOG"
    REPORTED[$name]=1
    return
  fi
  if (( now - ${LAST_START[$name]:-0} < MIN_RESTART_S )); then
    return
  fi
  (cd "$dir" && setsid nohup "$@" >>"$out" 2>&1 </dev/null &)
  LAST_START[$name]=$now
  REPORTED[$name]=
  echo "$(ts) $name started" >>"$LOG"
}

watcher_finished() {  # ended its 7-day window, or all 4H/1D triggers fired
  tail -1 "$CDCX/trading/alerts/xrp_bos_watch.log" 2>/dev/null | grep -q "watcher finished"
}

mkdir -p "$CDCX/trading/alerts"
echo "$(ts) autostart supervisor up (pid $$)" >>"$LOG"
while true; do
  start_once "telegram bot" "cdcx-telegram bot|cdcx\.telegram_bot" "$CDCX" "$CDCX/trading/telegram_bot.log" \
    "$BIN/cdcx-telegram" bot
  if ! watcher_finished; then
    start_once "xrp bos watcher" "xrp_bos_trigger_watch\.py" "$CDCX/trading/alerts" \
      "$CDCX/trading/alerts/xrp_bos_watch.stdout" "$BIN/python" xrp_bos_trigger_watch.py
  fi
  if ! tail -1 "$CDCX/trading/alerts/xrp_vp_plan_watch.log" 2>/dev/null | grep -q "watcher finished"; then
    start_once "xrp vp plan watcher" "xrp_vp_plan_watch\.py$" "$CDCX/trading/alerts" \
      "$CDCX/trading/alerts/xrp_vp_plan_watch.stdout" "$BIN/python" xrp_vp_plan_watch.py
  fi
  if ! tail -1 "$CDCX/trading/alerts/xlm_vp_plan_watch.log" 2>/dev/null | grep -q "watcher finished"; then
    start_once "xlm vp plan watcher" "xrp_vp_plan_watch\.py --symbol XLM/USD" "$CDCX/trading/alerts" \
      "$CDCX/trading/alerts/xlm_vp_plan_watch.stdout" "$BIN/python" xrp_vp_plan_watch.py --symbol XLM/USD
  fi
  sleep "${CHECK_S:-60}"
done
