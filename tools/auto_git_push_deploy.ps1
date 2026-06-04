# 工作区有改动时：提交 -> 推送 GitHub -> 部署生产（供 Cursor stop 钩子调用）
param([switch]$Quiet)

$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot
$logFile = Join-Path $ProjectRoot ".cursor\auto-sync.log"

function Write-SyncLog($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $logFile -Value $line -Encoding UTF8
    if (-not $Quiet) { Write-Host $line }
}

function Invoke-Git {
    param([string[]]$GitArgs)
    $out = & git @GitArgs 2>&1
    $code = $LASTEXITCODE
    if ($out) { Write-SyncLog ($out -join "`n") }
    return $code
}

if (-not (Test-Path (Join-Path $ProjectRoot ".git"))) {
    Write-SyncLog "SKIP: not a git repo"
    exit 0
}

$porcelain = & git status --porcelain 2>&1
if (-not $porcelain) {
    Write-SyncLog "SKIP: working tree clean"
    exit 0
}

Write-SyncLog "START git add/commit/push"
Invoke-Git @("add", "-A") | Out-Null
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Invoke-Git @("diff", "--cached", "--quiet")
if ($LASTEXITCODE -eq 0) {
    Write-SyncLog "SKIP: nothing staged"
    exit 0
}

$msg = "Auto sync {0}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
Invoke-Git @("commit", "-m", $msg)
if ($LASTEXITCODE -ne 0) {
    Write-SyncLog "commit failed exit=$LASTEXITCODE"
    exit $LASTEXITCODE
}

Invoke-Git @("push", "origin", "main")
if ($LASTEXITCODE -ne 0) {
    Write-SyncLog "push failed exit=$LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-SyncLog "git push OK"

$deployScript = Join-Path $ProjectRoot "tools\deploy_to_server.ps1"
$key = Join-Path $ProjectRoot ".ssh_deploy_key"
if ((Test-Path $deployScript) -and ((Test-Path $key) -or $env:DEPLOY_SSH_KEY)) {
    Write-SyncLog "START deploy"
    & powershell -ExecutionPolicy Bypass -NoProfile -File $deployScript -Quiet
    Write-SyncLog "END deploy exit=$LASTEXITCODE"
} else {
    Write-SyncLog "SKIP deploy: no script or SSH key"
}

exit 0
