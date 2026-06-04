# Cursor hook: agent 完成一轮修改后自动部署到生产服务器
# 失败不阻断 agent（exit 0）
$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$deployScript = Join-Path $ProjectRoot "tools\deploy_to_server.ps1"
$logFile = Join-Path $ProjectRoot ".cursor\deploy-last.log"

function Write-Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

try {
    if (-not (Test-Path $deployScript)) {
        Write-Log "SKIP: deploy script not found"
        exit 0
    }
    $key = Join-Path $ProjectRoot ".ssh_deploy_key"
    if (-not (Test-Path $key)) {
        if (-not $env:DEPLOY_SSH_KEY) {
            Write-Log "SKIP: no .ssh_deploy_key or DEPLOY_SSH_KEY"
            exit 0
        }
    }
    # 消费 stdin（Cursor stop 事件 JSON），避免管道阻塞
    try {
        if ([Console]::In.Peek() -ge 0) {
            $null = [Console]::In.ReadToEnd()
        }
    } catch { }

    Write-Log "START auto-deploy"
    & powershell -ExecutionPolicy Bypass -NoProfile -File $deployScript -Quiet *> $logFile.tmp
    $code = $LASTEXITCODE
    if (Test-Path "$logFile.tmp") {
        Get-Content "$logFile.tmp" | Add-Content $logFile -Encoding UTF8
        Remove-Item "$logFile.tmp" -Force -ErrorAction SilentlyContinue
    }
    Write-Log "END auto-deploy exit=$code"
} catch {
    Write-Log "ERROR: $_"
}
exit 0
