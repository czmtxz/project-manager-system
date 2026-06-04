# 安装 git post-commit 钩子：每次本地 commit 后自动部署
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$hooksDir = Join-Path $ProjectRoot ".git\hooks"
$hookPath = Join-Path $hooksDir "post-commit"

if (-not (Test-Path (Join-Path $ProjectRoot ".git"))) {
    Write-Host "Not a git repository." -ForegroundColor Red
    exit 1
}

$hookContent = @'
#!/bin/sh
# Auto-deploy after commit (Windows: run via PowerShell)
ROOT="$(git rev-parse --show-toplevel)"
if [ -f "$ROOT/.ssh_deploy_key" ] || [ -n "$DEPLOY_SSH_KEY" ]; then
  powershell.exe -ExecutionPolicy Bypass -NoProfile -File "$ROOT/tools/deploy_to_server.ps1" -Quiet
fi
exit 0
'@

New-Item -ItemType Directory -Force -Path $hooksDir | Out-Null
Set-Content -Path $hookPath -Value $hookContent -Encoding UTF8 -NoNewline
Write-Host "Installed: $hookPath" -ForegroundColor Green
Write-Host "Each git commit will trigger deploy_to_server.ps1 (if SSH key present)."
