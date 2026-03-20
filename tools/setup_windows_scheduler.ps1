# setup_windows_scheduler.ps1 — Create Windows Task Scheduler task to ensure
# WSL2 is running before the daily production cron fires.
#
# Run from an ELEVATED PowerShell prompt:
#   powershell -ExecutionPolicy Bypass -File C:\Projects\biotech_screener\biotech-screener\tools\setup_windows_scheduler.ps1
#
# What it does:
#   1. Creates a task "BiotechScreener_EnsureWSL" that runs at 5:25 PM ET weekdays
#      (5 minutes before the cron job at 5:30 PM)
#   2. The task starts WSL2 Ubuntu, which activates cron
#   3. A second task "BiotechScreener_DailyScreen" at 5:30 PM directly invokes
#      the production script via wsl.exe as a belt-and-suspenders backup

$TaskNameWSL = "BiotechScreener_EnsureWSL"
$TaskNameScreen = "BiotechScreener_DailyScreen"

# --- Task 1: Ensure WSL2 is running (5:25 PM weekdays) ---
$existingWSL = Get-ScheduledTask -TaskName $TaskNameWSL -ErrorAction SilentlyContinue
if ($existingWSL) {
    Write-Host "Removing existing task: $TaskNameWSL"
    Unregister-ScheduledTask -TaskName $TaskNameWSL -Confirm:$false
}

$triggerWSL = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "17:25"
$actionWSL = New-ScheduledTaskAction -Execute "wsl.exe" -Argument "-d Ubuntu -e /bin/bash -c 'echo WSL active at $(date)'"
$settingsWSL = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $TaskNameWSL `
    -Trigger $triggerWSL `
    -Action $actionWSL `
    -Settings $settingsWSL `
    -Description "Wake WSL2 so cron daemon starts before daily biotech screen at 5:30 PM" `
    -RunLevel Highest

Write-Host "Created task: $TaskNameWSL (5:25 PM weekdays)"

# --- Task 2: Direct screen invocation as backup (5:30 PM weekdays) ---
$existingScreen = Get-ScheduledTask -TaskName $TaskNameScreen -ErrorAction SilentlyContinue
if ($existingScreen) {
    Write-Host "Removing existing task: $TaskNameScreen"
    Unregister-ScheduledTask -TaskName $TaskNameScreen -Confirm:$false
}

$triggerScreen = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "17:30"
$actionScreen = New-ScheduledTaskAction -Execute "wsl.exe" -Argument "-d Ubuntu -e /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_daily_production.sh"
$settingsScreen = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $TaskNameScreen `
    -Trigger $triggerScreen `
    -Action $actionScreen `
    -Settings $settingsScreen `
    -Description "Daily biotech production screen via WSL2 (belt-and-suspenders backup to cron)" `
    -RunLevel Highest

Write-Host "Created task: $TaskNameScreen (5:30 PM weekdays)"

Write-Host ""
Write-Host "Done. Two tasks created:"
Write-Host "  1. $TaskNameWSL    — wakes WSL2 at 5:25 PM so cron is active"
Write-Host "  2. $TaskNameScreen — directly runs the screen at 5:30 PM as backup"
Write-Host ""
Write-Host "To verify: Get-ScheduledTask -TaskName 'BiotechScreener_*' | Format-Table TaskName, State, LastRunTime"
Write-Host "To remove: Unregister-ScheduledTask -TaskName '$TaskNameWSL'; Unregister-ScheduledTask -TaskName '$TaskNameScreen'"
