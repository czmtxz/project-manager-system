# Cursor hook: 对话结束后自动 git push + 部署
$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$syncScript = Join-Path $ProjectRoot "tools\auto_git_push_deploy.ps1"
$logFile = Join-Path $ProjectRoot ".cursor\auto-sync.log"

function Write-Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

try {
    try {
        if ([Console]::In.Peek() -ge 0) { $null = [Console]::In.ReadToEnd() }
    } catch { }

    if (-not (Test-Path $syncScript)) {
        Write-Log "SKIP: auto_git_push_deploy.ps1 missing"
        exit 0
    }
    Write-Log "START auto_git_push_deploy"
    & powershell -ExecutionPolicy Bypass -NoProfile -File $syncScript -Quiet
    Write-Log "END auto_git_push_deploy exit=$LASTEXITCODE"
} catch {
    Write-Log "ERROR: $_"
}
exit 0
