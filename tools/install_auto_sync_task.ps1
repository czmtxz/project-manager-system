param(
    [string]$TaskName = "ProjectManagerGitAutoSync",
    [string]$RepoPath = (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
)

$ErrorActionPreference = "Stop"
$RepoPath = (Resolve-Path $RepoPath).Path
$ScriptPath = Join-Path $RepoPath "tools\auto_sync_to_github.ps1"

if (-not (Test-Path $ScriptPath)) {
    throw "Auto sync script not found: $ScriptPath"
}

Import-Module ScheduledTasks

$argument = "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`" -RepoPath `"$RepoPath`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Automatically commits and pushes local project changes to GitHub." -Force | Out-Host
Start-ScheduledTask -TaskName $TaskName

Write-Host "Auto sync task installed and started: $TaskName"
Write-Host "Repo: $RepoPath"
Write-Host "Log:  $RepoPath\.git\auto-sync.log"
