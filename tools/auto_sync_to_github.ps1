param(
    [string]$RepoPath = (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)),
    [int]$DebounceSeconds = 20,
    [int]$PollSeconds = 5,
    [string]$Remote = "origin",
    [string]$Branch = "main"
)

$ErrorActionPreference = "Continue"
$RepoPath = (Resolve-Path $RepoPath).Path
$LogPath = Join-Path $RepoPath ".git\auto-sync.log"

function Write-SyncLog {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Path $LogPath -Value $line -Encoding UTF8
}

function Invoke-Git {
    param([string[]]$Args)
    Push-Location $RepoPath
    try {
        $output = & git @Args 2>&1
        $code = $LASTEXITCODE
        if ($output) { Write-SyncLog ($output -join "`n") }
        return $code
    }
    finally {
        Pop-Location
    }
}

function Test-GitBusy {
    $gitDir = Join-Path $RepoPath ".git"
    return (Test-Path (Join-Path $gitDir "MERGE_HEAD")) -or
           (Test-Path (Join-Path $gitDir "rebase-merge")) -or
           (Test-Path (Join-Path $gitDir "rebase-apply")) -or
           (Test-Path (Join-Path $gitDir "index.lock"))
}

function Sync-Changes {
    if (Test-GitBusy) {
        Write-SyncLog "Skip sync: git operation in progress."
        return
    }

    Push-Location $RepoPath
    try {
        $status = & git status --porcelain 2>$null
        if (-not $status) { return }

        Write-SyncLog "Detected changes. Preparing auto sync."
        & git add -A | Out-Null
        & git diff --cached --quiet
        if ($LASTEXITCODE -eq 0) {
            Write-SyncLog "No staged changes after git add."
            return
        }

        $message = "Auto sync {0}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        & git commit -m $message 2>&1 | ForEach-Object { Write-SyncLog $_ }
        if ($LASTEXITCODE -ne 0) {
            Write-SyncLog "Commit failed."
            return
        }

        & git push $Remote $Branch 2>&1 | ForEach-Object { Write-SyncLog $_ }
        if ($LASTEXITCODE -eq 0) {
            Write-SyncLog "Pushed auto sync commit to $Remote/$Branch."
        } else {
            Write-SyncLog "Push failed. Manual intervention may be required."
        }
    }
    finally {
        Pop-Location
    }
}

Write-SyncLog "Auto sync watcher started for $RepoPath."
Write-SyncLog "DebounceSeconds=$DebounceSeconds PollSeconds=$PollSeconds Remote=$Remote Branch=$Branch"

$lastSignature = ""
$pendingSince = $null

while ($true) {
    Push-Location $RepoPath
    try {
        $signature = (& git status --porcelain 2>$null) -join "`n"
    }
    finally {
        Pop-Location
    }

    if ($signature -and $signature -ne $lastSignature) {
        $lastSignature = $signature
        $pendingSince = Get-Date
        Write-SyncLog "Change signature updated; waiting for debounce."
    }

    if ($pendingSince) {
        $age = (New-TimeSpan -Start $pendingSince -End (Get-Date)).TotalSeconds
        if ($age -ge $DebounceSeconds) {
            $pendingSince = $null
            Sync-Changes
            Push-Location $RepoPath
            try {
                $lastSignature = (& git status --porcelain 2>$null) -join "`n"
            }
            finally {
                Pop-Location
            }
        }
    }

    Start-Sleep -Seconds $PollSeconds
}
