# Registers the per-user scheduled task "cdcx-autostart": at Windows logon it
# runs scripts/cdcx_autostart.sh in WSL (hidden), which starts the cdcx Telegram
# bot and the XRP/USD BOS watcher if they are not already running.
# No admin rights needed (current user, interactive logon only).
#   Register:  powershell -ExecutionPolicy Bypass -File scripts\register_cdcx_autostart.ps1
#   Remove:    Unregister-ScheduledTask -TaskName cdcx-autostart -Confirm:$false
#   Run now:   Start-ScheduledTask -TaskName cdcx-autostart

$taskName = "cdcx-autostart"
$distro   = "Ubuntu-26.04"
$script   = "/mnt/c/Users/patch/my-trade/backtrader-repo/scripts/cdcx_autostart.sh"
$user     = "$env:USERDOMAIN\$env:USERNAME"

# conhost --headless: no console window pops up at logon
$action = New-ScheduledTaskAction -Execute "conhost.exe" -Argument "--headless wsl.exe -d $distro -- bash $script"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$trigger.Delay = "PT30S"   # let networking come up first
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description "Start cdcx Telegram bot + XRP BOS watcher in WSL at logon" -Force | Out-Null

$t = Get-ScheduledTask -TaskName $taskName
Write-Output "REGISTERED: $($t.TaskName) state=$($t.State) trigger=AtLogOn($user, +30s) action=conhost.exe $($action.Arguments)"
